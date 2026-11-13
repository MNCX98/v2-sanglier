"""Relance du sort d'ouverture quand il est de nouveau disponible (plus de chiffre sur l'icône).

1) Sur des captures réelles : icône disponible (tour 1) ou en recharge (tour 2, assombrie avec un chiffre).
2) Logique de play_turn avec de faux lancers : relance seulement si activée, tour > 1, sort disponible, et on
   abandonne après 2 échecs de suite dans le combat.
"""
import sys
import types
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"

from core.config import Config  # noqa: E402
from core.paths import app_dir  # noqa: E402
from core.spells import default_spellbook  # noqa: E402
from core.vision import load_ui_templates  # noqa: E402
import phases.casting as casting  # noqa: E402
import phases.p4_tour as p4  # noqa: E402
from phases.base import Context  # noqa: E402


def _img(name):
    return cv2.imdecode(np.fromfile(str(FIX / name), np.uint8), cv2.IMREAD_COLOR)


class _Cap:
    def __init__(self, img):
        self.img = img

    def grab(self):
        return self.img, (0, 0)


def check_real_screens():
    ui = load_ui_templates(app_dir() / "assets" / "ui")
    spell = default_spellbook().opening
    expect = {"09_mon_tour.png": True, "07_fight.png": True, "33_bord_haut_entoure_1.png": True,
              "36_deplacement_tour2.png": False, "35_deplacement_tour1.png": False, "32_ennemi_cache_arc.png": False}
    for name, want in expect.items():
        ctx = Context(Config(), _Cap(_img(name)), [], ui, lambda m: None)
        got = casting.opening_available(ctx, spell)
        assert got == want, f"{name} : disponible={got}, attendu {want}"
    print(f"[OK] icône du sort d'ouverture : disponible/en recharge bien distingués sur {len(expect)} captures réelles")


def check_turn_logic():
    calls, cd = [], {"available": True, "cast_ok": True}
    saved = (p4.cast_opening, p4.opening_available, p4._primary_step, p4._secondary_spells, p4.release_spells,
             p4.time.sleep)
    p4.cast_opening = lambda ctx, spell, first_turn=True: calls.append(("cast", first_turn)) or cd["cast_ok"]
    p4.opening_available = lambda ctx, spell: cd["available"]
    p4._primary_step = lambda ctx, st, stop: False
    p4._secondary_spells = lambda ctx, st, stop: None
    p4.release_spells = lambda ctx: None
    p4.time.sleep = lambda s: None
    try:
        def run(turns, available=True, cast_ok=True, **cfg_over):
            calls.clear()
            cd.update(available=available, cast_ok=cast_ok)
            cfg = Config()
            cfg.turn_start_delay_s = 0.0
            for k, v in cfg_over.items():
                setattr(cfg, k, v)
            ctx = Context(cfg, _Cap(None), [], [], lambda m: None)
            ctx.spells = default_spellbook()
            for t in turns:
                p4.play_turn(ctx, lambda: False, t)
            return list(calls), ctx

        c, _ = run([1])
        assert c == [("cast", True)], c                                     # 1er tour : comme avant
        c, _ = run([1, 2, 3], available=True)
        assert c == [("cast", True), ("cast", False), ("cast", False)], c   # relancé dès qu'il est disponible
        c, _ = run([1, 2, 3], available=False)
        assert c == [("cast", True)], c                                     # en recharge : pas de relance
        c, _ = run([1, 2, 3], available=True, opening_recast=False)
        assert c == [("cast", True)], c                                     # option désactivée
        c, _ = run([1, 2, 3], available=True, opening_spell=False)
        assert c == [], c                                                   # sort d'ouverture désactivé : rien
        c, ctx = run([2, 3, 4, 5], available=True, cast_ok=False)
        assert c == [("cast", False), ("cast", False)], c                   # 2 échecs de suite : on arrête d'essayer
        c, ctx = run([1, 2, 3, 4], available=True, cast_ok=False)
        assert [x[1] for x in c] == [True, False, False], c                 # un nouveau combat (tour 1) remet à zéro
        print("[OK] play_turn : 1er tour inchangé, relance si disponible, désactivable, arrêt après 2 échecs")
    finally:
        (p4.cast_opening, p4.opening_available, p4._primary_step, p4._secondary_spells, p4.release_spells,
         p4.time.sleep) = saved


if __name__ == "__main__":
    check_real_screens()
    check_turn_logic()
    print("RÉSULTAT : tous les tests réussis")
