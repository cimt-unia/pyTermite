#  Copyright (c) 2026 by Jonas Rostan
#
#  SPDX-License-Identifier: BSD-3-Clause

"""
Tests for pytermite.fetch_data.

No camera, network or real worker processes are used:
- make_gopro_request is replaced by a fake that answers per request path,
- multiprocessing.Pool is replaced by an in-process pool,
- time.sleep is a no-op,
- FETCH_RECORDINGS and all save paths point into pytest's tmp_path, so the
  real fetch_recordings.json and ~/Downloads are never touched.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pytermite import fetch_data

# --------------------------------------------------------------------------- #
# Fakes and fixtures
# --------------------------------------------------------------------------- #


class FakeConnection:
    def __init__(self, identifier):
        self._identifier = identifier


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self._content = content

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


class FakePool:
    """Runs starmap in the current process instead of spawning workers."""

    def __init__(self, processes=None):
        self.processes = processes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starmap(self, func, tasks):
        return [func(*task) for task in tasks]


@pytest.fixture(autouse=True)
def recordings_file(monkeypatch, tmp_path):
    """Redirect the JSON bookkeeping file into tmp_path for every test."""
    path = tmp_path / "fetch_recordings.json"
    monkeypatch.setattr(fetch_data, "FETCH_RECORDINGS", path)
    return path


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetch_data.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


@pytest.fixture
def fake_pool(monkeypatch):
    pools = []

    def _pool(processes=None):
        pool = FakePool(processes)
        pools.append(pool)
        return pool

    monkeypatch.setattr(fetch_data.multiprocessing, "Pool", _pool)
    return pools


@pytest.fixture
def requests_log(monkeypatch):
    """
    Fake make_gopro_request.

    ``handlers`` maps (identifier, path) -> FakeResponse | None | list.
    A list is consumed one item per call (for retry tests).
    Unknown requests return None (= request failed).
    """
    calls = []
    handlers = {}

    def _fake(connection, path, timeout=10):
        key = (connection._identifier, path)
        calls.append(key)
        result = handlers.get(key)
        if isinstance(result, list):
            return result.pop(0) if result else None
        return result

    monkeypatch.setattr(fetch_data, "make_gopro_request", _fake)
    return SimpleNamespace(calls=calls, handlers=handlers)


def write_entries(path, entries):
    path.write_text(json.dumps(entries))


def read_entries(path):
    return json.loads(path.read_text())


def entry(n):
    return {"folder": "100GOPRO", "file": f"GX0{n}.MP4"}


def info_path(e):
    return f"gopro/media/info?path={e['folder']}/{e['file']}"


def video_path(e):
    return f"videos/DCIM/{e['folder']}/{e['file']}"


# --------------------------------------------------------------------------- #
# _get_saved_entries / _save_entries
# --------------------------------------------------------------------------- #


def test_get_saved_entries_missing_file_returns_empty(recordings_file):
    assert not recordings_file.exists()
    assert fetch_data._get_saved_entries() == {}
    assert not recordings_file.exists()  # reading must not create it


def test_save_and_load_roundtrip(recordings_file):
    data = {"1234": [entry(1), entry(2)]}
    fetch_data._save_entries(data)
    assert read_entries(recordings_file) == data
    assert fetch_data._get_saved_entries() == data


# --------------------------------------------------------------------------- #
# fetch_filenames
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("gopros", [None, set()])
def test_fetch_filenames_without_gopros_does_nothing(
    gopros, requests_log, recordings_file
):
    fetch_data.fetch_filenames(gopros)

    assert requests_log.calls == []
    assert not recordings_file.exists()


def test_fetch_filenames_saves_new_camera(requests_log, recordings_file):
    cam = FakeConnection("1234")
    requests_log.handlers[("1234", "gopro/media/last_captured")] = FakeResponse(
        payload=entry(1)
    )

    fetch_data.fetch_filenames({cam})

    assert read_entries(recordings_file) == {"1234": [entry(1)]}


def test_fetch_filenames_appends_to_existing(requests_log, recordings_file):
    write_entries(recordings_file, {"1234": [entry(1)], "9999": [entry(7)]})
    cam = FakeConnection("1234")
    requests_log.handlers[("1234", "gopro/media/last_captured")] = FakeResponse(
        payload=entry(2)
    )

    fetch_data.fetch_filenames({cam})

    assert read_entries(recordings_file) == {
        "1234": [entry(1), entry(2)],
        "9999": [entry(7)],  # other cameras untouched
    }


@pytest.mark.parametrize("response", [None, FakeResponse(status_code=500)])
def test_fetch_filenames_skips_failed_camera(response, requests_log, recordings_file):
    ok_cam, bad_cam = FakeConnection("1111"), FakeConnection("2222")
    requests_log.handlers[("1111", "gopro/media/last_captured")] = FakeResponse(
        payload=entry(1)
    )
    requests_log.handlers[("2222", "gopro/media/last_captured")] = response

    fetch_data.fetch_filenames({ok_cam, bad_cam})

    assert read_entries(recordings_file) == {"1111": [entry(1)]}


def test_fetch_filenames_all_failed_writes_nothing(requests_log, recordings_file):
    fetch_data.fetch_filenames({FakeConnection("1111")})

    assert not recordings_file.exists()


# --------------------------------------------------------------------------- #
# _fetch_recoding
# --------------------------------------------------------------------------- #


def test_fetch_recoding_writes_file(requests_log, tmp_path):
    cam = FakeConnection("1234")
    content = b"x" * 20000  # several 8192-byte chunks
    requests_log.handlers[("1234", "videos/DCIM/100GOPRO/GX01.MP4")] = FakeResponse(
        content=content
    )
    target_dir = tmp_path / "out" / "1234"  # does not exist yet

    result = fetch_data._fetch_recoding(
        cam, "videos/DCIM/100GOPRO/GX01.MP4", target_dir, "GX01.MP4", "1234", 3
    )

    assert result == ("1234", 3, True, (target_dir, "GX01.MP4"))
    assert (target_dir / "GX01.MP4").read_bytes() == content


@pytest.mark.parametrize("response", [None, FakeResponse(status_code=404)])
def test_fetch_recoding_failure_creates_nothing(response, requests_log, tmp_path):
    cam = FakeConnection("1234")
    requests_log.handlers[("1234", "videos/x")] = response
    target_dir = tmp_path / "out" / "1234"

    result = fetch_data._fetch_recoding(
        cam, "videos/x", target_dir, "GX01.MP4", "1234", 0
    )

    assert result == ("1234", 0, False, (target_dir, "GX01.MP4"))
    assert not target_dir.exists()


# --------------------------------------------------------------------------- #
# fetch_recorded
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("gopros", [None, set()])
def test_fetch_recorded_without_gopros_aborts(
    gopros, requests_log, fake_pool, recordings_file
):
    write_entries(recordings_file, {"1234": [entry(1)]})

    fetch_data.fetch_recorded(gopros, save_path=recordings_file.parent)

    assert requests_log.calls == []
    assert fake_pool == []
    assert read_entries(recordings_file) == {"1234": [entry(1)]}


def test_fetch_recorded_without_saved_entries_aborts(
    requests_log, fake_pool, recordings_file
):
    fetch_data.fetch_recorded({FakeConnection("1234")}, save_path="unused")

    assert requests_log.calls == []
    assert fake_pool == []
    assert not recordings_file.exists()


def mark_available(requests_log, cam_id, e, content=b"video"):
    requests_log.handlers[(cam_id, info_path(e))] = FakeResponse()
    requests_log.handlers[(cam_id, video_path(e))] = FakeResponse(content=content)


def test_fetch_recorded_downloads_and_clears_entries(
    requests_log, fake_pool, recordings_file, tmp_path
):
    e1, e2 = entry(1), entry(2)
    write_entries(recordings_file, {"1234": [e1, e2]})
    mark_available(requests_log, "1234", e1, b"one")
    mark_available(requests_log, "1234", e2, b"two")
    out = tmp_path / "videos"

    fetch_data.fetch_recorded({FakeConnection("1234")}, save_path=str(out))

    assert (out / "1234" / "GX01.MP4").read_bytes() == b"one"
    assert (out / "1234" / "GX02.MP4").read_bytes() == b"two"
    # everything fetched -> camera removed from bookkeeping
    assert read_entries(recordings_file) == {}
    assert fake_pool[0].processes == 8


def test_fetch_recorded_keeps_failed_downloads(
    requests_log, fake_pool, recordings_file, tmp_path
):
    e1, e2, e3 = entry(1), entry(2), entry(3)
    write_entries(recordings_file, {"1234": [e1, e2, e3]})
    mark_available(requests_log, "1234", e1)
    mark_available(requests_log, "1234", e3)
    # e2: info OK, but the download itself fails
    requests_log.handlers[("1234", info_path(e2))] = FakeResponse()
    requests_log.handlers[("1234", video_path(e2))] = FakeResponse(status_code=500)

    fetch_data.fetch_recorded({FakeConnection("1234")}, save_path=tmp_path)

    # indices 0 and 2 deleted, the right entry (e2) stays
    assert read_entries(recordings_file) == {"1234": [e2]}
    assert not (tmp_path / "1234" / "GX02.MP4").exists()


def test_fetch_recorded_skips_disconnected_camera(
    requests_log, fake_pool, recordings_file, tmp_path
):
    write_entries(recordings_file, {"1234": [entry(1)], "5678": [entry(2)]})
    mark_available(requests_log, "1234", entry(1))

    fetch_data.fetch_recorded({FakeConnection("1234")}, save_path=tmp_path)

    assert all(cam == "1234" for cam, _ in requests_log.calls)
    assert read_entries(recordings_file) == {"5678": [entry(2)]}


def test_fetch_recorded_retries_info_then_succeeds(
    requests_log, fake_pool, recordings_file, tmp_path, no_sleep
):
    e = entry(1)
    write_entries(recordings_file, {"1234": [e]})
    requests_log.handlers[("1234", info_path(e))] = [
        None,
        FakeResponse(status_code=503),
        FakeResponse(),
    ]
    requests_log.handlers[("1234", video_path(e))] = FakeResponse(content=b"v")

    fetch_data.fetch_recorded({FakeConnection("1234")}, save_path=tmp_path)

    assert requests_log.calls.count(("1234", info_path(e))) == 3
    assert no_sleep == [1, 1]
    assert read_entries(recordings_file) == {}


def test_fetch_recorded_gives_up_after_retries(
    requests_log, fake_pool, recordings_file, tmp_path, no_sleep
):
    e = entry(1)
    write_entries(recordings_file, {"1234": [e]})
    # info never answers -> no download attempted

    fetch_data.fetch_recorded(
        {FakeConnection("1234")}, save_path=tmp_path, allowed_retries=4
    )

    assert requests_log.calls == [("1234", info_path(e))] * 4
    assert no_sleep == [1] * 4
    assert read_entries(recordings_file) == {"1234": [e]}
    assert not (tmp_path / "1234").exists()


def test_fetch_recorded_defaults_to_downloads(
    monkeypatch, requests_log, fake_pool, recordings_file, tmp_path
):
    home = tmp_path / "home"
    monkeypatch.setattr(fetch_data.Path, "home", classmethod(lambda cls: home))
    e = entry(1)
    write_entries(recordings_file, {"1234": [e]})
    mark_available(requests_log, "1234", e, b"data")

    fetch_data.fetch_recorded({FakeConnection("1234")}, max_processes=2)

    assert (home / "Downloads" / "1234" / "GX01.MP4").read_bytes() == b"data"
    assert fake_pool[0].processes == 2


def test_fetch_recorded_multiple_cameras(
    requests_log, fake_pool, recordings_file, tmp_path
):
    write_entries(recordings_file, {"1111": [entry(1)], "2222": [entry(2)]})
    mark_available(requests_log, "1111", entry(1), b"a")
    mark_available(requests_log, "2222", entry(2), b"b")

    fetch_data.fetch_recorded(
        {FakeConnection("1111"), FakeConnection("2222")}, save_path=tmp_path
    )

    assert (tmp_path / "1111" / "GX01.MP4").read_bytes() == b"a"
    assert (tmp_path / "2222" / "GX02.MP4").read_bytes() == b"b"
    assert read_entries(recordings_file) == {}