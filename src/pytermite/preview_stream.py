import requests
import tkinter as tk
import threading

class PreviewStream():
    def __init__(self, serials, stop_event, logger):
        self.logger = logger
        self.serials = serials
        self.stop_event = stop_event
        self.ports = [int(f"855{i}") for i in range(len(self.serials))]
        self.ips = {f"172.2{serial_nr[-3]}.1{serial_nr[-2:]}.51:8080": self.ports[idx] for idx, serial_nr in enumerate(self.serials)}
        self.root = tk.Tk()
        self.canvas_size = math.ceil(math.sqrt(len(serials)))
        self.canvas = tk.grid(root, row=canvas_size, column=canvas_size)
        threading.Thread(target=root.mainloop, daemon=True).start()

    def preview_start(self) -> None:
        for ip, port in self.ips.items():
            url = f"http://{ip}/gopro/camera/stream/start?port={port}"
            response = requests.request("GET", url)
        asyncio.run(self.show_streams())

    def preview_stop(self) -> None:
        for ip in self.ips:
            url = f"http://{ip}/gopro/camera/stream/stop"
            response = requests.request("GET", url)
    
    async def show_streams(self):
        loop = asyncio.get_event_loop()
        for ip, port in self.ips.items():
            row, col = divmod(port % 10, 3) 
            threading.Thread(target=UDPReceiver, args=(self.canvas, row, col, ip, port, canvas_size), daemon=True).start()
        await self.stop_event.wait()


class UDPReceiver():
    def __init__(self, canvas, row, col, ip, port, canvas_size):
        super().__init__()
        self.canvas = canvas
        self.row = row
        self.column = col
        self.ip = ip
        self.port = port
        self.canvas_size = canvas_size
        self._run()
    
    def _run(self):
        #TODO check whether duplicating this (width, height, framesize) inside loop make it responsive to window changes during runtime
        width = self.canvas.winfo_width() / canvas_size
        height = (width * 9) / 16
        frame_size = width * height * 3
        process = subprocess.Popen(["ffmpeg", "-i", f"udp://{self.ip}:{self.port}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE)
        while raw_bytes := process.stdout.read(frame_size):
            image = PIL.Image.frombytes("RGB", (self.width, self.height), raw_bytes)
            imageTk = ImageTk.PhotoImage(image)
            canvas.after(0, lambda: canvas.create_image(self.column * width, self.row * height, image=imageTk))