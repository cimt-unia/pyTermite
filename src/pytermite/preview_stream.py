import PIL.Image, PIL.ImageTk
import threading
import tkinter as tk
import subprocess
import asyncio
import math

from pytermite.connection import make_gopro_request, WiredConnection, WirelessConnection

class PreviewStream():
    _active_instance = None  # guards against overlapping preview sessions

    def __init__(self, connection: WirelessConnection | WiredConnection, stop_event, logger):
        if PreviewStream._active_instance is not None:
            logger.warning(
                "A preview stream is already running — ignoring duplicate start request "
                "(this can happen if the start command was triggered twice, e.g. by "
                "pressing Enter again after starting)."
            )
            return

        PreviewStream._active_instance = self
        self.logger = logger
        self.stop_event = stop_event
        self.connection = connection
        self.ips = {}
        
        self.root = tk.Tk()
        self.canvas_size = math.ceil(math.sqrt(len(connection)))
        self.canvas = tk.Canvas(self.root, width=1000, height=1000, bg="white")
        self.canvas.grid(row=self.canvas_size, column=self.canvas_size)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.streams = []
        
        threading.Thread(target=self.preview_start, daemon=True).start()
        
        try:
            self.root.mainloop()
        finally:
            PreviewStream._active_instance = None

    def preview_start(self) -> None:
        
        total_canvas_width = 1000

        for index, connection in enumerate(self.connection):
            self.ips[connection.ip_address] = 8554 + index

        asyncio.run(self.show_streams(total_canvas_width))

    def on_close(self):
        self.stop_event.set()
        self.preview_stop()
        self.root.destroy()
        for stream in self.streams:
            stream.process.kill()

    def preview_stop(self) -> None:
        for ip in self.ips:
            response = make_gopro_request(ip, "gopro/camera/stream/stop")
            
            if response is None or not response.ok:
                self.logger.warning(f"Failed to stop stream for {ip}: {response}")

    async def show_streams(self, total_canvas_width):
        for connection in self.connection:

            response = make_gopro_request(
                connection, f"gopro/camera/stream/start?port={self.ips[connection.ip_address]}"
            )
            if response is None or not response.ok:
                self.logger.warning(
                    f"Failed to start stream for {connection.ip_address}: {response}"
                )

        await asyncio.sleep(0.5)
                
        
        for index, (ip, port) in enumerate(self.ips.items()):
            row, col = divmod(index, self.canvas_size)

            receiver = UDPReceiver(self.canvas, row, col, ip, port, self.canvas_size, total_canvas_width)
            stream = threading.Thread(target=receiver.start, daemon=True)
            stream.start()
            self.streams.append(receiver)

        await asyncio.to_thread(self.stop_event.wait)


class UDPReceiver():
    def __init__(self, canvas, row, col, ip, port, canvas_size, total_canvas_width):
        self.canvas = canvas
        self.row = row
        self.column = col
        self.ip = ip
        self.port = port
        self.canvas_size = canvas_size
        self.total_canvas_width = total_canvas_width
        self.current_img = None
        self.canvas_image_id = None
        self.process = None

    def start(self):
        width = max(self.total_canvas_width // self.canvas_size, 320)
        height = (width * 9) // 16
        frame_size = width * height * 3

        cmd = [
            "ffmpeg",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-f", "mpegts",
            "-i", f"udp://0.0.0.0:{self.port}",
            "-vf", f"scale={width}:{height}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"
        ]

        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        while raw_bytes := self.process.stdout.read(frame_size):
            if len(raw_bytes) != frame_size:
                continue
            image = PIL.Image.frombytes("RGB", (width, height), raw_bytes)

            self.canvas.after(0, self._draw_frame, image, width, height)

    def _draw_frame(self, image, width, height):
        img_tk = PIL.ImageTk.PhotoImage(image)
        self.current_img = img_tk

        x, y = self.column * width, self.row * height

        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(x, y, image=img_tk, anchor="nw")
        else:
            self.canvas.itemconfig(self.canvas_image_id, image=img_tk)