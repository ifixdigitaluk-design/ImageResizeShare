"""Zoomable preview view and interactive crop canvas."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QImage, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QWidget


def checker_brush(cell: int = 8) -> QBrush:
    pm = QPixmap(cell * 2, cell * 2)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.fillRect(0, 0, cell, cell, QColor("#e5e9ef"))
    p.fillRect(cell, cell, cell, cell, QColor("#e5e9ef"))
    p.end()
    return QBrush(pm)


class ZoomView(QGraphicsView):
    """Image view: fits the window, mouse-wheel zoom, drag to pan, 100% view."""
    zoomChanged = Signal(float)
    hovered = Signal(float, float)    # scene (= image pixel) coordinates under the mouse
    clicked = Signal(float, float)

    def __init__(self, placeholder: str = "", parent=None, bg: str = "#f6f8fb"):
        super().__init__(parent)
        self._bg = QColor(bg)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self._has_image = False
        self._logical = QSizeF(1, 1)        # size in output pixels (a preview picture can be smaller)
        self._fit = True
        self._placeholder = placeholder
        self._checker = checker_brush()
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet(f"background: {bg}; border-radius: 8px;")
        self.setMinimumSize(200, 180)
        # let drops fall through to the main window
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)
        self.viewport().setMouseTracking(True)
        self._marker: Optional[QRectF] = None
        self._press_pos = None

    # --------------------------------------------------------------
    def set_image(self, qimg: Optional[QImage], keep_view: bool = False, logical_size=None) -> None:
        """Show a picture. logical_size = the real output size when qimg is a smaller preview: the
        view then works in output pixels (zoom %, hover and click positions stay true)."""
        if qimg is None or qimg.isNull():
            self._item.setPixmap(QPixmap())
            self._has_image = False
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            self.viewport().update()
            return
        lw, lh = (logical_size if logical_size else (qimg.width(), qimg.height()))
        same_size = self._has_image and (self._logical.width(), self._logical.height()) == (lw, lh)
        self._item.setPixmap(qimg if isinstance(qimg, QPixmap) else QPixmap.fromImage(qimg))
        self._item.setScale(lw / max(1, qimg.width()))
        self._logical = QSizeF(lw, lh)
        self._has_image = True
        self._scene.setSceneRect(QRectF(0, 0, lw, lh))
        if self._fit or not (keep_view and same_size):
            self.fit()
        self.viewport().update()

    def has_image(self) -> bool:
        return self._has_image

    def _img_rect(self) -> QRectF:
        return QRectF(0, 0, self._logical.width(), self._logical.height())

    def zoom(self) -> float:
        return self.transform().m11()

    def set_zoom(self, z: float) -> None:
        z = max(0.02, min(32.0, z))
        self.resetTransform()
        self.scale(z, z)
        # pixel-exact rendering when zoomed in, smooth when zoomed out
        self._item.setTransformationMode(Qt.TransformationMode.FastTransformation if z >= 2
                                         else Qt.TransformationMode.SmoothTransformation)
        self.zoomChanged.emit(z)

    def zoom_to(self, z: float) -> None:
        """Zoom to ``z`` (1.0 = 100%) keeping the centre of the view in place."""
        if not self._has_image:
            return
        c = self.mapToScene(self.viewport().rect().center())
        self._fit = False
        self.set_zoom(z)
        self.centerOn(c)

    def is_fit(self) -> bool:
        return self._fit

    def fit(self) -> None:
        self._fit = True
        if not self._has_image:
            return
        r = self._img_rect()
        vw, vh = max(1, self.viewport().width() - 16), max(1, self.viewport().height() - 16)
        z = min(vw / r.width(), vh / r.height(), 1.0)  # never enlarge in "fit"
        self.set_zoom(z)
        self.centerOn(r.center())

    def actual_size(self) -> None:
        self._fit = False
        self.set_zoom(1.0)

    # --------------------------------------------------------------
    def wheelEvent(self, ev) -> None:
        if not self._has_image:
            return
        steps = ev.angleDelta().y() / 120.0
        if steps == 0:
            return
        self._fit = False
        new = self.zoom() * (1.25 ** steps)
        new = max(0.02, min(32.0, new))
        f = new / self.zoom()
        self.scale(f, f)
        self._item.setTransformationMode(Qt.TransformationMode.FastTransformation if new >= 2
                                         else Qt.TransformationMode.SmoothTransformation)
        self.zoomChanged.emit(new)

    def set_marker(self, rect: Optional[QRectF]) -> None:
        """Outline shown on top of the image (e.g. the close-up area)."""
        self._marker = rect
        self.viewport().update()

    def mouseMoveEvent(self, ev) -> None:
        super().mouseMoveEvent(ev)
        if self._has_image:
            p = self.mapToScene(ev.position().toPoint())
            self.hovered.emit(p.x(), p.y())

    def mousePressEvent(self, ev) -> None:
        self._press_pos = ev.position()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        super().mouseReleaseEvent(ev)
        if self._has_image and self._press_pos is not None:
            d = ev.position() - self._press_pos
            if abs(d.x()) + abs(d.y()) < 5:
                p = self.mapToScene(ev.position().toPoint())
                self.clicked.emit(p.x(), p.y())
        self._press_pos = None

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self._has_image and self._marker is not None:
            painter.save()
            w = 2.0 / max(0.01, self.zoom())   # constant 2px on screen
            painter.setPen(QPen(QColor(0, 0, 0, 140), w * 2))
            painter.drawRect(self._marker)
            painter.setPen(QPen(QColor("#1a73e8"), w))
            painter.drawRect(self._marker)
            painter.restore()

    def mouseDoubleClickEvent(self, ev) -> None:
        if self._fit:
            self.actual_size()
        else:
            self.fit()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self._fit:
            self.fit()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, self._bg)
        if self._has_image:
            painter.save()
            painter.setBrushOrigin(0, 0)
            painter.fillRect(self._img_rect(), self._checker)
            painter.restore()

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        if not self._has_image and self._placeholder:
            p = QPainter(self.viewport())
            p.setPen(QColor("#94a3b8"))
            f = QFont(self.font())
            f.setPointSize(10)
            p.setFont(f)
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            p.end()


class CloseUpView(ZoomView):
    """Fixed-magnification loupe that follows a point (no fitting)."""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(placeholder, parent)
        self._fit = False
        self._look = None
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setMinimumSize(160, 140)
        # sharp real-size pixels for the spot being looked at, drawn over a preview picture
        self._tile = QGraphicsPixmapItem()
        self._tile.setZValue(1)
        self._tile.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._scene.addItem(self._tile)
        self.tile_rect: Optional[QRectF] = None

    def set_image(self, qimg, keep_view: bool = False, logical_size=None) -> None:
        self.clear_tile()
        super().set_image(qimg, keep_view, logical_size)

    def set_tile(self, pm: QPixmap, x: float, y: float) -> None:
        self._tile.setPixmap(pm)
        self._tile.setPos(x, y)
        self.tile_rect = QRectF(x, y, pm.width(), pm.height())
        self.viewport().update()

    def clear_tile(self) -> None:
        self._tile.setPixmap(QPixmap())
        self.tile_rect = None

    def fit(self) -> None:          # never auto-fit
        self._fit = False

    def wheelEvent(self, ev) -> None:   # zoom is controlled by the panel
        ev.ignore()

    def resizeEvent(self, ev) -> None:
        QGraphicsView.resizeEvent(self, ev)
        if self._look:
            self.look(*self._look)

    def look(self, zoom: float, x: float, y: float) -> None:
        self._look = (zoom, x, y)
        if not self._has_image:
            return
        # Allow centring near the edges: pad the scene rect by half a view.
        r = self._img_rect()
        hw = self.viewport().width() / (2 * max(zoom, 0.01))
        hh = self.viewport().height() / (2 * max(zoom, 0.01))
        self._scene.setSceneRect(r.adjusted(-hw, -hh, hw, hh))
        self.set_zoom(zoom)
        self.centerOn(x, y)


# ======================================================================
class CropCanvas(QWidget):
    """Shows the image and lets the user drag a crop rectangle.

    * drag on the image -> new selection
    * drag inside the selection -> move it
    * drag edges / corners -> resize (respecting the chosen aspect ratio)
    * mouse wheel -> zoom, right/middle drag -> pan, double-click -> fit
    """
    rectChanged = Signal(object)    # (x, y, w, h) ints, or None
    editStarted = Signal()
    editFinished = Signal()

    HANDLE = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pix: Optional[QPixmap] = None
        self._W = self._H = 0
        self._rect: Optional[QRectF] = None   # in image coordinates
        self._ratio: Optional[float] = None   # w / h
        self._grid = True
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._drag: Optional[str] = None
        self._press_img = QPointF()
        self._press_rect = QRectF()
        self._pan_start = QPointF()
        self._checker = checker_brush()

    # ---------------------------------------------------------- public
    def set_image(self, qimg: Optional[QImage]) -> None:
        if qimg is None or qimg.isNull():
            self._pix, self._W, self._H, self._rect = None, 0, 0, None
        else:
            new_size = (qimg.width(), qimg.height()) != (self._W, self._H)
            self._pix = qimg if isinstance(qimg, QPixmap) else QPixmap.fromImage(qimg)
            self._W, self._H = qimg.width(), qimg.height()
            if new_size:
                self._zoom, self._pan = 1.0, QPointF(0, 0)
        self.update()

    def set_rect(self, rect, emit: bool = False) -> None:
        if rect is None or self._W == 0:
            self._rect = None
        else:
            x, y, w, h = rect
            self._rect = QRectF(x, y, w, h).intersected(QRectF(0, 0, self._W, self._H))
        self.update()
        if emit:
            self.rectChanged.emit(self.rect_tuple())

    def rect_tuple(self):
        if self._rect is None or self._rect.width() < 1 or self._rect.height() < 1:
            return None
        r = self._rect
        return (int(round(r.x())), int(round(r.y())), int(round(r.width())), int(round(r.height())))

    def set_ratio(self, ratio: Optional[float]) -> None:
        self._ratio = ratio if ratio and ratio > 0 else None
        if self._ratio and self._W:
            # Fit the largest rectangle of that ratio inside the current one
            # (or inside the whole image if nothing is selected yet).
            base = self._rect if self._rect is not None else QRectF(0, 0, self._W, self._H)
            w, h = base.width(), base.height()
            if w / h > self._ratio:
                w = h * self._ratio
            else:
                h = w / self._ratio
            c = base.center()
            self._rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
            self._rect = self._clamp_move(self._rect)
            self.rectChanged.emit(self.rect_tuple())
        self.update()

    def set_grid(self, on: bool) -> None:
        self._grid = on
        self.update()

    def reset_view(self) -> None:
        self._zoom, self._pan = 1.0, QPointF(0, 0)
        self.update()

    # ---------------------------------------------------------- geometry
    def _scale(self) -> float:
        if not self._W:
            return 1.0
        fit = min((self.width() - 24) / self._W, (self.height() - 24) / self._H)
        return max(1e-4, fit * self._zoom)

    def _origin(self) -> QPointF:
        s = self._scale()
        return QPointF((self.width() - self._W * s) / 2, (self.height() - self._H * s) / 2) + self._pan

    def _to_img(self, p: QPointF) -> QPointF:
        o, s = self._origin(), self._scale()
        return QPointF((p.x() - o.x()) / s, (p.y() - o.y()) / s)

    def _to_widget_rect(self, r: QRectF) -> QRectF:
        o, s = self._origin(), self._scale()
        return QRectF(o.x() + r.x() * s, o.y() + r.y() * s, r.width() * s, r.height() * s)

    def _effective_rect(self) -> Optional[QRectF]:
        """The selection, or the whole image when nothing is selected."""
        if self._rect is not None:
            return self._rect
        return QRectF(0, 0, self._W, self._H) if self._W else None

    def _handles(self) -> dict:
        er = self._effective_rect()
        if er is None:
            return {}
        r = self._to_widget_rect(er)
        cx, cy = r.center().x(), r.center().y()
        pts = {"tl": (r.left(), r.top()), "t": (cx, r.top()), "tr": (r.right(), r.top()),
               "r": (r.right(), cy), "br": (r.right(), r.bottom()), "b": (cx, r.bottom()),
               "bl": (r.left(), r.bottom()), "l": (r.left(), cy)}
        return {k: QPointF(*v) for k, v in pts.items()}

    def _hit(self, pos: QPointF) -> Optional[str]:
        for k, p in self._handles().items():
            if abs(p.x() - pos.x()) <= self.HANDLE and abs(p.y() - pos.y()) <= self.HANDLE:
                return k
        if self._rect is not None and self._to_widget_rect(self._rect).contains(pos):
            return "move"
        return None

    def _clamp_pt(self, p: QPointF) -> QPointF:
        return QPointF(min(max(p.x(), 0.0), float(self._W)), min(max(p.y(), 0.0), float(self._H)))

    def _clamp_move(self, r: QRectF) -> QRectF:
        w, h = min(r.width(), self._W), min(r.height(), self._H)
        x = min(max(r.x(), 0.0), self._W - w)
        y = min(max(r.y(), 0.0), self._H - h)
        return QRectF(x, y, w, h)

    def _from_anchor(self, ax: float, ay: float, m: QPointF) -> QRectF:
        """Rectangle from a fixed anchor corner to the mouse (ratio applied)."""
        m = self._clamp_pt(m)
        dx, dy = m.x() - ax, m.y() - ay
        w, h = abs(dx), abs(dy)
        if self._ratio:
            if h == 0 or w / max(h, 1e-6) > self._ratio:
                w = h * self._ratio
            else:
                h = w / self._ratio
        x = ax if dx >= 0 else ax - w
        y = ay if dy >= 0 else ay - h
        return QRectF(x, y, w, h)

    def _resize_edge(self, edge: str, m: QPointF) -> QRectF:
        r = QRectF(self._press_rect)
        m = self._clamp_pt(m)
        if edge in ("l", "r"):
            fixed = r.right() if edge == "l" else r.left()
            w = abs(m.x() - fixed)
            x = min(m.x(), fixed)
            h, cy = r.height(), r.center().y()
            if self._ratio:
                h = w / self._ratio
                hmax = 2 * min(cy, self._H - cy)
                if h > hmax:
                    h = hmax
                    w = h * self._ratio
                    x = fixed - w if m.x() < fixed else fixed
            return QRectF(x, cy - h / 2, w, h)
        fixed = r.bottom() if edge == "t" else r.top()
        h = abs(m.y() - fixed)
        y = min(m.y(), fixed)
        w, cx = r.width(), r.center().x()
        if self._ratio:
            w = h * self._ratio
            wmax = 2 * min(cx, self._W - cx)
            if w > wmax:
                w = wmax
                h = w / self._ratio
                y = fixed - h if m.y() < fixed else fixed
        return QRectF(cx - w / 2, y, w, h)

    # ---------------------------------------------------------- events
    def mousePressEvent(self, ev) -> None:
        if not self._pix:
            return
        pos = ev.position()
        if ev.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag = "pan"
            self._pan_start = pos - self._pan
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self.editStarted.emit()
        self._press_img = self._to_img(pos)
        hit = self._hit(pos)
        if self._rect is None and hit == "move":
            hit = None            # dragging inside the full image draws a new selection
        er = self._effective_rect()
        self._press_rect = QRectF(er) if (hit and er is not None) else QRectF()
        self._drag = hit or "new"
        if self._drag == "new":
            p = self._clamp_pt(self._press_img)
            self._press_img = p
            self._rect = QRectF(p.x(), p.y(), 0, 0)

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        if self._drag is None:
            self._update_cursor(pos)
            return
        if self._drag == "pan":
            self._pan = pos - self._pan_start
            self.update()
            return
        m = self._to_img(pos)
        r0 = self._press_rect
        if self._drag == "new":
            self._rect = self._from_anchor(self._press_img.x(), self._press_img.y(), m)
        elif self._drag == "move":
            d = m - self._press_img
            self._rect = self._clamp_move(r0.translated(d))
        elif self._drag in ("tl", "tr", "bl", "br"):
            ax = r0.right() if "l" in self._drag else r0.left()
            ay = r0.bottom() if "t" in self._drag else r0.top()
            self._rect = self._from_anchor(ax, ay, m)
        else:
            self._rect = self._resize_edge(self._drag, m)
        self.update()
        self.rectChanged.emit(self.rect_tuple())

    def mouseReleaseEvent(self, ev) -> None:
        if self._drag is None:
            return
        was = self._drag
        self._drag = None
        self._update_cursor(ev.position())
        if was == "pan":
            return
        if self._rect is not None and (self._rect.width() < 2 or self._rect.height() < 2):
            self._rect = None  # a simple click clears the selection
        self.update()
        self.rectChanged.emit(self.rect_tuple())
        self.editFinished.emit()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.reset_view()

    def wheelEvent(self, ev) -> None:
        if not self._pix:
            return
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        pos = ev.position()
        before = self._to_img(pos)
        self._zoom = max(0.2, min(40.0, self._zoom * (1.25 ** steps)))
        o, s = self._origin(), self._scale()
        after = QPointF(o.x() + before.x() * s, o.y() + before.y() * s)
        self._pan += pos - after
        self.update()

    def _update_cursor(self, pos: QPointF) -> None:
        hit = self._hit(pos) if self._pix else None
        if hit == "move" and self._rect is None:
            hit = None
        shapes = {"tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                  "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                  "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
                  "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
                  "move": Qt.CursorShape.SizeAllCursor}
        self.setCursor(QCursor(shapes.get(hit, Qt.CursorShape.CrossCursor if self._pix
                                          else Qt.CursorShape.ArrowCursor)))

    # ---------------------------------------------------------- paint
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#f6f8fb"))
        if not self._pix:
            p.setPen(QColor("#94a3b8"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Open an image, then drag on it to select the crop area")
            p.end()
            return
        img_r = self._to_widget_rect(QRectF(0, 0, self._W, self._H))
        p.fillRect(img_r, self._checker)
        p.drawPixmap(img_r, self._pix, QRectF(self._pix.rect()))

        sel = self._rect if self._rect is not None else QRectF(0, 0, self._W, self._H)
        if sel.width() > 0 and sel.height() > 0:
            cr = self._to_widget_rect(sel)
            if self._rect is not None:
                shade = QPainterPath()
                shade.addRect(img_r)
                inner = QPainterPath()
                inner.addRect(cr)
                p.fillPath(shade.subtracted(inner), QColor(15, 23, 42, 140))

            if self._grid:
                p.setPen(QPen(QColor(255, 255, 255, 150), 1))
                for i in (1, 2):
                    x = cr.left() + cr.width() * i / 3
                    y = cr.top() + cr.height() * i / 3
                    p.drawLine(QPointF(x, cr.top()), QPointF(x, cr.bottom()))
                    p.drawLine(QPointF(cr.left(), y), QPointF(cr.right(), y))
            p.setPen(QPen(QColor(0, 0, 0, 90), 3))
            p.drawRect(cr)
            p.setPen(QPen(QColor("#1a73e8"), 2))
            p.drawRect(cr)

            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.setBrush(QColor("#1a73e8"))
            hs = self.HANDLE
            for pt in self._handles().values():
                p.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))

            t = self.rect_tuple()
            if t and self._drag is not None:
                label = f"{t[2]} × {t[3]} px"
                f = QFont(self.font())
                f.setPointSize(9)
                f.setBold(True)
                p.setFont(f)
                tw = p.fontMetrics().horizontalAdvance(label) + 14
                lx = cr.left()
                ly = cr.top() - 26 if cr.top() > 30 else cr.top() + 6
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(15, 23, 42, 200))
                p.drawRoundedRect(QRectF(lx, ly, tw, 20), 5, 5)
                p.setPen(QColor("#ffffff"))
                p.drawText(QRectF(lx, ly, tw, 20), Qt.AlignmentFlag.AlignCenter, label)
        p.end()
