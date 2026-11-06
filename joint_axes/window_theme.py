"""Windows başlık çubuğunu uygulama temasına uyarlar."""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Mapping


def _colorref(hex_color: str) -> int:
    """#RRGGBB rengini Windows COLORREF (0x00BBGGRR) değerine çevirir."""

    value = hex_color.lstrip("#")
    if len(value) != 6:
        return 0
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def apply_title_bar_theme(
    window: tk.Misc,
    palette: Mapping[str, str],
    dark: bool,
) -> None:
    """Windows 10/11 başlık çubuğunu tema paletine yaklaştırır.

    Windows 11'de caption/text/border renkleri doğrudan atanır. Windows 10'da
    yalnızca koyu mod ve sistem renkleri desteklenir; desteklenmeyen öznitelikler
    sessizce yok sayılır.
    """

    if sys.platform != "win32":
        return

    try:
        import ctypes
        from ctypes import wintypes

        window.update_idletasks()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND

        hwnd = wintypes.HWND(window.winfo_id())
        root_hwnd = user32.GetAncestor(hwnd, 2)  # GA_ROOT
        if not root_hwnd:
            root_hwnd = user32.GetParent(hwnd)
        if not root_hwnd:
            root_hwnd = hwnd

        dwmapi = ctypes.WinDLL("dwmapi")
        set_attribute = dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        set_attribute.restype = ctypes.c_long

        dark_value = ctypes.c_int(1 if dark else 0)
        # 20: Windows 10 2004+, 19: eski Windows 10.
        result = set_attribute(
            root_hwnd,
            20,
            ctypes.byref(dark_value),
            ctypes.sizeof(dark_value),
        )
        if result != 0:
            set_attribute(
                root_hwnd,
                19,
                ctypes.byref(dark_value),
                ctypes.sizeof(dark_value),
            )

        # 35: caption, 36: text, 34: border (Windows 11).
        for attribute, color_key in (
            (35, "bg"),
            (36, "text"),
            (34, "border"),
        ):
            color = ctypes.c_uint(_colorref(palette[color_key]))
            set_attribute(
                root_hwnd,
                attribute,
                ctypes.byref(color),
                ctypes.sizeof(color),
            )
    except Exception:  # noqa: BLE001 - eski Windows / DWM kapalı
        return
