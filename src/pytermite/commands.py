"""High-level commands used by the pytermite CLI.

Short Summary
-------------
Convenience helpers that operate on sets of connected WiredConnection objects to
retrieve camera information, status and control (start/stop recording).

Functions
---------
get_camera_info
    Retrieve camera information from each connected GoPro.
get_camera_status
    Retrieve camera state from each connected GoPro.
get_preset_status
    Retrieve preset configuration from each connected GoPro.
camera_shutter
    Start or stop recording on all connected GoPro cameras.
"""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import asyncio
from typing import Coroutine

import aiohttp
import requests
import structlog

from pytermite.connection import WiredConnection
from pytermite.utils import create_base_url, serialize_dict

logger = structlog.get_logger()


async def get_camera_info(
    connected_gopros: set[WiredConnection],
) -> dict[Coroutine, dict]:
    """
    Fetch camera information from connected GoPro devices.

    Parameters
    ----------
    connected_gopros : set[WiredConnection]
        Set of active WiredConnection objects representing connected cameras.

    Returns
    -------
    dict[str, dict]
        Mapping from camera name to a serializable dictionary of camera info.
    """
    camera_information = {}
    for connection in connected_gopros:
        info = await connection.http_command.get_camera_info()
        camera_information[connection.name] = serialize_dict(info.data.__dict__)
    return camera_information


async def get_camera_status(
    connected_gopros: set[WiredConnection],
) -> dict[Coroutine, dict]:
    """
    Fetch the runtime state for each connected GoPro.

    Parameters
    ----------
    connected_gopros : set[WiredConnection]
        A set of active WiredConnection objects representing connected cameras.

    Returns
    -------
    dict[str, dict]
        Mapping from camera name to a serializable dictionary containing camera state.
    """
    camera_state = {}
    for connection in connected_gopros:
        state = await connection.http_command.get_camera_state()
        camera_state[connection.name] = serialize_dict(state.data)
    return camera_state


async def get_preset_status(
    connected_gopros: set[WiredConnection],
) -> dict[Coroutine, dict]:
    """
    Retrieve preset configuration for each connected GoPro.

    Notes
    -----
    The OpenGoPro library's preset status retrieval is currently not working as
    expected; this function performs a manual HTTP GET request against the
    camera's REST endpoint as a workaround.

    Parameters
    ----------
    connected_gopros : set[WiredConnection]
        A set of active WiredConnection objects representing connected cameras.

    Returns
    -------
    dict[str, dict]
        Mapping from camera name to a serializable dictionary describing presets.
    """
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


async def camera_shutter(
    connected_gopros: set[WiredConnection], mode: str = "start"
) -> None:
    """
    Start or stop recording on all connected GoPro cameras.

    This issues HTTP requests to the camera REST endpoint to trigger shutter
    actions. It performs the requests concurrently using an aiohttp session.

    Parameters
    ----------
    connected_gopros : set[WiredConnection]
        A set of active WiredConnection objects representing connected cameras.
    mode : {"start", "stop"}, optional
        Whether to start or stop recording. Default is "start".

    Raises
    ------
    RuntimeError
        If no connected GoPro cameras are passed in.
    """
    if len(connected_gopros) == 0:
        logger.warning(
            "No connected GoPro cameras found. Please connect at least one camera."
        )
        return

    urls = []
    for connection in connected_gopros:
        # Manual HTTP request as preset status is currently not working in open_gopro
        url = create_base_url(connection.identifier) + f"/shutter/{mode}"
        urls.append(url)

    if mode == "start":
        logger.info("Starting recording on all connected GoPro cameras")
    else:
        logger.info("Stopping recording on all connected GoPro cameras")

    async with aiohttp.ClientSession() as session:
        tasks = [session.get(url) for url in urls]
        await asyncio.gather(*tasks)
