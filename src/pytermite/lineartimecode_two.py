"""
Linear Time Code Generator and utilities used for injecting timecode into audio track.
"""

#  Copyright (c) 2026 by Jonas Rostan
#
#  SPDX-License-Identifier: BSD-3-Clause

import os
import numpy as np
import sounddevice as sd
import soundfile as sf
import threading
import queue
import time
import ffmpeg
import multiprocessing

position_map = {
    50: {
        "FF": {
            "units": (0,),
            "tens":  (8, 10)
        },
        "SS": {
            "units": (16,),
            "tens":  (24,)
        },
        "MM": {
            "units": (32,),
            "tens":  (40,)
        },
        "HH": {
            "units": (48,),
            "tens":  (56,)
        },
    },
    25: {
        "FF": {
            "units": (0,),
            "tens":  (8,)
        },
        "SS": {
            "units": (16,),
            "tens":  (24,)
        },
        "MM": {
            "units": (32,),
            "tens":  (40,)
        },
        "HH": {
            "units": (48,),
            "tens":  (56,)
        },
    }
}

bit_mask = {
    1: 0x1,
    2: 0x3,
    3: 0x7,
    4: 0xF
}

class LTC_Generator():
    def __init__(self, config:dict, stop_event):
        self.stop_event = stop_event
        self.sample_rate = config["sample_rate"]
        self.fps = config["fps"]
        self.device = config["device"]
        self.samples_per_frame = self.sample_rate // self.fps
        self.samples_per_bit = int(self.sample_rate / self.fps / 80)
        self.total_samples = 0
        self.next_level_sign = -1
        self.frame_queue = queue.Queue(maxsize=self.fps)

    def play_control_sound(self, filename: str, amplification:float=1.0):
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(BASE_DIR, "audios", f"{filename}.wav")
        data, samplerate = sf.read(path)
        sd.play(data * amplification, samplerate, device=self.device)
        sd.wait()

    def print_allowed_fps(self) -> None:
        print([fps for fps in position_map.keys()])

    def generate_wav(self, duration:int=10):
        total_frames = self.fps * duration
        data = []
        for _ in range(total_frames):
            word = self.create_next_bitword()
            samples = self.sample_word(word)
            data.extend(samples)
        data = np.array(data, dtype=np.float32)
        sf.write(f"test_{self.fps}_{duration}.wav", data, self.sample_rate)

    def convert_bits(self, number: int, position: str):
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

    def create_next_bitword(self) -> int:
        frame_number = self.total_samples // self.samples_per_frame
        FF = frame_number % self.fps
        SS = (frame_number // self.fps) % 60
        MM = (frame_number // (self.fps * 60)) % 60
        HH = (1 + frame_number // (self.fps * 3600)) % 24
        self.total_samples += self.samples_per_frame

        word = 0
        conversions = [0b1011111111111100 << 64]
        conversions.extend(self.convert_bits(FF, "FF"))
        conversions.extend(self.convert_bits(SS, "SS"))
        conversions.extend(self.convert_bits(MM, "MM"))
        conversions.extend(self.convert_bits(HH, "HH"))

        for conv in conversions:
            word |= conv

        return word

    def sample_word(self, word:int) -> list:
        samples = []
        level = self.next_level_sign * 0.75
        for i in range(80):
            start = round(i * self.samples_per_bit)
            end   = round((i + 1) * self.samples_per_bit)
            mid   = start + (end - start) // 2

            bit = (word >> i) & 1
            level *= -1
            samples.extend([level] * (mid - start))
            if bit == 1:
                level *= -1
            samples.extend([level] * (end - mid))
        self.next_level_sign = 1 if level > 0 else -1
        return samples

    def generate_frames(self):
        while not self.stop_event.is_set():
            word = self.create_next_bitword()
            samples = self.sample_word(word)
            self.frame_queue.put(np.array(samples, dtype=np.float32))


    def callback(self, outdata, frames, time, status): #??? types
        try:
            outdata[:, 0] = self.frame_queue.get_nowait()
        except queue.Empty:
            outdata[:] = 0
            return

    def run(self):
        t = threading.Thread(target=self.generate_frames, daemon=True)
        t.start()
        # self.play_control_sound("start_recording")
        while not self.stop_event.is_set():
            with sd.OutputStream(samplerate=self.sample_rate, device=self.device, 
                        channels=1, dtype='float32',
                        blocksize=self.samples_per_frame,
                        callback=self.callback):
                while not self.stop_event.is_set():
                    sd.sleep(1000)
        # time.sleep(1)
        #TODO new louder recording and manuel trigger without ltc class
        # self.play_control_sound("stop_recording", 2.0)

class LTC_Decoder():
    def __init__(self):
        self.timecode_format = "HH:MM:SS:FF"

    def _extract_audio(self, input_path:str, wav_path:str):
        ffmpeg.input(input_path).output(wav_path, vn=None).run(overwrite_output=True)

    def _write_timecode(self, input_path:str, output_path:str, timecode:str):
        ffmpeg.input(input_path).output(output_path,  c="copy", timecode=timecode).run(overwrite_output=True)

    def _convert_position_bits(self, frame_bits:np.array, position:str, fps:int) -> dict:
        units = None
        tens = None
        shift_units = position_map[fps][position]["units"]
        shift_tens = position_map[fps][position]["tens"]
        
        units = frame_bits[:, shift_units[0]:shift_units[0] + 4]
        total_units = units @ np.array([1, 2, 4, 8])

        if position in ["FF", "HH"]:
            tens = frame_bits[:, shift_tens[0]:shift_tens[0] + 2]
            total_tens = tens @ np.array([1, 2])
        else:
            if len(shift_tens) > 1:
                tens_one = frame_bits[:, shift_tens[0]:shift_tens[0] + 2]
                tens_two = frame_bits[:, shift_tens[1]:shift_tens[1] + 1]
                tens = np.concatenate([tens_one, tens_two], axis=1)
            else:
                tens = frame_bits[:, shift_tens[0]:shift_tens[0] + 3]
            total_tens = tens @ np.array([1, 2, 4])

        return total_units + total_tens * 10
            
    import matplotlib.pyplot as plt

    def decode_ltc(self, input_path:str, fps:int):
        base_path = ".".join(input_path.split(".")[:-1])
        audio_path = f"{base_path}.wav"
        video_path = f"{base_path}_timecode.mp4"
        self._extract_audio(input_path, audio_path)
        data, samplerate = sf.read(audio_path)
        if data.ndim > 1:
            data = data[:, 0]
        samples_per_bit = int(samplerate / fps / 80)
        transitions = np.nonzero(np.diff(np.sign(data)))[0]
        transition_diffs_short = (np.diff(transitions) < (samples_per_bit * 0.75)).astype(int)
        group_starts = []
        group_lengths = []
        idx_counter = 0
        while idx_counter < len(transition_diffs_short):
            if transition_diffs_short[idx_counter] == 0:
                group_starts.append(idx_counter)
                group_lengths.append(1)
                idx_counter += 1
            elif    (
                        idx_counter < len(transition_diffs_short) - 1 and\
                        transition_diffs_short[idx_counter] == 1 and\
                        transition_diffs_short[idx_counter + 1] == 1) or\
                    ( 
                        transition_diffs_short[idx_counter] == 1 and\
                        idx_counter == len(transition_diffs_short) - 1
                    ):
                group_starts.append(idx_counter)
                group_lengths.append(2)
                idx_counter += 2
            else:
                group_starts.append(idx_counter)
                group_lengths.append(-1)
                idx_counter += 1

        group_starts = np.array(group_starts, dtype=np.int64)
        group_lengths = np.array(group_lengths, dtype=np.int8)
        group_values = transition_diffs_short[group_starts]

        is_zero = (group_values == 0) & (group_lengths == 1)
        is_one = (group_values == 1) & (group_lengths == 2)

        labels = np.full(len(group_values), -1)
        labels[is_zero] = 0
        labels[is_one] = 1

        sync_word = np.array([
            0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,1
        ], dtype=np.uint8)
        
        window = np.lib.stride_tricks.sliding_window_view(labels, window_shape=16)
        sync_pos = np.nonzero(np.all(window == sync_word, axis=1))[0]
        frame_starts = sync_pos - 80 + 16
        valid_starts = frame_starts[(frame_starts >= 0) & (frame_starts + 80 <= len(labels))]
        indices = valid_starts[:, None] + np.arange(80)
        frame_bits = labels[indices]

        totals = {}
        for position in position_map[fps]:
            totals[position] = self._convert_position_bits(frame_bits, position, fps)
        
        total_frames = [h*3600*fps + m*60*fps + s*fps + f
                        for h, m, s, f in zip(
                            totals["HH"],
                            totals["MM"],
                            totals["SS"],
                            totals["FF"]
                    )]

        frame_diffs = np.diff(total_frames)
        safety = 10
        anchor_idx = np.where(np.convolve(frame_diffs == 1, np.ones(safety, dtype=int), mode='valid') == safety)[0][0]

        group_sample_positions = transitions[group_starts]
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

def decode_timecode_batch(decode_tasks:list, max_processes=8):
    with multiprocessing.Pool(processes=max_processes) as pool:
        results = pool.starmap(start_LTC_Decoder, decode_tasks)
    for result in results:
        if result[1]: continue
        print(f"Error when decoding: {result[0]}")

def start_LTC_Decoder(input_path:str, fps=50):
    success = False
    try:
        decoder = LTC_Decoder()
        decoder.decode_ltc(input_path, fps)
        success = True
    finally:
        return (input_path, success)
