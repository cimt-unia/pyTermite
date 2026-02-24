#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import requests

from pytermite.connection import WiredConnection
from pytermite.utils import create_base_url, reverse_dict, serialize_dict


async def get_camera_info(connected_gopros: set[WiredConnection]) -> dict[str, dict]:
    camera_information = {}
    for connection in connected_gopros:
        info = await connection.http_command.get_camera_info()
        camera_information[connection.name] = serialize_dict(info.data.__dict__)
    return camera_information


async def get_camera_status(connected_gopros: set[WiredConnection]):
    camera_state = {}
    for connection in connected_gopros:
        state = await connection.http_command.get_camera_state()
        camera_state[connection.name] = serialize_dict(state.data)
    return camera_state


async def get_preset_status(connected_gopros: set[WiredConnection]):
    preset_state = {}
    for connection in connected_gopros:
        # Manual HTTP request as preset status is currently not working in open_gopro
        url = create_base_url(connection.identifier) + "/presets/get"
        # querystring = {"include-hidden": "0"}  # Currently not working

        response = requests.request("GET", url)
        state = response.json()

        # Currently not working in open_gopro
        # state = await connection.http_command.get_preset_status()
        # state = state.data

        preset_state[connection.name] = serialize_dict(state)
    return preset_state


async def start_camera_recording(connected_gopros: set[WiredConnection]):
    for camera in connected_gopros:
        await camera.http_command.set_shutter()
