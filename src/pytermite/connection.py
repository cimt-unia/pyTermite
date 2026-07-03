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
import socket
import json
from collections.abc import AsyncGenerator
from typing import Any

import click
import structlog
from open_gopro import WiredGoPro, WirelessGoPro
from open_gopro.domain.exceptions import ResponseTimeout
from zeroconf import ServiceListener, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo
from open_gopro.models.proto import EnumCOHNNetworkState, EnumCOHNStatus
from bleak import BleakScanner
from returns.pipeline import is_successful


from pytermite.utils import (
    load_serial_numbers_from_json,
    reverse_dict,
    serialize_dict,
)

logger = structlog.get_logger()

GOPROS: set[str] = set()
BLES: set[str] = set()
INTERRUPT = False
# Get serial_numbers path from environment variable
SERIALS_PATH = os.getenv("PYTERMITE_SERIALS_PATH", None)
SERIALS = (
    load_serial_numbers_from_json(pathlib.Path(SERIALS_PATH)) if SERIALS_PATH else {}
)
COHN_DB = pathlib.Path(os.getenv("PYTERMITE_COHN_DB_PATH", "cohn_db.json"))

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


class WirelessConnection(WirelessGoPro):
    """
    Subclass of ``WirelessGoPro`` providing a cached human-readable name.
    """

    def __init__(self, **kwargs: Any) -> None:
        target = kwargs.pop("target", None)
        super().__init__(target=target, **kwargs)
        self._target: str | None = target
        # self.identifier = self._identifier

    # @property
    # async def identifier(self) -> str:

    #     return self.identifier

def create_wired_gopros(
    gopro_serials: dict[str, str] | set[str],
) -> dict[str, WiredConnection]:
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
            gopros[cam_name] = WiredConnection(serial=serial_number)
    elif isinstance(gopro_serials, set):
        for serial_number in gopro_serials:
            gopros[serial_number] = WiredConnection(serial=serial_number)
    return gopros


def create_wireless_gopros(
        gopro_names: dict[str, str] | set[str],
) -> dict[str, WirelessConnection]:
    """
    Create :py:class:`~WirelessConnection` objects for provided names.
    """
    gopros = {}
    if isinstance(gopro_names, dict):
        for cam_name, identifier in gopro_names.items():
            gopros[cam_name] = WirelessConnection(target=identifier, interfaces={WirelessGoPro.Interface.BLE, WirelessGoPro.Interface.COHN})
    elif isinstance(gopro_names, set):
        for identifier in gopro_names:
            gopros[identifier] = WirelessConnection(target=identifier, interfaces={WirelessGoPro.Interface.BLE, WirelessGoPro.Interface.COHN})
    return gopros

def load_cohn_identifiers(cohn_db_path: pathlib.Path | str = COHN_DB) -> set[str]:
    """
    Return the set of camera identifiers already provisioned for COHN.
 
    Reads the TinyDB-backed COHN credential store (as produced by
    ``open_gopro``'s ``cohn.configure()``) and collects the ``serial`` field
    of every entry, i.e. each camera's short identifier (the last 4 digits
    of its full serial number, e.g. ``"8157"``).
 
    Parameters
    ----------
    cohn_db_path : pathlib.Path | str, optional
        Path to the COHN credential database (JSON file written by TinyDB).
        Defaults to :py:data:`COHN_DB_PATH`.
 
    Returns
    -------
    set[str]
        Identifiers of cameras already provisioned for COHN. Empty if the
        database file does not exist or cannot be parsed.
    """
    cohn_db_path = pathlib.Path(cohn_db_path)
    if not cohn_db_path.exists():
        return set()
    try:
        with cohn_db_path.open("r") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to read COHN database", path=str(cohn_db_path), error=str(e)
        )
        return set()
    table = raw.get("_default", {})
    return {
        entry["serial"]
        for entry in table.values()
        if isinstance(entry, dict) and "serial" in entry
    }
 
 
def create_cohn_gopros(
    identifiers: set[str],
    cohn_db_path: pathlib.Path | str = COHN_DB,
) -> dict[str, WirelessConnection]:
    """
    Create COHN-only :py:class:`~WirelessConnection` objects for provided identifiers.
 
    Unlike :py:func:`create_wireless_gopros`, the returned connections only
    use the ``COHN`` interface: no BLE connection or provisioning will be
    attempted. This is appropriate for cameras that already have credentials
    stored in *cohn_db_path*.
 
    Parameters
    ----------
    identifiers : set[str]
        Camera identifiers (last 4 digits of serial number) to create
        connections for.
    cohn_db_path : pathlib.Path | str, optional
        Path to the COHN credential database to read credentials from.
        Defaults to :py:data:`COHN_DB_PATH`.
 
    Returns
    -------
    dict[str, WirelessConnection]
        Mapping from identifier to a COHN-only :py:class:`~WirelessConnection`.
    """
    cohn_db_path = pathlib.Path(cohn_db_path)
    gopros = {}
    for identifier in identifiers:
        gopros[identifier] = WirelessConnection(
            target=identifier,
            interfaces={WirelessGoPro.Interface.COHN},
            cohn_db=cohn_db_path,
        )
    return gopros


async def connect_gopros(
    gopros: dict[str, WiredConnection],
) -> AsyncGenerator[WiredConnection, None]:
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
            await gopro.open(retries=1, timeout=1)
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
import logging
logging.getLogger("open_gopro").setLevel(logging.DEBUG)
logging.getLogger("open_gopro").addHandler(logging.StreamHandler())

async def connect_gopros_wireless(
    gopros: dict[str, WirelessConnection],
) -> AsyncGenerator[WirelessConnection, None]:
    """
    Attempt to open a connect to each provided :py:class:`~WirelessConnection`.
    """
 
    # Iterate over a snapshot of the items rather than the live dict:
    # callers (e.g. _connect_to_gopros) commonly pop successfully-connected
    # entries out of this same dict as they're yielded, which would raise
    # "RuntimeError: dictionary changed size during iteration" if we kept
    # iterating the dict directly.
    for cam_name, gopro in list(gopros.items()):
        try:
            await gopro.open(retries=5, timeout=10)
            await logger.ainfo(
                f"Connected to {gopro.identifier}",
                cam_name=gopro.identifier,
            )
            status = (await gopro.ble_command.cohn_get_status(register=True)).data
            await logger.ainfo(f"Initial COHN status: {status}", cam_name=gopro.identifier)
 
            already_ready = (
                status.status == EnumCOHNStatus.COHN_PROVISIONED
                and status.state == EnumCOHNNetworkState.COHN_STATE_NetworkConnected
            )
 
            if already_ready:
                await logger.ainfo(
                    "COHN already provisioned and connected, skipping configure()",
                    cam_name=gopro.identifier,
                )
                
            else:
                if status.state in (
                    EnumCOHNNetworkState.COHN_STATE_ConnectingToNetwork,
                    EnumCOHNNetworkState.COHN_STATE_NetworkConnected,
                ):
                    await logger.ainfo(
                        "Camera already connecting/connected, skipping new AP request",
                        cam_name=gopro.identifier,
                    )
                else:
                    await logger.ainfo("Connecting to AP...")
                    await gopro.ble_command.request_wifi_connect_new(
                        ssid="Nothing5", password="smartwatch34"
                    )
 
                await logger.ainfo("Configure COHN...")
                result = await gopro.cohn.configure(
                    force_reprovision=(status.status == EnumCOHNStatus.COHN_UNPROVISIONED),
                    timeout=60,
                )
                if not is_successful(result):
                    # configure() only writes the camera's real IP address to
                    # the COHN db *after* it observes COHN_STATE_NetworkConnected.
                    # If we get here, that never happened (e.g. it's still
                    # stuck in COHN_STATE_ConnectingToNetwork) — the db entry
                    # for this camera has incomplete/no credentials (no IP),
                    # and it is NOT actually usable via COHN yet. Don't report
                    # it as connected.
                    await logger.aerror(
                        "COHN configuration did not complete (camera never "
                        "reached NetworkConnected — likely still associating "
                        "with the AP or failing to get an IP); camera is not "
                        "connected via COHN",
                        cam_name=gopro.identifier,
                        error=str(result.failure()),
                    )
                    continue
 
            yield gopro
        except ResponseTimeout as e:
            await logger.aerror(
                f"Failed to connect to GoPro {cam_name}",
                error=str(e),
            )

async def connect_gopros_cohn(
    gopros: dict[str, WirelessConnection],
) -> AsyncGenerator[WirelessConnection, None]:
    """
    Attempt to open a connection to each provided COHN-only :py:class:`~WirelessConnection`.
 
    Unlike :py:func:`connect_gopros_wireless`, this does not touch BLE at
    all: it connects directly over HTTPS using credentials already present
    in the COHN database (see :py:func:`create_cohn_gopros`). Intended for
    cameras that have previously been provisioned for COHN, so they can be
    reconnected quickly without re-scanning or re-provisioning via BLE.
 
    Parameters
    ----------
    gopros : dict[str, WirelessConnection]
        Mapping of camera identifiers to COHN-only :py:class:`~WirelessConnection`
        objects to connect, as created by :py:func:`create_cohn_gopros`.
 
    Yields
    ------
    WirelessConnection
        Each successfully connected :py:class:`~WirelessConnection` object.
    """
    for cam_name, gopro in list(gopros.items()):
        try:
            await gopro.open(retries=5, timeout=10)
            await logger.ainfo(f"{gopro}: {gopro.is_http_connected}")
            await logger.ainfo(f"{gopro._wifi.is_connected}")
            await logger.ainfo(
                f"Connected to {gopro.identifier} via COHN",
                cam_name=gopro.identifier,
            )
            yield gopro
        except ResponseTimeout as e:
            await logger.aerror(
                f"Failed to connect to GoPro {cam_name} via COHN",
                error=str(e),
            )
        except Exception as e:  # noqa: BLE001 - don't let one bad camera abort the rest
            await logger.aerror(
                f"Unexpected error connecting to GoPro {cam_name} via COHN",
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
    # if sys.platform.startswith("win32"):
    if True:
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
        wait_task = asyncio.create_task(wait_for_user_interrupt())
        tasks = [scan_task, wait_task]
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


async def scan_for_gopros_wireless(waiting_time: int = 20) -> set[str]:
    """
    Scan for BLE devices and retrieve identifier.

    """
    global BLES
    BLES = set()

    try:
        scan_task = asyncio.create_task(scan_for_gopros_ble())
        wait_task = asyncio.create_task(wait_for_user_interrupt())
        tasks = [scan_task, wait_task]
        await logger.adebug("Waiting for timeout", timeout=waiting_time)
        for task in asyncio.as_completed(tasks, timeout=waiting_time):
            await task
    except TimeoutError:
        await logger.ainfo("Timeout reached. Stopping...", timeout=waiting_time)
    finally:
        await logger.ainfo(f"Found {len(BLES)} devices")
        await logger.ainfo(f"Found: {BLES}")

        global INTERRUPT
        INTERRUPT = False
    return BLES

USB_IP_PATTERN = re.compile(r"^172\.2[0-9]\.1[0-9]{2}\.51$")

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
        asyncio.create_task(self._check_and_add(zc, type_, name, serial))

    async def _check_and_add(self, zc: Zeroconf, type_: str, name: str, serial: str) -> None:
        info = AsyncServiceInfo(type_, name)
        if not await info.async_request(zc, timeout=3000):
            await logger.adebug(f"Could not resolve service info for {serial}")
            return
    
        addresses = info.parsed_scoped_addresses() if hasattr(info, "parsed_scoped_addresses") else info.parsed_addresses()
        for addr in addresses:
            if USB_IP_PATTERN.match(addr):
                global GOPROS
                if serial not in GOPROS:
                    await logger.ainfo(
                        f"Found new USB-connected GoPro with serial: {serial}",
                        cam_serial=serial,
                        ip=addr,
                    )
                GOPROS.add(serial)
                return

        await logger.adebug(
            f"Ignoring GoPro {serial} — not a USB address", cam_serial=serial, addresses=addresses
        )


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


async def scan_for_gopros_ble(waiting_time: int = 20) -> set[str]:
    """
    Scan for BLE devices and retrieve identfier.
    """
    token = re.compile(r"GoPro [A-Z0-9]{4}")

    await logger.ainfo("Start scanning for GoPro BLE devices")
    waiting_time = 3
    global BLES
    global INTERRUPT
    while not INTERRUPT:
        devices = await BleakScanner.discover()
        matched_devices = [device for device in devices if device.name and token.match(device.name)]
        for d in matched_devices:
            BLES.add(d.name.split()[-1])
        await logger.adebug(f"Waiting for {waiting_time} seconds before retry")
        await asyncio.sleep(waiting_time)
    await logger.adebug("Finished scanning for GoPro BLE devices")
