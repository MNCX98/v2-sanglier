# DofusAuto 0.8.10

Projet Python Windows pour BlueStacks. Le détail des corrections 0.8.10 et des points restant à valider est dans [`CHANGELOG_CORRECTIONS.md`](CHANGELOG_CORRECTIONS.md).

## Pré-requis

- Windows 10/11
- Python 3.10 ou plus récent, avec le lanceur `py`
- BlueStacks et Dofus Touch

## Lancer depuis les sources

```bat
py -m pip install -r requirements.txt
py main.py
```

## Construire le .exe

Double-cliquer sur `build_windows.bat` depuis Windows, ou exécuter :

```bat
build_windows.bat
```

Le résultat est `dist\DofusAuto\DofusAuto.exe`. Conserver le dossier `dist\DofusAuto` entier : les assets et `config.json` sont nécessaires à côté de l'exécutable. Ne déplacer que le `.exe` seul ne suffit pas.

## Tests de reconnaissance

```bat
py tests\test_vision.py
```

Les tests utilisent les captures de `tests/fixtures`. Ils vérifient la reconnaissance sur ces images, pas les clics ni les transitions réelles de l'interface en direct.

## GitHub

Inclure les dossiers `assets`, `core`, `gui`, `phases`, `tests`, ainsi que `main.py`, `config.json`, `requirements.txt`, `README.md`, `LISEZMOI.txt`, `CHANGELOG_CORRECTIONS.md` et `build_windows.bat`. Les dossiers `dist`, `build`, `logs`, `captures` et `__pycache__` sont ignorés par Git.
