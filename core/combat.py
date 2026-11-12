"""Vision du combat : anneaux sous les combattants, portée du sort (violet), distances."""
from dataclasses import dataclass

import cv2
import numpy as np

from core.grid import grid_distance


@dataclass
class Fighter:
    cx: int
    cy: int
    pixels: int
    w: int = 0
    h: int = 0

    @property
    def center(self) -> tuple[int, int]:
        return self.cx, self.cy


# Colonne d'icônes du panneau « Challenges » quand il est DÉPLIÉ (grosses icônes orange à pastille rouge, à gauche) :
# elle ressemble à un anneau rouge. Replié, le panneau n'affiche rien là et la carte y est visible : on ne l'exclut
# alors pas. Réglé au démarrage par config.challenges_panel_open.
EXCLUDE_ICON_COLUMN = False

# Barre d'ordre de jeu (portraits à barres bleues/rouges, minuteur, « Fin du tour », « Challenges ») en haut à gauche.
# Disposition COMPACTE (un seul portrait, boutons rangés à gauche) : elle tient dans x < 605, y < 301 et la carte
# commence juste à côté ; la détection voit alors tout le reste, y compris le bord haut de la carte.
# Disposition LARGE (frise horizontale de portraits qui s'étire vers la droite) : on ignore tout le quart haut-gauche.
TURN_BAR_COMPACT = True


def set_turn_bar_compact(value: bool) -> None:
    global TURN_BAR_COMPACT
    TURN_BAR_COMPACT = bool(value)


def apply_layout(cfg) -> None:
    """Applique la disposition d'écran choisie dans la configuration (barre d'ordre de jeu, panneau Challenges)."""
    set_icon_column_excluded(cfg.challenges_panel_open)
    set_turn_bar_compact(cfg.turn_bar_compact)


def _turn_bar_zone(h: int, w: int) -> tuple[int, int]:
    """(largeur, hauteur) en pixels de la zone haut-gauche ignorée (barre d'ordre de jeu)."""
    if TURN_BAR_COMPACT:
        return int(0.315 * w), int(0.295 * h)
    return int(0.48 * w), int(0.27 * h)


def set_icon_column_excluded(value: bool) -> None:
    global EXCLUDE_ICON_COLUMN
    EXCLUDE_ICON_COLUMN = bool(value)


def _game_roi_wide(h: int, w: int) -> np.ndarray:
    """Zone de jeu élargie : tout l'écran de jeu sauf les éléments d'interface connus (frise des tours et minuteur,
    barre « Challenges », colonne d'icônes). Elle couvre le bord supérieur gauche de la carte et les fines bandes
    le long des bords, que la zone habituelle ignore. Utilisée seulement quand rien n'a été trouvé dans la zone habituelle."""
    sx, sy = w / 1920.0, h / 1020.0
    roi = np.zeros((h, w), bool)
    roi[int(78 * sy):int(976 * sy), int(316 * sx):int(1604 * sx)] = True
    if TURN_BAR_COMPACT:
        zw, zh = _turn_bar_zone(h, w)
        roi[:zh, :zw] = False                           # barre d'ordre de jeu, minuteur, « Fin du tour », « Challenges »
    else:
        roi[:int(265 * sy), :int(612 * sx)] = False     # frise des tours, portraits, minuteur, « Fin du tour »
        roi[:int(140 * sy), int(612 * sx):int(815 * sx)] = False   # barre « Challenges »
    if EXCLUDE_ICON_COLUMN:
        roi[:int(570 * sy), :int(412 * sx)] = False     # colonne d'icônes du panneau Challenges déplié
    return roi


def movement_mask(scene: np.ndarray) -> np.ndarray:
    """Cases de déplacement : le jeu colore en vert franc (teinte ~50) les cases où mon personnage peut aller ;
    le sol est olive (teinte ~35) et l'herbe des blocs jaune-vert (teinte ~31)."""
    h, w = scene.shape[:2]
    hh, ss, vv = _hsv(scene)
    return ((hh >= 44) & (hh <= 58) & (ss > 110) & (vv > 100) & (_game_roi(h, w) | _game_roi_wide(h, w))).astype(np.uint8)


def reachable_cells(scene: np.ndarray, ref: tuple[int, int]) -> list[tuple[int, int]]:
    """Centres (écran) des cases où mon personnage peut aller, alignés sur la grille dont `ref` est un centre de case
    (typiquement un monstre). Liste vide si aucune case verte n'est visible (plus de PM, ou couleur non reconnue)."""
    from core.grid import to_screen
    m = movement_mask(scene)
    if int(m.sum()) < 600:
        return []
    h, w = m.shape
    frac = cv2.blur(m.astype(np.float32), (9, 5))
    cells = []
    for u in range(-45, 46):
        for v in range(-45, 46):
            x, y = to_screen((u, v), ref)
            if 6 <= x < w - 6 and 4 <= y < h - 4 and frac[y, x] >= 0.7:
                cells.append((x, y))
    return cells


def _game_roi(h: int, w: int) -> np.ndarray:
    roi = np.zeros((h, w), bool)
    roi[int(0.05 * h):int(0.955 * h), int(0.17 * w):int(0.83 * w)] = True
    zw, zh = _turn_bar_zone(h, w)
    roi[:zh, :zw] = False                              # barre d'ordre de jeu (barres bleues/rouges des portraits)
    if EXCLUDE_ICON_COLUMN:
        roi[:int(0.5 * h), :int(0.215 * w)] = False    # colonne d'icônes du panneau Challenges déplié
    return roi


def _hsv(scene):
    return cv2.split(cv2.cvtColor(scene, cv2.COLOR_BGR2HSV))


def _rings(mask: np.ndarray, min_pixels: int = 35, merge=(31, 15)) -> list[tuple[Fighter, float]]:
    """Regroupe les morceaux d'anneau voisins ; retourne (combattant, taux de remplissage)."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, merge)
    joined = cv2.dilate(mask, k)
    n, lab, _, _ = cv2.connectedComponentsWithStats(joined)
    out = []
    for i in range(1, n):
        ys, xs = np.where((lab == i) & (mask > 0))
        if len(xs) < min_pixels:
            continue
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        fill = len(xs) / max(1, (x1 - x0 + 1) * (y1 - y0 + 1))
        out.append((Fighter(int((x0 + x1) // 2), int((y0 + y1) // 2), len(xs),
                            int(x1 - x0 + 1), int(y1 - y0 + 1)), fill))
    return out



# Anneau sous un combattant : ellipse d'environ 47×22 px (identique en mode normal et en mode créature).
RING_W, RING_H = 47, 22


def _ring_template() -> np.ndarray:
    t = np.zeros((RING_H + 2, RING_W + 2), np.float32)
    cv2.ellipse(t, ((RING_W + 2) // 2, (RING_H + 2) // 2), (RING_W // 2, RING_H // 2), 0, 0, 360, 1.0, 1)
    return t


_RING = _ring_template()


def _find_rings(mask: np.ndarray, min_cover: float = 0.55, max_fill: float = 2.6) -> list[Fighter]:
    """Cherche des anneaux par leur forme : sépare les combattants sur des cases voisines.

    min_cover : part de l'ellipse retrouvée dans le masque de couleur (un anneau à demi caché reste accepté).
    max_fill  : écarte les formes pleines (cases, icônes, chiffres de dégâts), qui ne sont pas des anneaux fins.
    """
    return [f for f, _ in _find_rings_scored(mask, min_cover, max_fill)]


def _find_rings_scored(mask: np.ndarray, min_cover: float = 0.55, max_fill: float = 2.6) -> list[tuple[Fighter, float]]:
    """Comme _find_rings, avec la couverture de l'ellipse pour chaque anneau trouvé."""
    th, tw = _RING.shape
    if mask.shape[0] < th or mask.shape[1] < tw:
        return []
    m = cv2.dilate((mask > 0).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
    n_ring = float(_RING.sum())
    cover = cv2.matchTemplate(m, _RING, cv2.TM_CCORR) / n_ring
    raw = (mask > 0).astype(np.float32)
    area = cv2.boxFilter(raw, -1, (tw, th), normalize=False, borderType=cv2.BORDER_CONSTANT)
    ys, xs = np.where(cover >= min_cover)
    order = np.argsort(-cover[ys, xs])
    found: list[tuple[Fighter, float]] = []
    for i in order:
        x, y = int(xs[i]), int(ys[i])
        cx, cy = x + tw // 2, y + th // 2
        if any(abs(cx - f.cx) < 20 and abs(cy - f.cy) < 10 for f, _ in found):
            continue
        inside = float(area[y + th // 2, x + tw // 2])
        if inside > max_fill * n_ring:
            continue
        found.append((Fighter(cx, cy, int(inside), tw, th), float(cover[y, x])))
        if len(found) >= 24:
            break
    return found


def find_enemies(scene: np.ndarray) -> list[Fighter]:
    """Adversaires : anneau bleu sous chaque monstre.

    Méthode validée : on regroupe les morceaux d'anneau. Si un groupe est trop grand pour être un seul
    anneau (monstres sur des cases voisines), on le découpe en cherchant la forme de l'anneau.
    """
    h, w = scene.shape[:2]
    hh, ss, vv = _hsv(scene)
    blue = (hh > 98) & (hh < 112) & (ss > 140) & (vv > 140)
    out = _enemies_in(blue & _game_roi(h, w), h, w)
    if not out:                                             # rien : un adversaire dans un angle de la carte ?
        out = _enemies_in(blue & _game_roi_wide(h, w), h, w)
    if not out:                                             # toujours rien : un anneau à moitié caché par un décor ?
        out = _enemies_partial((blue & _game_roi_wide(h, w)).astype(np.uint8) * 255)
    if not out:                                             # tout dernier recours : un simple arc d'anneau dépasse d'un décor
        out = _enemies_arc((blue & _game_roi_wide(h, w)).astype(np.uint8) * 255)
    return out


ENEMY_PARTIAL_COVER = 0.25      # couverture minimale d'un anneau bleu à moitié caché (dernier recours)


def _enemies_partial(m: np.ndarray) -> list[Fighter]:
    """Dernier recours quand AUCUN adversaire n'est vu : cherche la forme d'anneaux bleus en partie cachés."""
    rings = [(f, c) for f, c in _find_rings_scored(m, min_cover=ENEMY_PARTIAL_COVER) if c >= ENEMY_PARTIAL_COVER]
    rings.sort(key=lambda fc: -fc[1])
    return [f for f, _ in rings[:6]]


ARC_MIN_PIXELS = 12          # un arc plus petit est confondu avec du bruit
ARC_MAX_PIXELS = 400         # au-delà, ce n'est plus un anneau caché mais autre chose de bleu
ARC_TOLERANCE = 1.6          # écart maximal (px) entre un pixel de l'arc et l'ellipse de l'anneau
ARC_MIN_PRECISION = 0.85     # part des pixels bleus qui doivent être SUR l'ellipse (sinon : pas un anneau)


def _enemies_arc(m: np.ndarray) -> list[Fighter]:
    """Dernier recours : monstre presque entièrement caché par un décor (bloc d'herbe, rocher), dont seul un petit
    arc de l'anneau bleu dépasse (quelques dizaines de pixels). La couverture de l'anneau est alors trop faible
    pour _enemies_partial ; on mesure plutôt si les pixels bleus visibles se placent EXACTEMENT sur une ellipse de
    la taille connue de l'anneau. Un arc, même court, donne alors un centre unique (la courbure fixe la position).
    """
    pts_mask = m > 0
    if int(pts_mask.sum()) < ARC_MIN_PIXELS:
        return []
    a, b = RING_W / 2.0, RING_H / 2.0
    joined = cv2.dilate(pts_mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    n, lab = cv2.connectedComponents(joined)
    found: list[tuple[Fighter, int]] = []
    for i in range(1, n):
        gy, gx = np.where((lab == i) & pts_mask)
        if not (ARC_MIN_PIXELS <= len(gx) <= ARC_MAX_PIXELS):
            continue
        px, py = gx.astype(np.float32), gy.astype(np.float32)
        best = None
        for cx in range(int(px.max() - a - 3), int(px.min() + a + 4)):
            dx = (px - cx) / a
            for cy in range(int(py.max() - b - 3), int(py.min() + b + 4)):
                dy = (py - cy) / b
                r = np.hypot(dx, dy)
                radius = np.hypot(dx * a, dy * b) / np.maximum(r, 1e-6)       # rayon local de l'ellipse, en px
                on = int((np.abs(r - 1.0) * radius <= ARC_TOLERANCE).sum())
                if best is None or on > best[0]:
                    best = (on, cx, cy)
        if best and best[0] >= ARC_MIN_PIXELS and best[0] / len(gx) >= ARC_MIN_PRECISION:
            found.append((Fighter(best[1], best[2], best[0], RING_W, RING_H), best[0]))
    found.sort(key=lambda fp: -fp[1])
    return [f for f, _ in found[:6]]


def _enemies_in(zone: np.ndarray, h: int, w: int) -> list[Fighter]:
    m = zone.astype(np.uint8) * 255
    out: list[Fighter] = []
    for f, _ in _rings(m):
        if f.w <= RING_W + 10 and f.h <= RING_H + 8:
            out.append(f)                                   # un seul anneau
            continue
        x0, y0 = max(0, f.cx - f.w // 2 - 6), max(0, f.cy - f.h // 2 - 6)
        x1, y1 = min(w, f.cx + f.w // 2 + 7), min(h, f.cy + f.h // 2 + 7)
        parts = _find_rings(m[y0:y1, x0:x1])
        if parts:
            for p in parts:
                out.append(Fighter(p.cx + x0, p.cy + y0, p.pixels, p.w, p.h))
        else:
            out.append(f)                                   # découpage impossible : on garde le groupe
    return out


def find_me(scene: np.ndarray, hint: tuple[int, int] | None = None) -> Fighter | None:
    """Mon personnage : anneau rouge (ellipse d'environ 48×25 px, en mode normal comme en mode créature).

    On écarte les chiffres de dégâts rouges (plus gros), les cases rouges et les icônes rouges.
    `hint` : position connue (mon personnage ne bouge pas pendant le combat) pour départager.
    """
    h, w = scene.shape[:2]
    hh, ss, vv = _hsv(scene)
    red = ((hh < 8) | (hh > 172)) & (ss > 120) & (vv > 120)
    found = _find_me_in((red & _game_roi(h, w)).astype(np.uint8) * 255, hint)
    if found is None:                                       # rien : mon personnage dans un angle de la carte ?
        found = _find_me_in((red & _game_roi_wide(h, w)).astype(np.uint8) * 255, hint)
    return found


def _find_me_in(m: np.ndarray, hint: tuple[int, int] | None) -> Fighter | None:
    cands = [f for f, fill in _rings(m, min_pixels=120)
             if 120 <= f.pixels <= 650 and 40 <= f.w <= 60 and 15 <= f.h <= 40 and f.w / f.h >= 1.3 and fill < 0.6]
    if not cands:
        return _find_me_partial(m, hint)
    if hint is not None:
        near = [f for f in cands if abs(f.cx - hint[0]) <= 20 and abs(f.cy - hint[1]) <= 20]
        if near:
            return near[0]
    return max(cands, key=lambda f: f.pixels)


PARTIAL_NEAR_HINT = 0.28     # couverture minimale de l'anneau près de la dernière position connue
PARTIAL_ALONE = 0.33         # couverture minimale sans position connue
PARTIAL_MARGIN = 1.4         # l'anneau retenu doit être nettement meilleur que le suivant


def _find_me_partial(m: np.ndarray, hint: tuple[int, int] | None) -> Fighter | None:
    """Anneau rouge à moitié caché (personnage derrière un décor) : on cherche la FORME de l'anneau.
    Un arc visible suffit pour retrouver le centre, car la taille de l'ellipse est connue."""
    rings = _find_rings_scored(m, min_cover=PARTIAL_NEAR_HINT)
    if not rings:
        return None
    if hint is not None:                                   # tout près de la dernière position connue : on affine
        near = [(f, c) for f, c in rings if abs(f.cx - hint[0]) <= 10 and abs(f.cy - hint[1]) <= 6]
        if near:
            return max(near, key=lambda fc: fc[1])[0]
    rings.sort(key=lambda fc: -fc[1])                      # sinon : seulement si une seule forme se détache nettement
    best, cover = rings[0]
    if cover < PARTIAL_ALONE:
        return None
    if len(rings) > 1 and cover < PARTIAL_MARGIN * rings[1][1]:
        return None                                        # ambigu : plusieurs formes semblables
    return best


def range_mask(scene: np.ndarray) -> np.ndarray:
    """Cases où le sort sélectionné peut être lancé (violet affiché par le jeu)."""
    h, w = scene.shape[:2]
    hh, ss, vv = _hsv(scene)
    # Le bleu de la portée varie un peu selon le sol de la carte (teinte 118 sur sol vert, 122-123 sur sable) :
    # on accepte toute la plage 113-130. Les anneaux bleus des monstres (teinte 98-112) restent à part.
    m = ((hh >= 113) & (hh <= 130) & (ss > 100) & (vv > 130) & (_game_roi(h, w) | _game_roi_wide(h, w))).astype(np.uint8)
    return m


def spell_border_pixels(scene: np.ndarray, x: int, y: int, w: int, h: int, pad: int = 7) -> int:
    """Nombre de pixels orange du cadre qui entoure l'icône d'un sort sélectionné (0 si non sélectionné)."""
    sh, sw = scene.shape[:2]
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(sw, x + w + pad), min(sh, y + h + pad)
    if x1 <= x0 or y1 <= y0:
        return 0                                        # icône hors de l'image (fenêtre redimensionnée) : pas de cadre vu
    roi = cv2.cvtColor(scene[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    orange = ((roi[:, :, 0] >= 8) & (roi[:, :, 0] <= 20) & (roi[:, :, 1] > 180) & (roi[:, :, 2] > 200)).astype(np.uint8)
    inner = np.zeros_like(orange)                       # on ne compte que le cadre, pas l'intérieur de l'icône
    iy0, iy1, ix0, ix1 = y - y0 + 2, y - y0 + h - 2, x - x0 + 2, x - x0 + w - 2
    inner[max(0, iy0):max(0, iy1), max(0, ix0):max(0, ix1)] = 1
    return int((orange * (1 - inner)).sum())


def spell_selected(scene: np.ndarray, x: int, y: int, w: int, h: int, pad: int = 7, min_pixels: int = 150) -> bool:
    """Un sort sélectionné est entouré d'un cadre orange dans la barre de sorts : indicateur qui ne dépend
    pas de la couleur du sol de la carte. (x, y, w, h) = position de l'icône du sort trouvée à l'écran."""
    return spell_border_pixels(scene, x, y, w, h, pad) >= min_pixels


def range_visible(scene: np.ndarray, min_pixels: int = 3000) -> bool:
    return int(range_mask(scene).sum()) >= min_pixels


def range_fraction(mask: np.ndarray, center: tuple[int, int], half=(34, 15)) -> float:
    """Part de violet autour d'un point (case d'un adversaire)."""
    x, y = center
    h, w = mask.shape
    patch = mask[max(0, y - half[1]):min(h, y + half[1]), max(0, x - half[0]):min(w, x + half[0])]
    return float(patch.mean()) if patch.size else 0.0


def sort_by_distance(fighters: list[Fighter], origin: tuple[int, int]) -> list[Fighter]:
    return sorted(fighters, key=lambda f: grid_distance(f.center, origin))
