"""Onglet « Sorts » : choisir les sorts à jouer en découpant leurs icônes dans une capture d'écran.

Un profil = un jeu de sorts (une classe). Le profil intégré (Coagulation + Pied du Sacrieur) est en lecture
seule ; on le duplique ou on crée un profil pour utiliser d'autres sorts.
"""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from core.spells import (BIG_RANGE_PIXELS, DEFAULT_PROFILE, SMALL_RANGE_PIXELS, USER_ICON_PREFIX, Spell, SpellBook,
                         analyze_icon, copy_book, default_spellbook, delete_icon, load_icon_image, load_profiles,
                         new_icon_name, save_icon, save_profiles)


def to_qimage(img: np.ndarray) -> QImage:
    h, w = img.shape[:2]
    return QImage(np.ascontiguousarray(img).data, w, h, 3 * w, QImage.Format_BGR888).copy()


def qimage_to_bgr(q: QImage) -> np.ndarray:
    q = q.convertToFormat(QImage.Format_BGR888)
    w, h, bpl = q.width(), q.height(), q.bytesPerLine()
    arr = np.frombuffer(q.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)
    return arr[:, :w * 3].reshape(h, w, 3).copy()


def read_image_file(path: str) -> np.ndarray | None:
    try:
        return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None


# --- découpe d'une icône ------------------------------------------------------------------------------------

class ImageView(QWidget):
    """Affiche une capture et laisse tracer un rectangle à la souris (coordonnées de l'image, pas de l'écran)."""
    selectionChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(760, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self._img: np.ndarray | None = None
        self._pix: QPixmap | None = None
        self._scale, self._off = 1.0, (0, 0)
        self.sel: QRect | None = None
        self._anchor: QPoint | None = None

    def set_image(self, img: np.ndarray) -> None:
        self._img, self.sel = img, None
        self._rebuild()
        self.selectionChanged.emit()
        self.update()

    def _rebuild(self) -> None:
        if self._img is None:
            return
        h, w = self._img.shape[:2]
        self._scale = min(self.width() / w, self.height() / h)
        pw, ph = max(1, int(w * self._scale)), max(1, int(h * self._scale))
        self._pix = QPixmap.fromImage(to_qimage(self._img)).scaled(pw, ph, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._off = ((self.width() - pw) // 2, (self.height() - ph) // 2)

    def resizeEvent(self, e):
        self._rebuild()
        super().resizeEvent(e)

    def _to_img(self, p: QPoint) -> QPoint:
        h, w = self._img.shape[:2]
        x = int((p.x() - self._off[0]) / self._scale)
        y = int((p.y() - self._off[1]) / self._scale)
        return QPoint(min(max(x, 0), w - 1), min(max(y, 0), h - 1))

    def set_selection(self, rect: QRect | None) -> None:
        self.sel = rect
        self.update()

    def mousePressEvent(self, e):
        if self._img is None or e.button() != Qt.LeftButton:
            return
        self._anchor = self._to_img(e.position().toPoint())
        self.sel = QRect(self._anchor, self._anchor)
        self.update()

    def mouseMoveEvent(self, e):
        if self._anchor is not None and self._img is not None:
            self.sel = QRect(self._anchor, self._to_img(e.position().toPoint())).normalized()
            self.selectionChanged.emit()
            self.update()

    def mouseReleaseEvent(self, e):
        self._anchor = None
        self.selectionChanged.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#222"))
        if self._pix is None:
            p.setPen(QColor("#aaa"))
            p.drawText(self.rect(), Qt.AlignCenter, "Ouvre ou colle une capture d'écran, puis entoure l'icône du sort.")
            return
        p.drawPixmap(self._off[0], self._off[1], self._pix)
        if self.sel and self.sel.width() > 0:
            pen = QPen(QColor(255, 40, 40), 2)
            p.setPen(pen)
            s = self._scale
            p.drawRect(int(self._off[0] + self.sel.x() * s), int(self._off[1] + self.sel.y() * s),
                       max(1, int(self.sel.width() * s)), max(1, int(self.sel.height() * s)))


class CropDialog(QDialog):
    """Découpe l'icône d'un sort dans une capture : ouverture d'un fichier, presse-papiers ou capture du jeu."""
    TIP = ("Choisis une capture où le sort n'est PAS sélectionné (pas de cadre orange). Entoure uniquement l'icône, "
           "sans les icônes voisines. Pour une taille d'image identique à celle du programme, utilise « Capturer le jeu »\n"
           "(ou une image du dossier captures, enregistrée par le bouton « Une capture » de l'onglet Tests).")

    def __init__(self, parent=None, grab_game=None, title="Découper l'icône du sort"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.grab_game = grab_game
        self.source: np.ndarray | None = None
        self.check = None
        lay = QVBoxLayout(self)
        tip = QLabel(self.TIP)
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QHBoxLayout()
        self.btn_open = QPushButton("Ouvrir une image…")
        self.btn_paste = QPushButton("Coller (Win+Maj+S puis Ctrl+V)")
        self.btn_game = QPushButton("Capturer le jeu (dans 2 s)")
        self.btn_game.setEnabled(grab_game is not None)
        for b in (self.btn_open, self.btn_paste, self.btn_game):
            row.addWidget(b)
        lay.addLayout(row)
        self.view = ImageView()
        lay.addWidget(self.view, 1)
        coords = QHBoxLayout()
        self.spins = {}
        for key, label in (("x", "X"), ("y", "Y"), ("w", "Largeur"), ("h", "Hauteur")):
            sp = QSpinBox()
            sp.setRange(0, 9999)
            sp.valueChanged.connect(self._spin_changed)
            self.spins[key] = sp
            coords.addWidget(QLabel(label + " :"))
            coords.addWidget(sp)
        coords.addStretch(1)
        self.preview = QLabel()
        self.preview.setFixedSize(120, 120)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#222;")
        coords.addWidget(self.preview)
        lay.addLayout(coords)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.btn_open.clicked.connect(self._open_file)
        self.btn_paste.clicked.connect(self._paste)
        self.btn_game.clicked.connect(self._capture_game)
        self.view.selectionChanged.connect(self._view_changed)
        self.resize(900, 720)

    # --- sources de la capture
    def load_image(self, img: np.ndarray | None) -> None:
        if img is None or img.size == 0:
            self.msg.setText("⚠ Image illisible.")
            return
        self.source = img
        self.view.set_image(img)
        h, w = img.shape[:2]
        for k, mx in (("x", w), ("y", h), ("w", w), ("h", h)):
            self.spins[k].setMaximum(mx)
        self.msg.setText(f"Capture de {w}×{h} px. Entoure l'icône du sort à la souris.")

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Capture d'écran", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.load_image(read_image_file(path))

    def _paste(self):
        q = QGuiApplication.clipboard().image()
        if q.isNull():
            self.msg.setText("⚠ Le presse-papiers ne contient pas d'image. Fais Win+Maj+S, entoure la zone, puis recolle.")
            return
        self.load_image(qimage_to_bgr(q))

    def _capture_game(self):
        main = self.parentWidget().window() if self.parentWidget() else None
        self.hide()
        if main:
            main.showMinimized()
        QTimer.singleShot(2000, lambda: self._do_capture(main))

    def _do_capture(self, main):
        img, err = None, ""
        try:
            img = self.grab_game()
        except Exception as e:                     # fenêtre de jeu introuvable, etc.
            err = str(e)
        if main:
            main.showNormal()
            main.raise_()
        self.show()
        self.raise_()
        if img is None:
            self.msg.setText(f"⚠ Capture impossible : {err or 'fenêtre du jeu introuvable'}.")
        else:
            self.load_image(img)

    # --- sélection ↔ champs ↔ contrôle
    def _view_changed(self):
        r = self.view.sel
        for k, v in (("x", r.x() if r else 0), ("y", r.y() if r else 0),
                     ("w", r.width() if r else 0), ("h", r.height() if r else 0)):
            self.spins[k].blockSignals(True)
            self.spins[k].setValue(v)
            self.spins[k].blockSignals(False)
        self._refresh()

    def _spin_changed(self):
        if self.source is None:
            return
        r = QRect(self.spins["x"].value(), self.spins["y"].value(), self.spins["w"].value(), self.spins["h"].value())
        self.view.set_selection(r)
        self._refresh()

    def rect(self) -> tuple[int, int, int, int]:
        return tuple(self.spins[k].value() for k in ("x", "y", "w", "h"))

    def _refresh(self):
        ok = False
        self.check = None
        if self.source is not None and self.spins["w"].value() > 0:
            self.check = analyze_icon(self.source, self.rect())
            ok = self.check.ok
            lines = [f"✖ {e}" for e in self.check.errors] + [f"⚠ {w}" for w in self.check.warnings]
            if ok and not lines:
                lines = ["✔ Icône valide."]
            self.msg.setText("\n".join(lines))
            x, y, w, h = self.rect()
            if ok:
                self.preview.setPixmap(QPixmap.fromImage(to_qimage(self.source[y:y + h, x:x + w])).scaled(
                    120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview.clear()
        else:
            self.preview.clear()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def _accept(self):
        if self.check and self.check.warnings:
            if QMessageBox.question(self, "Confirmer", "\n".join(self.check.warnings) + "\n\nUtiliser quand même cette icône ?"
                                    ) != QMessageBox.Yes:
                return
        self.accept()

    def crop(self) -> np.ndarray:
        x, y, w, h = self.rect()
        return self.source[y:y + h, x:x + w].copy()


# --- l'onglet --------------------------------------------------------------------------------------------

class SlotRow(QWidget):
    """Une ligne : aperçu de l'icône, nom du sort, boutons."""
    iconRequested = Signal()
    removeRequested = Signal()
    nameEdited = Signal(str)

    def __init__(self, removable: bool):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel("aucune")
        self.preview.setFixedSize(56, 56)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#222;color:#888;")
        lay.addWidget(self.preview)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nom du sort (affiché dans le journal)")
        self.name.editingFinished.connect(lambda: self.nameEdited.emit(self.name.text().strip()))
        lay.addWidget(self.name, 1)
        self.btn_icon = QPushButton("Choisir l'icône depuis une capture…")
        self.btn_icon.clicked.connect(self.iconRequested)
        lay.addWidget(self.btn_icon)
        self.btn_remove = QPushButton("Retirer")
        self.btn_remove.setVisible(removable)
        self.btn_remove.clicked.connect(self.removeRequested)
        lay.addWidget(self.btn_remove)

    def show_spell(self, spell: Spell | None, editable: bool) -> None:
        img = load_icon_image(spell.icon) if spell else None
        if img is not None:
            self.preview.setPixmap(QPixmap.fromImage(to_qimage(img)).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("aucune" if spell is None else "?")
        self.name.setText(spell.name if spell else "")
        for w in (self.name, self.btn_icon, self.btn_remove):
            w.setEnabled(editable)


class SpellsTab(QWidget):
    """Choix du profil de sorts et de leurs icônes. `changed` est émis après chaque modification enregistrée."""
    changed = Signal()

    def __init__(self, cfg, grab_game=None, parent=None):
        super().__init__(parent)
        self.cfg, self.grab_game = cfg, grab_game
        self.profiles: dict[str, SpellBook] = load_profiles()
        self.current = cfg.spell_profile if cfg.spell_profile in self.profiles else DEFAULT_PROFILE
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Profil de sorts :"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(320)
        top.addWidget(self.combo, 1)
        self.btn_new = QPushButton("Nouveau profil…")
        self.btn_dup = QPushButton("Dupliquer…")
        self.btn_del = QPushButton("Supprimer")
        for b in (self.btn_new, self.btn_dup, self.btn_del):
            top.addWidget(b)
        root.addLayout(top)
        self.info = QLabel()
        self.info.setWordWrap(True)
        root.addWidget(self.info)
        box = QGroupBox("Sort d'ouverture : 1er tour seulement, lancé sur soi (facultatif)")
        v = QVBoxLayout(box)
        self.row_open = SlotRow(removable=True)
        v.addWidget(self.row_open)
        root.addWidget(box)
        box = QGroupBox("Sort principal : lancé sur l'adversaire le plus proche à portée (onglet Combat : « Lancers par tour »)")
        v = QVBoxLayout(box)
        self.row_main = SlotRow(removable=False)
        v.addWidget(self.row_main)
        root.addWidget(box)
        self.box_sec = QGroupBox("Sorts secondaires : lancés ensuite sur un adversaire au contact (le personnage se rapproche s'il lui reste des PM)")
        self.sec_layout = QVBoxLayout(self.box_sec)
        self.sec_rows: list[SlotRow] = []
        self.btn_add_sec = QPushButton("+ Ajouter un sort secondaire…")
        self.sec_layout.addWidget(self.btn_add_sec)
        root.addWidget(self.box_sec)
        root.addStretch(1)

        self.row_open.iconRequested.connect(lambda: self._pick_icon("opening"))
        self.row_open.removeRequested.connect(lambda: self._remove("opening"))
        self.row_open.nameEdited.connect(lambda t: self._rename("opening", t))
        self.row_main.iconRequested.connect(lambda: self._pick_icon("primary"))
        self.row_main.nameEdited.connect(lambda t: self._rename("primary", t))
        self.btn_add_sec.clicked.connect(self._add_secondary)
        self.btn_new.clicked.connect(self._new_profile)
        self.btn_dup.clicked.connect(self._duplicate)
        self.btn_del.clicked.connect(self._delete)
        self.combo.currentIndexChanged.connect(self._combo_changed)
        self._fill_combo()

    # --- état courant
    def book(self) -> SpellBook:
        return default_spellbook() if self.current == DEFAULT_PROFILE else self.profiles[self.current]

    def editable(self) -> bool:
        return self.current != DEFAULT_PROFILE

    def selected_name(self) -> str:
        """Valeur à enregistrer dans la configuration (vide = profil intégré)."""
        return "" if self.current == DEFAULT_PROFILE else self.current

    def _slot(self, key):
        b = self.book()
        if key == "opening":
            return b.opening
        if key == "primary":
            return b.primary
        return b.secondary[key[1]]

    def _put(self, key, spell):
        b = self.profiles[self.current]
        if key == "opening":
            b.opening = spell
        elif key == "primary":
            b.primary = spell
        else:
            b.secondary[key[1]] = spell

    # --- affichage
    def _fill_combo(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(DEFAULT_PROFILE, DEFAULT_PROFILE)
        for n in sorted(self.profiles):
            self.combo.addItem(n, n)
        self.combo.setCurrentIndex(max(0, self.combo.findData(self.current)))
        self.combo.blockSignals(False)
        self._refresh()

    def _refresh(self):
        b, ed = self.book(), self.editable()
        self.info.setText("Profil intégré, en lecture seule : « Dupliquer… » ou « Nouveau profil… » pour utiliser d'autres sorts."
                          if not ed else "Les modifications sont enregistrées tout de suite. Le profil choisi est celui utilisé au "
                                         "prochain « Démarrer » ou « Tester ».")
        self.btn_del.setEnabled(ed)
        self.row_open.show_spell(b.opening, ed)
        self.row_open.btn_remove.setEnabled(ed and b.opening is not None)
        self.row_main.show_spell(b.primary, ed)
        for r in self.sec_rows:
            self.sec_layout.removeWidget(r)
            r.deleteLater()
        self.sec_rows = []
        for i, s in enumerate(b.secondary):
            r = SlotRow(removable=True)
            r.show_spell(s, ed)
            r.iconRequested.connect(lambda i=i: self._pick_icon(("sec", i)))
            r.removeRequested.connect(lambda i=i: self._remove(("sec", i)))
            r.nameEdited.connect(lambda t, i=i: self._rename(("sec", i), t))
            self.sec_layout.insertWidget(i, r)
            self.sec_rows.append(r)
        self.btn_add_sec.setEnabled(ed)

    def _commit(self):
        save_profiles(self.profiles)
        self.cfg.spell_profile = self.selected_name()
        self.changed.emit()

    def _combo_changed(self, _i):
        self.current = self.combo.currentData() or DEFAULT_PROFILE
        self._refresh()
        self.cfg.spell_profile = self.selected_name()
        self.changed.emit()

    # --- profils
    def _ask_name(self, title, default=""):
        name, ok = QInputDialog.getText(self, title, "Nom du profil (par exemple le nom de la classe) :", text=default)
        name = name.strip()
        if not ok or not name:
            return None
        if name == DEFAULT_PROFILE or name in self.profiles:
            QMessageBox.warning(self, "Nom déjà utilisé", "Un profil porte déjà ce nom.")
            return None
        return name

    def create_profile(self, name: str, source: SpellBook | None = None) -> SpellBook:
        """Crée un profil (copie du profil donné, par défaut l'intégré) et le sélectionne."""
        self.profiles[name] = copy_book(source or default_spellbook(), name)
        self.current = name
        self._commit()
        self._fill_combo()
        return self.profiles[name]

    def _new_profile(self):
        name = self._ask_name("Nouveau profil")
        if name:
            self.create_profile(name, default_spellbook())

    def _duplicate(self):
        name = self._ask_name("Dupliquer le profil", f"{self.current} (copie)" if self.editable() else "")
        if name:
            self.create_profile(name, self.book())

    def delete_profile(self):
        b = self.profiles.pop(self.current, None)
        if b:
            for s in ([b.opening] if b.opening else []) + [b.primary] + b.secondary:
                delete_icon(s.icon)
        self.current = DEFAULT_PROFILE
        self._commit()
        self._fill_combo()

    def _delete(self):
        if self.editable() and QMessageBox.question(self, "Supprimer", f"Supprimer le profil « {self.current} » ?") == QMessageBox.Yes:
            self.delete_profile()

    # --- sorts
    def _slot_label(self, key):
        return f"secondaire{key[1] + 1}" if isinstance(key, tuple) else {"opening": "ouverture", "primary": "principal"}[key]

    def apply_icon(self, key, crop: np.ndarray, name: str | None = None) -> None:
        """Enregistre `crop` comme icône du sort `key` (« opening », « primary » ou ("sec", n)) du profil courant."""
        if not self.editable():
            return
        k = ("secondary", key[1]) if isinstance(key, tuple) else key
        old = self._slot(k) if not (k == "opening" and self.book().opening is None) else None
        icon = new_icon_name(self.current, self._slot_label(key))
        save_icon(icon, crop)
        rng = SMALL_RANGE_PIXELS if isinstance(key, tuple) else BIG_RANGE_PIXELS
        label = name or (old.name if old else "sort d'ouverture")
        self._put(k, Spell(label, icon, rng))
        if old:
            self._delete_if_unused(old.icon)
        self._commit()
        self._refresh()

    def _delete_if_unused(self, icon: str) -> None:
        used = {s.icon for b in self.profiles.values() for s in ([b.opening] if b.opening else []) + [b.primary] + b.secondary}
        if icon not in used:
            delete_icon(icon)

    def _pick_icon(self, key):
        dlg = CropDialog(self, self.grab_game)
        if dlg.exec() == QDialog.Accepted:
            self.apply_icon(key, dlg.crop())

    def _rename(self, key, text):
        if not self.editable() or not text:
            return
        k = ("secondary", key[1]) if isinstance(key, tuple) else key
        s = self._slot(k)
        if s and s.name != text:
            s.name = text
            self._commit()

    def _remove(self, key):
        if not self.editable():
            return
        b = self.profiles[self.current]
        if key == "opening" and b.opening:
            old, b.opening = b.opening, None
        elif isinstance(key, tuple) and key[1] < len(b.secondary):
            old = b.secondary.pop(key[1])
        else:
            return
        self._delete_if_unused(old.icon)
        self._commit()
        self._refresh()

    def add_secondary(self, crop: np.ndarray, name: str | None = None) -> None:
        if not self.editable():
            return
        b = self.profiles[self.current]
        n = len(b.secondary) + 1
        icon = new_icon_name(self.current, f"secondaire{n}")
        save_icon(icon, crop)
        b.secondary.append(Spell(name or f"Sort secondaire {n}", icon, SMALL_RANGE_PIXELS))
        self._commit()
        self._refresh()

    def _add_secondary(self):
        dlg = CropDialog(self, self.grab_game, "Découper l'icône du sort secondaire")
        if dlg.exec() == QDialog.Accepted:
            self.add_secondary(dlg.crop())
