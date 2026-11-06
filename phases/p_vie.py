"""Contrôle de la vie avant de relancer un combat : si elle est sous le minimum, boire des potions
(double clic sur la potion de la barre d'objets) jusqu'à atteindre le minimum."""
import time

from core import input as inp
from core.vie import read_hp_percent
from phases.base import Context
from phases.p4_tour import _find

# Intervalles (ms) entre les deux appuis du double clic, essayés dans l'ordre tant que la vie ne monte pas ;
# celui qui a marché est réutilisé en premier ensuite.
GAPS_MS = (100, 180, 280, 60)
_good_gap = {"ms": None}

ANCHOR = "hud_oeil"        # repère du HUD (assets/ui/hud_oeil.png) : le cœur est à une position fixe par rapport à lui
POTION = "potion_vie"      # image de la potion à boire (assets/ui/potion_vie.png)


def _sleep(seconds: float, should_stop) -> None:
    end = time.time() + seconds
    while time.time() < end and not should_stop():
        time.sleep(0.05)


def ensure_health(ctx: Context, should_stop) -> str:
    """Retourne 'ok' (vie suffisante), 'unknown' (cœur introuvable : contrôle ignoré) ou 'fail' (impossible
    d'atteindre le minimum : le programme doit s'arrêter)."""
    cfg = ctx.config
    last, stalled, gap_used = None, 0, None
    for used in range(cfg.heal_max_potions + 1):
        if should_stop():
            return "fail"
        scene, (ox, oy) = ctx.capture.grab()
        eye = _find(ctx, scene, ANCHOR)
        pct = read_hp_percent(scene, eye.x, eye.y) if eye else None
        if pct is None:
            ctx.log("Contrôle de la vie ignoré : le cœur n'est pas visible (repère de l'interface introuvable).")
            return "unknown"
        ctx.log(f"Vie : {pct:.0f} % (minimum {cfg.min_hp_percent} %).")
        if last is not None and pct > last + 0.5 and gap_used is not None:
            _good_gap["ms"] = gap_used                  # ce double clic a marché : on le garde
        if pct >= cfg.min_hp_percent:
            return "ok"
        if used >= cfg.heal_max_potions:
            break
        stalled = stalled + 1 if (last is not None and pct <= last + 0.5) else 0
        if stalled >= len(GAPS_MS):
            ctx.log("⚠ La vie ne monte plus malgré les potions (plus de potions, ou double clic non pris en compte ?).")
            return "fail"
        last = pct
        potion = _find(ctx, scene, POTION)
        if not potion:
            ctx.log(f"⚠ Potion introuvable dans la barre d'objets ({POTION}.png dans assets/ui).")
            return "fail"
        gap_used = _good_gap["ms"] if (stalled == 0 and _good_gap["ms"]) else GAPS_MS[stalled]
        ctx.log(f"Je bois une potion (double clic rapide, {gap_used} ms entre les deux appuis) : {used + 1}.")
        inp.double_click(ox + potion.center[0], oy + potion.center[1], gap_s=gap_used / 1000)
        _sleep(1.5, should_stop)                        # animation de la potion avant de relire la vie
    ctx.log(f"⚠ Vie toujours sous le minimum après {cfg.heal_max_potions} potion(s).")
    return "fail"
