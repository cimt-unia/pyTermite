"""Utility helpers used across the pytermite package.

Short summary
-------------
Small convenience functions for loading serial mappings, serial -> URL
conversion, simple dict utilities and serializing complex objects to plain
Python data types suitable for JSON output.
"""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import json
import pathlib
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any


def load_serial_numbers_from_json(filepath: pathlib.Path | str) -> dict[str, str]:
    """Load a JSON file containing a mapping of camera names to serial numbers.

    Parameters
    ----------
    filepath : pathlib.Path | str
        Path to a JSON file containing a mapping of camera name -> serial string.

    Returns
    -------
    dict[str, str]
        Parsed mapping from the JSON file.
    """
    filepath = pathlib.Path(filepath) if isinstance(filepath, str) else filepath
    with filepath.open("r") as f:
        return json.load(f)


def create_base_url(serial_number: str) -> str:
    """Create the camera REST base URL from a serial number.

    Parameters
    ----------
    serial_number : str
        The camera serial number used to derive the REST API base URL.

    Returns
    -------
    str
        Fully qualified base URL for the camera's REST API.
    """
    x = serial_number[-3:-2]
    y = serial_number[-2:-1]
    z = serial_number[-1:]
    return f"http://172.2{x}.1{y}{z}.51:8080/gopro/camera"


def reverse_dict(d: dict) -> dict:
    """Return a dict with keys and values swapped.

    Parameters
    ----------
    d : dict
        Mapping to reverse.

    Returns
    -------
    dict
        Reversed mapping where original values become keys.
    """
    return {v: k for k, v in d.items()}


def serialize_dict(d: dict) -> dict:
    """Serialize complex objects in a dict to JSON-friendly Python types.

    Parameters
    ----------
    d : dict
        Dictionary potentially containing dataclasses, enums or objects.

    Returns
    -------
    dict
        Dictionary where values have been converted to primitives, dicts or
        strings suitable for JSON serialization.
    """
    output_dict: dict[str, Any] = {}
    for k, v in d.items():
        # Enum needs to come first as it is also int
        if isinstance(v, Enum):
            output_dict[str(k)] = v.name
        elif isinstance(v, (str, int, list, float, bool, dict, type(None))):
            output_dict[str(k)] = v
        elif is_dataclass(v):
            output_dict[str(k)] = asdict(v)  # type: ignore
        else:
            output_dict[str(k)] = v.__dict__ if hasattr(v, "__dict__") else str(v)
    return output_dict


def write_json_to_file(data: dict, filepath: pathlib.Path | str) -> None:
    """Write a mapping to a file as pretty-printed JSON, creating parents.

    Parameters
    ----------
    data : dict
        Mapping to write as JSON.
    filepath : pathlib.Path | str
        Destination file path. If extension is not .json it will be added.
    """
    filepath = pathlib.Path(filepath) if isinstance(filepath, str) else filepath
    if not filepath.parent.exists():
        filepath.parent.mkdir(parents=True, exist_ok=True)
    if not filepath.suffix == ".json":
        filepath = filepath.with_suffix(".json")
    with pathlib.Path(filepath).open("w") as f:
        json.dump(data, f, indent=4)
