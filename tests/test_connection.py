#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio

import pytest

from pytermite import connection


@pytest.mark.asyncio
async def test_create_wired_gopros_from_dict(monkeypatch):
    # Use real WiredConnection but monkeypatch its constructor to a simple object
    class FakeWired:
        def __init__(self, serial=None):
            self.serial = serial
            self.identifier = serial
            self._name = None

    monkeypatch.setattr(connection, "WiredConnection", FakeWired)
    inp = {"camA": "S1", "camB": "S2"}
    g = connection.create_wired_gopros(inp)
    assert set(g.keys()) == set(inp.keys())
    assert all(isinstance(v, FakeWired) for v in g.values())


@pytest.mark.asyncio
async def test_create_wired_gopros_from_set(monkeypatch):
    class FakeWired:
        def __init__(self, serial=None):
            self.serial = serial
            self.identifier = serial

    monkeypatch.setattr(connection, "WiredConnection", FakeWired)
    inp = {"S1", "S2"}
    g = connection.create_wired_gopros(inp)
    assert set(g.keys()) == inp


@pytest.mark.asyncio
async def test_connect_and_close_gopros(monkeypatch):
    class FakeWired:
        def __init__(self, serial):
            self.identifier = serial
            self.serial = serial
            self.open_called = False
            self.closed = False

        async def open(self, retries=1, timeout=1):
            self.open_called = True

        async def close(self):
            self.closed = True

        @property
        async def name(self):
            return self.identifier

    monkeypatch.setattr(connection, "WiredConnection", FakeWired)
    gopros = {"a": FakeWired("S1"), "b": FakeWired("S2")}

    collected = [gp async for gp in connection.connect_gopros(gopros)]

    assert len(collected) == 2
    await connection.close_gopros(gopros)
    assert all(v.closed for v in gopros.values())


@pytest.mark.asyncio
async def test_scan_for_gopros_cancels_interrupt_waiter_on_timeout(monkeypatch):
    cancelled = asyncio.Event()

    async def fake_scan_for_gopros_usb():
        await asyncio.Event().wait()

    async def fake_wait_for_user_interrupt():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(connection, "scan_for_gopros_usb", fake_scan_for_gopros_usb)
    monkeypatch.setattr(
        connection, "wait_for_user_interrupt", fake_wait_for_user_interrupt
    )

    gopros, bles = await connection.scan_for_gopros(waiting_time=0.01)

    assert gopros == set()
    assert bles == set()
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_scan_for_gopros_can_skip_usb_scan(monkeypatch):
    usb_called = asyncio.Event()
    ble_called = asyncio.Event()

    async def fake_scan_for_gopros_usb():
        usb_called.set()
        await asyncio.Event().wait()

    async def fake_scan_for_gopros_ble():
        ble_called.set()
        await asyncio.Event().wait()

    async def fake_wait_for_user_interrupt():
        await asyncio.Event().wait()

    monkeypatch.setenv("PYTERMITE_BLUETOOTH_AVAILABLE", "true")
    monkeypatch.setattr(connection, "scan_for_gopros_usb", fake_scan_for_gopros_usb)
    monkeypatch.setattr(connection, "scan_for_gopros_ble", fake_scan_for_gopros_ble)
    monkeypatch.setattr(
        connection, "wait_for_user_interrupt", fake_wait_for_user_interrupt
    )

    gopros, bles = await connection.scan_for_gopros(
        waiting_time=0.01, bluetooth=True, usb=False
    )

    assert gopros == set()
    assert bles == set()
    assert not usb_called.is_set()
    assert ble_called.is_set()


# @pytest.mark.asyncio
# async def test_scan_for_gopros_usb_finds_devices(monkeypatch):
#     # simulate find_first_ip_addr returning an object with name
#     async def fake_find(service, timeout=2):
#         class R:
#             def __init__(self, name):
#                 self.name = name
#
#         # after first call, set INTERRUPT and return
#         connection.GOPROS = set()
#         return R("S1234.local")
#
#     monkeypatch.setattr(connection, "find_first_ip_addr", fake_find)
#     connection.INTERRUPT = False
#     res = await connection.scan_for_gopros_usb()
#     assert "S1234" in res
