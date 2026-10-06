"""
Video fetching and saving functions for GoPro cameras.

Used to remember the last captured video on each camera
(`WiredConnection` and `WirelessConnection`). Fetching of data is realised in parallel
using multiprocessing, and is done using wired connections to the cameras.
"""

#  Copyright (c) 2026 by Jonas Rostan
#
#  SPDX-License-Identifier: BSD-3-Clause

import json
import multiprocessing
import time
from pathlib import Path

import structlog

from pytermite.config import PYTERMITE_LOG_LEVEL, resolve_config_path
from pytermite.connection import WiredConnection, WirelessConnection, make_gopro_request

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(PYTERMITE_LOG_LEVEL),
)
logger = structlog.get_logger()

FETCH_RECORDINGS = resolve_config_path(
    "PYTERMITE_FETCH_RECORDINGS_PATH",
    default_filename="fetch_recordings.json",
)


def fetch_filenames(
    gopros: set[WiredConnection | WirelessConnection] | None = None,
) -> None:
    """
    Fetch the filenames of the last captured videos from connected GoPro cameras.

    Parameters
    ----------
    gopros : set[WiredConnection | WirelessConnection] | None, optional
        A set of connected GoPro camera objects.

    Notes
    -----
    Filenames are saved per camera in a temporary JSON file for later retrieval.
    """
    gopros_valid = not (gopros is None or len(gopros) < 1)
    if not gopros_valid:
        logger.warning(
            "No connected GoPros found! Recorded data paths could not be saved"
        )
        return

    saved_entries = _get_saved_entries()
    # ruff: ignore[S101]
    assert gopros is not None  # for mypy
    for connection in gopros:
        response_last = make_gopro_request(connection, "gopro/media/last_captured")
        if response_last is not None and response_last.status_code == 200:
            if connection._identifier not in saved_entries:
                saved_entries[connection._identifier] = [response_last.json()]
            else:
                saved_entries[connection._identifier].append(response_last.json())
            _save_entries(saved_entries)
        else:
            logger.warning(
                f"Last captured of {connection._identifier} could not be saved!"
            )


def fetch_recorded(
    gopros: set[WiredConnection | WirelessConnection] | None = None,
    save_path: str | Path | None = None,
    max_processes: int = 8,
    allowed_retries: int = 10,
) -> None:
    """
    Fetch recorded videos from connected GoPro cameras.

    Video filenames are retrieved from the temporary JSON file created by
    `fetch_filenames`. The videos are downloaded in parallel using multiprocessing.

    Parameters
    ----------
    gopros : set[WiredConnection | WirelessConnection] | None, optional
        A set of connected GoPro camera objects. If no cameras are connected,
        the function will abort.
    save_path : str | Path | None, optional
        The path where the fetched videos will be saved. If not provided, defaults
        to the user's Downloads folder.
    max_processes : int, optional
        The maximum number of parallel processes to use for fetching videos.
        Default is 8.
    allowed_retries : int, optional
        The number of times to retry fetching a video if the request fails.
        Default is 10.

    Notes
    -----
    The function will skip cameras that are not currently connected, even if
    they have files marked for fetching. However, if cameras are connected, but
    no files are marked for fetching, the function will also abort.
    """
    if gopros is None or len(gopros) < 1:
        logger.warning("No GoPro Connection found! Fetching data aborted...")
        return
    connected_cams = {connection._identifier: connection for connection in gopros}

    saved_entries = _get_saved_entries()
    if len(saved_entries) < 1:
        logger.warning("No Files marked for fetching found!")
        return

    tasks = []

    if save_path is None:
        save_path = Path.home() / "Downloads"
    else:
        save_path = Path(save_path)

    for cam_id, entry_list in saved_entries.items():
        if cam_id not in connected_cams:
            logger.info(
                f"Camera {cam_id} has files marked for fetching, but is not connected. "
                f"Skipped..."
            )
            continue
        save_path_cam = save_path / cam_id

        for idx, entry in enumerate(entry_list):
            for _ in range(allowed_retries):
                response_info = make_gopro_request(
                    connected_cams[cam_id],
                    f"gopro/media/info?path={entry['folder']}/{entry['file']}",
                )
                if response_info and response_info.status_code == 200:
                    break
                time.sleep(1)
            else:
                logger.warning(
                    f"Timeout: Data of {cam_id} could not be fetched. Filename: "
                    f"{entry['file']}"
                )
                continue

            tasks.append(
                (
                    connected_cams[cam_id],
                    f"videos/DCIM/{entry['folder']}/{entry['file']}",
                    save_path_cam,
                    entry["file"],
                    cam_id,
                    idx,
                )
            )

    with multiprocessing.Pool(processes=max_processes) as pool:
        results = pool.starmap(_fetch_recoding, tasks)

    delete_dict = {}
    saved_video_paths = []
    for cam_id, idx, success, save_path_cam in results:
        if not success:
            continue
        saved_video_paths.append((f"{save_path_cam[0]}/{save_path_cam[1]}", 50))
        if cam_id not in delete_dict:
            delete_dict[cam_id] = [idx]
        else:
            delete_dict[cam_id].append(idx)

    for cam_id, idxs in delete_dict.items():
        for i in sorted(idxs, reverse=True):
            del saved_entries[cam_id][i]
        if not saved_entries[cam_id]:
            del saved_entries[cam_id]
    _save_entries(saved_entries)


def _fetch_recoding(
    connection: WirelessConnection | WiredConnection,
    request_path: str,
    save_path_cam: Path,
    filename: str,
    cam_id: str,
    idx: int,
) -> tuple[str, int, bool, tuple[Path, str]]:
    response = make_gopro_request(connection, request_path)
    status = False
    if response and response.status_code == 200:
        status = True
        Path(save_path_cam).mkdir(exist_ok=True, parents=True)
        with Path(save_path_cam / filename).open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    return cam_id, idx, status, (save_path_cam, filename)


def _get_saved_entries() -> dict:
    global FETCH_RECORDINGS
    try:
        with Path(FETCH_RECORDINGS).open() as f:
            saved_entries = json.load(f)
    except FileNotFoundError:
        saved_entries = {}
    return saved_entries


def _save_entries(saved_entries: dict) -> None:
    global FETCH_RECORDINGS
    with Path(FETCH_RECORDINGS).open("w") as f:
        json.dump(saved_entries, f)
