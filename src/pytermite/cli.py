"""
`pyTermite` command line interface and REPL utilities.

Provides a Click-based CLI for discovering, connecting to and controlling
multiple GoPro devices. Includes an interactive REPL for repeated commands.
"""

#  Copyright (c) 2026 by Lukas Behammer, Patrick Braun, Jonas Rostan
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import atexit
import enum
import logging
import os
import shlex
import time
from multiprocessing import Event, Process
from multiprocessing.synchronize import Event as SyncEvent
from pathlib import Path

import click
import structlog
from click_help_colors import HelpColorsGroup

from pytermite.commands import camera_shutter
from pytermite.config import PYTERMITE_LOG_LEVEL, resolve_config_path
from pytermite.connection import (
    COHN_DB,
    WiredConnection,
    WirelessConnection,
    close_gopros,
    connect_gopros,
    connect_gopros_cohn,
    connect_gopros_wireless,
    create_cohn_gopros,
    create_wired_gopros,
    create_wireless_gopros,
    load_cohn_identifiers,
    scan_for_gopros,
)
from pytermite.fetch_data import fetch_filenames, fetch_recorded
from pytermite.lineartimecode import (
    LTCGenerator,
    decode_timecode_batch,
)
from pytermite.utils import load_serial_numbers_from_json

os.environ["LANG"] = "en_US"

LOG_LEVEL = PYTERMITE_LOG_LEVEL
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
GOPROS: dict[str, WiredConnection] = {}
BLES: dict[str, WirelessConnection] = {}
COHN: dict[str, WirelessConnection] = {}
CONNECTED_GOPROS: set[WiredConnection | WirelessConnection] = set()
KEEP_OPEN = False


class _LineContinue(enum.StrEnum):
    """Special return values for to control REPL flow."""

    CONTINUE = "continue"
    BREAK = "break"


structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(PYTERMITE_LOG_LEVEL),
)
logger = structlog.get_logger()


def _setup_history() -> None:
    """
    Try to enable readline history and persist it in the user's home dir.

    Silently ignore failures.
    """
    try:
        import readline  # optional: enables convenient command-line editing and history

        try:
            histfile = resolve_config_path(
                "PYTERMITE_HISTORY_PATH",
                default_filename=".history",
            )
            histfile.parent.mkdir(parents=True, exist_ok=True)
            try:
                readline.read_history_file(str(histfile))
            except Exception:
                # ignore history read errors
                logger.warning(
                    "Failed to read history file; starting with empty history",
                    file=str(histfile),
                )

            def _save_hist() -> None:
                try:
                    readline.write_history_file(str(histfile))
                except Exception:
                    logger.warning(
                        "Failed to write history file on exit",
                        file=str(histfile),
                    )

            atexit.register(_save_hist)
        except Exception:
            logger.warning(
                "Failed to set up history file; command history will not be saved",
            )
    except Exception:
        logger.warning(
            "Failed to import readline; command history will not be available",
        )


def _check_line(line: str, ctx: click.Context) -> str | None:
    """
    Check if the input line is a special command that should be handled directly.

    Parameters
    ----------
    line : str
        The input line to check.
    ctx : click.Context
        Click context used to provide help text inside the REPL.

    Returns
    -------
    str | None
        LineContinue.CONTINUE if the line was handled and the REPL should continue,
        LineContinue.BREAK if the line was handled and the REPL should exit,
        or None if the line should be processed as a normal command.
    """
    if not line:
        return _LineContinue.CONTINUE

    if line == "help":
        click.echo(ctx.get_help())
        return _LineContinue.CONTINUE

    if line in ("exit", "quit"):
        return _LineContinue.BREAK

    # allow running shell-style comments
    if line.startswith("#"):
        return _LineContinue.CONTINUE

    return None


def _run_repl(ctx: click.Context) -> None:
    """
    Run the interactive REPL.

    Parameters
    ----------
    ctx : click.Context
        Click context used to provide help text and program name inside the REPL.
    """
    log = logger.bind(command="shell")
    log.debug("Entering interactive shell")
    info_str = "Starting interactive shell; type 'help' or 'exit' to leave."
    click.echo(info_str)

    # Try to initialise command history support.
    _setup_history()

    prompt = "pytermite> "

    while True:
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            # Ctrl-D or Ctrl-C -> exit the shell
            click.echo()
            break

        line = (line or "").strip()
        if _check_line(line, ctx) == _LineContinue.CONTINUE:
            continue
        if _check_line(line, ctx) == _LineContinue.BREAK:
            break

        try:
            args = shlex.split(line)
        except ValueError as e:
            log.error("Failed to parse input", error=str(e))
            continue

        # Dispatch the parsed args back into the click CLI. Use standalone_mode=False
        # so that click doesn't call sys.exit(). Handle SystemExit to avoid breaking
        # the REPL.
        try:
            cli.main(args=args, prog_name=ctx.info_name, standalone_mode=False)
        except SystemExit:
            # Commands may call sys.exit(); ignore and continue the REPL.
            continue
        except click.UsageError:
            click.echo(info_str)
            continue
        except Exception as e:
            log.exception("Error while executing command", error=str(e))

    log.debug("Leaving interactive shell")


@click.group(
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
    cls=HelpColorsGroup,
    help_headers_color="magenta",
    help_options_color="cyan",
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    help="After running a command, keep the process open and enter the interactive "
    "shell.",
)
@click.version_option(None, "-V", "--version")
@click.option("--verbose", "-v", is_flag=True, help="Show debug statements.")
@click.pass_context
def cli(
    ctx: click.Context, interactive: bool, verbose: bool
) -> None:  # numpydoc ignore=GL03
    """
    `pyTermite` CLI - Control multiple GoPro cameras via USB connection.

    When invoked without a subcommand this CLI will enter an interactive REPL
    allowing multiple commands to be executed without exiting the process.
    If started with --interactive the CLI will stay open after running a
    subcommand and drop into the interactive REPL.

    \f

    Parameters
    ----------
    ctx : click.Context
        Click context used to provide help text and program name inside the REPL.
    interactive : bool
        Whether to keep the process open and enter the interactive shell after
        running a command.
    verbose : bool
        Whether to show debug statements.
    """
    # Configure log level
    global LOG_LEVEL
    if verbose:
        LOG_LEVEL = logging.DEBUG
    else:
        LOG_LEVEL = logging.INFO
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(LOG_LEVEL),
    )

    # Store the interactive preference globally so individual commands can
    # decide whether to drop into the REPL after finishing.
    global KEEP_OPEN
    KEEP_OPEN = bool(interactive)

    # If a subcommand was supplied, let click dispatch normally.
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand: start the interactive REPL.
    _run_repl(ctx)


@cli.command()
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=10,
    show_default=True,
    help="Time to wait for GoPro devices to be discovered (in seconds).",
    metavar="<int>",
)
@click.option(
    "--bluetooth",
    "-bt",
    is_flag=True,
    default=False,
    show_default=True,
    help="Search for GoPro devices via Bluetooth Low Energy (BLE) in addition to USB .",
)
def scan(timeout: int, bluetooth: bool) -> None:  # numpydoc ignore=GL03
    """
    Discover GoPro devices via USB and mDNS and Bluetooth.

    \f

    Parameters
    ----------
    timeout : int
        How long to wait for discovery in seconds.
    bluetooth : bool
        Whether to search for devices via Bluetooth Low Energy.
    """
    if bluetooth and os.getenv("PYTERMITE_BLUETOOTH_AVAILABLE") == "false":
        logger.warning("Bluetooth is not available. Skipping BLE discovery.")
        bluetooth = False
    asyncio.run(scan_for_gopros(waiting_time=timeout, bluetooth=bluetooth))
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


@cli.command()
@click.option(
    "--auto",
    is_flag=True,
    show_default=True,
    help="Automatically connect to all discovered GoPro cameras.",
)
@click.option(
    "--serials",
    "-s",
    help="Serial numbers of GoPro cameras to connect to. Separated by commas.",
    envvar="PYTERMITE_SERIALS",
    show_envvar=True,
    metavar="<str>",
)
@click.option(
    "--ble",
    "-b",
    help="BLE names of GoPro cameras to connect to. Separated by commas.",
    envvar="PYTERMITE_BLES",
    show_envvar=True,
    metavar="<str>",
)
@click.option(
    "--cohn",
    "-c",
    is_flag=True,
    default=False,
    help="Using provisioned COHN devices only.",
    envvar="PYTERMITE_COHN",
    show_envvar=True,
)
@click.option(
    "--serials-file",
    "-f",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a file containing serial numbers of GoPro cameras to connect to, "
    "JSON format.",
    envvar="PYTERMITE_SERIALS_PATH",
    show_envvar=True,
    metavar="<str>",
)
def connect(
    auto: bool,
    serials: str | None,
    serials_file: str | None,
    ble: str | None,
    cohn: bool,
    cohn_db: Path = COHN_DB,
) -> None:  # numpydoc ignore=GL03
    """
    Connect to one or more GoPro devices using the selected discovery method.

    \f

    Parameters
    ----------
    auto : bool
        When True, automatically discover and connect to all devices.
    serials : str | None
        Comma-separated serials provided on the command-line.
    serials_file : str | None
        Path to a JSON file containing serials.
    ble : str | None
        Comma-separated BLE names provided on the command-line.
    cohn : bool
        When True, only connect to COHN provisioned devices.
    cohn_db : str
        Path to the COHN credential database.
    """
    global GOPROS
    global BLES
    global COHN
    log = logger.bind(command="connect")
    serial_numbers: dict[str, str] | set[str] | None = None
    ble_names: dict[str, str] | set[str] | None = None
    cohn_identifiers: set[str] = set()
    cohn_db = Path(cohn_db)
    if auto:
        log = log.bind(option="auto")
        log.info("Searching for connected GoPro cameras via USB connection...")
        serial_numbers, _ = asyncio.run(
            scan_for_gopros(waiting_time=10, bluetooth=False, usb=True)
        )

        # load cohn database
        log.info("Searching for COHN provisioned GoPro cameras in database...")
        cohn_identifiers = load_cohn_identifiers(cohn_db)

        if cohn_identifiers:
            log.info(
                "Found cameras already provisioned for COHN. Connecting via network...",
                count=len(cohn_identifiers),
                identifiers=sorted(cohn_identifiers),
            )

        # bluetooth discovery
        log.info("Searching for GoPro cameras via BLE connection...")
        _, discovered_ble = asyncio.run(
            scan_for_gopros(waiting_time=10, bluetooth=True, usb=False)
        )
        ble_names = discovered_ble - cohn_identifiers
        skipped = discovered_ble & cohn_identifiers
        if serial_numbers not in (None, set()):
            ble_names = ble_names - {sn[-4:] for sn in serial_numbers}
            skipped = skipped & {sn[-4:] for sn in serial_numbers}

        if skipped:
            log.info(
                "Skipping BLE provisioning for cameras already provisioned for COHN",
                identifiers=sorted(skipped),
            )
    elif serials:
        log = log.bind(option="serials")
        log.info("Using provided serial numbers to connect to GoPro cameras...")
        serial_numbers = {s.strip() for s in serials.split(",")}
    elif serials_file:
        log = log.bind(option="serials_file")
        serials_path = Path(serials_file)
        if not serials_path.exists():
            log.warning(
                "Serials file does not exist; continuing without "
                "preconfigured serials.",
                file=str(serials_path),
            )
            serial_numbers = {}
        else:
            log.info(
                "Loading serial numbers from provided file to connect to "
                "GoPro cameras...",
            )
            serial_numbers = load_serial_numbers_from_json(serials_path)
    elif ble:
        log = log.bind(option="ble")
        log.info("Using provided ble names to connect to GoPro cameras...")
        ble_names = {n.strip() for n in ble.split(",")}
    elif cohn:
        log = log.bind(option="cohn")
        log.info("Using just provisioned COHN devices...")
        # load cohn database
        cohn_identifiers = load_cohn_identifiers(cohn_db)

        if cohn_identifiers:
            log.info(
                "Found cameras already provisioned for COHN; connecting "
                "directly without BLE...",
                count=len(cohn_identifiers),
                identifiers=sorted(cohn_identifiers),
            )
    else:
        raise click.UsageError(
            "Please specify a connection method: --auto, --serials, --ble, --cohn or "
            "--serials-file.",
        )
    if serial_numbers:
        log.debug("Serial numbers to connect to: %s", serial_numbers)
    else:
        serial_numbers = set()
        for gp in GOPROS.values():
            if isinstance(gp, WiredConnection):
                if gp.serial is not None:
                    serial_numbers.add(gp.serial)
        log.debug("Serial numbers to connect to: %s", serial_numbers)

    if ble_names:
        log.debug("BLE names to connect to: %s", ble_names)
    else:
        ble_names = set()
        for gpw in BLES.values():
            if isinstance(gpw, WirelessConnection):
                if gpw.identifier is not None:
                    ble_names.add(gpw.identifier)

    if cohn_identifiers:
        log.info("COHN identifiers to connect to: %s", cohn_identifiers)

    log.info(f"Using USB: {serial_numbers if serial_numbers else 'None'}")
    log.info(f"Using BLE: {ble_names if ble_names else 'None'}")
    log.info(f"Using COHN: {cohn_identifiers if cohn_identifiers else 'None'}")

    GOPROS = create_wired_gopros(gopro_serials=serial_numbers)
    BLES = create_wireless_gopros(gopro_names=ble_names)
    # cohn_db
    COHN = create_cohn_gopros(identifiers=cohn_identifiers, cohn_db_path=cohn_db)
    asyncio.run(_connect_to_gopros())
    failed = {**GOPROS, **BLES, **COHN}
    if failed:
        log.warning(
            f"Failed to connect to {len(failed)} of "
            f"{len(GOPROS) + len(BLES) + len(COHN) + len(CONNECTED_GOPROS)} "
            f"requested camera(s): "
            f"{sorted(failed)}"
        )
    if CONNECTED_GOPROS:
        log.info(f"Connected to {len(CONNECTED_GOPROS)} GoPro camera(s)")
    else:
        log.error("Failed to connect to any requested GoPro cameras")
    # When running inside the interactive shell the process will stay alive
    # and the user can call `disconnect` from the same shell. If invoked
    # directly from a single-shot process the CLI will exit as before.
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


async def _connect_to_gopros() -> None:
    """
    Connect to all GoPro objects stored in the global mappings.

    All GoPro objects are stored in ``CONNECTED_GOPROS``.
    """
    global GOPROS, BLES, COHN, CONNECTED_GOPROS

    def _remove_connected(
        mapping: dict[str, WiredConnection] | dict[str, WirelessConnection],
        connected: WiredConnection | WirelessConnection,
    ) -> None:
        # Remove by object identity because mapping keys can be camera names,
        # serials, or identifiers depending on how the connection was created.
        for key, value in mapping.items():
            if value is connected:
                _ = mapping.pop(key, None)
                break

    connected_cohn: list[WirelessConnection] = []
    async for gopro_cohn in connect_gopros_cohn(gopros=COHN):
        CONNECTED_GOPROS.add(gopro_cohn)
        connected_cohn.append(gopro_cohn)
    for gopro_cohn in connected_cohn:
        _remove_connected(COHN, gopro_cohn)

    connected_wired: list[WiredConnection] = []
    async for gopro in connect_gopros(gopros=GOPROS):
        CONNECTED_GOPROS.add(gopro)
        connected_wired.append(gopro)
    for gopro in connected_wired:
        _remove_connected(GOPROS, gopro)

    ssid = os.getenv("PYTERMITE_COHN_SSID")
    password = os.getenv("PYTERMITE_COHN_PASSWORD")
    if ssid and password:
        connected_wireless: list[WirelessConnection] = []
        async for gopro_wireless in connect_gopros_wireless(
            gopros=BLES,
            ssid=ssid,
            password=password,
        ):
            CONNECTED_GOPROS.add(gopro_wireless)
            connected_wireless.append(gopro_wireless)
        for gopro_wireless in connected_wireless:
            _remove_connected(BLES, gopro_wireless)
    elif BLES:
        logger.warning(
            "Skipping wireless/BLE provisioning because the required environment "
            "variables are not set: PYTERMITE_COHN_SSID and "
            "PYTERMITE_COHN_PASSWORD."
        )


@cli.command()
def list_connected() -> None:
    """List connected GoPros."""
    log = logger.bind(command="list_connected")
    log.debug("Listing connected GoPro cameras")
    global CONNECTED_GOPROS
    for gopro in CONNECTED_GOPROS:
        print("GoPro: ", gopro.identifier)


@cli.command()
def disconnect() -> None:
    """
    Disconnect from all connected GoPro cameras.

    This will gracefully close each connection stored in the global ``GOPROS``
    mapping.
    """
    log = logger.bind(command="disconnect")
    log.info("Disconnecting from all connected GoPro cameras")
    global CONNECTED_GOPROS
    asyncio.run(close_gopros(gopros=CONNECTED_GOPROS))
    CONNECTED_GOPROS = set()
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


ltc_processes: list[tuple[Process, SyncEvent]] = []
last_timecode_flag = False


@cli.command()
@click.option(
    "--no-timecode",
    "-nt",
    is_flag=True,
    show_default=False,
    help="Deactivate the use of linear timecode",
)
@click.option("--device", default=None, type=int)
@click.option("--fps", default=50, type=int)
@click.option("--sample_rate", default=48000, type=int)
@click.argument("action", type=click.Choice(["start", "stop"]))
def record(
    action: str, no_timecode: bool, device: int | None, fps: int, sample_rate: int
) -> None:  # numpydoc ignore=GL03
    """
    Start or stop recording on all currently connected GoPro cameras.

    \f

    Parameters
    ----------
    action : {"start", "stop"}
        Whether to start or stop recording.
    """
    log = logger.bind(command="record")
    global ltc_processes
    global last_timecode_flag
    global CONNECTED_GOPROS
    no_timecode = last_timecode_flag if action == "stop" else no_timecode
    last_timecode_flag = (
        (no_timecode if device is not None else True)
        if action == "start"
        else last_timecode_flag
    )
    try:
        if not no_timecode and (device is not None or action == "stop"):
            if action == "start":
                ltc_config = {"sample_rate": sample_rate, "fps": fps, "device": device}
                stop_event = Event()
                ltc_process = Process(
                    target=_run_generator, args=(ltc_config, stop_event)
                )
                ltc_process.start()
                ltc_processes.append((ltc_process, stop_event))
                time.sleep(3)
            elif action == "stop":
                for p in ltc_processes:
                    p[1].set()
        asyncio.run(camera_shutter(CONNECTED_GOPROS, action))
        if action == "stop":
            fetch_process = Process(
                target=fetch_filenames,
                args=(CONNECTED_GOPROS,),
                daemon=False,
            )
            fetch_process.start()
    except RuntimeError as e:
        log.error(str(e))
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


@cli.command()
@click.option("--save_path", default=None, type=click.Path())
def fetchdata(save_path: str | None) -> None:
    """Fetch recorded media from all connected GoPro cameras.

    Parameters
    ----------
        save_path: Directory to save the fetched media to. If None,
            a default path is used.

    Raises
    ------
        RuntimeError: If starting the fetch process fails.
    """
    log = logger.bind(command="fetch_data")
    try:
        fetch_process = Process(
            target=fetch_recorded,
            args=(CONNECTED_GOPROS, save_path),
            daemon=False,
        )
        fetch_process.start()
    except RuntimeError as e:
        log.error(str(e))
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


decode_processes: list[Process] = []


@cli.command()
@click.option("--input_path", default=None, type=click.Path())
@click.option("--fps", default=50, type=int)
@click.argument("action", type=click.Choice(["start", "stop"]))
def decode_path(action: str, input_path: str | None, fps: int) -> None:
    """Start or stop timecode decoding as a background process.

    Parameters
    ----------
        action: Either "start" to launch a decode process or "stop" to
            terminate all running decode processes.
        input_path: Path to the input file
        fps: Frame rate used for decoding

    Raises
    ------
        RuntimeError: If starting or stopping the process fails.
    """
    global decode_processes
    log = logger.bind(command="decode_path")
    try:
        if action == "start":
            p = Process(
                target=decode_timecode_batch,
                args=([(input_path, fps)], 1),
                daemon=False,
            )
            decode_processes.append(p)
            p.start()
        elif action == "stop":
            for p in decode_processes:
                p.terminate()
    except RuntimeError as e:
        log.error(str(e))
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


def _run_generator(config: dict, stop_event: SyncEvent) -> None:
    generator = LTCGenerator(config, stop_event)
    generator.run()


def _exit_handler() -> None:
    """
    Atexit handler to close connections on process exit.
    """  # ruff: ignore[D200]
    log = logger.bind()
    log.debug("Exiting pyTermite CLI")
    log.info("Closing all connections")
    global CONNECTED_GOPROS
    asyncio.run(close_gopros(gopros=CONNECTED_GOPROS))


atexit.register(_exit_handler)
