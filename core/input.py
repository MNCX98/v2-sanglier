"""Souris et clavier (Windows, via l'API native : aucune dépendance)."""
import sys
import time

IS_WINDOWS = sys.platform == "win32"
VK_F12 = 0x7B

if IS_WINDOWS:
    import ctypes

    _user32 = ctypes.windll.user32


_transform = None   # (x0, y0, échelle, px, py, ref_x, ref_y) : voir core/viewport.py


def set_transform(transform) -> None:
    """Mémorise l'adaptation d'échelle appliquée à la dernière capture (None : aucune)."""
    global _transform
    _transform = transform


def map_point(x: float, y: float) -> tuple[float, float]:
    """Convertit un point de l'image remise à l'échelle d'origine en vraie coordonnée d'écran."""
    if _transform is None:
        return x, y
    x0, y0, s, px, py, rx, ry = _transform
    return x0 + px + (x - x0 - rx) * s, y0 + py + (y - y0 - ry) * s


def click(x: int, y: int, hold_s: float = 0.06) -> None:
    """Clic gauche à la position écran (x, y). Les coordonnées sont celles de l'image remise à l'échelle d'origine
    (origine de la fenêtre + position dans l'image) ; elles sont reconverties en vraies coordonnées d'écran."""
    if not IS_WINDOWS:
        raise RuntimeError("Les clics ne fonctionnent que sous Windows.")
    x, y = map_point(x, y)
    _user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    _user32.mouse_event(0x0002, 0, 0, 0, 0)   # bouton gauche enfoncé
    time.sleep(hold_s)
    _user32.mouse_event(0x0004, 0, 0, 0, 0)   # bouton gauche relâché


def is_key_down(vk: int) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)
