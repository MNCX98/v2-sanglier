"""Inventaire plein : transférer les objets dans la monture.

Déclenchement : le badge rouge « ! » sur l'icône de l'inventaire (carte, aucune fenêtre ouverte) ou le message
« Inventaire plein… » de la fenêtre « Attention ! ».

Séquence (celle que le joueur fait à la main) :
  1. fermer les fenêtres ouvertes (croix vertes) ;
  2. agrandir le menu du bas si besoin (petit triangle vert en bas à gauche du menu) ;
  3. clic sur l'icône de la monture, puis sur le bouton « sac » de sa fenêtre (inventaire de la monture) ;
  4. clic sur la flèche verte ◀ de la fenêtre Inventaire, puis sur « Transférer les objets visibles » (ou « tous ») ;
  5. fermer les fenêtres, refermer le menu si on l'a agrandi, vérifier que le badge a disparu."""
import time

import cv2
import numpy as np

from core import input as inp
from core.paths import app_dir
from core.vision import scan
from phases.base import Context

BADGE = "inv_badge"                  # petit rond rouge « ! » sur l'icône de l'inventaire (assets/ui)
MOUNT_ICON = "inv_monture"           # icône de la monture dans le menu agrandi
MOUNT_BAG = "inv_monture_sac"        # bouton « sac » dans la fenêtre de la monture
TRIANGLE = "inv_triangle"            # petit triangle vert (les trois coins de l'interface se ressemblent : on prend le plus bas)
CLOSE = "fermer_resultat"            # croix verte des fenêtres

BADGE_MIN = 0.92
ICON_MIN = 0.90
TEXT_MIN = 0.85
INV_ARROW_FROM_TITLE = (-171, 72)    # flèche ◀ de la fenêtre Inventaire, par rapport au centre de son titre
MOUNT_ARROW_FROM_TITLE = (224, 72)   # flèche ▶ de la fenêtre Monture (essai de secours)

_texts: dict[str, np.ndarray | None] = {}


def _white(img: np.ndarray) -> np.ndarray:
    """Masque des pixels blancs : le texte se reconnaît sur ce masque, quel que soit le fond (carte visible à travers)."""
    return ((img.min(axis=2) > 185).astype(np.uint8)) * 255


def _text_template(name: str):
    if name not in _texts:
        try:
            img = cv2.imdecode(np.fromfile(str(app_dir() / "assets" / "texte" / f"{name}.png"), np.uint8), cv2.IMREAD_COLOR)
        except OSError:
            img = None
        _texts[name] = None if img is None else _white(img)
    return _texts[name]


def find_text(scene: np.ndarray, name: str, threshold: float = TEXT_MIN):
    """Cherche un texte (image dans assets/texte). Retourne ((x, y) du centre, score) ou None."""
    tpl = _text_template(name)
    if tpl is None or scene.shape[0] < tpl.shape[0] or scene.shape[1] < tpl.shape[1]:
        return None
    res = cv2.matchTemplate(_white(scene), tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < threshold:
        return None
    return (loc[0] + tpl.shape[1] // 2, loc[1] + tpl.shape[0] // 2), float(score)


def find_icons(ctx: Context, scene: np.ndarray, variant: str, threshold: float = ICON_MIN):
    templates = [t for t in ctx.ui_templates if t.variant == variant]
    return scan(scene, templates, threshold).detections if templates else []


def inventory_full(ctx: Context, scene: np.ndarray) -> bool:
    """Badge rouge sur l'icône de l'inventaire, ou message « Inventaire plein » dans une fenêtre d'avertissement.
    Le badge n'est cherché que sans fenêtre ouverte : la barre des pods d'une fenêtre porte un repère rouge semblable."""
    windows = find_icons(ctx, scene, CLOSE, 0.85)
    if windows:
        return find_text(scene, "inv_plein_texte") is not None
    return bool(find_icons(ctx, scene, BADGE, BADGE_MIN))


def _sleep(seconds: float, should_stop) -> None:
    end = time.time() + seconds
    while time.time() < end and not should_stop():
        time.sleep(0.05)


def _click(ctx: Context, origin, point) -> None:
    inp.click(origin[0] + point[0], origin[1] + point[1])


def _wait(ctx: Context, finder, should_stop, timeout: float = 4.0):
    """Attend qu'un élément apparaisse. Retourne (résultat, origine de la fenêtre) ou (None, origine)."""
    end, origin = time.time() + timeout, (0, 0)
    while not should_stop():
        scene, origin = ctx.capture.grab()
        found = finder(scene)
        if found:
            return found, origin
        if time.time() >= end:
            break
        time.sleep(0.3)
    return None, origin


def _wait_stable(ctx: Context, finder, pos_of, should_stop, timeout: float = 4.0, settle: float = 0.4, tol: int = 3):
    """Comme _wait, mais n'accepte l'élément que lorsqu'il est apparu ET qu'il ne bouge plus (au moins `settle`
    secondes à la même place). Un menu ou une fenêtre qui s'ouvre glisse pendant son animation : cliquer dès la
    première détection tombe à côté, sur le bouton voisin (ex. « Compagnon » au lieu de la monture).
    À l'expiration du délai, retourne le dernier élément vu s'il y en a un (mieux que rien), sinon None."""
    end, origin = time.time() + timeout, (0, 0)
    last_pos, since, last_found = None, 0.0, None
    while not should_stop():
        scene, origin = ctx.capture.grab()
        found = finder(scene)
        now = time.time()
        if found:
            pos = pos_of(found)
            moved = last_pos is None or abs(pos[0] - last_pos[0]) > tol or abs(pos[1] - last_pos[1]) > tol
            if moved:
                last_pos, since = pos, now
            elif now - since >= settle:
                return found, origin
            last_found = found
        else:
            last_pos, last_found = None, None
        if now >= end:
            break
        time.sleep(0.12)
    return last_found, origin


def close_windows(ctx: Context, should_stop, max_windows: int = 8) -> int:
    """Ferme toutes les fenêtres à croix verte (monture, inventaire, avertissement…)."""
    closed = 0
    while closed < max_windows and not should_stop():
        scene, origin = ctx.capture.grab()
        crosses = find_icons(ctx, scene, CLOSE, 0.85)
        if not crosses:
            break
        _click(ctx, origin, max(crosses, key=lambda d: d.score).center)
        closed += 1
        _sleep(0.9, should_stop)
    return closed


def _bottom_triangle(ctx: Context, scene: np.ndarray):
    triangles = find_icons(ctx, scene, TRIANGLE)
    return max(triangles, key=lambda d: d.center[1]) if triangles else None


def unload_to_mount(ctx: Context, should_stop) -> str:
    """Transfère les objets dans la monture. Retourne 'ok', 'full' (encore plein : monture pleine ?) ou 'fail'."""
    cfg = ctx.config
    option = "inv_menu_tous" if cfg.unload_mode == "tous" else "inv_menu_visibles"
    ctx.log("Inventaire plein : je transfère les objets dans la monture.")
    close_windows(ctx, should_stop)

    # 1) icône de la monture (menu du bas agrandi)
    find_mount = lambda s: next(iter(find_icons(ctx, s, MOUNT_ICON)), None)
    mount, origin = _wait_stable(ctx, find_mount, lambda d: d.center, should_stop, 1.2)
    expanded_by_us = False
    if not mount:
        scene, origin = ctx.capture.grab()
        tri = _bottom_triangle(ctx, scene)
        if not tri:
            ctx.log("⚠ Menu du bas introuvable (triangle vert) : transfert impossible.")
            return "fail"
        ctx.log("J'agrandis le menu du bas.")
        _click(ctx, origin, tri.center)
        expanded_by_us = True
        _sleep(0.9, should_stop)                           # animation de dépliage : les boutons glissent encore
        mount, origin = _wait_stable(ctx, find_mount, lambda d: d.center, should_stop, 3.0)
        if not mount:
            ctx.log("⚠ Icône de la monture introuvable après avoir agrandi le menu.")
            return "fail"

    def finish(result: str) -> str:
        close_windows(ctx, should_stop)
        if expanded_by_us:
            scene, org = ctx.capture.grab()
            tri = _bottom_triangle(ctx, scene)
            if tri:
                _click(ctx, org, tri.center)               # on remet le menu comme on l'a trouvé
                _sleep(0.6, should_stop)
        return result

    # 2) fenêtre de la monture, puis son inventaire (bouton « sac »)
    find_bag = lambda s: next(iter(find_icons(ctx, s, MOUNT_BAG)), None)
    bag = None
    for attempt in (1, 2):
        ctx.log("J'ouvre la monture." if attempt == 1 else "Nouvel essai : j'ouvre la monture.")
        _click(ctx, origin, mount.center)
        bag, origin = _wait_stable(ctx, find_bag, lambda d: d.center, should_stop, 4.0)
        if bag or attempt == 2 or should_stop():
            break
        # une autre fenêtre s'est probablement ouverte (ex. « Compagnon ») : on la ferme et on recommence
        ctx.log("⚠ Bouton « inventaire de la monture » introuvable : je ferme la fenêtre ouverte et je réessaie.")
        close_windows(ctx, should_stop)
        _sleep(0.6, should_stop)
        mount, origin = _wait_stable(ctx, find_mount, lambda d: d.center, should_stop, 3.0)
        if not mount:
            break
    if not bag:
        ctx.log("⚠ Bouton « inventaire de la monture » introuvable.")
        return finish("fail")
    _click(ctx, origin, bag.center)

    # 3) fenêtres Monture + Inventaire ouvertes : flèche verte, puis le choix de transfert
    def both_titles(scene):
        inv, mon = find_text(scene, "inv_titre_inventaire"), find_text(scene, "inv_titre_monture")
        return (inv, mon) if inv and mon else None

    titles, origin = _wait_stable(ctx, both_titles, lambda t: t[0][0], should_stop, 4.0)
    if not titles:
        ctx.log("⚠ Les fenêtres Monture et Inventaire ne se sont pas ouvertes.")
        return finish("fail")
    (inv_title, _), (mon_title, _) = titles
    chosen = None
    for label, title, off in (("Inventaire", inv_title, INV_ARROW_FROM_TITLE), ("Monture", mon_title, MOUNT_ARROW_FROM_TITLE)):
        ctx.log(f"Clic sur la flèche verte de la fenêtre {label}.")
        _click(ctx, origin, (title[0] + off[0], title[1] + off[1]))
        chosen, origin = _wait(ctx, lambda s: find_text(s, option), should_stop, 2.5)
        if chosen:
            break
    if not chosen:
        ctx.log("⚠ Le menu de transfert n'est pas apparu.")
        return finish("fail")
    label = "tous les objets" if cfg.unload_mode == "tous" else "des objets visibles"
    ctx.log(f"Transfert {'de ' if cfg.unload_mode == 'tous' else ''}{label}.")
    _click(ctx, origin, chosen[0])
    _sleep(2.5, should_stop)                                   # temps du transfert

    # 4) fermeture, puis vérification : le badge d'inventaire plein doit avoir disparu
    result = finish("ok")
    scene, _ = ctx.capture.grab()
    if inventory_full(ctx, scene):
        ctx.log("⚠ L'inventaire est toujours plein après le transfert (monture pleine ?).")
        return "full"
    ctx.log("✔ Objets transférés dans la monture.")
    return result
