"""Lancer les sorts autres que le sort principal : sort d'ouverture (1er tour, sur soi), sorts secondaires
(Pied du Sacrieur dans le profil intégré, au contact), et désélection de tout sort avant de finir le tour."""
import time

from core import input as inp
from core.combat import (find_enemies, find_me, range_fraction, range_mask, sort_by_distance, spell_selected)
from core.grid import grid_distance
from core.spells import Spell
from phases.base import Context
from phases.movement import move_closer, my_position, plan_move_green
from phases.primary_spell import deselect_primary
from phases.turn_helpers import book, find_icon, icon_hint, is_selected, save_diag, wait_confirm


# --- sorts secondaires (au contact) ----------------------------------------------------------------

def select_secondary(ctx: Context, spell: Spell):
    """Clique l'icône du sort secondaire et attend qu'il soit sélectionné. Retourne (sélectionné, icône)."""
    scene, (ox, oy) = ctx.capture.grab()
    icon = find_icon(ctx, scene, spell.icon)
    if not icon:
        ctx.log(f"⚠ Icône du {spell.name} introuvable ({spell.icon}.png dans {icon_hint(spell.icon)}).")
        return False, None
    inp.click(ox + icon.center[0], oy + icon.center[1])
    t0 = time.time()
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        if is_selected(ctx.capture.grab()[0], icon, spell.range_pixels):
            return True, icon
    ctx.log(f"Le {spell.name} ne s'affiche pas (plus assez de PA ?).")
    return False, icon


def deselect_secondary(ctx: Context, spell: Spell, icon) -> bool:
    """Reclique l'icône du sort secondaire pour le désélectionner (le jeu refuse de déplacer tant qu'il l'est)."""
    scene, (ox, oy) = ctx.capture.grab()
    ic = find_icon(ctx, scene, spell.icon) or icon
    inp.click(ox + ic.center[0], oy + ic.center[1])
    t0 = time.time()
    while time.time() - t0 < 1.8:
        time.sleep(0.3)
        s, _ = ctx.capture.grab()
        if not is_selected(s, find_icon(ctx, s, spell.icon) or ic, spell.range_pixels):
            return True
    ctx.log(f"⚠ Le {spell.name} reste sélectionné.")
    return False


def cast_secondary(ctx: Context, spell: Spell, should_stop=lambda: False) -> tuple[bool, bool]:
    """Sélectionne le sort secondaire, le lance sur l'adversaire à portée le plus proche et confirme.
    Si personne n'est à portée mais qu'il reste des PM (cases vertes de déplacement visibles), le personnage se
    rapproche de l'adversaire le plus proche puis relance le sort, au lieu de passer.
    Retourne (lancé, déplacé)."""
    cfg = ctx.config
    moved = False
    for attempt in (1, 2):                              # 2e passage = après un déplacement
        selected, icon = select_secondary(ctx, spell)
        if not selected:
            return False, moved
        scene, (ox, oy) = ctx.capture.grab()
        enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
        mask = range_mask(scene)
        origin = me.center if me else (ctx.me_hint or (enemies[0].center if enemies else None))
        in_range = [f for f in (sort_by_distance(enemies, origin) if origin else enemies)
                    if range_fraction(mask, f.center) >= cfg.range_min_fraction]
        ctx.log(f"{spell.name} : {len(enemies)} adversaire(s), {len(in_range)} à portée.")
        if in_range:
            for target in in_range[:3]:
                save_diag(ctx, scene, enemies, me, target, label="pied")
                inp.click(ox + target.cx, oy + target.cy - 4)
                ok, origin2 = wait_confirm(ctx)
                if ok:
                    inp.click(origin2[0] + ok.center[0], origin2[1] + ok.center[1])
                    ctx.log(f"✔ {spell.name} lancé en {target.center}.")
                    time.sleep(1.5)
                    return True, moved
                ctx.log("Pas de confirmation sur cette cible.")
                scene, (ox, oy) = ctx.capture.grab()
                if not is_selected(scene, find_icon(ctx, scene, spell.icon) or icon, spell.range_pixels):
                    break
            return False, moved
        # Personne au contact : on désélectionne le sort, puis on regarde s'il reste des PM pour se rapprocher.
        ctx.log(f"Personne au contact : pas de {spell.name} pour l'instant.")
        deselected = deselect_secondary(ctx, spell, icon)
        if attempt == 2 or not deselected or not enemies or not cfg.move_when_out_of_range or should_stop():
            return False, moved
        time.sleep(0.4)
        scene, _ = ctx.capture.grab()
        me = find_me(scene, ctx.me_hint) or me
        if me:
            ctx.me_hint = me.center
        pos = my_position(ctx, scene, me, range_mask(scene), enemies)
        if not pos:
            return False, moved
        _, green = plan_move_green(ctx, scene, enemies, pos)
        if not green:
            ctx.log("Plus de PM (aucune case verte de déplacement) : je ne bouge pas.")
            return False, moved
        ctx.log(f"Il me reste des PM ({len(green)} cases vertes) : je me rapproche pour lancer le {spell.name}.")
        ctx.select_unverified = False                   # le sort principal n'est plus sélectionné à ce stade
        if not move_closer(ctx, enemies, pos, should_stop):
            return False, moved
        moved = True
        time.sleep(0.8)                                 # laisse le personnage s'arrêter avant de resélectionner le sort
    return False, moved


# --- sort d'ouverture (1er tour) : se lance sur mon propre personnage ------------------------------

def settle_after_opening(ctx: Context, spell: Spell) -> None:
    """Après le sort d'ouverture : laisse l'écran se stabiliser et désélectionne ce sort s'il est resté sélectionné,
    sinon le clic suivant sur le sort principal peut être ignoré ou mal interprété (problème vu au 1er tour seulement)."""
    time.sleep(0.8)
    scene, (ox, oy) = ctx.capture.grab()
    icon = find_icon(ctx, scene, spell.icon)
    if icon and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
        ctx.log(f"Le {spell.name} est resté sélectionné : je le désélectionne avant {book(ctx).primary.name}.")
        inp.click(ox + icon.center[0], oy + icon.center[1])
        time.sleep(0.6)


def cast_opening(ctx: Context, spell: Spell) -> bool:
    """Sélectionne le sort d'ouverture, clique sur mon propre personnage, puis confirme (coche verte)."""
    unverified = False                                  # sélection jamais vue : on ne reclique pas sur l'icône
    for attempt in range(1, 3):
        scene, (ox, oy) = ctx.capture.grab()
        icon = find_icon(ctx, scene, spell.icon)
        if not icon:
            ctx.log(f"⚠ Icône du {spell.name} introuvable ({spell.icon}.png dans {icon_hint(spell.icon)}).")
            return False
        if not unverified and not spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
            inp.click(ox + icon.center[0], oy + icon.center[1])
            seen, t0 = False, time.time()
            while time.time() - t0 < 1.8:
                time.sleep(0.3)
                s, _ = ctx.capture.grab()
                ic = find_icon(ctx, s, spell.icon) or icon
                if spell_selected(s, ic.x, ic.y, ic.w, ic.h):
                    seen = True
                    break
            if not seen:
                ctx.log(f"Sélection du {spell.name} non vérifiée : j'essaie quand même, "
                        "la fenêtre de confirmation dira si ça marche.")
                unverified = True
        scene, (ox, oy) = ctx.capture.grab()
        enemies, me = find_enemies(scene), find_me(scene, ctx.me_hint)
        if me and ctx.me_hint and grid_distance(me.center, ctx.me_hint) > 2.0:
            # Au 1er tour on sait exactement où l'on est (la case du placement) : un anneau rouge repéré loin de là
            # (autre élément rouge de l'écran) n'est pas mon personnage, et on ne lui lance pas le sort.
            ctx.log(f"Anneau rouge repéré en {me.center}, loin de ma case de départ {ctx.me_hint} : je garde ma case de départ.")
            me = None
        if me:
            ctx.me_hint = me.center
        pos = my_position(ctx, scene, me, range_mask(scene), enemies)
        if not pos:
            ctx.log(f"⚠ Position de mon personnage inconnue : pas de {spell.name}.")
            break
        ctx.log(f"{spell.name.capitalize()} : clic sur mon personnage en {pos}.")
        inp.click(ox + pos[0], oy + pos[1])
        ok, origin2 = wait_confirm(ctx)
        if ok:
            inp.click(origin2[0] + ok.center[0], origin2[1] + ok.center[1])
            ctx.log(f"✔ {spell.name.capitalize()} lancé.")
            time.sleep(1.5)                             # animation
            settle_after_opening(ctx, spell)
            return True
        ctx.log(f"Pas de confirmation pour le {spell.name} (essai {attempt}/2).")
    scene, (ox, oy) = ctx.capture.grab()                # échec : on ne laisse pas le sort sélectionné
    icon = find_icon(ctx, scene, spell.icon)
    if icon and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):
        inp.click(ox + icon.center[0], oy + icon.center[1])
        time.sleep(0.5)
    return False


# --- fin de tour -----------------------------------------------------------------------------------

def release_spells(ctx: Context) -> None:
    """Avant de finir le tour : désélectionne tout sort resté sélectionné (secondaires, puis sort principal)."""
    b = book(ctx)
    scene, (ox, oy) = ctx.capture.grab()
    if find_icon(ctx, scene, "resultat_titre"):
        return
    for spell in b.secondary:
        icon2 = find_icon(ctx, scene, spell.icon)
        if icon2 and spell_selected(scene, icon2.x, icon2.y, icon2.w, icon2.h):
            ctx.log(f"Je désélectionne le {spell.name} avant de finir le tour.")
            inp.click(ox + icon2.center[0], oy + icon2.center[1])
            time.sleep(0.5)
    scene, _ = ctx.capture.grab()
    icon = find_icon(ctx, scene, b.primary.icon)
    if icon and spell_selected(scene, icon.x, icon.y, icon.w, icon.h):   # cadre orange vu = sort vraiment sélectionné
        ctx.log(f"Je désélectionne {b.primary.name} avant de finir le tour.")
        deselect_primary(ctx)
