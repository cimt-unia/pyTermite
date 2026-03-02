#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import types
from dataclasses import dataclass

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@dataclass
class DummyHTTPResponse:
    data: dict | types.SimpleNamespace


class DummyHTTPCommand:
    def __init__(self, camera_info=None, camera_state=None):
        self._camera_info = camera_info or {}
        self._camera_state = camera_state or {}

    async def get_camera_info(self):
        return types.SimpleNamespace(data=types.SimpleNamespace(**self._camera_info))

    async def get_camera_state(self):
        return types.SimpleNamespace(data=self._camera_state)


class DummyWiredConnection:
    def __init__(
        self, serial: str, name: str | None = None, camera_info=None, camera_state=None
    ):
        self.identifier = serial
        self.serial = serial
        self._name = name
        self.http_command = DummyHTTPCommand(camera_info or {}, camera_state or {})
        self.open_called = False
        self.closed = False

    async def open(self, retries=1, timeout=1):
        self.open_called = True

    async def close(self):
        self.closed = True

    @property
    def name(self):
        # Provide a synchronous `.name` so tests that don't await it still work
        if self._name:
            return self._name
        # Try to synchronously fall back to identifier if no cached name
        return self.identifier


@pytest.fixture
def dummy_wired_connection_factory():
    def _factory(
        serial: str, name: str | None = None, camera_info=None, camera_state=None
    ):
        return DummyWiredConnection(
            serial=serial, name=name, camera_info=camera_info, camera_state=camera_state
        )

    return _factory
