"""AI Upscale studio – Lupa-style modes, presets, 2x–16x or 'fit print size', before/after slider."""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget)

from app.core import imaging as im
from app.core import sheets as sh
from app.core import upscale as up
from app.ui import share
from app.ui.preview_dialogs import UNIT_ITEMS, SheetDialog
from app.ui.qtutil import TwoLineButton, hint, icon, pil_to_qimage

COMPARE_MAX = 8000     # longest side of the on-screen copy of the upscaled image


# ======================================================================
# Before / after slider
# ======================================================================
class CompareView(QWidget):
    """Drag the handle to compare; mouse wheel zooms, drag pans, double-click fits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._before: Optional[QPixmap] = None
        self._after: Optional[QPixmap] = None
        self._size = (1, 1)            # logical output size (pixels of the result)
        self._split = 0.5
        self._zoom = 1.0               # 1.0 = fit
        self._pan = QPointF(0, 0)
        self._drag: Optional[str] = None
        self._last = QPointF()
        self._busy_text = ""

    def set_images(self, before: QImage, after: Optional[QImage], out_size) -> None:
        self._before = QPixmap.fromImage(before)
        self._after = QPixmap.fromImage(after) if after is not None else None
        self._size = (max(1, out_size[0]), max(1, out_size[1]))
        self.update()

    def set_busy(self, text: str) -> None:
        self._busy_text = text
        self.update()

    def fit(self) -> None:
        self._zoom, self._pan = 1.0, QPointF(0, 0)
        self.update()

    def actual(self, factor: float = 1.0) -> None:
        f = self._fit_scale()
        self._zoom = max(0.05, factor / f)
        self.update()

    def _fit_scale(self) -> float:
        W, H = self._size
        return max(1e-6, min((self.width() - 24) / W, (self.height() - 24) / H))

    def _img_rect(self) -> QRectF:
        W, H = self._size
        s = self._fit_scale() * self._zoom
        w, h = W * s, H * s
        return QRectF((self.width() - w) / 2 + self._pan.x(), (self.height() - h) / 2 + self._pan.y(), w, h)

    def _split_x(self) -> float:
        r = self._img_rect()
        x = r.left() + r.width() * self._split
        return min(max(x, 0.0), float(self.width()))

    # ---------- events ----------
    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        if self._after is not None and abs(pos.x() - self._split_x()) < 16:
            self._drag = "split"
        else:
            self._drag = "pan"
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._last = pos

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        if self._drag == "split":
            r = self._img_rect()
            self._split = min(1.0, max(0.0, (pos.x() - r.left()) / max(1.0, r.width())))
            self.update()
        elif self._drag == "pan":
            self._pan += pos - self._last
            self._last = pos
            self.update()
        else:
            near = self._after is not None and abs(pos.x() - self._split_x()) < 16
            self.setCursor(Qt.CursorShape.SplitHCursor if near else Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, ev) -> None:
        self.fit()

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        pos = ev.position()
        r = self._img_rect()
        rel = QPointF((pos.x() - r.left()) / r.width(), (pos.y() - r.top()) / r.height())
        self._zoom = max(0.2, min(60.0, self._zoom * (1.25 ** steps)))
        r2 = self._img_rect()
        target = QPointF(r2.left() + rel.x() * r2.width(), r2.top() + rel.y() * r2.height())
        self._pan += pos - target
        self.update()

    # ---------- paint ----------
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#f6f8fb"))
        if not self._before:
            p.setPen(QColor("#94a3b8"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open an image first")
            p.end()
            return
        r = self._img_rect()
        sx = self._split_x() if self._after is not None else self.width() + 1
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # before (left of the handle)
        p.save()
        p.setClipRect(QRectF(0, 0, sx, self.height()))
        p.drawPixmap(r, self._before, QRectF(self._before.rect()))
        p.restore()
        if self._after is not None:
            p.save()
            p.setClipRect(QRectF(sx, 0, self.width() - sx, self.height()))
            p.drawPixmap(r, self._after, QRectF(self._after.rect()))
            p.restore()
            # handle
            p.setPen(QPen(QColor(0, 0, 0, 70), 4))
            p.drawLine(QPointF(sx, 0), QPointF(sx, self.height()))
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(QPointF(sx, 0), QPointF(sx, self.height()))
            c = QPointF(sx, self.height() / 2)
            p.setPen(QPen(QColor(0, 0, 0, 60), 1))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(c, 17, 17)
            p.setPen(QPen(QColor("#334155"), 2))
            for d in (-1, 1):
                path = QPainterPath()
                path.moveTo(c.x() + d * 4, c.y() - 5)
                path.lineTo(c.x() + d * 9, c.y())
                path.lineTo(c.x() + d * 4, c.y() + 5)
                p.drawPath(path)
        # labels
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)

        def chip(text, x, right=False):
            w = fm.horizontalAdvance(text) + 20
            rr = QRectF(x - w if right else x, 12, w, fm.height() + 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(15, 23, 42, 190))
            p.drawRoundedRect(rr, 6, 6)
            p.setPen(QColor("#ffffff"))
            p.drawText(rr, Qt.AlignmentFlag.AlignCenter, text)

        if self._after is not None:
            chip("Before", 12)
            chip("After (AI upscaled)", self.width() - 12, right=True)
        else:
            chip("Original", 12)
        if self._busy_text:
            w = fm.horizontalAdvance(self._busy_text) + 40
            rr = QRectF((self.width() - w) / 2, self.height() - 60, w, 38)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(15, 23, 42, 210))
            p.drawRoundedRect(rr, 10, 10)
            p.setPen(QColor("#ffffff"))
            p.drawText(rr, Qt.AlignmentFlag.AlignCenter, self._busy_text)
        p.end()


# ======================================================================
# Background job
# ======================================================================
class _Signals(QObject):
    finished = Signal(int, object, object, float)    # gen, image, notes, seconds
    failed = Signal(int, str)
    progress = Signal(int, str)


class UpscaleJob(QRunnable):
    def __init__(self, gen, img, us, ai):
        super().__init__()
        self.setAutoDelete(False)
        self.gen, self.img, self.us, self.ai = gen, img, us, ai
        self.signals = _Signals()

    def run(self) -> None:
        t0 = time.time()
        notes: list = []
        try:
            out = up.upscale(self.img, self.us, self.ai, notes,
                             progress=lambda m: self.signals.progress.emit(self.gen, m))
            self.signals.finished.emit(self.gen, out, notes, time.time() - t0)
        except MemoryError:
            self.signals.failed.emit(self.gen, "Not enough memory for this size. Choose a smaller factor.")
        except Exception as exc:
            traceback.print_exc()
            self.signals.failed.emit(self.gen, str(exc))


# ======================================================================
# Studio dialog
# ======================================================================
def _card(title: str):
    c = QFrame()
    c.setObjectName("Card")
    lay = QVBoxLayout(c)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    t = QLabel(title)
    t.setObjectName("PaneTitle")
    lay.addWidget(t)
    return c, lay


class UpscaleDialog(SheetDialog):
    """Lupa-style upscaler. ``applied`` carries the upscaled image back to the editor."""
    applied = Signal(object, object, int, str)    # image, UpscaleSettings, dpi (0 = keep), print unit

    def __init__(self, parent, image: Image.Image, src_name: Optional[str], ai_engine, dpi: int = 300):
        super().__init__(parent, "sparkle", "AI Upscale",
                         "Make small images big and sharp for wallpaper & print – runs offline on this PC",
                         size=(1320, 880))
        self.image = image if image.mode in ("RGB", "RGBA") else image.convert("RGB")
        self.src_name = src_name
        self.ai = ai_engine
        self.dpi = dpi
        self.settings = QSettings("ImageResizeShare", "ImageResizeShare")
        self.us = up.UpscaleSettings()
        self.result: Optional[Image.Image] = None
        self.result_us: Optional[up.UpscaleSettings] = None
        self.gen = 0
        self.jobs: set = set()
        self.pool = QThreadPool.globalInstance()
        self._t0 = 0.0
        self._fit_w_in = 96.0
        self._before_q = pil_to_qimage(self.image)

        mid = QHBoxLayout()
        mid.setSpacing(16)
        mid.addWidget(self._build_controls())
        right = QVBoxLayout()
        right.setSpacing(8)
        tb = QHBoxLayout()
        lab = QLabel("Before / After")
        lab.setObjectName("PaneTitle")
        tb.addWidget(lab)
        tb.addWidget(hint("  Drag the white handle to compare · wheel to zoom · drag to move"))
        tb.addStretch()
        for text, slot in (("Fit", lambda: self.compare.fit()), ("100%", lambda: self.compare.actual(1.0)),
                           ("200%", lambda: self.compare.actual(2.0))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            tb.addWidget(b)
        right.addLayout(tb)
        self.compare = CompareView()
        right.addWidget(self.compare, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        right.addWidget(self.progress)
        mid.addLayout(right, 1)
        self.body.addLayout(mid, 1)

        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.info = QLabel("")
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        foot.addWidget(self.info, 1)
        self.b_go = QPushButton(icon("sparkle", "#ffffff"), "  Upscale")
        self.b_go.setObjectName("AIButton")
        self.b_go.setIconSize(QSize(20, 20))
        self.b_go.setMinimumHeight(48)
        self.b_go.setMinimumWidth(170)
        self.b_go.clicked.connect(self.run_upscale)
        self.b_save = QPushButton(icon("download"), "  Download Upscaled")
        self.b_save.setObjectName("Light")
        self.b_use = QPushButton(icon("image", "#ffffff"), "  Use in Editor")
        self.b_use.setObjectName("Dark")
        self.b_use.setToolTip("Continue with the upscaled image: crop, preview, print, share")
        b_close = QPushButton("Close")
        b_close.setObjectName("Light")
        for b in (self.b_save, self.b_use, b_close):
            b.setIconSize(QSize(20, 20))
            b.setMinimumHeight(48)
        self.b_save.clicked.connect(self.save_result)
        self.b_use.clicked.connect(self.use_result)
        b_close.clicked.connect(self.reject)
        for b in (self.b_go, self.b_save, self.b_use, b_close):
            foot.addWidget(b)
        self.body.addLayout(foot)

        self.elapsed = QTimer(self)
        self.elapsed.setInterval(500)
        self.elapsed.timeout.connect(self._tick)
        self._load_settings()
        self._sync_controls()
        self._update_info()
        self._show_compare()

    # ------------------------------------------------------------------
    def _build_controls(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)

        # mode
        c, cl = _card("1.  Mode")
        g = QGridLayout()
        g.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        self.mode_btns = {}
        for i, (key, (title, desc)) in enumerate(up.MODES.items()):
            b = TwoLineButton(title, desc, obj="ModeCard", align_left=True)
            b.setMinimumHeight(68)
            self.mode_group.addButton(b, i)
            self.mode_btns[key] = b
            b.clicked.connect(lambda _=False, k=key: self._set(mode=k))
            g.addWidget(b, i // 2, i % 2)
        cl.addLayout(g)
        lay.addWidget(c)

        # presets
        c, cl = _card("2.  One-click presets")
        g = QGridLayout()
        g.setSpacing(6)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(False)
        self.preset_btns = {}
        for i, (name, _vals) in enumerate(up.PRESETS):
            b = QPushButton(name.replace("&", "&&"))
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=name: self._preset(n))
            self.preset_btns[name] = b
            g.addWidget(b, i // 3, i % 3)
        cl.addLayout(g)
        lay.addWidget(c)

        # scale
        c, cl = _card("3.  Upscale by")
        row = QHBoxLayout()
        row.setSpacing(0)
        self.factor_group = QButtonGroup(self)
        self.factor_btns = {}
        n = len(up.FACTORS)
        for i, f in enumerate(up.FACTORS):
            b = QPushButton(f"{f:g}×")
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            css = []
            if i == 0:
                css.append("border-top-left-radius:8px;border-bottom-left-radius:8px;")
            if i == n - 1:
                css.append("border-top-right-radius:8px;border-bottom-right-radius:8px;")
            b.setStyleSheet("".join(css))
            self.factor_group.addButton(b, i)
            self.factor_btns[f] = b
            b.clicked.connect(lambda _=False, f=f: self._set_factor(f))
            row.addWidget(b)
        cl.addLayout(row)
        self.b_fit = QPushButton(icon("ruler"), "  Fit a print / wall size")
        self.b_fit.setCheckable(True)
        self.b_fit.setObjectName("Chip")
        self.b_fit.toggled.connect(self._on_fit_toggled)
        cl.addWidget(self.b_fit)
        self.fit_box = QWidget()
        fg = QGridLayout(self.fit_box)
        fg.setContentsMargins(0, 0, 0, 0)
        fg.setHorizontalSpacing(8)
        fg.setVerticalSpacing(4)
        fg.addWidget(QLabel("Width"), 0, 0)
        fg.addWidget(QLabel("Unit"), 0, 1)
        fg.addWidget(QLabel("DPI"), 0, 2)
        self.sp_pw = QDoubleSpinBox()
        self.sp_pw.setDecimals(2)
        self.sp_pw.setRange(0.1, 100000)
        self.sp_pw.setKeyboardTracking(False)
        self.cb_pu = QComboBox()
        for t, v in UNIT_ITEMS:
            self.cb_pu.addItem(t, v)
        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(36, 1200)
        self.sp_dpi.setKeyboardTracking(False)
        fg.addWidget(self.sp_pw, 1, 0)
        fg.addWidget(self.cb_pu, 1, 1)
        fg.addWidget(self.sp_dpi, 1, 2)
        self.lbl_ph = QLabel("")
        self.lbl_ph.setObjectName("Hint")
        fg.addWidget(self.lbl_ph, 2, 0, 1, 3)
        fg.addWidget(hint("Wallpaper & murals: 100–150 DPI is plenty – they're seen from a distance. "
                          "To match a wall's shape, crop first."), 3, 0, 1, 3)
        self.sp_pw.valueChanged.connect(lambda _v: self._fit_changed())
        self.cb_pu.currentIndexChanged.connect(self._unit_changed)
        self.sp_dpi.valueChanged.connect(lambda _v: self._fit_changed())
        cl.addWidget(self.fit_box)
        self.out_info = QLabel("")
        self.out_info.setTextFormat(Qt.TextFormat.RichText)
        self.out_info.setWordWrap(True)
        cl.addWidget(self.out_info)
        lay.addWidget(c)

        # fine-tune
        c, cl = _card("4.  Fine-tune")
        self.sliders = {}
        self.slider_vals = {}
        for key, label, tip in (("detail", "Detail / sharpness", "How crisp edges and fine detail look"),
                                ("denoise", "Remove noise", "Cleans JPEG blocks and grain before enlarging"),
                                ("texture", "Texture", "Adds fine grain so big prints don't look plastic")):
            r = QHBoxLayout()
            lab = QLabel(label)
            lab.setToolTip(tip)
            lab.setMinimumWidth(118)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 100)
            s.setObjectName("BlueSlider")
            v = QLabel("0")
            v.setFixedWidth(28)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            s.valueChanged.connect(lambda val, k=key: self._set(**{k: val}))
            r.addWidget(lab)
            r.addWidget(s, 1)
            r.addWidget(v)
            cl.addLayout(r)
            self.sliders[key] = s
            self.slider_vals[key] = v
        lay.addWidget(c)

        eng = QHBoxLayout()
        dot = QLabel("●")
        ok = self.ai is not None and self.ai.available()
        dot.setStyleSheet(f"color:{'#16a34a' if ok else '#d97706'};font-size:12pt;")
        eng.addWidget(dot)
        txt = (self.ai.status_text() + " – Real-ESRGAN on your graphics card") if ok else \
            ((self.ai.status_text() if self.ai else "AI engine not installed") +
             " – Enhanced upscaling will be used")
        el = hint(txt)
        eng.addWidget(el, 1)
        lay.addLayout(eng)
        lay.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        scroll.setFixedWidth(360)
        return scroll

    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        s = self.settings
        mode = str(s.value("up_mode", up.MODE_FIDELITY))
        self.us.mode = mode if mode in up.MODES else up.MODE_FIDELITY
        for k in ("detail", "denoise", "texture"):
            try:
                setattr(self.us, k, int(s.value(f"up_{k}", getattr(self.us, k))))
            except (TypeError, ValueError):
                pass
        try:
            f = float(s.value("up_factor", 4.0))
        except (TypeError, ValueError):
            f = 4.0
        self.us.factor = f if f in up.FACTORS else 4.0
        unit = str(s.value("up_unit", "ft"))
        self.cb_pu.blockSignals(True)
        self.cb_pu.setCurrentIndex(max(0, self.cb_pu.findData(unit if unit in sh.UNITS else "ft")))
        self.cb_pu.blockSignals(False)
        try:
            w_in = float(s.value("up_width_in", 96.0))
            dpi = int(s.value("up_dpi", 100))
        except (TypeError, ValueError):
            w_in, dpi = 96.0, 100
        self._fit_w_in = w_in
        self.sp_dpi.blockSignals(True)
        self.sp_dpi.setValue(dpi)
        self.sp_dpi.blockSignals(False)
        self._refresh_fit_spin()

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("up_mode", self.us.mode)
        s.setValue("up_factor", self.us.factor)
        for k in ("detail", "denoise", "texture"):
            s.setValue(f"up_{k}", getattr(self.us, k))
        s.setValue("up_unit", self.cb_pu.currentData())
        s.setValue("up_width_in", self._fit_w_in)
        s.setValue("up_dpi", self.sp_dpi.value())

    def _sync_controls(self) -> None:
        self.mode_btns[self.us.mode].setChecked(True)
        fb = self.factor_btns.get(self.us.factor)
        if fb and not self.b_fit.isChecked():
            fb.setChecked(True)
        for k, s in self.sliders.items():
            val = getattr(self.us, k)
            s.blockSignals(True)
            s.setValue(val)
            s.blockSignals(False)
            self.slider_vals[k].setText(str(val))
        self.fit_box.setVisible(self.b_fit.isChecked())
        for name, vals in up.PRESETS:
            cur = {k: getattr(self.us, k) for k in vals}
            self.preset_btns[name].setChecked(cur == vals)

    def _set(self, **kw) -> None:
        changed = False
        for k, v in kw.items():
            if getattr(self.us, k) != v:
                setattr(self.us, k, v)
                changed = True
        if changed:
            self._sync_controls()
            self._update_info()

    def _preset(self, name: str) -> None:
        self.us = up.apply_preset(self.us, name)
        self._sync_controls()
        self._update_info()

    def _set_factor(self, f: float) -> None:
        self.b_fit.setChecked(False)
        self.us.factor = f
        self.us.target = None
        self._update_info()

    def _on_fit_toggled(self, on: bool) -> None:
        self.fit_box.setVisible(on)
        self.factor_group.setExclusive(not on)
        for b in self.factor_btns.values():
            if on:
                b.setChecked(False)
        if not on:
            self.us.target = None
            fb = self.factor_btns.get(self.us.factor)
            if fb:
                fb.setChecked(True)
        self.factor_group.setExclusive(True)
        self._fit_changed()

    def _refresh_fit_spin(self) -> None:
        u = self.cb_pu.currentData()
        self.sp_pw.blockSignals(True)
        self.sp_pw.setDecimals(1 if u == "mm" else 2)
        self.sp_pw.setValue(sh.to_unit(self._fit_w_in, u))
        self.sp_pw.blockSignals(False)

    def _unit_changed(self, _i) -> None:
        self._refresh_fit_spin()
        self._fit_changed()

    def _fit_changed(self) -> None:
        u = self.cb_pu.currentData()
        self._fit_w_in = sh.from_unit(self.sp_pw.value(), u)
        w_in = self._fit_w_in
        h_in = w_in * self.image.height / self.image.width
        self.lbl_ph.setText(f"Height: {sh.fmt_len(h_in, u)} (keeps the picture's shape)  ·  "
                            f"area {sh.area_text(w_in, h_in)}")
        if self.b_fit.isChecked():
            self.us.target = up.size_for_print(self.image.size, w_in, h_in, self.sp_dpi.value())
        else:
            self.us.target = None
        self._update_info()

    def _update_info(self) -> None:
        tw, th = up.target_size(self.image.size, self.us)
        f = tw / self.image.width
        fit = self.b_fit.isChecked()
        dpi = self.sp_dpi.value() if fit else self.dpi
        unit = self.cb_pu.currentData() if fit else ("in" if tw / dpi < 36 else "ft")
        msg = up.check_target((tw, th))
        lines = [f"<b>Output:</b> {tw:,} × {th:,} px &nbsp;({tw * th / 1e6:.1f} MP, {f:.2f}×)",
                 f"<b>Prints:</b> {sh.size_text(tw / dpi, th / dpi, unit)} at {dpi} DPI"]
        if msg:
            lines.append(f"<span style='color:#b91c1c'>{msg}</span>")
        elif tw * th > 60e6:
            lines.append("<span style='color:#b45309'>Big job – AI can take a few minutes.</span>")
        self.out_info.setText("<br>".join(lines))
        self.b_go.setEnabled(msg is None and not self.jobs)
        has = self.result is not None
        self.b_save.setEnabled(has)
        self.b_use.setEnabled(has)
        src = f"Original {self.image.width:,} × {self.image.height:,} px"
        if has:
            r = self.result
            same = self.result_us == self.us
            self.info.setText(f"{src}  →  upscaled {r.width:,} × {r.height:,} px "
                              f"({up.MODES[self.result_us.mode][0]})"
                              + ("" if same else "   ·   settings changed – press Upscale to update"))
        else:
            self.info.setText(f"{src}. Choose a mode and size, then press Upscale.")

    def _show_compare(self) -> None:
        if self.result is None:
            self.compare.set_images(self._before_q, None, self.image.size)
            return
        disp = self.result
        if max(disp.size) > COMPARE_MAX:
            disp = disp.copy()
            disp.thumbnail((COMPARE_MAX, COMPARE_MAX), Image.Resampling.LANCZOS)
        self.compare.set_images(self._before_q, pil_to_qimage(disp), self.result.size)

    # ------------------------------------------------------------------
    def run_upscale(self) -> None:
        msg = up.check_target(up.target_size(self.image.size, self.us))
        if msg:
            QMessageBox.information(self, "Too large", msg)
            return
        self.gen += 1
        job = UpscaleJob(self.gen, self.image, self.us.copy(), self.ai)
        job.signals.finished.connect(self._on_done)
        job.signals.failed.connect(self._on_failed)
        job.signals.progress.connect(self._on_progress)
        self.jobs.add(job)
        self._t0 = time.time()
        self.progress.setVisible(True)
        self.b_go.setEnabled(False)
        self.compare.set_busy("Upscaling…")
        self.elapsed.start()
        self._save_settings()
        self.pool.start(job)

    def _tick(self) -> None:
        if self.jobs:
            self.compare.set_busy(f"{self._status}  {time.time() - self._t0:.0f} s")

    _status = "Upscaling…"

    def _on_progress(self, gen, msg) -> None:
        if gen == self.gen:
            self._status = msg
            self._tick()

    def _finish_job(self, gen) -> None:
        self.jobs = {j for j in self.jobs if j.gen != gen}
        if not self.jobs:
            self.elapsed.stop()
            self.progress.setVisible(False)
            self.compare.set_busy("")

    def _on_done(self, gen, img, notes, secs) -> None:
        self._finish_job(gen)
        if gen != self.gen:
            return
        self.result = img
        self.result_us = self.us.copy()
        self._show_compare()
        self._update_info()
        if notes:
            self.info.setText(self.info.text() + "   ·   " + " ".join(notes))
        self.info.setToolTip(f"Done in {secs:.1f} s")

    def _on_failed(self, gen, msg) -> None:
        self._finish_job(gen)
        self._update_info()
        if gen == self.gen:
            QMessageBox.warning(self, "Upscale failed", msg)

    def wait_done(self, timeout_ms: int = 600000) -> None:
        """Block until the current job finishes (used by the self-test)."""
        from PySide6.QtCore import QEventLoop
        from PySide6.QtWidgets import QApplication
        t_end = time.time() + timeout_ms / 1000
        while self.jobs and time.time() < t_end:
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            time.sleep(0.02)
        QApplication.processEvents()

    # ------------------------------------------------------------------
    def _out_dpi(self) -> int:
        return self.sp_dpi.value() if (self.result_us and self.result_us.target) else self.dpi

    def save_result(self) -> Optional[Path]:
        if self.result is None:
            return None
        start = self.settings.value("last_save_dir", str(Path.home() / "Pictures"))
        stem = Path(self.src_name).stem if self.src_name else "image"
        name = f"{stem}_upscaled_{self.result.width}x{self.result.height}.png"
        path, flt = QFileDialog.getSaveFileName(
            self, "Download upscaled image", str(Path(str(start)) / name),
            "PNG – lossless (*.png);;TIFF – lossless, for print (*.tif);;JPG (*.jpg);;PDF (*.pdf)")
        if not path:
            return None
        p = Path(path)
        fmt = {".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".jpg": "JPG", ".jpeg": "JPG",
               ".pdf": "PDF"}.get(p.suffix.lower())
        if fmt is None:
            fmt = "TIFF" if "TIFF" in flt else "JPG" if "JPG" in flt else "PDF" if "PDF" in flt else "PNG"
            p = p.with_suffix(im.FORMATS[fmt]["ext"])
        from app.ui.errors import save_or_warn, write_bytes_safely
        data = lambda: im.encode(self.result, im.OutputSettings(fmt=fmt, quality=95, dpi=self._out_dpi()))  # noqa: E731
        if not save_or_warn(self, lambda: write_bytes_safely(p, data()), p):
            return None
        self.settings.setValue("last_save_dir", str(p.parent))
        self.info.setText(f"Saved {p.name}")
        share.show_in_folder(p)
        return p

    def use_result(self) -> None:
        if self.result is None:
            return
        self._save_settings()
        fit = bool(self.result_us and self.result_us.target)
        self.applied.emit(self.result, self.result_us, self.sp_dpi.value() if fit else 0,
                          self.cb_pu.currentData() if fit else "")
        self.accept()

    def reject(self) -> None:
        self._save_settings()
        super().reject()
