#  Copyright (c) 2026 by Patrick Braun, Jonas Rostan
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

"""Live preview of GoPro camera streams in a Tk window."""

import asyncio
import math
import threading
import tkinter as tk
from screeninfo import get_monitors
from multiprocessing.synchronize import Event as SyncEvent

import PIL.Image
import PIL.ImageTk
import structlog

from pytermite.connection import WiredConnection, WirelessConnection, make_gopro_request


class PreviewStream:
    """
    Show the live preview streams of several GoPros in one window.

    Only one instance can run at a time; creating another while one is active
    logs a warning and returns without starting a preview.

    Parameters
    ----------
    connection : set of WiredConnection or WirelessConnection
        Connections whose streams should be shown.
    stop_event : multiprocessing.synchronize.Event
        Event that, when set, stops the preview.
    logger : structlog.BoundLogger
        Logger used for status and error messages.
    """

    # guards against overlapping preview sessions
    _active_instance: "PreviewStream | None" = None

    def __init__(
        self,
        connection: set[WiredConnection | WirelessConnection],
        stop_event: SyncEvent,
        logger: structlog.BoundLogger,
    ) -> None:
        if PreviewStream._active_instance is not None:
            logger.warning(
                "A preview stream is already running — ignoring duplicate start "
                "request (this can happen if the start command was triggered twice, "
                "e.g. by pressing Enter again after starting)."
            )
            return

        PreviewStream._active_instance = self
        self.logger = logger
        self.stop_event = stop_event
        self.connection = connection
        self.ips: dict[str, int] = {}

        self.root = tk.Tk()
        self.canvas_size = min(math.ceil(math.sqrt(len(connection))), 3)
        canvas_width, canvas_height, cam_width, cam_height = self.get_canvas_resolution(200)
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.canvas = tk.Canvas(self.root, width=canvas_width, height=canvas_height, bg="white")
        self.canvas.grid(row=0, column=0)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.streams: list[UDPReceiver] = []

        threading.Thread(target=self.preview_start, daemon=True).start()

        try:
            self.root.mainloop()
        finally:
            PreviewStream._active_instance = None

    def preview_start(self) -> None:
        """
        Assign a UDP port to each camera and start the streams.

        Runs the asynchronous stream setup in its own event loop.
        """
        for index, connection in enumerate(self.connection):
            self.ips[connection.ip_address] = 8554 + index

        asyncio.run(self.show_streams())

    def on_close(self) -> None:
        """
        Stop all streams and close the preview window.

        Sets the stop event, stops the cameras' streams, destroys the window and
        kills any ffmpeg processes still running.
        """
        self.stop_event.set()
        self.preview_stop()
        self.root.destroy()
        for stream in self.streams:
            stream.process.kill() if stream.process else None

    def preview_stop(self) -> None:
        """Ask every camera to stop its stream and log failures."""
        for ip in self.ips:
            response = make_gopro_request(ip, "gopro/camera/stream/stop")

            if response is None or not response.ok:
                self.logger.warning(f"Failed to stop stream for {ip}: {response}")

    def get_canvas_resolution(self, margin:int=0):
        monitors = get_monitors()
        primary = next((m for m in monitors if m.is_primary), monitors[0])
        cam_width = (primary.width - margin) // self.canvas_size
        cam_height = (cam_width * 9) // 16
        return cam_width * self.canvas_size, cam_height * ((len(self.connection) + 2) // 3), cam_width, cam_height

    async def show_streams(self) -> None:
        """
        Start the cameras' streams and display them until the stop event is set.
        """
        for connection in self.connection:
            response = make_gopro_request(
                connection,
                f"gopro/camera/stream/start?port={self.ips[connection.ip_address]}",
            )
            if response and response.status_code == 409:
                # If a stream is already running, stop it first
                _ = make_gopro_request(connection, "gopro/camera/stream/stop")
                response = make_gopro_request(
                    connection,
                    f"gopro/camera/stream/start?port={self.ips[connection.ip_address]}",
                )
            if response is None or not response.ok:
                self.logger.warning(
                    f"Failed to start stream for {connection.ip_address}: {response}"
                )

        await asyncio.sleep(0.5)

        for index, (ip, port) in enumerate(self.ips.items()):
            row, col = divmod(index, self.canvas_size)

            self.logger.debug(f"Starting new Receiver for port {port}")
            receiver = UDPReceiver(
                self.canvas, row, col, ip, port, self.cam_width, self.cam_height
            )
            stream = threading.Thread(target=receiver.start, daemon=True)
            stream.start()
            self.streams.append(receiver)

        await asyncio.to_thread(self.stop_event.wait)


class UDPReceiver:
    """
    Receive an MPEG-TS UDP stream via ffmpeg and draw it onto a canvas cell.

    Parameters
    ----------
    canvas : tkinter.Canvas
        Canvas the frames are drawn on.
    row : int
        Row of the cell on the canvas grid.
    col : int
        Column of the cell on the canvas grid.
    ip : str
        IP address of the camera streaming to this receiver.
    port : int
        UDP port to listen on.
    cam_width : int
        Width in pixels reserved for this camera on the canvas.
    cam_height : int
        Height in pixels reserved for this camera on the canvas.
    """

    def __init__(
        self,
        canvas: tk.Canvas,
        row: int,
        col: int,
        ip: str,
        port: int,
        cam_width: int,
        cam_height: int,
    ) -> None:
        self.canvas = canvas
        self.row = row
        self.column = col
        self.ip = ip
        self.port = port
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.current_img: PIL.ImageTk.PhotoImage | None = None
        self.canvas_image_id: int | None = None
        self.process: asyncio.subprocess.Process | None = None

    def start(self) -> None:
        """
        Start ffmpeg and draw decoded frames until the stream ends.

        Frames are read as raw RGB from ffmpeg's stdout and scheduled for drawing
        on the Tk main loop.
        """
        width = self.cam_width
        height = self.cam_height
        frame_size = width * height * 3

        cmd = [
            "ffmpeg",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-f",
            "mpegts",
            "-i",
            f"udp://0.0.0.0:{self.port}",
            "-vf",
            f"scale={width}:{height}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]

        asyncio.run(self._read_frames(cmd, width, height, frame_size))

    async def _read_frames(
        self, cmd: list[str], width: int, height: int, frame_size: int
    ) -> None:
        """
        Run ffmpeg and schedule each complete frame from its stdout for drawing.

        Parameters
        ----------
        cmd : list of str
            Command calling ffmpeg that writes raw RGB frames to stdout.
        width : int
            Width of each frame in pixels.
        height : int
            Height of each frame in pixels.
        frame_size : int
            Size of one raw RGB frame in bytes.
        """
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if self.process.stdout is None:
            return

        while True:
            try:
                raw_bytes = await self.process.stdout.readexactly(frame_size)
            except asyncio.IncompleteReadError:
                break

            image = PIL.Image.frombytes("RGB", (width, height), raw_bytes)

            self.canvas.after(0, self._draw_frame, image, width, height)

    def _draw_frame(self, image: PIL.Image.Image, width: int, height: int) -> None:
        """
        Draw a frame into this receiver's cell of the canvas.

        Parameters
        ----------
        image : PIL.Image.Image
            Frame to draw.
        width : int
            Width of the frame in pixels.
        height : int
            Height of the frame in pixels.
        """
        img_tk = PIL.ImageTk.PhotoImage(image)
        self.current_img = img_tk

        x, y = self.column * width, self.row * height

        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(
                x, y, image=img_tk, anchor="nw"
            )
        else:
            self.canvas.itemconfig(self.canvas_image_id, image=img_tk)
