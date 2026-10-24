"""Text & Logo: names, slogans and logos on top of the design, placed in real sizes."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from app.core import layers as ly
from app.core import production as pr
from app.core import units as un
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon, pil_to_qimage


class LayerCanvas(QWidget):
    changed = Signal(bool)      # final?
    selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 380)
        self.setMouseTracking(True)
        self.job = None
        self.job_dir = None
        self.layers: List[dict] = []
        self.art: Optional[QImage] = None
        self.sel = -1
        self._drag = None
        self._cache = {}

    # ---------------- mapping ----------------
    def _geom(self):
        j = self.job
        m = 24
        s = min((self.width() - 2 * m) / j.art_width, (self.height() - 2 * m) / j.art_height)
        ox = (self.width() - j.art_width * s) / 2
        oy = (self.height() - j.art_height * s) / 2
        return ox, oy, s

    def to_px(self, x, y) -> QPointF:
        ox, oy, s = self._geom()
        return QPointF(ox + x * s, oy + y * s)

    def to_m(self, pos):
        ox, oy, s = self._geom()
        return (pos.x() - ox) / s, (pos.y() - oy) / s

    def _rect(self, lay) -> QRectF:
        x0, y0, x1, y1 = ly.rect(self.job, lay, self.job_dir)
        return QRectF(self.to_px(x0, y0), self.to_px(x1, y1))

    # ---------------- mouse ----------------
    def mousePressEvent(self, ev) -> None:
        if self.job is None:
            return
        pos = ev.position()
        if 0 <= self.sel < len(self.layers):
            r = self._rect(self.layers[self.sel])
            if (pos - r.bottomRight()).manhattanLength() < 14:
                self._drag = ("size", self.sel, r.topLeft(), self.layers[self.sel]["h"], r.height())
                return
        hit = -1
        for i in reversed(range(len(self.layers))):
            if self._rect(self.layers[i]).contains(pos):
                hit = i
                break
        if hit != self.sel:
            self.sel = hit
            self.selected.emit(hit)
        if hit >= 0:
            lay = self.layers[hit]
            self._drag = ("move", hit, self.to_m(pos), (lay["x"], lay["y"]))
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        d = self._drag
        pos = ev.position()
        if d is None:
            cur = Qt.CursorShape.ArrowCursor
            if 0 <= self.sel < len(self.layers) and \
                    (pos - self._rect(self.layers[self.sel]).bottomRight()).manhattanLength() < 14:
                cur = Qt.CursorShape.SizeFDiagCursor
            elif any(self._rect(lay).contains(pos) for lay in self.layers):
                cur = Qt.CursorShape.SizeAllCursor
            self.setCursor(cur)
            return
        lay = self.layers[d[1]]
        if d[0] == "move":
            mx, my = self.to_m(pos)
            lay["x"] = round(d[3][0] + mx - d[2][0], 4)
            lay["y"] = round(d[3][1] - (my - d[2][1]), 4)
        else:
            _ox, _oy, s = self._geom()
            top_left = d[2]
            new_h_px = max(6.0, pos.y() - top_left.y())
            bottom_old = lay["y"]
            h_old = lay["h"]
            lay["h"] = round(max(0.01, d[3] * new_h_px / max(1.0, d[4])), 4)
            lay["y"] = round(bottom_old - (lay["h"] - h_old), 4)        # keep the top edge in place
        self.changed.emit(False)
        self.update()

    def mouseReleaseEvent(self, _ev) -> None:
        if self._drag is not None:
            self._drag = None
            self.changed.emit(True)

    # ---------------- paint ----------------
    def _layer_pixmap(self, lay, w, h) -> QPixmap:
        key = (repr(sorted((k, v) for k, v in lay.items() if not k.startswith("_"))), int(w), int(h))
        pm = self._cache.get(key)
        if pm is None:
            img = ly.render_layer(lay, max(1, int(w)), max(1, int(h)), self.job_dir)
            pm = QPixmap.fromImage(pil_to_qimage(img))
            if len(self._cache) > 40:
                self._cache.clear()
            self._cache[key] = pm
        return pm

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#eef1f5"))
        j = self.job
        if j is None:
            return
        art_r = QRectF(self.to_px(0, 0), self.to_px(j.art_width, j.art_height))
        if self.art is not None:
            p.drawImage(art_r, self.art)
        # wall outlines and the area outside them
        walls = QPainterPath()
        for i in range(len(j.walls)):
            sub = QPainterPath()
            sub.addPolygon(QPolygonF([self.to_px(x, y) for x, y in j.wall_outline(i)]))
            sub.closeSubpath()
            walls = walls.united(sub)
        outside = QPainterPath()
        outside.addRect(art_r)
        p.fillPath(outside.subtracted(walls), QColor(255, 255, 255, 140))
        p.setPen(QPen(QColor("#0f172a"), 1.5, Qt.PenStyle.DashLine))
        p.drawPath(walls)
        for i, lay in enumerate(self.layers):
            r = self._rect(lay)
            p.drawPixmap(r.toRect(), self._layer_pixmap(lay, r.width(), r.height()))
            if i == self.sel:
                p.setPen(QPen(QColor("#1a73e8"), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r)
                p.setPen(QPen(QColor("white"), 1.5))
                p.setBrush(QColor("#1a73e8"))
                p.drawRect(QRectF(r.right() - 6, r.bottom() - 6, 12, 12))


class LayersDialog(SheetDialog):
    def __init__(self, studio):
        super().__init__(studio.window(), "doc", "Text & Logo",
                         "Add a name, slogan or logo on the wall in real sizes. They print sharp at full resolution.",
                         size=(1500, 920))
        self.studio = studio
        self.job = studio.job.copy()
        self.job.layers = copy.deepcopy(studio.job.layers)
        self.job_dir: Path = studio.ensure_dir()
        self.unit = studio.unit() if studio.unit() in ("m", "cm", "ft", "in") else "cm"
        self.su = "cm" if self.unit == "m" else self.unit
        self._loading = False
        row = QHBoxLayout()
        row.setSpacing(16)
        self.canvas = LayerCanvas()
        self.canvas.job, self.canvas.job_dir, self.canvas.layers = self.job, self.job_dir, self.job.layers
        self.canvas.changed.connect(self._on_canvas)
        self.canvas.selected.connect(self._select)
        row.addWidget(self.canvas, 1)

        side = QVBoxLayout()
        side.setSpacing(8)
        br = QHBoxLayout()
        b_t = QPushButton(icon("plus"), " Text")
        b_t.clicked.connect(self.add_text)
        br.addWidget(b_t)
        b_l = QPushButton(icon("image"), " Logo / picture…")
        b_l.clicked.connect(self.add_logo)
        br.addWidget(b_l)
        br.addStretch()
        side.addLayout(br)
        self.list = QListWidget()
        self.list.setMaximumHeight(130)
        self.list.currentRowChanged.connect(self._on_row)
        side.addWidget(self.list)
        ar = QHBoxLayout()
        for ic, txt, tip, fn in (("", "Back", "Behind the other items", lambda: self._move(-1)),
                                 ("", "Front", "In front of the other items", lambda: self._move(1)),
                                 ("copy", "Copy", "Duplicate", self.duplicate),
                                 ("trash", "Remove", "Remove", self.remove)):
            b = QPushButton(icon(ic), " " + txt) if ic else QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            ar.addWidget(b)
        ar.addStretch()
        side.addLayout(ar)
        self.form_w = QWidget()
        f = QFormLayout(self.form_w)
        f.setContentsMargins(0, 4, 0, 0)
        f.setVerticalSpacing(8)
        self.ed_text = QPlainTextEdit()
        self.ed_text.setMaximumHeight(70)
        self.ed_text.textChanged.connect(lambda: self._set("text", self.ed_text.toPlainText()))
        self.row_text = self.ed_text
        f.addRow("Text", self.ed_text)
        self.cb_font = QComboBox()
        self.cb_font.setEditable(True)
        self.cb_font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cb_font.setMaxVisibleItems(18)
        for name in ly.list_fonts():
            self.cb_font.addItem(name)
        self.cb_font.currentTextChanged.connect(lambda t: t in ly.list_fonts() and self._set("font", t))
        f.addRow("Font", self.cb_font)
        cr = QHBoxLayout()
        self.b_col = QPushButton("Colour")
        self.b_col.clicked.connect(lambda: self._pick("colour"))
        cr.addWidget(self.b_col)
        self.chk_outline = QCheckBox("Outline")
        self.chk_outline.toggled.connect(lambda v: self._set("outline", (self._cur() or {}).get("_outline_c", "#1e293b")
                                                             if v else ""))
        cr.addWidget(self.chk_outline)
        self.b_out = QPushButton("…")
        self.b_out.setFixedWidth(34)
        self.b_out.setToolTip("Outline colour")
        self.b_out.clicked.connect(lambda: self._pick("outline"))
        cr.addWidget(self.b_out)
        self.chk_shadow = QCheckBox("Shadow")
        self.chk_shadow.toggled.connect(lambda v: self._set("shadow", v))
        cr.addWidget(self.chk_shadow)
        cr.addStretch()
        self.row_colour = QWidget()
        self.row_colour.setLayout(cr)
        f.addRow("", self.row_colour)
        self.chk_white = QCheckBox("Remove white background")
        self.chk_white.toggled.connect(lambda v: self._set("key_white", v))
        f.addRow("", self.chk_white)
        self.sp = {}
        for key, label in (("h", "Height"), ("x", "From the left"), ("y", "From the floor")):
            s = QDoubleSpinBox()
            s.setDecimals(1 if self.su in ("cm", "in") else 2)
            if key == "h":                               # 1 cm … 30 m (the tallest wall)
                s.setRange(un.to_unit(0.01, self.su), un.to_unit(30.0, self.su))
            else:                                        # anywhere on a wall up to 100 m
                s.setRange(un.to_unit(-100.0, self.su), un.to_unit(100.0, self.su))
            s.setSuffix(" " + self.su)
            s.setKeyboardTracking(False)
            s.valueChanged.connect(lambda v, k=key: self._set(k, un.from_unit(v, self.su)))
            self.sp[key] = s
            f.addRow(label, s)
        self.lbl_w = hint("")
        f.addRow("", self.lbl_w)
        self.sl_op = QSlider(Qt.Orientation.Horizontal)
        self.sl_op.setRange(10, 100)
        self.sl_op.valueChanged.connect(lambda v: self._set("opacity", v / 100.0))
        f.addRow("Opacity", self.sl_op)
        cb = QHBoxLayout()
        b_cx = QPushButton("Centre across")
        b_cx.clicked.connect(self.centre_x)
        cb.addWidget(b_cx)
        b_cy = QPushButton("Centre up/down")
        b_cy.clicked.connect(self.centre_y)
        cb.addWidget(b_cy)
        f.addRow("", self._wrap(cb))
        side.addWidget(self.form_w)
        side.addStretch()
        side.addWidget(hint("Drag on the wall to move, drag the blue corner to resize. Sizes are real: "
                            "a 20 cm letter prints 20 cm tall."))
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(400)
        row.addWidget(sw)
        self.body.addLayout(row, 1)
        bot = QHBoxLayout()
        bot.addStretch()
        ok = QPushButton(icon("check", "#ffffff"), "  Use on the Wall")
        ok.setObjectName("Go")
        ok.clicked.connect(self.accept)
        bot.addWidget(ok)
        c = QPushButton("Cancel")
        c.setObjectName("Light")
        c.clicked.connect(self.reject)
        bot.addWidget(c)
        self.body.addLayout(bot)
        QTimer.singleShot(0, self._render_base)
        self._fill_list(0 if self.job.layers else -1)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    # ------------------------------------------------------------------
    def _render_base(self) -> None:
        from app.core.layers import LayeredSource
        src = self.studio.source
        base = src.base if isinstance(src, LayeredSource) else src
        if base is None:
            return
        img, _ppm = pr.render_artwork(base, self.job, max_side=1600, fast=True)
        self.canvas.art = pil_to_qimage(img)
        self.canvas.update()

    def _cur(self) -> Optional[dict]:
        r = self.list.currentRow()
        return self.job.layers[r] if 0 <= r < len(self.job.layers) else None

    def _fill_list(self, sel: int) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for lay in self.job.layers:
            if lay.get("kind") == "image":
                txt = "Logo · " + Path(lay.get("file", "")).name
            else:
                txt = "Text · " + (lay.get("text") or "").replace("\n", " ")[:30]
            self.list.addItem(QListWidgetItem(txt))
        self.list.blockSignals(False)
        self.list.setCurrentRow(sel)
        self._refresh_form()

    def _refresh_form(self) -> None:
        lay = self._cur()
        self.form_w.setEnabled(lay is not None)
        self.canvas.sel = self.list.currentRow()
        self.canvas.update()
        if lay is None:
            return
        self._loading = True
        is_text = lay.get("kind") != "image"
        for w in (self.ed_text, self.cb_font, self.row_colour):
            w.setVisible(is_text)
            lab = self.form_w.layout().labelForField(w)
            if lab:
                lab.setVisible(is_text)
        self.chk_white.setVisible(not is_text)
        if is_text:
            if self.ed_text.toPlainText() != lay.get("text", ""):
                self.ed_text.setPlainText(lay.get("text", ""))
            self.cb_font.setCurrentText(lay.get("font", ""))
            pm = QPixmap(16, 16)
            pm.fill(QColor(lay.get("colour", "#ffffff")))
            self.b_col.setIcon(QIcon(pm))
            self.chk_outline.setChecked(bool(lay.get("outline")))
            self.chk_shadow.setChecked(bool(lay.get("shadow")))
        else:
            self.chk_white.setChecked(bool(lay.get("key_white")))
        for k, s in self.sp.items():
            s.setValue(un.to_unit(float(lay.get(k, 0.0)), self.su))
        self.sl_op.setValue(int(round(float(lay.get("opacity", 1.0)) * 100)))
        wm = float(lay["h"]) * ly.aspect(lay, self.job_dir)
        self.lbl_w.setText(f"Width {un.fmt(wm, self.su)} (follows the shape)")
        self._loading = False

    def _set(self, key: str, value) -> None:
        if self._loading:
            return
        lay = self._cur()
        if lay is None:
            return
        lay[key] = value
        if key == "outline" and value:
            lay["_outline_c"] = value
        if key == "text":
            it = self.list.currentItem()
            if it:
                it.setText("Text · " + value.replace("\n", " ")[:30])
        if key in ("text", "font", "h"):
            wm = float(lay["h"]) * ly.aspect(lay, self.job_dir)
            self.lbl_w.setText(f"Width {un.fmt(wm, self.su)} (follows the shape)")
        self.canvas.update()

    def _pick(self, key: str) -> None:
        lay = self._cur()
        if lay is None:
            return
        c = QColorDialog.getColor(QColor(lay.get(key) or "#ffffff"), self, "Colour")
        if c.isValid():
            self._set(key, c.name())
            if key == "outline":
                self.chk_outline.setChecked(True)
            self._refresh_form()

    def _on_row(self, _r: int) -> None:
        self._refresh_form()

    def _select(self, i: int) -> None:
        self.list.setCurrentRow(i)

    def _on_canvas(self, final: bool) -> None:
        if final:
            self._refresh_form()

    # ------------------------------------------------------------------
    def add_text(self) -> None:
        self.job.layers.append(ly.new_text_layer(self.job))
        self._fill_list(len(self.job.layers) - 1)
        self.ed_text.setFocus()
        self.ed_text.selectAll()

    def add_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a logo or picture", "",
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if not path:
            return
        try:
            with Image.open(path) as im:
                img = ImageOps.exif_transpose(im).convert("RGBA")
        except Exception as exc:
            from app.core.imaging import load_error_text
            QMessageBox.warning(self, "Logo", load_error_text(path, exc))
            return
        d = self.job_dir / "layers"
        d.mkdir(parents=True, exist_ok=True)
        name = f"{pr.safe_name(Path(path).stem)}.png"
        n = 1
        while (d / name).exists():
            n += 1
            name = f"{pr.safe_name(Path(path).stem)}_{n}.png"
        img.save(d / name, "PNG")
        lay = ly.new_image_layer(self.job, f"layers/{name}", img.size)
        if Path(path).suffix.lower() in (".jpg", ".jpeg", ".bmp"):
            lay["key_white"] = True          # most logos sent as JPG sit on white
        self.job.layers.append(lay)
        self._fill_list(len(self.job.layers) - 1)

    def remove(self) -> None:
        r = self.list.currentRow()
        if 0 <= r < len(self.job.layers):
            self.job.layers.pop(r)
            self._fill_list(min(r, len(self.job.layers) - 1))

    def duplicate(self) -> None:
        lay = self._cur()
        if lay is None:
            return
        import uuid
        k = copy.deepcopy(lay)
        k["id"] = uuid.uuid4().hex[:8]
        k["y"] = float(k["y"]) - float(k["h"]) * 1.2
        self.job.layers.append(k)
        self._fill_list(len(self.job.layers) - 1)

    def _move(self, d: int) -> None:
        r = self.list.currentRow()
        k = r + d
        if 0 <= r < len(self.job.layers) and 0 <= k < len(self.job.layers):
            L = self.job.layers
            L[r], L[k] = L[k], L[r]
            self._fill_list(k)

    def centre_x(self) -> None:
        lay = self._cur()
        if lay:
            w = float(lay["h"]) * ly.aspect(lay, self.job_dir)
            self._set("x", round((self.job.run_width - w) / 2, 4))
            self._refresh_form()

    def centre_y(self) -> None:
        lay = self._cur()
        if lay:
            self._set("y", round((self.job.run_height - float(lay["h"])) / 2, 4))
            self._refresh_form()

    def result_layers(self) -> List[dict]:
        return [lay for lay in self.job.layers if lay.get("kind") == "image" or (lay.get("text") or "").strip()]
