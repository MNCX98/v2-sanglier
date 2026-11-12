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


def _text_template(name: str, scale: float = 1.0):
    """Masque blanc du texte (assets/texte) à l'échelle demandée (mis en cache). Pour une autre échelle, on remet
    d'abord l'image COULEUR à l'échelle, puis on en tire le masque blanc, comme pour l'écran : réduire directement le
    masque ferait disparaître les traits fins (le texte du menu n'a que 1 à 2 pixels d'épaisseur)."""
    key = (name, round(scale, 3))
    if key not in _texts:
        if (name, "img") not in _texts:
            try:
                _texts[(name, "img")] = cv2.imdecode(np.fromfile(str(app_dir() / "assets" / "texte" / f"{name}.png"),
                                                                 np.uint8), cv2.IMREAD_COLOR)
            except OSError:
                _texts[(name, "img")] = None
        img = _texts[(name, "img")]
        if img is None:
            _texts[key] = None
        else:
            if abs(scale - 1.0) > 1e-6:
                img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            _texts[key] = _white(img)
    return _texts[key]


def find_text(scene: np.ndarray, name: str, threshold: float = TEXT_MIN, scale: float = 1.0, white=None):
    """Cherche un texte (image dans assets/texte) à l'échelle donnée.
    Retourne ((x, y) du centre, score) ou None."""
    tpl = _text_template(name, scale)
    if tpl is None or scene.shape[0] < tpl.shape[0] or scene.shape[1] < tpl.shape[1]:
        return None
    res = cv2.matchTemplate(_white(scene) if white is None else white, tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < threshold:
        return None
    return (loc[0] + tpl.shape[1] // 2, loc[1] + tpl.shape[0] // 2), float(score)


TEXT_SCALES = tuple(round(0.90 + 0.01 * i, 2) for i in range(21))      # 0,90 … 1,10 : adaptation d'échelle imparfaite


def find_text_any_scale(scene: np.ndarray, name: str, threshold: float = TEXT_MIN, around: float | None = None, white=None):
    """Comme find_text, mais à plusieurs échelles : un texte fin n'est reconnu qu'à 1 % près (à 1 % d'écart son score
    tombe de 1,00 à 0,5), or l'adaptation automatique à la taille du jeu n'est jamais parfaite partout.
    Essaie d'abord autour de `around` (échelle déjà connue), puis toute la plage.
    Retourne ((x, y) du centre, score, échelle du texte trouvé) ou None."""
    white = _white(scene) if white is None else white
    tried: set[float] = set()
    ranges = []
    if around is not None:
        ranges.append(tuple(round(around + d, 2) for d in (0, -0.01, 0.01, -0.02, 0.02)))
    ranges.append(TEXT_SCALES)
    for scales in ranges:
        best = None
        for sc in scales:
            if sc in tried:
                continue
            tried.add(sc)
            r = find_text(scene, name, 0.0, sc, white)
            if r and (best is None or r[1] > best[1]):
                best = (r[0], r[1], sc)
        if best and best[1] >= threshold:
            return best
    return None


MENU_LINE_MIN = 0.50                 # score minimal de chaque ligne du menu quand les DEUX sont retrouvées, bien placées
MENU_DY, MENU_DX = 43, 15           # « …les objets visibles » est 43 px plus bas et 15 px plus à droite que « …tous les objets »


def _find_text_near(white: np.ndarray, name: str, scale: float, center: tuple[float, float], radius: int = 14):
    """Meilleure correspondance d'un texte dans un petit rectangle autour de `center` : ((x, y), score) ou None."""
    tpl = _text_template(name, scale)
    if tpl is None:
        return None
    th, tw = tpl.shape[:2]
    x0, y0 = max(0, int(center[0] - tw / 2 - radius)), max(0, int(center[1] - th / 2 - radius))
    x1, y1 = min(white.shape[1], int(center[0] + tw / 2 + radius)), min(white.shape[0], int(center[1] + th / 2 + radius))
    if x1 - x0 < tw or y1 - y0 < th:
        return None
    _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(white[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED))
    return (x0 + loc[0] + tw // 2, y0 + loc[1] + th // 2), float(score)


def find_transfer_option(scene: np.ndarray, option: str, around: float | None = None):
    """Retrouve la ligne `option` du menu de transfert, même si l'échelle de l'écran est un peu fausse.
    Un texte fin est peu fiable seul : on exige soit un score élevé (0,85), soit les deux lignes « tous les objets » et
    « les objets visibles » retrouvées à la même échelle et à la bonne distance l'une de l'autre.
    Retourne ((x, y) du centre, score, échelle) ou None."""
    white = _white(scene)
    ranges = []
    if around is not None:
        ranges.append(tuple(round(around + d, 2) for d in (0, -0.01, 0.01, -0.02, 0.02)))
    ranges.append(TEXT_SCALES)
    done: set[float] = set()
    for scales in ranges:
        best = None
        for sc in scales:
            if sc in done:
                continue
            done.add(sc)
            t = find_text(scene, "inv_menu_tous", 0.0, sc, white)
            if not t:
                continue
            # la 2e ligne ressemble à la 3e (« …déjà présents ») : on ne la cherche qu'à la place attendue
            v = _find_text_near(white, "inv_menu_visibles", sc, (t[0][0] + MENU_DX * sc, t[0][1] + MENU_DY * sc))
            if not v:
                continue
            wanted = t if option == "inv_menu_tous" else v
            alone = wanted[1] >= TEXT_MIN
            paired = min(t[1], v[1]) >= MENU_LINE_MIN
            if (alone or paired) and (best is None or wanted[1] > best[1]):
                best = (wanted[0], wanted[1], sc)
        if best:
            return best
    return None


def find_icons(ctx: Context, scene: np.ndarray, variant: str, threshold: float = ICON_MIN):
    templates = [t for t in ctx.ui_templates if t.variant == variant]
    return scan(scene, templates, threshold).detections if templates else []


def inventory_full(ctx: Context, scene: np.ndarray) -> bool:
    """Badge rouge sur l'icône de l'inventaire, ou message « Inventaire plein » dans une fenêtre d'avertissement.
    Le badge n'est cherché que sans fenêtre ouverte : la barre des pods d'une fenêtre porte un repère rouge semblable."""
    windows = find_icons(ctx, scene, CLOSE, 0.85)
    if windows:
        return find_text_any_scale(scene, "inv_plein_texte") is not None
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


def _save_transfer_diag(ctx: Context, option: str, titles, clicked) -> None:
    """Menu de transfert introuvable : meilleurs scores de lecture dans le journal + capture annotée (titres en
    jaune, clics en rouge) enregistrée dans logs, pour voir si le menu est à l'écran ou si le clic a manqué."""
    from datetime import datetime
    from core.imgio import save_image
    from core.paths import logs_dir
    scene, _ = ctx.capture.grab()
    white = _white(scene)
    best = {n: max((find_text(scene, n, 0.0, sc, white) or (None, 0.0))[1] for sc in TEXT_SCALES)
            for n in ("inv_menu_visibles", "inv_menu_tous")}
    ctx.log("Diagnostic du menu de transfert : meilleur score de lecture de « " + option + " » = "
            f"{best.get(option, 0.0):.2f} (0,85 demandé) ; clics aux positions {clicked}.")
    if ctx.config.save_diagnostics:
        out = scene.copy()
        for t in titles:
            cv2.circle(out, (int(t[0]), int(t[1])), 10, (0, 255, 255), 3)
        for c in clicked:
            cv2.circle(out, (int(c[0]), int(c[1])), 14, (0, 0, 255), 3)
        try:
            save_image(logs_dir() / f"transfert_menu_absent_{datetime.now():%Y%m%d_%H%M%S}.png", out)
        except Exception:
            pass


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
        white = _white(scene)
        inv = find_text_any_scale(scene, "inv_titre_inventaire", white=white)
        mon = find_text_any_scale(scene, "inv_titre_monture", around=inv[2] if inv else None, white=white) if inv else None
        return (inv, mon) if inv and mon else None

    titles, origin = _wait_stable(ctx, both_titles, lambda t: t[0][0], should_stop, 4.0)
    if not titles:
        ctx.log("⚠ Les fenêtres Monture et Inventaire ne se sont pas ouvertes.")
        return finish("fail")
    (inv_title, _, s_inv), (mon_title, _, s_mon) = titles
    ui_scale = (s_inv + s_mon) / 2                             # échelle réelle des fenêtres (1,00 = mise en page d'origine)
    ctx.log(f"Fenêtres Monture et Inventaire reconnues (échelle {ui_scale:.2f}).")
    find_option = lambda s: find_transfer_option(s, option, around=ui_scale)
    chosen, clicked = None, []
    for label, title, off in (("Inventaire", inv_title, INV_ARROW_FROM_TITLE), ("Monture", mon_title, MOUNT_ARROW_FROM_TITLE)):
        ctx.log(f"Clic sur la flèche verte de la fenêtre {label}.")
        target = (int(title[0] + off[0] * ui_scale), int(title[1] + off[1] * ui_scale))
        clicked.append(target)
        _click(ctx, origin, target)
        chosen, origin = _wait(ctx, find_option, should_stop, 2.5)
        if chosen:
            break
    if not chosen:
        ctx.log("⚠ Le menu de transfert n'est pas apparu.")
        _save_transfer_diag(ctx, option, [inv_title, mon_title], clicked)
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
