"""Zone de jeu (la carte visible) et bordure de carte.

Un clic sur une case du bord de la carte fait changer de carte. Pour ne pas cliquer un monstre posé au bord, on
mesure sa distance aux bords de la zone de jeu. La zone est estimée sur l'image remise à l'échelle d'origine :
  - à droite : le panneau de sorts et de menus (fixe, ancré sur la bulle de discussion) ;
  - en haut et en bas : les bandes noires de la fenêtre et la barre de titre ;
  - à gauche : le bandeau de publicité de BlueStacks s'il est affiché, sinon le bord de la fenêtre.
"""
import cv2
import numpy as np

PANEL_X = 1600                 # bord gauche du panneau de droite (mise en page d'origine, 1920×1020)
AD_PANEL_RIGHT = 316           # bord droit du bandeau de publicité BlueStacks
CONTENT_V = 70                 # luminosité minimale d'un pixel « de carte » (le noir des bandes et la barre de titre sont plus sombres)


def _has_ad_panel(scene: np.ndarray) -> bool:
    """Le bandeau de publicité a un fond bleu nuit uni qui n'existe nulle part ailleurs dans le jeu."""
    band = scene[60:scene.shape[0] - 60, 0:min(300, scene.shape[1])]
    if band.size == 0:
        return False
    b, g, r = band[..., 0].astype(int), band[..., 1].astype(int), band[..., 2].astype(int)
    navy = (b > r + 12) & (b < 70) & (r < 30) & (g < 40)
    return float(navy.mean()) > 0.08


def _longest_run(flags: np.ndarray, start: int = 0, max_gap: int = 12) -> tuple[int, int] | None:
    """Plus longue plage continue de True (les trous de moins de `max_gap` lignes ne l'interrompent pas) : une ligne
    claire isolée au bord de la fenêtre n'allonge pas la zone de jeu. Retourne (début, fin exclue) ou None."""
    idx = np.where(flags)[0]
    idx = idx[idx >= start]
    if len(idx) == 0:
        return None
    breaks = np.where(np.diff(idx) > max_gap)[0]
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [len(idx) - 1]))
    k = int(np.argmax(idx[ends] - idx[starts]))
    return int(idx[starts[k]]), int(idx[ends[k]]) + 1


def map_area(scene: np.ndarray) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) de la carte visible dans l'image."""
    h, w = scene.shape[:2]
    v = scene.max(axis=2)
    x1 = min(PANEL_X, w)
    x0 = AD_PANEL_RIGHT if _has_ad_panel(scene) else 0
    cols = slice(max(x0, 0) + 40, max(x0 + 41, x1 - 40))
    rows_bright = (v[:, cols] > CONTENT_V).mean(axis=1)               # part de pixels « de carte » par ligne
    y0, y1 = _longest_run(rows_bright > 0.30, start=38) or (0, h)      # sous la barre de titre BlueStacks
    mid = slice(min(h - 1, y0 + 60), max(y0 + 61, y1 - 60))
    if x0 == 0:                                                       # sans publicité : bord gauche de la fenêtre
        run = _longest_run((v[mid, :x1] > CONTENT_V).mean(axis=0) > 0.30)
        x0 = run[0] if run else 0
    return x0, y0, x1, y1


def inner_area(area: tuple[int, int, int, int], margin_pct: float) -> tuple[int, int, int, int]:
    """Zone dont on exclut une bande de `margin_pct` % (de la largeur et de la hauteur) le long de chaque bord."""
    x0, y0, x1, y1 = area
    mx, my = (x1 - x0) * margin_pct / 100.0, (y1 - y0) * margin_pct / 100.0
    return int(x0 + mx), int(y0 + my), int(x1 - mx), int(y1 - my)


def near_border(center: tuple[int, int], area: tuple[int, int, int, int], margin_pct: float) -> bool:
    """True si `center` est dans la bande de bordure (ou hors de la zone). margin_pct <= 0 : fonction désactivée."""
    if margin_pct <= 0:
        return False
    ix0, iy0, ix1, iy1 = inner_area(area, margin_pct)
    return not (ix0 <= center[0] <= ix1 and iy0 <= center[1] <= iy1)
