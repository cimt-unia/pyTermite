#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
import datetime

from pytermite.commands import get_camera_info, get_camera_status, get_preset_status
from pytermite.connection import close_gopros, connect_gopros, create_wired_gopros
from pytermite.utils import (
    load_serial_numbers_from_json,
    write_json_to_file,
)


async def main():
    print("Start time: ", datetime.datetime.now().isoformat())
    print("Connecting to GoPros...")

    serial_numbers = load_serial_numbers_from_json("./config/gopro_serials.json")
    gopros = create_wired_gopros(serial_numbers)

    connected_gopros = set()
    async for gopro in connect_gopros(gopros):
        print(f"Connected to GoPro {gopro.identifier}.")
        connected_gopros.add(gopro)

    print("All GoPros connected at ", datetime.datetime.now().isoformat())

    infos = await get_camera_info(connected_gopros)
    states = await get_camera_status(connected_gopros)
    presets = await get_preset_status(connected_gopros)

    await close_gopros(gopros)
    print("All GoPros disconnected at ", datetime.datetime.now().isoformat())

    write_json_to_file(infos, "./output/camera_information.json")
    for camera_name, camera_state in states.items():
        write_json_to_file(camera_state, f"./output/states/{camera_name}_state.json")
    for camera_name, preset_state in presets.items():
        write_json_to_file(preset_state, f"./output/presets/{camera_name}_presets.json")


if __name__ == "__main__":
    asyncio.run(main())
