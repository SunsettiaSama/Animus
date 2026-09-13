"""win32 窗口工具：无边框、置顶、色键透明（桌宠窗口）。

仅 Windows 有效；其他平台优雅降级为普通 NOFRAME 窗口。
"""

from __future__ import annotations

import sys

import pygame

MAGIC_KEY = (255, 0, 255)  # 品红 = 透明色键

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080  # 不出现在任务栏
LWA_COLORKEY = 0x00000001

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_FRAMECHANGED = 0x0020


def is_windows() -> bool:
    return sys.platform == "win32"


def make_pet_window(size: tuple[int, int], *, title: str = "desktop-pet") -> pygame.Surface:
    """创建无边框窗口；Windows 下再叠加色键透明 + 置顶 + 任务栏隐藏。"""
    screen = pygame.display.set_mode(size, pygame.NOFRAME)
    pygame.display.set_caption(title)
    screen.fill(MAGIC_KEY)
    if is_windows():
        _apply_layered(pygame.display.get_wm_info().get("hwnd"))
    return screen


def _apply_layered(hwnd: int) -> None:
    import ctypes

    if not hwnd:
        return  # dummy 视频驱动（无头自检）下没有原生窗口
    user32 = ctypes.windll.user32
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd,
        GWL_EXSTYLE,
        ex | WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
    )
    user32.SetLayeredWindowAttributes(
        hwnd, _colorref(MAGIC_KEY), 0, LWA_COLORKEY
    )
    user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED,
    )


def _colorref(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return r | (g << 8) | (b << 16)


def reassert_topmost() -> None:
    """被其他置顶窗口压住时调用（如用户点击了别的置顶窗口）。"""
    if not is_windows():
        return
    import ctypes

    hwnd = pygame.display.get_wm_info().get("hwnd")
    if not hwnd:
        return
    ctypes.windll.user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
    )