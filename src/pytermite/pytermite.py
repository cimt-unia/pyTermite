"""
`pyTermite` command line interface and REPL utilities.

Provides a Click-based CLI for discovering, connecting to and controlling
multiple GoPro devices. Includes an interactive REPL for repeated commands.
"""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import atexit
import enum
import shlex
from pathlib import Path

import click
import structlog
from click import UsageError

from pytermite.commands import camera_shutter
from pytermite.connection import (
    WiredConnection,
    close_gopros,
    connect_gopros,
    create_wired_gopros,
    scan_for_gopros,
)
from pytermite.utils import load_serial_numbers_from_json

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
GOPROS: dict[str, WiredConnection] = {}
CONNECTED_GOPROS: set[WiredConnection] = set()
KEEP_OPEN = False


class _LineContinue(enum.StrEnum):
    """Special return values for to control REPL flow."""

    CONTINUE = "continue"
    BREAK = "break"


logger = structlog.get_logger()


def _setup_history() -> None:
    """
    Try to enable readline history and persist it in the user's home dir.

    Silently ignore failures.
    """
    try:
        import readline  # optional: enables convenient command-line editing and history

        try:
            histfile = Path("~/.pytermite_history").expanduser()
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
        except UsageError:
            click.echo(info_str)
            continue
        except Exception as e:
            log.exception("Error while executing command", error=str(e))

    log.debug("Leaving interactive shell")


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    help="After running a command, keep the process open and enter the interactive "
    "shell.",
)
@click.version_option(None, "-v", "--version")
@click.pass_context
def cli(ctx: click.Context, interactive: bool) -> None:
    """
    `pyTermite` CLI - Control multiple GoPro cameras via USB connection.

    When invoked without a subcommand this CLI will enter an interactive REPL
    allowing multiple commands to be executed without exiting the process.
    If started with --interactive the CLI will stay open after running a
    subcommand and drop into the interactive REPL.

    Parameters
    ----------
    ctx : click.Context
        Click context used to provide help text and program name inside the REPL.
    interactive : bool
        Whether to keep the process open and enter the interactive shell after
        running a command.
    """
    # Store the interactive preference globally so individual commands can
    # decide whether to drop into the REPL after finishing.
    global KEEP_OPEN
    KEEP_OPEN = bool(interactive)

    # If a subcommand was supplied, let click dispatch normally.
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand: start the interactive REPL.
    _run_repl(ctx)


@click.command()
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=10,
    help="Time to wait for GoPro devices to be discovered (in seconds).",
)
def scan(timeout: int) -> None:
    """
    Discover GoPro devices via USB and mDNS.

    Parameters
    ----------
    timeout : int
        How long to wait for discovery in seconds.
    """
    asyncio.run(scan_for_gopros(waiting_time=timeout))
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


@click.command()
@click.option(
    "--auto",
    is_flag=True,
    help="Automatically connect to all discovered GoPro cameras.",
)
@click.option(
    "--serials",
    "-s",
    help="Serial numbers of GoPro cameras to connect to. Separated by commas.",
    envvar="PYTERMITE_SERIALS",
)
@click.option(
    "--serials-file",
    "-f",
    type=click.Path(exists=True),
    help="Path to a file containing serial numbers of GoPro cameras to connect to, "
    "JSON format.",
    envvar="PYTERMITE_SERIALS_PATH",
)
def connect(auto: bool, serials: str | None, serials_file: str | None) -> None:
    """
    Connect to one or more GoPro devices using the selected discovery method.

    Parameters
    ----------
    auto : bool
        When True, automatically discover and connect to all devices.
    serials : str | None
        Comma-separated serials provided on the command-line.
    serials_file : str | None
        Path to a JSON file containing serials.
    """
    global GOPROS
    log = logger.bind(command="connect")
    serial_numbers: dict[str, str] | set[str] | None = None
    if auto:
        log = log.bind(option="auto")
        if len(GOPROS) == 0:
            log.info("Searching for connected GoPro cameras via USB connection...")
            serial_numbers = asyncio.run(scan_for_gopros(waiting_time=5))
        else:
            log.info("Using previously discovered GoPro cameras to connect...")
            pass
    elif serials:
        log = log.bind(option="serials")
        log.info("Using provided serial numbers to connect to GoPro cameras...")
        serial_numbers = {s.strip() for s in serials.split(",")}
    elif serials_file:
        log = log.bind(option="serials_file")
        log.info(
            "Loading serial numbers from provided file to connect to GoPro cameras...",
        )
        serial_numbers = load_serial_numbers_from_json(serials_file)
    else:
        raise click.UsageError(
            "Please specify a connection method: --auto, --serials, or --serials-file.",
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
    GOPROS = create_wired_gopros(gopro_serials=serial_numbers)
    asyncio.run(_connect_to_gopros())
    log.info("Connected to all requested GoPro cameras")
    # When running inside the interactive shell the process will stay alive
    # and the user can call `disconnect` from the same shell. If invoked
    # directly from a single-shot process the CLI will exit as before.
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


async def _connect_to_gopros() -> None:
    """
    Connect to all GoPro objects stored in the global ``GOPROS`` mapping.

    Yields
    ------
    None
        This function adds connected WiredConnection objects to the global
        ``CONNECTED_GOPROS`` set as a side-effect.
    """
    global GOPROS, CONNECTED_GOPROS
    async for gopro in connect_gopros(gopros=GOPROS):
        CONNECTED_GOPROS.add(gopro)


@click.command()
def disconnect() -> None:
    """
    Disconnect from all connected GoPro cameras.

    This will gracefully close each connection stored in the global ``GOPROS``
    mapping.
    """
    log = logger.bind()
    log.info("Disconnecting from all connected GoPro cameras")
    global GOPROS
    asyncio.run(close_gopros(gopros=GOPROS))
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


@click.command()
@click.argument("action", type=click.Choice(["start", "stop"]))
def record(action: str) -> None:
    """
    Start or stop recording on all currently connected GoPro cameras.

    Parameters
    ----------
    action : {"start", "stop"}
        Whether to start or stop recording.
    """
    log = logger.bind(command="record")
    global CONNECTED_GOPROS
    try:
        asyncio.run(camera_shutter(CONNECTED_GOPROS, action))
    except RuntimeError as e:
        log.error(str(e))
    if KEEP_OPEN:
        _run_repl(click.get_current_context())


cli.add_command(scan)
cli.add_command(connect)
cli.add_command(record)
cli.add_command(disconnect)


def _exit_handler() -> None:
    """
    Atexit handler to close connections on process exit.
    """  # noqa: D200
    log = logger.bind()
    log.info("Exiting pyTermite CLI")
    log.info("Closing all connections")
    global GOPROS
    asyncio.run(close_gopros(gopros=GOPROS))


atexit.register(_exit_handler)
