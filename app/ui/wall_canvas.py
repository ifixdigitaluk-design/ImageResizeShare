"""Interactive wall plan: design, bleed, walls, doors/windows/furniture, panels and seams."""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)
from PySide6.QtWidgets import QMenu, QWidget

from app.core import units as un
from app.core import wall as wl

HANDLE = 8


def _q(hexs: str, a: int = 255) -> QColor:
    c = QColor(hexs)
    c.setAlpha(a)
    return c


class WallCanvas(QWidget):
    changed = Signal(str)          # what changed: placement / seams / items
    editStarted = Signal()         # before an edit (for undo)
    selectionChanged = Signal(object)
    zoomChanged = Signal(float)
    requestAddItem = Signal(int, str, float, float)    # wall index, kind, x, y (wall coords)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(420, 300)
        self.job: Optional[wl.Job] = None
        self.design_px: Optional[Tuple[int, int]] = None
        self.art: Optional[QPixmap] = None          # whole artwork (with bleed) at display size
        self.overlay: Optional[QPixmap] = None      # gamut mask etc. (same extent as art)
        self.risk: Optional[np.ndarray] = None
        self.faces: List[Tuple[float, float, float, float]] = []   # artwork metres
        self.show_panels = True
        self.show_items = True
        self.show_dims = True
        self.show_risk = False
        self.unit = "m"
        self.selected: Optional[Tuple[int, str]] = None   # (wall index, obstacle id)
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._drag = None
        self._press = QPointF()
        self._press_state = None
        self.placeholder = "Enter the wall size and choose a design"

    # ------------------------------------------------------------------
    def set_job(self, job: wl.Job, design_px) -> None:
        self.job = job
        self.design_px = design_px
        self.update()

    def set_art(self, art: Optional[QImage], overlay: Optional[QImage] = None) -> None:
        self.art = QPixmap.fromImage(art) if art is not None else None
        self.overlay = QPixmap.fromImage(overlay) if overlay is not None else None
        self.update()

    def fit(self) -> None:
        self._zoom, self._pan = 1.0, QPointF(0, 0)
        self.zoomChanged.emit(self.view_scale())
        self.update()

    def zoom_to(self, f: float) -> None:
        self._zoom = max(0.3, min(30.0, f))
        self.zoomChanged.emit(self.view_scale())
        self.update()

    def zoom_factor(self) -> float:
        return self._zoom

    # ------------------------------------------------------------------
    # geometry: artwork metres <-> widget px
    def _margins(self):
        return 76, 104, 30, 62       # left, top, right, bottom (room for sizes and panel numbers)

    def _fit_scale(self) -> float:
        if not self.job:
            return 1.0
        l, t, r, b = self._margins()
        return max(1e-3, min((self.width() - l - r) / self.job.art_width,
                             (self.height() - t - b) / self.job.art_height))

    def view_scale(self) -> float:
        """Pixels per metre on screen."""
        return self._fit_scale() * self._zoom

    def _origin(self) -> QPointF:
        l, t, r, b = self._margins()
        s = self.view_scale()
        aw, ah = self.job.art_width * s, self.job.art_height * s
        return QPointF(l + (self.width() - l - r - aw) / 2, t + (self.height() - t - b - ah) / 2) + self._pan

    def to_px(self, x: float, y: float) -> QPointF:
        o = self._origin()
        s = self.view_scale()
        return QPointF(o.x() + x * s, o.y() + y * s)

    def to_m(self, p: QPointF) -> Tuple[float, float]:
        o = self._origin()
        s = self.view_scale()
        return (p.x() - o.x()) / s, (p.y() - o.y()) / s

    def rect_px(self, x0, y0, x1, y1) -> QRectF:
        a, b = self.to_px(x0, y0), self.to_px(x1, y1)
        return QRectF(a, b).normalized()

    # ------------------------------------------------------------------
    def _hit(self, pos: QPointF):
        if not self.job:
            return None
        x, y = self.to_m(pos)
        # obstacles (resize handle first, then body)
        if self.show_items:
            for wi, o in reversed(list(self.job.all_obstacles())):
                r = self.rect_px(*self.job.obstacle_rect(wi, o))
                if (abs(pos.x() - r.right()) <= HANDLE and abs(pos.y() - r.bottom()) <= HANDLE):
                    return ("resize", wi, o.id)
                if r.contains(pos):
                    return ("item", wi, o.id)
        if self.show_panels:
            for i, sx in enumerate(wl.current_seams(self.job)):
                if abs(pos.x() - self.to_px(sx, 0).x()) <= 6 and 0 <= y <= self.job.art_height:
                    return ("seam", i, None)
        if 0 <= x <= self.job.art_width and 0 <= y <= self.job.art_height and self.design_px:
            return ("design", None, None)
        return None

    def _find(self, wi: int, oid: str) -> Optional[wl.Obstacle]:
        for o in self.job.walls[wi].obstacles:
            if o.id == oid:
                return o
        return None

    # ------------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        if not self.job:
            return
        pos = ev.position()
        if ev.button() == Qt.MouseButton.RightButton:
            self._context(pos)
            return
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._drag = ("pan",)
            self._press = pos - self._pan
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._hit(pos)
        self._press = pos
        if hit is None:
            self._drag = ("pan",)
            self._press = pos - self._pan
            self.selected = None
            self.selectionChanged.emit(None)
            self.update()
            return
        kind, a, b = hit
        self.editStarted.emit()
        if kind in ("item", "resize"):
            self.selected = (a, b)
            self.selectionChanged.emit(self.selected)
            o = self._find(a, b)
            self._press_state = (o.x, o.y, o.w, o.h)
            self._drag = (kind, a, b)
        elif kind == "seam":
            self._drag = ("seam", a)
        elif kind == "design":
            wl.to_custom(self.job, self.design_px)
            self._press_state = (self.job.placement.ox, self.job.placement.oy)
            self._drag = ("design",)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        if not self.job:
            return
        pos = ev.position()
        if self._drag is None:
            hit = self._hit(pos)
            cur = Qt.CursorShape.ArrowCursor
            if hit:
                cur = {"resize": Qt.CursorShape.SizeFDiagCursor, "item": Qt.CursorShape.SizeAllCursor,
                       "seam": Qt.CursorShape.SplitHCursor, "design": Qt.CursorShape.OpenHandCursor}[hit[0]]
            self.setCursor(QCursor(cur))
            return
        s = self.view_scale()
        kind = self._drag[0]
        if kind == "pan":
            self._pan = pos - self._press
        elif kind == "design":
            dx, dy = (pos.x() - self._press.x()) / s, (pos.y() - self._press.y()) / s
            self.job.placement.ox = self._press_state[0] + dx
            self.job.placement.oy = self._press_state[1] + dy
            self.changed.emit("placement-live")
        elif kind == "seam":
            x, _y = self.to_m(pos)
            wl.move_seam(self.job, self._drag[1], x)
            self.changed.emit("seams-live")
        elif kind in ("item", "resize"):
            wi, oid = self._drag[1], self._drag[2]
            o = self._find(wi, oid)
            w = self.job.walls[wi]
            dx, dy = (pos.x() - self._press.x()) / s, -(pos.y() - self._press.y()) / s
            x0, y0, w0, h0 = self._press_state
            if kind == "item":
                o.x, o.y = x0 + dx, y0 + dy
                if abs(o.y) < 0.03:
                    o.y = 0.0               # snap to the floor
            else:
                # bottom-right handle: right edge and bottom edge move, top-left stays
                o.w = max(0.03, w0 + dx)
                new_bottom = min(y0 + dy, y0 + h0 - 0.03)
                if abs(new_bottom) < 0.03:
                    new_bottom = 0.0
                o.y = max(0.0, new_bottom)
                o.h = y0 + h0 - o.y
            o.clamp(w.width, w.height)
            self.changed.emit("items-live")
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if self._drag is None:
            return
        kind = self._drag[0]
        self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if kind == "design":
            self.changed.emit("placement")
        elif kind == "seam":
            self.changed.emit("seams")
        elif kind in ("item", "resize"):
            self.changed.emit("items")

    def mouseDoubleClickEvent(self, ev) -> None:
        hit = self._hit(ev.position()) if self.job else None
        if hit and hit[0] == "seam":
            self.editStarted.emit()
            wl.remove_seam(self.job, hit[1])
            self.changed.emit("seams")
        else:
            self.fit()

    def wheelEvent(self, ev) -> None:
        if not self.job:
            return
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        pos = ev.position()
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier and self.design_px:
            self.editStarted.emit()
            x, y = self.to_m(pos)
            wl.zoom_placement(self.job, self.design_px, 1.05 ** steps, x, y)
            self.changed.emit("placement")
            return
        before = self.to_m(pos)
        self._zoom = max(0.3, min(30.0, self._zoom * (1.2 ** steps)))
        after = self.to_px(*before)
        self._pan += pos - after
        self.zoomChanged.emit(self.view_scale())
        self.update()

    def keyPressEvent(self, ev) -> None:
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected and self.job:
            self.editStarted.emit()
            wi, oid = self.selected
            self.job.walls[wi].obstacles = [o for o in self.job.walls[wi].obstacles if o.id != oid]
            self.selected = None
            self.selectionChanged.emit(None)
            self.changed.emit("items")
            return
        super().keyPressEvent(ev)

    def _context(self, pos: QPointF) -> None:
        x, y = self.to_m(pos)
        m = QMenu(self)
        wi = self._wall_at(x)
        if wi is not None:
            wx = x - self.job.wall_x(wi)
            wy = self.job.floor_y - y
            add = m.addMenu("Add here")
            for k, (label, _f, _c) in wl.OBSTACLE_KINDS.items():
                add.addAction(label, lambda k=k: self.requestAddItem.emit(wi, k, wx, wy))
        if 0 < x < self.job.art_width:
            m.addAction("Add a seam here", lambda: (self.editStarted.emit(), wl.add_seam(self.job, x),
                                                    self.changed.emit("seams")))
        hit = self._hit(pos)
        if hit and hit[0] == "seam":
            m.addAction("Remove this seam", lambda: (self.editStarted.emit(), wl.remove_seam(self.job, hit[1]),
                                                     self.changed.emit("seams")))
        if hit and hit[0] in ("item", "resize"):
            m.addAction("Delete this item", lambda: self._delete(hit[1], hit[2]))
        m.addSeparator()
        m.addAction("Fit view", self.fit)
        m.exec(self.mapToGlobal(pos.toPoint()))

    def _delete(self, wi, oid):
        self.editStarted.emit()
        self.job.walls[wi].obstacles = [o for o in self.job.walls[wi].obstacles if o.id != oid]
        self.selected = None
        self.selectionChanged.emit(None)
        self.changed.emit("items")

    def _wall_at(self, x: float) -> Optional[int]:
        for i in range(len(self.job.walls)):
            x0, _y0, x1, _y1 = self.job.wall_rect(i)
            if x0 <= x <= x1:
                return i
        return None

    # ------------------------------------------------------------------
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#eef1f5"))
        if not self.job or self.job.art_width <= 0:
            p.setPen(QColor("#94a3b8"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            p.end()
            return
        j = self.job
        aw, ah = j.art_width, j.art_height
        art_r = self.rect_px(0, 0, aw, ah)
        # design (or empty print area)
        if self.art is not None:
            p.drawPixmap(art_r, self.art, QRectF(self.art.rect()))
            if self.overlay is not None:
                p.setOpacity(0.75)
                p.drawPixmap(art_r, self.overlay, QRectF(self.overlay.rect()))
                p.setOpacity(1.0)
        else:
            p.fillRect(art_r, QColor("#ffffff"))
            p.setPen(QColor("#94a3b8"))
            p.drawText(art_r, Qt.AlignmentFlag.AlignCenter, self.placeholder)
        # bleed area
        bt = j.panels.bleed_top
        veil = QColor(255, 255, 255, 120)
        wall_path = QPainterPath()
        polys = []
        for i in range(len(j.walls)):
            poly = QPolygonF([self.to_px(x, y) for x, y in j.wall_outline(i)])
            polys.append(poly)
            sub = QPainterPath()
            sub.addPolygon(poly)
            sub.closeSubpath()
            wall_path = wall_path.united(sub)
        outside = QPainterPath()
        outside.addRect(art_r)
        p.fillPath(outside.subtracted(wall_path), veil)
        # hatch where there is no wall: above lower walls, above slopes, below stairs
        no_wall = QPainterPath()
        no_wall.addRect(self.rect_px(j.panels.bleed_left, bt, j.panels.bleed_left + j.run_width, j.floor_y))
        no_wall = no_wall.subtracted(wall_path)
        if not no_wall.isEmpty():
            p.save()
            p.setClipPath(no_wall)
            p.setPen(QPen(QColor(100, 116, 139, 90), 1))
            r = no_wall.boundingRect()
            for t in range(int(r.left() - r.height()), int(r.right()), 10):
                p.drawLine(QPointF(t, r.bottom()), QPointF(t + r.height(), r.top()))
            p.restore()
        p.setPen(QPen(QColor("#0f172a"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for poly in polys:
            p.drawPolygon(poly)
        p.setPen(QPen(QColor("#94a3b8"), 1, Qt.PenStyle.DashLine))
        p.drawRect(art_r)
        f_small = QFont(self.font())
        f_small.setPointSizeF(8.5)
        p.setFont(f_small)
        for cx, kind in j.corners():
            a, b = self.to_px(cx, bt), self.to_px(cx, j.floor_y)
            p.setPen(QPen(QColor("#334155"), 1.5, Qt.PenStyle.DashDotLine))
            p.drawLine(a, b)
            p.setPen(QColor("#334155"))
            p.drawText(QPointF(b.x() + 4, b.y() - 6), f"{kind} corner")
        # faces / seam risk
        if self.show_risk:
            for (fx0, fy0, fx1, fy1) in self.faces:
                p.setPen(QPen(QColor("#e11d48"), 2))
                p.drawRect(self.rect_px(fx0, fy0, fx1, fy1))
            if self.risk is not None and len(self.risk):
                n = len(self.risk)
                y0 = art_r.top() - 10
                for k in range(0, n, max(1, n // 400)):
                    v = min(1.0, float(self.risk[k]) / 2.0)
                    col = QColor.fromHsvF(max(0.0, 0.33 * (1 - v)), 0.85, 0.9)
                    x = art_r.left() + art_r.width() * k / max(1, n - 1)
                    p.fillRect(QRectF(x, y0, max(1.0, art_r.width() / n * max(1, n // 400) + 0.5), 6), col)
        # items
        if self.show_items:
            fb = QFont(self.font())
            fb.setPointSizeF(8.5)
            fb.setBold(True)
            fm = QFontMetrics(fb)
            for wi, o in j.all_obstacles():
                r = self.rect_px(*j.obstacle_rect(wi, o))
                c = QColor(o.colour)
                sel = self.selected == (wi, o.id)
                if o.in_front:
                    p.save()
                    p.setClipRect(r)
                    p.setPen(QPen(_q(o.colour, 120), 1.2))
                    for t in range(int(r.left() - r.height()), int(r.right()), 8):
                        p.drawLine(QPointF(t, r.bottom()), QPointF(t + r.height(), r.top()))
                    p.restore()
                    p.setPen(QPen(c, 2.2 if not sel else 3, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    p.setPen(QPen(c, 2.4 if not sel else 3.4))
                    p.setBrush(QColor(255, 255, 255, 110))
                p.drawRect(r)
                tag = o.name + (" · in front" if o.in_front else "")
                tw = fm.horizontalAdvance(tag) + 12
                chip = QRectF(r.left() + 3, r.top() + 3, tw, fm.height() + 6)
                if tw > r.width() - 6:
                    chip = QRectF(r.left(), r.top() - fm.height() - 8, tw, fm.height() + 6)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(chip, 4, 4)
                p.setFont(fb)
                p.setPen(QColor("#ffffff"))
                p.drawText(chip, Qt.AlignmentFlag.AlignCenter, tag)
                if sel:
                    p.setBrush(QColor("#ffffff"))
                    p.setPen(QPen(c, 2))
                    p.drawRect(QRectF(r.right() - 5, r.bottom() - 5, 10, 10))
        # panels + seams
        panels = wl.compute_panels(j)
        if self.show_panels:
            fb = QFont(self.font())
            fb.setBold(True)
            fb.setPointSizeF(9)
            p.setFont(fb)
            for k, pn in enumerate(panels):
                r = self.rect_px(pn.x0, pn.y0, pn.x1, pn.y1)
                if k % 2:
                    p.fillRect(r, QColor(26, 115, 232, 22))
                if pn.y0 > 1e-6 or pn.y1 < ah - 1e-6:          # trimmed panel: show its real length
                    p.setPen(QPen(QColor(26, 115, 232, 160), 1, Qt.PenStyle.DotLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(r)
                cx = r.center().x()
                cy = art_r.top() - 34
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#1e293b"))
                p.drawEllipse(QPointF(cx, cy), 14, 14)
                p.setPen(QColor("#ffffff"))
                p.drawText(QRectF(cx - 14, cy - 14, 28, 28), Qt.AlignmentFlag.AlignCenter, f"P{pn.index}")
            o = j.panels.overlap
            for sx in wl.current_seams(j):
                band = self.rect_px(sx - o / 2, 0, sx + o / 2, ah)
                p.fillRect(band, QColor(225, 29, 46, 50))
                p.setPen(QPen(QColor("#e11d2e"), 2, Qt.PenStyle.DashLine))
                a = self.to_px(sx, 0)
                p.drawLine(QPointF(a.x(), art_r.top() - 16), QPointF(a.x(), art_r.bottom() + 4))
        # dimensions
        if self.show_dims:
            self._dims(p, j, art_r, panels)
        p.end()

    def _dims(self, p: QPainter, j: wl.Job, art_r: QRectF, panels) -> None:
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        ink = QColor("#0f172a")

        def hdim(x0, x1, y, text, col=ink):
            p.setPen(QPen(col, 1.2))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
            for x in (x0, x1):
                p.drawLine(QPointF(x, y - 5), QPointF(x, y + 5))
                p.drawLine(QPointF(x - 3.5, y + 3.5), QPointF(x + 3.5, y - 3.5))
            tw = fm.horizontalAdvance(text) + 8
            box = QRectF((x0 + x1) / 2 - tw / 2, y - fm.height() / 2 - 1, tw, fm.height() + 2)
            if tw > abs(x1 - x0) - 4:
                box.moveTop(y + 4)
            p.fillRect(box, QColor(238, 241, 245, 235))
            p.setPen(col)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

        def vdim(x, y0, y1, text, col=ink):
            p.setPen(QPen(col, 1.2))
            p.drawLine(QPointF(x, y0), QPointF(x, y1))
            for y in (y0, y1):
                p.drawLine(QPointF(x - 5, y), QPointF(x + 5, y))
                p.drawLine(QPointF(x - 3.5, y + 3.5), QPointF(x + 3.5, y - 3.5))
            tw = fm.horizontalAdvance(text) + 8
            p.save()
            p.translate(x, (y0 + y1) / 2)
            p.rotate(-90)
            box = QRectF(-tw / 2, -fm.height() / 2 - 1, tw, fm.height() + 2)
            p.fillRect(box, QColor(238, 241, 245, 235))
            p.setPen(col)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            p.restore()

        u = self.unit
        x0 = self.to_px(j.panels.bleed_left, 0).x()
        x1 = self.to_px(j.panels.bleed_left + j.run_width, 0).x()
        hdim(x0, x1, art_r.top() - 64, f"wall {un.fmt(j.run_width, u)}"
             + (f"  ({un.ft_in(j.run_width)})" if u in ("m", "cm", "mm") else ""))
        y0 = self.to_px(0, j.floor_y - j.run_height).y()
        y1 = self.to_px(0, j.floor_y).y()
        vdim(art_r.left() - 30, y0, y1, f"{un.fmt(j.run_height, u)}"
             + (f"  ({un.ft_in(j.run_height)})" if u in ("m", "cm", "mm") else ""))
        if self.show_panels and len(panels) > 1:
            for pn in panels:
                a, b = self.to_px(pn.x0, 0).x(), self.to_px(pn.x1, 0).x()
                hdim(a, b, art_r.bottom() + 18, f"{pn.width * 100:.1f}", QColor("#334155"))
        elif len(j.walls) > 1:
            for i, w in enumerate(j.walls):
                a, _, b, _ = j.wall_rect(i)
                hdim(self.to_px(a, 0).x(), self.to_px(b, 0).x(), art_r.bottom() + 18, un.fmt(w.width, u))
