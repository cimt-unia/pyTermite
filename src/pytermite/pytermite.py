#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import atexit
import shlex
from pathlib import Path

import click
import structlog
from click import UsageError

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

logger = structlog.get_logger()


def _setup_history():
    """Try to enable readline history and persist it in the user's home dir.
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
                pass

            def _save_hist():
                try:
                    readline.write_history_file(str(histfile))
                except Exception:
                    pass

            atexit.register(_save_hist)
        except Exception:
            pass
    except Exception:
        pass


def run_repl(ctx):
    """Run the interactive REPL. Extracted so it can be reused after a
    subcommand completes when the user requested to stay interactive.
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
        if not line:
            continue

        if line == "help":
            click.echo(ctx.get_help())
            continue

        if line in ("exit", "quit"):
            break

        # allow running shell-style comments
        if line.startswith("#"):
            continue

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
    help="After running a command, keep the process open and enter the interactive shell.",
)
@click.version_option(None, "-v", "--version")
@click.pass_context
def cli(ctx, interactive):
    """pyTermite CLI - Control multiple GoPro cameras via USB connection.

    When invoked without a subcommand this CLI will enter an interactive REPL
    allowing multiple commands to be executed without exiting the process.
    If started with --interactive the CLI will stay open after running a
    subcommand and drop into the interactive REPL.
    """
    # Store the interactive preference globally so individual commands can
    # decide whether to drop into the REPL after finishing.
    global KEEP_OPEN
    KEEP_OPEN = bool(interactive)

    # If a subcommand was supplied, let click dispatch normally.
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand: start the interactive REPL.
    run_repl(ctx)


@click.command()
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=10,
    help="Time to wait for GoPro devices to be discovered (in seconds).",
)
def scan(timeout):
    asyncio.run(scan_for_gopros(timeout=timeout))
    if KEEP_OPEN:
        run_repl(click.get_current_context())


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
    help="Path to a file containing serial numbers of GoPro cameras to connect to, JSON format.",
    envvar="PYTERMITE_SERIALS_PATH",
)
def connect(auto, serials, serials_file):
    log = logger.bind(command="connect")
    if auto:
        log = log.bind(option="auto")
        from pytermite.connection import GOPROS as cached_gopros
        if len(cached_gopros) == 0:
            log.info("Searching for connected GoPro cameras via USB connection...")
            serial_numbers = asyncio.run(scan_for_gopros(timeout=5))
        else:
            log.info("Using previously discovered GoPro cameras to connect...")
            serial_numbers = cached_gopros
    elif serials:
        log = log.bind(option="serials")
        log.info("Using provided serial numbers to connect to GoPro cameras...")
        serials = [s.strip() for s in serials.split(",")]
        serial_numbers = set(serials)
    elif serials_file:
        log = log.bind(option="serials_file")
        log.info("Loading serial numbers from provided file to connect to GoPro cameras...")
        serial_numbers = load_serial_numbers_from_json(serials_file)
    else:
        raise click.UsageError(
            "Please specify a connection method: --auto, --serials, or --serials-file."
        )
    log.debug(f"Serial numbers to connect to: {serial_numbers}")
    global GOPROS
    GOPROS = create_wired_gopros(gopro_serials=serial_numbers)
    asyncio.run(connect_to_gopros())
    log.info("Connected to all requested GoPro cameras")
    # When running inside the interactive shell the process will stay alive
    # and the user can call `disconnect` from the same shell. If invoked
    # directly from a single-shot process the CLI will exit as before.
    if KEEP_OPEN:
        run_repl(click.get_current_context())


async def connect_to_gopros() -> None:
    global GOPROS, CONNECTED_GOPROS
    async for gopro in connect_gopros(gopros=GOPROS):
        CONNECTED_GOPROS.add(gopro)


@click.command()
def disconnect():
    log = logger.bind()
    log.info("Disconnecting from all connected GoPro cameras")
    global GOPROS
    asyncio.run(close_gopros(gopros=GOPROS))
    if KEEP_OPEN:
        run_repl(click.get_current_context())


cli.add_command(scan)
cli.add_command(connect)
cli.add_command(disconnect)


def exit_handler():
    log = logger.bind()
    log.info("Exiting pyTermite CLI")
    log.info("Closing all connections")
    global GOPROS
    asyncio.run(close_gopros(gopros=GOPROS))


atexit.register(exit_handler)
