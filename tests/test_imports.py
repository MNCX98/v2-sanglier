"""Démarrage : tous les modules s'importent et la fenêtre principale se construit (sans écran).
Attrape les imports cassés par un déplacement de code, que les autres tests ne voient pas.

    python tests/test_imports.py
"""
import importlib
import os
import pkgutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    bad = []
    n = 0
    for pkg in ("core", "phases", "gui"):
        mod = importlib.import_module(pkg)
        for m in pkgutil.iter_modules(mod.__path__):
            name = f"{pkg}.{m.name}"
            n += 1
            try:
                importlib.import_module(name)
            except Exception as e:                         # noqa: BLE001
                bad.append(f"{name} : {type(e).__name__}: {e}")
    importlib.import_module("main") if (ROOT / "main.py").exists() and False else None
    for b in bad:
        print("[ÉCHEC] import", b)
    if not bad:
        print(f"[OK] {n} modules importés sans erreur")
    try:                                                   # le démarrage de la boucle (sans jeu) : réglages, profil de sorts
        from core.capture import WindowCapture
        from core.config import Config
        from phases.base import Context
        from phases.runner import run_phases
        logs = []
        ctx = Context(Config(), WindowCapture("BlueStacks"), [], [], logs.append)
        run_phases(ctx, lambda: True)
        ok = ctx.spells is not None and ctx.spells.builtin and any("Arrêté" in x for x in logs)
        print(f"[{'OK' if ok else 'ÉCHEC'}] démarrage de la boucle principale (arrêt immédiat) : profil de sorts chargé")
        bad += [] if ok else ["runner"]
    except Exception as e:                                 # noqa: BLE001
        print(f"[ÉCHEC] boucle principale : {type(e).__name__}: {e}")
        bad.append("runner")
    try:
        from PySide6.QtWidgets import QApplication, QTabWidget
        app = QApplication.instance() or QApplication([])
        from gui.app import MainWindow
        w = MainWindow()
        tabs = w.findChild(QTabWidget)
        names = [tabs.tabText(i) for i in range(tabs.count())]
        ok = "Sorts" in names and w.ctx.spells is not None and w.ctx.spells.builtin
        print(f"[{'OK' if ok else 'ÉCHEC'}] fenêtre principale construite, onglets : {', '.join(names)}")
        bad += [] if ok else ["fenêtre"]
    except Exception as e:                                 # noqa: BLE001
        print(f"[ÉCHEC] fenêtre principale : {type(e).__name__}: {e}")
        bad.append("fenêtre")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
