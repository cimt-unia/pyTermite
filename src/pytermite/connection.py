#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import os
import pathlib

import click
import structlog
from open_gopro import WiredGoPro
from open_gopro.domain.exceptions import FailedToFindDevice, ResponseTimeout
from open_gopro.network.wifi.mdns_scanner import find_first_ip_addr
from open_gopro.util import ainput

from pytermite.utils import (
    load_serial_numbers_from_json,
    reverse_dict,
    serialize_dict,
)

logger = structlog.get_logger()

GOPROS: set[str] = set()
INTERRUPT = False
# Get serial_numbers path from environment variable
SERIALS_PATH = os.getenv("PYTERMITE_SERIALS_PATH", None)
SERIALS = load_serial_numbers_from_json(pathlib.Path(SERIALS_PATH)) if SERIALS_PATH else {}


class WiredConnection(WiredGoPro):
    """Subclass of WiredGoPro to allow future extensions."""

    def __init__(self, **kwargs):
        name = kwargs.pop("name", None)
        super().__init__(**kwargs)
        self._name: str | None = None

    @property
    async def name(self):
        if not self._name:
            info = serialize_dict(
                (await self.http_command.get_camera_info()).data.__dict__
            )
            name = info.get("ap_ssid", None)
            self._name = name or reverse_dict(SERIALS)[self.identifier]
        return self._name


def create_wired_gopros(gopro_serials: dict[str, str] | set[str]) -> dict[str, WiredConnection]:
    gopros = {}
    if isinstance(gopro_serials, dict):
        for cam_name, serial_number in gopro_serials.items():
            gopros[cam_name] = WiredConnection(serial=serial_number)
    elif isinstance(gopro_serials, set):
        for serial_number in gopro_serials:
            gopros[serial_number] = WiredConnection(serial=serial_number)
    return gopros


async def connect_gopros(gopros: dict[str, WiredConnection]):
    for cam_name, gopro in gopros.items():
        try:
            await gopro.open(retries=1, timeout=1)
            await logger.ainfo(f"Connected to {await gopro.name}")
            yield gopro
        except ResponseTimeout as e:
            await logger.aerror(
                f"Failed to connect to GoPro {cam_name} with serial "
                f"{gopro.identifier}", error=str(e)
            )


async def close_gopros(gopros: dict[str, WiredConnection]):
    for _, gopro in gopros.items():
        await gopro.close()
        logger.debug(f"Disconnected from {await gopro.name}")


async def wait_for_user_interrupt() -> None:
    global INTERRUPT
    while not INTERRUPT:
        await ainput("Press Enter to stop scanning...\n")
        await logger.ainfo("Stopping...")
        INTERRUPT = True


async def wait_for_timeout(timeout: int) -> None:
    await logger.ainfo(f"Waiting for {timeout} seconds...")
    global INTERRUPT
    while not INTERRUPT:
        await asyncio.sleep(timeout)
        await logger.ainfo("Timeout reached. Stopping...")
        INTERRUPT = True


async def scan_for_gopros(timeout: int = 10) -> set[str]:
    """Scan for connected GoPro devices via USB connection and print their names."""
    async with asyncio.TaskGroup() as tg:
        gopros = tg.create_task(scan_for_gopros_usb())
        # tg.create_task(wait_for_user_interrupt())
        tg.create_task(wait_for_timeout(timeout))
    return gopros.result()


async def scan_for_gopros_usb() -> set[str]:
    global GOPROS
    global INTERRUPT
    while not INTERRUPT:
        try:
            response = await find_first_ip_addr(
                WiredConnection._MDNS_SERVICE_NAME, timeout=2
            )
            name = response.name.split(".")[0]
            if name not in GOPROS:
                await logger.ainfo(f"Found new GoPro device with serial: {name}")
            GOPROS.add(name)
        except FailedToFindDevice:
            continue
    return GOPROS
