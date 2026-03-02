#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

from types import SimpleNamespace

import pytest

from pytermite import commands


class DummyResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class DummyAiohttpSession:
    def __init__(self, urls_collected):
        self.urls = urls_collected

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        # record URL and return a dummy response-like object
        self.urls.append(url)

        class R:
            pass

        return R()


@pytest.mark.asyncio
async def test_get_preset_status(monkeypatch, dummy_wired_connection_factory):
    conn = dummy_wired_connection_factory("SER1", name="cam1")
    # patch requests.request
    monkeypatch.setattr(
        commands,
        "requests",
        SimpleNamespace(request=lambda *_: DummyResp({"presets": 1})),
    )
    res = await commands.get_preset_status({conn})
    # the result keys are connection.name values which in our dummy is
    # 'cam1' via name property
    assert any(v.get("presets") == 1 for v in res.values())


@pytest.mark.asyncio
async def test_camera_shutter_no_gopros():
    # calling with empty set should simply return without exception
    res = await commands.camera_shutter(set(), mode="start")
    assert res is None


@pytest.mark.asyncio
async def test_camera_shutter_calls_urls(monkeypatch, dummy_wired_connection_factory):
    urls = []

    class CS:
        def __init__(self):
            pass

        async def __aenter__(self):
            return DummyAiohttpSession(urls)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(commands, "aiohttp", SimpleNamespace(ClientSession=CS))

    conn = dummy_wired_connection_factory("SER2", name="cam2")
    await commands.camera_shutter({conn}, mode="start")
    # ensure URL was constructed
    assert any("/shutter/start" in u for u in urls)
