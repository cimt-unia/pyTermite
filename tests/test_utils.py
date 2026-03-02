#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

from dataclasses import dataclass
from enum import Enum

from pytermite import utils


class Color(Enum):
    RED = 1
    GREEN = 2


@dataclass
class Thing:
    a: int
    b: str


def test_create_base_url_short_serial():
    url = utils.create_base_url("C123456789")
    assert url == "http://172.27.189.51:8080/gopro/camera"


def test_reverse_and_serialize_dict_dataclass_and_enum():
    d = {"cam1": "SER1", "cam2": "SER2"}
    rev = utils.reverse_dict(d)
    assert rev["SER1"] == "cam1"

    thing = Thing(1, "x")
    data = {"t": thing, "c": Color.RED, "n": None, "s": "ok", "i": 3}
    serialized = utils.serialize_dict(data)
    assert serialized["t"]["a"] == 1
    assert serialized["t"]["b"] == "x"
    assert serialized["c"] == "RED"
    assert serialized["n"] is None


def test_load_serial_numbers_from_json_and_write(tmp_path):
    p = tmp_path / "serials.json"
    mapping = {"camA": "S1", "camB": "S2"}
    utils.write_json_to_file(mapping, p)
    loaded = utils.load_serial_numbers_from_json(p)
    assert loaded == mapping

    # write with no .json suffix
    p2 = tmp_path / "out"
    utils.write_json_to_file(mapping, p2)
    assert p2.with_suffix(".json").exists()


def test_serialize_fallback_object():
    class X:
        def __init__(self):
            self.foo = "bar"

    x = X()
    out = utils.serialize_dict({"x": x})
    assert out["x"]["foo"] == "bar"
