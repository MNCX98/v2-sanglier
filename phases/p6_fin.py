"""Phase 6 : fin du combat. Fermer la fenêtre « Résultat du combat » et attendre le retour à la carte."""
import time
from datetime import datetime

from core import input as inp
from core.imgio import save_image
from core.paths import logs_dir
from core.vision import scan
from phases.base import Context
from phases.p2_combat import find_ui

POPUP_MIN_GAP_PX = 40      # une croix « fermer » plus basse (ou plus haute) que le titre du résultat appartient à une autre fenêtre


def popup_close_buttons(ctx: Context, scene, title):
    """Croix de fermeture des fenêtres posées PAR-DESSUS le résultat du combat (montée de niveau…).
    La croix de la fenêtre de résultat est alignée sur son titre : toutes les autres sont celles d'une fenêtre ajoutée."""
    templates = [t for t in ctx.ui_templates if t.variant == "fermer_resultat"]
    if not templates or title is None:
        return []
    found = scan(scene, templates, ctx.config.ui_threshold).detections
    return [d for d in found if abs(d.center[1] - title.center[1]) > POPUP_MIN_GAP_PX]


def close_popups(ctx: Context, should_stop, max_popups: int = 4) -> int:
    """Ferme les fenêtres ajoutées au-dessus du résultat (elles bloquent la croix de la fenêtre de résultat)."""
    closed = 0
    while closed < max_popups and not should_stop():
        scene, (ox, oy) = ctx.capture.grab()
        popups = popup_close_buttons(ctx, scene, find_ui(ctx, scene, "resultat_titre"))
        if not popups:
            break
        btn = max(popups, key=lambda d: d.score)
        ctx.log("Une fenêtre (montée de niveau ?) est ouverte par-dessus le résultat : je la ferme.")
        inp.click(ox + btn.center[0], oy + btn.center[1])
        closed += 1
        time.sleep(1.2)                                    # laisse la fenêtre se fermer (ou la suivante apparaître)
    return closed


def close_stray_popups(ctx: Context, should_stop) -> bool:
    """Sur la carte (aucune fenêtre de résultat) : ferme une fenêtre restée ouverte ou arrivée en retard
    (montée de niveau qui s'affiche quelques secondes après la fin du combat). True si une fenêtre a été fermée.
    La croix verte n'existe ni dans l'interface normale de la carte, ni en combat : toute croix vue ici est une fenêtre."""
    scene, (ox, oy) = ctx.capture.grab()
    if find_ui(ctx, scene, "resultat_titre"):
        return False                                       # la fenêtre de résultat est gérée par close_result
    templates = [t for t in ctx.ui_templates if t.variant == "fermer_resultat"]
    if not templates:
        return False
    found = scan(scene, templates, ctx.config.ui_threshold).detections
    if not found or should_stop():
        return False
    btn = max(found, key=lambda d: d.score)
    ctx.log("Une fenêtre est restée ouverte ou arrivée en retard (montée de niveau ?) : je la ferme.")
    inp.click(ox + btn.center[0], oy + btn.center[1])
    time.sleep(1.2)
    return True


def close_result(ctx: Context, should_stop) -> bool:
    """Clique sur la croix de la fenêtre de résultat, puis attend le retour à l'écran de recherche."""
    ctx.log("Phase 6 : fermeture de la fenêtre de résultat…")
    closed = False
    for attempt in range(3):
        close_popups(ctx, should_stop)
        scene, (ox, oy) = ctx.capture.grab()
        title = find_ui(ctx, scene, "resultat_titre")
        if not title:
            closed = True                                  # déjà fermée
            break
        templates = [t for t in ctx.ui_templates if t.variant == "fermer_resultat"]
        crosses = sorted(scan(scene, templates, ctx.config.ui_threshold).detections, key=lambda d: -d.score) if templates else []
        if crosses:
            # essai 1 : la meilleure croix ; essai 2 : la suivante (si une autre fenêtre bloque la première) ; essai 3 : la meilleure
            btn = crosses[1] if (attempt == 1 and len(crosses) > 1) else crosses[0]
            inp.click(ox + btn.center[0], oy + btn.center[1])
        else:
            ctx.log("⚠ Croix de fermeture introuvable.")
        t0 = time.time()
        while time.time() - t0 < 3 and not should_stop():
            time.sleep(0.4)
            s, _ = ctx.capture.grab()
            if not find_ui(ctx, s, "resultat_titre"):
                closed = True
                break
        if closed or should_stop():
            break
        ctx.log(f"La fenêtre est toujours là (essai {attempt + 1}/3).")
    if not closed:
        ctx.log("⚠ Impossible de fermer la fenêtre de résultat.")
        try:                                               # capture automatique : montre ce qui bloque
            scene, _ = ctx.capture.grab()
            path = logs_dir() / f"fermeture_impossible_{datetime.now():%Y%m%d_%H%M%S}.png"
            save_image(path, scene)
            ctx.log(f"Capture de l'écran enregistrée : {path}")
        except Exception:
            pass
        return False
    # Retour à la carte : plus de fenêtre de résultat, plus de grille de sorts de combat
    t0 = time.time()
    while time.time() - t0 < 10 and not should_stop():
        s, _ = ctx.capture.grab()
        if not find_ui(ctx, s, "resultat_titre") and not find_ui(ctx, s, "sort_attaque"):
            time.sleep(1.5)                                # le personnage réapparaît sur la carte
            ctx.log("Retour à la carte.")
            return True
        time.sleep(0.5)
    ctx.log("⚠ Le retour à la carte n'est pas confirmé.")
    return False
