#  Copyright (c) 2026 by Lukas Behammer, Patrick Braun, Jonas Rostan
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

"""
Tests for pytermite.cli.

Commands are run through click's CliRunner. Everything that would touch the
outside world is faked: cameras, HTTP requests, multiprocessing.Process,
sounddevice, time.sleep, readline and the REPL itself. Files are only written
to pytest's tmp_path.
"""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner
from open_gopro.models.constants import StatusId
from structlog.testing import capture_logs

from pytermite import cli as cli_mod

# change-setting / get-camera-state compare `con.name == identifier`, but
# WiredConnection.name is async -> Python warns about an un-awaited coroutine.
# The bug itself is documented by test_change_setting_by_wired_camera_name.
pytestmark = pytest.mark.filterwarnings(
    "ignore:coroutine .* was never awaited:RuntimeWarning"
)

# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeWired:
    """Stands in for WiredConnection (isinstance checks are patched to this)."""

    def __init__(self, identifier, serial=None, name=None, battery=80, ok=True):
        self.identifier = identifier
        self._identifier = identifier
        self.serial = serial
        self._name = name
        self.ok = ok  # used by the fake connect_* generators

        async def get_camera_state():
            if isinstance(battery, Exception):
                raise battery
            return SimpleNamespace(
                data={StatusId.INTERNAL_BATTERY_PERCENTAGE: battery}
            )

        self.http_command = SimpleNamespace(get_camera_state=get_camera_state)

    @property
    async def name(self):  # async, exactly like the real WiredConnection.name
        return self._name


class FakeWireless(FakeWired):
    """Stands in for WirelessConnection."""


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeProcess:
    def __init__(self, target=None, args=(), daemon=None, alive=True):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self.joined = False
        self.alive = alive

    def start(self):
        self.started = True

    def is_alive(self):
        return self.alive

    def join(self):
        self.joined = True


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

ENV_VARS = [
    "PYTERMITE_SERIALS",
    "PYTERMITE_BLES",
    "PYTERMITE_COHN",
    "PYTERMITE_SERIALS_PATH",
    "PYTERMITE_COHN_SSID",
    "PYTERMITE_COHN_PASSWORD",
    "PYTERMITE_BLUETOOTH_AVAILABLE",
]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Reset module state and env vars so tests can't influence each other."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli_mod, "GOPROS", {})
    monkeypatch.setattr(cli_mod, "BLES", {})
    monkeypatch.setattr(cli_mod, "COHN", {})
    monkeypatch.setattr(cli_mod, "CONNECTED_GOPROS", set())
    monkeypatch.setattr(cli_mod, "KEEP_OPEN", False)
    monkeypatch.setattr(cli_mod, "LOG_LEVEL", cli_mod.LOG_LEVEL)
    monkeypatch.setattr(cli_mod, "PREVIEW_PROCESSES", [])
    monkeypatch.setattr(cli_mod, "ltc_process", None)
    monkeypatch.setattr(cli_mod, "WiredConnection", FakeWired)
    monkeypatch.setattr(cli_mod, "WirelessConnection", FakeWireless)
    # never enter the real REPL from a command
    repl = MagicMock()
    monkeypatch.setattr(cli_mod, "_run_repl", repl)
    return repl


@pytest.fixture
def logs():
    with capture_logs() as captured:
        yield captured


def events(captured, level=None):
    return [e["event"] for e in captured if level is None or e["log_level"] == level]


def invoke(*args, env=None):
    result = CliRunner().invoke(cli_mod.cli, list(args), env=env)
    assert result.exit_code == 0, result.output + repr(result.exception)
    return result


def connect_cams(monkeypatch, *cams):
    monkeypatch.setattr(cli_mod, "CONNECTED_GOPROS", set(cams))


@pytest.fixture
def requests_log(monkeypatch):
    """Fake make_gopro_request: handlers map (identifier, path) -> response."""
    calls = []
    handlers = {}

    def _fake(connection, path, timeout=10):
        calls.append((connection.identifier, path))
        return handlers.get((connection.identifier, path))

    monkeypatch.setattr(cli_mod, "make_gopro_request", _fake)
    return SimpleNamespace(calls=calls, handlers=handlers)


@pytest.fixture
def processes(monkeypatch):
    """Replace Process/Event so no child process is ever started."""
    created = []

    def _process(*args, **kwargs):
        p = FakeProcess(*args, **kwargs)
        created.append(p)
        return p

    monkeypatch.setattr(cli_mod, "Process", _process)
    monkeypatch.setattr(cli_mod, "Event", threading.Event)
    monkeypatch.setattr(cli_mod.multiprocessing, "Event", threading.Event)
    return created


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(cli_mod.time, "sleep", sleeps.append)
    return sleeps


@pytest.fixture
def audio(monkeypatch):
    """Fake sounddevice and the fps check used by generate-timecode."""
    queries = []

    def _query(kind):
        queries.append(kind)
        return {"index": 7}

    monkeypatch.setattr(cli_mod.sounddevice, "query_devices", _query)
    check_fps = MagicMock()
    monkeypatch.setattr(cli_mod, "_check_fps", check_fps)
    return SimpleNamespace(queries=queries, check_fps=check_fps)


@pytest.fixture
def shutter(monkeypatch):
    actions = []

    async def _fake(gopros, action):
        actions.append((set(gopros), action))

    monkeypatch.setattr(cli_mod, "camera_shutter", _fake)
    return actions


# --------------------------------------------------------------------------- #
# REPL helpers
# --------------------------------------------------------------------------- #


def test_check_line(capsys):
    ctx = click.Context(cli_mod.cli, info_name="pytermite")

    assert cli_mod._check_line("", ctx) == cli_mod._LineContinue.CONTINUE
    assert cli_mod._check_line("# comment", ctx) == cli_mod._LineContinue.CONTINUE
    assert cli_mod._check_line("exit", ctx) == cli_mod._LineContinue.BREAK
    assert cli_mod._check_line("quit", ctx) == cli_mod._LineContinue.BREAK
    assert cli_mod._check_line("record start", ctx) is None

    assert cli_mod._check_line("help", ctx) == cli_mod._LineContinue.CONTINUE
    assert "Usage: pytermite" in capsys.readouterr().out


def test_find_option():
    params = cli_mod.cli.commands["connect"].params
    assert cli_mod._find_option(params, "--serials").name == "serials"
    assert cli_mod._find_option(params, "-s").name == "serials"
    assert cli_mod._find_option(params, "--nope") is None


def test_choice_matches():
    choice = click.Choice(["start", "stop", "jamsync"])
    assert cli_mod._choice_matches(choice, "st") == ["start", "stop"]
    assert cli_mod._choice_matches(choice, "") == ["jamsync", "start", "stop"]
    assert cli_mod._choice_matches(click.INT, "1") == []


@pytest.mark.parametrize(
    "line, text, expected",
    [
        # command names, including REPL built-ins
        ("", "", None),
        ("re", "re", ["record"]),
        ("e", "e", ["exit"]),
        ("nope ", "", []),  # unknown command
        # options
        ("connect --se", "--se", ["--serials", "--serials-file"]),
        # positional choice argument
        ("record ", "", ["start", "stop"]),
        ("record s", "s", ["start", "stop"]),
        ("record --no-timecode st", "st", ["start", "stop"]),  # flag is skipped
        ("generate-timecode --fps 50 j", "j", ["jamsync"]),  # option value skipped
        ("record start ", "", []),  # no more positionals
        ("completion b", "b", ["bash"]),
    ],
)
def test_completion_candidates(line, text, expected):
    result = cli_mod._get_completion_candidates(cli_mod.cli, line, text)
    if expected is None:
        assert {"record", "connect", "help", "exit", "quit"} <= set(result)
        assert result == sorted(result)
    else:
        assert result == expected


def test_completion_candidates_option_value_choices():
    @click.group()
    def group():
        pass

    @group.command()
    @click.option("--mode", type=click.Choice(["fast", "slow"]))
    @click.option("--flag", is_flag=True)
    def run(mode, flag):
        pass

    assert cli_mod._get_completion_candidates(group, "run --mode f", "f") == ["fast"]
    # a flag takes no value -> no value completion
    assert cli_mod._get_completion_candidates(group, "run --flag ", "") == []


def test_setup_completion_registers_completer(monkeypatch):
    import readline

    registered = {}
    monkeypatch.setattr(readline, "set_completer", lambda f: registered.setdefault("f", f))
    monkeypatch.setattr(readline, "set_completer_delims", lambda d: None)
    monkeypatch.setattr(readline, "parse_and_bind", lambda s: registered.setdefault("bind", s))
    monkeypatch.setattr(readline, "get_line_buffer", lambda: "rec")
    monkeypatch.setattr(readline, "get_endidx", lambda: 3)

    cli_mod._setup_completion(click.Context(cli_mod.cli))

    completer = registered["f"]
    assert completer("rec", 0) == "record"
    assert completer("rec", 1) is None
    assert "complete" in registered["bind"]


def test_setup_history_uses_config_path(monkeypatch, tmp_path, logs):
    histfile = tmp_path / "sub" / ".history"
    monkeypatch.setattr(cli_mod, "resolve_config_path", lambda *a, **k: histfile)
    registered = []
    monkeypatch.setattr(cli_mod.atexit, "register", registered.append)

    cli_mod._setup_history()

    assert histfile.parent.is_dir()
    # file didn't exist yet -> warning, but history is still set up
    assert any("Failed to read history" in e for e in events(logs, "warning"))
    assert len(registered) == 1
    registered[0]()  # the atexit hook
    assert histfile.exists()


# --------------------------------------------------------------------------- #
# _run_repl
# --------------------------------------------------------------------------- #


def feed_input(monkeypatch, lines, end=EOFError):
    lines = list(lines)

    def _input(prompt=""):
        if not lines:
            raise end
        return lines.pop(0)

    monkeypatch.setattr("builtins.input", _input)


@pytest.fixture
def real_repl(monkeypatch, isolate):
    """Use the real _run_repl, but fake the CLI it dispatches to."""
    monkeypatch.setattr(cli_mod, "_run_repl", REAL_RUN_REPL)
    monkeypatch.setattr(cli_mod, "_setup_history", lambda: None)
    monkeypatch.setattr(cli_mod, "_setup_completion", lambda ctx: None)
    dispatched = []
    errors = {
        "sysexit": SystemExit(1),
        "usage": click.UsageError("bad"),
        "boom": ValueError("boom"),
    }

    def _main(args, prog_name, standalone_mode):
        assert standalone_mode is False
        dispatched.append(args)
        if args and args[0] in errors:
            raise errors[args[0]]

    ctx = click.Context(cli_mod.cli, info_name="pytermite")
    monkeypatch.setattr(cli_mod, "cli", SimpleNamespace(main=_main))
    return SimpleNamespace(ctx=ctx, dispatched=dispatched)


REAL_RUN_REPL = cli_mod._run_repl


def test_repl_dispatches_and_survives_errors(monkeypatch, real_repl, capsys):
    feed_input(
        monkeypatch,
        [
            "",
            "   # a comment",
            "help",
            'record "unbalanced',  # shlex error -> skipped
            "list-connected",
            "sysexit",
            "usage",
            "boom",
            "record start",
            "exit",
            "never-reached",
        ],
    )

    cli_mod._run_repl(real_repl.ctx)

    assert real_repl.dispatched == [
        ["list-connected"],
        ["sysexit"],
        ["usage"],
        ["boom"],
        ["record", "start"],
    ]
    assert "Usage: pytermite" in capsys.readouterr().out


@pytest.mark.parametrize("end", [EOFError, KeyboardInterrupt])
def test_repl_exits_on_eof_and_ctrl_c(monkeypatch, real_repl, end):
    feed_input(monkeypatch, ["disconnect"], end=end)

    cli_mod._run_repl(real_repl.ctx)

    assert real_repl.dispatched == [["disconnect"]]


# --------------------------------------------------------------------------- #
# cli group
# --------------------------------------------------------------------------- #


def test_no_subcommand_starts_repl(isolate):
    invoke()
    isolate.assert_called_once()


@pytest.mark.parametrize("flag, level", [([], 20), (["-v"], 10)])
def test_verbose_sets_log_level(flag, level):
    invoke(*flag, "list-connected")
    assert cli_mod.LOG_LEVEL == level


def test_interactive_keeps_repl_open_after_command(monkeypatch, isolate):
    async def _close(gopros):
        pass

    monkeypatch.setattr(cli_mod, "close_gopros", _close)

    invoke("-i", "disconnect")

    assert cli_mod.KEEP_OPEN is True
    isolate.assert_called_once()


def test_without_interactive_no_repl_after_command(isolate):
    invoke("list-connected")
    isolate.assert_not_called()


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #


@pytest.fixture
def scans(monkeypatch):
    calls = []

    async def _fake(waiting_time=10, bluetooth=False, usb=True):
        calls.append((waiting_time, bluetooth, usb))
        return set(), set()

    monkeypatch.setattr(cli_mod, "scan_for_gopros", _fake)
    return calls


def test_scan_defaults(scans):
    invoke("scan")
    assert scans == [(10, False, True)]


def test_scan_with_options(scans):
    invoke("scan", "-t", "3", "-bt")
    assert scans == [(3, True, True)]


def test_scan_bluetooth_unavailable(scans):
    invoke("scan", "-bt", env={"PYTERMITE_BLUETOOTH_AVAILABLE": "false"})
    assert scans == [(10, False, True)]


# --------------------------------------------------------------------------- #
# connect
# --------------------------------------------------------------------------- #


@pytest.fixture
def creators(monkeypatch):
    """Record what connect() asks to create; don't actually connect."""
    seen = {}

    def _wired(gopro_serials):
        seen["wired"] = gopro_serials
        return {k: FakeWired(k) for k in gopro_serials}

    def _wireless(gopro_names):
        seen["wireless"] = gopro_names
        return {k: FakeWireless(k) for k in gopro_names}

    def _cohn(identifiers, cohn_db_path):
        seen["cohn"] = identifiers
        seen["cohn_db"] = cohn_db_path
        return {k: FakeWireless(k) for k in identifiers}

    async def _connect():
        seen["connected"] = True

    monkeypatch.setattr(cli_mod, "create_wired_gopros", _wired)
    monkeypatch.setattr(cli_mod, "create_wireless_gopros", _wireless)
    monkeypatch.setattr(cli_mod, "create_cohn_gopros", _cohn)
    monkeypatch.setattr(cli_mod, "_connect_to_gopros", _connect)
    monkeypatch.setattr(cli_mod, "load_cohn_identifiers", lambda path: set())
    return seen


def test_connect_requires_a_method(creators):
    result = CliRunner().invoke(cli_mod.cli, ["connect"])
    assert result.exit_code == 2
    assert "Please specify a connection method" in result.output
    assert "connected" not in creators


def test_connect_with_serials(creators, logs):
    invoke("connect", "--serials", "C111, C222")

    assert creators["wired"] == {"C111", "C222"}
    assert creators["wireless"] == set()
    assert creators["cohn"] == set()
    assert creators["connected"] is True
    # nothing connected in this fake -> error is logged
    assert "Failed to connect to any requested GoPro cameras" in events(logs, "error")


def test_connect_serials_from_env(creators):
    invoke("connect", env={"PYTERMITE_SERIALS": "C999"})
    assert creators["wired"] == {"C999"}


def test_connect_with_serials_file(monkeypatch, creators, tmp_path):
    path = tmp_path / "serials.json"
    path.write_text("{}")
    monkeypatch.setattr(
        cli_mod, "load_serial_numbers_from_json", lambda p: {"camA": "C111"}
    )

    invoke("connect", "-f", str(path))

    assert creators["wired"] == {"camA": "C111"}


def test_connect_serials_file_must_exist(creators, tmp_path):
    result = CliRunner().invoke(
        cli_mod.cli, ["connect", "-f", str(tmp_path / "missing.json")]
    )
    assert result.exit_code == 2


def test_connect_with_ble(creators):
    invoke("connect", "--ble", "1111,2222 ")
    assert creators["wireless"] == {"1111", "2222"}
    assert creators["wired"] == set()


def test_connect_with_cohn(monkeypatch, creators, tmp_path):
    monkeypatch.setattr(cli_mod, "load_cohn_identifiers", lambda path: {"3333"})

    invoke("connect", "--cohn")

    assert creators["cohn"] == {"3333"}
    assert creators["cohn_db"] == cli_mod.COHN_DB


def test_connect_auto_combines_usb_ble_and_cohn(monkeypatch, creators):
    async def _scan(waiting_time, bluetooth, usb):
        if usb:
            return {"C3391324491111"}, set()
        return set(), {"1111", "2222", "3333"}

    monkeypatch.setattr(cli_mod, "scan_for_gopros", _scan)
    monkeypatch.setattr(cli_mod, "load_cohn_identifiers", lambda path: {"3333"})

    invoke("connect", "--auto")

    assert creators["wired"] == {"C3391324491111"}
    # 1111 is already on USB, 3333 is already provisioned for COHN
    assert creators["wireless"] == {"2222"}
    assert creators["cohn"] == {"3333"}


def test_connect_falls_back_to_known_cameras(monkeypatch, creators):
    monkeypatch.setattr(cli_mod, "GOPROS", {"a": FakeWired("1111", serial="C1111")})
    monkeypatch.setattr(cli_mod, "BLES", {"b": FakeWireless("2222")})
    monkeypatch.setattr(cli_mod, "load_cohn_identifiers", lambda path: {"3333"})

    invoke("connect", "--cohn")

    assert creators["wired"] == {"C1111"}
    assert creators["wireless"] == {"2222"}


# --------------------------------------------------------------------------- #
# _connect_to_gopros
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_connectors(monkeypatch):
    seen = {}

    async def _cohn(gopros):
        for g in list(gopros.values()):
            if g.ok:
                yield g

    async def _wired(gopros):
        for g in list(gopros.values()):
            if g.ok:
                yield g

    async def _wireless(gopros, ssid, password):
        seen["wifi"] = (ssid, password)
        for g in list(gopros.values()):
            if g.ok:
                yield g

    monkeypatch.setattr(cli_mod, "connect_gopros_cohn", _cohn)
    monkeypatch.setattr(cli_mod, "connect_gopros", _wired)
    monkeypatch.setattr(cli_mod, "connect_gopros_wireless", _wireless)
    return seen


def test_connect_to_gopros_moves_connected_cameras(monkeypatch, fake_connectors):
    monkeypatch.setenv("PYTERMITE_COHN_SSID", "net")
    monkeypatch.setenv("PYTERMITE_COHN_PASSWORD", "pw")
    w_ok, w_bad = FakeWired("w1"), FakeWired("w2", ok=False)
    b_ok, b_bad = FakeWireless("b1"), FakeWireless("b2", ok=False)
    c_ok = FakeWireless("c1")
    monkeypatch.setattr(cli_mod, "GOPROS", {"camA": w_ok, "camB": w_bad})
    monkeypatch.setattr(cli_mod, "BLES", {"b1": b_ok, "b2": b_bad})
    monkeypatch.setattr(cli_mod, "COHN", {"c1": c_ok})

    asyncio.run(cli_mod._connect_to_gopros())

    assert cli_mod.CONNECTED_GOPROS == {w_ok, b_ok, c_ok}
    # only the failed ones are left in the mappings
    assert cli_mod.GOPROS == {"camB": w_bad}
    assert cli_mod.BLES == {"b2": b_bad}
    assert cli_mod.COHN == {}
    assert fake_connectors["wifi"] == ("net", "pw")


def test_connect_to_gopros_skips_wireless_without_credentials(
    monkeypatch, fake_connectors, logs
):
    ble = FakeWireless("b1")
    monkeypatch.setattr(cli_mod, "BLES", {"b1": ble})

    asyncio.run(cli_mod._connect_to_gopros())

    assert "wifi" not in fake_connectors
    assert cli_mod.BLES == {"b1": ble}
    assert any("PYTERMITE_COHN_SSID" in e for e in events(logs, "warning"))


# --------------------------------------------------------------------------- #
# list-connected / disconnect
# --------------------------------------------------------------------------- #


def test_list_connected_prints_battery(monkeypatch, logs):
    connect_cams(
        monkeypatch,
        FakeWired("1111", battery=77),
        FakeWired("2222", battery=RuntimeError("offline")),
    )

    result = invoke("list-connected")

    assert "1111" in result.output and "77" in result.output
    assert "2222" not in result.output
    assert any("2222" in e for e in events(logs, "warning"))


def test_disconnect_closes_and_clears(monkeypatch):
    cams = {FakeWired("1111"), FakeWireless("2222")}
    connect_cams(monkeypatch, *cams)
    closed = []

    async def _close(gopros):
        closed.append(set(gopros))

    monkeypatch.setattr(cli_mod, "close_gopros", _close)

    invoke("disconnect")

    assert closed == [cams]
    assert cli_mod.CONNECTED_GOPROS == set()


def test_exit_handler_closes_connections(monkeypatch):
    cams = {FakeWired("1111")}
    connect_cams(monkeypatch, *cams)
    closed = []

    async def _close(gopros):
        closed.append(set(gopros))

    monkeypatch.setattr(cli_mod, "close_gopros", _close)

    cli_mod._exit_handler()

    assert closed == [cams]


# --------------------------------------------------------------------------- #
# record
# --------------------------------------------------------------------------- #


def test_record_start_starts_timecode_and_shutter(
    monkeypatch, shutter, processes, audio, no_sleep
):
    cam = FakeWired("1111")
    connect_cams(monkeypatch, cam)

    invoke("record", "start")

    assert shutter == [({cam}, "start")]
    # timecode generator started, no fetch process
    assert [p.target for p in processes] == [cli_mod._run_generator]
    assert cli_mod.ltc_process is not None


def test_record_start_without_timecode(shutter, processes, audio):
    invoke("record", "--no-timecode", "start")

    assert shutter == [(set(), "start")]
    assert processes == []
    assert cli_mod.ltc_process is None


def test_record_no_timecode_while_running_warns(monkeypatch, shutter, processes, logs):
    monkeypatch.setattr(cli_mod, "ltc_process", (FakeProcess(), threading.Event()))

    invoke("record", "-nt", "start")

    assert any("timecode already running" in e for e in events(logs, "warning"))


def test_record_stop_fetches_filenames(monkeypatch, shutter, processes):
    cam = FakeWired("1111")
    connect_cams(monkeypatch, cam)

    invoke("record", "stop")

    assert shutter == [({cam}, "stop")]
    assert len(processes) == 1
    fetch = processes[0]
    assert fetch.target is cli_mod.fetch_filenames
    assert fetch.args == ({cam},)
    assert fetch.started and fetch.daemon is False


def test_record_shutter_error_is_logged(monkeypatch, processes, logs):
    async def _fail(gopros, action):
        raise RuntimeError("camera busy")

    monkeypatch.setattr(cli_mod, "camera_shutter", _fail)

    invoke("record", "-nt", "stop")

    assert processes == []
    assert "Failed to execute record action" in events(logs, "error")


def test_record_rejects_invalid_action(shutter):
    result = CliRunner().invoke(cli_mod.cli, ["record", "pause"])
    assert result.exit_code == 2
    assert shutter == []


# --------------------------------------------------------------------------- #
# generate-timecode
# --------------------------------------------------------------------------- #


def test_timecode_start_uses_default_device(processes, audio, no_sleep):
    invoke("generate-timecode", "start", "--fps", "25")

    audio.check_fps.assert_called_once_with(25)
    assert audio.queries == ["output"]
    (proc,) = processes
    config, event = proc.args
    assert proc.target is cli_mod._run_generator and proc.started
    assert config == {"sample_rate": 48000, "fps": 25, "device": 7}
    assert cli_mod.ltc_process == (proc, event)
    assert no_sleep == [3]


def test_timecode_start_with_explicit_device(processes, audio, no_sleep):
    invoke("generate-timecode", "start", "--device", "2", "--sample_rate", "44100")

    assert audio.queries == []
    assert processes[0].args[0] == {"sample_rate": 44100, "fps": 50, "device": 2}


def test_timecode_start_when_already_running(monkeypatch, processes, audio, no_sleep):
    running = (FakeProcess(), threading.Event())
    monkeypatch.setattr(cli_mod, "ltc_process", running)

    invoke("generate-timecode", "start")

    assert processes == []
    assert cli_mod.ltc_process is running


def test_timecode_stop(monkeypatch, processes):
    event = threading.Event()
    monkeypatch.setattr(cli_mod, "ltc_process", (FakeProcess(), event))

    invoke("generate-timecode", "stop")

    assert event.is_set()
    assert cli_mod.ltc_process is None


def test_timecode_stop_when_not_running(processes, logs):
    invoke("generate-timecode", "stop")

    assert processes == []
    assert any("No valid options" in e for e in events(logs, "info"))


def test_timecode_jamsync(processes, no_sleep):
    invoke("generate-timecode", "jamsync", "--duration", "4")

    (proc,) = processes
    _, event = proc.args
    assert no_sleep == [4]
    assert event.is_set() and proc.joined
    # jamsync is temporary: it must not be stored as the running generator
    assert cli_mod.ltc_process is None


@pytest.mark.parametrize("duration", [[], ["--duration", "0"]])
def test_timecode_jamsync_requires_positive_duration(processes, logs, duration):
    invoke("generate-timecode", "jamsync", *duration)

    assert processes == []
    assert any("positive --duration" in e for e in events(logs, "error"))


def test_timecode_duration_ignored_for_start(processes, audio, no_sleep, logs):
    invoke("generate-timecode", "start", "--duration", "5")

    assert any("only used with the jamsync" in e for e in events(logs, "warning"))
    assert no_sleep == [3]


def test_timecode_audio_error_is_logged(monkeypatch, processes, audio, logs):
    def _broken(kind):
        raise cli_mod.sounddevice.PortAudioError("no device")

    monkeypatch.setattr(cli_mod.sounddevice, "query_devices", _broken)

    invoke("generate-timecode", "start")

    assert processes == []
    assert "Failed to execute timecode generator action" in events(logs, "error")


def test_run_generator(monkeypatch):
    created = []

    class FakeGenerator:
        def __init__(self, config, stop_event):
            created.append((config, stop_event))
            self.ran = False

        def run(self):
            created.append("ran")

    monkeypatch.setattr(cli_mod, "LTCGenerator", FakeGenerator)
    event = threading.Event()

    cli_mod._run_generator({"fps": 50}, event)

    assert created == [({"fps": 50}, event), "ran"]


# --------------------------------------------------------------------------- #
# _check_fps
# --------------------------------------------------------------------------- #

SETTINGS_MAP = {"2": {"options": {"1": "4K"}}, "3": {"options": {"5": "60.0", "8": "50.0"}}}


def state(fps_option, extra=None):
    return FakeResponse(payload={"settings": {"3": fps_option, **(extra or {})}})


def test_check_fps_warns_on_mismatch(monkeypatch, requests_log, logs):
    monkeypatch.setattr(cli_mod, "_load_bundled_json", lambda name: SETTINGS_MAP)
    connect_cams(
        monkeypatch, FakeWired("1111"), FakeWired("2222"), FakeWired("3333")
    )
    requests_log.handlers[("1111", "gopro/camera/state")] = state(8)  # 50 fps
    requests_log.handlers[("2222", "gopro/camera/state")] = state(5)  # 60 fps
    # 3333: request fails -> ignored

    cli_mod._check_fps(50)

    warnings = events(logs, "warning")
    assert "Camera 2222: 60fps" in warnings
    assert not any("1111" in w or "3333" in w for w in warnings)


def test_check_fps_all_match(monkeypatch, requests_log, logs):
    monkeypatch.setattr(cli_mod, "_load_bundled_json", lambda name: SETTINGS_MAP)
    connect_cams(monkeypatch, FakeWired("1111"))
    requests_log.handlers[("1111", "gopro/camera/state")] = state(8)

    cli_mod._check_fps(50)

    assert events(logs, "warning") == []


# --------------------------------------------------------------------------- #
# fetchdata
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("args, save_path", [([], None), (["--save_path", "out"], "out")])
def test_fetchdata_starts_fetch_process(monkeypatch, processes, args, save_path):
    cam = FakeWired("1111")
    connect_cams(monkeypatch, cam)

    invoke("fetchdata", *args)

    (proc,) = processes
    assert proc.target is cli_mod.fetch_recorded
    assert proc.args == ({cam}, save_path)
    assert proc.started and proc.daemon is False


# --------------------------------------------------------------------------- #
# change-setting
# --------------------------------------------------------------------------- #


@pytest.fixture
def parse(monkeypatch):
    monkeypatch.setattr(cli_mod, "parse_setting", lambda setting, option, **kw: (2, 1))


def test_change_setting_success(monkeypatch, requests_log, parse, logs):
    connect_cams(monkeypatch, FakeWireless("1111"))
    path = "gopro/camera/setting?option=1&setting=2"
    requests_log.handlers[("1111", path)] = FakeResponse()

    invoke("change-setting", "1111", "resolution", "4K")

    assert requests_log.calls == [("1111", path)]
    assert "Changed resolution for 1111 to 4K" in events(logs, "info")


def test_change_setting_request_fails(monkeypatch, requests_log, parse, logs):
    connect_cams(monkeypatch, FakeWireless("1111"))

    invoke("change-setting", "1111", "resolution", "4K")

    assert any("could not be changed" in e for e in events(logs, "warning"))


def test_change_setting_unknown_camera(requests_log, parse, logs):
    invoke("change-setting", "9999", "resolution", "4K")

    assert requests_log.calls == []
    assert "9999 is not connected" in events(logs, "warning")


@pytest.mark.xfail(
    strict=True,
    reason="WiredConnection.name is an async property, so `con.name == identifier` "
    "compares a coroutine with a string and never matches",
)
def test_change_setting_by_wired_camera_name(monkeypatch, requests_log, parse):
    connect_cams(monkeypatch, FakeWired("1111", name="GP-Left"))

    invoke("change-setting", "GP-Left", "resolution", "4K")

    assert requests_log.calls  # a request should have been sent


# --------------------------------------------------------------------------- #
# preview-stream
# --------------------------------------------------------------------------- #


def test_preview_start(monkeypatch, processes):
    cam = FakeWired("1111")
    connect_cams(monkeypatch, cam)
    monkeypatch.setattr(
        cli_mod, "serializable_connections", lambda cams: ("serialized", set(cams))
    )

    invoke("preview-stream", "start")

    (proc,) = processes
    serials, event = proc.args
    assert proc.target is cli_mod._run_preview and proc.started
    assert serials == ("serialized", {cam})
    assert cli_mod.PREVIEW_PROCESSES == [(proc, event)]


def test_preview_stop_signals_all_and_drops_finished(monkeypatch, processes):
    alive = (FakeProcess(alive=True), threading.Event())
    dead = (FakeProcess(alive=False), threading.Event())
    monkeypatch.setattr(cli_mod, "PREVIEW_PROCESSES", [alive, dead])

    invoke("preview-stream", "stop")

    assert alive[1].is_set() and dead[1].is_set()
    assert cli_mod.PREVIEW_PROCESSES == [alive]


def test_preview_without_action_warns(processes, logs):
    invoke("preview-stream")

    assert processes == []
    assert any("could not be started" in e for e in events(logs, "warning"))


def test_run_preview(monkeypatch):
    created = []
    monkeypatch.setattr(
        cli_mod, "PreviewStream", lambda serials, event, log: created.append((serials, event))
    )
    event = threading.Event()

    cli_mod._run_preview({"cam"}, event)

    assert created == [({"cam"}, event)]


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #


def test_settings_without_camera(requests_log, logs):
    invoke("settings")
    assert requests_log.calls == []
    assert any("No identifier provided" in e for e in events(logs, "warning"))


def test_settings_unknown_camera(requests_log, logs):
    invoke("settings", "9999", "--export", "x.json")
    assert requests_log.calls == []
    assert "9999 is not connected" in events(logs, "warning")


def test_settings_without_action(monkeypatch, requests_log, logs):
    connect_cams(monkeypatch, FakeWired("1111"))
    invoke("settings", "1111")
    assert requests_log.calls == []
    assert any("No action specified" in e for e in events(logs, "warning"))


@pytest.mark.parametrize("ref", ["1111", "GP-Left"])  # identifier or name
def test_settings_export(monkeypatch, requests_log, tmp_path, ref):
    monkeypatch.setattr(cli_mod, "_load_bundled_json", lambda name: SETTINGS_MAP)
    connect_cams(monkeypatch, FakeWired("1111", name="GP-Left"))
    requests_log.handlers[("1111", "gopro/camera/state")] = state(8, {"2": 1, "999": 4})
    out = tmp_path / "settings.json"

    invoke("settings", ref, "--export", str(out))

    # unknown setting ids are filtered out
    assert json.loads(out.read_text()) == {"2": 1, "3": 8}


def test_settings_export_failure_writes_nothing(monkeypatch, requests_log, tmp_path, logs):
    connect_cams(monkeypatch, FakeWired("1111"))
    out = tmp_path / "settings.json"

    invoke("settings", "1111", "--export", str(out))

    assert not out.exists()
    assert any("export for 1111 failed" in e for e in events(logs, "warning"))


def test_settings_import(monkeypatch, requests_log, tmp_path, logs):
    connect_cams(monkeypatch, FakeWired("1111"))
    src = tmp_path / "settings.json"
    src.write_text(json.dumps({"2": 1, "3": 8, "bad": 7}))

    def _parse(setting, value, mode):
        if setting == "bad":
            return None, None
        if mode == "camera_ref":
            return int(setting), int(value)
        return f"setting{setting}", f"option{value}"

    monkeypatch.setattr(cli_mod, "parse_setting", _parse)
    requests_log.handlers[("1111", "gopro/camera/setting?option=1&setting=2")] = (
        FakeResponse()
    )
    # setting 3 gets no handler -> request fails

    invoke("settings", "1111", "--import", str(src))

    assert requests_log.calls == [
        ("1111", "gopro/camera/setting?option=1&setting=2"),
        ("1111", "gopro/camera/setting?option=8&setting=3"),
    ]
    assert "Changed setting2 for 1111 to option1" in events(logs, "info")
    warnings = events(logs, "warning")
    assert any("setting3 for 1111 could not be changed" in w for w in warnings)
    assert any("Could not parse setting bad" in w for w in warnings)


# --------------------------------------------------------------------------- #
# get-camera-state
# --------------------------------------------------------------------------- #


@pytest.fixture
def two_cams(monkeypatch, requests_log):
    def _parse(key, value, mode):
        if key == "99":
            return None, None
        return f"setting{key}", f"opt{value}"

    monkeypatch.setattr(cli_mod, "parse_setting", _parse)
    monkeypatch.setattr(cli_mod, "parse_status", lambda key: f"status{key}")
    wired, wireless = FakeWired("1111"), FakeWireless("2222")
    connect_cams(monkeypatch, wired, wireless)
    for cam_id, battery in (("1111", 81), ("2222", 42)):
        requests_log.handlers[(cam_id, "gopro/camera/state")] = FakeResponse(
            payload={"settings": {"2": 1, "99": 0}, "status": {"70": battery}}
        )
    return requests_log


def test_get_camera_state_both_tables(two_cams):
    out = invoke("get-camera-state", "1111,2222").output

    assert "1111 (USB)" in out and "2222 (Wireless)" in out
    assert "setting2" in out and "opt1" in out
    assert "setting99" not in out  # unparsable settings are skipped
    assert "status70" in out and "81" in out and "42" in out


def test_get_camera_state_settings_only(two_cams):
    out = invoke("get-camera-state", "--settings", "1111").output
    assert "setting2" in out
    assert "status70" not in out


def test_get_camera_state_status_only(two_cams):
    out = invoke("get-camera-state", "--status", "1111").output
    assert "status70" in out
    assert "setting2" not in out


def test_get_camera_state_defaults_to_all_cameras(two_cams):
    out = invoke("get-camera-state").output
    assert "1111 (USB)" in out and "2222 (Wireless)" in out


def test_get_camera_state_unknown_and_failing(two_cams, logs):
    del two_cams.handlers[("2222", "gopro/camera/state")]

    invoke("get-camera-state", "2222, 9999")

    warnings = events(logs, "warning")
    assert "9999 is not connected" in warnings
    assert "State request for 2222 failed" in warnings


# --------------------------------------------------------------------------- #
# completion
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_script(shell):
    out = invoke("completion", shell).output
    assert "_PYTERMITE_COMPLETE" in out
    assert "pytermite" in out


def test_completion_rejects_unknown_shell():
    result = CliRunner().invoke(cli_mod.cli, ["completion", "powershell"])
    assert result.exit_code == 2


# --------------------------------------------------------------------------- #
# Behaviour shared by several commands
# --------------------------------------------------------------------------- #


def test_connect_reports_success(monkeypatch, creators, logs):
    cam = FakeWired("1111")

    async def _connect():
        cli_mod.CONNECTED_GOPROS.add(cam)
        cli_mod.GOPROS.clear()

    monkeypatch.setattr(cli_mod, "_connect_to_gopros", _connect)

    invoke("connect", "-s", "C1111")

    assert "Connected to 1 GoPro camera(s)" in events(logs, "info")
    assert events(logs, "error") == []


@pytest.mark.parametrize(
    "args",
    [
        ["scan"],
        ["connect", "--ble", "1111"],
        ["record", "-nt", "stop"],
        ["generate-timecode", "stop"],
        ["fetchdata"],
        ["change-setting", "9999", "s", "o"],
        ["preview-stream"],
        ["get-camera-state", "9999"],
    ],
    ids=lambda a: a[0],
)
def test_interactive_flag_returns_to_repl(
    isolate, scans, creators, shutter, processes, args
):
    invoke("-i", *args)
    isolate.assert_called_once()


@pytest.fixture
def failing_process(monkeypatch):
    def _process(*args, **kwargs):
        raise RuntimeError("cannot start process")

    monkeypatch.setattr(cli_mod, "Process", _process)
    monkeypatch.setattr(cli_mod.multiprocessing, "Event", threading.Event)
    monkeypatch.setattr(cli_mod, "serializable_connections", lambda cams: cams)


@pytest.mark.parametrize(
    "args, message",
    [
        (["fetchdata"], "Failed to start fetch process"),
        (["preview-stream", "start"], "Failed to execute preview action"),
    ],
)
def test_process_start_errors_are_logged(failing_process, logs, args, message):
    invoke(*args)
    assert message in events(logs, "error")


def test_change_setting_runtime_error_is_logged(monkeypatch, requests_log, logs):
    connect_cams(monkeypatch, FakeWireless("1111"))

    def _broken(*a, **k):
        raise RuntimeError("unknown setting")

    monkeypatch.setattr(cli_mod, "parse_setting", _broken)

    invoke("change-setting", "1111", "x", "y")

    assert "Failed to change setting" in events(logs, "error")


def test_get_camera_state_runtime_error_is_logged(monkeypatch, logs):
    connect_cams(monkeypatch, FakeWireless("1111"))

    def _broken(connection, path, timeout=10):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(cli_mod, "make_gopro_request", _broken)

    invoke("get-camera-state", "1111")

    assert "Failed to get camera state" in events(logs, "error")