"""
Connection helpers for discovering and managing wired GoPro devices.

Utilities to create connection objects for GoPro devices, scan for devices over
USB/mdns, and manage open/close life-cycle of WiredConnection objects.
"""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import os
import pathlib
import sys
import re
from collections.abc import AsyncGenerator
from typing import Any

import click
import structlog
from open_gopro import WiredGoPro, WirelessGoPro
from open_gopro.domain.exceptions import ResponseTimeout
from zeroconf import ServiceListener, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser
from bleak import BleakScanner

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
SERIALS = (
    load_serial_numbers_from_json(pathlib.Path(SERIALS_PATH)) if SERIALS_PATH else {}
)
IP_FORMAT = r"^(?:2[0-4][0-9]|25[0-5]|1?[0-9]?[0-9])[.](?:2[0-4][0-9]|25[0-5]|1?[0-9]?[0-9])[.](?:2[0-4][0-9]|25[0-5]|1?[0-9]?[0-9])[.](?:2[0-4][0-9]|25[0-5]|1?[0-9]?[0-9])$"


class WirelessConnection(WirelessGoPro):
    def __init__(self, **kwargs: Any) -> None:
        name = kwargs.pop("name", None)
        super().__init__(**kwargs)
        self._name: str | None = name
        self.mac = self._identifier

    @property
    async def name(self) -> str:
        if not self._name:
            
            info = serialize_dict(
                (await self.ble_command.get_camera_info()).data.__dict__,
            )
            name = info.get("ap_ssid", None) or info.get("name", None)
            self._name = name or reverse_dict(SERIALS)[self.identifier]
        return self._name

class WiredConnection(WiredGoPro):
    """
    Subclass of ``WiredGoPro`` providing a cached human-readable name.

    Parameters
    ----------
    **kwargs
        All keyword arguments are passed to the ``WiredGoPro`` constructor.
        The `name` keyword is reserved for an optional cached camera name that can be
        provided on initialization.
        If not provided, the name will be lazily loaded on first access by querying the
        camera's information via the HTTP API and falling back to a name derived from
        the serial numbers mapping.
    """

    def __init__(self, **kwargs: Any) -> None:
        name = kwargs.pop("name", None)
        super().__init__(**kwargs)
        self._name: str | None = name
        self.serial = self._serial

    @property
    async def name(self) -> str:
        """
        Asynchronously return the human-friendly name of the camera.

        If the name has not been determined yet this will query the camera for
        its information via the HTTP API and fall back to a name derived from
        the serial numbers mapping.

        Returns
        -------
        str
            The camera name.
        """
        if not self._name:
            info = serialize_dict(
                (await self.http_command.get_camera_info()).data.__dict__,
            )
            name = info.get("ap_ssid", None)
            self._name = name or reverse_dict(SERIALS)[self.identifier]
        return self._name


def create_wired_gopros(
    gopro_serials: dict[str, str] | set[str],
) -> dict[str, WiredConnection | WirelessConnection]:
    # TODO: this function creates Wired and(!) Wireless Connections
    """
    Create :py:class:`~WiredConnection` objects for provided serial numbers.

    Parameters
    ----------
    gopro_serials : dict[str, str] | set[str]
        Mapping from camera name to serial number, or a set of serial numbers.

    Returns
    -------
    dict[str, WiredConnection]
        Mapping from provided key (camera name or serial) to a
        :py:class:`~WiredConnection` instance.
    """
    gopros = {}
    if isinstance(gopro_serials, dict):
        for cam_name, serial_number in gopro_serials.items():
            if re.match(IP_FORMAT, serial_number):
                gopros[cam_name] = WiredConnection(serial=serial_number)
            else:
                gopros[cam_name] = WirelessConnection(mac=serial_number)
    elif isinstance(gopro_serials, set):
        for serial_number in gopro_serials:
            if re.match(IP_FORMAT, serial_number):
                gopros[serial_number] = WiredConnection(serial=serial_number)
            else:
                gopros[serial_number] = WirelessConnection(mac=serial_number)
    return gopros


async def connect_gopros(
    gopros: dict[str, WiredConnection | WirelessConnection],
) -> AsyncGenerator[WiredConnection | WirelessConnection, None]:
    """
    Attempt to open a connection to each provided :py:class:`~WiredConnection`.

    This is an async generator that yields each connected :py:class:`~WiredConnection`.

    Parameters
    ----------
    gopros : dict[str, WiredConnection]
        Mapping of camera keys to :py:class:`~WiredConnection` objects to connect.

    Yields
    ------
    WiredConnection
        Each successfully connected :py:class:`~WiredConnection` object.
    """
    for cam_name, gopro in gopros.items():
        try:
            # retries=1, timeout=1
            await gopro.open()
            await logger.ainfo(
                f"Connected to {await gopro.name}",
                cam_name=await gopro.name,
                cam_serial=gopro.identifier,
            )
            yield gopro
        except ResponseTimeout as e:
            await logger.aerror(
                f"Failed to connect to GoPro {cam_name} with serial {gopro.identifier}",
                error=str(e),
            )


async def close_gopros(
    gopros: dict[str, WiredConnection] | set[WiredConnection],
) -> None:
    """
    Close all provided :py:class:`~WiredConnection` objects.

    Parameters
    ----------
    gopros : dict[str, WiredConnection] | set[WiredConnection]
        Mapping of camera keys to :py:class:`~WiredConnection` objects to close.
    """
    if isinstance(gopros, dict):
        gopros = set(gopros.values())
    for gopro in gopros:
        await gopro.close()
        logger.debug(
            f"Disconnected from {await gopro.name}",
            cam_name=await gopro.name,
            cam_serial=gopro.identifier,
        )


async def wait_for_user_interrupt() -> None:
    """
    Wait for the user to press Enter using a non-blocking stdin reader.

    Notes
    -----
    Uses the event loop's ``add_reader`` API so the waiter can be cancelled
    immediately (the reader is removed in the finally block). This avoids the
    problem where awaiting a blocking input call prevents task cancellation.
    """
    await logger.adebug("Waiting for user interrupt")
    try:
        click.get_current_context()
        click.echo("Waiting for user input (press Enter)...")
    except RuntimeError:
        print("Waiting for user input (press Enter)...")

    loop = asyncio.get_running_loop()
    if sys.platform.startswith("win32"):
        _ = await loop.run_in_executor(None, sys.stdin.readline)
    else:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        _ = await reader.readline()

    global INTERRUPT
    INTERRUPT = True
    await logger.ainfo("User interrupt received. Stopping...")


async def scan_for_gopros(waiting_time: int = 10) -> set[str]:
    """
    Scan for connected GoPro devices via USB connection and return a set of serials.

    The scan runs until either the user requests to stop (press Enter) or the
    timeout happens. Both are executed concurrently alongside the USB
    scanning task.

    Parameters
    ----------
    waiting_time : int, optional
        Maximum seconds to wait for discovery. Default is 10.

    Returns
    -------
    set[str]
        Set of discovered device serial numbers (strings).
    """
    global GOPROS
    # reset state for each invocation
    GOPROS = set()

    try:
        scan_task = asyncio.create_task(scan_for_gopros_usb())
        ble_scan_taks = asyncio.create_task(scan_for_gopros_ble())
        wait_task = asyncio.create_task(wait_for_user_interrupt())
        tasks = [scan_task, ble_scan_taks, wait_task]
        await logger.adebug("Waiting for timeout", timeout=waiting_time)
        for task in asyncio.as_completed(tasks, timeout=waiting_time):
            await task
    except TimeoutError:
        await logger.ainfo("Timeout reached. Stopping...", timeout=waiting_time)
    finally:
        await logger.ainfo(f"Found {len(GOPROS)} devices")
        # Clean up
        global INTERRUPT
        INTERRUPT = False
    return GOPROS


class GoProListener(ServiceListener):
    """
    Service listener for mDNS services that collects discovered GoPro serial numbers.

    Implements the :py:class:`~zeroconf.ServiceListener` interface.
    Discovered serial numbers are stored in the module-level ``GOPROS`` set
    so that :py:func:`scan_for_gopros` can return them after the scan window
    closes.
    """

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:  # noqa: ARG002
        """
        Handle a newly discovered GoPro mDNS service.

        Called by zeroconf whenever a ``_gopro-web._tcp.local.`` service
        advertisement is received. The camera serial number is extracted from
        the first DNS label of *name* (the part before the first ``"."``).

        Parameters
        ----------
        zc : Zeroconf
            The :py:class:`~zeroconf.Zeroconf` instance that detected the
            service.
        type_ : str
            The mDNS service type string (e.g. ``"_gopro-web._tcp.local."``).
        name : str
            Full mDNS service name. The serial number is the first label,
            e.g. ``"C3391324497848.<type_>"``.
        """
        serial = name.split(".")[0]
        global GOPROS
        if serial not in GOPROS:
            logger.info(
                f"Found new GoPro device with serial: {serial}", cam_serial=serial
            )
        GOPROS.add(serial)


async def scan_for_gopros_usb() -> None:
    """
    Continuously scan for GoPro devices via mDNS until interrupted.

    Creates a :py:class:`~zeroconf.Zeroconf` instance, registers a
    :py:class:`GoProListener` for the ``_gopro-web._tcp.local.`` service type,
    and then suspends indefinitely while zeroconf delivers callbacks in the
    background.  Discovered serials are accumulated in the module-level
    ``GOPROS`` set.

    Notes
    -----
    This coroutine never returns on its own — it must be cancelled externally,
    for example by the :py:func:`scan_for_gopros` wrapper which imposes a
    timeout and also waits for a user interrupt.
    """
    await logger.ainfo("Start scanning for GoPro devices via mDNS")
    waiting_time = 3  # Time to wait between retries
    zeroconf = Zeroconf(unicast=True)
    listener = GoProListener()
    global INTERRUPT
    while not INTERRUPT:
        AsyncServiceBrowser(zeroconf, "_gopro-web._tcp.local.", listener)
        await logger.adebug(f"Waiting for {waiting_time} seconds before retry")
        await asyncio.sleep(waiting_time)
    await logger.adebug("Finished scanning for GoPro devices via mDNS")

async def detection_callback(device, advertisement_data):
    friendly_name = advertisement_data.local_name
    global GOPROS
    if friendly_name and friendly_name.startswith("GoPro"):
        GOPROS.add(device.address)
        await logger.ainfo(f"Found {friendly_name} at {device.address}")

async def scan_for_gopros_ble() -> None:
    """
    Continuously scan for GoPro devices via Bluetooth Low Energy (BLE)
    until interrupted.
    """
    await logger.ainfo("Start scanning for GoPro devices via Bluetooth")

    scanner = BleakScanner(detection_callback)
    await scanner.start()
    try:
        while not INTERRUPT:
            await asyncio.sleep(1)
    finally:
        await scanner.stop()

    await logger.adebug("Finished scanning for GoPro devices via Bluetooth")