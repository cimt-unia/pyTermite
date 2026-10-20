#  Copyright (c) 2026 by Patrick Braun
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

"""
Tests for pytermite.preview_stream.

None of these tests open a Tk window, start ffmpeg or talk to a camera:
Tk, ffmpeg (create_subprocess_exec), threads and HTTP requests are all faked.
"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import PIL.Image
import pytest

from pytermite import preview_stream
from pytermite.preview_stream import PreviewStream, UDPReceiver

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def fake_response(status_code=200):
    return SimpleNamespace(status_code=status_code, ok=200 <= status_code < 400)


def make_preview(connections, ips=None, canvas_size=1):
    """
    Build a PreviewStream without running __init__.

    __init__ creates a Tk window and blocks in mainloop(), so the methods are
    tested on an instance whose attributes are set by hand.
    """
    ps = object.__new__(PreviewStream)
    ps.logger = MagicMock()
    ps.stop_event = threading.Event()
    ps.connection = connections
    ps.ips = dict(ips or {})
    ps.canvas = MagicMock()
    ps.canvas_size = canvas_size
    ps.root = MagicMock()
    ps.streams = []
    return ps


class FakeConnection:
    def __init__(self, ip):
        self.ip_address = ip


@pytest.fixture
def requests_log(monkeypatch):
    """Replace make_gopro_request; tests set the responses per path."""
    calls = []
    responses = {}

    def _fake(target, path, timeout=10):
        calls.append((target, path))
        result = responses.get(path, fake_response(200))
        # a list means "return these one after another"
        if isinstance(result, list):
            return result.pop(0)
        return result

    monkeypatch.setattr(preview_stream, "make_gopro_request", _fake)
    return SimpleNamespace(calls=calls, responses=responses)


@pytest.fixture(autouse=True)
def reset_active_instance():
    PreviewStream._active_instance = None
    yield
    PreviewStream._active_instance = None


# --------------------------------------------------------------------------- #
# PreviewStream.__init__
# --------------------------------------------------------------------------- #


def test_duplicate_start_is_ignored(monkeypatch):
    tk_called = MagicMock()
    monkeypatch.setattr(preview_stream.tk, "Tk", tk_called)
    PreviewStream._active_instance = object()  # pretend one is running
    logger = MagicMock()

    PreviewStream({FakeConnection("1.2.3.4")}, threading.Event(), logger)

    logger.warning.assert_called_once()
    tk_called.assert_not_called()


def test_init_builds_window_and_clears_guard(monkeypatch):
    root = MagicMock()
    monkeypatch.setattr(preview_stream.tk, "Tk", lambda: root)
    monkeypatch.setattr(preview_stream.tk, "Canvas", MagicMock())
    started = []
    monkeypatch.setattr(
        preview_stream.threading,
        "Thread",
        lambda target, daemon: SimpleNamespace(start=lambda: started.append(target)),
    )

    conns = {FakeConnection(f"10.0.0.{i}") for i in range(5)}
    ps = PreviewStream(conns, threading.Event(), MagicMock())

    assert ps.canvas_size == 3  # ceil(sqrt(5))
    root.protocol.assert_called_once_with("WM_DELETE_WINDOW", ps.on_close)
    root.mainloop.assert_called_once()
    assert started == [ps.preview_start]
    # guard is released once mainloop returns
    assert PreviewStream._active_instance is None


def test_init_releases_guard_if_mainloop_raises(monkeypatch):
    root = MagicMock()
    root.mainloop.side_effect = RuntimeError("boom")
    monkeypatch.setattr(preview_stream.tk, "Tk", lambda: root)
    monkeypatch.setattr(preview_stream.tk, "Canvas", MagicMock())
    monkeypatch.setattr(
        preview_stream.threading,
        "Thread",
        lambda target, daemon: SimpleNamespace(start=lambda: None),
    )

    with pytest.raises(RuntimeError):
        PreviewStream({FakeConnection("1.1.1.1")}, threading.Event(), MagicMock())

    assert PreviewStream._active_instance is None


# --------------------------------------------------------------------------- #
# PreviewStream.preview_start
# --------------------------------------------------------------------------- #


def test_preview_start_assigns_ports_and_runs_show_streams(monkeypatch):
    conns = [FakeConnection("10.0.0.1"), FakeConnection("10.0.0.2")]
    ps = make_preview(conns)
    seen = []

    async def fake_show_streams(width):
        seen.append(width)

    monkeypatch.setattr(ps, "show_streams", fake_show_streams)

    ps.preview_start()

    assert ps.ips == {"10.0.0.1": 8554, "10.0.0.2": 8555}
    assert seen == [1000]


# --------------------------------------------------------------------------- #
# PreviewStream.show_streams
# --------------------------------------------------------------------------- #


@pytest.fixture
def no_receivers(monkeypatch):
    """Don't start real receivers/threads and don't sleep."""
    created = []

    class FakeReceiver:
        def __init__(self, canvas, row, col, ip, port, canvas_size, width):
            self.args = (row, col, ip, port, canvas_size, width)
            self.process = None
            created.append(self)

        def start(self):
            pass

    real_sleep = asyncio.sleep

    async def short_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(preview_stream, "UDPReceiver", FakeReceiver)
    monkeypatch.setattr(preview_stream.asyncio, "sleep", short_sleep)
    return created


@pytest.mark.asyncio
async def test_show_streams_starts_each_camera(requests_log, no_receivers):
    conns = [FakeConnection("10.0.0.1"), FakeConnection("10.0.0.2")]
    ps = make_preview(conns, ips={"10.0.0.1": 8554, "10.0.0.2": 8555}, canvas_size=2)
    ps.stop_event.set()  # return right after setup

    await ps.show_streams(1000)

    assert requests_log.calls == [
        (conns[0], "gopro/camera/stream/start?port=8554"),
        (conns[1], "gopro/camera/stream/start?port=8555"),
    ]
    assert [r.args for r in no_receivers] == [
        (0, 0, "10.0.0.1", 8554, 2, 1000),
        (0, 1, "10.0.0.2", 8555, 2, 1000),
    ]
    assert ps.streams == no_receivers
    ps.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_show_streams_restarts_on_409(requests_log, no_receivers):
    conn = FakeConnection("10.0.0.1")
    ps = make_preview([conn], ips={"10.0.0.1": 8554})
    ps.stop_event.set()
    start = "gopro/camera/stream/start?port=8554"
    requests_log.responses[start] = [fake_response(409), fake_response(200)]

    await ps.show_streams(1000)

    assert [path for _, path in requests_log.calls] == [
        start,
        "gopro/camera/stream/stop",
        start,
    ]
    ps.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, fake_response(500)])
async def test_show_streams_warns_when_start_fails(
    requests_log, no_receivers, response
):
    conn = FakeConnection("10.0.0.1")
    ps = make_preview([conn], ips={"10.0.0.1": 8554})
    ps.stop_event.set()
    requests_log.responses["gopro/camera/stream/start?port=8554"] = response

    await ps.show_streams(1000)

    ps.logger.warning.assert_called_once()
    assert "10.0.0.1" in ps.logger.warning.call_args.args[0]


@pytest.mark.asyncio
async def test_show_streams_waits_for_stop_event(requests_log, no_receivers):
    ps = make_preview([FakeConnection("10.0.0.1")], ips={"10.0.0.1": 8554})

    task = asyncio.create_task(ps.show_streams(1000))
    await asyncio.wait({task}, timeout=0.1)
    assert not task.done()

    ps.stop_event.set()
    await asyncio.wait_for(task, timeout=1)


# --------------------------------------------------------------------------- #
# PreviewStream.preview_stop / on_close
# --------------------------------------------------------------------------- #


def test_preview_stop_requests_stop_for_every_ip(requests_log):
    ps = make_preview([], ips={"10.0.0.1": 8554, "10.0.0.2": 8555})

    ps.preview_stop()

    assert requests_log.calls == [
        ("10.0.0.1", "gopro/camera/stream/stop"),
        ("10.0.0.2", "gopro/camera/stream/stop"),
    ]
    ps.logger.warning.assert_not_called()


def test_preview_stop_warns_on_failure(requests_log):
    ps = make_preview([], ips={"10.0.0.1": 8554})
    requests_log.responses["gopro/camera/stream/stop"] = None

    ps.preview_stop()

    ps.logger.warning.assert_called_once()


def test_on_close_stops_everything(requests_log):
    ps = make_preview([], ips={"10.0.0.1": 8554})
    running = SimpleNamespace(process=MagicMock())
    not_started = SimpleNamespace(process=None)
    ps.streams = [running, not_started]

    ps.on_close()

    assert ps.stop_event.is_set()
    assert requests_log.calls == [("10.0.0.1", "gopro/camera/stream/stop")]
    ps.root.destroy.assert_called_once()
    running.process.kill.assert_called_once()


# --------------------------------------------------------------------------- #
# UDPReceiver
# --------------------------------------------------------------------------- #


def make_receiver(canvas_size=1, row=0, col=0, width=1000):
    return UDPReceiver(MagicMock(), row, col, "10.0.0.1", 8554, canvas_size, width)


@pytest.mark.parametrize(
    "canvas_size, expected",
    [
        (1, (1000, 562)),  # one camera: full width
        (2, (500, 281)),
        (4, (320, 180)),  # 1000 // 4 = 250 -> clamped to the 320 minimum
    ],
)
def test_receiver_start_frame_size_and_command(monkeypatch, canvas_size, expected):
    receiver = make_receiver(canvas_size=canvas_size)
    captured = {}

    async def fake_read_frames(cmd, width, height, frame_size):
        captured.update(cmd=cmd, size=(width, height), frame_size=frame_size)

    monkeypatch.setattr(receiver, "_read_frames", fake_read_frames)

    receiver.start()

    width, height = expected
    assert captured["size"] == expected
    assert captured["frame_size"] == width * height * 3
    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "udp://0.0.0.0:8554" in cmd
    assert f"scale={width}:{height}" in cmd
    assert cmd[-1] == "pipe:1"


def fake_ffmpeg(monkeypatch, stdout_bytes):
    """Make create_subprocess_exec return a process whose stdout yields bytes."""
    launched = []

    async def _fake_exec(*cmd, **kwargs):
        reader = asyncio.StreamReader()
        reader.feed_data(stdout_bytes)
        reader.feed_eof()
        launched.append(cmd)
        return SimpleNamespace(stdout=reader)

    monkeypatch.setattr(preview_stream.asyncio, "create_subprocess_exec", _fake_exec)
    return launched


@pytest.mark.asyncio
async def test_read_frames_schedules_each_complete_frame(monkeypatch):
    width, height = 4, 2
    frame_size = width * height * 3
    # two full frames plus a partial one that must be dropped
    data = bytes([10]) * frame_size + bytes([20]) * frame_size + b"\x00" * 5
    launched = fake_ffmpeg(monkeypatch, data)
    receiver = make_receiver()

    await receiver._read_frames(["ffmpeg", "x"], width, height, frame_size)

    assert launched == [("ffmpeg", "x")]
    assert receiver.canvas.after.call_count == 2
    images = [c.args[2] for c in receiver.canvas.after.call_args_list]
    assert [img.getpixel((0, 0)) for img in images] == [(10, 10, 10), (20, 20, 20)]
    for c in receiver.canvas.after.call_args_list:
        delay, func, _img, w, h = c.args
        assert (delay, func, w, h) == (0, receiver._draw_frame, width, height)


@pytest.mark.asyncio
async def test_read_frames_returns_without_stdout(monkeypatch):
    async def _fake_exec(*cmd, **kwargs):
        return SimpleNamespace(stdout=None)

    monkeypatch.setattr(preview_stream.asyncio, "create_subprocess_exec", _fake_exec)
    receiver = make_receiver()

    await receiver._read_frames(["ffmpeg"], 4, 2, 24)

    receiver.canvas.after.assert_not_called()


def test_draw_frame_creates_then_updates_image(monkeypatch):
    photos = []

    def fake_photo(image):
        photos.append(image)
        return f"photo{len(photos)}"

    monkeypatch.setattr(preview_stream.PIL.ImageTk, "PhotoImage", fake_photo)
    receiver = make_receiver(row=1, col=2)
    receiver.canvas.create_image.return_value = 42
    img = PIL.Image.new("RGB", (320, 180))

    receiver._draw_frame(img, 320, 180)
    receiver._draw_frame(img, 320, 180)

    receiver.canvas.create_image.assert_called_once_with(
        640, 180, image="photo1", anchor="nw"
    )
    receiver.canvas.itemconfig.assert_called_once_with(42, image="photo2")
    assert receiver.canvas_image_id == 42
    # reference must be kept, otherwise Tk shows an empty image
    assert receiver.current_img == "photo2"
