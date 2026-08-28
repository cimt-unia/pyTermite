#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

import warnings

import pytest

import pytermite.cli as pytermite_cli
from pytermite import config

warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    module=r"click.*",
)


def test_resolve_config_path_uses_env_directory(monkeypatch, tmp_path):
    config_dir = tmp_path / "app-config"
    monkeypatch.setenv("PYTERMITE_CONFIG_PATH", str(config_dir))

    resolved = config.resolve_config_path(
        "PYTERMITE_SERIALS_PATH",
        default_filename="serials.json",
    )

    assert resolved == config_dir / "serials.json"


@pytest.mark.asyncio
async def test_connect_to_gopros_reads_cohn_env_credentials(monkeypatch):
    class DummyWireless:
        def __init__(self, identifier: str):
            self.identifier = identifier
            self.ip_address = ""

    wireless = DummyWireless("cam-42")
    captured: dict[str, str] = {}

    async def fake_connect_gopros_cohn(gopros):
        if False:
            yield None

    async def fake_connect_gopros(gopros):
        if False:
            yield None

    async def fake_connect_gopros_wireless(gopros, ssid: str, password: str):
        captured["ssid"] = ssid
        captured["password"] = password
        assert gopros == {"cam-42": wireless}
        yield wireless

    monkeypatch.setenv("PYTERMITE_COHN_SSID", "my-gopro-ssid")
    monkeypatch.setenv("PYTERMITE_COHN_PASSWORD", "my-super-secret")
    monkeypatch.setattr(pytermite_cli, "connect_gopros_cohn", fake_connect_gopros_cohn)
    monkeypatch.setattr(pytermite_cli, "connect_gopros", fake_connect_gopros)
    monkeypatch.setattr(
        pytermite_cli,
        "connect_gopros_wireless",
        fake_connect_gopros_wireless,
    )

    old_gopros = pytermite_cli.GOPROS
    old_bles = pytermite_cli.BLES
    old_cohn = pytermite_cli.COHN
    old_connected = pytermite_cli.CONNECTED_GOPROS
    try:
        pytermite_cli.GOPROS = {}
        pytermite_cli.BLES = {"cam-42": wireless}
        pytermite_cli.COHN = {}
        pytermite_cli.CONNECTED_GOPROS = set()

        await pytermite_cli._connect_to_gopros()

        assert captured == {"ssid": "my-gopro-ssid", "password": "my-super-secret"}
        assert wireless in pytermite_cli.CONNECTED_GOPROS
        assert "cam-42" not in pytermite_cli.BLES
    finally:
        pytermite_cli.GOPROS = old_gopros
        pytermite_cli.BLES = old_bles
        pytermite_cli.COHN = old_cohn
        pytermite_cli.CONNECTED_GOPROS = old_connected
