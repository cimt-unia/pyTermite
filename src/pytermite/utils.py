#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import json
import pathlib
from dataclasses import asdict, is_dataclass
from enum import Enum
from functools import wraps


def load_serial_numbers_from_json(filepath: pathlib.Path | str) -> dict[str, str]:
    filepath = pathlib.Path(filepath) if isinstance(filepath, str) else filepath
    with filepath.open("r") as f:
        return json.load(f)


def create_base_url(serial_number: str) -> str:
    x = serial_number[-3:-2]
    y = serial_number[-2:-1]
    z = serial_number[-1:]
    return f"http://172.2{x}.1{y}{z}.51:8080/gopro/camera"


def reverse_dict(d: dict) -> dict:
    return {v: k for k, v in d.items()}


def serialize_dict(d: dict) -> dict:
    output_dict = {}
    for k, v in d.items():
        # Enum needs to come first as it is also int
        if isinstance(v, Enum):
            output_dict[str(k)] = v.name
        elif isinstance(v, (str, int, list, float, bool, dict, type(None))):
            output_dict[str(k)] = v
        elif is_dataclass(v):
            output_dict[str(k)] = asdict(v)
        else:
            output_dict[str(k)] = v.__dict__ if hasattr(v, "__dict__") else str(v)
    return output_dict


def write_json_to_file(data: dict, filepath: pathlib.Path | str):
    filepath = pathlib.Path(filepath) if isinstance(filepath, str) else filepath
    if not filepath.parent.exists():
        filepath.parent.mkdir(parents=True, exist_ok=True)
    if not filepath.suffix == ".json":
        filepath = filepath.with_suffix(".json")
    with pathlib.Path(filepath).open("w") as f:
        json.dump(data, f, indent=4)
