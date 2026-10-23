"""
Colour: print check (soft proof + gamut), palette & paint/brand colour matching,
colour replacement and colourways. Changes are saved as a new design version.
"""
from __future__ import annotations

import traceback
from typing import List, Optional, Tuple

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from app.core import colour as col
from app.core import production as pr
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon, pil_to_qimage
from app.ui.views import ZoomView
from app.ui.worker import run_bg

PREVIEW_MAX = 1400


def _swatch(rgb, size=28) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(*rgb))
    return QIcon(pm)


class ColourDialog(SheetDialog):
    def __init__(self, studio):
        super().__init__(studio.window(), "palette", "Colour",
                         "Check how the colours will print, match paint or brand colours, and make colourways.",
                         size=(1500, 940))
        self.studio = studio
        j = studio.job
        self.pattern = j.design_kind == "pattern" and studio.tile_img is not None
        self.full = studio.tile_img if self.pattern else studio.design_img
        self.src = self.full.copy()
        if max(self.src.size) > PREVIEW_MAX:
            self.src.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.Resampling.LANCZOS)
        self.result_img: Optional[Image.Image] = None
        self.result_note = ""
        self.way = "Original"
        self.adj = [0.0, 1.0, 1.0, 0.0]          # hue, saturation, brightness, warmth
        self.repl: List[Tuple[tuple, tuple, float]] = []
        self.picked: Optional[tuple] = None
        self._after_cache = None
        self.t = QTimer(self, singleShot=True, interval=80, timeout=self._refresh)

        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        top = QHBoxLayout()
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.view_group = QButtonGroup(self)
        for i, t in enumerate(("Before", "After", "As printed", "Out of range")):
            b = QPushButton(t)
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setMinimumWidth(110)
            b.setStyleSheet("border-top-left-radius:8px;border-bottom-left-radius:8px;" if i == 0 else
                            "border-top-right-radius:8px;border-bottom-right-radius:8px;" if i == 3 else "")
            self.view_group.addButton(b, i)
            seg.addWidget(b)
        self.view_group.button(1).setChecked(True)
        self.view_group.idClicked.connect(lambda _i: self.t.start())
        top.addLayout(seg)
        top.addStretch()
        top.addWidget(hint("Click the picture to pick a colour"))
        left.addLayout(top)
        self.view = ZoomView("", bg="#eef1f5")
        self.view.clicked.connect(self._pick_at)
        left.addWidget(self.view, 1)
        self.lbl_info = hint("")
        self.lbl_info.setWordWrap(True)
        left.addWidget(self.lbl_info)
        row.addLayout(left, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._print_tab(), "Print check")
        self.tabs.addTab(self._palette_tab(), "Match && replace")
        self.tabs.addTab(self._ways_tab(), "Colourways")
        self.tabs.setFixedWidth(420)
        row.addWidget(self.tabs)
        self.body.addLayout(row, 1)

        bot = QHBoxLayout()
        bot.setSpacing(12)
        b_reset = QPushButton(icon("reset"), "  Reset")
        b_reset.setObjectName("Light")
        b_reset.clicked.connect(self.reset)
        bot.addWidget(b_reset)
        bot.addStretch()
        self.lbl_status = hint("")
        bot.addWidget(self.lbl_status)
        self.b_apply = QPushButton(icon("check", "#ffffff"), "  Save as New Design Version")
        self.b_apply.setObjectName("Go")
        self.b_apply.clicked.connect(self.apply)
        bot.addWidget(self.b_apply)
        b_close = QPushButton("Close")
        b_close.setObjectName("Light")
        b_close.clicked.connect(self.reject)
        bot.addWidget(b_close)
        self.body.addLayout(bot)
        self._fill_palette()
        QTimer.singleShot(0, self._refresh)
        QTimer.singleShot(0, self._make_way_thumbs)

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _print_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Printer colour profile"))
        self.cb_prof = QComboBox()
        for p in col.list_profiles():
            self.cb_prof.addItem(p.name)
        cur = pr.find_preset(self.studio.job.output_preset).colour
        k = self.cb_prof.findText(cur)
        if k < 0:
            k = self.cb_prof.findText(col.BUNDLED.get("FOGRA39L_coated.icc", ""))
        self.cb_prof.setCurrentIndex(max(0, k))
        self.cb_prof.currentIndexChanged.connect(lambda _i: self._on_print_settings())
        lay.addWidget(self.cb_prof)
        b_add = QPushButton(icon("plus"), " Add the print shop's ICC profile…")
        b_add.clicked.connect(self._add_profile)
        lay.addWidget(b_add)
        lay.addWidget(QLabel("Rendering intent"))
        self.cb_intent = QComboBox()
        for name in col.INTENTS:
            self.cb_intent.addItem(name)
        self.cb_intent.setCurrentText("Relative colorimetric")
        self.cb_intent.currentIndexChanged.connect(lambda _i: self._on_print_settings())
        lay.addWidget(self.cb_intent)
        self.lbl_gamut = QLabel("")
        self.lbl_gamut.setWordWrap(True)
        self.lbl_gamut.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.lbl_gamut)
        tip = hint("‘As printed’ shows the colours the printer can really make on this profile. "
                   "‘Out of range’ marks in pink the colours that will print duller. Bright blues, greens "
                   "and oranges are usually affected. Ask your print shop for their ICC profile for the "
                   "most accurate check.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        b_fix = QPushButton(icon("sparkle"), " Bring colours into range")
        b_fix.setToolTip("Lower the saturation slightly so fewer colours fall outside the printer's range")
        b_fix.clicked.connect(self._soften_for_print)
        lay.addWidget(b_fix)
        lay.addStretch()
        return w

    def _palette_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Colour book to match with"))
        r = QHBoxLayout()
        self.cb_book = QComboBox()
        self._fill_books()
        self.cb_book.currentIndexChanged.connect(lambda _i: self._fill_palette())
        r.addWidget(self.cb_book, 1)
        bi = QPushButton(icon("upload"), " Import…")
        bi.setToolTip("Import a paint or brand colour list (CSV: Name,#hex  or  Name,R,G,B  or  Name,L,a,b)")
        bi.clicked.connect(self._import_book)
        r.addWidget(bi)
        lay.addLayout(r)
        lay.addWidget(QLabel("Main colours in the design"))
        self.list_pal = QListWidget()
        self.list_pal.setIconSize(QSize(28, 28))
        self.list_pal.setWordWrap(True)
        self.list_pal.currentRowChanged.connect(self._on_pal_row)
        lay.addWidget(self.list_pal, 1)
        self.lbl_pick = QLabel("")
        self.lbl_pick.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_pick.setWordWrap(True)
        lay.addWidget(self.lbl_pick)
        rr = QHBoxLayout()
        self.b_to = QPushButton(icon("palette"), " Replace with…")
        self.b_to.clicked.connect(self._replace_with)
        rr.addWidget(self.b_to)
        self.b_to_match = QPushButton(" Use closest from book")
        self.b_to_match.clicked.connect(self._replace_with_match)
        rr.addWidget(self.b_to_match)
        lay.addLayout(rr)
        tr = QHBoxLayout()
        tr.addWidget(QLabel("How similar"))
        self.sl_tol = QSlider(Qt.Orientation.Horizontal)
        self.sl_tol.setRange(4, 60)
        self.sl_tol.setValue(18)
        self.sl_tol.setToolTip("How close a colour must be to be replaced")
        self.sl_tol.valueChanged.connect(self._on_tol)
        tr.addWidget(self.sl_tol, 1)
        lay.addLayout(tr)
        self.list_repl = QListWidget()
        self.list_repl.setMaximumHeight(96)
        lay.addWidget(self.list_repl)
        b_undo = QPushButton(icon("undo"), " Remove last replacement")
        b_undo.clicked.connect(self._pop_repl)
        lay.addWidget(b_undo)
        return w

    def _ways_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        g = QGridLayout()
        g.setSpacing(8)
        self.way_group = QButtonGroup(self)
        for i, name in enumerate(col.COLOURWAYS):
            b = QToolButton()
            b.setObjectName("PresetTile")
            b.setCheckable(True)
            b.setText(name.replace("&", "&&"))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(104, 70))
            b.setMinimumSize(QSize(118, 100))
            self.way_group.addButton(b, i)
            g.addWidget(b, i // 3, i % 3)
        self.way_group.button(0).setChecked(True)
        self.way_group.idClicked.connect(self._on_way)
        lay.addLayout(g)
        self.sliders = []
        for i, (lab, lo, hi, val) in enumerate((("Hue", -180, 180, 0), ("Saturation", 0, 200, 100),
                                                ("Brightness", 50, 150, 100), ("Warm / cool", -100, 100, 0))):
            r = QHBoxLayout()
            ll = QLabel(lab)
            ll.setFixedWidth(84)
            r.addWidget(ll)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            s.setValue(val)
            s.valueChanged.connect(self._on_adjust)
            r.addWidget(s, 1)
            v = QLabel(str(val))
            v.setFixedWidth(34)
            r.addWidget(v)
            self.sliders.append((s, v))
            lay.addLayout(r)
        lay.addStretch()
        return w

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    def _ops(self, img: Image.Image) -> Image.Image:
        out = col.colourway(img, self.way) if self.way != "Original" else img
        h, s, b, w = self.adj
        if h or s != 1 or b != 1 or w:
            out = col.adjust(out, hue=h, saturation=s, brightness=b, warmth=w)
        for src, dst, tol in self.repl:
            out = col.replace_colour(out, src, dst, tol)
        return out

    def _changed_ops(self) -> None:
        self._after_cache = None
        self.t.start()

    def _after(self) -> Image.Image:
        if self._after_cache is None:
            self._after_cache = self._ops(self.src)
        return self._after_cache

    def _profile(self):
        return col.find_profile(self.cb_prof.currentText())

    def _refresh(self) -> None:
        mode = self.view_group.checkedId()
        try:
            img = self.src if mode == 0 else self._after()
            prof = self._profile()
            info = ""
            if prof is not None:
                mask, frac = col.gamut_map(img, prof, self.cb_intent.currentText())
                level = "#15803d" if frac < 0.02 else "#b45309" if frac < 0.12 else "#dc2626"
                self.lbl_gamut.setText(f"<span style='color:{level};font-weight:700'>{frac * 100:.1f}%</span> of "
                                       f"the picture is outside the printer's colours.<br>"
                                       + ("Looks fine for print." if frac < 0.02 else
                                          "Those areas will print a little duller." if frac < 0.12 else
                                          "Noticeable change in bright colours – show the customer the "
                                          "‘As printed’ view."))
                if mode == 2:
                    img = col.soft_proof(img, prof, self.cb_intent.currentText())
                    info = f"As printed on {prof.name} ({self.cb_intent.currentText().lower()}) – a screen " \
                           "simulation, not an exact match."
                elif mode == 3:
                    img = col.gamut_overlay(img, mask)
                    info = "Pink = colours the printer can't reach. They will print slightly duller."
            if mode == 0:
                info = "Before: the design as it is now."
            elif mode == 1:
                info = info or "After: with your colour changes."
            self.view.set_image(pil_to_qimage(img.convert("RGB")), keep_view=self.view.has_image())
            self.lbl_info.setText(info)
            changes = (self.way != "Original") + (self.adj != [0.0, 1.0, 1.0, 0.0]) + len(self.repl)
            self.b_apply.setEnabled(bool(changes))
            self.lbl_status.setText(f"{changes} change{'s' if changes != 1 else ''}" if changes else "")
        except Exception as exc:
            traceback.print_exc()
            self.lbl_info.setText(f"Could not show the colours: {exc}")

    def _on_print_settings(self) -> None:
        self.t.start()

    def _add_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add an ICC profile", "", "ICC profiles (*.icc *.icm)")
        if not path:
            return
        try:
            p = col.add_user_profile(path)
        except Exception as exc:
            QMessageBox.warning(self, "ICC profile", f"Could not use this profile:\n{exc}")
            return
        self.cb_prof.addItem(p.name)
        self.cb_prof.setCurrentText(p.name)

    def _soften_for_print(self) -> None:
        self.tabs.setCurrentIndex(2)
        s, _v = self.sliders[1]
        s.setValue(max(0, s.value() - 12))
        self.view_group.button(3).setChecked(True)
        self.t.start()

    # ---------------- palette ----------------
    def _fill_books(self) -> None:
        cur = self.cb_book.currentText()
        self.cb_book.blockSignals(True)
        self.cb_book.clear()
        self.books = col.list_palettes()
        for name in self.books:
            self.cb_book.addItem(name)
        k = self.cb_book.findText(cur)
        self.cb_book.setCurrentIndex(max(0, k))
        self.cb_book.blockSignals(False)

    def _import_book(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import colour list", "", "Colour lists (*.csv *.json *.txt)")
        if not path:
            return
        try:
            name, n = col.import_palette(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import colours", str(exc))
            return
        self._fill_books()
        self.cb_book.setCurrentText(name)
        self.lbl_status.setText(f"Imported {n} colours as ‘{name}’.")

    def _book(self) -> dict:
        return self.books.get(self.cb_book.currentText(), {})

    def _fill_palette(self) -> None:
        self.pal = col.extract_palette(self._after() if hasattr(self, "view") else self.src, 8)
        self.list_pal.clear()
        book = self._book()
        for rgb, frac in self.pal:
            m = col.match_colour(rgb, book, 1)
            txt = f"{col.hex_of(rgb)}  ·  {frac * 100:.0f}%"
            if m:
                name, hx, de = m[0]
                txt += f"\nclosest: {name} {hx}  (ΔE {de:.1f})"
            self.list_pal.addItem(QListWidgetItem(_swatch(rgb), txt))
        if self.pal:
            self.list_pal.setCurrentRow(0)

    def _on_pal_row(self, r: int) -> None:
        if 0 <= r < len(self.pal):
            self._set_picked(self.pal[r][0])

    def _pick_at(self, x: float, y: float) -> None:
        img = self._after() if self.view_group.checkedId() != 0 else self.src
        xi, yi = int(x), int(y)
        if 0 <= xi < img.width and 0 <= yi < img.height:
            box = img.convert("RGB").crop((max(0, xi - 2), max(0, yi - 2), xi + 3, yi + 3))
            px = list(box.getdata())
            rgb = tuple(int(round(sum(c[i] for c in px) / len(px))) for i in range(3))
            self.tabs.setCurrentIndex(1)
            self._set_picked(rgb)

    def _set_picked(self, rgb) -> None:
        self.picked = tuple(int(v) for v in rgb)
        rows = col.match_colour(self.picked, self._book(), 3)
        sw = f"<span style='background:{col.hex_of(self.picked)};'>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>"
        lines = [f"{sw} <b>{col.hex_of(self.picked)}</b> &nbsp; RGB {self.picked[0]}, {self.picked[1]}, {self.picked[2]}"]
        for name, hx, de in rows:
            q = "same to the eye" if de < 1 else "very close" if de < 2.5 else "close" if de < 5 else "different"
            lines.append(f"<span style='background:{hx};'>&nbsp;&nbsp;&nbsp;&nbsp;</span> {name} {hx} – ΔE {de:.1f} ({q})")
        self.lbl_pick.setText("<br>".join(lines))

    def _replace_with(self) -> None:
        if self.picked is None:
            return
        c = QColorDialog.getColor(QColor(*self.picked), self, "Replace with")
        if c.isValid():
            self._add_repl((c.red(), c.green(), c.blue()))

    def _replace_with_match(self) -> None:
        if self.picked is None:
            return
        rows = col.match_colour(self.picked, self._book(), 1)
        if rows:
            self._add_repl(col.rgb_of(rows[0][1]), rows[0][0])

    def _add_repl(self, dst, name: str = "") -> None:
        self.repl.append((self.picked, tuple(dst), float(self.sl_tol.value())))
        it = QListWidgetItem(_swatch(self.picked, 18), f"{col.hex_of(self.picked)} → {name or col.hex_of(dst)}")
        it.setIcon(_swatch(dst, 18))
        self.list_repl.addItem(it)
        self._changed_ops()

    def _on_tol(self, v: int) -> None:
        if self.repl:
            s, d, _t = self.repl[-1]
            self.repl[-1] = (s, d, float(v))
            self._changed_ops()

    def _pop_repl(self) -> None:
        if self.repl:
            self.repl.pop()
            self.list_repl.takeItem(self.list_repl.count() - 1)
            self._changed_ops()

    # ---------------- colourways ----------------
    def _make_way_thumbs(self) -> None:
        small = self.src.convert("RGB").copy()
        small.thumbnail((208, 140))
        for i, name in enumerate(col.COLOURWAYS):
            try:
                t = col.colourway(small, name)
                pm = QPixmap.fromImage(pil_to_qimage(t))
                pm.setDevicePixelRatio(2)
                self.way_group.button(i).setIcon(QIcon(pm))
            except Exception:
                traceback.print_exc()

    def _on_way(self, i: int) -> None:
        self.way = col.COLOURWAYS[i]
        self._changed_ops()

    def _on_adjust(self, _v=None) -> None:
        vals = [s.value() for s, _l in self.sliders]
        for (s, l), v in zip(self.sliders, vals):
            l.setText(str(v))
        self.adj = [float(vals[0]), vals[1] / 100.0, vals[2] / 100.0, vals[3] / 100.0]
        self._changed_ops()

    def reset(self) -> None:
        self.way = "Original"
        self.way_group.button(0).setChecked(True)
        for (s, _l), v in zip(self.sliders, (0, 100, 100, 0)):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)
        self._on_adjust()
        self.repl.clear()
        self.list_repl.clear()
        self._changed_ops()

    # ------------------------------------------------------------------
    def apply(self) -> None:
        notes = []
        if self.way != "Original":
            notes.append(self.way.lower())
        if self.adj != [0.0, 1.0, 1.0, 0.0]:
            notes.append("colour adjusted")
        if self.repl:
            notes.append(f"{len(self.repl)} colour{'s' if len(self.repl) > 1 else ''} replaced")
        self.result_note = "colour: " + ", ".join(notes)
        self.b_apply.setEnabled(False)
        self.lbl_status.setText("Applying to the full-size design…")
        self.setCursor(Qt.CursorShape.WaitCursor)
        full = self.full

        def job(_p):
            return self._ops(full)

        def done(img):
            self.unsetCursor()
            self.result_img = img
            self.accept()

        def failed(msg):
            self.unsetCursor()
            self.b_apply.setEnabled(True)
            QMessageBox.warning(self, "Colour", f"Could not apply the change:\n{msg}")

        run_bg(job, done, failed)
