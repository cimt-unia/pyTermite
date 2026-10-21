"""
Linear Time Code (LTC) Generator and utilities used for injecting timecode.

LTC can by generated at several frame rates (25, 50).

A Decoder is also provided to extract the timecode from a video file and
write it into the metadata of the video file.
"""

#  Copyright (c) 2026 by Jonas Rostan
#
#  SPDX-License-Identifier: BSD-3-Clause

import pathlib
import queue
import threading
from datetime import datetime
from multiprocessing.synchronize import Event as SyncEvent
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd
import soundfile as sf
import structlog
from pylsl import IRREGULAR_RATE, StreamInfo, StreamOutlet, local_clock
from pylsl.lib import cf_string

from pytermite.config import PYTERMITE_LOG_LEVEL

if TYPE_CHECKING:
    from ctypes import _CData


structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(PYTERMITE_LOG_LEVEL),
)
logger = structlog.get_logger(__name__)

position_map: dict[int, dict[str, dict[str, tuple]]] = {
    50: {
        "FF": {"units": (0,), "tens": (8, 10)},
        "SS": {"units": (16,), "tens": (24,)},
        "MM": {"units": (32,), "tens": (40,)},
        "HH": {"units": (48,), "tens": (56,)},
    },
    25: {
        "FF": {"units": (0,), "tens": (8,)},
        "SS": {"units": (16,), "tens": (24,)},
        "MM": {"units": (32,), "tens": (40,)},
        "HH": {"units": (48,), "tens": (56,)},
    },
}

bit_mask = {1: 0x1, 2: 0x3, 3: 0x7, 4: 0xF}


class LTCGenerator:
    """
    A generator for creating Linear Time Code (LTC) signals at various frame rates.

    LTC contains timecode information in the format HH:MM:SS:FF,
    where HH is hours, MM is minutes, SS is seconds, and FF is frames. It also
    includes a sync word for synchronization.

    Parameters
    ----------
    config : dict
        Configuration with the keys ``sample_rate``, ``fps`` and ``device``.
    stop_event : multiprocessing.synchronize.Event
        Event that stops the generation when set.
    """

    def __init__(self, config: dict, stop_event: SyncEvent) -> None:
        self.stop_event = stop_event
        self.sample_rate = config["sample_rate"]
        self.double_frames = config["fps"] == 50
        self.fps = config["fps"] // 2 if self.double_frames else config["fps"]
        self.device = config["device"]
        self.use_system_time = config["use_system_time"]
        self.samples_per_frame = self.sample_rate // self.fps
        self.samples_per_bit = int(self.sample_rate / self.fps / 80)
        self.frame_number = 0
        self.next_level_sign = -1
        self.time_dict = {"hh": 1, "mm": 0, "ss": 0}
        self.frame_queue: queue.Queue = queue.Queue(maxsize=self.fps)
        self.info = StreamInfo(
            name="LtcTimecode",
            type="Markers",
            channel_count=1,
            nominal_srate=IRREGULAR_RATE,
            channel_format=cf_string,
            source_id="ltc_timecode_stream",
        )
        self.outlet = StreamOutlet(self.info)

    def play_control_sound(self, filename: str, amplification: float = 1.0) -> None:
        """
        Play a control sound to start or stop a GoPro recording.

        GoPros may be controlled using voice activation. The sounds are
        pre-recorded and stored in the 'audios' directory.

        Parameters
        ----------
        filename : str
            Name of the control sound file, without the ``.wav`` extension.
        amplification : float, default 1.0
            Factor by which the sound is amplified before playback.
        """
        base_dir = pathlib.Path(__file__).resolve().parent
        path = base_dir / "audios" / f"{filename}.wav"
        data, samplerate = sf.read(path)
        sd.play(data * amplification, samplerate, device=self.device)
        sd.wait()

    @staticmethod
    def print_allowed_fps() -> None:
        """Return the allowed frame rates for LTC generation."""
        print(list(position_map.keys()))

    def generate_wav(self, filename: str, duration: int = 10) -> None:
        """
        Debug function to generate a wav file with LTC for a given duration.

        Parameters
        ----------
        filename : str
            Prefix of the output file. The file is named
            ``{filename}_{fps}_{duration}.wav``.
        duration : int, default 10
            Duration of the signal in seconds.
        """
        total_frames = self.fps * duration
        data: list = []
        for _ in range(total_frames):
            word, _ = self.create_next_bitword()
            samples = self.sample_word(word)
            data.extend(samples)
        data_array = np.array(data, dtype=np.float32)
        sf.write(f"{filename}_{self.fps}_{duration}.wav", data_array, self.sample_rate)

    def convert_bits(self, number: int, position: str) -> list:
        """
        Convert a number into its corresponding bit representation.

        Convert into representation for a given position in the LTC frame
        (FF, SS, MM, HH).

        Parameters
        ----------
        number : int
            Value to convert, e.g. the frame or second number.
        position : str
            Position in the LTC frame, one of "FF", "SS", "MM" or "HH".

        Returns
        -------
        list of int
            Bit values, already shifted to their positions in the LTC word.
        """
        conversions = []
        units = number % 10
        tens = number // 10
        for key, value in position_map[self.fps][position].items():
            if key == "units":
                conversions.append((units & bit_mask[4]) << value[0])
            elif key == "tens":
                bit_mask_tens = bit_mask[2] if position in ["FF", "HH"] else bit_mask[3]
                conversions.append((tens & bit_mask_tens) << value[0])
                if len(value) > 1:
                    conversions.append(((tens >> 2) & bit_mask[1]) << value[1])
            else:
                continue
        return conversions

    def create_next_bitword(self) -> tuple[int, str]:
        """
        Create the next 80-bit word for the LTC based on the current timecode.

        Returns
        -------
        word : int
            The 80-bit LTC word.
        timecode : str
            The encoded timecode in the format "HH:MM:SS:FF".
        """
        total_frames = (
            self.time_dict["hh"] * 3600
            + self.time_dict["mm"] * 60
            + self.time_dict["ss"]
        ) * self.fps + self.frame_number

        ff = total_frames % self.fps
        ss = (total_frames // self.fps) % 60
        mm = (total_frames // (self.fps * 60)) % 60
        hh = (total_frames // (self.fps * 3600)) % 24
        self.frame_number += 1

        word = 0
        conversions = [0b1011111111111100 << 64]
        conversions.extend(self.convert_bits(ff, "FF"))
        conversions.extend(self.convert_bits(ss, "SS"))
        conversions.extend(self.convert_bits(mm, "MM"))
        conversions.extend(self.convert_bits(hh, "HH"))

        for conv in conversions:
            word |= conv

        parity_bit = 59 if self.fps == 25 else 27
        word &= ~(1 << parity_bit)
        word |= (word.bit_count() % 2) << parity_bit

        timecode = f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
        return word, timecode

    def sample_word(self, word: int) -> list:
        """
        Sample the 80-bit word into a list of audio samples for the LTC signal.

        Parameters
        ----------
        word : int
            The 80-bit LTC word to sample.

        Returns
        -------
        list of float
            Audio samples of the encoded word.
        """
        samples = []
        level = self.next_level_sign * 0.75
        for i in range(80):
            start = round(i * self.samples_per_bit)
            end = round((i + 1) * self.samples_per_bit)
            mid = start + (end - start) // 2

            bit = (word >> i) & 1
            level *= -1
            samples.extend([level] * (mid - start))
            if bit == 1:
                level *= -1
            samples.extend([level] * (end - mid))
        self.next_level_sign = 1 if level > 0 else -1
        return samples

    def generate_frames(self) -> None:
        """
        Pipeline for generating LTC frames.

        This function continuously generates LTC frames and puts them into a queue
        until stopped.
        """
        if self.use_system_time:
            now = datetime.now()
            self.time_dict = {"hh": now.hour, "mm": now.minute, "ss": now.second}
        n = 2 if self.double_frames else 1
        while not self.stop_event.is_set():
            word, timecode = self.create_next_bitword()
            samples = np.array(self.sample_word(word), dtype=np.float32)
            for i in range(n):
                # Only the first copy carries the timecode: one marker per word.
                self.frame_queue.put((samples, timecode if i == 0 else None))

    # ruff: ignore[ARG002]
    def callback(
        self, outdata: np.ndarray, frames: int, time: "_CData", status: sd.CallbackFlags
    ) -> None:
        """
        Write the next LTC frame from the queue to the output buffer.

        The timecode of the frame is pushed as a marker, timestamped with the
        time at which the frame is sent to the output device.

        Parameters
        ----------
        outdata : np.ndarray
            Output buffer that is filled with the next LTC samples.
        frames : int
            Number of frames requested by the audio stream.
        time : _CData
            Timing information provided by the audio stream.
        status : sounddevice.CallbackFlags
            Status flags of the audio stream.
        """
        try:
            samples, timecode = self.frame_queue.get_nowait()
        except queue.Empty:
            outdata[:] = 0
            return
        outdata[:, 0] = samples
        if timecode is not None:
            timestamp = local_clock()
            self.outlet.push_sample([timecode], timestamp)

    def run(self) -> None:
        """
        Start the LTC generation process.

        It initializes a separate thread for generating frames and manages
        the audio output stream.
        """
        t = threading.Thread(target=self.generate_frames, daemon=True)
        t.start()
        while not self.stop_event.is_set():
            with sd.OutputStream(
                samplerate=self.sample_rate,
                device=self.device,
                channels=1,
                dtype="float32",
                blocksize=self.samples_per_frame,
                callback=self.callback,
            ):
                while not self.stop_event.is_set():
                    sd.sleep(1000)
