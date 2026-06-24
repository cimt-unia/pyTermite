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

position_map = {
    50: {
        "FF": {
            "units": (0,),
            "tens":  (8, 11)
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
        self.samples_per_bit = self.sample_rate / self.fps / 80
        self.total_samples = 0
        self.frame_queue = queue.Queue(maxsize=self.fps)

    def play_control_sound(self, filename: str, amplification:float=1.0):
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(BASE_DIR, "audios", f"{filename}.wav")
        data, samplerate = sf.read(path)
        sd.play(data * amplification, samplerate)
        sd.wait()

    def print_allowed_fps(self) -> None:
        print([fps for fps in position_map.keys()])

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
        level = -1
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
        self.play_control_sound("start_recording")
        while not self.stop_event.is_set():
            with sd.OutputStream(samplerate=self.sample_rate, device=self.device, 
                        channels=1, dtype='float32',
                        blocksize=self.samples_per_frame,
                        callback=self.callback):
                while not self.stop_event.is_set():
                    sd.sleep(1000)
        self.play_control_sound("stop_recording", 2.0)