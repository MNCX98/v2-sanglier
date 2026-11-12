"""Sort principal (Coagulation dans le profil intégré) : sélection, désélection, resélection après un déplacement."""
import time

from core import input as inp
from phases.base import Context
from phases.turn_helpers import book, find_icon, is_selected, save_select_diag


def select_primary(ctx: Context, force: bool = False) -> bool:
    """force=True : on SAIT que le sort est désélectionné (après un déplacement) → on clique l'icône sans condition."""
    spell = book(ctx).primary
    if force:
        ctx.select_unverified = False
    if ctx.select_unverified:
        return True                                   # supposé sélectionné : recliquer sur l'icône le désélectionnerait
    scene, (ox, oy) = ctx.capture.grab()
    icon = find_icon(ctx, scene, spell.icon)
    if not force and is_selected(scene, icon, spell.range_pixels):
        return True                                   # déjà sélectionné
    if not icon:
        ctx.log("⚠ Icône du sort introuvable.")
        return False
    inp.click(ox + icon.center[0], oy + icon.center[1])
    t0 = time.time()
    s = scene
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        s, _ = ctx.capture.grab()
        if is_selected(s, find_icon(ctx, s, spell.icon) or icon, spell.range_pixels):
            return True
    # Ni le cadre orange ni la zone de portée ne sont vus. Plutôt que de passer le tour, on tente quand même :
    # la fenêtre de confirmation (coche verte) n'apparaît que si le sort est vraiment sélectionné et la cible valide.
    save_select_diag(ctx, s, icon)
    ctx.select_unverified = True
    ctx.log("Sélection du sort non vérifiée : j'essaie quand même, la fenêtre de confirmation dira si ça marche.")
    return True


def deselect_primary(ctx: Context) -> bool:
    """Le jeu refuse de déplacer le personnage tant que le sort est sélectionné : on reclique dessus."""
    spell = book(ctx).primary
    scene, (ox, oy) = ctx.capture.grab()
    icon = find_icon(ctx, scene, spell.icon)
    if ctx.select_unverified:                          # sélection supposée mais jamais vue : un clic la défait
        ctx.select_unverified = False
        if icon:
            inp.click(ox + icon.center[0], oy + icon.center[1])
            time.sleep(0.6)
        return True
    if not is_selected(scene, icon, spell.range_pixels):
        return True
    if not icon:
        ctx.log("⚠ Icône du sort introuvable : impossible de désélectionner le sort.")
        return False
    inp.click(ox + icon.center[0], oy + icon.center[1])
    t0 = time.time()
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        s, _ = ctx.capture.grab()
        if not is_selected(s, find_icon(ctx, s, spell.icon) or icon, spell.range_pixels):
            return True
    ctx.log("⚠ Le sort reste sélectionné : pas de déplacement.")
    return False


def reselect_primary(ctx: Context) -> bool:
    """Après un déplacement, le sort est forcément désélectionné : on reclique sur le sort principal."""
    time.sleep(0.8)                                   # laisse le personnage s'arrêter et l'écran se stabiliser
    ctx.log(f"Je resélectionne {book(ctx).primary.name} après le déplacement.")
    return select_primary(ctx, force=True)
