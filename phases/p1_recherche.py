"""Phase 1 : recherche des monstres et clic sur la meilleure correspondance."""
import time
from datetime import datetime
from dataclasses import dataclass

import cv2
import numpy as np

from core import input as inp
from core.imgio import save_image
from core.maparea import inner_area, map_area, near_border
from core.paths import logs_dir
from core.vision import Detection, annotate, scan
from phases.base import Context


@dataclass
class ScanOutcome:
    frame: np.ndarray              # image annotée à afficher
    detection: Detection | None    # cible choisie (ou None)
    clicked: bool


def _mark_border(frame: np.ndarray, area, margin: float, skipped: list) -> np.ndarray:
    """Aperçu : cadre jaune = zone où les monstres sont cliquables ; croix rouge = monstre ignoré car trop près du bord."""
    if area is None:
        return frame
    x0, y0, x1, y1 = inner_area(area, margin)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (0, 255, 255), 1)
    for d in skipped:
        cx, cy = d.center
        cv2.drawMarker(frame, (cx, cy), (0, 0, 255), cv2.MARKER_TILTED_CROSS, 28, 3)
    return frame


def scan_once(ctx: Context, do_click: bool) -> ScanOutcome:
    """Une observation : capture -> recherche -> (clic éventuel)."""
    t0 = time.time()
    scene, (ox, oy) = ctx.capture.grab()
    t1 = time.time()
    result = scan(scene, ctx.templates, ctx.config.threshold)
    ms_cap, ms_scan = (t1 - t0) * 1000, (time.time() - t1) * 1000

    if not result.detections:
        best = max(result.best_scores.values(), default=0.0)
        ctx.log(f"Aucune cible (meilleur score {best:.2f}, seuil {ctx.config.threshold:.2f}) "
                f"· image {scene.shape[1]}×{scene.shape[0]} · capture {ms_cap:.0f} ms, analyse {ms_scan:.0f} ms")
        return ScanOutcome(annotate(scene, []), None, False)

    # Un clic sur une case du bord de la carte change de carte : on ignore les monstres trop près du bord.
    margin = ctx.config.edge_margin_pct
    area = map_area(scene) if margin > 0 else None
    usable = [d for d in result.detections if not near_border(d.center, area, margin)] if area else result.detections
    skipped = [d for d in result.detections if d not in usable]
    if not usable:
        ctx.log(f"{len(skipped)} monstre(s) reconnu(s), tous à moins de {margin} % du bord de la carte : "
                "je n'y touche pas (ils risquent de me faire changer de carte), j'attends qu'ils s'éloignent.")
        return ScanOutcome(_mark_border(annotate(scene, []), area, margin, skipped), None, False)
    target = usable[0]                     # la plus fiable parmi celles qui ne sont pas au bord
    cx, cy = target.center
    ctx.log(f"Cible : {target.monster}/{target.variant} score {target.score:.2f} "
            f"en ({cx}, {cy}) — {len(usable)} détection(s) · analyse {ms_scan:.0f} ms"
            + (f" · {len(skipped)} ignorée(s) près du bord" if skipped else ""))
    clicked = False
    if do_click:
        n = max(1, int(ctx.config.click_count))
        for i in range(n):
            inp.click(ox + cx, oy + cy)
            if i < n - 1:
                time.sleep(ctx.config.click_interval_ms / 1000)
        clicked = True
        ctx.log(f"{'Double clic' if n == 2 else str(n) + ' clic(s)'} effectué en ({cx}, {cy})")
    frame = _mark_border(annotate(scene, usable, (cx, cy) if clicked else None), area, margin, skipped)
    if ctx.config.save_diagnostics:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_image(logs_dir() / f"diag_{stamp}.png", frame)
    return ScanOutcome(frame, target, clicked)
