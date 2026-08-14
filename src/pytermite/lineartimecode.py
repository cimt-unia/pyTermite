"""
Linear Time Code Generator and utilities used for injecting timecode into audio track.
"""

#  Copyright (c) 2026 by Patrick Braun
#
#  SPDX-License-Identifier: BSD-3-Clause


def create_linear_timecode(hours: int, minutes: int, seconds: int, frames: int):

    # initialize 80-bit array with zeros
    timecode = [0] * 80

    # write bits into subset
    def write_bits(value: int, start_bit: int, bit_count: int):
        for i in range(bit_count):
            timecode[start_bit + i] = (value >> i) & 1

    # frame_units + frame_tens
    write_bits(frames % 10, 0, 4)
    write_bits(frames // 10, 8, 2)

    # second_units + second_tens
    write_bits(seconds % 10, 16, 4)
    write_bits(seconds // 10, 24, 3)

    # min_units + min_tens
    write_bits(minutes % 10, 32, 4)
    write_bits(minutes // 10, 40, 3)

    # hour_units + hour_tens
    write_bits(hours % 10, 48, 4)
    write_bits(hours // 10, 56, 2)

    # sync word
    sync_word = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]
    for i in range(16):
        timecode[64 + i] = sync_word[i]

    return timecode


# Example test: 01:23:45:12
tc = create_linear_timecode(1, 23, 45, 12)
