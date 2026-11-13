"""Enregistrement d'images (compatible avec les chemins accentués sous Windows)."""
import cv2

# Images de diagnostic « de routine » (une par clic, lancer ou déplacement) : on ne garde que les plus récentes
# pour que le dossier logs ne grossisse pas sans fin. Les captures d'erreur (tour_introuvable, aucun_monstre,
# fermeture_impossible, selection_sort, transfert_menu_absent…) ne sont jamais supprimées.
ROUTINE_PREFIXES = ("diag_", "tour_2", "deplacement_", "pied_", "perso_introuvable_", "placement_", "combat_")
MAX_ROUTINE_IMAGES = 150


def _prune_logs(folder) -> None:
    try:
        files = [f for f in folder.iterdir() if f.suffix == ".png" and f.name.startswith(ROUTINE_PREFIXES)]
        if len(files) <= MAX_ROUTINE_IMAGES:
            return
        files.sort(key=lambda f: f.stat().st_mtime)
        for f in files[:len(files) - MAX_ROUTINE_IMAGES]:
            f.unlink(missing_ok=True)
    except OSError:
        pass                                   # le nettoyage ne doit jamais gêner le programme


def save_image(path, img, ext: str = ".png") -> None:
    params = [cv2.IMWRITE_JPEG_QUALITY, 88] if ext == ".jpg" else []
    ok, buf = cv2.imencode(ext, img, params)
    if ok:
        buf.tofile(str(path))
        if path.parent.name == "logs":
            _prune_logs(path.parent)
