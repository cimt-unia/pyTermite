# ruff: file-ignore[non-empty-init-module]
"""
`pyTermite` is a small package to control multiple GoPro cameras via USB connection.

Examples
--------
>>> import pytermite
>>> pytermite.get_version()
'0.0.1'
"""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import os
from importlib.metadata import PackageNotFoundError, version

import structlog
from bleak import BleakError, BleakScanner

import pytermite.commands as commands
import pytermite.config as config
import pytermite.connection as connection
import pytermite.utils as utils

logger = structlog.get_logger(__name__)

try:
    __version__ = version("pytermite")
except PackageNotFoundError:
    # package is not installed
    pass


async def _is_bluetooth_available() -> None:
    try:
        # Try to instantiate a BleakScanner (does not require a device to be powered on)
        scanner = BleakScanner()
        await scanner.start()
        await scanner.stop()
        await logger.adebug("Bluetooth is available.")
        os.environ["BLUETOOTH_AVAILABLE"] = "true"
    except BleakError as e:
        await logger.adebug("Bluetooth is not available.", error=str(e))
        os.environ["BLUETOOTH_AVAILABLE"] = "false"


# Run the Bluetooth availability check asynchronously at module import time
asyncio.run(_is_bluetooth_available())


__author__ = "Lukas Behammer"

__all__ = [
    "commands",
    "config",
    "connection",
    "get_version",
    "utils",
]


def get_version() -> str:
    """
    Return the version of the pyTermite package.

    Returns
    -------
    str
        The version string of the package.
    """
    try:
        return __version__
    except NameError as e:
        raise RuntimeError(
            "Version information is not available."
            "The package may not be installed properly."
        ) from e
