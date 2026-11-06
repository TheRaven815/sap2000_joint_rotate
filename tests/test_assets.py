"""Uygulama ikon varlıklarının paket içinde bulunduğunu doğrular."""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "joint_axes" / "assets"


def test_icon_assets_exist() -> None:
    ico = ASSETS / "app.ico"
    png = ASSETS / "tiger.png"

    assert ico.is_file()
    assert png.is_file()
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
