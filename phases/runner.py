"""Enchaîne toutes les phases en boucle : recherche (1), combat (2), placement (3),
tours (4-5), fin du combat (6), puis retour à la recherche."""
import time

from core.combat import apply_layout
from core.spells import resolve_spellbook
from phases.base import Context
from phases.p1_recherche import scan_once
from phases.p2_combat import wait_for_combat
from phases.p3_placement import run_placement
from phases.p4_tour import run_turns
from phases.p6_fin import close_result, close_stray_popups
from phases.p_inventaire import inventory_full, unload_to_mount
from phases.p_vie import ensure_health


def _sleep(seconds: float, should_stop) -> None:
    end = time.time() + seconds
    while time.time() < end and not should_stop():
        time.sleep(0.05)


def _fight(ctx: Context, should_stop, on_frame) -> str:
    """Déroule un combat après le clic sur le monstre. Retourne 'next' (reprendre la recherche),
    'done' (combat terminé et fenêtre fermée) ou 'stop' (le programme doit s'arrêter)."""
    cfg = ctx.config
    if not wait_for_combat(ctx, should_stop, on_frame):            # phase 2
        return "next"
    if not cfg.do_placement:
        ctx.log("Phase 2 validée. Le programme s'arrête ici.")
        return "stop"
    if not run_placement(ctx, should_stop, on_frame):              # phase 3
        ctx.log("Phase 3 non aboutie : le programme s'arrête, reprends la main.")
        return "stop"
    if not cfg.do_turns:
        ctx.log("Phase 3 validée. Le programme s'arrête ici.")
        return "stop"
    status = run_turns(ctx, should_stop)                           # phases 4-5
    if status != "over":
        return "stop"
    if not close_result(ctx, should_stop):                         # phase 6
        return "stop"
    return "done"


def _stop_lost(ctx: Context, seconds: int) -> None:
    """Aucun monstre reconnu depuis `seconds` s : le personnage est peut-être sur une autre carte (sortie par le bord)."""
    from datetime import datetime
    from core.imgio import save_image
    from core.paths import logs_dir
    ctx.log(f"Aucun monstre reconnu depuis {seconds} s : je suis peut-être sur une autre carte (sortie par le bord ?). "
            "Le programme s'arrête, reprends la main.")
    try:
        scene, _ = ctx.capture.grab()
        path = logs_dir() / f"aucun_monstre_{datetime.now():%Y%m%d_%H%M%S}.png"
        save_image(path, scene)
        ctx.log(f"Capture enregistrée : {path}")
    except Exception:
        pass


_last_error_capture = 0.0


def _save_error_capture(ctx: Context, error: Exception) -> None:
    """Erreur inattendue : enregistre une capture « erreur_….png » (ce que le programme voyait) pour comprendre ce qui s'est passé.
    Pas pour « fenêtre introuvable » (aucune image à prendre) ; au plus une capture toutes les 10 s pour ne pas en produire à la chaîne."""
    global _last_error_capture
    from datetime import datetime
    from core.capture import WindowNotFound
    from core.imgio import save_image
    from core.paths import logs_dir
    if isinstance(error, WindowNotFound) or time.time() - _last_error_capture < 10:
        return
    try:
        scene, _ = ctx.capture.grab()
        path = logs_dir() / f"erreur_{datetime.now():%Y%m%d_%H%M%S}.png"
        save_image(path, scene)
        _last_error_capture = time.time()
        ctx.log(f"Capture de l'écran enregistrée : {path} ({type(error).__name__})")
    except Exception:
        pass                                                       # la capture d'erreur ne doit jamais provoquer une autre erreur


def run_phases(ctx: Context, should_stop, on_frame=None) -> None:
    cfg = ctx.config
    apply_layout(cfg)
    ctx.spells = resolve_spellbook(cfg.spell_profile)
    ctx.log("Démarré. Appuie sur F12 pour arrêter.")
    if not ctx.spells.builtin:
        ctx.log(f"Sorts : profil « {ctx.spells.name} ».")
    ctx.capture.viewport.log_hook = ctx.log                        # messages d'adaptation à l'échelle du jeu
    combats = 0
    lost_since: float | None = None                                 # début d'une série de recherches sans monstre
    need_heal = True                                               # contrôle de la vie avant chaque combat
    while not should_stop():
        pause = cfg.scan_interval_ms / 1000
        try:
            if cfg.unload_enabled:                                  # inventaire plein : on vide dans la monture
                scene, _ = ctx.capture.grab()
                if inventory_full(ctx, scene):
                    if unload_to_mount(ctx, should_stop) != "ok":
                        if not should_stop():
                            ctx.log("Le programme s'arrête : impossible de vider l'inventaire dans la monture.")
                        return
                    continue
            if close_stray_popups(ctx, should_stop):                # fenêtre (montée de niveau…) arrivée en retard
                continue
            if need_heal and cfg.heal_enabled:
                if ensure_health(ctx, should_stop) == "fail":
                    if not should_stop():
                        ctx.log("Le programme s'arrête : vie insuffisante, reprends la main.")
                    return
                need_heal = False
            out = scan_once(ctx, do_click=True)                    # phase 1
            if on_frame:
                on_frame(out.frame)
            if out.detection is not None:
                lost_since = None
            elif cfg.lost_stop_after_s > 0:
                lost_since = lost_since or time.time()
                if time.time() - lost_since >= cfg.lost_stop_after_s:
                    _stop_lost(ctx, cfg.lost_stop_after_s)
                    return
            if out.clicked:
                if cfg.detect_combat:
                    result = _fight(ctx, should_stop, on_frame)
                    if result == "stop":
                        return
                    if result == "done":
                        combats += 1
                        ctx.me_hint = None
                        need_heal = True
                        ctx.log(f"✔ Combat n°{combats} terminé.")
                        if not cfg.loop_combats:
                            ctx.log("Arrêt après un combat (option « enchaîner les combats » décochée).")
                            return
                        ctx.log("Je reprends la recherche d'un monstre.")
                        pause = 2.0
                else:
                    pause = cfg.cooldown_after_click_s
        except Exception as e:                                     # fenêtre introuvable, etc.
            ctx.log(f"⚠ {e}")
            _save_error_capture(ctx, e)
            pause = 2.0
        _sleep(pause, should_stop)
    if combats:
        ctx.log(f"Arrêté après {combats} combat(s) terminé(s).")
    else:
        ctx.log("Arrêté.")
