"""
Measure from Photo.

  Photo (drag the 4 corners)  │  Straightened wall with sizes  │  Scale · result · items
  ─────────────────────────────────────────────────────────────────────────────────────
  Save Survey Sheet · Use in Wall Plan

The customer's photo is taken at an angle. Four corners plus ONE tape
measurement (or a known object such as an A4 sheet or a door) fix the size;
the second measurement, if given, is used as an accuracy check. Doors,
windows and furniture are found automatically and can be corrected by
dragging them on the straightened wall.
"""
from __future__ import annotations

import math
import shutil
import traceback
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

from app.core import imaging as im
from app.core import jobs
from app.core import measure as ms
from app.core import production as pr
from app.core import units as un
from app.core import wall as wl
from app.ui import share
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon, pil_to_qimage
from app.ui.worker import run_bg

BLUE = QColor("#1a73e8")
ORANGE = QColor("#f59e0b")
UNIT_CHOICES = [("m", "m"), ("cm", "cm"), ("mm", "mm"), ("feet + inches", "ftin"), ("feet", "ft"), ("inches", "in")]
WORK_MAX = 2000          # working copy of the photo (longest side, px)
FLAT_MAX = 1400          # straightened view


def _spin_unit(unit: str) -> str:
    return "in" if unit == "ftin" else unit


# ======================================================================
# Photo with draggable corners and a magnifier
# ======================================================================
class PhotoCanvas(QWidget):
    cornersChanged = Signal(bool)      # final?
    refChanged = Signal(bool)
    boxDrawn = Signal(object, object)  # (x, y, w, h) photo px, global QPoint
    itemClicked = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.img: Optional[QImage] = None
        self.corners: List[QPointF] = []
        self.ref: List[QPointF] = []
        self.show_ref = False
        self.items: list = []          # (poly np 4x2, colour, label, selected)
        self.labels = ("", "")         # top edge, left edge
        self.draw_mode = False
        self._zoom = 1.0
        self._centre: Optional[QPointF] = None
        self._drag = None
        self._cursor: Optional[QPointF] = None

    # ---------------- data ----------------
    def set_image(self, img: Optional[QImage]) -> None:
        self.img = img
        self._zoom = 1.0
        self._centre = None
        self.update()

    def fit(self) -> None:
        self._zoom = 1.0
        self._centre = None
        self.update()

    # ---------------- transforms ----------------
    def _scale(self) -> float:
        if self.img is None:
            return 1.0
        s0 = min((self.width() - 16) / self.img.width(), (self.height() - 16) / self.img.height())
        return max(1e-3, s0 * self._zoom)

    def _origin(self):
        s = self._scale()
        c = self._centre or QPointF(self.img.width() / 2, self.img.height() / 2)
        return self.width() / 2 - c.x() * s, self.height() / 2 - c.y() * s, s

    def to_screen(self, p) -> QPointF:
        ox, oy, s = self._origin()
        return QPointF(ox + p.x() * s, oy + p.y() * s)

    def to_img(self, q) -> QPointF:
        ox, oy, s = self._origin()
        return QPointF((q.x() - ox) / s, (q.y() - oy) / s)

    def _clamp(self, p: QPointF) -> QPointF:
        return QPointF(min(max(0.0, p.x()), self.img.width() - 1.0), min(max(0.0, p.y()), self.img.height() - 1.0))

    # ---------------- mouse ----------------
    def _hit(self, pos) -> Optional[tuple]:
        pts = [("ref", i, p) for i, p in enumerate(self.ref)] if self.show_ref else []
        pts += [("corner", i, p) for i, p in enumerate(self.corners)]
        best, bd = None, 16.0
        for kind, i, p in pts:
            d = math.hypot(self.to_screen(p).x() - pos.x(), self.to_screen(p).y() - pos.y())
            if d < bd:
                best, bd = (kind, i), d
        return best

    def mousePressEvent(self, ev) -> None:
        if self.img is None:
            return
        pos = ev.position()
        if ev.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag = ("pan", pos, self._centre or QPointF(self.img.width() / 2, self.img.height() / 2))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        h = self._hit(pos)
        if h:
            self._drag = h
            self._cursor = (self.ref if h[0] == "ref" else self.corners)[h[1]]
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.update()
            return
        if self.draw_mode:
            p = self._clamp(self.to_img(pos))
            self._drag = ("box", p, p)
            return
        ip = self.to_img(pos)
        for k, (poly, _c, _l, _s) in enumerate(self.items):
            if QPolygonF([QPointF(x, y) for x, y in poly]).containsPoint(ip, Qt.FillRule.OddEvenFill):
                self.itemClicked.emit(k)
                return
        if self._zoom > 1.0:
            self._drag = ("pan", pos, self._centre or QPointF(self.img.width() / 2, self.img.height() / 2))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, ev) -> None:
        if self.img is None:
            return
        pos = ev.position()
        d = self._drag
        if d is None:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self._hit(pos) else
                           Qt.CursorShape.CrossCursor if self.draw_mode else Qt.CursorShape.ArrowCursor)
            return
        if d[0] == "pan":
            s = self._scale()
            self._centre = QPointF(d[2].x() - (pos.x() - d[1].x()) / s, d[2].y() - (pos.y() - d[1].y()) / s)
            self.update()
        elif d[0] in ("corner", "ref"):
            p = self._clamp(self.to_img(pos))
            (self.ref if d[0] == "ref" else self.corners)[d[1]] = p
            self._cursor = p
            (self.refChanged if d[0] == "ref" else self.cornersChanged).emit(False)
            self.update()
        elif d[0] == "box":
            self._drag = ("box", d[1], self._clamp(self.to_img(pos)))
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        d = self._drag
        self._drag = None
        self._cursor = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if d is None:
            return
        if d[0] in ("corner", "ref"):
            (self.refChanged if d[0] == "ref" else self.cornersChanged).emit(True)
        elif d[0] == "box":
            a, b = d[1], d[2]
            x0, x1 = sorted((a.x(), b.x()))
            y0, y1 = sorted((a.y(), b.y()))
            if (x1 - x0) * self._scale() > 8 and (y1 - y0) * self._scale() > 8:
                self.boxDrawn.emit((x0, y0, x1 - x0, y1 - y0), ev.globalPosition().toPoint())
        self.update()

    def wheelEvent(self, ev) -> None:
        if self.img is None:
            return
        steps = ev.angleDelta().y() / 120.0
        before = self.to_img(ev.position())
        self._zoom = min(16.0, max(1.0, self._zoom * (1.2 ** steps)))
        if self._zoom <= 1.0001:
            self._centre = None
        else:
            after = self.to_img(ev.position())
            c = self._centre or QPointF(self.img.width() / 2, self.img.height() / 2)
            self._centre = QPointF(c.x() + before.x() - after.x(), c.y() + before.y() - after.y())
        self.update()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.fit()

    # ---------------- paint ----------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#eef1f5"))
        if self.img is None:
            p.setPen(QColor("#64748b"))
            f = p.font()
            f.setPointSizeF(11)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Choose a photo of the wall\n\nStand back so all four corners are in the picture.\n"
                       "Use the normal 1× camera, not 0.5× wide angle.")
            return
        ox, oy, s = self._origin()
        p.drawImage(QRectF(ox, oy, self.img.width() * s, self.img.height() * s), self.img)
        # items
        for poly, colour, label, sel in self.items:
            q = QPolygonF([self.to_screen(QPointF(x, y)) for x, y in poly])
            c = QColor(colour)
            fill = QColor(c)
            fill.setAlpha(70 if sel else 40)
            p.setBrush(fill)
            p.setPen(QPen(c, 3 if sel else 2))
            p.drawPolygon(q)
            self._chip(p, q.boundingRect().topLeft() + QPointF(4, 4), label, c)
        # wall outline
        if len(self.corners) == 4:
            q = QPolygonF([self.to_screen(c) for c in self.corners])
            p.setBrush(QColor(26, 115, 232, 26))
            p.setPen(QPen(BLUE, 2.5))
            p.drawPolygon(q)
            top, left = self.labels
            if top:
                self._chip(p, (q[0] + q[1]) / 2, top, BLUE, centre=True)
            if left:
                self._chip(p, (q[0] + q[3]) / 2, left, BLUE, centre=True)
        if self.show_ref and len(self.ref) == 4:
            q = QPolygonF([self.to_screen(c) for c in self.ref])
            p.setBrush(QColor(245, 158, 11, 50))
            p.setPen(QPen(ORANGE, 2))
            p.drawPolygon(q)
        # handles
        for i, c in enumerate(self.corners):
            self._handle(p, self.to_screen(c), str(i + 1), BLUE)
        if self.show_ref:
            for i, c in enumerate(self.ref):
                self._handle(p, self.to_screen(c), "", ORANGE, r=7)
        # box being drawn
        if self._drag and self._drag[0] == "box":
            a, b = self.to_screen(self._drag[1]), self.to_screen(self._drag[2])
            p.setBrush(QColor(26, 115, 232, 30))
            p.setPen(QPen(BLUE, 1.5, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(a, b).normalized())
        # magnifier while a corner is dragged
        if self._cursor is not None:
            self._loupe(p, self._cursor)

    def _chip(self, p: QPainter, at: QPointF, text: str, colour: QColor, centre: bool = False) -> None:
        if not text:
            return
        f = QFont(self.font())
        f.setPointSizeF(9)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 12, fm.height() + 4
        r = QRectF(at.x() - (w / 2 if centre else 0), at.y() - (h / 2 if centre else 0), w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _handle(self, p: QPainter, c: QPointF, label: str, colour: QColor, r: float = 10) -> None:
        p.setPen(QPen(QColor("white"), 2.5))
        p.setBrush(colour)
        p.drawEllipse(c, r, r)
        if label:
            f = QFont(self.font())
            f.setPointSizeF(8)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, label)

    def _loupe(self, p: QPainter, at: QPointF) -> None:
        R = 78
        sc = self.to_screen(at)
        cx = self.width() - R - 14 if sc.x() < self.width() / 2 else R + 14
        cy = R + 14
        centre = QPointF(cx, cy)
        ls = min(8.0, max(1.0, self._scale() * 4))
        path = QPainterPath()
        path.addEllipse(centre, R, R)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(cx - R, cy - R, 2 * R, 2 * R), QColor("#0f172a"))
        p.translate(centre)
        p.scale(ls, ls)
        p.translate(-at.x(), -at.y())
        p.drawImage(QPointF(0, 0), self.img)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 230), 1))
        p.drawLine(QPointF(cx - R, cy), QPointF(cx - 6, cy))
        p.drawLine(QPointF(cx + 6, cy), QPointF(cx + R, cy))
        p.drawLine(QPointF(cx, cy - R), QPointF(cx, cy - 6))
        p.drawLine(QPointF(cx, cy + 6), QPointF(cx, cy + R))
        p.setPen(QPen(BLUE, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(centre, 5, 5)
        p.setPen(QPen(QColor("white"), 4))
        p.drawEllipse(centre, R, R)
        p.setPen(QPen(QColor("#94a3b8"), 1))
        p.drawEllipse(centre, R + 2, R + 2)


# ======================================================================
# Straightened wall with items and dimension lines
# ======================================================================
class FlatCanvas(QWidget):
    changed = Signal(bool)        # final?
    selected = Signal(int)
    deleteRequested = Signal()
    contextRequested = Signal(int, object)

    ML, MT, MR, MB = 92, 86, 70, 64

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.img: Optional[QImage] = None
        self.wall: Optional[wl.Wall] = None
        self.unit = "m"
        self.sel = -1
        self.show_dims = True
        self.ruler_on = False
        self.ruler = None             # ((x, y), (x, y)) wall coords, y from the floor
        self._drag = None

    def set_data(self, img: Optional[QImage], wall: Optional[wl.Wall], unit: str) -> None:
        self.img, self.wall, self.unit = img, wall, unit
        if wall is None or self.sel >= len(wall.obstacles):
            self.sel = -1
        self.update()

    # ---------------- transforms ----------------
    def _geom(self):
        w = self.wall
        aw = max(10, self.width() - self.ML - self.MR)
        ah = max(10, self.height() - self.MT - self.MB)
        s = min(aw / max(w.width, 0.01), ah / max(w.height, 0.01))
        ox = self.ML + (aw - w.width * s) / 2
        oy = self.MT + (ah - w.height * s) / 2
        return ox, oy, s

    def X(self, m: float) -> float:
        ox, _oy, s = self._geom()
        return ox + m * s

    def Y(self, yf: float) -> float:
        _ox, oy, s = self._geom()
        return oy + (self.wall.height - yf) * s

    def to_wall(self, pos):
        ox, oy, s = self._geom()
        return (pos.x() - ox) / s, self.wall.height - (pos.y() - oy) / s

    def _rect(self, o: wl.Obstacle) -> QRectF:
        return QRectF(QPointF(self.X(o.x), self.Y(o.top)), QPointF(self.X(o.x + o.w), self.Y(o.y)))

    def _corners(self, o: wl.Obstacle):
        r = self._rect(o)
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    # ---------------- mouse ----------------
    def mousePressEvent(self, ev) -> None:
        if self.wall is None:
            return
        self.setFocus()
        pos = ev.position()
        wx, wy = self.to_wall(pos)
        if self.ruler_on and ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ("ruler",)
            self.ruler = ((wx, wy), (wx, wy))
            self.update()
            return
        if 0 <= self.sel < len(self.wall.obstacles):
            o = self.wall.obstacles[self.sel]
            for ci, c in enumerate(self._corners(o)):
                if abs(c.x() - pos.x()) < 9 and abs(c.y() - pos.y()) < 9:
                    self._drag = ("corner", self.sel, ci, (o.x, o.y, o.x + o.w, o.top))
                    return
        hit = -1
        for i in reversed(range(len(self.wall.obstacles))):
            if self._rect(self.wall.obstacles[i]).adjusted(-3, -3, 3, 3).contains(pos):
                hit = i
                break
        if hit != self.sel:
            self.sel = hit
            self.selected.emit(hit)
        if ev.button() == Qt.MouseButton.RightButton:
            self.contextRequested.emit(hit, ev.globalPosition().toPoint())
            self.update()
            return
        if hit >= 0:
            o = self.wall.obstacles[hit]
            self._drag = ("move", hit, (wx, wy), (o.x, o.y))
        self.update()

    def _snap(self, v: float, targets, tol: float = 0.03) -> float:
        for t in targets:
            if abs(v - t) < tol:
                return t
        return v

    def mouseMoveEvent(self, ev) -> None:
        if self.wall is None:
            return
        pos = ev.position()
        d = self._drag
        if d is None:
            cur = Qt.CursorShape.CrossCursor if self.ruler_on else Qt.CursorShape.ArrowCursor
            if not self.ruler_on and 0 <= self.sel < len(self.wall.obstacles):
                for c in self._corners(self.wall.obstacles[self.sel]):
                    if abs(c.x() - pos.x()) < 9 and abs(c.y() - pos.y()) < 9:
                        cur = Qt.CursorShape.SizeFDiagCursor
            if cur == Qt.CursorShape.ArrowCursor:
                for o in self.wall.obstacles:
                    if self._rect(o).contains(pos):
                        cur = Qt.CursorShape.SizeAllCursor
            self.setCursor(cur)
            return
        wx, wy = self.to_wall(pos)
        W, H = self.wall.width, self.wall.height
        if d[0] == "ruler":
            a = self.ruler[0]
            if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:     # straight lines
                if abs(wx - a[0]) > abs(wy - a[1]):
                    wy = a[1]
                else:
                    wx = a[0]
            self.ruler = (a, (wx, wy))
            self.update()
            return
        if d[0] == "move":
            o = self.wall.obstacles[d[1]]
            nx = d[3][0] + wx - d[2][0]
            ny = d[3][1] + wy - d[2][1]
            nx = self._snap(nx, (0.0,))
            nx = self._snap(nx + o.w, (W,)) - o.w
            ny = self._snap(ny, (0.0,))
            o.x, o.y = nx, ny
            o.clamp(W, H)
        elif d[0] == "corner":
            o = self.wall.obstacles[d[1]]
            x0, y0, x1, y1 = d[3]
            ci = d[2]
            sx = self._snap(wx, (0.0, W))
            sy = self._snap(wy, (0.0, H))
            if ci in (0, 3):
                x0 = min(sx, x1 - 0.02)
            else:
                x1 = max(sx, x0 + 0.02)
            if ci in (0, 1):
                y1 = max(sy, y0 + 0.02)
            else:
                y0 = min(sy, y1 - 0.02)
            o.x, o.y, o.w, o.h = x0, y0, x1 - x0, y1 - y0
            o.clamp(W, H)
        self.changed.emit(False)
        self.update()

    def mouseReleaseEvent(self, _ev) -> None:
        d = self._drag
        self._drag = None
        if d and d[0] in ("move", "corner"):
            self.changed.emit(True)
        self.update()

    def keyPressEvent(self, ev) -> None:
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel >= 0:
            self.deleteRequested.emit()
        elif ev.key() == Qt.Key.Key_Escape and self.ruler is not None:
            self.ruler = None
            self.update()
        else:
            super().keyPressEvent(ev)

    # ---------------- paint ----------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if self.wall is None:
            p.setPen(QColor("#64748b"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "The straightened wall appears here\nonce the corners and one size are set.")
            return
        w = self.wall
        wr = QRectF(QPointF(self.X(0), self.Y(w.height)), QPointF(self.X(w.width), self.Y(0)))
        if self.img is not None:
            p.drawImage(wr, self.img)
            p.fillRect(wr, QColor(255, 255, 255, 60))
        else:
            p.fillRect(wr, QColor("#f1f5f9"))
        p.setPen(QPen(QColor("#0f172a"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(wr)
        # floor line
        p.setPen(QPen(QColor("#475569"), 3))
        p.drawLine(QPointF(wr.left() - 12, wr.bottom()), QPointF(wr.right() + 12, wr.bottom()))
        for i, o in enumerate(w.obstacles):
            self._item(p, o, i == self.sel)
        if self.show_dims:
            for dm in self._dims():
                self._dim(p, dm)
        if self.ruler is not None:
            self._ruler(p)

    def _dims(self) -> List[ms.Dim]:
        """Wall size and the chain of openings always; item details for the selected item."""
        w, u = self.wall, self.unit
        out = [d for d in ms.wall_dimensions(w, u) if d.level >= 1 and d.side != "bottom"]
        f = lambda m: un.fmt(m, u) if u != "m" else f"{m:.2f} m"
        for i, o in enumerate(w.obstacles):
            sel = i == self.sel
            if o.in_front:
                out.append(ms.Dim(o.x, 0, o.x + o.w, 0, f"{o.name.lower()} {f(o.w)}", o.colour, 1, "bottom"))
                if sel:
                    out.append(ms.Dim(o.x, max(0.0, o.y), o.x, o.top, f(o.h), o.colour, 0, "left"))
                continue
            if o.kind == "socket" and not sel:
                continue
            out.append(ms.Dim(o.x + o.w, o.y, o.x + o.w, o.top, f(o.h), o.colour, 0, "right"))
            if sel or o.kind == "window":
                if o.y > 0.03:
                    out.append(ms.Dim(o.x, 0, o.x, o.y, (f"sill {f(o.y)}" if o.kind == "window" else f(o.y)),
                                      o.colour, 0, "left"))
            if sel and w.height - o.top > 0.03:
                out.append(ms.Dim(o.x + o.w, o.top, o.x + o.w, w.height, un.fmt_short(w.height - o.top, u),
                                  o.colour, 0, "right"))
            if sel and o.kind == "socket":
                out.append(ms.Dim(o.x, o.y, o.x + o.w, o.y, f(o.w), o.colour, 0, "bottom"))
        return out

    def _font(self, size=9.0, bold=True) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(size)
        f.setBold(bold)
        return f

    def _pill(self, p: QPainter, centre: QPointF, text: str, colour: QColor, fg=QColor("white")) -> QRectF:
        f = self._font(8.6)
        p.setFont(f)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 10, fm.height() + 2
        r = QRectF(centre.x() - w / 2, centre.y() - h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawRoundedRect(r, 4, 4)
        p.setPen(fg)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        return r

    def _item(self, p: QPainter, o: wl.Obstacle, sel: bool) -> None:
        r = self._rect(o)
        c = QColor(o.colour)
        fill = QColor(c)
        fill.setAlpha(80 if sel else 45)
        p.setBrush(fill)
        pen = QPen(c, 3 if sel else 2)
        if o.in_front:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(r)
        txt = o.name + ("  · AI" if o.source == "detected" else "")
        f = self._font(9)
        p.setFont(f)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(txt) + 12
        chip = QRectF(r.left() + 4, r.top() + 4, min(tw, max(40.0, r.width() - 8)), fm.height() + 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(chip, 4, 4)
        p.setPen(QColor("white"))
        p.drawText(chip.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(txt, Qt.TextElideMode.ElideRight, int(chip.width() - 10)))
        if sel:
            p.setPen(QPen(QColor("white"), 1.5))
            p.setBrush(c)
            for q in self._corners(o):
                p.drawRect(QRectF(q.x() - 5, q.y() - 5, 10, 10))

    def _dim(self, p: QPainter, dm: ms.Dim) -> None:
        c = QColor(dm.colour)
        p.setPen(QPen(c, 1.6))
        tick = 6
        if dm.side in ("top", "bottom"):
            x0, x1 = self.X(dm.x0), self.X(dm.x1)
            if dm.side == "top":
                y = self.Y(self.wall.height) - 16 - 26 * (dm.level - 1) if dm.level >= 1 else self.Y(dm.y0) - 12
            else:
                y = self.Y(0) + 18 + 24 * (dm.level - 1) if dm.level >= 1 else self.Y(dm.y0) + 12
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
            for x in (x0, x1):
                p.drawLine(QPointF(x, y - tick), QPointF(x, y + tick))
                p.drawLine(QPointF(x - 3, y + 3), QPointF(x + 3, y - 3))
            if x1 - x0 > 14:
                self._pill(p, QPointF((x0 + x1) / 2, y), dm.text, QColor("white"), c).adjusted(0, 0, 0, 0)
        else:
            y0, y1 = self.Y(dm.y0), self.Y(dm.y1)
            if dm.side == "left":
                x = self.X(0) - 18 - 26 * (dm.level - 1) if dm.level >= 1 else self.X(dm.x0) - 10
            else:
                x = self.X(self.wall.width) + 18 + 26 * (dm.level - 1) if dm.level >= 1 else self.X(dm.x0) + 10
            p.drawLine(QPointF(x, y0), QPointF(x, y1))
            for y in (y0, y1):
                p.drawLine(QPointF(x - tick, y), QPointF(x + tick, y))
                p.drawLine(QPointF(x - 3, y + 3), QPointF(x + 3, y - 3))
            if abs(y1 - y0) > 14:
                self._pill(p, QPointF(x, (y0 + y1) / 2), dm.text, QColor("white"), c)

    def _ruler(self, p: QPainter) -> None:
        (ax, ay), (bx, by) = self.ruler
        a, b = QPointF(self.X(ax), self.Y(ay)), QPointF(self.X(bx), self.Y(by))
        p.setPen(QPen(QColor("#dc2626"), 2.2))
        p.drawLine(a, b)
        for q in (a, b):
            p.setBrush(QColor("#dc2626"))
            p.drawEllipse(q, 4, 4)
        dist = math.hypot(bx - ax, by - ay)
        if dist > 0.001:
            self._pill(p, (a + b) / 2 + QPointF(0, -14), un.fmt(dist, self.unit), QColor("#dc2626"))

    def ruler_length(self) -> float:
        if self.ruler is None:
            return 0.0
        (ax, ay), (bx, by) = self.ruler
        return math.hypot(bx - ax, by - ay)


# ======================================================================
# Dialog
# ======================================================================
class MeasureDialog(SheetDialog):
    def __init__(self, studio, job: wl.Job, wall_index: int, job_dir: Optional[Path]):
        super().__init__(studio.window(), "camera", "Measure from Photo",
                         "Drag the 4 blue corners onto the wall corners and enter one tape measurement. "
                         "Doors, windows and furniture are found and measured for you.", size=(1640, 960))
        self.studio, self.job, self.wi, self.job_dir = studio, job, wall_index, job_dir
        self.applied = False
        self.result_wall: Optional[wl.Wall] = None
        self.wall = wl.Wall.from_dict(job.walls[wall_index].to_dict())
        self.unit = job.unit if job.unit in dict((v, k) for k, v in UNIT_CHOICES) else "m"
        self.photo_path: Optional[Path] = None
        self.work: Optional[Image.Image] = None
        self.orig: Optional[Image.Image] = None     # working copy before lens straightening
        self.k1 = 0.0                                # lens straightening applied to `work`
        self.k = 1.0
        self.focal: Optional[float] = None
        self.res: Optional[ms.SurveyResult] = None
        self.flat: Optional[Image.Image] = None
        self.ppm = 0.0
        self.anchors: Dict[str, np.ndarray] = {}
        self._busy = False
        self._loading = False
        self.t_solve = QTimer(self, singleShot=True, interval=60, timeout=lambda: self._solve(final=False))
        self._build()
        self._load_existing()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(16)
        # ---- photo ----
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addLayout(self._pane_head("1", "Customer's photo", "drag the corners · scroll to zoom"))
        tb = QHBoxLayout()
        tb.setSpacing(8)
        b = QPushButton(icon("image"), " Photo…")
        b.setToolTip("Choose a photo of the wall")
        b.clicked.connect(self.choose_photo)
        tb.addWidget(b)
        self.btn_corners = QPushButton(icon("sparkle"), " Find corners")
        self.btn_corners.setToolTip("Place the 4 corners automatically from the edges of the wall – then check them")
        self.btn_corners.clicked.connect(lambda: self.auto_corners(force=True))
        tb.addWidget(self.btn_corners)
        self.btn_lens = QPushButton(icon("frame"), " Lens fix")
        self.btn_lens.setCheckable(True)
        self.btn_lens.setToolTip("Straighten lines bent by a wide-angle (0.5×) camera")
        self.btn_lens.toggled.connect(self._on_lens_toggled)
        tb.addWidget(self.btn_lens)
        self.btn_draw = QPushButton(icon("plus"), " Draw item")
        self.btn_draw.setCheckable(True)
        self.btn_draw.setToolTip("Drag a box round a door, window, sofa… on the photo to measure it")
        self.btn_draw.toggled.connect(self._on_draw_mode)
        tb.addWidget(self.btn_draw)
        self._tool_btns = [b, self.btn_corners, self.btn_lens, self.btn_draw]
        tb.addStretch()
        bf = QToolButton()
        bf.setObjectName("IconBtn")
        bf.setIcon(icon("fit"))
        bf.setToolTip("Fit the photo")
        bf.clicked.connect(lambda: self.photo.fit())
        tb.addWidget(bf)
        left.addLayout(tb)
        self.photo = PhotoCanvas()
        self.photo.setStyleSheet("border-radius:10px;")
        self.photo.cornersChanged.connect(self._on_corners)
        self.photo.refChanged.connect(self._on_corners)
        self.photo.boxDrawn.connect(self._on_box)
        self.photo.itemClicked.connect(self._select_item)
        left.addWidget(self.photo, 1)
        self.lens_row = QWidget()
        lr = QHBoxLayout(self.lens_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addWidget(QLabel("Lens straightening"))
        self.sl_lens = QSlider(Qt.Orientation.Horizontal)
        self.sl_lens.setRange(-50, 15)
        self.sl_lens.setToolTip("Move until the wall edges, door frames and the ceiling line look straight")
        self.sl_lens.sliderReleased.connect(lambda: self._set_lens(self.sl_lens.value() / 100.0))
        self.sl_lens.valueChanged.connect(lambda v: self.lbl_lens.setText(f"{v / 100:+.2f}"))
        lr.addWidget(self.sl_lens, 1)
        self.lbl_lens = QLabel("0.00")
        self.lbl_lens.setFixedWidth(40)
        lr.addWidget(self.lbl_lens)
        b_auto = QPushButton("Auto")
        b_auto.clicked.connect(self.auto_lens)
        lr.addWidget(b_auto)
        self.lens_row.setVisible(False)
        left.addWidget(self.lens_row)
        self.lbl_photo = hint("")
        left.addWidget(self.lbl_photo)
        row.addLayout(left, 10)
        # ---- straightened ----
        mid = QVBoxLayout()
        mid.setSpacing(8)
        mid.addLayout(self._pane_head("2", "Straightened wall", "drag items to correct them"))
        tb2 = QHBoxLayout()
        tb2.setSpacing(8)
        self.btn_ruler = QPushButton(icon("ruler"), "  Measure a distance")
        self.btn_ruler.setCheckable(True)
        self.btn_ruler.setToolTip("Drag on the wall to measure anything (hold Shift for a straight line)")
        self.btn_ruler.toggled.connect(self._on_ruler)
        tb2.addWidget(self.btn_ruler)
        self._tool_btns.append(self.btn_ruler)
        self.chk_dims = QCheckBox("Dimension lines")
        self.chk_dims.setChecked(True)
        self.chk_dims.toggled.connect(lambda on: (setattr(self.flatc, "show_dims", on), self.flatc.update()))
        tb2.addWidget(self.chk_dims)
        tb2.addStretch()
        self.lbl_units = QLabel("Units")
        tb2.addWidget(self.lbl_units)
        self.cb_unit = QComboBox()
        for t, v in UNIT_CHOICES:
            self.cb_unit.addItem(t, v)
        self.cb_unit.setCurrentIndex(max(0, self.cb_unit.findData(self.unit)))
        self.cb_unit.currentIndexChanged.connect(self._on_unit)
        tb2.addWidget(self.cb_unit)
        mid.addLayout(tb2)
        self.flatc = FlatCanvas()
        self.flatc.changed.connect(self._on_flat_changed)
        self.flatc.selected.connect(self._select_item)
        self.flatc.deleteRequested.connect(self.remove_item)
        self.flatc.contextRequested.connect(self._item_menu)
        frame = QFrame()
        frame.setObjectName("InfoBox")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(4, 4, 4, 4)
        fl.addWidget(self.flatc)
        mid.addWidget(frame, 1)
        self.lbl_ruler = hint("")
        mid.addWidget(self.lbl_ruler)
        row.addLayout(mid, 11)
        # ---- side panel ----
        side_w = QWidget()
        side_w.setObjectName("LeftInner")
        side = QVBoxLayout(side_w)
        side.setContentsMargins(0, 0, 4, 0)
        side.setSpacing(10)
        side.addWidget(self._section("3", "Size"))
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.scale_group = QButtonGroup(self)
        for i, t in enumerate(("Tape measure", "Known object")):
            bt = QPushButton(t)
            bt.setObjectName("SegBtn")
            bt.setCheckable(True)
            bt.setStyleSheet("border-top-left-radius:8px;border-bottom-left-radius:8px;" if i == 0 else
                             "border-top-right-radius:8px;border-bottom-right-radius:8px;")
            self.scale_group.addButton(bt, i)
            seg.addWidget(bt)
        self.scale_group.button(0).setChecked(True)
        self.scale_group.idClicked.connect(self._on_scale_mode)
        side.addLayout(seg)
        # tape
        self.tape_box = QWidget()
        g = QGridLayout(self.tape_box)
        g.setContentsMargins(0, 2, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.ed_w = QLineEdit()
        self.ed_h = QLineEdit()
        for r, (lab, ed) in enumerate((("Width", self.ed_w), ("Height", self.ed_h))):
            g.addWidget(QLabel(lab), r, 0)
            ed.setPlaceholderText("e.g. 4.2 m, 420 cm, 13' 9\"")
            ed.textChanged.connect(lambda _t: self.t_solve.start())
            ed.editingFinished.connect(lambda: self._solve(final=True))
            g.addWidget(ed, r, 1)
        self.lbl_tape = hint("Measure one side with a tape. Enter both and the photo checks your accuracy.")
        self.lbl_tape.setWordWrap(True)
        g.addWidget(self.lbl_tape, 2, 0, 1, 2)
        side.addWidget(self.tape_box)
        # reference
        self.ref_box = QWidget()
        rl = QVBoxLayout(self.ref_box)
        rl.setContentsMargins(0, 2, 0, 0)
        rl.setSpacing(6)
        self.cb_ref = QComboBox()
        for k in ms.REFERENCES:
            self.cb_ref.addItem(k)
        self.cb_ref.addItem("Other size…")
        self.cb_ref.currentIndexChanged.connect(self._on_ref_kind)
        rl.addWidget(self.cb_ref)
        h = hint("Something on the wall you know the size of. Drag the 4 orange points onto its corners.")
        h.setWordWrap(True)
        rl.addWidget(h)
        self.ref_box.setVisible(False)
        side.addWidget(self.ref_box)
        self._custom_ref = (0.2, 0.2)
        # result
        box = QFrame()
        box.setObjectName("InfoBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 10, 14, 12)
        bl.setSpacing(3)
        lab = QLabel("Wall size")
        lab.setObjectName("InfoLabel")
        bl.addWidget(lab)
        self.lbl_size = QLabel("—")
        self.lbl_size.setObjectName("InfoValue")
        bl.addWidget(self.lbl_size)
        self.lbl_alt = QLabel("")
        self.lbl_alt.setObjectName("InfoAlt")
        self.lbl_alt.setWordWrap(True)
        bl.addWidget(self.lbl_alt)
        self.lbl_acc = QLabel("")
        self.lbl_acc.setWordWrap(True)
        bl.addWidget(self.lbl_acc)
        side.addWidget(box)
        # items
        side.addWidget(self._section("4", "Doors, windows & furniture"))
        self.btn_find = QPushButton(icon("sparkle", "#ffffff"), "  Find them automatically")
        self.btn_find.setObjectName("AIButton")
        self.btn_find.setMinimumHeight(42)
        self.btn_find.clicked.connect(self.auto_detect)
        side.addWidget(self.btn_find)
        self.list_items = QListWidget()
        self.list_items.setMinimumHeight(130)
        self.list_items.currentRowChanged.connect(self._on_item_row)
        side.addWidget(self.list_items, 1)
        ib = QHBoxLayout()
        ib.setSpacing(6)
        badd = QPushButton(icon("plus"), " Add")
        m = QMenu(badd)
        for kind, (label, _f, _c) in wl.OBSTACLE_KINDS.items():
            m.addAction(label, lambda k=kind: self.add_item(k))
        badd.setMenu(m)
        ib.addWidget(badd)
        brm = QPushButton(icon("trash"), " Remove")
        brm.clicked.connect(self.remove_item)
        ib.addWidget(brm)
        ib.addStretch()
        side.addLayout(ib)
        self.item_form = QWidget()
        fg = QGridLayout(self.item_form)
        fg.setContentsMargins(0, 0, 0, 0)
        fg.setHorizontalSpacing(8)
        fg.setVerticalSpacing(6)
        self.cb_kind = QComboBox()
        for kind, (label, _f, _c) in wl.OBSTACLE_KINDS.items():
            self.cb_kind.addItem(label, kind)
        self.cb_kind.currentIndexChanged.connect(lambda _i: self._set_item("kind", self.cb_kind.currentData()))
        fg.addWidget(QLabel("Item"), 0, 0)
        fg.addWidget(self.cb_kind, 0, 1, 1, 3)
        fg.setColumnStretch(1, 1)
        fg.setColumnStretch(3, 1)
        self.sp = {}
        for i, (key, lab) in enumerate((("w", "Width"), ("h", "Height"), ("x", "From left"), ("y", "From floor"))):
            s = QDoubleSpinBox()
            s.setKeyboardTracking(False)
            s.setRange(0, 99999)
            s.setMinimumWidth(80)
            s.valueChanged.connect(lambda v, k=key: self._set_item(k, v))
            self.sp[key] = s
            lb = QLabel(lab)
            lb.setObjectName("Hint")
            fg.addWidget(lb, 1 + (i // 2) * 2, (i % 2) * 2, 1, 2)
            fg.addWidget(s, 2 + (i // 2) * 2, (i % 2) * 2, 1, 2)
        self.chk_front = QCheckBox("In front of the wall (furniture)")
        self.chk_front.toggled.connect(lambda on: self._set_item("in_front", on))
        fg.addWidget(self.chk_front, 5, 0, 1, 4)
        side.addWidget(self.item_form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(side_w)
        scroll.setFixedWidth(372)
        row.addWidget(scroll)
        self.body.addLayout(row, 1)
        # ---- buttons ----
        bot = QHBoxLayout()
        bot.setSpacing(12)
        self.lbl_status = hint("")
        self.lbl_status.setWordWrap(True)
        bot.addWidget(self.lbl_status, 1)
        b_long = QPushButton("Wall too long for one photo?")
        b_long.setObjectName("LinkBtn")
        b_long.clicked.connect(self._long_wall_help)
        bot.addWidget(b_long)
        b1 = QPushButton(icon("doc"), "  Save Survey Sheet")
        b1.setObjectName("Light")
        b1.clicked.connect(self.save_survey)
        bot.addWidget(b1)
        b2 = QPushButton(icon("wall", "#ffffff"), "  Use in Wall Plan")
        b2.setObjectName("Go")
        b2.clicked.connect(self.apply)
        bot.addWidget(b2)
        b3 = QPushButton("Cancel")
        b3.setObjectName("Light")
        b3.clicked.connect(self.reject)
        bot.addWidget(b3)
        self.body.addLayout(bot)
        self._refresh_items()

    def _pane_head(self, n: str, title: str, tip: str) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(8)
        num = QLabel(n)
        num.setFixedSize(24, 24)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setStyleSheet("background:#0f172a;color:white;border-radius:12px;font-weight:700;")
        h.addWidget(num)
        t = QLabel(title)
        t.setObjectName("PaneTitle")
        h.addWidget(t)
        tl = hint(tip)
        h.addWidget(tl)
        self._pane_tips = getattr(self, "_pane_tips", []) + [tl]
        h.addStretch()
        return h

    # ---- narrow screens: icon-only tool buttons (names stay in the tooltips) ----
    def _label(self, btn, text: str) -> None:
        btn.setProperty("full_text", text)
        btn.setText("" if getattr(self, "_compact", False) else text)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        compact = self.width() < 1560
        if compact == getattr(self, "_compact", None):
            return
        self._compact = compact
        for b in getattr(self, "_tool_btns", []):
            full = b.property("full_text")
            if full is None:
                full = b.text()
                b.setProperty("full_text", full)
                if full.strip() and full.strip() not in (b.toolTip() or ""):
                    b.setToolTip(f"{full.strip()}: {b.toolTip()}" if b.toolTip() else full.strip())
            b.setText("" if compact else full)
        for tl in getattr(self, "_pane_tips", []):
            tl.setVisible(not compact)
        if hasattr(self, "lbl_units"):
            self.lbl_units.setVisible(not compact)

    def _section(self, n: str, title: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 4, 0, 0)
        h.setSpacing(8)
        num = QLabel(n)
        num.setFixedSize(24, 24)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setStyleSheet("background:#0f172a;color:white;border-radius:12px;font-weight:700;")
        h.addWidget(num)
        t = QLabel(title)
        t.setObjectName("PaneTitle")
        h.addWidget(t, 1)
        return w

    # ------------------------------------------------------------------
    # Photo
    # ------------------------------------------------------------------
    def _load_existing(self) -> None:
        w = self.wall
        sv = w.survey or {}
        self._loading = True
        if sv.get("tape_w"):
            self.ed_w.setText(un.fmt(sv["tape_w"], self.unit))
        if sv.get("tape_h"):
            self.ed_h.setText(un.fmt(sv["tape_h"], self.unit))
        if sv.get("reference"):
            self.scale_group.button(1).setChecked(True)
            k = self.cb_ref.findText(sv["reference"])
            if k >= 0:
                self.cb_ref.setCurrentIndex(k)
            self._custom_ref = tuple(sv.get("reference_size") or self._custom_ref)
            self._on_scale_mode(1, solve=False)
        self._loading = False
        if w.photo and self.job_dir and (self.job_dir / w.photo).is_file():
            corners = w.corners if len(w.corners) == 4 else None
            self._set_photo(self.job_dir / w.photo, corners, keep_items=True,
                            ref_full=sv.get("reference_quad"))
        else:
            if not (sv.get("tape_w") or sv.get("tape_h")):
                self.ed_w.setText(un.fmt(w.width, self.unit))
            self.lbl_status.setText("Choose a photo of the wall to start.")

    def choose_photo(self) -> None:
        start = self.studio.settings.value("last_photo_dir", str(Path.home() / "Pictures"))
        exts = " ".join("*" + e for e in im.supported_input_extensions())
        path, _ = QFileDialog.getOpenFileName(self, "Choose a photo of the wall", str(start), f"Photos ({exts})")
        if not path:
            return
        self.studio.settings.setValue("last_photo_dir", str(Path(path).parent))
        keep = False
        if self.wall.obstacles:
            keep = QMessageBox.question(self, "Measure from photo", "Keep the doors, windows and furniture "
                                        "already on this wall?") == QMessageBox.StandardButton.Yes
        self._set_photo(Path(path), None, keep_items=keep, clear_items=not keep)

    def _set_photo(self, path: Path, corners_full, keep_items: bool, ref_full=None,
                   clear_items: bool = False) -> None:
        try:
            full, focal = ms.load_photo(path)
        except Exception as exc:
            QMessageBox.warning(self, "Photo", im.load_error_text(path, exc))
            return
        if clear_items:                    # only once the new photo has opened
            self.wall.obstacles = []
        self.photo_path = path
        self.k = min(1.0, WORK_MAX / max(full.size))
        self.work = full if self.k >= 1 else full.resize((round(full.width * self.k), round(full.height * self.k)),
                                                          Image.Resampling.LANCZOS)
        self.focal = focal * self.k if focal else None
        self.orig = self.work
        self.k1 = 0.0
        self.f35 = None
        try:
            with Image.open(path) as _im:
                self.f35 = ms.exif_focal_35(_im)
        except Exception:
            pass
        self.btn_lens.blockSignals(True)
        self.btn_lens.setChecked(False)
        self.btn_lens.blockSignals(False)
        self.lens_row.setVisible(False)
        self.sl_lens.setValue(0)
        self.photo.set_image(pil_to_qimage(self.work))
        W, H = self.work.size
        if corners_full:
            self.photo.corners = [QPointF(x * self.k, y * self.k) for x, y in ms.order_corners(corners_full)]
        else:
            mx, my = W * 0.12, H * 0.12
            self.photo.corners = [QPointF(mx, my), QPointF(W - mx, my), QPointF(W - mx, H - my), QPointF(mx, H - my)]
        if ref_full and len(ref_full) == 4:
            self.photo.ref = [QPointF(x * self.k, y * self.k) for x, y in ref_full]
        else:
            self._default_ref()
        self.lbl_photo.setText(f"{path.name} · {full.width} × {full.height} px"
                               + (" · lens from photo data" if focal else ""))
        self.anchors = {}
        self.res = None
        self._solve(final=True, anchor_all=True)
        if not keep_items or not self.wall.obstacles:
            self.lbl_status.setText("Drag the 4 blue corners onto the corners of the wall, then press "
                                    "‘Find them automatically’.")
        if not corners_full:
            # new photo: straighten an ultra-wide shot, then place the corners automatically
            if self.f35 and self.f35 < 20:
                self.btn_lens.setChecked(True)          # runs auto lens, then the corners
            else:
                self.auto_corners()

    # ---------------- automatic corners & lens straightening ----------------
    def auto_corners(self, force: bool = False) -> None:
        if self.work is None:
            return
        img = self.work
        self.btn_corners.setEnabled(False)
        self._label(self.btn_corners, " Looking…")

        def done(r):
            self.btn_corners.setEnabled(True)
            self._label(self.btn_corners, " Find corners")
            if self.work is not img:
                return
            if r is None:
                if force:
                    self.lbl_status.setText("Couldn't find the wall edges in this photo – drag the 4 corners by hand.")
                return
            pts, _conf = r
            self.photo.corners = [QPointF(x, y) for x, y in pts]
            self._default_ref()
            self.photo.update()
            self._solve(final=True)
            self.lbl_status.setText("Corners placed automatically – check each one (the magnifier shows it close up) "
                                    "and drag if needed.")

        def failed(_m):
            self.btn_corners.setEnabled(True)
            self._label(self.btn_corners, " Find corners")

        run_bg(lambda _p: ms.find_wall_corners(img), done, failed)

    def _on_lens_toggled(self, on: bool) -> None:
        self.lens_row.setVisible(on)
        if on:
            self.auto_lens(then_corners=True)
        else:
            self._set_lens(0.0)

    def auto_lens(self, then_corners: bool = False) -> None:
        if self.orig is None:
            return
        img = self.orig
        self.lbl_status.setText("Checking the lens…")

        def done(r):
            if self.orig is not img:
                return
            k1, gain = r
            if gain < 1.04:
                k1 = 0.0
            self.sl_lens.blockSignals(True)
            self.sl_lens.setValue(int(round(k1 * 100)))
            self.sl_lens.blockSignals(False)
            self.lbl_lens.setText(f"{k1:+.2f}")
            self._set_lens(k1)
            self.lbl_status.setText("Lens straightened – walls and frames should now be straight." if k1 else
                                    "The lines are already straight – no lens fix needed.")
            if then_corners:
                self.auto_corners()

        run_bg(lambda _p: ms.estimate_lens(img), done, lambda m: self.lbl_status.setText(""))

    def _set_lens(self, k1: float) -> None:
        if self.orig is None or abs(k1 - self.k1) < 1e-4:
            return
        size = self.orig.size
        # keep the corners on the same spots of the photo
        def remap(qpts):
            if not qpts:
                return qpts
            pts = np.array([(q.x(), q.y()) for q in qpts])
            raw = ms.lens_distort_points(pts, size, self.k1)
            new = ms.lens_undistort_points(raw, size, k1)
            return [QPointF(float(x), float(y)) for x, y in new]
        self.photo.corners = remap(self.photo.corners)
        self.photo.ref = remap(self.photo.ref)
        self.k1 = k1
        self.work = ms.undistort(self.orig, k1)
        self.photo.img = pil_to_qimage(self.work)
        self.photo.update()
        self._solve(final=True, anchor_all=True)

    def _default_ref(self) -> None:
        if self.work is None:
            return
        cs = self.photo.corners
        cx = sum(p.x() for p in cs) / 4
        cy = sum(p.y() for p in cs) / 4
        d = min(self.work.size) * 0.06
        self.photo.ref = [QPointF(cx - d, cy - d * 1.4), QPointF(cx + d, cy - d * 1.4),
                          QPointF(cx + d, cy + d * 1.4), QPointF(cx - d, cy + d * 1.4)]

    # ------------------------------------------------------------------
    # Solving
    # ------------------------------------------------------------------
    def _tape(self, ed: QLineEdit) -> float:
        t = ed.text().strip()
        if not t:
            return 0.0
        try:
            v = un.parse_length(t, self.unit)
            return v if v > 0 else 0.0
        except ValueError:
            return -1.0

    def _ref_size(self):
        t = self.cb_ref.currentText()
        return ms.REFERENCES.get(t, self._custom_ref)

    def _survey(self) -> ms.Survey:
        corners = [(p.x(), p.y()) for p in self.photo.corners]
        s = ms.Survey(self.work.size, corners, focal_px=self.focal)
        if self.scale_group.checkedId() == 1:
            s.reference = self.cb_ref.currentText()
            s.reference_size = self._ref_size()
            s.reference_quad = [(p.x(), p.y()) for p in self.photo.ref]
        else:
            s.width = max(0.0, self._tape(self.ed_w))
            s.height = max(0.0, self._tape(self.ed_h))
        return s

    def _solve(self, final: bool = True, anchor_all: bool = False) -> None:
        if self.work is None or self._loading:
            self._update_tape_hint()
            return
        bad = [n for n, ed in (("width", self.ed_w), ("height", self.ed_h)) if self._tape(ed) < 0]
        try:
            res = ms.solve(self._survey())
            if not (math.isfinite(res.width) and math.isfinite(res.height)) or res.width <= 0 or res.height <= 0:
                raise ValueError("The corners do not make a wall shape – drag them onto the 4 corners.")
        except Exception as exc:
            self.res = None
            self.lbl_size.setText("—")
            self.lbl_alt.setText(str(exc) if isinstance(exc, ValueError) else "Drag the corners onto the wall.")
            self.lbl_acc.setText("")
            self.photo.labels = ("", "")
            self.photo.update()
            self._update_tape_hint(bad)
            return
        self.res = res
        self.wall.width, self.wall.height = res.width, res.height
        if anchor_all:
            for o in self.wall.obstacles:
                self.anchors[o.id] = self._anchor(o)
        else:
            for o in self.wall.obstacles:
                if o.id in self.anchors:
                    self._from_anchor(o)
        self._update_result(bad)
        if final:
            self._rectify()
        self._refresh_views()

    def _rectify(self) -> None:
        if self.res is None:
            return
        try:
            self.flat, self.ppm = ms.rectify(self.work, self.res, max_side=FLAT_MAX)
        except Exception:
            traceback.print_exc()
            self.flat = None

    def _update_tape_hint(self, bad=()) -> None:
        if bad:
            self.lbl_tape.setText(f"Could not read the {' and '.join(bad)}. Try 4.2, 420 cm or 13' 9\".")
            self.lbl_tape.setObjectName("Warn")
        else:
            self.lbl_tape.setText("Measure one side with a tape. Enter both and the photo checks your accuracy.")
            self.lbl_tape.setObjectName("Hint")
        self.lbl_tape.style().unpolish(self.lbl_tape)
        self.lbl_tape.style().polish(self.lbl_tape)

    def _update_result(self, bad=()) -> None:
        r, w, u = self.res, self.wall, self.unit
        self.lbl_size.setText(un.fmt_size(w.width, w.height, u))
        alt = un.fmt_size(w.width, w.height, "ftin") if u != "ftin" else un.fmt_size(w.width, w.height, "cm")
        self.lbl_alt.setText(f"{alt} · {un.fmt_area_both(w.area())}")
        if r.accuracy_pct is None:
            colour, txt = "#475569", r.accuracy_text(u)
        else:
            a = r.accuracy_pct
            colour = "#15803d" if a < 3 else "#b45309" if a < 6 else "#dc2626"
            other = "height" if self.scale_group.checkedId() == 0 else "size"
            pred = f" (photo says {other} {un.fmt(r.predicted, u)})" if r.predicted and self.scale_group.checkedId() == 0 \
                else ""
            txt = r.accuracy_text(u) + pred
        how = {"tape width + height": "Size from your width; height checked", "tape width": "Size from your width",
               "tape height": "Size from your height"}.get(r.scale_from, f"Size from the {r.scale_from}")
        self.lbl_acc.setText(f"<span style='color:{colour};font-weight:600'>{txt}</span><br>"
                             f"<span style='color:#64748b'>{how} · perspective: {r.method}</span>")
        self.photo.labels = (un.fmt(w.width, u), un.fmt(w.height, u))
        self._update_tape_hint(bad)

    # ---------------- item anchors (keep items glued to the photo) ----------------
    def _anchor(self, o: wl.Obstacle) -> np.ndarray:
        return ms.wall_to_photo(self.res, [(o.x, o.y), (o.x + o.w, o.y), (o.x + o.w, o.top), (o.x, o.top)])

    def _from_anchor(self, o: wl.Obstacle) -> None:
        q = ms.apply_h(self.res.H, self.anchors[o.id])
        x0, x1 = float(q[:, 0].min()), float(q[:, 0].max())
        y0, y1 = float(q[:, 1].min()), float(q[:, 1].max())
        o.x, o.w = x0, max(0.02, x1 - x0)
        o.y, o.h = self.res.height - y1, max(0.02, y1 - y0)
        o.clamp(self.wall.width, self.wall.height)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    def _refresh_views(self) -> None:
        if self.res is None:
            self.flatc.set_data(None, None, self.unit)
            return
        self.flatc.set_data(pil_to_qimage(self.flat) if self.flat is not None else None, self.wall, self.unit)
        sel = self.list_items.currentRow()
        items = []
        for i, o in enumerate(self.wall.obstacles):
            try:
                poly = ms.wall_to_photo(self.res, [(o.x, o.y), (o.x + o.w, o.y), (o.x + o.w, o.top), (o.x, o.top)])
                poly = poly[[3, 2, 1, 0]]
            except Exception:
                continue
            items.append((poly, o.colour, f"{o.name} {un.fmt_size(o.w, o.h, self.unit)}", i == sel))
        self.photo.items = items
        self.photo.update()
        if self.flatc.ruler is not None:
            self.lbl_ruler.setText(f"Distance: {un.fmt(self.flatc.ruler_length(), self.unit)}")

    def _refresh_items(self, select: Optional[int] = None) -> None:
        cur = self.list_items.currentRow() if select is None else select
        self.list_items.blockSignals(True)
        self.list_items.clear()
        for o in self.wall.obstacles:
            it = QListWidgetItem(icon("door" if not o.in_front else "sofa", o.colour),
                                 f"{o.name}  ·  {un.fmt_size(o.w, o.h, self.unit)}"
                                 + ("   AI" if o.source == "detected" else ""))
            it.setToolTip(f"{un.fmt(o.x, self.unit)} from the left, {un.fmt(o.y, self.unit)} from the floor")
            self.list_items.addItem(it)
        if 0 <= cur < self.list_items.count():
            self.list_items.setCurrentRow(cur)
        self.list_items.blockSignals(False)
        self._refresh_form()

    def _refresh_form(self) -> None:
        o = self._cur()
        self.item_form.setEnabled(o is not None)
        su = _spin_unit(self.unit)
        dec = un.DECIMALS[su]
        for key, s in self.sp.items():
            s.blockSignals(True)
            s.setDecimals(dec)
            s.setSuffix(" " + {"m": "m", "cm": "cm", "mm": "mm", "ft": "ft", "in": "in"}[su])
            s.setSingleStep({"m": 0.01, "cm": 1, "mm": 10, "ft": 0.1, "in": 1}[su])
            s.setValue(un.to_unit(getattr(o, key), su) if o else 0)
            s.blockSignals(False)
        self.cb_kind.blockSignals(True)
        self.chk_front.blockSignals(True)
        if o:
            self.cb_kind.setCurrentIndex(max(0, self.cb_kind.findData(o.kind)))
            self.chk_front.setChecked(o.in_front)
        self.cb_kind.blockSignals(False)
        self.chk_front.blockSignals(False)
        self.flatc.sel = self.list_items.currentRow()
        self.flatc.update()

    def _cur(self) -> Optional[wl.Obstacle]:
        r = self.list_items.currentRow()
        return self.wall.obstacles[r] if 0 <= r < len(self.wall.obstacles) else None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def _on_corners(self, final: bool) -> None:
        if final:
            self._solve(final=True)
        else:
            self.t_solve.start()

    def _on_scale_mode(self, i: int, solve: bool = True) -> None:
        self.tape_box.setVisible(i == 0)
        self.ref_box.setVisible(i == 1)
        self.photo.show_ref = i == 1
        if i == 1 and len(self.photo.ref) != 4:
            self._default_ref()
        self.photo.update()
        if solve:
            self._solve(final=True)

    def _on_ref_kind(self, _i: int) -> None:
        if self.cb_ref.currentText().startswith("Other"):
            txt, ok = QInputDialog.getText(self, "Object size", "Width × height of the object (e.g. 60 x 90 cm):",
                                           text=f"{self._custom_ref[0] * 100:.0f} x {self._custom_ref[1] * 100:.0f} cm")
            if ok:
                try:
                    a, b = [s.strip() for s in txt.lower().replace("×", "x").split("x", 1)]
                    unit = "cm"
                    for u_ in ("mm", "cm", "m", "in", "ft"):
                        if b.endswith(u_):
                            unit = u_
                            break
                    w_ = un.parse_length(a if a[-1:].isalpha() else a + unit, unit)
                    h_ = un.parse_length(b, unit)
                    self._custom_ref = (w_, h_)
                except Exception:
                    QMessageBox.warning(self, "Object size", "Please type it like 60 x 90 cm.")
        self._solve(final=True)

    def _on_unit(self, _i: int) -> None:
        old = self.unit
        self.unit = self.cb_unit.currentData()
        for ed in (self.ed_w, self.ed_h):
            t = ed.text().strip()
            if t:
                try:
                    ed.blockSignals(True)
                    ed.setText(un.fmt(un.parse_length(t, old), self.unit))
                finally:
                    ed.blockSignals(False)
        self._solve(final=False)
        self._refresh_items()

    def _on_draw_mode(self, on: bool) -> None:
        self.photo.draw_mode = on
        if on:
            self.btn_ruler.setChecked(False)
            self.lbl_status.setText("Drag a box round the item on the photo.")

    def _on_ruler(self, on: bool) -> None:
        self.flatc.ruler_on = on
        if not on:
            self.flatc.ruler = None
            self.lbl_ruler.setText("")
        else:
            self.btn_draw.setChecked(False)
            self.lbl_ruler.setText("Drag on the straightened wall to measure. Hold Shift for a straight line.")
        self.flatc.update()

    def _kind_menu(self, at, cb) -> None:
        m = QMenu(self)
        for kind, (label, _f, _c) in wl.OBSTACLE_KINDS.items():
            m.addAction(label, lambda k=kind: cb(k))
        m.exec(at)

    def _on_box(self, box, at) -> None:
        if self.res is None:
            return

        def make(kind: str) -> None:
            x, yf, w, h = ms.photo_box_to_wall(self.res, box)
            if w < 0.02 or h < 0.02:
                return
            o = wl.Obstacle.make(kind, x=x, y=yf, w=w, h=h)
            if kind in ("door", "opening") and yf < 0.1:
                o.h += o.y
                o.y = 0.0
            self.wall.obstacles.append(o)
            self.anchors[o.id] = self._anchor(o)
            self._refresh_items(len(self.wall.obstacles) - 1)
            self._refresh_views()
            self.lbl_status.setText(f"{o.name}: {un.fmt_size(o.w, o.h, self.unit)}. Drag it on the straightened "
                                    "wall to fine-tune.")

        self._kind_menu(at, make)

    def _select_item(self, i: int) -> None:
        if i != self.list_items.currentRow():
            self.list_items.setCurrentRow(i)
        else:
            self._refresh_form()
            self._refresh_views()

    def _on_item_row(self, _r: int) -> None:
        self._refresh_form()
        self._refresh_views()

    def _on_flat_changed(self, final: bool) -> None:
        o = self._cur()
        if final:
            for ob in self.wall.obstacles:
                self.anchors[ob.id] = self._anchor(ob)
            self._refresh_items()
        elif o is not None:
            self._refresh_form()
        self._refresh_views()
        if self.flatc.ruler is not None:
            self.lbl_ruler.setText(f"Distance: {un.fmt(self.flatc.ruler_length(), self.unit)}")

    def _item_menu(self, i: int, at) -> None:
        if i < 0:
            m = QMenu(self)
            sub = m.addMenu("Add here")
            for kind, (label, _f, _c) in wl.OBSTACLE_KINDS.items():
                sub.addAction(label, lambda k=kind: self.add_item(k))
            m.exec(at)
            return
        o = self.wall.obstacles[i]
        m = QMenu(self)
        sub = m.addMenu("Change to")
        for kind, (label, _f, _c) in wl.OBSTACLE_KINDS.items():
            sub.addAction(label, lambda k=kind: self._set_item("kind", k))
        a = m.addAction("In front of the wall (furniture)")
        a.setCheckable(True)
        a.setChecked(o.in_front)
        a.toggled.connect(lambda on: self._set_item("in_front", on))
        m.addAction(icon("trash"), "Remove", self.remove_item)
        m.exec(at)

    def _set_item(self, key: str, value) -> None:
        o = self._cur()
        if o is None or self.res is None:
            return
        if key == "kind":
            o.kind = value
            o.in_front = wl.OBSTACLE_KINDS.get(value, wl.OBSTACLE_KINDS["other"])[1]
            o.label = ""
        elif key == "in_front":
            o.in_front = bool(value)
        else:
            setattr(o, key, un.from_unit(value, _spin_unit(self.unit)))
            o.clamp(self.wall.width, self.wall.height)
        o.source = "manual" if key != "in_front" else o.source
        self.anchors[o.id] = self._anchor(o)
        self._refresh_items()
        self._refresh_views()

    def add_item(self, kind: str) -> None:
        if self.res is None:
            QMessageBox.information(self, "Add item", "Choose a photo and set the size first.")
            return
        o = wl.Obstacle.make(kind)
        o.x = max(0.0, (self.wall.width - o.w) / 2)
        o.clamp(self.wall.width, self.wall.height)
        self.wall.obstacles.append(o)
        self.anchors[o.id] = self._anchor(o)
        self._refresh_items(len(self.wall.obstacles) - 1)
        self._refresh_views()

    def remove_item(self) -> None:
        r = self.list_items.currentRow()
        if 0 <= r < len(self.wall.obstacles):
            o = self.wall.obstacles.pop(r)
            self.anchors.pop(o.id, None)
            self._refresh_items(min(r, len(self.wall.obstacles) - 1))
            self._refresh_views()

    # ------------------------------------------------------------------
    # Auto detection
    # ------------------------------------------------------------------
    def auto_detect(self) -> None:
        if self.res is None or self.work is None or self._busy:
            if self.res is None:
                QMessageBox.information(self, "Find items", "Choose a photo, drag the corners and enter one size first.")
            return
        self._busy = True
        self.btn_find.setEnabled(False)
        self.btn_find.setText("  Looking at the photo…")
        work, res = self.work, self.res
        flat, ppm = self.flat, self.ppm
        if flat is None:
            flat, ppm = ms.rectify(work, res, max_side=FLAT_MAX)

        def job(_progress):
            return ms.auto_detect(work, res, flat, ppm)

        run_bg(job, self._detected, self._detect_failed)

    def _detected(self, items) -> None:
        self._busy = False
        self.btn_find.setEnabled(True)
        self.btn_find.setText("  Find them automatically")
        keep = [o for o in self.wall.obstacles if o.source != "detected"]
        new = []
        for o in items:
            if any(ms._overlap_frac(o, k) > 0.6 for k in keep):
                continue
            new.append(o)
        self.wall.obstacles = sorted(keep + new, key=lambda o: o.x)
        for o in self.wall.obstacles:
            self.anchors[o.id] = self._anchor(o)
        self._refresh_items(0 if self.wall.obstacles else -1)
        self._refresh_views()
        if not new:
            self.lbl_status.setText("Nothing new found. Draw items on the photo or add them from the list.")
            return
        counts: Dict[str, int] = {}
        for o in new:
            counts[o.name.lower()] = counts.get(o.name.lower(), 0) + 1
        parts = [f"{n} {k}{'s' if n > 1 and not k.endswith('s') else ''}" for k, n in counts.items()]
        self.lbl_status.setText("Found " + ", ".join(parts) + ". Check each one – drag to correct.")

    def _detect_failed(self, msg: str) -> None:
        self._busy = False
        self.btn_find.setEnabled(True)
        self.btn_find.setText("  Find them automatically")
        QMessageBox.warning(self, "Find items", f"Could not look for items:\n{msg}")

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def _photo_rel(self) -> str:
        """Copy the photo into the job folder (once) and return its relative path."""
        if self.photo_path is None:
            return self.wall.photo
        d = self.job_dir or jobs.folder_for(self.job)
        saved = getattr(self, "_straightened", None)
        if abs(self.k1) >= 1e-4 and saved and saved[0] == round(self.k1, 4):
            return saved[1]
        if abs(self.k1) < 1e-4:
            try:
                rel = self.photo_path.resolve().relative_to(d.resolve())
                return rel.as_posix()
            except ValueError:
                pass
        sd = d / "survey"
        sd.mkdir(parents=True, exist_ok=True)
        stem = f"{pr.safe_name(self.wall.name)}_{pr.safe_name(self.photo_path.stem)}"
        if abs(self.k1) >= 1e-4:
            # the straightened photo is the one the corners refer to
            dst = sd / (stem.replace("_straightened", "") + "_straightened.jpg")
            full, _f = ms.load_photo(self.photo_path)
            ms.undistort(full, self.k1).save(dst, "JPEG", quality=94)
            self._straightened = (round(self.k1, 4), f"survey/{dst.name}")
            return self._straightened[1]
        if self.photo_path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            dst = sd / (stem + self.photo_path.suffix.lower())
            shutil.copyfile(self.photo_path, dst)
        else:
            dst = sd / (stem + ".jpg")
            full, _f = ms.load_photo(self.photo_path)
            full.save(dst, "JPEG", quality=94)
        self.photo_path = dst
        return f"survey/{dst.name}"

    def _result(self) -> wl.Wall:
        w = wl.Wall.from_dict(self.wall.to_dict())
        r = self.res
        w.width, w.height = round(r.width, 4), round(r.height, 4)
        for o in w.obstacles:
            o.clamp(w.width, w.height)
        w.photo = self._photo_rel()
        w.corners = [[round(p.x() / self.k, 2), round(p.y() / self.k, 2)] for p in self.photo.corners]
        sv = {"method": r.method, "scale_from": r.scale_from,
              "accuracy_pct": None if r.accuracy_pct is None else round(r.accuracy_pct, 2),
              "measured": True, "lens_k1": round(self.k1, 3)}
        if self.scale_group.checkedId() == 0:
            sv["tape_w"] = max(0.0, self._tape(self.ed_w)) or None
            sv["tape_h"] = max(0.0, self._tape(self.ed_h)) or None
        else:
            sv["reference"] = self.cb_ref.currentText()
            sv["reference_size"] = list(self._ref_size())
            sv["reference_quad"] = [[p.x() / self.k, p.y() / self.k] for p in self.photo.ref]
        w.survey = sv
        return w

    def _long_wall_help(self) -> None:
        QMessageBox.information(
            self, "Long walls",
            "Measure a long wall in parts:\n\n"
            "1. Take one photo per part, each showing its own 4 corners. Use a door edge, a window edge "
            "or a strip of tape on the wall as the line where one part ends and the next begins.\n"
            "2. Measure the first part here and press ‘Use in Wall Plan’.\n"
            "3. In Wall & Items press ＋ to add the next part, set ‘Corner to next wall’ to "
            "‘Flat (same wall)’ and measure it from its photo.\n\n"
            "The design then runs across all parts as one wall, and the panels are worked out for the "
            "whole length.")

    def save_survey(self) -> None:
        if self.res is None:
            QMessageBox.information(self, "Survey sheet", "Choose a photo and set the size first.")
            return
        from app.core import documents as docs
        w = self._result()
        jj = self.job.copy()
        jj.walls[self.wi] = w
        flat, _ppm = ms.rectify(self.work, self.res, max_side=2000)
        corners = [(p.x(), p.y()) for p in self.photo.corners]
        acc = self.res.accuracy_text(self.unit) + f" · perspective: {self.res.method}"
        page = docs.survey_sheet(jj, self.wi, flat, self.work, corners, jobs.load_business(), acc, self.unit)
        d = (self.job_dir or jobs.folder_for(self.job)) / "survey"
        d.mkdir(parents=True, exist_ok=True)
        default = d / f"{pr.safe_name(self.job.job_no)}_{pr.safe_name(w.name)}_survey.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save survey sheet", str(default), "PDF (*.pdf);;JPEG (*.jpg)")
        if not path:
            return
        p = Path(path)
        from app.ui.errors import save_or_warn

        def write():
            if p.suffix.lower() in (".jpg", ".jpeg"):
                page.save(p, "JPEG", quality=92)
            else:
                page.save(p, "PDF", resolution=150.0)
                page.save(p.with_suffix(".jpg"), "JPEG", quality=90)     # handy for WhatsApp
        if not save_or_warn(self, write, p):
            return
        self.job.log(f"Survey sheet saved for {w.name}")
        share.show_in_folder(p)
        self.lbl_status.setText(f"Saved {p.name}" + (" and a JPG copy for WhatsApp." if p.suffix == ".pdf" else "."))

    def apply(self) -> None:
        if self.res is None:
            QMessageBox.information(self, "Measure from photo", "Choose a photo, drag the corners and enter one "
                                                                "size first.")
            return
        r = self.res
        if r.accuracy_pct is not None and r.accuracy_pct >= 6:
            if QMessageBox.question(self, "Check the corners",
                                    f"The photo and your measurements differ by {r.accuracy_pct:.1f}%. "
                                    "The corners may be off, or the photo is very distorted.\n\nUse it anyway?") \
                    != QMessageBox.StandardButton.Yes:
                return
        self.result_wall = self._result()
        self.applied = True
        self.accept()
