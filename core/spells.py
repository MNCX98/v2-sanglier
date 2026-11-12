"""Sorts joués en combat : profils (une classe, un jeu de sorts) et icônes importées depuis des captures d'écran.

Un profil comporte trois emplacements :
  - ouverture   : sort lancé sur soi au 1er tour seulement (facultatif) ;
  - principal   : sort lancé sur l'adversaire le plus proche à portée, plusieurs fois par tour (« Lancers par tour ») ;
  - secondaires : sorts lancés ensuite, sur un adversaire au contact (le personnage se rapproche s'il lui reste des PM).

Le profil intégré reproduit exactement le comportement historique (Coagulation + Pied du Sacrieur, sort d'ouverture).
Les profils créés par l'utilisateur sont dans spells/profiles.json ; leurs icônes (PNG découpés dans une capture)
sont dans le même dossier. Une icône est désignée par son nom de fichier sans extension.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from core.paths import spells_dir, spells_profiles_path

DEFAULT_PROFILE = "Sacrieur : Coagulation + Pied du Sacrieur (intégré)"
BIG_RANGE_PIXELS = 3000          # zone de portée assez grande pour prouver qu'un sort à longue portée est sélectionné
SMALL_RANGE_PIXELS = 800         # idem pour un sort de courte portée (peu de couleur à l'écran)
USER_ICON_PREFIX = "usr_"        # les icônes importées ne peuvent jamais porter le nom d'une image intégrée


@dataclass
class Spell:
    name: str                                   # nom affiché dans le journal
    icon: str                                   # nom de l'image (sans .png) retrouvée à l'écran
    range_pixels: int = BIG_RANGE_PIXELS        # zone de portée minimale pour considérer le sort « sélectionné »


@dataclass
class SpellBook:
    name: str
    opening: Spell | None
    primary: Spell
    secondary: list[Spell] = field(default_factory=list)
    builtin: bool = False


def default_spellbook() -> SpellBook:
    """Le comportement historique : sort d'ouverture, Coagulation, puis Pied du Sacrieur."""
    return SpellBook(
        name=DEFAULT_PROFILE,
        opening=Spell("sort d'ouverture", "sort_debut_combat"),
        primary=Spell("Coagulation", "sort_attaque", BIG_RANGE_PIXELS),
        secondary=[Spell("Pied du Sacrieur", "pied_du_sacrieur", SMALL_RANGE_PIXELS)],
        builtin=True)


# --- enregistrement --------------------------------------------------------------------------------

def _spell_to_dict(s: Spell | None):
    return None if s is None else {"name": s.name, "icon": s.icon, "range_pixels": s.range_pixels}


def _spell_from_dict(d, default_range: int) -> Spell | None:
    if not d or not d.get("icon"):
        return None
    return Spell(str(d.get("name") or d["icon"]), str(d["icon"]), int(d.get("range_pixels", default_range)))


def book_to_dict(b: SpellBook) -> dict:
    return {"opening": _spell_to_dict(b.opening), "primary": _spell_to_dict(b.primary),
            "secondary": [_spell_to_dict(s) for s in b.secondary]}


def book_from_dict(name: str, d: dict) -> SpellBook | None:
    primary = _spell_from_dict(d.get("primary"), BIG_RANGE_PIXELS)
    if primary is None:
        return None                              # un profil sans sort principal n'a pas de sens
    secondary = [s for s in (_spell_from_dict(x, SMALL_RANGE_PIXELS) for x in d.get("secondary", [])) if s]
    return SpellBook(name, _spell_from_dict(d.get("opening"), BIG_RANGE_PIXELS), primary, secondary)


def load_profiles(path: Path | None = None) -> dict[str, SpellBook]:
    """Profils de l'utilisateur (le profil intégré n'est pas stocké). Un fichier absent ou abîmé donne {}."""
    try:
        data = json.loads((path or spells_profiles_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, SpellBook] = {}
    for name, d in (data.get("profiles", {}) if isinstance(data, dict) else {}).items():
        try:
            b = book_from_dict(name, d)
        except (TypeError, ValueError, KeyError, AttributeError):
            b = None
        if b and name != DEFAULT_PROFILE:
            out[name] = b
    return out


def save_profiles(profiles: dict[str, SpellBook], path: Path | None = None) -> None:
    data = {"profiles": {n: book_to_dict(b) for n, b in profiles.items() if n != DEFAULT_PROFILE}}
    (path or spells_profiles_path()).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def profile_names(profiles: dict[str, SpellBook] | None = None) -> list[str]:
    return [DEFAULT_PROFILE] + sorted((load_profiles() if profiles is None else profiles))


def resolve_spellbook(name: str) -> SpellBook:
    """Le profil demandé, ou le profil intégré si le nom est vide, inconnu ou si le profil est inutilisable."""
    if name and name != DEFAULT_PROFILE:
        b = load_profiles().get(name)
        if b:
            return b
    return default_spellbook()


# --- icônes -----------------------------------------------------------------------------------------

def slug(text: str) -> str:
    """Nom de fichier sûr (ASCII, sans espaces) tiré d'un nom de profil ou de sort."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return t or "sort"


def new_icon_name(profile: str, slot: str, existing: set[str] | None = None) -> str:
    """Nom d'icône unique (usr_<profil>_<emplacement>[_n]), jamais celui d'une image intégrée."""
    base = f"{USER_ICON_PREFIX}{slug(profile)}_{slug(slot)}"
    taken = existing if existing is not None else {p.stem for p in spells_dir().glob("*.png")}
    name, n = base, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    return name


def icon_path(icon: str) -> Path:
    return spells_dir() / f"{icon}.png"


def save_icon(icon: str, image: np.ndarray) -> Path:
    path = icon_path(icon)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Impossible d'encoder l'icône.")
    path.write_bytes(buf.tobytes())
    return path


def read_icon(icon: str) -> np.ndarray | None:
    try:
        return cv2.imdecode(np.frombuffer(icon_path(icon).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None


def delete_icon(icon: str) -> None:
    if icon.startswith(USER_ICON_PREFIX):             # on ne supprime jamais une image intégrée
        try:
            icon_path(icon).unlink()
        except OSError:
            pass


def unused_icons(profiles: dict[str, SpellBook]) -> list[str]:
    used = {s.icon for b in profiles.values() for s in ([b.opening] if b.opening else []) + [b.primary] + b.secondary}
    return [p.stem for p in spells_dir().glob(f"{USER_ICON_PREFIX}*.png") if p.stem not in used]


# --- contrôle d'une icône découpée dans une capture ------------------------------------------------------

MIN_ICON_SIDE, MAX_ICON_SIDE = 24, 140


@dataclass
class IconCheck:
    errors: list[str] = field(default_factory=list)       # bloquants
    warnings: list[str] = field(default_factory=list)     # à confirmer
    score: float = 0.0                                    # ressemblance avec la capture à l'endroit découpé (≈1)
    duplicates: int = 0                                   # autres endroits de la capture qui lui ressemblent

    @property
    def ok(self) -> bool:
        return not self.errors


def analyze_icon(source: np.ndarray, rect: tuple[int, int, int, int]) -> IconCheck:
    """Contrôle la qualité d'une icône découpée (x, y, largeur, hauteur) dans la capture `source` (BGR) :
    taille raisonnable, image pas trop uniforme, sort non sélectionné (pas de cadre orange autour), et image
    qui ne se retrouve pas ailleurs dans la capture (sinon le programme pourrait cliquer le mauvais sort)."""
    from core.combat import spell_border_pixels
    chk = IconCheck()
    x, y, w, h = rect
    H, W = source.shape[:2]
    if w < MIN_ICON_SIDE or h < MIN_ICON_SIDE:
        chk.errors.append(f"Zone trop petite ({w}×{h} px) : au moins {MIN_ICON_SIDE} px de côté.")
    if w > MAX_ICON_SIDE or h > MAX_ICON_SIDE:
        chk.errors.append(f"Zone trop grande ({w}×{h} px) : entoure seulement l'icône (au plus {MAX_ICON_SIDE} px).")
    if x < 0 or y < 0 or x + w > W or y + h > H:
        chk.errors.append("La zone dépasse de la capture.")
    if chk.errors:
        return chk
    crop = source[y:y + h, x:x + w]
    if float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).std()) < 12:
        chk.errors.append("Zone trop uniforme : elle ne contient pas l'icône d'un sort.")
        return chk
    if spell_border_pixels(source, x, y, w, h) >= 150:
        chk.warnings.append("Ce sort semble SÉLECTIONNÉ (cadre orange) : le programme le cherche non sélectionné. "
                            "Reprends une capture sans sélectionner le sort.")
    res = cv2.matchTemplate(source, crop, cv2.TM_CCOEFF_NORMED)
    chk.score = float(res[y, x]) if 0 <= y < res.shape[0] and 0 <= x < res.shape[1] else float(res.max())
    ys, xs = np.where(res >= 0.90)
    others = [(px, py) for px, py in zip(xs, ys) if abs(px - x) > w // 2 or abs(py - y) > h // 2]
    kept: list[tuple[int, int]] = []
    for px, py in others:                                  # un seul point par endroit
        if all(abs(px - kx) > w // 2 or abs(py - ky) > h // 2 for kx, ky in kept):
            kept.append((px, py))
    chk.duplicates = len(kept)
    if kept:
        chk.warnings.append(f"Cette image ressemble à {len(kept)} autre(s) endroit(s) de la capture : "
                            "le programme pourrait confondre deux sorts. Découpe plus précisément.")
    return chk


def find_icon_file(icon: str) -> Path | None:
    """Fichier d'une icône : celles importées (dossier spells) puis celles intégrées (assets/ui)."""
    from core.paths import ui_dir
    for d in (spells_dir(), ui_dir()):
        p = d / f"{icon}.png"
        if p.is_file():
            return p
    return None


def load_icon_image(icon: str) -> np.ndarray | None:
    p = find_icon_file(icon)
    if p is None:
        return None
    try:
        return cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None


def copy_book(src: SpellBook, new_name: str) -> SpellBook:
    """Copie d'un profil sous un autre nom ; les icônes importées sont dupliquées (chaque profil a les siennes)."""
    taken = {p.stem for p in spells_dir().glob("*.png")}

    def dup(s: Spell | None, slot: str) -> Spell | None:
        if s is None:
            return None
        icon = s.icon
        if icon.startswith(USER_ICON_PREFIX):
            img = load_icon_image(icon)
            if img is not None:
                icon = new_icon_name(new_name, slot, taken)
                taken.add(icon)
                save_icon(icon, img)
        return Spell(s.name, icon, s.range_pixels)

    return SpellBook(new_name, dup(src.opening, "ouverture"), dup(src.primary, "principal"),
                     [dup(s, f"secondaire{i + 1}") for i, s in enumerate(src.secondary)])
