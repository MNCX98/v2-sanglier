"""Phases 4 et 5 : jouer mon tour (sort d'ouverture, sort principal sur l'adversaire le plus proche à portée,
sorts secondaires, déplacements), puis finir le tour et recommencer à chaque tour.

Le détail est réparti dans :  turn_helpers (outils communs), primary_spell (sort principal), movement (déplacements),
casting (sort d'ouverture, sorts secondaires, fin de tour). Les sorts joués viennent du profil choisi (core/spells.py).
"""
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from core import input as inp
from core.combat import Fighter, find_enemies, find_me, range_fraction, range_mask, sort_by_distance
from core.grid import grid_distance
from core.imgio import save_image
from core.paths import logs_dir
from phases.base import Context
from phases.casting import cast_opening, cast_secondary, opening_available, release_spells
from phases.movement import MAX_MOVE_ATTEMPTS, move_closer, my_position, plan_move, plan_move_green   # noqa: F401 (réexportés)
from phases.p2_combat import read_ui
from phases.primary_spell import reselect_primary, select_primary
from phases.turn_helpers import book, find_icon, is_selected, save_diag, wait_confirm
from core.spells import SMALL_RANGE_PIXELS

RANGE_APPEAR_WAIT_S = 1.5            # attente maximale de l'affichage de la portée avant de la déclarer illisible
KNOWN_RANGE_PIXELS = 800             # en dessous, la zone de portée est jugée illisible
OWN_CELL_DISTANCE = 0.8              # un « adversaire » plus près que cela de mon personnage est mon personnage lui-même


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


# --- état d'un tour ---------------------------------------------------------------------------------

@dataclass
class TurnState:
    casts: int = 0                 # lancers réussis du sort principal (puis des secondaires)
    moved: bool = False            # un seul déplacement réussi par tour pour le sort principal
    move_failures: int = 0         # déplacements ratés : on réessaie avant de renoncer
    opening_done: bool = False     # sort d'ouverture lancé ce tour


# --- étapes du sort principal -----------------------------------------------------------------------

def _chase_last_known(ctx: Context, st: TurnState, scene, me, should_stop) -> bool:
    """Adversaire introuvable (caché derrière un décor) : plutôt que de passer le tour sans bouger, on se rapproche
    de l'endroit où on l'a vu la dernière fois. True = on a bougé et resélectionné le sort : on regarde à nouveau."""
    ghosts = [Fighter(x, y, 0) for x, y in ctx.last_enemies]
    pos = my_position(ctx, scene, me, range_mask(scene), ghosts)
    ctx.log(f"Aucun adversaire visible : je me rapproche de la dernière position connue {ctx.last_enemies[0]}.")
    if pos and move_closer(ctx, ghosts, pos, should_stop):
        st.moved = True
        if reselect_primary(ctx):
            return True
    return False


def _note_no_enemy(ctx: Context, st: TurnState, scene) -> None:
    ctx.log("Aucun adversaire visible.")
    if st.casts == 0:                                  # compte les tours entiers sans adversaire repéré
        ctx.no_enemy_streak += 1
        if ctx.no_enemy_streak == 3:                   # le combat ne se termine pas : une capture montre où il se cache
            try:
                path = logs_dir() / f"aucun_adversaire_{datetime.now():%Y%m%d_%H%M%S}.png"
                save_image(path, scene)
                ctx.log(f"⚠ Aucun adversaire visible depuis 3 tours alors que le combat continue. "
                        f"Capture de l'écran enregistrée : {path}")
            except Exception:
                pass


def _origin(ctx: Context, me, mask, range_known: bool, enemies):
    """Point de départ des distances : mon personnage, sinon le centre de la portée, sinon ma dernière position."""
    if me:
        return me.center
    if range_known:
        ys, xs = np.where(mask > 0)
        return (int(xs.mean()), int(ys.mean()))
    return ctx.me_hint or enemies[0].center            # portée illisible : le centre des quelques pixels bleus ne vaut rien


def _wait_range_display(ctx: Context, st: TurnState, should_stop, scene, ox, oy, mask, enemies, me, origin):
    """La zone de portée peut s'afficher avec retard (surtout juste après le sort d'ouverture, au 1er tour) :
    avant de conclure qu'elle est illisible — et de cliquer des adversaires peut-être hors de portée —
    on laisse l'écran se mettre à jour et on relit. Retourne (scene, ox, oy, mask, enemies, me, origin, range_known)."""
    t_wait = time.time()
    while time.time() - t_wait < RANGE_APPEAR_WAIT_S and not should_stop():
        time.sleep(0.3)
        scene, (ox, oy) = ctx.capture.grab()
        mask = range_mask(scene)
        if int(mask.sum()) >= KNOWN_RANGE_PIXELS:
            ctx.log("La portée du sort s'est affichée avec un léger retard : je la lis maintenant.")
            enemies = find_enemies(scene) or enemies
            me = find_me(scene, ctx.me_hint) or me
            origin = me.center if me else origin
            if me:
                enemies = [e for e in enemies if grid_distance(e.center, me.center) >= OWN_CELL_DISTANCE] or enemies
            return scene, ox, oy, mask, enemies, me, origin, True
    return scene, ox, oy, mask, enemies, me, origin, False


def _targets_in_range(ctx: Context, enemies, origin, mask, range_known: bool) -> list:
    """Adversaires à essayer, du plus proche au plus loin."""
    cfg = ctx.config
    if range_known:
        in_range = [f for f in sort_by_distance(enemies, origin) if range_fraction(mask, f.center) >= cfg.range_min_fraction]
        ctx.log(f"{len(enemies)} adversaire(s), {len(in_range)} à portée.")
        return in_range
    limit = cfg.blind_range_max_cells
    in_range = [f for f in sort_by_distance(enemies, origin) if grid_distance(f.center, origin) <= limit]
    ctx.log(f"{len(enemies)} adversaire(s). Portée du sort illisible à l'écran : j'essaie seulement ceux à "
            f"{limit} case(s) ou moins ({len(in_range)}), du plus proche au plus loin "
            "(la fenêtre de confirmation vérifie).")
    return in_range


def _try_move_closer(ctx: Context, st: TurnState, scene, me, mask, enemies, should_stop, why: str) -> bool:
    """Se rapproche du monstre le plus proche. True = on réessaie le sort (déplacement fait ou à refaire),
    False = on abandonne ce tour."""
    pos = my_position(ctx, scene, me, mask, enemies)
    if pos:
        ctx.log(why)
    if pos and move_closer(ctx, enemies, pos, should_stop):
        st.moved = True
        return reselect_primary(ctx)                   # on retente le sort depuis la nouvelle position
    if not should_stop():
        st.move_failures += 1
        if st.move_failures < MAX_MOVE_ATTEMPTS:
            ctx.log(f"Déplacement raté (essai {st.move_failures}/{MAX_MOVE_ATTEMPTS}) : je réessaie.")
            time.sleep(0.8)
            return True                                # nouvelle observation, nouvelle estimation de ma position
        ctx.log("⚠ Déplacement impossible après plusieurs essais : je passe le tour.")
    return False


def _cast_on_targets(ctx: Context, st: TurnState, scene, ox, oy, enemies, me, origin, in_range):
    """Clique les adversaires à portée (3 au plus) jusqu'à ce que la fenêtre de confirmation valide un lancer.
    Retourne (lancé, scene) ; scene peut avoir été relue entre deux essais."""
    cfg = ctx.config
    for target in in_range[:3]:
        dist = grid_distance(target.center, origin)
        ctx.log(f"Cible à {dist:.1f} case(s) en {target.center}.")
        save_diag(ctx, scene, enemies, me, target)
        inp.click(ox + target.cx, oy + target.cy - 4)
        ok, origin2 = wait_confirm(ctx)
        if ok:
            ox2, oy2 = origin2
            inp.click(ox2 + ok.center[0], oy2 + ok.center[1])
            st.casts += 1
            ctx.log(f"✔ Lancer {st.casts}/{cfg.casts_per_turn} confirmé.")
            time.sleep(1.5)                            # animation + dégâts
            if st.casts < cfg.casts_per_turn and cfg.pause_between_casts_ms > 0:
                ctx.log(f"Pause de {cfg.pause_between_casts_ms} ms avant le lancer suivant.")
                time.sleep(cfg.pause_between_casts_ms / 1000)
            return True, scene
        ctx.log("Pas de confirmation sur cette cible.")
        if not select_primary(ctx):
            break
        scene, (ox, oy) = ctx.capture.grab()
    return False, scene


def _primary_step(ctx: Context, st: TurnState, should_stop) -> bool:
    """Une tentative de lancer le sort principal. True = on continue la boucle du tour, False = on s'arrête là."""
    cfg = ctx.config
    scene0, _ = ctx.capture.grab()
    if find_icon(ctx, scene0, "resultat_titre"):
        ctx.log("Le combat est terminé.")
        return False
    if not select_primary(ctx):
        return False
    scene, (ox, oy) = ctx.capture.grab()
    enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
    if me:
        ctx.me_hint = me.center
    if not enemies and ctx.last_enemies and cfg.move_when_out_of_range and not st.moved:
        if _chase_last_known(ctx, st, scene, me, should_stop):
            return True                                # on regarde à nouveau depuis la nouvelle position
    if not enemies:
        _note_no_enemy(ctx, st, scene)
        return False
    ctx.no_enemy_streak = 0
    ctx.last_enemies = [e.center for e in enemies]
    mask = range_mask(scene)
    range_known = int(mask.sum()) >= KNOWN_RANGE_PIXELS
    origin = _origin(ctx, me, mask, range_known, enemies)
    if me:                                             # jamais mon propre personnage pris pour un adversaire
        own = [e for e in enemies if grid_distance(e.center, me.center) < OWN_CELL_DISTANCE]
        if own:
            ctx.log(f"J'ignore {len(own)} « adversaire(s) » situé(s) sur mon propre personnage.")
            enemies = [e for e in enemies if e not in own]
            if not enemies:
                return False
    if not range_known and st.casts == 0:
        scene, ox, oy, mask, enemies, me, origin, range_known = _wait_range_display(
            ctx, st, should_stop, scene, ox, oy, mask, enemies, me, origin)
    in_range = _targets_in_range(ctx, enemies, origin, mask, range_known)
    if not in_range:
        if cfg.move_when_out_of_range and not st.moved:
            return _try_move_closer(ctx, st, scene, me, mask, enemies, should_stop,
                                    "Aucun adversaire à portée : je me rapproche.")
        ctx.log("Aucun adversaire à portée : je passe le tour.")
        return False
    done, scene = _cast_on_targets(ctx, st, scene, ox, oy, enemies, me, origin, in_range)
    if done:
        return True
    if not range_known and cfg.move_when_out_of_range and not st.moved:
        return _try_move_closer(ctx, st, scene, me, mask, enemies, should_stop,
                                "Aucune cible n'a répondu : je me rapproche.")
    return False


def _secondary_spells(ctx: Context, st: TurnState, should_stop) -> None:
    """Après les lancers du sort principal : sorts secondaires (sauf si le sort d'ouverture a été lancé ce tour)."""
    cfg = ctx.config
    for spell in book(ctx).secondary:
        if not (cfg.second_spell and not st.opening_done and st.casts >= cfg.casts_per_turn and not should_stop()
                and not find_icon(ctx, ctx.capture.grab()[0], "resultat_titre")):
            return
        if cfg.pause_between_casts_ms > 0:
            ctx.log(f"Pause de {cfg.pause_between_casts_ms} ms avant le {spell.name}.")
            time.sleep(cfg.pause_between_casts_ms / 1000)
        cast_ok, moved_for_spell = cast_secondary(ctx, spell, should_stop)
        if cast_ok:
            st.casts += 1
        if moved_for_spell:
            st.moved = True


def play_turn(ctx: Context, should_stop, turn: int = 0) -> int:
    """Joue un tour (turn = numéro du tour dans le combat, 1 = premier). Retourne le nombre de lancers réussis."""
    cfg = ctx.config
    spells = book(ctx)
    ctx.log("Mon tour.")
    ctx.select_unverified = False
    ctx.failed_moves = []                              # cases de déplacement ratées : repart de zéro à chaque tour
    time.sleep(cfg.turn_start_delay_s)
    st = TurnState()
    if cfg.opening_spell and spells.opening:
        if turn == 1:                                                              # sort d'ouverture au 1er tour
            if not should_stop():
                ctx.opening_recast_fails = 0
                st.opening_done = cast_opening(ctx, spells.opening)
        elif turn > 1 and cfg.opening_recast and ctx.opening_recast_fails < 2 and not should_stop() \
                and opening_available(ctx, spells.opening):                        # rechargé : on le relance
            ctx.log(f"Le {spells.opening.name} est de nouveau disponible : je le relance (comme au 1er tour).")
            st.opening_done = cast_opening(ctx, spells.opening, first_turn=False)
            ctx.opening_recast_fails = 0 if st.opening_done else ctx.opening_recast_fails + 1
    while st.casts < cfg.casts_per_turn and not should_stop():
        if not _primary_step(ctx, st, should_stop):
            break
    _secondary_spells(ctx, st, should_stop)
    if not should_stop():
        release_spells(ctx)                            # aucun sort ne doit rester sélectionné au moment de finir le tour
    ctx.progress += st.casts + int(st.moved) + int(st.opening_done)
    return st.casts


# --- fin du tour, boucle des tours, diagnostic ------------------------------------------------------

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


def _save_turn_timeout_diag(ctx: Context) -> None:
    """Aucun tour détecté : capture de ce que voit le programme + échelle d'affichage et éléments reconnus, pour savoir
    si le jeu était simplement mal reconnu (échelle, fenêtre redimensionnée) ou si le combat était vraiment en pause."""
    try:
        scene, _ = ctx.capture.grab()
        r = read_ui(scene, ctx.ui_templates, ctx.config.ui_threshold)
        vp = getattr(ctx.capture, "viewport", None)
        ctx.log(f"Diagnostic : échelle d'affichage {getattr(vp, 'scale', '?')} "
                f"({'origine' if getattr(vp, 'identity', False) else 'adaptée'}), éléments reconnus : "
                f"{', '.join(sorted(r.found)) or 'aucun'}, tour actif : {r.turn_active}.")
        if ctx.config.save_diagnostics:
            path = logs_dir() / f"tour_introuvable_{datetime.now():%Y%m%d_%H%M%S}.png"
            save_image(path, scene)
            ctx.log(f"Capture enregistrée : {path}")
    except Exception as e:                                  # le diagnostic ne doit jamais gêner l'arrêt
        ctx.log(f"(diagnostic impossible : {e})")


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
            _save_turn_timeout_diag(ctx)
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
    spells = book(ctx)
    scene, _ = ctx.capture.grab()
    enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
    if me:
        ctx.me_hint = me.center
    mask = range_mask(scene)
    visible = (is_selected(scene, find_icon(ctx, scene, spells.primary.icon), SMALL_RANGE_PIXELS)
               or any(is_selected(scene, find_icon(ctx, scene, s.icon), SMALL_RANGE_PIXELS) for s in spells.secondary))
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
