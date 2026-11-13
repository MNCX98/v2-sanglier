"""Banc d'essai « différentiel » du tour de jeu.

Fait jouer play_turn sur des enchaînements d'écrans RÉELS (captures de tests/fixtures, mélangées de façon
reproductible), avec une horloge simulée et des clics enregistrés au lieu d'être envoyés. Le résultat
(clics, lignes du journal, état final) est comparé à une référence enregistrée avant le nettoyage du code :
si une seule ligne ou un seul clic change, le test échoue.

    python tests/turn_harness.py --record   # (re)crée la référence tests/golden/turns.json
    python tests/turn_harness.py            # compare à la référence
"""
import json
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"
GOLDEN = ROOT / "tests" / "golden" / "turns.json"
N_CASES = 100
VARIANTS = [{}, {"casts_per_turn": 1}, {"second_spell": False}, {"move_when_out_of_range": False},
            {"opening_spell": False, "casts_per_turn": 3}]


def _load(name):
    return cv2.imdecode(np.fromfile(str(FIX / name), np.uint8), cv2.IMREAD_COLOR)


def _pool():
    names = sorted(p.name for p in FIX.glob("*.png") if p.name[0].isdigit())
    return names, [_load(n) for n in names]


class _Clock:
    t = 1000.0


class _Cap:
    def __init__(self, frames):
        self.frames, self.i = frames, 0

    def grab(self):
        self.i += 1
        if self.i > 4000:
            raise RuntimeError("trop de captures : boucle ?")
        return self.frames[min(self.i - 1, len(self.frames) - 1)], (0, 0)


def run_case(args):
    seed, turn, variant_idx = args[:3]
    custom = len(args) > 3 and args[3]          # True : sorts d'un profil importé (copies des icônes d'origine)
    from core import input as inp
    from core.config import Config
    from core.paths import ui_dir
    from core.vision import load_ui_templates
    from phases.base import Context
    import phases.p4_tour as p4

    names, pool = _pool()
    rng = random.Random(seed)
    weights = [1 if n[:2] in ("26", "27", "28", "29", "30") else 5 for n in names]   # surtout des écrans de combat
    if seed > 50:                                              # 2e famille : beaucoup d'écrans « sort choisi / confirmation »
        weights = [30 if n[:2] in ("09", "10", "11", "13") else w for n, w in zip(names, weights)]
    frames = []
    while len(frames) < 120:                                   # des « plages » d'un même écran, comme en vrai
        img = pool[rng.choices(range(len(pool)), weights)[0]]
        frames += [img] * rng.randint(1, 5)
    cfg = Config()
    cfg.save_diagnostics = False
    cfg.turn_start_delay_s = 0.0
    cfg.opening_recast = False                     # ces bancs vérifient le comportement historique (sans relance)
    for k, v in VARIANTS[variant_idx].items():
        setattr(cfg, k, v)
    clicks, logs = [], []
    ui = load_ui_templates(ui_dir())
    spells = None
    if custom:
        import shutil
        import tempfile
        import core.spells as sp
        tmp = Path(tempfile.mkdtemp())
        sp.spells_dir = lambda: tmp
        pairs = (("sort_debut_combat", "usr_test_ouverture"), ("sort_attaque", "usr_test_principal"),
                 ("pied_du_sacrieur", "usr_test_secondaire1"))
        for stem, new in pairs:
            shutil.copy(ui_dir() / f"{stem}.png", tmp / f"{new}.png")
        ui = [t for t in ui if t.variant not in {a for a, _ in pairs}] + load_ui_templates(tmp)   # plus d'icônes d'origine
        spells = sp.SpellBook("Test", sp.Spell("sort d'ouverture", "usr_test_ouverture"),
                              sp.Spell("Coagulation", "usr_test_principal", sp.BIG_RANGE_PIXELS),
                              [sp.Spell("Pied du Sacrieur", "usr_test_secondaire1", sp.SMALL_RANGE_PIXELS)])
    ctx = Context(cfg, _Cap(frames), [], ui, logs.append)
    ctx.spells = spells
    real = (time.time, time.sleep, inp.click)
    _Clock.t = 1000.0
    time.time = lambda: _Clock.t
    time.sleep = lambda s: setattr(_Clock, "t", _Clock.t + s)
    inp.click = lambda x, y, *a, **k: clicks.append([int(x), int(y)])
    try:
        try:
            ret = p4.play_turn(ctx, lambda: False, turn)
            err = None
        except Exception as e:                                  # une exception fait aussi partie du comportement
            ret, err = None, f"{type(e).__name__}: {e}"
    finally:
        time.time, time.sleep, inp.click = real
    return {"case": f"seed{seed}-tour{turn}-var{variant_idx}", "ret": ret, "err": err, "clicks": clicks, "logs": logs,
            "grabs": ctx.capture.i,
            "state": {"me_hint": ctx.me_hint, "select_unverified": ctx.select_unverified,
                      "hint_unverified": ctx.hint_unverified, "failed_moves": ctx.failed_moves,
                      "last_enemies": ctx.last_enemies, "no_enemy_streak": ctx.no_enemy_streak,
                      "progress": ctx.progress}}


def cases():
    return [(s, 1 if s % 2 == 0 else 2, s % len(VARIANTS)) for s in range(1, N_CASES + 1)]


def main():
    record = "--record" in sys.argv
    with Pool(4) as p:
        results = p.map(run_case, cases())
    if record:
        GOLDEN.write_text(json.dumps(results, ensure_ascii=False, indent=0), encoding="utf-8")
        n_clicks = sum(len(r["clicks"]) for r in results)
        print(f"Référence enregistrée : {len(results)} cas, {n_clicks} clics, "
              f"{sum(len(r['logs']) for r in results)} lignes de journal, {sum(1 for r in results if r['err'])} exception(s).")
        return 0
    ref = json.loads(GOLDEN.read_text(encoding="utf-8"))
    bad = [(a["case"], b["case"]) for a, b in zip(ref, results) if a != json.loads(json.dumps(b))]
    if len(ref) != len(results) or bad:
        print(f"[ÉCHEC] banc d'essai des tours : {len(bad)} cas différents sur {len(results)}")
        for a, b in list(zip(ref, results))[:400]:
            b = json.loads(json.dumps(b))
            if a != b:
                print("  cas", a["case"])
                for i, (x, y) in enumerate(zip(a["logs"], b["logs"])):
                    if x != y:
                        print(f"    ligne {i}: attendu {x!r}\n              obtenu  {y!r}")
                        break
                else:
                    print("    journaux de longueurs/clics différents", len(a["logs"]), len(b["logs"]), a["clicks"] == b["clicks"])
                break
        return 1
    print(f"[OK] banc d'essai des tours : {len(results)} cas identiques à la référence "
          f"({sum(len(r['clicks']) for r in results)} clics, {sum(len(r['logs']) for r in results)} lignes de journal)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
