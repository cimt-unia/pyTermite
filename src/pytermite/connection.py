#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import os
import pathlib

from open_gopro import WiredGoPro
from open_gopro.domain.exceptions import ResponseTimeout

from pytermite.utils import load_serial_numbers_from_json, reverse_dict, serialize_dict

# Get serial_numbers path from environment variable
PATH = pathlib.Path(os.getenv("PYTERMITE_PATH", None))
SERIALS = load_serial_numbers_from_json(PATH / "serials.json")


class WiredConnection(WiredGoPro):
    """Subclass of WiredGoPro to allow future extensions."""
    def __init__(self, **kwargs):
        name = kwargs.pop("name", None)
        super().__init__(**kwargs)
        self._name: str | None = name

    @property
    def name(self):
        if not self._name:
            info = serialize_dict(asyncio.run(self.http_command.get_camera_info()).data.__dict__)
            name = info.get("ap_ssid", None)
            self._name = name or reverse_dict(SERIALS)[self.identifier]
        return self._name


def create_wired_gopros(gopro_serials: dict[str, str]) -> dict[str, WiredConnection]:
    gopros = {}
    for cam_name, serial_number in gopro_serials.items():
        gopros[cam_name] = WiredConnection(serial=serial_number)
    return gopros


async def connect_gopros(gopros: dict[str, WiredConnection]):
    for cam_name, gopro in gopros.items():
        try:
            await gopro.open(retries=1, timeout=1)
            yield gopro
        except ResponseTimeout as e:
            print(
                f"Failed to connect to GoPro {cam_name} with serial "
                f"{gopro.identifier}: {e}"
            )


async def close_gopros(gopros: dict[str, WiredConnection]):
    for _, gopro in gopros.items():
        await gopro.close()
