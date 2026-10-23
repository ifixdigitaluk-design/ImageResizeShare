"""Proof sheet dialog: preview with print size, area (sq ft) and note."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from app.core import imaging as im
from app.core import proof
from app.ui import share
from app.ui.qtutil import FreeAfterExec
from app.ui.qtutil import Card, hint, icon, pil_to_qimage, section
from app.ui.views import ZoomView

MAX_SOURCE_SIDE = 6000   # enough for a crisp close-up, keeps the dialog fast


class ProofDialog(FreeAfterExec, QDialog):
    def __init__(self, parent, image: Image.Image, src_name: str | None, dpi: int,
                 wa_target: str = "web", wa_phone: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Proof sheet – preview with size & area")
        self.resize(1280, 860)
        self.settings = QSettings("ImageResizeShare", "ImageResizeShare")
        self.src_name = src_name
        self.wa_target, self.wa_phone = wa_target, wa_phone
        self.full_px = image.size
        img = image.convert("RGB")
        if max(img.size) > MAX_SOURCE_SIDE:
            img = img.copy()
            img.thumbnail((MAX_SOURCE_SIDE, MAX_SOURCE_SIDE), Image.Resampling.LANCZOS)
        self.image = img
        self.ratio = image.height / image.width
        self.rendered: Image.Image | None = None
        self.ps = proof.ProofSettings()
        self.ps.closeup_center = (0.5, 0.5)

        root = QHBoxLayout(self)
        root.setSpacing(14)

        # ---------------- left: options ----------------
        form_w = QWidget()
        form = QVBoxLayout(form_w)
        form.setContentsMargins(0, 0, 6, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(form_w)
        scroll.setFixedWidth(400)
        root.addWidget(scroll)

        c1 = Card("Print size")
        g = QGridLayout()
        g.addWidget(QLabel("Width (in)"), 0, 0)
        g.addWidget(QLabel("Height (in)"), 0, 1)
        self.sp_w, self.sp_h = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.sp_w, self.sp_h):
            sp.setRange(0.5, 2000)
            sp.setDecimals(2)
            sp.setKeyboardTracking(False)
        g.addWidget(self.sp_w, 1, 0)
        g.addWidget(self.sp_h, 1, 1)
        c1.lay.addLayout(g)
        self.chk_lock = QCheckBox("Keep the design's shape")
        self.chk_lock.setChecked(True)
        c1.lay.addWidget(self.chk_lock)
        r = QHBoxLayout()
        r.addWidget(QLabel("Show size in"))
        self.cb_unit = QComboBox()
        for t, v in (("Inches  (125”x 104”)", "in"), ("Feet + inches  (10'5” x 8'8”)", "ft"),
                     ("Centimetres", "cm")):
            self.cb_unit.addItem(t, v)
        r.addWidget(self.cb_unit, 1)
        c1.lay.addLayout(r)
        r2 = QHBoxLayout()
        self.chk_area = QCheckBox("Show area in")
        self.chk_area.setChecked(True)
        self.cb_area = QComboBox()
        self.cb_area.addItem("Square feet (Sq.Ft)", "sqft")
        self.cb_area.addItem("Square metres (Sq.M)", "sqm")
        r2.addWidget(self.chk_area)
        r2.addWidget(self.cb_area, 1)
        c1.lay.addLayout(r2)
        self.area_big = QLabel("")
        self.area_big.setStyleSheet("font-size:15pt;font-weight:700;color:#0f172a;")
        c1.lay.addWidget(self.area_big)
        self.res_info = hint("")
        self.res_info.setTextFormat(Qt.TextFormat.RichText)
        c1.lay.addWidget(self.res_info)
        self.cb_fit = QComboBox()
        self.cb_fit.addItem("Trim design to the print shape", True)
        self.cb_fit.addItem("Show whole design (white bars)", False)
        c1.lay.addWidget(self.cb_fit)
        form.addWidget(c1)

        c2 = Card("Note")
        self.ed_title = QLineEdit("NOTE:-")
        self.ed_note = QPlainTextEdit("\n".join(proof.DEFAULT_NOTE))
        self.ed_note.setFixedHeight(80)
        c2.lay.addWidget(self.ed_title)
        c2.lay.addWidget(self.ed_note)
        c2.lay.addWidget(hint("Up to 3 lines. Text shrinks automatically to fit."))
        form.addWidget(c2)

        c3 = Card("Extras")
        self.chk_close = QCheckBox("Add close-up detail")
        c3.lay.addWidget(self.chk_close)
        c3.lay.addWidget(hint("Click on the preview to choose the close-up spot."))
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Close-up area"))
        self.cb_cz = QComboBox()
        for t, v in (("Small (strong zoom)", 0.10), ("Medium", 0.16), ("Large", 0.26)):
            self.cb_cz.addItem(t, v)
        self.cb_cz.setCurrentIndex(1)
        r3.addWidget(self.cb_cz, 1)
        c3.lay.addLayout(r3)
        c3.lay.addWidget(section("Watermark (protects your design)"))
        self.ed_wm = QLineEdit()
        self.ed_wm.setPlaceholderText("e.g. your shop name – leave empty for none")
        c3.lay.addWidget(self.ed_wm)
        c3.lay.addWidget(section("Footer"))
        self.ed_footer = QLineEdit()
        self.ed_footer.setPlaceholderText("e.g. shop name · phone · order number")
        c3.lay.addWidget(self.ed_footer)
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Proof width"))
        self.cb_px = QComboBox()
        for v in (1200, 1800, 2400, 3200):
            self.cb_px.addItem(f"{v} px", v)
        self.cb_px.setCurrentIndex(1)
        r4.addWidget(self.cb_px, 1)
        c3.lay.addLayout(r4)
        form.addWidget(c3)
        form.addStretch()

        # ---------------- right: preview + buttons ----------------
        right = QVBoxLayout()
        self.view = ZoomView("Rendering…")
        self.view.clicked.connect(self._on_preview_click)
        right.addWidget(self.view, 1)
        self.info = hint("")
        right.addWidget(self.info)
        btns = QHBoxLayout()
        b_save = QPushButton(icon("save"), "  Save proof…")
        b_save.setObjectName("Primary")
        b_copy = QPushButton(icon("copy"), "  Copy")
        b_wa = QPushButton(icon("chat", "#ffffff"), "  Send on WhatsApp")
        b_wa.setObjectName("WhatsApp")
        b_close = QPushButton("Close")
        for b in (b_save, b_copy, b_wa):
            b.setIconSize(QSize(20, 20))
            b.setMinimumHeight(44)
        b_save.clicked.connect(self.save)
        b_copy.clicked.connect(self.copy)
        b_wa.clicked.connect(self.whatsapp)
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_save, 2)
        btns.addWidget(b_copy, 1)
        btns.addWidget(b_wa, 2)
        btns.addWidget(b_close, 1)
        right.addLayout(btns)
        root.addLayout(right, 1)

        # ---------------- state ----------------
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.render)
        self._load_settings(dpi)

        self.sp_w.valueChanged.connect(self._on_w)
        self.sp_h.valueChanged.connect(self._on_h)
        for w in (self.cb_unit, self.cb_area, self.cb_fit, self.cb_cz, self.cb_px):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.chk_area, self.chk_close, self.chk_lock):
            w.toggled.connect(self._changed)
        for w in (self.ed_title, self.ed_wm, self.ed_footer):
            w.textChanged.connect(self._changed)
        self.ed_note.textChanged.connect(self._changed)
        self.render()

    # ------------------------------------------------------------------
    def _load_settings(self, dpi: int) -> None:
        s = self.settings
        w_in = self.full_px[0] / max(1, dpi)
        self.sp_w.setValue(round(w_in, 2))
        self.sp_h.setValue(round(w_in * self.ratio, 2))
        for combo, key in ((self.cb_unit, "proof_unit"), (self.cb_area, "proof_area"),
                           (self.cb_px, "proof_px")):
            v = s.value(key)
            if v is not None:
                i = combo.findData(type(combo.itemData(0))(v))
                if i >= 0:
                    combo.setCurrentIndex(i)
        self.ed_title.setText(str(s.value("proof_title", "NOTE:-")))
        note = s.value("proof_note")
        if note is not None:
            self.ed_note.setPlainText(str(note))
        self.ed_wm.setText(str(s.value("proof_wm", "")))
        self.ed_footer.setText(str(s.value("proof_footer", "")))

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("proof_unit", self.cb_unit.currentData())
        s.setValue("proof_area", self.cb_area.currentData())
        s.setValue("proof_px", self.cb_px.currentData())
        s.setValue("proof_title", self.ed_title.text())
        s.setValue("proof_note", self.ed_note.toPlainText())
        s.setValue("proof_wm", self.ed_wm.text())
        s.setValue("proof_footer", self.ed_footer.text())

    def _on_w(self, v) -> None:
        if self.chk_lock.isChecked():
            self.sp_h.blockSignals(True)
            self.sp_h.setValue(round(v * self.ratio, 2))
            self.sp_h.blockSignals(False)
        self._changed()

    def _on_h(self, v) -> None:
        if self.chk_lock.isChecked():
            self.sp_w.blockSignals(True)
            self.sp_w.setValue(round(v / self.ratio, 2))
            self.sp_w.blockSignals(False)
        self._changed()

    def _changed(self, *_):
        self.timer.start()

    def _on_preview_click(self, x: float, y: float) -> None:
        if not self.rendered:
            return
        ox, oy, dw, dh = self.rendered.info.get("design_box", (0, 0, 1, 1))
        u, v = (x - ox) / dw, (y - oy) / dh
        if 0 <= u <= 1 and 0 <= v <= 1:
            self.ps.closeup_center = (u, v)
            if not self.chk_close.isChecked():
                self.chk_close.setChecked(True)   # triggers a render
            else:
                self.render()

    def current_settings(self) -> proof.ProofSettings:
        lines = [ln for ln in self.ed_note.toPlainText().splitlines() if ln.strip()]
        return replace(
            self.ps, width_in=self.sp_w.value(), height_in=self.sp_h.value(),
            unit=self.cb_unit.currentData(), show_area=self.chk_area.isChecked(),
            area_unit=self.cb_area.currentData(), note_title=self.ed_title.text(),
            note_lines=lines, fill=self.cb_fit.currentData(), closeup=self.chk_close.isChecked(),
            closeup_fraction=self.cb_cz.currentData(), watermark=self.ed_wm.text(),
            footer=self.ed_footer.text(), width_px=self.cb_px.currentData())

    def render(self) -> None:
        ps = self.current_settings()
        try:
            self.rendered = proof.render_proof(self.image, ps)
        except Exception as exc:
            self.info.setText(f"Could not render: {exc}")
            return
        self.view.set_image(pil_to_qimage(self.rendered), keep_view=True)
        area = proof.area_label(ps.width_in, ps.height_in, ps.area_unit)
        self.area_big.setText(f"{proof.size_label(ps.width_in, ps.height_in, ps.unit)}  =  {area}")
        ppi = self.full_px[0] / ps.width_in
        if ppi >= 150:
            q = f"<span style='color:#15803d'>Excellent for print ({ppi:.0f} pixels per inch).</span>"
        elif ppi >= 72:
            q = f"<span style='color:#15803d'>Good for wall prints ({ppi:.0f} pixels per inch).</span>"
        else:
            need = 100 / ppi
            q = (f"<span style='color:#b45309'>Low resolution: {ppi:.0f} pixels per inch at this size. "
                 f"Use Upscale ×{min(8, max(2, round(need + 0.49)))} on the Resize tab first.</span>")
        self.res_info.setText(f"Design: {self.full_px[0]} × {self.full_px[1]} px<br>{q}")
        self.info.setText(f"Proof image: {self.rendered.width} × {self.rendered.height} px. "
                          "Mouse wheel to zoom.")

    # ------------------------------------------------------------------
    def _encode(self, fmt: str) -> bytes:
        return im.encode(self.rendered, im.OutputSettings(fmt=fmt, quality=92, dpi=150))

    def save(self) -> None:
        if not self.rendered:
            return
        self._save_settings()
        ps = self.current_settings()
        start = self.settings.value("last_save_dir", str(Path.home() / "Pictures"))
        name = proof.proof_filename(self.src_name, ps, ".jpg")
        path, flt = QFileDialog.getSaveFileName(
            self, "Save proof", str(Path(str(start)) / name),
            "JPG image (*.jpg);;PNG image (*.png);;PDF document (*.pdf)")
        if not path:
            return
        p = Path(path)
        fmt = {".png": "PNG", ".pdf": "PDF"}.get(p.suffix.lower())
        if fmt is None:
            fmt = "PNG" if "PNG" in flt else "PDF" if "PDF" in flt else "JPG"
            p = p.with_suffix(im.FORMATS[fmt]["ext"])
        from app.ui.errors import save_or_warn, write_bytes_safely
        if not save_or_warn(self, lambda: write_bytes_safely(p, self._encode(fmt)), p):
            return
        self.settings.setValue("last_save_dir", str(p.parent))
        self.info.setText(f"Saved {p.name}")
        share.show_in_folder(p)

    def _temp_file(self, folder: Path) -> Path:
        ps = self.current_settings()
        p = im.unique_path(folder / proof.proof_filename(self.src_name, ps, ".jpg"))
        p.write_bytes(self._encode("JPG"))
        return p

    def copy(self) -> None:
        if not self.rendered:
            return
        f = self._temp_file(share.temp_folder())
        share.copy_to_clipboard(pil_to_qimage(self.rendered), f)
        self.info.setText("Proof copied – press Ctrl+V in WhatsApp, email or any app.")

    def whatsapp(self) -> None:
        if not self.rendered:
            return
        self._save_settings()
        f = self._temp_file(share.share_folder())
        share.copy_to_clipboard(pil_to_qimage(self.rendered), f)
        share.open_whatsapp(self.wa_target, self.wa_phone)
        self.info.setText(f"Proof copied and WhatsApp opened – press Ctrl+V in the chat. File: {f.name}")

    def accept(self) -> None:
        self._save_settings()
        super().accept()
