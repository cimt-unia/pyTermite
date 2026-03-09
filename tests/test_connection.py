#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

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
    # create dummy gopro objects with open and close
    class D:
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

    gopros = {"a": D("S1"), "b": D("S2")}

    collected = [gp async for gp in connection.connect_gopros(gopros)]

    assert len(collected) == 2
    # test close
    await connection.close_gopros(gopros)
    assert all(v.closed for v in gopros.values())


@pytest.mark.asyncio
async def test_scan_for_gopros_usb_finds_devices(monkeypatch):
    # simulate find_first_ip_addr returning an object with name
    async def fake_find(service, timeout=2):
        class R:
            def __init__(self, name):
                self.name = name

        # after first call, set INTERRUPT and return
        connection.GOPROS = set()
        connection.INTERRUPT = True
        return R("S1234.local")

    monkeypatch.setattr(connection, "find_first_ip_addr", fake_find)
    connection.INTERRUPT = False
    res = await connection.scan_for_gopros_usb()
    assert "S1234" in res
