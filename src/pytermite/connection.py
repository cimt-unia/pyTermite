"""
Connection helpers for discovering and managing wired GoPro devices.

Utilities to create connection objects for GoPro devices, scan for devices over
USB/mdns, and manage open/close life-cycle of WiredConnection objects.
"""

#  Copyright (c) 2026 by Lukas Behammer, Patrick Braun, Jonas Rostan
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import json
import os
import pathlib
import re
import sys
import tempfile
import traceback
from collections.abc import AsyncGenerator
from typing import Any

import click
import requests
import structlog
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from open_gopro import WiredGoPro, WirelessGoPro
from open_gopro.domain.exceptions import ResponseTimeout
from open_gopro.models.proto import EnumCOHNNetworkState, EnumCOHNStatus
from requests import Response
from zeroconf import ServiceListener, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo

from pytermite.config import resolve_config_path
from pytermite.utils import (
    load_serial_numbers_from_json,
    reverse_dict,
    serialize_dict,
)

logger = structlog.get_logger()

GOPROS: set[str] = set()
BLES: set[str] = set()
INTERRUPT: asyncio.Event
SERIALS_PATH = resolve_config_path(
    "PYTERMITE_SERIALS_PATH",
    default_filename="serials.json",
)
SERIALS = load_serial_numbers_from_json(SERIALS_PATH) if SERIALS_PATH.exists() else {}
COHN_DB = resolve_config_path(
    "PYTERMITE_COHN_DB_PATH",
    default_filename="cohn_db.json",
)
USB_IP_PATTERN = re.compile(r"^172\.2[0-9]\.1[0-9]{2}\.51$")


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
        self._identifier: str | None = None
        if self.serial is not None:
            self._identifier = self.serial[-4:]
        else:
            logger.warning("Serial number could not be determined for WiredConnection.")

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
    """Subclass of ``WirelessGoPro`` providing a cached human-readable name."""

    def __init__(self, **kwargs: Any) -> None:
        target = kwargs.pop("target", None)
        super().__init__(target=target, **kwargs)
        self._target: str | None = target
        self._should_maintain_state = False  # TODO: untested!
        # self.identifier = self._identifier

    # @property
    # async def identifier(self) -> str:

    #     return self.identifier


def make_gopro_request(
    connection: WirelessConnection | WiredConnection,
    request_path: str,
    timeout: int = 10,
) -> Response | None:
    """
    Make GET request to provided GoPro Connection.

    Parameters
    ----------
    connection : WirelessConnection | WiredConnection
        Connection Object to be used for request
    request_path : str
        GoPro internal http request path
    timeout: int = 10
        Timeout used for request

    Returns
    -------
    Response | None
        Response created by made request,
        None if no valid connection is provided
    """
    response = None
    if isinstance(connection, WirelessConnection):
        if connection.cohn.credentials is None:
            logger.warning("Connection does not have Cohn credentials.")
            return None
        url = f"https://{connection.ip_address}/{request_path}"
        cert_string = connection.cohn.credentials.certificate

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pem") as f:
            f.write(cert_string)
            cert_path = f.name

        auth = (
            connection.cohn.credentials.username,
            connection.cohn.credentials.password,
        )
        try:
            response = requests.request(
                "GET", url, verify=cert_path, auth=auth, timeout=timeout
            )
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Request failed for GoPro {connection.identifier} at {url}",
                cam_serial=connection.identifier,
                url=url,
                error=str(e),
            )
            pass
        finally:
            pathlib.Path(cert_path).unlink()

    elif isinstance(connection, WiredConnection):
        try:
            url = f"http://{connection.ip_address}/{request_path}"
            response = requests.request("GET", url, timeout=timeout)
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Request failed for GoPro {connection.identifier} at {url}",
                cam_serial=connection.identifier,
                url=url,
                error=str(e),
            )
            pass
    return response


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

    Parameters
    ----------
    gopro_names : dict[str, str] | set[str]
        Mapping from camera name to target identifier, or a set of target identifiers.

    Returns
    -------
    dict[str, WirelessConnection]
        Mapping from provided key (camera name or target identifier) to a
        :py:class:`~WirelessConnection` instance.
    """
    gopros = {}
    if isinstance(gopro_names, dict):
        for cam_name, identifier in gopro_names.items():
            gopros[cam_name] = WirelessConnection(
                target=identifier,
                interfaces={WirelessGoPro.Interface.BLE, WirelessGoPro.Interface.COHN},
                keep_alive_interval=10,
                maintain_state=False,
                cohn_db=COHN_DB,
            )
    elif isinstance(gopro_names, set):
        for identifier in gopro_names:
            gopros[identifier] = WirelessConnection(
                target=identifier,
                interfaces={WirelessGoPro.Interface.BLE, WirelessGoPro.Interface.COHN},
                keep_alive_interval=10,
                maintain_state=False,
                cohn_db=COHN_DB,
            )
    return gopros


def load_cohn_identifiers(cohn_db_path: pathlib.Path | str = COHN_DB) -> set[str]:
    """
    Return the set of camera identifiers already provisioned for COHN.

    Reads the TinyDB-backed COHN credential store (as produced by
    ``open_gopro``'s ``cohn.configure()``) and collects the ``target identifier`` field
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
        Camera target identifiers (last 4 digits of serial number) to create
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


async def connect_gopros_wireless(
    gopros: dict[str, WirelessConnection],
    ssid: str,
    password: str,
) -> AsyncGenerator[WirelessConnection, None]:
    """
    Attempt to open a connection to each provided :py:class:`~WirelessConnection`.

    This is an async generator that yields each connected
    :py:class:`~WirelessConnection`.

    Parameters
    ----------
    gopros : dict[str, WirelessConnection]
        Mapping of camera keys to :py:class:`~WirelessConnection` objects to connect.
    ssid : str
        SSID of the Wi-Fi network to connect the cameras to.
    password : str
        Password of the Wi-Fi network to connect the cameras to.

    Yields
    ------
    WirelessConnection
        Each successfully connected :py:class:`~WirelessConnection` object.
    """
    for cam_name, gopro in list(gopros.items()):
        try:
            await gopro.open(retries=5, timeout=10)
            await logger.ainfo(f"Connected to {gopro.identifier}", cam_name=cam_name)

            status = (await gopro.ble_command.cohn_get_status(register=True)).data
            await logger.ainfo(
                f"Initial COHN status: {status.status}", cam_name=cam_name
            )
            await logger.ainfo(f"Initial COHN state: {status.state}", cam_name=cam_name)

            if gopro.cohn.credentials is not None:
                already_ready = (
                    status.status == EnumCOHNStatus.COHN_PROVISIONED
                    and status.state == EnumCOHNNetworkState.COHN_STATE_NetworkConnected
                    and gopro.cohn.credentials.ip_address != ""
                )
            else:
                already_ready = None

            if already_ready:
                await logger.ainfo(
                    "COHN already provisioned and connected, skipping configure()",
                    cam_name=cam_name,
                )
            else:
                await logger.ainfo("Connecting to AP...", cam_name=cam_name)
                await gopro.access_point.connect(ssid, password)

                await logger.ainfo("Configure COHN...", cam_name=cam_name)
                result = await gopro.cohn.configure(
                    force_reprovision=(
                        status.status == EnumCOHNStatus.COHN_UNPROVISIONED
                    ),
                    timeout=60,
                )
                await logger.adebug(result, cam_name=cam_name)

            yield gopro

        except ResponseTimeout as e:
            await logger.aerror(
                f"Timed out connecting to GoPro {cam_name}",
                error=str(e),
            )
        except Exception as e:
            await logger.aerror(
                f"Failed to connect to GoPro {cam_name}",
                error=str(e),
            )


async def connect_gopros_cohn(
    gopros: dict[str, WirelessConnection],
    waiting_time: int = 2,
) -> AsyncGenerator[WirelessConnection, None]:
    # ruff: ignore[E501]
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
    waiting_time : int, optional
        Maximum seconds to wait until connection. Default is 2.

    Yields
    ------
    WirelessConnection
        Each successfully connected :py:class:`~WirelessConnection` object.
    """
    for cam_name, gopro in list(gopros.items()):
        try:
            await gopro.open(retries=1, timeout=waiting_time)
            if gopro.cohn.credentials is not None:
                ip, port = gopro.cohn.credentials.ip_address, 443
                await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=waiting_time
                )
            else:
                logger.warning("Connection does not have Cohn credentials.")
        except (TimeoutError, OSError):
            await logger.ainfo(
                "Camera unreachable via COHN (Request Timed Out)", cam_name=cam_name
            )
            continue

        try:
            try:
                await asyncio.wait_for(
                    gopro.http_command.get_camera_state(), timeout=waiting_time
                )
                await logger.ainfo("Successfully connected", cam_name=cam_name)
                yield gopro

            except requests.exceptions.ConnectionError as e:
                await logger.ainfo(
                    "Camera network error via COHN", cam_name=cam_name, error=str(e)
                )
                continue

        except Exception as e:
            tb_str = traceback.format_exc()
            await logger.ainfo(
                "Failed to establish GoPro session",
                cam_name=cam_name,
                error=str(e),
                traceback=tb_str,
            )
            continue


async def close_gopros(
    gopros: dict[str, WiredConnection]
    | dict[str, WirelessConnection]
    | set[WiredConnection | WirelessConnection],
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
        if isinstance(gopro, WiredConnection):
            await gopro.close()
            logger.debug(
                f"Disconnected from {await gopro.name}",
                cam_name=await gopro.name,
                cam_serial=gopro.identifier,
            )
        elif isinstance(gopro, WirelessConnection):
            await gopro.close()
            logger.debug(
                f"Disconnected from {gopro.identifier}",
                cam_name=gopro.identifier,
            )


async def _wait_for_user_interrupt_windows() -> None:
    """
    Wait for the user to press Enter on Windows.

    Notes
    -----
    Polls ``msvcrt`` in short intervals so task cancellation is handled
    cooperatively by the event loop.
    """
    if sys.platform == "win32":
        import msvcrt

        while True:
            if msvcrt.kbhit() and msvcrt.getwch() in {"\r", "\n"}:
                return
            await asyncio.sleep(0.05)
    else:
        raise NotImplementedError(
            "Windows-specific function called on non-Windows platform"
        )


async def _wait_for_user_interrupt_unix() -> None:
    """
    Wait for the user to press Enter on Unix-like systems.

    Notes
    -----
    Uses the event loop's ``add_reader`` API so the wait can be cancelled
    without leaving a background stdin reader running.
    """
    loop = asyncio.get_running_loop()
    input_ready = loop.create_future()
    stdin_fd = sys.stdin.fileno()

    def _on_stdin_ready() -> None:
        if input_ready.done():
            return
        try:
            _ = sys.stdin.readline()
        except OSError as exc:
            input_ready.set_exception(exc)
        else:
            input_ready.set_result(None)

    loop.add_reader(stdin_fd, _on_stdin_ready)
    try:
        await input_ready
    finally:
        loop.remove_reader(stdin_fd)


async def wait_for_user_interrupt() -> None:
    """
    Wait for the user to press Enter using a non-blocking stdin reader.

    Notes
    -----
    Uses platform-specific non-blocking stdin handling so the waiter can be
    cancelled immediately when the outer scan times out.
    """
    await logger.adebug("Waiting for user interrupt")
    try:
        click.get_current_context()
        click.echo("Waiting for user input (press Enter)...")
    except RuntimeError:
        print("Waiting for user input (press Enter)...")

    if sys.platform == "win32":
        await _wait_for_user_interrupt_windows()
    elif sys.platform == "linux" or sys.platform == "darwin":
        await _wait_for_user_interrupt_unix()
    else:
        logger.warning("Unsupported operating system: %s.", sys.platform)

    global INTERRUPT
    INTERRUPT.set()
    await logger.ainfo("User interrupt received. Stopping...")


async def scan_for_gopros(
    waiting_time: int = 10, bluetooth: bool = False, usb: bool = True
) -> tuple[set[str], set[str]]:
    """
    Scan for connected GoPro devices via USB connection and return a set of serials.

    The scan runs until either the user requests to stop (press Enter) or the
    timeout happens. Both are executed concurrently alongside the USB
    scanning task.

    Parameters
    ----------
    waiting_time : int, optional
        Maximum seconds to wait for discovery. Default is 10.
    bluetooth : bool, optional
        Whether to also scan for BLE devices. Default is False.
    usb : bool, optional
        Whether to scan for USB devices. Default is True.

    Returns
    -------
    set[str]
        Set of discovered device serial numbers (strings).
    """
    if not usb and not bluetooth:
        raise ValueError("At least one of usb or bluetooth must be True")

    global GOPROS, BLES, INTERRUPT
    INTERRUPT = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    # reset state for each invocation
    GOPROS = set()
    BLES = set()

    try:
        if usb:
            tasks.append(asyncio.create_task(scan_for_gopros_usb()))
        if bluetooth and os.getenv("PYTERMITE_BLUETOOTH_AVAILABLE") == "true":
            tasks.append(asyncio.create_task(scan_for_gopros_ble()))
        elif bluetooth and os.getenv("PYTERMITE_BLUETOOTH_AVAILABLE") == "false":
            await logger.awarning("Bluetooth is not available. Skipping BLE discovery.")
        tasks.append(asyncio.create_task(wait_for_user_interrupt()))
        await logger.adebug("Waiting for timeout", timeout=waiting_time)
        for task in asyncio.as_completed(tasks, timeout=waiting_time):
            await task
    except TimeoutError:
        await logger.ainfo("Timeout reached. Stopping...", timeout=waiting_time)
    finally:
        # Clean up
        INTERRUPT.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException) and not isinstance(
                result, asyncio.CancelledError
            ):
                raise result
        if usb:
            await logger.ainfo(f"Found {len(GOPROS)} devices")
        if bluetooth:
            await logger.ainfo(f"Found {len(BLES)} devices")
        INTERRUPT.clear()
    return GOPROS, BLES


class GoProListener(ServiceListener):
    """
    Service listener for mDNS services that collects discovered GoPro serial numbers.

    Implements the :py:class:`~zeroconf.ServiceListener` interface.
    Discovered serial numbers are stored in the module-level ``GOPROS`` set
    so that :py:func:`scan_for_gopros` can return them after the scan window
    closes.
    """

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
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
        # ruff: ignore[RUF006]
        asyncio.create_task(self._check_and_add(zc, type_, name, serial))

    @staticmethod
    async def _check_and_add(zc: Zeroconf, type_: str, name: str, serial: str) -> None:
        info = AsyncServiceInfo(type_, name)
        if not await info.async_request(zc, timeout=3000):
            await logger.adebug(f"Could not resolve service info for {serial}")
            return

        addresses = (
            info.parsed_scoped_addresses()
            if hasattr(info, "parsed_scoped_addresses")
            else info.parsed_addresses()
        )
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
            f"Ignoring GoPro {serial} — not a USB address",
            cam_serial=serial,
            addresses=addresses,
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
    while not INTERRUPT.is_set():
        AsyncServiceBrowser(zeroconf, "_gopro-web._tcp.local.", listener)
        await logger.adebug(f"Waiting for {waiting_time} seconds before retry")
        await asyncio.sleep(waiting_time)
    await logger.adebug("Finished scanning for GoPro devices via mDNS")


async def scan_for_gopros_ble() -> None:
    """
    Continuously scan for GoPro devices using Bluetooth Low Energy until interrupted.

    If bluetooth is available, this function scans for BLE devices and
    retrieves the identifier of the GoPro cameras. The identifiers are
    accumulated in the module-level ``BLES`` set.

    Notes
    -----
    This coroutine never returns on its own — it must be cancelled externally,
    for example by the :py:func:`scan_for_gopros` wrapper which imposes a
    timeout and also waits for a user interrupt.
    """
    if os.getenv("PYTERMITE_BLUETOOTH_AVAILABLE") == "false":
        await logger.awarning("Bluetooth is not available. Skipping BLE discovery.")
        return

    token = re.compile(r"GoPro [A-Z0-9]{4}")
    global BLES
    global INTERRUPT

    await logger.ainfo("Start scanning for GoPro BLE devices")

    def detection_callback(
        device: BLEDevice, advertisment_data: AdvertisementData
    ) -> None:
        name = device.name or advertisment_data.local_name
        if name and token.match(name):
            cam_id = name.split()[-1]
            BLES.add(cam_id)

    while not INTERRUPT.is_set():
        async with BleakScanner(detection_callback=detection_callback):
            await INTERRUPT.wait()

    await logger.adebug("Finished scanning for GoPro BLE devices")
