"""Contrôle de la vie avant de relancer un combat : si elle est sous le minimum, boire des potions
(double clic sur la potion de la barre d'objets) jusqu'à atteindre le minimum.

Une potion rend peu de vie (environ 1,5 %, soit un cran du cœur) : on ne peut donc pas juger un double clic sur la
seule vie lue. On regarde plutôt le compteur de la potion (le petit nombre en haut à gauche de l'icône) : s'il a
changé, la potion a bien été bue ; sinon le double clic n'a pas été pris en compte et on insiste."""
import time

import cv2

from core import input as inp
from core.vie import read_hp_percent
from phases.base import Context
from phases.turn_helpers import find_icon as _find

ANCHOR = "hud_oeil"        # repère du HUD (assets/ui/hud_oeil.png) : le cœur est à une position fixe par rapport à lui
POTION = "potion_vie"      # image de la potion à boire (assets/ui/potion_vie.png)

DEFAULT_GAP_MS = 60                         # intervalle entre les deux appuis du double clic (celui qui a marché le mieux)
RETRY_GAPS_MS = (None, 100, 140, 200, 80)   # essais successifs après un échec (None = même intervalle, on insiste)
MAX_CLICK_FAILS = 6                         # échecs de double clic d'affilée avant d'abandonner
MAX_NO_GAIN = 8                             # potions bues d'affilée sans que la vie monte avant d'abandonner
# Pas de limite au nombre de potions tant que la vie monte : on s'arrête seulement si la potion disparaît de la barre
# (plus de stock), si les double clics échouent, ou si la vie ne monte plus.
_stats: dict[int, list[int]] = {}           # par intervalle (ms) : [doubles clics réussis, doubles clics tentés]


def _sleep(seconds: float, should_stop) -> None:
    end = time.time() + seconds
    while time.time() < end and not should_stop():
        time.sleep(0.05)


def _count_crop(scene, potion):
    """Zone du petit compteur (en haut à gauche de l'icône de la potion), en niveaux de gris."""
    x0, y0 = max(0, potion.x - 6), max(0, potion.y - 24)
    crop = scene[y0:max(y0 + 1, potion.y - 3), x0:potion.x + 44]
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)


def _count_changed(before, after) -> bool:
    if before is None or after is None or before.shape != after.shape:
        return False
    return int((cv2.absdiff(before, after) > 40).sum()) >= 10


def _record(gap_ms: int, success: bool) -> None:
    st = _stats.setdefault(gap_ms, [0, 0])
    st[0] += int(success)
    st[1] += 1


def _best_gap() -> int:
    """Intervalle au meilleur taux de réussite (l'intervalle par défaut part avec un petit avantage)."""
    rates = {g: (ok + (1 if g == DEFAULT_GAP_MS else 0.5)) / (n + 1.5) for g, (ok, n) in _stats.items()}
    rates.setdefault(DEFAULT_GAP_MS, 0.67)
    return max(rates, key=lambda g: (rates[g], g == DEFAULT_GAP_MS))


def _gap_for(fails: int) -> int:
    best = _best_gap()
    if fails <= 0:
        return best
    gap = RETRY_GAPS_MS[min(fails - 1, len(RETRY_GAPS_MS) - 1)]
    return gap or best


def ensure_health(ctx: Context, should_stop) -> str:
    """Retourne 'ok' (vie suffisante), 'unknown' (cœur introuvable : contrôle ignoré) ou 'fail' (impossible
    d'atteindre le minimum : le programme doit s'arrêter)."""
    cfg = ctx.config
    potions = fails = no_gain = 0
    last_pct = last_crop = gap_used = None
    while True:
        if should_stop():
            return "fail"
        scene, (ox, oy) = ctx.capture.grab()
        eye = _find(ctx, scene, ANCHOR)
        pct = read_hp_percent(scene, eye.x, eye.y) if eye else None
        if pct is None:
            ctx.log("Contrôle de la vie ignoré : le cœur n'est pas visible (repère de l'interface introuvable).")
            return "unknown"
        ctx.log(f"Vie : {pct:.0f} % (minimum {cfg.min_hp_percent} %).")
        if pct >= cfg.min_hp_percent:
            return "ok"
        potion = _find(ctx, scene, POTION)
        if not potion:
            ctx.log(f"⚠ Potion introuvable dans la barre d'objets ({POTION}.png dans assets/ui).")
            return "fail"
        crop = _count_crop(scene, potion)
        if last_crop is not None:                       # le double clic précédent a-t-il fait boire la potion ?
            if _count_changed(last_crop, crop):
                fails = 0
                _record(gap_used, True)                 # on retient les intervalles qui marchent
                no_gain = no_gain + 1 if pct <= last_pct + 0.5 else 0
                if no_gain >= MAX_NO_GAIN:
                    ctx.log(f"⚠ La vie ne monte plus malgré {no_gain} potions bues.")
                    return "fail"
            else:
                fails += 1
                _record(gap_used, False)
                ctx.log(f"Potion non bue (le compteur n'a pas changé) : le double clic n'a pas été pris en compte "
                        f"({fails}/{MAX_CLICK_FAILS}).")
                if fails >= MAX_CLICK_FAILS:
                    ctx.log("⚠ Le double clic sur la potion échoue à chaque fois.")
                    return "fail"
        gap_used = _gap_for(fails)
        ctx.log(f"Je bois une potion (double clic rapide, {gap_used} ms entre les deux appuis) : {potions + 1}.")
        inp.double_click(ox + potion.center[0], oy + potion.center[1], gap_s=gap_used / 1000)
        potions += 1
        last_crop, last_pct = crop, pct
        _sleep(1.5 + (0.8 if fails else 0), should_stop)   # animation de la potion avant de relire la vie
