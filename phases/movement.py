"""Déplacements : choix de la case (cases vertes fournies par le jeu, sinon calcul géométrique), ma position
(anneau rouge, dernière position connue ou centre de la portée) et exécution du déplacement."""
import time

import numpy as np

from core import input as inp
from core.combat import _game_roi, find_me, sort_by_distance
from core.combat import reachable_cells
from core.grid import grid_distance, move_candidates, to_grid, to_screen
from phases.base import Context
from phases.primary_spell import deselect_primary
from phases.turn_helpers import save_diag


def plan_move(ctx: Context, scene, enemies, me_pos: tuple[int, int]):
    """Monstre visé et cases candidates (les meilleures d'abord) pour se rapprocher."""
    target = sort_by_distance(enemies, me_pos)[0]
    h, w = scene.shape[:2]
    roi = _game_roi(h, w)
    # Toujours le nombre maximum de cases (jamais de déplacement plus court) ; plusieurs cases à ce nombre de pas,
    # sans reprendre une case déjà tentée sans succès pendant ce tour.
    cands = [(k, p) for k, p in move_candidates(me_pos, target.center, [e.center for e in enemies],
                                               ctx.config.max_move_cells, shorter=False, top=10)
             if 0 <= p[0] < w and 0 <= p[1] < h and roi[p[1], p[0]]
             and not any(grid_distance(p, f) < 0.5 for f in ctx.failed_moves)]
    return target, cands


def plan_move_green(ctx: Context, scene, enemies, me_pos: tuple[int, int]):
    """Monstre visé et cases où le jeu me laisse aller (cases vertes), les plus proches du monstre d'abord.
    Retourne (monstre, cases) ; cases est vide si aucune case verte fiable n'est visible (plus de PM, ou couleur
    non reconnue) : l'appelant se rabat alors sur le calcul géométrique."""
    target = sort_by_distance(enemies, me_pos)[0]
    cells = reachable_cells(scene, target.center)
    if len(cells) >= 2:                                        # ignore les taches vertes isolées : on garde la zone principale
        mid = sorted(cells)[len(cells) // 2]
        cells = [c for c in cells if grid_distance(c, mid) <= 8]
    if len(cells) < 2:
        return target, []
    busy = [e.center for e in enemies]
    cells = [c for c in cells
             if not any(grid_distance(c, b) < 0.5 for b in busy)
             and not any(grid_distance(c, f) < 0.5 for f in ctx.failed_moves)]
    cells.sort(key=lambda c: (round(grid_distance(c, target.center), 1), grid_distance(c, me_pos)))
    return target, cells


RANGE_MIN_PIXELS = 1500          # zone de portée assez grande pour être fiable
HINT_MISMATCH = 2.5              # écart (en cases) entre la dernière position connue et le centre de la portée
HINT_MISMATCH_UNVERIFIED = 2.2   # même chose quand la dernière position n'est qu'une supposition


def range_center(mask, enemies) -> tuple[int, int] | None:
    """Position approximative de mon personnage : centre de la zone violette du sort (qui l'entoure),
    recalé sur le centre d'une case (les adversaires servent de repère de grille)."""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or not enemies:
        return None
    c = (int(xs.mean()), int(ys.mean()))
    ref = enemies[0].center
    return to_screen(to_grid(c, ref), ref)


def my_position(ctx: Context, scene, me, mask, enemies):
    """Ma position : anneau rouge si visible, sinon dernière position connue, sinon centre de la portée."""
    if me:
        ctx.hint_unverified = False
        return me.center
    save_diag(ctx, scene, enemies, None, label="perso_introuvable")
    # La zone violette du sort entoure mon personnage : elle sert à recouper la dernière position connue, qui peut être
    # fausse (déplacement qui s'est arrêté avant la case visée, personnage poussé…). Sinon le programme reste bloqué.
    center = range_center(mask, enemies) if mask is not None and int((mask > 0).sum()) >= RANGE_MIN_PIXELS else None
    if ctx.me_hint:
        limit = HINT_MISMATCH_UNVERIFIED if ctx.hint_unverified else HINT_MISMATCH
        if center and grid_distance(center, ctx.me_hint) > limit:
            ctx.log(f"La dernière position connue {ctx.me_hint} ne correspond pas à la portée du sort : "
                    f"je situe mon personnage en {center}.")
            ctx.me_hint, ctx.hint_unverified = center, True
            return center
        ctx.log(f"Anneau rouge de mon personnage non vu : j'utilise sa dernière position connue {ctx.me_hint}.")
        return ctx.me_hint
    pos = center
    if pos:
        ctx.log(f"Anneau rouge de mon personnage non vu : je l'estime au centre de la portée du sort, en {pos}.")
    else:
        ctx.log("⚠ Position de mon personnage inconnue.")
    return pos


def wait_moved(ctx: Context, start: tuple[int, int], timeout: float = 4.0):
    """Attend la fin du déplacement. Retourne ('moved', position), ('same', None) si le personnage est
    toujours sur sa case, ou ('unknown', None) si l'anneau rouge n'est jamais visible."""
    t0, last, seen_same = time.time(), None, False
    while time.time() - t0 < timeout:
        time.sleep(0.4)
        s, _ = ctx.capture.grab()
        me = find_me(s)
        if not me:
            continue
        if grid_distance(me.center, start) < 0.75:
            seen_same, last = True, None
            continue
        if last and grid_distance(me.center, last) < 0.5:
            return "moved", me.center
        last = me.center
    if last:
        return "moved", last
    return ("same", None) if seen_same else ("unknown", None)


def move_closer(ctx: Context, enemies, me_pos: tuple[int, int], should_stop) -> bool:
    """Se rapproche du monstre le plus proche (double clic sur une case), au plus max_move_cells cases."""
    if not deselect_primary(ctx):
        return False
    scene, (ox, oy) = ctx.capture.grab()
    target, green = plan_move_green(ctx, scene, enemies, me_pos)
    if green:                                                  # le jeu indique lui-même les cases accessibles
        cands = [(round(grid_distance(c, me_pos)), c) for c in green]
        dist = grid_distance(target.center, me_pos)
        ctx.log(f"{len(green)} case(s) accessible(s) (vertes) : je vise la plus proche du monstre.")
    else:
        target, cands = plan_move(ctx, scene, enemies, me_pos)
        dist = grid_distance(target.center, me_pos)
    if not cands:
        if ctx.failed_moves:
            ctx.log(f"Toutes les cases possibles ont déjà été essayées sans succès ({len(ctx.failed_moves)}).")
        else:
            ctx.log(f"Monstre le plus proche à {dist:.0f} case(s) : déjà au contact ou aucune case possible.")
        return False
    for k, (x, y) in cands[:4]:
        if should_stop():
            return False
        ctx.log(f"Déplacement de {k} case(s) vers le monstre en {target.center} (à {dist:.0f} case(s)) : "
                f"double clic en ({x}, {y}).")
        save_diag(ctx, scene, enemies, None, target, label="deplacement")
        for i in range(2):
            inp.click(ox + x, oy + y)
            if i == 0:
                time.sleep(ctx.config.click_interval_ms / 1000)
        status, pos = wait_moved(ctx, me_pos)
        if status == "moved":
            ctx.me_hint, ctx.hint_unverified = pos, False
            ctx.log(f"✔ Personnage déplacé en {pos}.")
            return True
        if status == "unknown":
            ctx.me_hint, ctx.hint_unverified = (x, y), True   # on suppose le déplacement fait, sans le refaire
            ctx.log("Déplacement non vérifiable (anneau rouge non vu) : je considère qu'il est fait.")
            return True
        ctx.failed_moves.append((x, y))                # on ne retentera pas cette case pendant ce tour
        ctx.log("Le personnage n'a pas bougé (case inaccessible ?), j'essaie une autre case.")
    ctx.log("⚠ Déplacement impossible : je finis le tour.")
    return False


MAX_MOVE_ATTEMPTS = 3                   # essais de déplacement par tour (personnage caché, case inaccessible…)
