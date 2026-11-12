"""Lance toute la batterie de vérification. Options : --fast (saute les deux bancs sur images réelles, ~5 min)."""
import subprocess
import sys
from pathlib import Path

T = Path(__file__).resolve().parent
STEPS = [("démarrage", ["test_imports.py"], False), ("reconnaissance d'images", ["test_vision.py"], False),
         ("profils de sorts", ["test_spells.py"], False), ("tours : monde simulé", ["turn_model_harness.py", "3000"], False),
         ("tours : écrans réels", ["turn_harness.py"], True), ("fonctions déplacées", ["function_harness.py", "14"], True)]


def main():
    fast = "--fast" in sys.argv
    bad = 0
    for name, cmd, slow in STEPS:
        if fast and slow:
            print(f"-- {name} : sauté (--fast)")
            continue
        print(f"== {name}")
        r = subprocess.run([sys.executable, str(T / cmd[0])] + cmd[1:], cwd=T.parent)
        bad += r.returncode != 0
    print("\nBATTERIE :", "tout est OK" if not bad else f"{bad} étape(s) en échec")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
