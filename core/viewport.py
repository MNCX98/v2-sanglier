"""Adaptation automatique à la taille d'affichage du jeu.

BlueStacks agrandit ou réduit le jeu selon l'espace disponible (par exemple quand le bandeau de publicité à gauche
apparaît ou disparaît). Toutes les images du programme (monstres, boutons) ont été prises à l'échelle d'origine :
si le jeu est affiché 12 % plus gros, elles ne sont plus reconnues.

On repère donc la bulle verte du bouton de discussion (toujours visible), on en déduit l'échelle et la position du jeu,
puis on remet l'image capturée à l'échelle d'origine. Les clics sont reconvertis dans l'autre sens (core/input.py)."""
import time

import cv2
import numpy as np

from core.paths import app_dir

REF_POS = (1748, 895)           # position de la bulle dans la mise en page d'origine (échelle 1)
REF_SIZE = (1920, 1020)         # taille de la fenêtre d'origine (largeur, hauteur)
MATCH_OK = 0.85                 # score minimal pour accepter le repère
KEEP_OK = 0.80                  # score minimal pour garder la calibration en cours
RETRY_AFTER_S = 2.0             # délai avant de rechercher à nouveau si le repère est invisible


def _load_anchor():
    path = app_dir() / "assets" / "ancre" / "ancre_bulle.png"
    try:
        return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None


def _match(scene, tpl, x0, y0, x1, y1):
    """Meilleur score de correspondance de `tpl` dans la zone [x0:x1, y0:y1] ; retourne (score, (x, y) de la scène)."""
    th, tw = tpl.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(scene.shape[1], x1), min(scene.shape[0], y1)
    if x1 - x0 < tw or y1 - y0 < th:
        return 0.0, (0, 0)
    res = cv2.matchTemplate(scene[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    return float(mx), (loc[0] + x0, loc[1] + y0)


class Viewport:
    def __init__(self, log_hook=None):
        self.tpl = _load_anchor()
        self.scale = 1.0
        self.pos = REF_POS                 # position du repère dans l'image capturée
        self.identity = True               # True : l'affichage est déjà à l'échelle d'origine, rien à modifier
        self.retry_at = 0.0
        self.log_hook = log_hook
        self._scaled = {}                  # gabarit redimensionné, par échelle

    def _tpl(self, s: float):
        key = round(s, 3)
        if key not in self._scaled:
            self._scaled[key] = self.tpl if abs(s - 1) < 1e-6 else cv2.resize(
                self.tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        return self._scaled[key]

    def _check(self, scene) -> bool:
        """La calibration en cours est-elle toujours valable ? (recherche rapide autour de la position connue)"""
        px, py = self.pos
        score, loc = _match(scene, self._tpl(self.scale), px - 12, py - 12,
                            px + int(self.tpl.shape[1] * self.scale) + 12, py + int(self.tpl.shape[0] * self.scale) + 12)
        if score >= KEEP_OK:
            self.pos = loc
            return True
        return False

    def _search(self, scene) -> bool:
        """Cherche le repère à toutes les échelles plausibles (zone en bas à droite de la fenêtre).
        Recherche grossière en demi-résolution (rapide), puis affinage en pleine résolution autour du meilleur candidat."""
        h, w = scene.shape[:2]
        x0, y0 = int(w * 0.5), int(h * 0.5)
        half = cv2.resize(scene[y0:h, x0:w], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        best = (0.0, 1.0, (0, 0))
        for s in np.arange(0.80, 1.46, 0.02):                            # recherche grossière (demi-résolution)
            t = cv2.resize(self._tpl(float(s)), None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            if half.shape[0] <= t.shape[0] or half.shape[1] <= t.shape[1]:
                continue
            _, mx, _, loc = cv2.minMaxLoc(cv2.matchTemplate(half, t, cv2.TM_CCOEFF_NORMED))
            if mx > best[0]:
                best = (float(mx), float(s), (x0 + loc[0] * 2, y0 + loc[1] * 2))
        cx, cy = best[2]
        best = (0.0, best[1], best[2])
        for s in np.arange(best[1] - 0.03, best[1] + 0.0301, 0.005):    # affinage en pleine résolution (petite zone)
            score, loc = _match(scene, self._tpl(float(s)), cx - 14, cy - 14, cx + int(self.tpl.shape[1] * s) + 14,
                                cy + int(self.tpl.shape[0] * s) + 14)
            if score > best[0]:
                best = (score, float(s), loc)
        if best[0] < MATCH_OK:
            return False
        _, s, loc = best
        self.scale, self.pos = round(s, 3), loc
        self.identity = abs(s - 1) < 0.004 and abs(loc[0] - REF_POS[0]) <= 1 and abs(loc[1] - REF_POS[1]) <= 1
        if self.log_hook:
            if self.identity:
                self.log_hook("Affichage du jeu : échelle d'origine, aucune adaptation nécessaire.")
            else:
                self.log_hook(f"Affichage du jeu à l'échelle {s:.3f} : le programme adapte automatiquement l'image.")
        return True

    def normalize(self, scene):
        """Retourne (image à l'échelle d'origine, (échelle, x, y du repère)) ; la transformation vaut None si rien à faire."""
        if self.tpl is None:
            return scene, None
        if not self._check(scene) and time.time() >= self.retry_at:
            if not self._search(scene):
                self.retry_at = time.time() + RETRY_AFTER_S             # repère invisible : on garde l'ancienne calibration
        if self.identity:
            return scene, None
        s, (px, py) = self.scale, self.pos
        h, w = scene.shape[:2]
        m = np.float32([[1 / s, 0, REF_POS[0] - px / s], [0, 1 / s, REF_POS[1] - py / s]])
        out = cv2.warpAffine(scene, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
        return out, (s, px, py)
