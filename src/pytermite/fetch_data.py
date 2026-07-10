import requests
from pathlib import Path
import json
import time
import os
import tempfile
import multiprocessing
from  multiprocessing import Process

from pytermite.connection import (
    WiredConnection,
    WirelessConnection
)

from pytermite.lineartimecode_two import decode_timecode_batch

tmp_file = "tmp_recordings.json"
save_path = Path(__file__).parent / "tmp"

def fetch_filenames(serials: dict[str, str] | set[str] | None = None,
                    gopros: set[WiredConnection | WirelessConnection]  | None = None,
                    logger = None
    ):
    logger_available = logger is not None
    serials_valid = not (serials is None or len(serials) < 1)
    gopros_valid = not (gopros is None or len(gopros) < 1)
    if not serials_valid and not gopros_valid:
        if logger_available:
            logger.warning("No connected GoPros found! Recorded data paths could not be saved")
        return

    saved_entries = _get_saved_entries()
    
    if gopros_valid:
        for connection in gopros:
            if not isinstance(connection, WirelessConnection): continue
            
            url_last = f"https://{connection.ip_address}/gopro/media/last_captured"
            cert_string = connection.cohn.credentials.certificate
            
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pem") as f:
                f.write(cert_string)
                cert_path = f.name
            
            auth = (connection.cohn.credentials.username, connection.cohn.credentials.password)
            try:
                response_last = requests.request("GET", url_last, verify=cert_path, auth=auth)
            finally:
                os.unlink(cert_path)
            
            if response_last.status_code == 200:
                if not connection._identifier in saved_entries:
                    saved_entries[connection._identifier] = [response_last.json()]
                else:
                    saved_entries[connection._identifier].append(response_last.json())
                _save_entries(saved_entries)
            else:
                logger.warning(f"Last captured of wireless {connection._identifier} could not be saved!")
    
    if serials_valid:
        for serial_nr in serials:
            cam_id = serial_nr[-4:]
            ip = f"172.2{serial_nr[-3]}.1{serial_nr[-2:]}.51:8080"
            url_last = f"http://{ip}/gopro/media/last_captured"    
            response_last = requests.request("GET", url_last)
            if response_last.status_code == 200:
                if not cam_id in saved_entries:
                    saved_entries[cam_id] = [response_last.json()]
                else:
                    saved_entries[cam_id].append(response_last.json())
                _save_entries(saved_entries)
            else:
                logger.warning(f"Last captured of {cam_id} could not be saved!")

def fetch_recorded( serials: dict[str, str] | set[str] | None = None,
                    save_path: str|None = None, 
                    logger = None,
                    max_processes = 8,
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

    tasks = []

    if save_path is None:
        save_path = Path.home() / "Downloads"
    else:
        save_path = Path(save_path)

    for cam_id, entry_list in saved_entries.items():
        if cam_id not in connected_cam_ids:
            if logger_available:
                logger.info(f"Camera {cam_id} has files marked for fetching, but is not connected. Skipped...")
            continue
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

            tasks.append((
                f"http://{ip}/videos/DCIM/{entry["folder"]}/{entry["file"]}",
                save_path_cam,
                entry["file"],
                cam_id,
                idx
            ))

    with multiprocessing.Pool(processes=max_processes) as pool:
        results = pool.starmap(_fetch_recoding, tasks)
    
    delete_dict = {}
    saved_video_paths = []
    for cam_id, idx, success, save_path_cam in results:
        if not success: continue
        saved_video_paths.append((f"{save_path_cam[0]}/{save_path_cam[1]}", 50))
        if not cam_id in delete_dict:
            delete_dict[cam_id] = [idx]
        else:
            delete_dict[cam_id].append(idx)

    for cam_id, idxs in delete_dict.items():
        for i in sorted(idxs, reverse=True):
            del saved_entries[cam_id][i]
        if not saved_entries[cam_id]:
            del saved_entries[cam_id]
    _save_entries(saved_entries)

    Process(target=decode_timecode_batch, args=(saved_video_paths,max_processes,), daemon=False).start()

def _fetch_recoding(url, save_path_cam, filename, cam_id, idx):
    response = requests.request("GET", url, stream=True)
    if response.status_code == 200:
        os.makedirs(save_path_cam, exist_ok=True)
        with open(save_path_cam / filename, "wb") as f:
            
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    return (cam_id, idx, response.status_code == 200, (save_path_cam, filename))   

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
    save_path.mkdir(parents=True, exist_ok=True)
    with open(save_path / tmp_file, "w") as f:
        json.dump(saved_entries, f)
        