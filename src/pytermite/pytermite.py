#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import atexit

import click
import structlog

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

logger = structlog.get_logger()


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(None, "-v", "--version")
def cli():
    """pyTermite CLI - Control multiple GoPro cameras via USB connection."""
    pass


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
        log.info("Searching for connected GoPro cameras via USB connection...")
        serial_numbers = asyncio.run(scan_for_gopros(timeout=5))
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
    log.info("Connected to all requested GoPro cameras.")
    # Keep connection alive and wait for other commands until disconnect command is issued or user interrupts the program


async def connect_to_gopros() -> None:
    global GOPROS, CONNECTED_GOPROS
    async for gopro in connect_gopros(gopros=GOPROS):
        CONNECTED_GOPROS.add(gopro)


@click.command()
def disconnect():
    log = logger.bind()
    log.info("Disconnecting from all connected GoPro cameras.")
    global GOPROS
    asyncio.run(close_gopros(gopros=GOPROS))


cli.add_command(scan)
cli.add_command(connect)
cli.add_command(disconnect)


def exit_handler():
    log = logger.bind()
    log.info("Exiting pyTermite CLI. Closing all connections.")
    global GOPROS
    asyncio.run(close_gopros(gopros=GOPROS))


atexit.register(exit_handler)
