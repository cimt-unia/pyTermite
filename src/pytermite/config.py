"""Runtime configuration helpers for the pyTermite package.

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
    """Return the application state directory for config and runtime files."""
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
    """Create the application config directory if needed and return it."""
    config_dir = default_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def resolve_config_path(
    envvar: str,
    *,
    default_filename: str | None = None,
    must_exist: bool = False,
) -> pathlib.Path:
    """Resolve a path from environment variables or the config directory."""
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
