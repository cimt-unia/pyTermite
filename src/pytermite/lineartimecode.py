"""
Linear Time Code (LTC) Generator and utilities used for injecting timecode.

LTC can by generated at several frame rates (25, 50).

A Decoder is also provided to extract the timecode from a video file and
write it into the metadata of the video file.
"""

#  Copyright (c) 2026 by Jonas Rostan
#
#  SPDX-License-Identifier: BSD-3-Clause

import multiprocessing
import pathlib
import queue
import threading
from datetime import datetime
from multiprocessing.synchronize import Event as SyncEvent
from typing import TYPE_CHECKING

import ffmpeg
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
        self.fps = config["fps"]
        self.double_frames = config["fps"] == 50
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
            (
                self.time_dict["hh"] * 3600
                + self.time_dict["mm"] * 60
                + self.time_dict["ss"]
            ) * self.fps
            + self.frame_number
        )
        
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
            self.time_dict = {
                "hh": now.hour,
                "mm": now.minute,
                "ss": now.second
            }
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


class LTCDecoder:
    """
    Class for decoding Linear Time Code (LTC) from audio tracks in video files.

    It extracts the timecode from the audio and writes it into the metadata of
    the video file.
    """

    def __init__(self) -> None:
        self.timecode_format = "HH:MM:SS:FF"

    @staticmethod
    def _extract_audio(input_path: str, wav_path: str) -> None:
        """
        Extract the audio track of a video file to a WAV file.

        Parameters
        ----------
        input_path : str
            Path to the input video file.
        wav_path : str
            Path of the WAV file to write.
        """
        ffmpeg.input(input_path).output(wav_path, vn=None).run(overwrite_output=True)

    @staticmethod
    def _write_timecode(input_path: str, output_path: str, timecode: str) -> None:
        """
        Copy a video file and set its timecode metadata.

        Parameters
        ----------
        input_path : str
            Path to the input video file.
        output_path : str
            Path of the output video file to write.
        timecode : str
            Timecode to write into the output file, e.g. "01:00:00:00".
        """
        ffmpeg.input(input_path).output(output_path, c="copy", timecode=timecode).run(
            overwrite_output=True
        )

    @staticmethod
    def _convert_position_bits(
        frame_bits: np.typing.NDArray, position: str, fps: int
    ) -> np.typing.NDArray:
        """
        Extract the unit and tens bits of a timecode position from frame bits.

        Parameters
        ----------
        frame_bits : np.typing.NDArray
            Bits of each frame, one row per frame.
        position : str
            Timecode position to convert, e.g. "FF" or "HH".
        fps : int
            Frame rate the position map is looked up with.

        Returns
        -------
        np.typing.NDArray
            Decoded value of the position for each frame.
        """
        units = None
        tens = None
        shift_units = position_map[fps][position]["units"]
        shift_tens = position_map[fps][position]["tens"]

        units = frame_bits[:, shift_units[0] : shift_units[0] + 4]
        total_units = units @ np.array([1, 2, 4, 8])

        if position in ["FF", "HH"]:
            tens = frame_bits[:, shift_tens[0] : shift_tens[0] + 2]
            total_tens = tens @ np.array([1, 2])
        else:
            if len(shift_tens) > 1:
                tens_one = frame_bits[:, shift_tens[0] : shift_tens[0] + 2]
                tens_two = frame_bits[:, shift_tens[1] : shift_tens[1] + 1]
                tens = np.concatenate([tens_one, tens_two], axis=1)
            else:
                tens = frame_bits[:, shift_tens[0] : shift_tens[0] + 3]
            total_tens = tens @ np.array([1, 2, 4])

        return total_units + total_tens * 10

    def decode_ltc(self, input_path: str, fps: int) -> None:
        """
        Decode the LTC signal from the already extracted audio track of a video file.

        Write the extracted timecode into the metadata of the video file after decoding.

        Parameters
        ----------
        input_path : str
            Path to the input video file.
        fps : int
            Frame rate of the LTC signal.
        """
        base_path = ".".join(input_path.split(".")[:-1])
        audio_path = f"{base_path}.wav"
        video_path = f"{base_path}_timecode.mp4"
        self._extract_audio(input_path, audio_path)
        data, samplerate = sf.read(audio_path)
        if data.ndim > 1:
            data = data[:, 0]
        samples_per_bit = int(samplerate / fps / 80)
        transitions = np.nonzero(np.diff(np.sign(data)))[0]
        transition_diffs_short = (
            np.diff(transitions) < (samples_per_bit * 0.75)
        ).astype(int)
        group_starts: list = []
        group_lengths: list = []
        idx_counter = 0
        while idx_counter < len(transition_diffs_short):
            if transition_diffs_short[idx_counter] == 0:
                group_starts.append(idx_counter)
                group_lengths.append(1)
                idx_counter += 1
            elif (
                idx_counter < len(transition_diffs_short) - 1
                and transition_diffs_short[idx_counter] == 1
                and transition_diffs_short[idx_counter + 1] == 1
            ) or (
                transition_diffs_short[idx_counter] == 1
                and idx_counter == len(transition_diffs_short) - 1
            ):
                group_starts.append(idx_counter)
                group_lengths.append(2)
                idx_counter += 2
            else:
                group_starts.append(idx_counter)
                group_lengths.append(-1)
                idx_counter += 1

        group_starts_array = np.array(group_starts, dtype=np.int64)
        group_lengths_array = np.array(group_lengths, dtype=np.int8)
        group_values = transition_diffs_short[group_starts_array]

        is_zero = (group_values == 0) & (group_lengths_array == 1)
        is_one = (group_values == 1) & (group_lengths_array == 2)

        labels = np.full(len(group_values), -1)
        labels[is_zero] = 0
        labels[is_one] = 1

        sync_word = np.array(
            [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1], dtype=np.uint8
        )

        window = np.lib.stride_tricks.sliding_window_view(labels, window_shape=16)
        sync_pos = np.nonzero(np.all(window == sync_word, axis=1))[0]
        frame_starts = sync_pos - 80 + 16
        valid_starts = frame_starts[
            (frame_starts >= 0) & (frame_starts + 80 <= len(labels))
        ]
        indices = valid_starts[:, None] + np.arange(80)
        frame_bits = labels[indices]

        totals = {}
        for position in position_map[fps]:
            totals[position] = self._convert_position_bits(frame_bits, position, fps)

        total_frames = [
            h * 3600 * fps + m * 60 * fps + s * fps + f
            for h, m, s, f in zip(
                totals["HH"], totals["MM"], totals["SS"], totals["FF"], strict=True
            )
        ]

        frame_diffs = np.diff(total_frames)
        safety = 10
        anchor_idx = np.where(
            np.convolve(frame_diffs == 1, np.ones(safety, dtype=int), mode="valid")
            == safety
        )[0][0]

        group_sample_positions = transitions[group_starts_array]
        frame_sample_positions = group_sample_positions[valid_starts]

        video_frame_offset = frame_sample_positions[anchor_idx] / samplerate * fps
        frame0_total_frames = total_frames[anchor_idx] - round(video_frame_offset)

        h = frame0_total_frames // (3600 * fps)
        rest = frame0_total_frames % (3600 * fps)
        m = rest // (60 * fps)
        rest = rest % (60 * fps)
        s = rest // fps
        f = rest % fps

        final_timecode = f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
        self._write_timecode(input_path, video_path, final_timecode)


def decode_timecode_batch(decode_tasks: list, max_processes: int = 8) -> None:
    """
    Decode LTC timecode from a batch of video files using multiprocessing.

    Parameters
    ----------
    decode_tasks : list of tuple of (str, int)
        Pairs of ``(input_path, fps)`` to decode, one per video file.
    max_processes : int, default 8
        Maximum number of worker processes.
    """
    with multiprocessing.Pool(processes=max_processes) as pool:
        results = pool.starmap(start_ltc_decoder, decode_tasks)
    for result in results:
        if result[1]:
            continue
        logger.warning(f"Error when decoding: {result[0]}")


def start_ltc_decoder(input_path: str, fps: int = 50) -> tuple[str, bool]:
    """
    Start the LTC decoder for a given video file and frame rate.

    Parameters
    ----------
    input_path : str
        Path to the input video file.
    fps : int, default 50
        Frame rate of the LTC signal.

    Returns
    -------
    tuple of (str, bool)
        The input path and whether decoding succeeded.
    """
    success = False
    try:
        decoder = LTCDecoder()
        decoder.decode_ltc(input_path, fps)
        success = True
    except Exception as e:
        logger.warning(f"Error when decoding: {input_path}, {e}")
    return (input_path, success)
