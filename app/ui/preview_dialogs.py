"""
Customer preview dialogs, styled like the design mockups.

* DownloadPreviewDialog  – print size, area, the design with dimension arrows,
  the colour/size warning; Download Preview / Download Original.
* CloseupPrintPreviewDialog – a zoomed close-up of one spot to check sharpness
  before printing; Download Closeup Preview / Download Original.
* FullscreenViewer – the result on the whole screen.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from app.core import imaging as im
from app.core import sheets as sh
from app.ui import share
from app.ui.qtutil import FreeAfterExec
from app.ui.qtutil import icon, pil_to_qimage, svg_pixmap
from app.ui.views import ZoomView

UNIT_ITEMS = [("inches", "in"), ("cm", "cm"), ("mm", "mm"), ("feet", "ft")]
SPIN_DECIMALS = {"in": 2, "cm": 2, "mm": 1, "ft": 2}
DISPLAY_MAX = 2400          # longest side of the on-screen copy of the design


# ======================================================================
# Shared context and options
# ======================================================================
@dataclass
class PreviewContext:
    image: Image.Image                     # the finished design (full resolution)
    src_name: Optional[str]
    dpi: int
    spec: sh.PrintSpec
    wa_target: str = "web"
    wa_phone: str = ""
    download_original: Optional[Callable[[], Optional[Path]]] = None
    classic_proof: Optional[Callable[[], None]] = None


def load_options(s: QSettings) -> sh.SheetOptions:
    note = s.value("sheet_note")
    lines = [ln for ln in str(note).splitlines() if ln.strip()] if note is not None else list(sh.DEFAULT_WARNING)
    area = str(s.value("proof_area", "sqft"))
    fill = s.value("sheet_fill", True)
    return sh.SheetOptions(note_lines=lines, watermark=str(s.value("proof_wm", "")),
                           footer=str(s.value("proof_footer", "")),
                           area_unit=area if area in ("sqft", "sqm") else "sqft",
                           fill=fill in (True, "true", "1", 1))


def save_options(s: QSettings, o: sh.SheetOptions) -> None:
    s.setValue("sheet_note", "\n".join(o.note_lines))
    s.setValue("proof_wm", o.watermark)
    s.setValue("proof_footer", o.footer)
    s.setValue("proof_area", o.area_unit)
    s.setValue("sheet_fill", o.fill)


def _shaped_display(img: Image.Image, spec: sh.PrintSpec, fill: bool,
                    watermark: str = "") -> Image.Image:
    small = img.convert("RGB")
    if max(small.size) > DISPLAY_MAX * 2:
        small = small.copy()
        small.thumbnail((DISPLAY_MAX * 2, DISPLAY_MAX * 2), Image.Resampling.LANCZOS)
    shaped = sh.shape_to_print(small, spec.width_in, spec.height_in, fill)
    if max(shaped.size) > DISPLAY_MAX:
        shaped.thumbnail((DISPLAY_MAX, DISPLAY_MAX), Image.Resampling.LANCZOS)
    if watermark.strip():
        from app.core.proof import _watermark
        shaped = _watermark(shaped, watermark.strip(), shaped.width / 955.0)
    return shaped


# ======================================================================
# Base dialog: frameless sheet with a mockup-style header
# ======================================================================
class _DragHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag: Optional[QPoint] = None

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag = None


SHEET_MARGIN = 22          # see-through space round the card for its soft shadow
SHEET_RADIUS = 16


class _Backdrop(QWidget):
    """Dims the window behind an open sheet, so the sheet sits inside the app (as in the mockups)."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self.raise_()

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.host and ev.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
        return False

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(17, 24, 39, 105)
        if isinstance(self.host, SheetDialog):           # a sheet opened from another sheet
            m = SHEET_MARGIN
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect().adjusted(m, m, -m, -m)), SHEET_RADIUS, SHEET_RADIUS)
            p.fillPath(path, col)
        else:
            p.fillRect(self.rect(), col)

    def remove(self) -> None:
        try:
            self.host.removeEventFilter(self)
        except RuntimeError:
            pass
        self.hide()
        self.deleteLater()


class SheetDialog(FreeAfterExec, QDialog):
    """A rounded white card that opens over the app window, which is dimmed behind it."""

    def __init__(self, parent, icon_name: str, title: str, subtitle: str = "",
                 size=(1140, 820), icon_size: int = 26):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setModal(True)
        self._card_size = size
        self._backdrop: Optional[_Backdrop] = None
        self._placed = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHEET_MARGIN, SHEET_MARGIN, SHEET_MARGIN, SHEET_MARGIN)
        frame = QFrame()
        frame.setObjectName("Sheet")
        outer.addWidget(frame)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        # the content scrolls when the screen is smaller than the sheet needs (small laptops)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("SheetScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("SheetInner")
        self._scroll.setWidget(inner)
        fl.addWidget(self._scroll)
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(26, 16, 26, 20)
        self.body.setSpacing(14)

        head = _DragHeader()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)
        ic = QLabel()
        ic.setPixmap(svg_pixmap(icon_name, "#0f172a", icon_size))
        hl.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop if subtitle else Qt.AlignmentFlag.AlignVCenter)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("SheetTitle")
        tl.addWidget(t)
        if subtitle:
            st = QLabel(subtitle)
            st.setObjectName("SheetSub")
            tl.addWidget(st)
        hl.addLayout(tl, 1)
        self.head_layout = hl
        close = QToolButton()
        close.setObjectName("IconBtn")
        close.setIcon(icon("close", "#334155"))
        close.setIconSize(QSize(22, 22))
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.reject)
        hl.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addWidget(head)
        self._place()

    def paintEvent(self, ev) -> None:
        # soft shadow round the card (painted, not a graphics effect, so big dialogs stay fast)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        m = SHEET_MARGIN
        card = QRectF(self.rect().adjusted(m, m, -m, -m)).translated(0, 6)
        for i in range(m, 0, -2):
            a = int(34 * (1 - i / m) ** 2) + 2
            p.setBrush(QColor(15, 23, 42, a))
            p.drawRoundedRect(card.adjusted(-i, -i, i, i), SHEET_RADIUS + i, SHEET_RADIUS + i)
        p.end()
        super().paintEvent(ev)

    # ---------------- inside the app window ----------------
    def _host(self) -> Optional[QWidget]:
        p = self.parentWidget()
        return p.window() if p is not None else None

    def _content_area(self):
        """The host window's area below its tab bar, in screen coordinates (or the screen)."""
        host = self._host()
        scr = (host.screen() if host is not None else QApplication.primaryScreen()).availableGeometry()
        if host is None or not host.isVisible():
            return scr, scr
        top = 0
        nav = host.findChild(QWidget, "NavBar")
        if nav is not None and nav.isVisible():
            top = nav.mapTo(host, QPoint(0, nav.height())).y()
        if isinstance(host, SheetDialog):
            m = SHEET_MARGIN
            r = host.rect().adjusted(m, m, -m, -m)
        else:
            r = host.rect().adjusted(0, top, 0, 0)
        g = r.translated(host.mapToGlobal(QPoint(0, 0)))
        return g, scr

    def _place(self) -> None:
        area, scr = self._content_area()
        m = SHEET_MARGIN
        cw, ch = self._card_size
        # keep the card inside the app window (a little air round it), unless the window is tiny
        max_w = max(area.width() - 48, min(cw, scr.width() - 40))
        max_h = max(area.height() - 20, min(ch, scr.height() - 40))
        max_w = min(max_w, scr.width() - 40)
        max_h = min(max_h, scr.height() - 40)
        w, h = min(cw, max_w) + 2 * m, min(ch, max_h) + 2 * m
        w = max(w, self.minimumSizeHint().width())
        h = max(h, self.minimumSizeHint().height())
        self.resize(w, h)
        x = area.center().x() - w // 2
        y = area.center().y() - h // 2
        x = min(max(scr.left(), x), scr.right() - w + 1)
        y = min(max(scr.top(), y), scr.bottom() - h + 1)
        self.move(x, y)

    def showEvent(self, ev) -> None:
        if not self._placed:
            self._placed = True
            self._place()
        host = self._host()
        if host is not None and host.isVisible() and self._backdrop is None:
            self._backdrop = _Backdrop(host)
            self._backdrop.show()
        super().showEvent(ev)

    def hideEvent(self, ev) -> None:
        self._drop_backdrop()
        super().hideEvent(ev)

    def done(self, r) -> None:
        self._drop_backdrop()
        super().done(r)

    def _drop_backdrop(self) -> None:
        if self._backdrop is not None:
            self._backdrop.remove()
            self._backdrop = None

    def run(self) -> int:
        return self.exec()

    def add_header_menu(self, menu: QMenu, tip: str = "More options") -> QToolButton:
        """A ⋯ button next to the close button."""
        b = QToolButton()
        b.setObjectName("IconBtn")
        b.setIcon(icon("more", "#334155"))
        b.setIconSize(QSize(22, 22))
        b.setToolTip(tip)
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        b.setStyleSheet("QToolButton::menu-indicator{image:none;width:0px;}")
        b.setMenu(menu)
        self.head_layout.insertWidget(self.head_layout.count() - 1, b, 0, Qt.AlignmentFlag.AlignTop)
        return b


def info_box(icon_name: str, label: str):
    box = QFrame()
    box.setObjectName("InfoBox")
    lay = QHBoxLayout(box)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(14)
    ic = QLabel()
    ic.setPixmap(svg_pixmap(icon_name, "#334155", 24))
    lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(3)
    lab = QLabel(label)
    lab.setObjectName("InfoLabel")
    val = QLabel("")
    val.setObjectName("InfoValue")
    alt = QLabel("")
    alt.setObjectName("InfoAlt")
    alt.setWordWrap(True)
    col.addWidget(lab)
    col.addWidget(val)
    col.addWidget(alt)
    lay.addLayout(col, 1)
    return box, val, alt


def warn_box(lines) -> tuple:
    box = QFrame()
    box.setObjectName("WarnBox")
    lay = QHBoxLayout(box)
    lay.setContentsMargins(20, 12, 20, 12)
    lay.setSpacing(18)
    ic = QLabel()
    ic.setPixmap(svg_pixmap("warning", "#f5a623", 40))
    lay.addWidget(ic)
    txt = QLabel("\n".join(lines))
    txt.setObjectName("WarnText")
    txt.setWordWrap(True)
    lay.addWidget(txt, 1)
    return box, txt


# ======================================================================
# Print size editor (any unit)
# ======================================================================
class PrintSizeEditor(QWidget):
    changed = Signal()

    def __init__(self, spec: sh.PrintSpec, ratio: float, px_size, dpi: int, compact: bool = True,
                 parent=None):
        super().__init__(parent)
        self._w, self._h, self._unit = spec.width_in, spec.height_in, spec.unit
        self.ratio = ratio                      # design height / width
        self.px_size, self.dpi = px_size, dpi
        self.sp_w, self.sp_h = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.sp_w, self.sp_h):
            sp.setKeyboardTracking(False)
            sp.setMinimumWidth(92)
            sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.cb_unit = QComboBox()
        for t, v in UNIT_ITEMS:
            self.cb_unit.addItem(t, v)
        self.cb_unit.setCurrentIndex(max(0, self.cb_unit.findData(self._unit)))
        self.btn_lock = QToolButton()
        self.btn_lock.setObjectName("LinkToggle")
        self.btn_lock.setCheckable(True)
        self.btn_lock.setIconSize(QSize(18, 18))
        self.btn_lock.setToolTip("Keep the design's shape")
        self.btn_lock.setChecked(abs(self._h - self._w * ratio) <= max(0.01, self._h * 0.01))
        self.btn_lock.setIcon(icon("link" if self.btn_lock.isChecked() else "unlink", "#334155", "#ffffff"))
        self.btn_reset = QPushButton(f"Image size at {dpi} DPI")
        self.btn_reset.setObjectName("LinkBtn")
        self.btn_reset.setToolTip("Print size = pixels ÷ DPI")
        self.conv = QLabel("")
        self.conv.setObjectName("Hint")
        self.conv.setWordWrap(True)

        if compact:
            lay = QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            lab = QLabel("Print size")
            lab.setObjectName("Section")
            lay.addWidget(lab)
            lay.addWidget(self.sp_w)
            x = QLabel("×")
            lay.addWidget(x)
            lay.addWidget(self.sp_h)
            lay.addWidget(self.cb_unit)
            lay.addWidget(self.btn_lock)
            lay.addSpacing(6)
            lay.addWidget(self.btn_reset)
            lay.addStretch()
        else:
            g = QGridLayout(self)
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(8)
            g.setVerticalSpacing(6)
            g.addWidget(self._lab("Width"), 0, 0)
            g.addWidget(self._lab("Height"), 0, 2)
            g.addWidget(self.sp_w, 1, 0)
            g.addWidget(self.btn_lock, 1, 1)
            g.addWidget(self.sp_h, 1, 2)
            g.addWidget(self.cb_unit, 2, 0, 1, 3)
            g.addWidget(self.conv, 3, 0, 1, 3)
            g.addWidget(self.btn_reset, 4, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
            g.setColumnStretch(0, 1)
            g.setColumnStretch(2, 1)

        self.sp_w.valueChanged.connect(self._on_w)
        self.sp_h.valueChanged.connect(self._on_h)
        self.cb_unit.currentIndexChanged.connect(self._on_unit)
        self.btn_lock.toggled.connect(self._on_lock)
        self.btn_reset.clicked.connect(self.reset_to_pixels)
        self._refresh()

    @staticmethod
    def _lab(t):
        lab = QLabel(t)
        lab.setObjectName("FieldLabel")
        return lab

    def spec(self) -> sh.PrintSpec:
        return sh.PrintSpec(self._w, self._h, self._unit)

    def reset_to_pixels(self) -> None:
        s = sh.PrintSpec.from_pixels(self.px_size[0], self.px_size[1], self.dpi, self._unit)
        self._w, self._h = s.width_in, s.height_in
        self.btn_lock.setChecked(True)
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        u = self._unit
        d = SPIN_DECIMALS[u]
        lo, hi = sh.to_unit(0.05, u), sh.to_unit(3000, u)
        for sp, v in ((self.sp_w, self._w), (self.sp_h, self._h)):
            sp.blockSignals(True)
            sp.setDecimals(d)
            sp.setRange(lo, hi)
            sp.setSingleStep(1.0 if u in ("in", "cm") else 10.0 if u == "mm" else 0.5)
            sp.setValue(sh.to_unit(v, u))
            sp.blockSignals(False)
        others = [x for x in ("in", "cm", "mm") if x != u][:2] if u != "ft" else ["in", "cm"]
        self.conv.setText("=  " + "   =  ".join(
            f"{sh.to_unit(self._w, x):.{sh.UNIT_DECIMALS[x]}f} × {sh.to_unit(self._h, x):.{sh.UNIT_DECIMALS[x]}f} {x}"
            for x in others))

    def _on_w(self, v: float) -> None:
        self._w = max(0.01, sh.from_unit(v, self._unit))
        if self.btn_lock.isChecked():
            self._h = self._w * self.ratio
        self._refresh()
        self.changed.emit()

    def _on_h(self, v: float) -> None:
        self._h = max(0.01, sh.from_unit(v, self._unit))
        if self.btn_lock.isChecked():
            self._w = self._h / self.ratio
        self._refresh()
        self.changed.emit()

    def _on_unit(self, _i: int) -> None:
        self._unit = self.cb_unit.currentData()
        self._refresh()
        self.changed.emit()

    def _on_lock(self, on: bool) -> None:
        self.btn_lock.setIcon(icon("link" if on else "unlink", "#334155", "#ffffff"))
        if on:
            self._h = self._w * self.ratio
            self._refresh()
            self.changed.emit()


# ======================================================================
# Picture with dimension arrows
# ======================================================================
def _draw_arrow(p: QPainter, a: QPointF, b: QPointF, head: float = 9.0) -> None:
    import math
    p.drawLine(a, b)
    ang = math.atan2(b.y() - a.y(), b.x() - a.x())
    path = QPainterPath()
    for tip, t in ((b, ang), (a, ang + math.pi)):
        path.moveTo(tip)
        path.lineTo(tip.x() - head * math.cos(t - 0.42), tip.y() - head * math.sin(t - 0.42))
        path.lineTo(tip.x() - head * math.cos(t + 0.42), tip.y() - head * math.sin(t + 0.42))
        path.closeSubpath()
    p.fillPath(path, p.pen().color())


def _fit_font(base: QFont, text: str, max_w: float, size: float, min_size: float = 7.5) -> QFont:
    f = QFont(base)
    while size > min_size:
        f.setPointSizeF(size)
        if QFontMetrics(f).horizontalAdvance(text) <= max_w:
            return f
        size -= 0.5
    f.setPointSizeF(min_size)
    return f


class DimensionView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: Optional[QPixmap] = None
        self._wl = self._hl = ""
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_content(self, qimg: Optional[QImage], w_label: str, h_label: str) -> None:
        self._pix = QPixmap.fromImage(qimg) if qimg is not None else None
        self._wl, self._hl = w_label, h_label
        self.update()

    def image_rect(self) -> QRectF:
        pad, top, left = 18.0, 44.0, 50.0
        avail = QRectF(pad + left, pad + top, self.width() - 2 * pad - left - 10, self.height() - 2 * pad - top)
        if not self._pix or avail.width() <= 10 or avail.height() <= 10:
            return QRectF()
        r = self._pix.width() / self._pix.height()
        w = avail.width()
        h = w / r
        if h > avail.height():
            h = avail.height()
            w = h * r
        return QRectF(avail.left() + (avail.width() - w) / 2, avail.top() + (avail.height() - h) / 2, w, h)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.fillPath(path, QColor("#f6f8fb"))
        r = self.image_rect()
        if r.isEmpty():
            p.end()
            return
        p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))
        ink = QColor("#1e293b")
        p.setPen(QPen(ink, 1.6))
        base = QFont(self.font())
        base.setBold(True)
        gap = 12.0

        # horizontal
        f = _fit_font(base, self._wl, r.width() - 60, 11.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(self._wl)
        y = r.top() - 20
        lx = r.center().x() - tw / 2
        _draw_arrow(p, QPointF(lx - gap, y), QPointF(r.left(), y))
        _draw_arrow(p, QPointF(lx + tw + gap, y), QPointF(r.right(), y))
        p.drawText(QRectF(lx - 2, y - fm.height() / 2 - 1, tw + 4, fm.height()),
                   Qt.AlignmentFlag.AlignCenter, self._wl)

        # vertical (reads bottom to top)
        f2 = _fit_font(base, self._hl, r.height() - 60, 11.5)
        p.setFont(f2)
        fm2 = QFontMetrics(f2)
        th = fm2.horizontalAdvance(self._hl)
        x = r.left() - 24
        ly = r.center().y() - th / 2
        _draw_arrow(p, QPointF(x, ly - gap), QPointF(x, r.top()))
        _draw_arrow(p, QPointF(x, ly + th + gap), QPointF(x, r.bottom()))
        p.save()
        p.translate(x, r.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-th / 2 - 2, -fm2.height() / 2 - 1, th + 4, fm2.height()),
                   Qt.AlignmentFlag.AlignCenter, self._hl)
        p.restore()
        p.end()


# ======================================================================
# Common behaviour for both preview dialogs
# ======================================================================
class _PreviewBase(SheetDialog):
    kind = "preview"

    def __init__(self, parent, ctx: PreviewContext, icon_name, title, subtitle="", size=(1140, 820)):
        super().__init__(parent, icon_name, title, subtitle, size)
        self.ctx = ctx
        self.settings = QSettings("ImageResizeShare", "ImageResizeShare")
        self.opts = load_options(self.settings)
        self.ratio = ctx.image.height / ctx.image.width
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.refresh)
        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setVisible(False)
        self.add_header_menu(self._options_menu(self), "Options, copy, WhatsApp")

    # -- helpers -----------------------------------------------------
    def spec(self) -> sh.PrintSpec:
        raise NotImplementedError

    def _changed(self, *_):
        self.timer.start()

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _options_menu(self, parent) -> QMenu:
        m = QMenu(parent)
        m.addAction(icon("copy"), "Copy this preview", self.copy)
        m.addAction(icon("whatsapp", "#1f9d55"), "Copy and open WhatsApp", self.whatsapp)
        m.addSeparator()
        m.addAction("Edit warning note…", self._edit_note)
        m.addAction("Watermark text…", self._edit_wm)
        m.addAction("Footer (shop name / phone)…", self._edit_footer)
        sub = m.addMenu("Show area in")
        for t, v in (("Square feet (sq ft)", "sqft"), ("Square metres (sq m)", "sqm")):
            a = sub.addAction(t)
            a.setCheckable(True)
            a.setChecked(self.opts.area_unit == v)
            a.triggered.connect(lambda _=False, v=v, sub=sub: self._set_opt(area_unit=v, menu=sub))
        sub2 = m.addMenu("If the print shape is different")
        for t, v in (("Trim the design to fit", True), ("Show the whole design (white bars)", False)):
            a = sub2.addAction(t)
            a.setCheckable(True)
            a.setChecked(self.opts.fill == v)
            a.triggered.connect(lambda _=False, v=v, sub=sub2: self._set_opt(fill=v, menu=sub2))
        if self.ctx.classic_proof:
            m.addSeparator()
            m.addAction("Classic proof sheet (note header)…", self._classic)
        return m

    def _classic(self):
        self.accept()
        QTimer.singleShot(0, self.ctx.classic_proof)

    def _set_opt(self, menu=None, **kw):
        self.opts = replace(self.opts, **kw)
        if menu is not None:
            key = next(iter(kw.values()))
            vals = ["sqft", "sqm"] if "area_unit" in kw else [True, False]
            for a, v in zip(menu.actions(), vals):
                a.setChecked(v == key)
        save_options(self.settings, self.opts)
        self.refresh()

    def _edit_note(self):
        txt, ok = QInputDialog.getMultiLineText(self, "Warning note", "Up to 3 lines (shown on the preview):",
                                                "\n".join(self.opts.note_lines))
        if ok:
            self._set_opt(note_lines=[ln for ln in txt.splitlines() if ln.strip()][:3])

    def _edit_wm(self):
        txt, ok = QInputDialog.getText(self, "Watermark", "Text repeated across the design (empty = none):",
                                       text=self.opts.watermark)
        if ok:
            self._set_opt(watermark=txt)

    def _edit_footer(self):
        txt, ok = QInputDialog.getText(self, "Footer", "Shop name, phone or order number (empty = none):",
                                       text=self.opts.footer)
        if ok:
            self._set_opt(footer=txt)

    # -- output ------------------------------------------------------
    def render_sheet(self) -> Image.Image:
        raise NotImplementedError

    def _encode(self, img: Image.Image, fmt: str) -> bytes:
        return im.encode(img, im.OutputSettings(fmt=fmt, quality=92, dpi=150))

    def save_preview(self) -> Optional[Path]:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            img = self.render_sheet()
        finally:
            QApplication.restoreOverrideCursor()
        start = self.settings.value("last_save_dir", str(Path.home() / "Pictures"))
        name = sh.sheet_filename(self.ctx.src_name, self.spec(), self.kind, ".jpg")
        path, flt = QFileDialog.getSaveFileName(self, "Save preview", str(Path(str(start)) / name),
                                                "JPG image (*.jpg);;PNG image (*.png);;PDF document (*.pdf)")
        if not path:
            return None
        p = Path(path)
        fmt = {".png": "PNG", ".pdf": "PDF", ".jpg": "JPG", ".jpeg": "JPG"}.get(p.suffix.lower())
        if fmt is None:
            fmt = "PNG" if "PNG" in flt else "PDF" if "PDF" in flt else "JPG"
            p = p.with_suffix(im.FORMATS[fmt]["ext"])
        from app.ui.errors import save_or_warn, write_bytes_safely
        if not save_or_warn(self, lambda: write_bytes_safely(p, self._encode(img, fmt)), p):
            return None
        self.settings.setValue("last_save_dir", str(p.parent))
        self._say(f"Saved {p.name}")
        share.show_in_folder(p)
        return p

    def download_original(self) -> None:
        if not self.ctx.download_original:
            return
        p = self.ctx.download_original()
        if p:
            self._say(f"Saved the original print file: {Path(p).name}")

    def _temp(self, folder: Path) -> tuple:
        img = self.render_sheet()
        p = im.unique_path(folder / sh.sheet_filename(self.ctx.src_name, self.spec(), self.kind, ".jpg"))
        p.write_bytes(self._encode(img, "JPG"))
        return img, p

    def copy(self) -> None:
        img, p = self._temp(share.temp_folder())
        share.copy_to_clipboard(pil_to_qimage(img), p)
        self._say("Preview copied – press Ctrl+V to paste it")

    def whatsapp(self) -> None:
        img, p = self._temp(share.share_folder())
        share.copy_to_clipboard(pil_to_qimage(img), p)
        share.open_whatsapp(self.ctx.wa_target, self.ctx.wa_phone)
        self._say("Copied – press Ctrl+V in the WhatsApp chat")

    def _big_button(self, icon_name, text, obj, slot, color="#1e293b") -> QPushButton:
        b = QPushButton(icon(icon_name, color), "  " + text)
        b.setObjectName(obj)
        b.setIconSize(QSize(24, 24))
        b.setMinimumHeight(54)
        b.clicked.connect(slot)
        return b


# ======================================================================
# Download Preview (mockup 3)
# ======================================================================
class _EditableBox(QFrame):
    """An info box with a small ✎ button (used for the print size)."""
    clicked = Signal()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class DownloadPreviewDialog(_PreviewBase):
    kind = "preview"

    def __init__(self, parent, ctx: PreviewContext):
        super().__init__(parent, ctx, "download", "Download Preview", size=(960, 860))
        self._spec = sh.PrintSpec(ctx.spec.width_in, ctx.spec.height_in, ctx.spec.unit)
        boxes = QHBoxLayout()
        boxes.setSpacing(12)
        b1, self.v_size, self.a_size = info_box("frame", "Print Size (W × H)")
        b2, self.v_area, self.a_area = info_box("area", "Area")
        b3, self.v_words, self.a_quality = info_box("file_image", "Print Size (W × H)")
        # ✎ on the first box: change the print size
        edit = QToolButton(b1)
        edit.setObjectName("IconBtn")
        edit.setIcon(icon("ruler", "#155fc0"))
        edit.setIconSize(QSize(16, 16))
        edit.setText(" Edit")
        edit.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        edit.setStyleSheet("QToolButton{color:#155fc0;font-weight:600;}")
        edit.setToolTip("Change the print size (inches, cm, mm or feet)")
        edit.clicked.connect(self.edit_size)
        b1.layout().addWidget(edit, 0, Qt.AlignmentFlag.AlignTop)
        self.pill = QLabel("")
        self.pill.setStyleSheet("border-radius:9px;padding:2px 8px;font-size:8.5pt;font-weight:600;")
        b3.layout().addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        boxes.addWidget(b1, 5)
        boxes.addWidget(b2, 3)
        boxes.addWidget(b3, 5)
        self.body.addLayout(boxes)

        self.view = DimensionView()
        self.body.addWidget(self.view, 1)
        wb, self.warn_text = warn_box(self.opts.note_lines)
        self.warn = wb
        self.body.addWidget(wb)

        self.b_dl = self._big_button("download", "Download Preview", "Light", self.save_preview)
        self.b_orig = self._big_button("printer", "Download Original", "Light", self.download_original)
        self.b_orig.setToolTip("Save the full-resolution print file (format and DPI from Download settings)")
        self.b_orig.setVisible(ctx.download_original is not None)
        b_close = self._big_button("image", "Close", "Dark", self.accept, "#ffffff")
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        for b in (self.b_dl, self.b_orig, b_close):
            b.setMinimumWidth(220 if b is not b_close else 170)
            row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(self.status)
        self.refresh()

    def spec(self) -> sh.PrintSpec:
        return self._spec

    def edit_size(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Print size")
        lay = QVBoxLayout(dlg)
        ed = PrintSizeEditor(self._spec, self.ratio, self.ctx.image.size, self.ctx.dpi, compact=False)
        lay.addWidget(ed)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)

        def live():
            self._spec = ed.spec()
            self.refresh()
        ed.changed.connect(live)
        dlg.exec()
        live()

    def refresh(self) -> None:
        s = self.spec()
        w, h, u = s.width_in, s.height_in, s.unit
        self.v_size.setText(sh.size_text(w, h, u))
        self.a_size.setText(sh.size_alt_text(w, h, u))
        self.v_area.setText(sh.area_text(w, h, self.opts.area_unit))
        self.a_area.setText(sh.area_text(w, h, sh.other_area_unit(self.opts.area_unit)))
        self.v_words.setText(sh.size_words(w, h, u))
        self.a_quality.setText(sh.size_alt_text(w, h, u))
        ppi, level, text = sh.print_quality(self.ctx.image.width, self.ctx.image.height, w, h)
        bg, fg = {"good": ("#dcfce7", "#166534"), "ok": ("#fef3c7", "#92400e"), "low": ("#fee2e2", "#991b1b")}[level]
        self.pill.setText(f"{ppi:.0f} ppi")
        self.pill.setToolTip(f"{self.ctx.image.width} × {self.ctx.image.height} px · {text}")
        self.pill.setStyleSheet(f"background:{bg};color:{fg};border-radius:9px;padding:2px 8px;"
                                "font-size:8.5pt;font-weight:600;")
        shown = _shaped_display(self.ctx.image, s, self.opts.fill, self.opts.watermark)
        self.view.set_content(pil_to_qimage(shown), sh.length_label(w, u), sh.length_label(h, u))
        self.warn_text.setText("\n".join(self.opts.note_lines))
        self.warn.setVisible(bool(self.opts.note_lines))

    def render_sheet(self) -> Image.Image:
        return sh.render_download_preview(self.ctx.image, self.spec(), self.opts)


# ======================================================================
# Closeup Print Preview (mockup 2)
# ======================================================================
class CloseupCanvas(QWidget):
    centerChanged = Signal(float, float)
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self._full: Optional[Image.Image] = None       # print-shaped design, full resolution
        self._pix: Optional[QPixmap] = None
        self._center = (0.5, 0.5)
        self._zoom = 2.0
        self._inset_key = None
        self._inset_img: Optional[QImage] = None
        self._badge = QRectF()

    def set_image(self, full: Image.Image, display: Image.Image) -> None:
        self._full = full
        self._pix = QPixmap.fromImage(pil_to_qimage(display))
        self._inset_key = None
        self.update()

    def set_zoom(self, z: float) -> None:
        self._zoom = z
        self.update()

    def set_center(self, u: float, v: float) -> None:
        self._center = (min(1.0, max(0.0, u)), min(1.0, max(0.0, v)))
        self.update()

    def center(self):
        return self._center

    def image_rect(self) -> QRectF:
        if not self._pix:
            return QRectF()
        r = self._pix.width() / self._pix.height()
        w, h = self.width() - 2.0, self.height() - 2.0
        if w / h > r:
            w = h * r
        else:
            h = w / r
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _move_to(self, pos) -> None:
        r = self.image_rect()
        if r.isEmpty():
            return
        self.set_center((pos.x() - r.left()) / r.width(), (pos.y() - r.top()) / r.height())
        self.centerChanged.emit(*self._center)

    def _zoom_menu(self, pos) -> None:
        m = QMenu(self)
        for z in sh.ZOOM_LEVELS:
            a = m.addAction(f"Zoom: {z * 100:.0f}%")
            a.setCheckable(True)
            a.setChecked(abs(z - self._zoom) < 1e-6)
            a.triggered.connect(lambda _=False, z=z: (self.set_zoom(z), self.zoomChanged.emit(z)))
        m.exec(self.mapToGlobal(pos.toPoint()))

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            if self._badge.contains(ev.position()):
                self._zoom_menu(ev.position())
                return
            self._move_to(ev.position())

    def mouseMoveEvent(self, ev) -> None:
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._move_to(ev.position())
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self._badge.contains(ev.position())
                           else Qt.CursorShape.CrossCursor)

    def wheelEvent(self, ev) -> None:
        levels = list(sh.ZOOM_LEVELS)
        i = min(range(len(levels)), key=lambda k: abs(levels[k] - self._zoom))
        i = max(0, min(len(levels) - 1, i + (1 if ev.angleDelta().y() > 0 else -1)))
        if levels[i] != self._zoom:
            self.set_zoom(levels[i])
            self.zoomChanged.emit(levels[i])

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#ffffff"))
        r = self.image_rect()
        if r.isEmpty() or self._full is None:
            p.end()
            return
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.setClipPath(clip)
        p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))
        p.setClipping(False)

        lay = sh.closeup_layout(r.width(), r.height(), self._center, self._zoom)
        k = self._full.width / r.width()
        box = sh.source_box(lay, k)
        side = int(round(lay.inset[2] - lay.inset[0]))
        key = (box, side)
        if key != self._inset_key:
            crop = self._full.crop(box).resize((max(1, side), max(1, side)), Image.Resampling.LANCZOS)
            self._inset_img = pil_to_qimage(crop)
            self._inset_key = key
        red = QColor("#e11d2e")
        (x0, y0), (x1, y1) = lay.line
        p.setPen(QPen(red, 2))
        p.drawLine(QPointF(r.left() + x0, r.top() + y0), QPointF(r.left() + x1, r.top() + y1))
        p.setPen(QPen(red, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(r.left() + lay.box[0], r.top() + lay.box[1],
                          lay.box[2] - lay.box[0], lay.box[3] - lay.box[1]))
        ir = QRectF(r.left() + lay.inset[0], r.top() + lay.inset[1], side, side)
        p.fillRect(ir.adjusted(-4, -4, 4, 4), QColor("#ffffff"))
        p.drawImage(ir, self._inset_img)
        p.setPen(QPen(red, 3))
        p.drawRect(ir.adjusted(-1.5, -1.5, 1.5, 1.5))

        tag = f"Zoom: {self._zoom * 100:.0f}%"
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(11.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        bw, bh = fm.horizontalAdvance(tag) + 26, fm.height() + 16
        bx = r.left() + 12 if lay.badge_left else r.right() - 12 - bw
        self._badge = QRectF(bx, r.top() + 12, bw, bh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 24, 220))
        p.drawRoundedRect(self._badge, 6, 6)
        p.setPen(QColor("#ffffff"))
        p.drawText(self._badge, Qt.AlignmentFlag.AlignCenter, tag)
        p.end()


WIDTH_CHOICES = {
    "in": [4, 5, 6, 8, 10, 12, 16, 20, 24, 30, 36, 48, 60, 72, 96, 120, 144],
    "cm": [10, 15, 20, 25, 30, 40, 50, 60, 75, 90, 100, 120, 150, 200, 250, 300, 400],
    "mm": [100, 150, 200, 297, 420, 500, 600, 800, 1000, 1200, 1500, 2000, 3000],
    "ft": [1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 20],
}


class CloseupPrintPreviewDialog(_PreviewBase):
    kind = "closeup"

    def __init__(self, parent, ctx: PreviewContext, zoom: float = 2.0, center=(0.5, 0.42)):
        super().__init__(parent, ctx, "search", "Closeup Print Preview",
                         "Zoomed view to check print quality and details before printing", size=(1060, 850))
        self._w_in = ctx.spec.width_in
        self._unit = ctx.spec.unit if ctx.spec.unit in WIDTH_CHOICES else "in"
        zoom_s = self.settings.value("closeup_zoom")
        try:
            zoom = float(zoom_s) if zoom_s is not None else zoom
        except (TypeError, ValueError):
            pass
        if zoom not in sh.ZOOM_LEVELS:
            zoom = 2.0

        mid = QHBoxLayout()
        mid.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(14)
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 18)
        cl.setSpacing(10)
        t = QLabel("Print Size (Width × Height)")
        t.setObjectName("PaneTitle")
        cl.addWidget(t)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.cb_w = QComboBox()
        self.cb_w.setEditable(True)
        self.cb_w.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cb_w.setMinimumHeight(44)
        self.cb_w.setToolTip("Print width – type any value or pick one. The height follows the picture's shape.")
        self.cb_unit = QComboBox()
        self.cb_unit.setMinimumHeight(44)
        for txt, v in UNIT_ITEMS:
            self.cb_unit.addItem(txt, v)
        self.cb_unit.setCurrentIndex(max(0, self.cb_unit.findData(self._unit)))
        row.addWidget(self.cb_w, 1)
        row.addWidget(self.cb_unit, 1)
        cl.addLayout(row)
        self.conv = QLabel("")
        self.conv.setObjectName("Muted")
        cl.addWidget(self.conv)
        cl.addSpacing(10)
        t2 = QLabel("Area")
        t2.setObjectName("PaneTitle")
        cl.addWidget(t2)
        ab = QFrame()
        ab.setObjectName("InfoBox")
        al = QHBoxLayout(ab)
        al.setContentsMargins(14, 12, 14, 12)
        ic = QLabel()
        ic.setPixmap(svg_pixmap("area", "#334155", 24))
        al.addWidget(ic)
        self.v_area = QLabel("")
        self.v_area.setObjectName("InfoValue")
        al.addWidget(self.v_area, 1)
        cl.addWidget(ab)
        cl.addStretch(1)
        left.addWidget(card, 1)
        note = QFrame()
        note.setObjectName("NoteBox")
        nl = QHBoxLayout(note)
        nl.setContentsMargins(16, 14, 16, 14)
        nl.setSpacing(14)
        ni = QLabel()
        ni.setPixmap(svg_pixmap("search", "#1e293b", 26))
        nl.addWidget(ni, 0, Qt.AlignmentFlag.AlignTop)
        nt = QVBoxLayout()
        nt.setSpacing(4)
        a = QLabel("Print Preview")
        a.setObjectName("NoteTitle")
        b = QLabel("This is a closeup view to check image sharpness and details before printing.")
        b.setWordWrap(True)
        nt.addWidget(a)
        nt.addWidget(b)
        nl.addLayout(nt, 1)
        left.addWidget(note)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(290)
        mid.addWidget(lw)
        self.canvas = CloseupCanvas()
        self.canvas.set_center(*center)
        self.canvas.set_zoom(zoom)
        self.canvas.setToolTip("Click or drag to move the close-up · wheel or click the badge to zoom")
        mid.addWidget(self.canvas, 1)
        self.body.addLayout(mid, 1)

        strip = QFrame()
        strip.setObjectName("Strip")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(18, 12, 18, 12)
        sl.setSpacing(18)
        pi = QLabel()
        pi.setPixmap(svg_pixmap("printer", "#1e293b", 28))
        sl.addWidget(pi, 0, Qt.AlignmentFlag.AlignTop)
        st = QVBoxLayout()
        st.setSpacing(3)
        s1 = QLabel("Print Preview (Closeup)")
        s1.setObjectName("NoteTitle")
        s2 = QLabel("This zoomed preview helps you check fine details, sharpness and print quality.")
        s2.setObjectName("Muted")
        s2.setWordWrap(True)
        st.addWidget(s1)
        st.addWidget(s2)
        sl.addLayout(st, 3)
        for attr, lab in (("s_size", "Print Size:"), ("s_area", "Area:"), ("s_quality", "Quality:")):
            sep = QFrame()
            sep.setObjectName("StripSep")
            sep.setFixedWidth(1)
            sl.addWidget(sep)
            col = QVBoxLayout()
            col.setSpacing(2)
            l1 = QLabel(lab)
            l1.setObjectName("Muted")
            v = QLabel("")
            v.setObjectName("PaneTitle")
            col.addWidget(l1)
            col.addWidget(v)
            setattr(self, attr, v)
            if attr == "s_size":
                self.s_size_alt = QLabel("")
                self.s_size_alt.setObjectName("Muted")
                col.addWidget(self.s_size_alt)
            if attr == "s_quality":
                self.s_quality_alt = QLabel("")
                self.s_quality_alt.setObjectName("Muted")
                col.addWidget(self.s_quality_alt)
            col.addStretch()
            sl.addLayout(col, 2 if attr == "s_size" else 1)
        self.body.addWidget(strip)

        self.b_dl = self._big_button("search", "Download Closeup Preview", "Light", self.save_preview)
        self.b_orig = self._big_button("printer", "Download Original", "Light", self.download_original)
        self.b_orig.setToolTip("Save the full-resolution print file (format and DPI from Download settings)")
        self.b_orig.setVisible(ctx.download_original is not None)
        b_close = self._big_button("image", "Close", "Dark", self.accept, "#ffffff")
        b_close.setMinimumWidth(160)
        brow = QHBoxLayout()
        brow.setSpacing(14)
        brow.addWidget(self.status)
        brow.addStretch(1)
        for b_ in (self.b_dl, self.b_orig, b_close):
            b_.setMinimumWidth(200 if b_ is not b_close else 160)
            brow.addWidget(b_)
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(brow)

        self._fill_widths()
        self.cb_w.lineEdit().editingFinished.connect(self._on_width_text)
        self.cb_w.activated.connect(lambda _i: self._on_width_text())
        self.cb_unit.currentIndexChanged.connect(self._on_unit)
        self.canvas.zoomChanged.connect(lambda z: self.settings.setValue("closeup_zoom", z))
        self._shape_key = None
        self.refresh()

    # -- print size -------------------------------------------------
    def _fill_widths(self) -> None:
        u = self._unit
        self.cb_w.blockSignals(True)
        self.cb_w.clear()
        for v in WIDTH_CHOICES[u]:
            self.cb_w.addItem(f"{v:.2f}" if u in ("in", "ft") else f"{v:g}")
        d = sh.UNIT_DECIMALS[u]
        self.cb_w.setEditText(f"{sh.to_unit(self._w_in, u):.{d}f}")
        self.cb_w.blockSignals(False)

    def _on_width_text(self) -> None:
        try:
            v = float(self.cb_w.currentText().replace(",", ".").split()[0])
        except (ValueError, IndexError):
            self._fill_widths()
            return
        if v > 0:
            self._w_in = sh.from_unit(v, self._unit)
            self._changed()

    def _on_unit(self, _i) -> None:
        self._unit = self.cb_unit.currentData()
        self._fill_widths()
        self._changed()

    def spec(self) -> sh.PrintSpec:
        return sh.PrintSpec(self._w_in, self._w_in * self.ratio, self._unit)

    def zoom(self) -> float:
        return float(self.canvas._zoom)

    def refresh(self) -> None:
        s = self.spec()
        w, h, u = s.width_in, s.height_in, s.unit
        self.conv.setText(sh.conversions_text(w, u))
        self.v_area.setText(sh.area_text(w, h, self.opts.area_unit))
        self.s_size.setText(sh.size_text(w, h, u))
        self.s_size_alt.setText(sh.size_alt_text(w, h, u, first_only=True))
        self.s_area.setText(sh.area_text(w, h, self.opts.area_unit))
        ppi, level, text = sh.print_quality(self.ctx.image.width, self.ctx.image.height, w, h)
        color = {"good": "#15803d", "ok": "#b45309", "low": "#b91c1c"}[level]
        self.s_quality.setText(f"{ppi:.0f} ppi")
        self.s_quality.setStyleSheet(f"color:{color};")
        self.s_quality_alt.setText({"good": "excellent", "ok": "good for walls", "low": "low – upscale"}[level])
        key = (round(w / h, 4), self.opts.fill, self.opts.watermark)
        if key != self._shape_key:
            full = sh.shape_to_print(self.ctx.image, w, h, self.opts.fill)
            disp = _shaped_display(self.ctx.image, s, self.opts.fill, self.opts.watermark)
            self.canvas.set_image(full, disp)
            self._shape_key = key

    def render_sheet(self) -> Image.Image:
        return sh.render_closeup_preview(self.ctx.image, self.spec(), self.canvas.center(), self.zoom(),
                                         self.opts)


# ======================================================================
# Fullscreen viewer
# ======================================================================
class FullscreenViewer(FreeAfterExec, QDialog):
    def __init__(self, parent, qimg: QImage, title: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("background:#101114;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 8, 10, 8)
        t = QLabel(title)
        t.setStyleSheet("color:#e2e8f0;font-weight:600;font-size:11pt;background:transparent;")
        bar.addWidget(t)
        bar.addStretch()
        h = QLabel("Mouse wheel = zoom · drag = move · double-click = 100% / fit · Esc = close")
        h.setStyleSheet("color:#94a3b8;background:transparent;")
        bar.addWidget(h)
        close = QToolButton()
        close.setIcon(icon("close", "#e2e8f0"))
        close.setIconSize(QSize(22, 22))
        close.setStyleSheet("QToolButton{background:transparent;border:none;padding:6px;}"
                            "QToolButton:hover{background:#2a2d33;border-radius:6px;}")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        lay.addLayout(bar)
        self.view = ZoomView("", bg="#101114")
        self.view.setStyleSheet("background:#101114;border:none;")
        lay.addWidget(self.view, 1)
        self.view.set_image(qimg)

    def run(self) -> int:
        self.showFullScreen()
        QTimer.singleShot(0, self.view.fit)
        return self.exec()
