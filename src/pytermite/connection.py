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

import structlog
from open_gopro import WiredGoPro
from open_gopro.domain.exceptions import FailedToFindDevice, ResponseTimeout
from open_gopro.network.wifi.mdns_scanner import find_first_ip_addr

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
    load_serial_numbers_from_json(pathlib.Path(SERIALS_PATH))
    if SERIALS_PATH
    else {}
)


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


def create_wired_gopros(
    gopro_serials: dict[str, str] | set[str]
) -> dict[str, WiredConnection]:
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
    """Wait for the user to press Enter using a non-blocking stdin reader.

    This uses the event loop's add_reader API so the waiter can be cancelled
    immediately (the reader is removed in the finally block). This avoids the
    problem where awaiting a blocking input call prevents task cancellation.
    """
    await logger.adebug("Waiting for user interrupt (press Enter)...")
    global INTERRUPT
    loop = asyncio.get_running_loop()
    fd = sys.stdin.fileno()
    event = asyncio.Event()

    def _on_input() -> None:
        """Callback run when stdin is readable (user pressed Enter).

        Read and discard the line, set the global interrupt flag and the
        event so the coroutine can continue.
        """
        try:
            # consume the input line so the next read is fresh
            # use os.read on the fd to avoid potential blocking text IO
            try:
                _ = os.read(fd, 4096)
            except Exception:
                # fallback to readline if os.read fails for any reason
                try:
                    _ = sys.stdin.readline()
                except Exception:
                    pass
        except Exception:
            pass
        # log asynchronously; schedule it on the loop
        try:
            loop.create_task(logger.ainfo("Stopping..."))
        except Exception:
            pass
        # set global flag and notify the waiting coroutine
        try:
            global INTERRUPT
            INTERRUPT = True
        except Exception:
            pass
        event.set()

    # Register the reader and await the event. Use the file descriptor
    # (integer) which is the expected argument for add_reader/remove_reader.
    # wrap the callback in a no-arg lambda so the add_reader signature is satisfied
    loop.add_reader(fd, lambda: _on_input())
    try:
        await event.wait()
    finally:
        # Ensure removal is attempted but ignore if it's already gone.
        try:
            loop.remove_reader(fd)
        except Exception:
            pass


async def wait_for_timeout(timeout: int) -> None:
    await logger.ainfo(f"Waiting for {timeout} seconds...")
    global INTERRUPT
    while not INTERRUPT:
        await asyncio.sleep(timeout)
        await logger.ainfo("Timeout reached. Stopping...")
        INTERRUPT = True


async def scan_for_gopros(timeout: int = 10) -> set[str]:
    """Scan for connected GoPro devices via USB connection and print their names.

    The scan runs until either the user requests to stop (press Enter) or the
    timeout task fires. Both are executed concurrently alongside the USB
    scanning task. When one of the stop conditions completes, all remaining
    tasks are cancelled so the function returns immediately instead of waiting
    for the timeout to finish.
    """
    global INTERRUPT, GOPROS
    # reset state for each invocation
    INTERRUPT = False
    GOPROS = set()

    # Create tasks explicitly and wait for the first one to complete.
    scan_task = asyncio.create_task(scan_for_gopros_usb())
    user_task = asyncio.create_task(wait_for_user_interrupt())
    timeout_task = asyncio.create_task(wait_for_timeout(timeout))

    # Wait until either scan completes, user interrupts, or timeout occurs.
    done, pending = await asyncio.wait(
        {scan_task, user_task, timeout_task}, return_when=asyncio.FIRST_COMPLETED
    )

    # Cancel any tasks that are still pending so we don't wait for the timeout
    # (or the user input) to finish after one condition has fired.
    for p in pending:
        logger.debug(f"Cancelling pending task: {p.get_coro().__name__}")
        p.cancel()

    # Ensure pending tasks are awaited to suppress warnings and allow proper
    # cancellation handling.
    await asyncio.gather(*pending, return_exceptions=True)

    # The scan task should complete soon after INTERRUPT is set; wait briefly
    # for it and if it doesn't finish, cancel it.
    if not scan_task.done():
        try:
            await asyncio.wait_for(scan_task, timeout=2)
        except asyncio.TimeoutError:
            scan_task.cancel()
            try:
                await scan_task
            except Exception:
                pass

    # If scan_task completed normally, return its result; otherwise return the
    # current GOPROS set which reflects discovered devices so far.
    try:
        if scan_task.cancelled():
            return GOPROS
        return scan_task.result()
    except Exception:
        return GOPROS


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
