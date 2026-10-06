# ruff: file-ignore[RUF067, E402]
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
import pathlib
import sys
from importlib.metadata import PackageNotFoundError, version

import structlog
from bleak import BleakError, BleakScanner

from pytermite.config import PYTERMITE_LOG_LEVEL

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(PYTERMITE_LOG_LEVEL),
)
logger = structlog.get_logger(__name__)

try:
    __version__ = version("pytermite")
except PackageNotFoundError:
    # package is not installed
    pass


def _set_environment() -> None:
    config_path = os.environ.get("PYTERMITE_CONFIG_PATH")
    if not config_path:
        if sys.platform == "win32":
            base = (
                os.environ.get("APPDATA")
                or pathlib.Path(r"~\AppData\Roaming").expanduser()
            )
            path = pathlib.Path(base).expanduser() / "pytermite"
        elif sys.platform == "linux" or sys.platform == "darwin":
            path = pathlib.Path("~/.pytermite").expanduser()
        else:
            logger.warning("Unsupported operating system: %s.", sys.platform)
            path = pathlib.Path("pytermite").expanduser()
        logger.debug("Setting PYTERMITE_CONFIG_PATH environment variable to %s.", path)
        path.mkdir(parents=True, exist_ok=True)
        os.environ["PYTERMITE_CONFIG_PATH"] = str(path)
    else:
        logger.debug(
            "PYTERMITE_CONFIG_PATH environment variable set to %s.", config_path
        )


_set_environment()


async def _is_bluetooth_available() -> None:
    try:
        # Try to instantiate a BleakScanner (does not require a device to be powered on)
        scanner = BleakScanner()
        await scanner.start()
        await scanner.stop()
        await logger.adebug(
            "Bluetooth is available. Setting PYTERMITE_BLUETOOTH_AVAILABLE "
            "environment variable."
        )
        os.environ["PYTERMITE_BLUETOOTH_AVAILABLE"] = "true"
    except BleakError as e:
        await logger.adebug(
            "Bluetooth is not available. Setting PYTERMITE_BLUETOOTH_AVAILABLE "
            "environment variable.",
            error=str(e),
        )
        os.environ["PYTERMITE_BLUETOOTH_AVAILABLE"] = "false"


# Run the Bluetooth availability check at import time when safe.
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    asyncio.run(_is_bluetooth_available())
else:
    loop.create_task(_is_bluetooth_available())  # ruff: ignore[RUF006]

import pytermite.commands as commands
import pytermite.config as config
import pytermite.connection as connection
import pytermite.utils as utils

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
