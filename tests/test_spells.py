"""Tests des profils de sorts : enregistrement, icônes, onglet « Sorts », fenêtre de découpe, et moteur de jeu avec un
profil importé (qui doit se comporter exactement comme le profil intégré si les icônes sont les mêmes).

    python tests/test_spells.py
"""
import json
import os
import re
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import cv2                      # noqa: E402
import numpy as np              # noqa: E402

FIX = ROOT / "tests" / "fixtures"
failures = 0


def check(ok, text):
    global failures
    print(f"[{'OK' if ok else 'ÉCHEC'}] {text}")
    failures += not ok


def load(name):
    return cv2.imdecode(np.fromfile(str(FIX / name), np.uint8), cv2.IMREAD_COLOR)


def _norm(line):                # le nom du fichier d'icône dans un message n'est pas un comportement
    return re.sub(r"\(.*?\.png dans .*?\)", "(…)", line)


def _custom_vs_golden(_):
    import turn_harness as th
    golden = json.loads(th.GOLDEN.read_text(encoding="utf-8"))
    cases = th.cases()[:24]
    bad = 0
    for i, (seed, turn, var) in enumerate(cases):
        r = th.run_case((seed, turn, var, True))
        g = golden[i]
        same = (r["clicks"] == g["clicks"] and [_norm(x) for x in r["logs"]] == [_norm(x) for x in g["logs"]]
                and r["ret"] == g["ret"] and r["grabs"] == g["grabs"])
        bad += not same
    return bad


def main():
    import core.spells as sp
    tmp = Path(tempfile.mkdtemp())
    sp.spells_dir = lambda: tmp
    sp.spells_profiles_path = lambda: tmp / "profiles.json"

    # 1) profil intégré = comportement historique
    b = sp.default_spellbook()
    check(b.builtin and b.opening.icon == "sort_debut_combat" and b.primary.icon == "sort_attaque"
          and b.primary.name == "Coagulation" and [s.icon for s in b.secondary] == ["pied_du_sacrieur"]
          and b.secondary[0].range_pixels == 800 and b.primary.range_pixels == 3000,
          "profil intégré : sort d'ouverture, Coagulation, Pied du Sacrieur (portées 3000 / 800 px)")
    check(sp.resolve_spellbook("").builtin and sp.resolve_spellbook("inconnu").builtin
          and sp.resolve_spellbook(sp.DEFAULT_PROFILE).builtin, "profil vide, inconnu ou intégré -> profil intégré")

    # 2) enregistrement
    crop = load("09_mon_tour.png")[646:646 + 56, 1613:1613 + 55]
    name = sp.new_icon_name("Cra (tir)", "principal", set())
    sp.save_icon(name, crop)
    book = sp.SpellBook("Cra (tir)", None, sp.Spell("Flèche", name), [])
    sp.save_profiles({"Cra (tir)": book})
    again = sp.load_profiles()
    check(name.startswith("usr_cra_tir_principal") and list(again) == ["Cra (tir)"] and again["Cra (tir)"].opening is None
          and again["Cra (tir)"].primary.name == "Flèche" and sp.resolve_spellbook("Cra (tir)").primary.icon == name
          and np.array_equal(sp.load_icon_image(name), crop), "profil et icône enregistrés puis relus à l'identique")
    (tmp / "profiles.json").write_text("{pas du json", encoding="utf-8")
    check(sp.load_profiles() == {} and sp.resolve_spellbook("Cra (tir)").builtin,
          "fichier de profils abîmé -> aucun plantage, retour au profil intégré")
    sp.save_profiles({"Cra (tir)": book})
    check(sp.new_icon_name("Cra (tir)", "principal") != name and not sp.new_icon_name("x", "y").startswith("sort_"),
          "un nom d'icône n'écrase jamais une icône existante ni une image intégrée")
    before = {p.name for p in sp.spells_dir().glob("*.png")}
    sp.delete_icon("sort_attaque")
    check(sp.delete_icon.__name__ and {p.name for p in sp.spells_dir().glob("*.png")} == before
          and (ROOT / "assets/ui/sort_attaque.png").exists(), "une image intégrée ne peut pas être supprimée")

    # 3) contrôle d'une icône découpée
    cur = load("09_mon_tour.png")
    c_ok = sp.analyze_icon(cur, (1613, 646, 55, 56))
    c_sel = sp.analyze_icon(load("10_sort_choisi.png"), (1613, 646, 55, 56))
    c_small = sp.analyze_icon(cur, (10, 10, 20, 20))
    c_edge = sp.analyze_icon(cur, (1900, 1000, 55, 56))
    check(c_ok.ok and not c_ok.warnings and c_ok.score > 0.99 and c_sel.ok and len(c_sel.warnings) == 1
          and not c_small.ok and not c_edge.ok,
          "contrôle d'icône : valide / « sélectionné » signalé / trop petit refusé / hors capture refusé")

    # 4) interface (sans écran) : onglet Sorts et fenêtre de découpe
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from core.config import Config
    from gui.spells_tab import CropDialog, SpellsTab
    cfg = Config()
    tab = SpellsTab(cfg)
    emitted = []
    tab.changed.connect(lambda: emitted.append(1))
    tab.apply_icon("primary", crop)                                     # profil intégré : lecture seule
    check(tab.current == sp.DEFAULT_PROFILE and not tab.editable() and not emitted and tab.combo.count() >= 2,
          "profil intégré protégé : aucune modification possible")
    nb = tab.create_profile("Eniripsa")
    tab.apply_icon("primary", crop, "Mot Soignant")
    tab.add_secondary(crop, "Mot Stimulant")
    tab.apply_icon(("sec", 0), crop)                                    # remplace l'icône du 1er secondaire
    tab.apply_icon("opening", crop, "Prévention")                       # ouvre un emplacement vide (sort d'ouverture)
    saved = sp.load_profiles()["Eniripsa"]
    used = {saved.primary.icon, saved.secondary[0].icon, saved.opening.icon}
    files = {p.stem for p in sp.spells_dir().glob("usr_eniripsa*.png")}
    check(nb.name == "Eniripsa" and saved.primary.name == "Mot Soignant" and len(saved.secondary) == 2
          and saved.secondary[0].name == "Pied du Sacrieur" and saved.secondary[1].name == "Mot Stimulant"
          and saved.opening.name == "Prévention" and len(used) == 3 and used <= files and cfg.spell_profile == "Eniripsa"
          and emitted, "nouveau profil : icônes remplacées, sort secondaire ajouté, ouverture créée, tout enregistré")
    tab._rename("primary", "Mot Soignant 2")
    tab._remove(("sec", 1))
    tab._remove("opening")
    saved = sp.load_profiles()["Eniripsa"]
    leftover = {p.stem for p in sp.spells_dir().glob("usr_eniripsa*.png")}
    check(saved.primary.name == "Mot Soignant 2" and len(saved.secondary) == 1 and saved.opening is None
          and leftover == {saved.primary.icon, saved.secondary[0].icon}, "renommer, retirer : fichiers inutiles supprimés")
    tab.create_profile("Copie", saved)
    c2 = sp.load_profiles()["Copie"]
    check(c2.primary.icon != saved.primary.icon and sp.icon_path(c2.primary.icon).exists()
          and np.array_equal(sp.load_icon_image(c2.primary.icon), sp.load_icon_image(saved.primary.icon)),
          "duplication : le profil copié a ses propres fichiers d'icônes")
    tab.current = "Eniripsa"
    tab.delete_profile()
    check("Eniripsa" not in sp.load_profiles() and "Copie" in sp.load_profiles() and sp.icon_path(c2.primary.icon).exists()
          and not sp.icon_path(saved.primary.icon).exists() and tab.current == sp.DEFAULT_PROFILE,
          "suppression d'un profil : ses icônes disparaissent, celles de la copie restent")
    dlg = CropDialog(None, None)
    dlg.load_image(cur)
    for k, v in zip(("x", "y", "w", "h"), (1613, 646, 55, 56)):
        dlg.spins[k].setValue(v)
    ok1 = dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled() and dlg.crop().shape[:2] == (56, 55)
    dlg.spins["w"].setValue(10)
    ok2 = not dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled()
    check(ok1 and ok2, "fenêtre de découpe : zone valide acceptée, zone trop petite refusée")

    # 5) moteur : un profil importé identique au profil intégré joue exactement pareil (même référence figée)
    with Pool(4) as p:
        bad = sum(p.map(_custom_vs_golden, [0]))
    check(bad == 0, "moteur avec un profil importé (icônes d'origine retirées) : 24 enchaînements d'écrans identiques à la référence")
    print("RÉSULTAT :", "tous les tests réussis" if not failures else f"{failures} échec(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
