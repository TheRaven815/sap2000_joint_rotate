"""Windows başlık çubuğu renk yardımcıları."""

from __future__ import annotations

from joint_axes.window_theme import _colorref


def test_colorref_uses_windows_byte_order() -> None:
    assert _colorref("#c8102e") == 0x002E10C8
    assert _colorref("#ffffff") == 0x00FFFFFF
    assert _colorref("#000000") == 0
