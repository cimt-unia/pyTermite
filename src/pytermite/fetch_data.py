import requests
from pathlib import Path
import json
import time
import os

from pytermite.connection import (
    WiredConnection
)

tmp_file = "tmp_recordings.json"
save_path = Path(__file__).parent / "tmp"

def fetch_filenames(serials: dict[str, str] | set[str] | None = None,
                    logger = None
    ):
    logger_available = logger is not None
    if (serials is None or len(serials) < 1):
        if logger_available:
            logger.warning("No connected GoPros found! Recorded data paths could not be saved")
        return

    saved_entries = _get_saved_entries()

    for serial_nr in serials:
        ip = f"172.2{serial_nr[-3]}.1{serial_nr[-2:]}.51:8080"
        url_last = f"http://{ip}/gopro/media/last_captured"
        response_last = requests.request("GET", url_last)
        if response_last.status_code == 200:
            if not serial_nr[-4:] in saved_entries:
                saved_entries[serial_nr[-4:]] = [response_last.json()]
            else:
                saved_entries[serial_nr[-4:]].append(response_last.json())

            _save_entries(saved_entries)
        else:
            logger.warning(f"Last captured of {serial_nr[-4:]} could not be saved!")

def fetch_recorded( serials: dict[str, str] | set[str] | None = None,
                    save_path: str|None = None, 
                    logger = None,
                    allowed_retries = 10
    ):
    logger_available = logger is not None

    if (serials is None or len(serials) < 1):
        if logger_available:
            logger.warning("No GoPro Connection found! Fetching data aboarded...")
        return
    connected_cam_ids = [serial[-4:] for serial in serials]
    
    saved_entries = _get_saved_entries()
    if (len(saved_entries) < 1):
        if logger_available:
            logger.warning("No Files marked for fetching found!")
        return

    if save_path is None:
        save_path = Path.home() / "Downloads"
    else:
        save_path = Path(save_path)

    delete_dict = {}
    for cam_id, entry_list in saved_entries.items():
        if cam_id not in connected_cam_ids:
            if logger_available:
                logger.info(f"Camera {cam_id} has files marked for fetching, but is not connected. Skipped...")
            continue
        delete_dict[cam_id] =  []
        save_path_cam = save_path / cam_id
        ip = f"172.2{cam_id[-3]}.1{cam_id[-2:]}.51:8080"

        for idx, entry in enumerate(entry_list):
            url_info = f"http://{ip}/gopro/media/info?path={entry["folder"]}/{entry["file"]}"

            counter = 0
            while counter < allowed_retries:
                response_info = requests.request("GET", url_info)
                if response_info.status_code == 200:
                    time.sleep(1)
                    break
                counter += 1
                time.sleep(1)
            if counter >= allowed_retries:
                logger.warning(f"Timeout: Data of {cam_id} could not be fetched. Filename: {entry["file"]}")
                continue

            url = f"http://{ip}/videos/DCIM/{entry["folder"]}/{entry["file"]}"
            response = requests.request("GET", url)
            if response.status_code == 200:
                os.makedirs(save_path_cam, exist_ok=True)
                logger.info(f"Saved to {save_path_cam}")
                with open(save_path_cam / entry["file"], "wb") as f:
                    f.write(response.content)
                delete_dict[cam_id].append(idx)
            else:
                logger.warning(f"Unknown: Data of {cam_id} could not be fetched. Filename: {entry["file"]}")
    
    for cam_id, idxs in delete_dict.items():
        for i in sorted(idxs, reverse=True):
            del saved_entries[cam_id][i]
        if not saved_entries[cam_id]:
            del saved_entries[cam_id]
    _save_entries(saved_entries)

def _get_saved_entries() -> dict:
    global tmp_file
    global save_path
    try:
        with open(save_path / tmp_file, "r") as f:
            saved_entries = json.load(f)
    except FileNotFoundError:
        saved_entries = {}
    return saved_entries

def _save_entries(saved_entries:dict) -> None:
    global tmp_file
    global save_path
    with open(save_path / tmp_file, "w") as f:
        json.dump(saved_entries, f)
        