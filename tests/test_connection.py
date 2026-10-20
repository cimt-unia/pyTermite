#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio

import pytest

from pytermite import connection

from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

class FakeWired:
    def __init__(self, serial=None):
        self.serial = serial
        self.identifier = serial
        self._name = None

class FakeWireless:
    def __init__(self, target, interfaces, keep_alive_interval, maintain_state, cohn_db):
        self.identifier = target

@pytest.mark.asyncio
async def test_create_wired_gopros_from_dict(monkeypatch):
    # Use real WiredConnection but monkeypatch its constructor to a simple object

    monkeypatch.setattr(connection, "WiredConnection", FakeWired)
    inp = {"camA": "S1", "camB": "S2"}
    g = connection.create_wired_gopros(inp)
    assert set(g.keys()) == set(inp.keys())
    assert all(isinstance(v, FakeWired) for v in g.values())


@pytest.mark.asyncio
async def test_create_wireless_gopros_from_dict(monkeypatch):
    
    monkeypatch.setattr(connection, "WirelessConnection", FakeWireless)
    inp = {"camA": "S1", "camB": "S2"}
    g = connection.create_wireless_gopros(inp)
    assert set(g.keys()) == set(inp.keys())
    assert all(isinstance(v, FakeWireless) for v in g.values())


@pytest.mark.asyncio
async def test_create_wired_gopros_from_set(monkeypatch):

    monkeypatch.setattr(connection, "WiredConnection", FakeWired)
    inp = {"S1", "S2"}
    g = connection.create_wired_gopros(inp)
    assert set(g.keys()) == inp


@pytest.mark.asyncio
async def test_create_wireless_gopros_from_set(monkeypatch):

    monkeypatch.setattr(connection, "WirelessConnection", FakeWireless)
    inp = {"S1", "S2"}
    g = connection.create_wireless_gopros(inp)
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

    class FakeWireless:
        def __init__(self, target, interfaces=None, keep_alive_interval=None, maintain_state=None, cohn_db=None):
            self.identifier = target
            self.is_ble_connected = True
            self._ble = True
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
    monkeypatch.setattr(connection, "WirelessConnection", FakeWireless)
    gopros = {"a": FakeWired("S1"), "b": FakeWired("S2"), "c": FakeWireless("S3"), "d": FakeWireless("S4")}

    collected = [gp async for gp in connection.connect_gopros(gopros)]

    assert len(collected) == 4
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


@pytest.mark.asyncio
async def test_make_gopro_request(monkeypatch):
    class FakeWired:
        def __init__(self, serial):
            self.identifier = serial
            self.serial = serial
            self.open_called = False
            self.closed = False
            self.ip_address = "172.16.0.1"

    class FakeWireless:

        class FakeCohn:

            class FakeCredentials:

                def __init__(self):
                    self.certificate = "fake_cert"
                    self.username = "fake_user"
                    self.password = "fake_pass"

            def __init__(self):
                self.credentials = self.FakeCredentials()

        def __init__(self, target, interfaces=None, keep_alive_interval=None, maintain_state=None, cohn_db=None):
            self.identifier = target
            self.is_ble_connected = True
            self._ble = True
            self.open_called = False
            self.closed = False
            self.ip_address = "192.168.0.10"
            self.cohn = self.FakeCohn()

    monkeypatch.setattr(connection, "WiredConnection", FakeWired)
    monkeypatch.setattr(connection, "WirelessConnection", FakeWireless)
    gopros = {"a": FakeWired("S1"), "b": FakeWireless("S2"), "c": "192.168.0.20", "d": int(5)}

    for gp in gopros.values():
        assert connection.make_gopro_request(gp, "/status", timeout=0.01) is None


@pytest.mark.asyncio
async def test_load_cohn_identifiers(monkeypatch, tmp_path):
    json_file1 = tmp_path / "identifiers.json"
    json_file1.write_text(
        '{"_default": {'
        '"1": {"serial": "S1"}, '
        '"2": {"serial": "S2"}, '
        '"3": {"serial": "S3"}'
        '}}'
    )

    json_file2 = tmp_path / "identifiers2.json"
    json_file2.write_text(
        '"_default": {'
        '"1": {"serial": "S1"}, '
        '"2": {"serial": "S2"}, '
        '"3": {"serial": "S3"}'
        '}}'
    )

    loaded_identifiers1 = connection.load_cohn_identifiers(str(json_file1))
    loaded_identifiers2 = connection.load_cohn_identifiers(str(json_file2))
    assert set(loaded_identifiers1) == {"S1", "S2", "S3"}
    assert set(loaded_identifiers2) == set()


@pytest.mark.asyncio
async def test_create_cohn_gopros(monkeypatch):
    class FakeWireless:

        class FakeCohn:

            class FakeCredentials:

                def __init__(self):
                    self.certificate = "fake_cert"
                    self.username = "fake_user"
                    self.password = "fake_pass"

            def __init__(self):
                self.credentials = self.FakeCredentials()

        def __init__(self, target, interfaces=None, keep_alive_interval=None, maintain_state=None, cohn_db=None):
            self.identifier = target
            self.is_ble_connected = True
            self._ble = True
            self.open_called = False
            self.closed = False
            self.ip_address = "192.168.0.10"

    monkeypatch.setattr(connection, "WirelessConnection", FakeWireless)
    identifiers = {"camA": "S1", "camB": "S2"}
    cohn_db = "temp_path"
    gopros = connection.create_cohn_gopros(identifiers, cohn_db)
    assert set(gopros.keys()) == set(identifiers.keys())
    assert all(isinstance(v, FakeWireless) for v in gopros.values())


@pytest.mark.asyncio
async def test_connect_gopros_wireless_success(monkeypatch):

    class FakeStatus:
        def __init__(self):
            self.status = "ok"
            self.state = "ready"

    class FakeGoProResp:
        def __init__(self):
            self.data = FakeStatus()

    class FakeResult:
        def __init__(self):
            self.success = True

    class FakeAccessPoint:
        async def connect(self, ssid, password):
            return FakeResult()

    class FakeCredentials:
        def __init__(self):
            self.certificate = "fake_cert"
            self.username = "fake_user"
            self.password = "fake_pass"
            self.ip_address = "192.168.0.30"

    class FakeCohn:
        def __init__(self):
            self.credentials = FakeCredentials()

        async def configure(self, force_reprovision, timeout):
            return FakeResult()

    class FakeBleCommand:
        async def cohn_get_status(self, register):
            return FakeGoProResp()

    class FakeWireless:
        def __init__(self, target, interfaces=None, keep_alive_interval=None, maintain_state=None, cohn_db=None):
            self.identifier = target
            self.is_ble_connected = True
            self._ble = True
            self.open_called = False
            self.closed = False
            self._is_open = True
            
            self.ble_command = FakeBleCommand()
            self.cohn = FakeCohn()
            self.access_point = FakeAccessPoint()

        async def open(self, retries=1, timeout=1):
            self.open_called = True

        async def _close_ble(self):
            self.closed = True

    monkeypatch.setattr(connection, "WirelessConnection", FakeWireless)
    gopros = {"a": FakeWireless("S1"), "b": FakeWireless("S2")}

    yielded_gopros = [
        gp async for gp in connection.connect_gopros_wireless(
            gopros, ssid="test_ssid", password="test_pass"
        )
    ]
    assert set(yielded_gopros) == set(gopros.values())

@pytest.fixture
def fake_open_connection(monkeypatch):
    calls = []

    async def _fake(host, port, *args, **kwargs):
        calls.append((host, port))
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        return MagicMock(), writer  # (reader, writer)

    monkeypatch.setattr(connection.asyncio, "open_connection", _fake)
    return calls

@pytest.mark.asyncio
async def test_connect_gopros_cohn(fake_open_connection):
    class FakeHttpCommand:
        async def get_camera_state(self):
            return MagicMock()

    class FakeWireless:
        def __init__(self, ip):
            self.cohn = SimpleNamespace(credentials=SimpleNamespace(ip_address=ip))
            self.http_command = FakeHttpCommand()
            self.open_called = False

        async def open(self, retries=1, timeout=1):
            self.open_called = True

    gopros = {"a": FakeWireless("192.168.0.30"), "b": FakeWireless("192.168.0.31")}

    yielded = [gp async for gp in connection.connect_gopros_cohn(gopros)]

    assert yielded == list(gopros.values())
    assert all(gp.open_called for gp in gopros.values())
    assert fake_open_connection == [("192.168.0.30", 443), ("192.168.0.31", 443)]

@pytest.mark.asyncio
async def test_scan_for_gopros_ble(monkeypatch):
    # adds devices to global BLES
    BLES = None

    assert connection.scan_for_gopros_ble()


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
