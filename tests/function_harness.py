"""Compare, sur de vraies captures, chaque fonction déplacée lors du nettoyage avec sa version d'origine
(tests/legacy/p4_tour_legacy.py) : mêmes clics, mêmes lignes de journal, même valeur, même état final.

    python tests/function_harness.py [cas_par_fonction]
"""
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import turn_harness as th                      # noqa: E402

FUNCS = ["opening", "secondary", "release", "select", "select_force", "deselect", "reselect", "move_closer",
         "my_position", "plan_move", "plan_move_green"]


def _weights(names):
    heavy = ("10", "19", "09c", "11")
    mid = ("09", "13", "35", "36", "32", "33", "34", "17", "18", "08c", "07", "05")
    return [25 if n[:3] in heavy or n[:2] in heavy else 8 if n[:2] in mid else 1 for n in names]


def run_one(args):
    fname, seed = args
    import importlib
    from core import input as inp
    from core.combat import find_enemies, find_me
    from core.config import Config
    from core.paths import ui_dir
    from core.spells import default_spellbook
    from core.vision import load_ui_templates
    from phases.base import Context
    import phases.casting as casting
    import phases.movement as movement
    import phases.primary_spell as primary
    legacy = importlib.import_module("tests.legacy.p4_tour_legacy") if False else __import__("turn_model_harness")._legacy_module()
    names, pool = th._pool()
    ui = load_ui_templates(ui_dir())
    book = default_spellbook()
    out = []
    for which in (0, 1):
        rng = random.Random(seed)
        frames = []
        w = _weights(names)
        while len(frames) < 80:
            img = pool[rng.choices(range(len(pool)), w)[0]]
            frames += [img] * rng.randint(1, 4)
        cfg = Config()
        cfg.save_diagnostics = False
        cfg.move_when_out_of_range = rng.random() < 0.85
        clicks, logs = [], []
        ctx = Context(cfg, th._Cap(frames), [], ui, logs.append)
        ctx.me_hint = rng.choice([None, (1023, 651), (936, 563), (805, 192)])
        ctx.select_unverified = rng.random() < 0.2
        ctx.hint_unverified = rng.random() < 0.2
        real = (time.time, time.sleep, inp.click)
        th._Clock.t = 1000.0
        time.time = lambda: th._Clock.t
        time.sleep = lambda s: setattr(th._Clock, "t", th._Clock.t + s)
        inp.click = lambda x, y, *a, **k: clicks.append([int(x), int(y)])
        stop = lambda: False
        try:
            first = frames[0]
            enemies = find_enemies(first)
            me = find_me(first)
            pos = rng.choice([me.center if me else None, (900, 500), (500, 600)])
            try:
                if fname == "opening":
                    ret = (legacy.cast_opening_spell(ctx) if which == 0 else casting.cast_opening(ctx, book.opening))
                elif fname == "secondary":
                    ret = (legacy.cast_second_spell(ctx, stop) if which == 0
                           else casting.cast_secondary(ctx, book.secondary[0], stop))
                elif fname == "release":
                    ret = (legacy._release_spells(ctx) if which == 0 else casting.release_spells(ctx))
                elif fname in ("select", "select_force"):
                    force = fname == "select_force"
                    ret = (legacy._select_spell(ctx, force) if which == 0 else primary.select_primary(ctx, force))
                elif fname == "deselect":
                    ret = (legacy._deselect_spell(ctx) if which == 0 else primary.deselect_primary(ctx))
                elif fname == "reselect":
                    ret = (legacy._reselect_after_move(ctx) if which == 0 else primary.reselect_primary(ctx))
                elif fname == "move_closer":
                    ret = (legacy.move_closer(ctx, enemies, pos, stop) if which == 0
                           else movement.move_closer(ctx, enemies, pos, stop)) if pos and enemies else "sans objet"
                elif fname == "my_position":
                    from core.combat import range_mask
                    m = range_mask(first)
                    ret = (legacy.my_position(ctx, first, me, m, enemies) if which == 0
                           else movement.my_position(ctx, first, me, m, enemies)) if enemies else "sans objet"
                else:                                   # plan_move / plan_move_green : fonctions pures
                    f = {"plan_move": (legacy.plan_move, movement.plan_move),
                         "plan_move_green": (legacy.plan_move_green, movement.plan_move_green)}[fname][which]
                    r = f(ctx, first, enemies, pos) if pos and enemies else None
                    ret = None if r is None else repr(r)
                err = None
            except Exception as e:
                ret, err = None, f"{type(e).__name__}: {e}"
        finally:
            time.time, time.sleep, inp.click = real
        out.append({"ret": repr(ret), "err": err, "clicks": clicks, "logs": logs, "grabs": ctx.capture.i,
                    "state": repr([ctx.me_hint, ctx.select_unverified, ctx.hint_unverified, ctx.failed_moves, ctx.progress])})
    return (fname, seed, out[0] == out[1], out[0], out[1])


def main(n=40):
    jobs = [(f, s) for f in FUNCS for s in range(n)]
    with Pool(4) as p:
        res = p.map(run_one, jobs, chunksize=4)
    bad = [r for r in res if not r[2]]
    errs = sum(1 for r in res if r[3]["err"])
    clicks = sum(len(r[3]["clicks"]) for r in res)
    per = {f: sum(1 for r in res if r[0] == f and r[2]) for f in FUNCS}
    if bad:
        print(f"[ÉCHEC] {len(bad)} cas différents sur {len(res)}")
        for f, s, _, a, b in bad[:3]:
            print(f"  {f} seed {s}")
            for k in a:
                if a[k] != b[k]:
                    print(f"   {k}:\n     ancien  {a[k]}\n     nouveau {b[k]}")
                    break
        return 1
    print(f"[OK] fonctions déplacées : {len(res)} appels identiques à l'ancien code ({clicks} clics, "
          f"{errs} exception(s) identiques) — " + ", ".join(f"{f} {c}/{n}" for f, c in per.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 40))
