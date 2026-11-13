"""Banc d'essai « monde simulé » du tour de jeu : l'ancien code (tests/legacy/p4_tour_legacy.py) et le nouveau
(phases/p4_tour.py) jouent côte à côte les mêmes milliers de tours, dont chaque décision du « monde » (sort
sélectionné ou non, déplacement réussi ou non, confirmation ou non, portée lisible ou non, adversaires visibles
ou non…) est tirée au hasard avec le même tirage. Les appels effectués, les clics, les lignes du journal, la valeur
retournée et l'état final doivent être strictement identiques.

    python tests/turn_model_harness.py [nombre_de_cas]
"""
import importlib.util
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# nom logique -> (nom dans l'ancien module, nom dans le nouveau module)
NAMES = {
    "find_icon": ("_find", "find_icon"), "select": ("_select_spell", "select_primary"),
    "reselect": ("_reselect_after_move", "reselect_primary"), "my_position": ("my_position", "my_position"),
    "move_closer": ("move_closer", "move_closer"), "wait_confirm": ("_wait_confirm", "wait_confirm"),
    "find_enemies": ("find_enemies", "find_enemies"), "find_me": ("find_me", "find_me"),
    "range_mask": ("range_mask", "range_mask"), "range_fraction": ("range_fraction", "range_fraction"),
    "cast_opening": ("cast_opening_spell", "cast_opening"), "cast_second": ("cast_second_spell", "cast_secondary"),
    "release": ("_release_spells", "release_spells"), "diag": ("_diag", "save_diag"),
}


def _legacy_module():
    spec = importlib.util.spec_from_file_location("p4_tour_legacy", ROOT / "tests" / "legacy" / "p4_tour_legacy.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Clock:
    t = 1000.0


class _Cap:
    def __init__(self, trace):
        self.trace = trace

    def grab(self):
        self.trace.append("grab")
        return np.zeros((8, 8, 3), np.uint8), (0, 0)


def run_case(module, which: int, seed: int):
    """which : 0 = ancien module, 1 = nouveau module."""
    from core.combat import Fighter
    from core.config import Config
    from phases.base import Context
    rng = random.Random(seed)
    trace, clicks, logs = [], [], []
    cfg = Config()
    cfg.save_diagnostics = False
    cfg.turn_start_delay_s = 0.0
    cfg.opening_recast = False                     # ces bancs vérifient le comportement historique (sans relance)
    cfg.casts_per_turn = rng.choice([1, 2, 2, 3])
    cfg.move_when_out_of_range = rng.random() < 0.8
    cfg.second_spell = rng.random() < 0.8
    cfg.opening_spell = rng.random() < 0.8
    cfg.pause_between_casts_ms = rng.choice([0, 500])
    cfg.blind_range_max_cells = rng.choice([3, 5])
    turn = rng.choice([1, 2])
    ctx = Context(cfg, _Cap(trace), [], [], logs.append)
    ctx.me_hint = rng.choice([None, (400, 300), (900, 500)])
    ctx.last_enemies = rng.choice([[], [(600, 400)], [(300, 200), (700, 450)]])
    ctx.no_enemy_streak = rng.choice([0, 1, 3, 5])           # jamais 2 : +1 donnerait 3 (écriture d'une capture)
    stop_after = rng.choice([None, None, None, 6, 15, 40])
    calls = {"stop": 0}

    def should_stop():
        calls["stop"] += 1
        return stop_after is not None and calls["stop"] > stop_after

    def pick(p):
        return rng.random() < p

    def fighters(n):
        return [Fighter(rng.randrange(350, 1500), rng.randrange(150, 900), 300) for _ in range(n)]

    def stub(name):
        def f(*a, **k):
            trace.append(name)
            if name == "find_icon":
                nm = a[2] if len(a) > 2 else k.get("name")
                trace.append(nm)
                return object() if nm == "resultat_titre" and pick(0.06) else None
            if name == "select":
                ok = pick(0.85)
                if ok and pick(0.15):
                    ctx.select_unverified = True
                return ok
            if name == "reselect":
                return pick(0.85)
            if name == "my_position":
                return rng.choice([None, (520, 380), (880, 560)])
            if name == "move_closer":
                ok = pick(0.5)
                if ok and pick(0.5):
                    ctx.me_hint = (rng.randrange(400, 1400), rng.randrange(200, 800))
                return ok
            if name == "wait_confirm":
                if pick(0.55):
                    return type("D", (), {"center": (700, 600)})(), (0, 0)
                return None, None
            if name == "find_enemies":
                return fighters(rng.choice([0, 1, 1, 2, 3, 4]))
            if name == "find_me":
                return fighters(1)[0] if pick(0.7) else None
            if name == "range_mask":
                m = np.zeros((40, 40), np.uint8)
                n = rng.choice([0, 100, 900, 1200])
                m.reshape(-1)[:n] = 1
                return m
            if name == "range_fraction":
                return rng.choice([0.0, 0.02, 0.06, 0.4])
            if name == "cast_opening":
                return pick(0.7)
            if name == "cast_second":
                return pick(0.5), pick(0.3)
            return None                                       # release, diag
        return f

    patched = []
    mod_clock = (time.time, time.sleep)
    from core import input as inp
    real_click = inp.click
    _Clock.t = 1000.0
    time.time = lambda: _Clock.t
    time.sleep = lambda s: setattr(_Clock, "t", _Clock.t + s)
    inp.click = lambda x, y, *a, **k: clicks.append([int(x), int(y)])
    try:
        for logical, names in NAMES.items():
            nm = names[which]
            patched.append((nm, getattr(module, nm)))
            setattr(module, nm, stub(logical))
        try:
            ret, err = module.play_turn(ctx, should_stop, turn), None
        except Exception as e:
            ret, err = None, f"{type(e).__name__}: {e}"
    finally:
        for nm, orig in patched:
            setattr(module, nm, orig)
        time.time, time.sleep = mod_clock
        inp.click = real_click
    return {"ret": ret, "err": err, "trace": trace, "clicks": clicks, "logs": logs, "stop_calls": calls["stop"],
            "state": [ctx.me_hint, ctx.select_unverified, ctx.hint_unverified, ctx.failed_moves, ctx.last_enemies,
                      ctx.no_enemy_streak, ctx.progress]}


def main(n=3000):
    import phases.p4_tour as new
    old = _legacy_module()
    bad = 0
    n_logs = n_clicks = 0
    for seed in range(n):
        a, b = run_case(old, 0, seed), run_case(new, 1, seed)
        n_logs += len(a["logs"])
        n_clicks += len(a["clicks"])
        if a != b:
            bad += 1
            if bad <= 3:
                print(f"[ÉCHEC] seed {seed} : résultats différents")
                for k in a:
                    if a[k] != b[k]:
                        print(f"   {k}:\n     ancien  {a[k]}\n     nouveau {b[k]}")
                        break
    if bad:
        print(f"[ÉCHEC] banc « monde simulé » : {bad} cas différents sur {n}")
        return 1
    print(f"[OK] banc « monde simulé » : {n} tours identiques, ancien code contre nouveau "
          f"({n_logs} lignes de journal, {n_clicks} clics)")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3000))
