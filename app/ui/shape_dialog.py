"""Wall shape: sloped ceiling, gable end, staircase or arched top."""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from app.core import units as un
from app.core import wall as wl
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint

# shape: [(key, label, kind)]  kind: "y" = a height, "x" = a distance from the left, "h" = the wall height, "b" = tick
FIELDS = {
    "slope": [("left_h", "Height at the left", "y"), ("right_h", "Height at the right", "y"),
              ("break_x", "Flat part from the left", "x"), ("mirror", "Mirror (swap left and right)", "b")],
    "gable": [("side_h", "Height at the sides", "y"), ("_H", "Height at the peak", "h"),
              ("peak_x", "Peak from the left", "x")],
    "stairs": [("start_x", "Stairs start (from the left)", "x"), ("end_x", "Stairs end (from the left)", "x"),
               ("rise", "Stairs rise", "y"), ("top_left", "Ceiling height at the left", "y"),
               ("top_right", "Ceiling height at the right", "y"),
               ("mirror", "Mirror (stairs go down to the right)", "b")],
    "arch": [("side_h", "Height at the sides", "y"), ("_H", "Top of the arch", "h")],
}
TIPS = {
    "rect": "A plain rectangular wall.",
    "slope": "Attic rooms and walls under a sloping roof. Set the height at each end; the flat part is the "
             "length that stays full height before the slope starts.",
    "gable": "A pitched gable end: straight sides, sloping up to a peak.",
    "stairs": "A wall beside a staircase. Below the stair line there is no wallpaper. Heights are from the "
              "bottom floor.",
    "arch": "A wall or alcove with a rounded top.",
}


class ShapePreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 260)
        self.wall = None
        self.unit = "m"

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#f6f8fb"))
        w = self.wall
        if w is None:
            return
        m = 46
        s = min((self.width() - 2 * m) / max(w.width, 0.1), (self.height() - 2 * m) / max(w.height, 0.1))
        ox = (self.width() - w.width * s) / 2
        oy = (self.height() + w.height * s) / 2
        X = lambda x: ox + x * s
        Y = lambda y: oy - y * s
        p.setPen(QPen(QColor("#cbd5e1"), 1, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(QPointF(X(0), Y(w.height)), QPointF(X(w.width), Y(0))))
        poly = QPolygonF([QPointF(X(x), Y(y)) for x, y in w.outline()])
        p.setBrush(QColor(26, 115, 232, 40))
        p.setPen(QPen(QColor("#1a73e8"), 2.5))
        p.drawPolygon(poly)
        p.setPen(QPen(QColor("#475569"), 3))
        p.drawLine(QPointF(X(0) - 10, Y(0)), QPointF(X(w.width) + 10, Y(0)))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#0f172a"))
        p.drawText(QRectF(X(0), Y(0) + 6, w.width * s, 18), Qt.AlignmentFlag.AlignCenter, un.fmt(w.width, self.unit))
        for x, al in ((0.0, Qt.AlignmentFlag.AlignRight), (w.width, Qt.AlignmentFlag.AlignLeft)):
            lo, hi = w.span(x, x)
            r = QRectF(X(x) - 84, Y((lo + hi) / 2) - 9, 78, 18) if x == 0 else \
                QRectF(X(x) + 6, Y((lo + hi) / 2) - 9, 78, 18)
            p.drawText(r, al | Qt.AlignmentFlag.AlignVCenter, un.fmt(hi - lo, self.unit))
        p.setPen(QColor("#64748b"))
        p.drawText(QRectF(0, 6, self.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   f"Wallpaper area {un.fmt_area_both(w.area())}")


class ShapeDialog(SheetDialog):
    def __init__(self, parent, wall: wl.Wall, unit: str):
        super().__init__(parent, "wall", "Wall Shape",
                         "For sloped ceilings, gable ends, staircases and arches. Panels are cut to the shape "
                         "(plus bleed), which saves media.", size=(860, 640))
        self.unit = unit if unit in ("m", "cm", "ft", "in") else "m"
        self.wall = wl.Wall.from_dict(wall.to_dict())
        self.params: Dict[str, Dict] = {}
        if self.wall.shaped:
            self.params[self.wall.shape] = dict(self.wall.shape_params)
        row = QHBoxLayout()
        row.setSpacing(18)
        left = QVBoxLayout()
        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self.group = QButtonGroup(self)
        for i, (k, name) in enumerate(wl.SHAPES.items()):
            b = QToolButton()
            b.setObjectName("PresetTile")
            b.setCheckable(True)
            b.setText({"rect": "Rectangle", "slope": "Sloped ceiling", "gable": "Gable end", "stairs": "Staircase",
                       "arch": "Arched top"}.get(k, name))
            b.setToolTip(name)
            b.setIcon(self._icon(k))
            b.setIconSize(QSize(54, 40))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setMinimumSize(QSize(112, 82))
            b.setProperty("shape", k)
            self.group.addButton(b, i)
            tiles.addWidget(b)
            if k == (self.wall.shape if self.wall.shape in wl.SHAPES else "rect"):
                b.setChecked(True)
        self.group.idClicked.connect(self._on_shape)
        left.addLayout(tiles)
        self.lbl_tip = hint("")
        self.lbl_tip.setWordWrap(True)
        left.addWidget(self.lbl_tip)
        self.form_box = QWidget()
        self.form = QFormLayout(self.form_box)
        self.form.setContentsMargins(0, 6, 0, 0)
        self.form.setVerticalSpacing(8)
        left.addWidget(self.form_box)
        left.addStretch()
        row.addLayout(left, 1)
        self.preview = ShapePreview()
        self.preview.unit = self.unit
        row.addWidget(self.preview, 1)
        self.body.addLayout(row, 1)
        bot = QHBoxLayout()
        bot.addStretch()
        ok = QPushButton("Use This Shape")
        ok.setObjectName("Go")
        ok.clicked.connect(self.accept)
        bot.addWidget(ok)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Light")
        cancel.clicked.connect(self.reject)
        bot.addWidget(cancel)
        self.body.addLayout(bot)
        self._build_form()

    # ------------------------------------------------------------------
    def _icon(self, shape: str):
        from PySide6.QtGui import QPixmap
        pm = QPixmap(108, 80)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = 1.4, 1.0
        pts = wl.shape_outline(shape, wl.default_shape_params(shape, W, H), W, H, 24)
        poly = QPolygonF([QPointF(8 + x / W * 92, 72 - y / H * 64) for x, y in pts])
        p.setBrush(QColor(26, 115, 232, 60))
        p.setPen(QPen(QColor("#1a73e8"), 3))
        p.drawPolygon(poly)
        p.end()
        pm.setDevicePixelRatio(2)
        return pm

    def shape(self) -> str:
        b = self.group.checkedButton()
        return b.property("shape") if b else "rect"

    def _on_shape(self, _i: int) -> None:
        w = self.wall
        if w.shaped:
            self.params[w.shape] = dict(w.shape_params)
        k = self.shape()
        w.shape = k
        w.shape_params = self.params.get(k) or wl.default_shape_params(k, w.width, w.height)
        w.height = wl.shape_height(k, w.shape_params, w.height)
        self._build_form()

    def _build_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        w = self.wall
        k = self.shape()
        self.lbl_tip.setText(TIPS.get(k, ""))
        dec = {"m": 2, "cm": 1, "ft": 2, "in": 1}[self.unit]
        for key, label, kind in FIELDS.get(k, []):
            if kind == "b":
                c = QCheckBox(label)
                c.setChecked(bool(w.shape_params.get(key)))
                c.toggled.connect(lambda v, key=key: self._set(key, v))
                self.form.addRow("", c)
                continue
            sp = QDoubleSpinBox()
            sp.setDecimals(dec)
            sp.setRange(0, un.to_unit(60, self.unit))
            sp.setSingleStep({"m": 0.05, "cm": 5, "ft": 0.25, "in": 1}[self.unit])
            sp.setSuffix(" " + self.unit)
            sp.setKeyboardTracking(False)
            val = w.height if kind == "h" else float(w.shape_params.get(key, 0.0))
            sp.setValue(un.to_unit(val, self.unit))
            sp.valueChanged.connect(lambda v, key=key, kind=kind: self._set(key, un.from_unit(v, self.unit), kind))
            self.form.addRow(label, sp)
        if k == "rect":
            self.form.addRow("", hint(f"{un.fmt_size(w.width, w.height, self.unit)} – change the size in "
                                      "Wall & Items."))
        self.preview.wall = w
        self.preview.update()

    def _set(self, key: str, value, kind: str = "b") -> None:
        w = self.wall
        if kind == "h":
            w.height = max(0.1, value)
        else:
            w.shape_params[key] = value
            w.height = wl.shape_height(w.shape, w.shape_params, w.height)
        self.preview.update()

    def result_wall(self) -> wl.Wall:
        w = self.wall
        if not w.shaped:
            w.shape, w.shape_params = "rect", {}
        for o in w.obstacles:
            o.clamp(w.width, w.height)
        return w
