"""Contains the configuration for the "pyTermite" package."""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import json
import logging
import os
import pathlib

import structlog

logger = structlog.get_logger(__name__)

# Set base logging level from environment variable, defaulting to INFO if not set
PYTERMITE_LOG_LEVEL = logging.getLevelNamesMapping()[
    os.environ.get("PYTERMITE_LOG_LEVEL", "INFO")
]


def read_from_config(path: pathlib.Path | None = None) -> dict | None:
    """Read the configuration from the config.json file."""
    if not path:
        # save to set default path to "" since the environment variable is always
        # initialized in __init__.py, so this will always be a valid path
        config_path = os.getenv("PYTERMITE_CONFIG_PATH", "")
        path = pathlib.Path(config_path) / "config.json"
    if path.exists():
        try:
            return json.load(path.open())
        except json.decoder.JSONDecodeError as e:
            logger.exception(
                "Could not load the given file as JSON. The file might "
                "not be in JSON format.",
                error=str(e),
            )
            return None
    else:
        raise FileNotFoundError("The given path does not exist.")
