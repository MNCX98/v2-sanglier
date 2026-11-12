"""Petites fonctions communes aux étapes d'un tour : recherche d'icônes, fenêtre de confirmation, diagnostics."""
import time
from datetime import datetime

import cv2

from core.combat import range_mask, range_visible, spell_border_pixels, spell_selected
from core.imgio import save_image
from core.paths import logs_dir
from core.spells import SpellBook, default_spellbook
from phases.base import Context
from phases.p2_combat import find_ui


def book(ctx: Context) -> SpellBook:
    """Les sorts à jouer (le profil intégré si aucun n'a été choisi)."""
    return ctx.spells or default_spellbook()


def icon_hint(icon: str) -> str:
    """Où se trouve le fichier d'une icône (pour les messages d'erreur)."""
    return "spells" if icon.startswith("usr_") else "assets/ui"


def find_icon(ctx: Context, scene, name: str):
    return find_ui(ctx, scene, name)


def save_diag(ctx: Context, scene, enemies, me, target=None, label="tour"):
    if not ctx.config.save_diagnostics:
        return
    out = scene.copy()
    for f in enemies:
        cv2.circle(out, f.center, 8, (0, 255, 255), -1)
    if me:
        cv2.circle(out, me.center, 10, (0, 0, 255), -1)
    if target:
        cv2.circle(out, target.center, 22, (0, 255, 0), 3)
    save_image(logs_dir() / f"{label}_{datetime.now():%Y%m%d_%H%M%S_%f}.png", out)


def wait_confirm(ctx: Context, timeout: float = 1.6):
    t0 = time.time()
    while time.time() - t0 < timeout:
        scene, origin = ctx.capture.grab()
        d = find_icon(ctx, scene, "valider")
        if d:
            return d, origin
        time.sleep(0.2)
    return None, None


def is_selected(scene, icon, min_pixels: int = 3000) -> bool:
    """Sort sélectionné ? Cadre orange autour de son icône (sûr sur toutes les cartes) ou zone de portée bleue."""
    if icon is not None and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
        return True
    return range_visible(scene, min_pixels)


def save_select_diag(ctx: Context, scene, icon) -> None:
    """Quand la sélection du sort ne peut pas être vérifiée : chiffres dans le journal + capture annotée."""
    n = spell_border_pixels(scene, icon.x, icon.y, icon.w, icon.h) if icon else -1
    m = int(range_mask(scene).sum())
    where = f"icône en ({icon.x}, {icon.y}), score {icon.score:.2f}" if icon else "icône introuvable"
    ctx.log(f"Diagnostic de sélection : cadre orange {n} px (150 attendus si le sort est sélectionné), "
            f"bleu de portée {m} px (3000 attendus), {where}.")
    if ctx.config.save_diagnostics:
        out = scene.copy()
        if icon:
            cv2.rectangle(out, (icon.x - 7, icon.y - 7), (icon.x + icon.w + 7, icon.y + icon.h + 7), (0, 255, 255), 2)
        save_image(logs_dir() / f"selection_sort_{datetime.now():%Y%m%d_%H%M%S}.png", out)
