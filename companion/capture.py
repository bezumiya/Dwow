"""Capture of the WoW window's client area via PrintWindow.

PrintWindow works even when the window is behind others (but not minimized)
and captures DirectX content with the PW_RENDERFULLCONTENT flag.
"""
from __future__ import annotations

import ctypes
import logging
from collections.abc import Iterator

import pywintypes
import win32con
import win32gui
import win32ui
from PIL import Image
from log_i18n import text as T

log = logging.getLogger("dwow.capture")

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2

WOW_WINDOW_CLASSES = {"GxWindowClass", "GxWindowClassD3d"}

_warned_bpp = False


def set_dpi_aware() -> None:
    """Must run before any window call: without DPI awareness, Windows skews
    the coordinates on monitors with scaling != 100%."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def find_window(title_substring: str) -> int | None:
    """Prefers the WoW client's window class, then an exact title match, then
    a substring — a browser tab with 'World of Warcraft' in the title must not
    beat the game."""
    matches: list[tuple[int, str]] = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and title_substring.lower() in title.lower():
                matches.append((hwnd, title))

    win32gui.EnumWindows(_cb, None)
    if not matches:
        return None
    for hwnd, _title in matches:
        try:
            if win32gui.GetClassName(hwnd) in WOW_WINDOW_CLASSES:
                return hwnd
        except win32gui.error:
            pass
    for hwnd, title in matches:
        if title.lower() == title_substring.lower():
            return hwnd
    return matches[0][0]


def is_minimized(hwnd: int) -> bool:
    try:
        return bool(win32gui.IsIconic(hwnd))
    except win32gui.error:
        return True


def is_foreground(hwnd: int) -> bool:
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except win32gui.error:
        return False


def _capture_client_printwindow(hwnd: int) -> Image.Image | None:
    """Returns the client area as an RGB image, or None if the capture fails.

    The window can be destroyed/minimized between any pair of calls (the loop
    runs once per second for hours), so each GDI resource is released
    independently — a leak here would exhaust the process's 10k handles.
    """
    global _warned_bpp
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
    except win32gui.error:
        return None
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None

    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
    except win32gui.error:
        return None
    if not hwnd_dc:
        return None

    mfc_dc = save_dc = bmp = None
    try:
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bmp)
        ok = ctypes.windll.user32.PrintWindow(
            hwnd, save_dc.GetSafeHdc(), PW_CLIENTONLY | PW_RENDERFULLCONTENT
        )
        if not ok:
            return None
        info = bmp.GetInfo()
        if info["bmBitsPixel"] != 32:
            # session with reduced color depth (e.g. 16bpp RDP):
            # the buffer doesn't match the expected BGRX layout
            if not _warned_bpp:
                log.warning(T(
                    "Bitmap de %d bpp (esperado 32); captura exige cor de 32 bits.",
                    "%d-bpp bitmap (expected 32); capture requires 32-bit color."),
                    info["bmBitsPixel"])
                _warned_bpp = True
            return None
        data = bmp.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB", (info["bmWidth"], info["bmHeight"]), data, "raw", "BGRX", 0, 1
        )
    except (win32ui.error, win32gui.error, pywintypes.error):
        return None
    finally:
        if bmp is not None:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
            except Exception:
                pass
        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception:
                pass
        if mfc_dc is not None:
            try:
                mfc_dc.DeleteDC()
            except Exception:
                pass
        try:
            win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def _capture_client_bitblt(hwnd: int) -> Image.Image | None:
    """Fast client-area capture for a visible or background DWM window."""
    global _warned_bpp
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
    except win32gui.error:
        return None
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    try:
        hwnd_dc = win32gui.GetDC(hwnd)
    except win32gui.error:
        return None
    if not hwnd_dc:
        return None

    src_dc = save_dc = bmp = None
    try:
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = src_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(src_dc, width, height)
        save_dc.SelectObject(bmp)
        save_dc.BitBlt((0, 0), (width, height), src_dc, (0, 0), win32con.SRCCOPY)
        info = bmp.GetInfo()
        if info["bmBitsPixel"] != 32:
            return None
        data = bmp.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB", (info["bmWidth"], info["bmHeight"]), data, "raw", "BGRX", 0, 1
        )
    except (win32ui.error, win32gui.error, pywintypes.error):
        return None
    finally:
        if bmp is not None:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
            except Exception:
                pass
        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception:
                pass
        if src_dc is not None:
            try:
                src_dc.DeleteDC()
            except Exception:
                pass
        try:
            win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass


def capture_candidates(hwnd: int, method: str = "auto") -> Iterator[tuple[str, Image.Image]]:
    """Return capture candidates in preference order.

    Decoding decides which candidate is valid: a graphics API may return a
    perfectly shaped but stale/corrupted image, which capture alone cannot know.
    """
    if is_minimized(hwnd):
        return
    methods = {
        "auto": (("bitblt", _capture_client_bitblt),
                 ("printwindow", _capture_client_printwindow)),
        "bitblt": (("bitblt", _capture_client_bitblt),),
        "printwindow": (("printwindow", _capture_client_printwindow),),
    }.get(method, ())
    for name, func in methods:
        img = func(hwnd)
        if img is not None:
            yield name, img


def capture_client(hwnd: int, method: str = "auto") -> Image.Image | None:
    """Compatibility helper; protocol-aware callers should use candidates."""
    candidate = next(capture_candidates(hwnd, method), None)
    return candidate[1] if candidate else None
