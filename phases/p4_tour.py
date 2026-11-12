"""Phases 4 et 5 : jouer mon tour (lancer le sort sur l'adversaire le plus proche à portée,
puis finir le tour) et recommencer à chaque tour."""
import time
from datetime import datetime

import cv2
import numpy as np

from core import input as inp
from core.combat import (Fighter, find_enemies, find_me, range_fraction, range_mask, range_visible, reachable_cells,
                         sort_by_distance, spell_border_pixels, spell_selected)
from core.combat import _game_roi
from core.grid import grid_distance, move_candidates, to_grid, to_screen
from core.imgio import save_image
from core.paths import logs_dir
from core.vision import scan
from phases.base import Context
from phases.p2_combat import find_ui, read_ui


def _find(ctx: Context, scene, name: str):
    return find_ui(ctx, scene, name)


def wait_my_turn(ctx: Context, should_stop) -> str:
    """Attend mon tour. Retourne 'turn', 'over' (fenêtre de résultat), 'timeout' ou 'stopped'."""
    t0 = time.time()
    while time.time() - t0 < ctx.config.turn_wait_s and not should_stop():
        scene, _ = ctx.capture.grab()
        r = read_ui(scene, ctx.ui_templates, ctx.config.ui_threshold)
        if "resultat_titre" in r.found:
            return "over"
        if r.turn_active:
            return "turn"
        time.sleep(0.4)
    return "stopped" if should_stop() else "timeout"


def _diag(ctx: Context, scene, enemies, me, target=None, label="tour"):
    if not ctx.config.save_diagnostics:
        return
    out = scene.copy()
    for f in enemies:
        cv2.circle(out, f.center, 8, (0, 255, 255), -1)
    if me:
        cv2.circle(out, me.center, 10, (0, 0, 255), -1)
    if target:
        cv2.circle(out, target.center, 22, (0, 255, 0), 3)
    save_image(logs_dir() / f"{label}_{datetime.now():%Y%m%d_%H%M%S_%f}.png", out)


def _wait_confirm(ctx: Context, timeout: float = 1.6):
    t0 = time.time()
    while time.time() - t0 < timeout:
        scene, origin = ctx.capture.grab()
        d = _find(ctx, scene, "valider")
        if d:
            return d, origin
        time.sleep(0.2)
    return None, None


def _is_selected(scene, icon, min_pixels: int = 3000) -> bool:
    """Sort sélectionné ? Cadre orange autour de son icône (sûr sur toutes les cartes) ou zone de portée bleue."""
    if icon is not None and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
        return True
    return range_visible(scene, min_pixels)


def _diag_select(ctx: Context, scene, icon) -> None:
    """Quand la sélection du sort ne peut pas être vérifiée : chiffres dans le journal + capture annotée."""
    n = spell_border_pixels(scene, icon.x, icon.y, icon.w, icon.h) if icon else -1
    m = int(range_mask(scene).sum())
    where = f"icône en ({icon.x}, {icon.y}), score {icon.score:.2f}" if icon else "icône introuvable"
    ctx.log(f"Diagnostic de sélection : cadre orange {n} px (150 attendus si le sort est sélectionné), "
            f"bleu de portée {m} px (3000 attendus), {where}.")
    if ctx.config.save_diagnostics:
        out = scene.copy()
        if icon:
            cv2.rectangle(out, (icon.x - 7, icon.y - 7), (icon.x + icon.w + 7, icon.y + icon.h + 7), (0, 255, 255), 2)
        save_image(logs_dir() / f"selection_sort_{datetime.now():%Y%m%d_%H%M%S}.png", out)


def _select_spell(ctx: Context, force: bool = False) -> bool:
    """force=True : on SAIT que le sort est désélectionné (après un déplacement) → on clique l'icône sans condition."""
    if force:
        ctx.select_unverified = False
    if ctx.select_unverified:
        return True                                   # supposé sélectionné : recliquer sur l'icône le désélectionnerait
    scene, (ox, oy) = ctx.capture.grab()
    icon = _find(ctx, scene, "sort_attaque")
    if not force and _is_selected(scene, icon):
        return True                                   # déjà sélectionné
    if not icon:
        ctx.log("⚠ Icône du sort introuvable.")
        return False
    inp.click(ox + icon.center[0], oy + icon.center[1])
    t0 = time.time()
    s = scene
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        s, _ = ctx.capture.grab()
        if _is_selected(s, _find(ctx, s, "sort_attaque") or icon):
            return True
    # Ni le cadre orange ni la zone de portée ne sont vus. Plutôt que de passer le tour, on tente quand même :
    # la fenêtre de confirmation (coche verte) n'apparaît que si le sort est vraiment sélectionné et la cible valide.
    _diag_select(ctx, s, icon)
    ctx.select_unverified = True
    ctx.log("Sélection du sort non vérifiée : j'essaie quand même, la fenêtre de confirmation dira si ça marche.")
    return True


def _deselect_spell(ctx: Context) -> bool:
    """Le jeu refuse de déplacer le personnage tant que le sort est sélectionné : on reclique dessus."""
    scene, (ox, oy) = ctx.capture.grab()
    icon = _find(ctx, scene, "sort_attaque")
    if ctx.select_unverified:                          # sélection supposée mais jamais vue : un clic la défait
        ctx.select_unverified = False
        if icon:
            inp.click(ox + icon.center[0], oy + icon.center[1])
            time.sleep(0.6)
        return True
    if not _is_selected(scene, icon):
        return True
    if not icon:
        ctx.log("⚠ Icône du sort introuvable : impossible de désélectionner le sort.")
        return False
    inp.click(ox + icon.center[0], oy + icon.center[1])
    t0 = time.time()
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        s, _ = ctx.capture.grab()
        if not _is_selected(s, _find(ctx, s, "sort_attaque") or icon):
            return True
    ctx.log("⚠ Le sort reste sélectionné : pas de déplacement.")
    return False


def _reselect_after_move(ctx: Context) -> bool:
    """Après un déplacement, le sort est forcément désélectionné : on reclique sur Coagulation."""
    time.sleep(0.8)                                   # laisse le personnage s'arrêter et l'écran se stabiliser
    ctx.log("Je resélectionne Coagulation après le déplacement.")
    return _select_spell(ctx, force=True)


def _release_spells(ctx: Context) -> None:
    """Avant de finir le tour : désélectionne tout sort resté sélectionné (Pied du Sacrieur, puis Coagulation)."""
    scene, (ox, oy) = ctx.capture.grab()
    if _find(ctx, scene, "resultat_titre"):
        return
    icon2 = _find(ctx, scene, SECOND_SPELL)
    if icon2 and spell_selected(scene, icon2.x, icon2.y, icon2.w, icon2.h):
        ctx.log(f"Je désélectionne le {SECOND_SPELL_LABEL} avant de finir le tour.")
        inp.click(ox + icon2.center[0], oy + icon2.center[1])
        time.sleep(0.5)
    scene, _ = ctx.capture.grab()
    icon = _find(ctx, scene, "sort_attaque")
    if icon and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):   # cadre orange vu = sort vraiment sélectionné
        ctx.log("Je désélectionne Coagulation avant de finir le tour.")
        _deselect_spell(ctx)


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


RANGE_APPEAR_WAIT_S = 1.5            # attente maximale de l'affichage de la portée avant de la déclarer illisible
RANGE_MIN_PIXELS = 1500          # zone de portée assez grande pour être fiable
HINT_MISMATCH = 2.5              # écart (en cases) entre la dernière position connue et le centre de la portée
HINT_MISMATCH_UNVERIFIED = 2.2   # même chose quand la dernière position n'est qu'une supposition


def _range_center(mask, enemies) -> tuple[int, int] | None:
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
    _diag(ctx, scene, enemies, None, label="perso_introuvable")
    # La zone violette du sort entoure mon personnage : elle sert à recouper la dernière position connue, qui peut être
    # fausse (déplacement qui s'est arrêté avant la case visée, personnage poussé…). Sinon le programme reste bloqué.
    center = _range_center(mask, enemies) if mask is not None and int((mask > 0).sum()) >= RANGE_MIN_PIXELS else None
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


def _wait_moved(ctx: Context, start: tuple[int, int], timeout: float = 4.0):
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
    if not _deselect_spell(ctx):
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
        _diag(ctx, scene, enemies, None, target, label="deplacement")
        for i in range(2):
            inp.click(ox + x, oy + y)
            if i == 0:
                time.sleep(ctx.config.click_interval_ms / 1000)
        status, pos = _wait_moved(ctx, me_pos)
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


def play_turn(ctx: Context, should_stop, turn: int = 0) -> int:
    """Joue un tour (turn = numéro du tour dans le combat, 1 = premier). Retourne le nombre de lancers réussis."""
    cfg = ctx.config
    ctx.log("Mon tour.")
    ctx.select_unverified = False
    ctx.failed_moves = []                              # cases de déplacement ratées : repart de zéro à chaque tour
    time.sleep(cfg.turn_start_delay_s)
    opening_done = False
    if turn == 1 and cfg.opening_spell and not should_stop():       # sort d'ouverture : premier tour uniquement
        opening_done = cast_opening_spell(ctx)
    casts = 0
    moved = False                                      # un seul déplacement réussi par tour
    move_failures = 0                                  # déplacements ratés : on réessaie avant de renoncer
    while casts < cfg.casts_per_turn and not should_stop():
        scene0, _ = ctx.capture.grab()
        if _find(ctx, scene0, "resultat_titre"):
            ctx.log("Le combat est terminé.")
            break
        if not _select_spell(ctx):
            break
        scene, (ox, oy) = ctx.capture.grab()
        enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
        if me:
            ctx.me_hint = me.center
        if not enemies and ctx.last_enemies and cfg.move_when_out_of_range and not moved:
            # Adversaire introuvable (caché derrière un décor) : plutôt que de passer le tour sans bouger,
            # on se rapproche de l'endroit où on l'a vu la dernière fois.
            ghosts = [Fighter(x, y, 0) for x, y in ctx.last_enemies]
            pos = my_position(ctx, scene, me, range_mask(scene), ghosts)
            ctx.log(f"Aucun adversaire visible : je me rapproche de la dernière position connue {ctx.last_enemies[0]}.")
            if pos and move_closer(ctx, ghosts, pos, should_stop):
                moved = True
                if _reselect_after_move(ctx):
                    continue                               # on regarde à nouveau depuis la nouvelle position
        if not enemies:
            ctx.log("Aucun adversaire visible.")
            if casts == 0:                                 # compte les tours entiers sans adversaire repéré
                ctx.no_enemy_streak += 1
                if ctx.no_enemy_streak == 3:               # le combat ne se termine pas : une capture montre où il se cache
                    try:
                        path = logs_dir() / f"aucun_adversaire_{datetime.now():%Y%m%d_%H%M%S}.png"
                        save_image(path, scene)
                        ctx.log(f"⚠ Aucun adversaire visible depuis 3 tours alors que le combat continue. "
                                f"Capture de l'écran enregistrée : {path}")
                    except Exception:
                        pass
            break
        ctx.no_enemy_streak = 0
        ctx.last_enemies = [e.center for e in enemies]
        mask = range_mask(scene)
        range_known = int(mask.sum()) >= 800
        if me:
            origin = me.center
        elif range_known:
            ys, xs = np.where(mask > 0)
            origin = (int(xs.mean()), int(ys.mean()))
        else:                                              # portée illisible : le centre des quelques pixels bleus ne vaut rien
            origin = ctx.me_hint or enemies[0].center
        if me:                                             # jamais mon propre personnage pris pour un adversaire
            own = [e for e in enemies if grid_distance(e.center, me.center) < 0.8]
            if own:
                ctx.log(f"J'ignore {len(own)} « adversaire(s) » situé(s) sur mon propre personnage.")
                enemies = [e for e in enemies if e not in own]
                if not enemies:
                    break
        if not range_known and casts == 0:
            # La zone de portée peut s'afficher avec retard (surtout juste après le sort d'ouverture, au 1er tour) :
            # avant de conclure qu'elle est illisible — et de cliquer des adversaires peut-être hors de portée —
            # on laisse l'écran se mettre à jour et on relit.
            t_wait = time.time()
            while time.time() - t_wait < RANGE_APPEAR_WAIT_S and not should_stop():
                time.sleep(0.3)
                scene, (ox, oy) = ctx.capture.grab()
                mask = range_mask(scene)
                if int(mask.sum()) >= 800:
                    range_known = True
                    ctx.log("La portée du sort s'est affichée avec un léger retard : je la lis maintenant.")
                    enemies = find_enemies(scene) or enemies
                    me = find_me(scene, ctx.me_hint) or me
                    origin = me.center if me else origin
                    if me:
                        enemies = [e for e in enemies if grid_distance(e.center, me.center) >= 0.8] or enemies
                    break
        if range_known:
            in_range = [f for f in sort_by_distance(enemies, origin)
                        if range_fraction(mask, f.center) >= cfg.range_min_fraction]
            ctx.log(f"{len(enemies)} adversaire(s), {len(in_range)} à portée.")
        else:
            limit = cfg.blind_range_max_cells
            in_range = [f for f in sort_by_distance(enemies, origin) if grid_distance(f.center, origin) <= limit]
            ctx.log(f"{len(enemies)} adversaire(s). Portée du sort illisible à l'écran : j'essaie seulement ceux à "
                    f"{limit} case(s) ou moins ({len(in_range)}), du plus proche au plus loin "
                    "(la fenêtre de confirmation vérifie).")
        if not in_range:
            if cfg.move_when_out_of_range and not moved:
                pos = my_position(ctx, scene, me, mask, enemies)
                if pos:
                    ctx.log("Aucun adversaire à portée : je me rapproche.")
                if pos and move_closer(ctx, enemies, pos, should_stop):
                    moved = True
                    if _reselect_after_move(ctx):
                        continue                       # on retente le sort depuis la nouvelle position
                elif not should_stop():
                    move_failures += 1
                    if move_failures < MAX_MOVE_ATTEMPTS:
                        ctx.log(f"Déplacement raté (essai {move_failures}/{MAX_MOVE_ATTEMPTS}) : je réessaie.")
                        time.sleep(0.8)
                        continue                       # nouvelle observation, nouvelle estimation de ma position
                    ctx.log("⚠ Déplacement impossible après plusieurs essais : je passe le tour.")
            else:
                ctx.log("Aucun adversaire à portée : je passe le tour.")
            break
        done = False
        for target in in_range[:3]:
            dist = grid_distance(target.center, origin)
            ctx.log(f"Cible à {dist:.1f} case(s) en {target.center}.")
            _diag(ctx, scene, enemies, me, target)
            inp.click(ox + target.cx, oy + target.cy - 4)
            ok, origin2 = _wait_confirm(ctx)
            if ok:
                ox2, oy2 = origin2
                inp.click(ox2 + ok.center[0], oy2 + ok.center[1])
                casts += 1
                ctx.log(f"✔ Lancer {casts}/{cfg.casts_per_turn} confirmé.")
                time.sleep(1.5)                       # animation + dégâts
                if casts < cfg.casts_per_turn and cfg.pause_between_casts_ms > 0:
                    ctx.log(f"Pause de {cfg.pause_between_casts_ms} ms avant le lancer suivant.")
                    time.sleep(cfg.pause_between_casts_ms / 1000)
                done = True
                break
            ctx.log("Pas de confirmation sur cette cible.")
            if not _select_spell(ctx):
                break
            scene, (ox, oy) = ctx.capture.grab()
        if not done:
            if not range_known and cfg.move_when_out_of_range and not moved:
                pos = my_position(ctx, scene, me, mask, enemies)
                if pos:
                    ctx.log("Aucune cible n'a répondu : je me rapproche.")
                if pos and move_closer(ctx, enemies, pos, should_stop):
                    moved = True
                    if _reselect_after_move(ctx):
                        continue                       # on retente le sort depuis la nouvelle position
                elif not should_stop():
                    move_failures += 1
                    if move_failures < MAX_MOVE_ATTEMPTS:
                        ctx.log(f"Déplacement raté (essai {move_failures}/{MAX_MOVE_ATTEMPTS}) : je réessaie.")
                        time.sleep(0.8)
                        continue
                    ctx.log("⚠ Déplacement impossible après plusieurs essais : je passe le tour.")
            break
    if (cfg.second_spell and not opening_done and casts >= cfg.casts_per_turn and not should_stop()
            and not _find(ctx, ctx.capture.grab()[0], "resultat_titre")):
        if cfg.pause_between_casts_ms > 0:
            ctx.log(f"Pause de {cfg.pause_between_casts_ms} ms avant le Pied du Sacrieur.")
            time.sleep(cfg.pause_between_casts_ms / 1000)
        cast_ok, moved_for_foot = cast_second_spell(ctx, should_stop)
        if cast_ok:
            casts += 1
        if moved_for_foot:
            moved = True
    if not should_stop():
        _release_spells(ctx)                          # aucun sort ne doit rester sélectionné au moment de finir le tour
    ctx.progress += casts + int(moved) + int(opening_done)
    return casts


# --- 2e sort : Pied du Sacrieur (3 PA, au contact) ------------------------------------------------
SECOND_SPELL = "pied_du_sacrieur"       # nom de l'image dans assets/ui
SECOND_SPELL_LABEL = "Pied du Sacrieur"
SMALL_RANGE_PIXELS = 800                # portée de 4 cases seulement : peu de violet à l'écran


def _select_second_spell(ctx: Context):
    """Clique l'icône du Pied du Sacrieur et attend qu'il soit sélectionné. Retourne (sélectionné, icône)."""
    scene, (ox, oy) = ctx.capture.grab()
    icon = _find(ctx, scene, SECOND_SPELL)
    if not icon:
        ctx.log(f"⚠ Icône du {SECOND_SPELL_LABEL} introuvable ({SECOND_SPELL}.png dans assets/ui).")
        return False, None
    inp.click(ox + icon.center[0], oy + icon.center[1])
    t0 = time.time()
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        if _is_selected(ctx.capture.grab()[0], icon, SMALL_RANGE_PIXELS):
            return True, icon
    ctx.log(f"Le {SECOND_SPELL_LABEL} ne s'affiche pas (plus assez de PA ?).")
    return False, icon


def _deselect_second_spell(ctx: Context, icon) -> bool:
    """Reclique l'icône du Pied du Sacrieur pour le désélectionner (le jeu refuse de déplacer tant qu'il l'est)."""
    scene, (ox, oy) = ctx.capture.grab()
    ic = _find(ctx, scene, SECOND_SPELL) or icon
    inp.click(ox + ic.center[0], oy + ic.center[1])
    t0 = time.time()
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        s, _ = ctx.capture.grab()
        if not _is_selected(s, _find(ctx, s, SECOND_SPELL) or ic, SMALL_RANGE_PIXELS):
            return True
    ctx.log(f"⚠ Le {SECOND_SPELL_LABEL} reste sélectionné.")
    return False


def cast_second_spell(ctx: Context, should_stop=lambda: False) -> tuple[bool, bool]:
    """Sélectionne le Pied du Sacrieur, le lance sur l'adversaire à portée le plus proche et confirme.
    Si personne n'est à portée mais qu'il reste des PM (cases vertes de déplacement visibles), le personnage se
    rapproche de l'adversaire le plus proche puis relance le Pied du Sacrieur, au lieu de passer.
    Retourne (lancé, déplacé)."""
    cfg = ctx.config
    moved = False
    for attempt in (1, 2):                              # 2e passage = après un déplacement
        selected, icon = _select_second_spell(ctx)
        if not selected:
            return False, moved
        scene, (ox, oy) = ctx.capture.grab()
        enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
        mask = range_mask(scene)
        origin = me.center if me else (ctx.me_hint or (enemies[0].center if enemies else None))
        in_range = [f for f in (sort_by_distance(enemies, origin) if origin else enemies)
                    if range_fraction(mask, f.center) >= cfg.range_min_fraction]
        ctx.log(f"{SECOND_SPELL_LABEL} : {len(enemies)} adversaire(s), {len(in_range)} à portée.")
        if in_range:
            for target in in_range[:3]:
                _diag(ctx, scene, enemies, me, target, label="pied")
                inp.click(ox + target.cx, oy + target.cy - 4)
                ok, origin2 = _wait_confirm(ctx)
                if ok:
                    inp.click(origin2[0] + ok.center[0], origin2[1] + ok.center[1])
                    ctx.log(f"✔ {SECOND_SPELL_LABEL} lancé en {target.center}.")
                    time.sleep(1.5)
                    return True, moved
                ctx.log("Pas de confirmation sur cette cible.")
                scene, (ox, oy) = ctx.capture.grab()
                if not _is_selected(scene, _find(ctx, scene, SECOND_SPELL) or icon, SMALL_RANGE_PIXELS):
                    break
            return False, moved
        # Personne au contact : on désélectionne le sort, puis on regarde s'il reste des PM pour se rapprocher.
        ctx.log(f"Personne au contact : pas de {SECOND_SPELL_LABEL} pour l'instant.")
        deselected = _deselect_second_spell(ctx, icon)
        if attempt == 2 or not deselected or not enemies or not cfg.move_when_out_of_range or should_stop():
            return False, moved
        time.sleep(0.4)
        scene, _ = ctx.capture.grab()
        me = find_me(scene, ctx.me_hint) or me
        if me:
            ctx.me_hint = me.center
        pos = my_position(ctx, scene, me, range_mask(scene), enemies)
        if not pos:
            return False, moved
        _, green = plan_move_green(ctx, scene, enemies, pos)
        if not green:
            ctx.log("Plus de PM (aucune case verte de déplacement) : je ne bouge pas.")
            return False, moved
        ctx.log(f"Il me reste des PM ({len(green)} cases vertes) : je me rapproche pour lancer le {SECOND_SPELL_LABEL}.")
        ctx.select_unverified = False                   # Coagulation n'est plus sélectionnée à ce stade
        if not move_closer(ctx, enemies, pos, should_stop):
            return False, moved
        moved = True
        time.sleep(0.8)                                 # laisse le personnage s'arrêter avant de resélectionner le sort
    return False, moved


# --- Sort d'ouverture (1er tour) : se lance sur mon propre personnage ----------------------------
OPENING_SPELL = "sort_debut_combat"     # nom de l'image dans assets/ui (icône dorée, couronne d'épines)
OPENING_SPELL_LABEL = "sort d'ouverture"


def _settle_after_opening(ctx: Context) -> None:
    """Après le sort d'ouverture : laisse l'écran se stabiliser et désélectionne ce sort s'il est resté sélectionné,
    sinon le clic suivant sur Coagulation peut être ignoré ou mal interprété (problème vu au 1er tour seulement)."""
    time.sleep(0.8)
    scene, (ox, oy) = ctx.capture.grab()
    icon = _find(ctx, scene, OPENING_SPELL)
    if icon and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
        ctx.log(f"Le {OPENING_SPELL_LABEL} est resté sélectionné : je le désélectionne avant Coagulation.")
        inp.click(ox + icon.center[0], oy + icon.center[1])
        time.sleep(0.6)


def cast_opening_spell(ctx: Context) -> bool:
    """Sélectionne le sort d'ouverture, clique sur mon propre personnage, puis confirme (coche verte)."""
    unverified = False                                  # sélection jamais vue : on ne reclique pas sur l'icône
    for attempt in range(1, 3):
        scene, (ox, oy) = ctx.capture.grab()
        icon = _find(ctx, scene, OPENING_SPELL)
        if not icon:
            ctx.log(f"⚠ Icône du {OPENING_SPELL_LABEL} introuvable ({OPENING_SPELL}.png dans assets/ui).")
            return False
        if not unverified and not spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
            inp.click(ox + icon.center[0], oy + icon.center[1])
            seen, t0 = False, time.time()
            while time.time() - t0 < 1.8:
                time.sleep(0.3)
                s, _ = ctx.capture.grab()
                ic = _find(ctx, s, OPENING_SPELL) or icon
                if spell_selected(s, ic.x, ic.y, ic.w, ic.h):
                    seen = True
                    break
            if not seen:
                ctx.log(f"Sélection du {OPENING_SPELL_LABEL} non vérifiée : j'essaie quand même, "
                        "la fenêtre de confirmation dira si ça marche.")
                unverified = True
        scene, (ox, oy) = ctx.capture.grab()
        enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
        if me and ctx.me_hint and grid_distance(me.center, ctx.me_hint) > 2.0:
            # Au 1er tour on sait exactement où l'on est (la case du placement) : un anneau rouge repéré loin de là
            # (autre élément rouge de l'écran) n'est pas mon personnage, et on ne lui lance pas le sort.
            ctx.log(f"Anneau rouge repéré en {me.center}, loin de ma case de départ {ctx.me_hint} : je garde ma case de départ.")
            me = None
        if me:
            ctx.me_hint = me.center
        pos = my_position(ctx, scene, me, range_mask(scene), enemies)
        if not pos:
            ctx.log(f"⚠ Position de mon personnage inconnue : pas de {OPENING_SPELL_LABEL}.")
            break
        ctx.log(f"{OPENING_SPELL_LABEL.capitalize()} : clic sur mon personnage en {pos}.")
        inp.click(ox + pos[0], oy + pos[1])
        ok, origin2 = _wait_confirm(ctx)
        if ok:
            inp.click(origin2[0] + ok.center[0], origin2[1] + ok.center[1])
            ctx.log(f"✔ {OPENING_SPELL_LABEL.capitalize()} lancé.")
            time.sleep(1.5)                             # animation
            _settle_after_opening(ctx)
            return True
        ctx.log(f"Pas de confirmation pour le {OPENING_SPELL_LABEL} (essai {attempt}/2).")
    scene, (ox, oy) = ctx.capture.grab()                # échec : on ne laisse pas le sort sélectionné
    icon = _find(ctx, scene, OPENING_SPELL)
    if icon and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
        inp.click(ox + icon.center[0], oy + icon.center[1])
        time.sleep(0.5)
    return False


def end_turn(ctx: Context) -> bool:
    scene, (ox, oy) = ctx.capture.grab()
    r = read_ui(scene, ctx.ui_templates, ctx.config.ui_threshold)
    fin = r.found.get("fin_du_tour")
    if "resultat_titre" in r.found:
        ctx.log("Le combat est terminé.")
        return False
    if not fin or not r.turn_active:
        ctx.log("⚠ Bouton « Fin du tour » vert introuvable.")
        return False
    inp.click(ox + fin.center[0], oy + fin.center[1])
    t0 = time.time()
    while time.time() - t0 < 6:
        time.sleep(0.4)
        s, _ = ctx.capture.grab()
        if not read_ui(s, ctx.ui_templates, ctx.config.ui_threshold).turn_active:
            ctx.log("Tour terminé.")
            return True
    ctx.log("⚠ Le tour ne semble pas terminé.")
    return False


STALL_TURNS = 4                  # tours de suite sans aucune action réussie avant de remettre la position à zéro


def run_turns(ctx: Context, should_stop) -> str:
    """Boucle des tours. Retourne 'over' (combat terminé), 'timeout' ou 'stopped'."""
    ctx.log("Phases 4-5 : je joue les tours (F12 pour arrêter).")
    n = idle = 0
    while not should_stop():
        status = wait_my_turn(ctx, should_stop)
        if status == "over":
            ctx.log("Le combat est terminé (fenêtre de résultat).")
            return "over"
        if status == "timeout":
            ctx.log(f"Aucun tour à jouer pendant {ctx.config.turn_wait_s} s : le programme s'arrête.")
            return "timeout"
        if status == "stopped":
            break
        n += 1
        ctx.log(f"── Tour {n} ──")
        before = ctx.progress
        play_turn(ctx, should_stop, turn=n)
        idle = 0 if ctx.progress > before else idle + 1
        if idle == STALL_TURNS and not should_stop():
            ctx.log(f"⚠ Aucun lancer ni déplacement réussi depuis {idle} tours : j'oublie la dernière position connue "
                    "et je la recalcule.")
            ctx.me_hint, ctx.hint_unverified = None, False
        if should_stop():
            break
        end_turn(ctx)
    return "stopped"


def test_combat(ctx: Context) -> np.ndarray:
    """Diagnostic sans clic : adversaires, mon personnage, portée."""
    scene, _ = ctx.capture.grab()
    enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
    if me:
        ctx.me_hint = me.center
    mask = range_mask(scene)
    visible = (_is_selected(scene, _find(ctx, scene, "sort_attaque"), SMALL_RANGE_PIXELS)
               or _is_selected(scene, _find(ctx, scene, SECOND_SPELL), SMALL_RANGE_PIXELS))
    ctx.log(f"Mon personnage : {me.center if me else 'introuvable'} · {len(enemies)} adversaire(s) · "
            f"portée du sort {'affichée' if visible else 'non affichée (sélectionne d’abord le sort)'}")
    origin = me.center if me else None
    for f in (sort_by_distance(enemies, origin) if origin else enemies):
        frac = range_fraction(mask, f.center)
        dist = f"{grid_distance(f.center, origin):.1f} case(s)" if origin else "?"
        ctx.log(f"  adversaire {f.center} : {dist}" + (f" · {'À PORTÉE' if frac >= ctx.config.range_min_fraction else 'hors portée'}"
                                                        if visible else ""))
    out = scene.copy()
    move_to = None
    if me and enemies and visible and ctx.config.move_when_out_of_range and not any(
            range_fraction(mask, f.center) >= ctx.config.range_min_fraction for f in enemies):
        target, cands = plan_move(ctx, scene, enemies, me.center)
        if cands:
            move_to = cands[0]
            ctx.log(f"Personne à portée : je me déplacerais de {move_to[0]} case(s) en {move_to[1]} "
                    f"vers le monstre en {target.center}.")
        else:
            ctx.log("Personne à portée et aucune case de déplacement possible.")
    out[mask > 0] = (0.55 * out[mask > 0] + 0.45 * np.array([0, 255, 0])).astype(np.uint8)
    for f in enemies:
        cv2.circle(out, f.center, 9, (0, 255, 255), -1)
    if me:
        cv2.circle(out, me.center, 11, (0, 0, 255), -1)
    if move_to:
        cv2.drawMarker(out, move_to[1], (255, 0, 255), cv2.MARKER_TILTED_CROSS, 26, 3)
    return out
