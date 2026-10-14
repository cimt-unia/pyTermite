"""
Runtime configuration helpers for the pyTermite package.

The application intentionally reads configuration from environment variables.
A user may inject those variables via an external dotenv file in the shell or
startup environment; pyTermite itself does not import dotenv or depend on JSON
configuration files.
"""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import logging
import os
import pathlib
import sys

import structlog

logger = structlog.get_logger(__name__)

# Set base logging level from environment variable, defaulting to INFO if not set
PYTERMITE_LOG_LEVEL = logging.getLevelNamesMapping()[
    os.environ.get("PYTERMITE_LOG_LEVEL", "INFO")
]


def default_config_dir() -> pathlib.Path:
    """
    Return the application state directory for config and runtime files.

    Returns
    -------
    pathlib.Path
        The directory given by ``PYTERMITE_CONFIG_PATH``, otherwise the platform
        specific default directory.
    """
    config_path = os.environ.get("PYTERMITE_CONFIG_PATH")
    if config_path:
        return pathlib.Path(config_path).expanduser()

    if sys.platform == "win32":
        base = (
            os.environ.get("APPDATA") or pathlib.Path(r"~\AppData\Roaming").expanduser()
        )
        return pathlib.Path(base).expanduser() / "pytermite"

    return pathlib.Path("~/.pytermite").expanduser()


def ensure_config_dir() -> pathlib.Path:
    """
    Create the application config directory if needed and return it.

    Returns
    -------
    pathlib.Path
        The application config directory.
    """
    config_dir = default_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def resolve_config_path(
    envvar: str,
    *,
    default_filename: str | None = None,
    must_exist: bool = False,
) -> pathlib.Path:
    """
    Resolve a path from environment variables or the config directory.

    Parameters
    ----------
    envvar : str
        Name of the environment variable that may contain an explicit path.
    default_filename : str, optional
        File name inside the config directory used if ``envvar`` is not set.
        If None, the config directory itself is returned.
    must_exist : bool, default: False
        Whether to raise an error if the resolved path does not exist.

    Returns
    -------
    pathlib.Path
        The resolved path.

    Raises
    ------
    FileNotFoundError
        If ``must_exist`` is True and the resolved path does not exist.
    """
    configured = os.environ.get(envvar)
    if configured:
        path = pathlib.Path(configured).expanduser()
    elif default_filename is not None:
        path = ensure_config_dir() / default_filename
    else:
        path = ensure_config_dir()

    if must_exist and not path.exists():
        raise FileNotFoundError(f"The configured path does not exist: {path}")
    return path
