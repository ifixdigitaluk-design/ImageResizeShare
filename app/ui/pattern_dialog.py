"""Repeating Pattern: a tile repeated across the wall at a real repeat size."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from app.core import imaging as im
from app.core import jobs
from app.core import pattern as pt
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon, pil_to_qimage
from app.ui.views import ZoomView


def _repeat_icon(kind: str, size: int = 44) -> QPixmap:
    """Little diagram of the match type."""
    img = Image.new("RGB", (size * 2, size * 2), (255, 255, 255))
    d = ImageDraw.Draw(img)
    c = [(26, 115, 232), (109, 74, 255)]
    s = size // 2
    for i in range(-1, 5):
        for j in range(-1, 5):
            dx = s // 2 if kind == "brick" and j % 2 else 0
            dy = s // 2 if kind == "half_drop" and i % 2 else 0
            x, y = i * s + dx, j * s + dy
            fill = c[(i + j) % 2] if kind != "mirror" else c[(i % 2) ^ (j % 2)]
            d.rectangle([x + 3, y + 3, x + s - 3, y + s - 3], outline=fill, width=3)
            if kind == "mirror":
                d.line([(x + 3 + (s - 6) * (i % 2), y + 3), (x + s - 3 - (s - 6) * (i % 2), y + s - 3)],
                       fill=fill, width=3)
            else:
                d.line([(x + 3, y + 3), (x + s - 3, y + s - 3)], fill=fill, width=3)
    pm = QPixmap.fromImage(pil_to_qimage(img))
    pm.setDevicePixelRatio(2)
    return pm


class PatternDialog(SheetDialog):
    def __init__(self, studio):
        super().__init__(studio.window(), "pattern", "Repeating Pattern",
                         "Turn a tile into wallpaper: set the repeat size and match, make it seamless and check the "
                         "joins before printing.", size=(1480, 920))
        self.studio = studio
        j = studio.job
        self.result = None
        self.tile: Optional[Image.Image] = None
        self.name = "pattern"
        self.spec = pt.PatternSpec.from_dict(j.pattern) if j.design_kind == "pattern" else pt.PatternSpec()
        if j.design_kind == "pattern" and studio.tile_img is not None:
            self.tile = studio.tile_img
            self.name = Path(j.design_name or "pattern").stem
        self.t = QTimer(self, singleShot=True, interval=90, timeout=self._render)

        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        top = QHBoxLayout()
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.view_group = QButtonGroup(self)
        for i, t in enumerate(("On the wall", "Check the joins (3 × 3)")):
            b = QPushButton(t)
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setMinimumWidth(170)
            b.setStyleSheet("border-top-left-radius:8px;border-bottom-left-radius:8px;" if i == 0 else
                            "border-top-right-radius:8px;border-bottom-right-radius:8px;")
            self.view_group.addButton(b, i)
            seg.addWidget(b)
        self.view_group.button(0).setChecked(True)
        self.view_group.idClicked.connect(lambda _i: self.t.start())
        top.addLayout(seg)
        top.addStretch()
        self.chk_grid = QCheckBox("Show repeat lines")
        self.chk_grid.toggled.connect(lambda _v: self.t.start())
        top.addWidget(self.chk_grid)
        left.addLayout(top)
        self.view = ZoomView("Choose a tile to start", bg="#eef1f5")
        left.addWidget(self.view, 1)
        self.lbl_info = hint("")
        left.addWidget(self.lbl_info)
        row.addLayout(left, 1)

        side = QVBoxLayout()
        side.setSpacing(10)
        t1 = QLabel("Tile")
        t1.setObjectName("PaneTitle")
        side.addWidget(t1)
        tr = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(110, 110)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background:#eef1f5;border-radius:8px;")
        tr.addWidget(self.thumb)
        tb = QVBoxLayout()
        b1 = QPushButton(icon("folder_fill", "#1e293b"), " Choose tile…")
        b1.clicked.connect(self.choose_tile)
        tb.addWidget(b1)
        b2 = QPushButton(icon("image"), " Use the current design")
        b2.setEnabled(studio.design_img is not None)
        b2.clicked.connect(self.from_design)
        tb.addWidget(b2)
        b3 = QPushButton(icon("books"), " From the library")
        b3.clicked.connect(self.from_library)
        tb.addWidget(b3)
        tr.addLayout(tb, 1)
        side.addLayout(tr)
        self.lbl_tile = hint("")
        side.addWidget(self.lbl_tile)

        t2 = QLabel("Repeat")
        t2.setObjectName("PaneTitle")
        side.addWidget(t2)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Repeat width"), 0, 0)
        self.sp_w = QDoubleSpinBox()
        self.sp_w.setRange(2, 500)
        self.sp_w.setDecimals(1)
        self.sp_w.setSuffix(" cm")
        self.sp_w.setKeyboardTracking(False)
        self.sp_w.setValue(self.spec.repeat_w * 100)
        self.sp_w.valueChanged.connect(self._on_spec)
        g.addWidget(self.sp_w, 0, 1)
        self.lbl_h = hint("")
        g.addWidget(self.lbl_h, 1, 1)
        quick = QHBoxLayout()
        for cm in (26.5, 53, 64, 70, 100):
            b = QPushButton(f"{cm:g}")
            b.setObjectName("Chip")
            b.setToolTip(f"{cm:g} cm repeat")
            b.clicked.connect(lambda _c=False, v=cm: self.sp_w.setValue(v))
            quick.addWidget(b)
        g.addLayout(quick, 2, 0, 1, 2)
        side.addLayout(g)
        gm = QGridLayout()
        gm.setSpacing(8)
        self.match_group = QButtonGroup(self)
        for i, (k, name) in enumerate(pt.REPEATS.items()):
            b = QPushButton(name)
            b.setObjectName("PresetTile")
            b.setCheckable(True)
            b.setIcon(_repeat_icon(k))
            b.setIconSize(QSize(44, 44))
            b.setMinimumHeight(58)
            b.setProperty("key", k)
            self.match_group.addButton(b, i)
            gm.addWidget(b, i // 2, i % 2)
            if k == self.spec.repeat_type:
                b.setChecked(True)
        self.match_group.idClicked.connect(lambda _i: self._on_spec())
        side.addLayout(gm)
        self.chk_seam = QCheckBox("Make seamless (hide the tile edges)")
        self.chk_seam.setChecked(self.spec.seamless)
        self.chk_seam.toggled.connect(self._on_spec)
        side.addWidget(self.chk_seam)
        br = QHBoxLayout()
        br.addWidget(QLabel("Blend"))
        self.sl_blend = QSlider(Qt.Orientation.Horizontal)
        self.sl_blend.setRange(5, 50)
        self.sl_blend.setValue(int(self.spec.blend * 100))
        self.sl_blend.valueChanged.connect(self._on_spec)
        br.addWidget(self.sl_blend, 1)
        side.addLayout(br)
        t3 = QLabel("Position on the wall")
        t3.setObjectName("PaneTitle")
        side.addWidget(t3)
        og = QGridLayout()
        og.addWidget(QLabel("Shift across"), 0, 0)
        self.sp_ox = QSpinBox()
        self.sp_ox.setRange(-250, 250)
        self.sp_ox.setSuffix(" cm")
        self.sp_ox.setValue(int(round(self.spec.offset_x * 100)))
        self.sp_ox.valueChanged.connect(self._on_spec)
        og.addWidget(self.sp_ox, 0, 1)
        og.addWidget(QLabel("Shift down"), 1, 0)
        self.sp_oy = QSpinBox()
        self.sp_oy.setRange(-250, 250)
        self.sp_oy.setSuffix(" cm")
        self.sp_oy.setValue(int(round(self.spec.offset_y * 100)))
        self.sp_oy.valueChanged.connect(self._on_spec)
        og.addWidget(self.sp_oy, 1, 1)
        b_c = QPushButton("Centre a repeat on the wall")
        b_c.clicked.connect(self.centre)
        og.addWidget(b_c, 2, 0, 1, 2)
        side.addLayout(og)
        side.addStretch()
        b_rep = QPushButton(icon("download"), " Save one repeat for the printer…")
        b_rep.setToolTip("For print shops that step-and-repeat in their RIP")
        b_rep.clicked.connect(self.save_repeat)
        side.addWidget(b_rep)
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(360)
        row.addWidget(sw)
        self.body.addLayout(row, 1)

        bot = QHBoxLayout()
        bot.addStretch()
        self.b_use = QPushButton(icon("check", "#ffffff"), "  Use This Pattern")
        self.b_use.setObjectName("Go")
        self.b_use.clicked.connect(self.use)
        bot.addWidget(self.b_use)
        b_close = QPushButton("Cancel")
        b_close.setObjectName("Light")
        b_close.clicked.connect(self.reject)
        bot.addWidget(b_close)
        self.body.addLayout(bot)
        self._tile_changed()

    # ------------------------------------------------------------------
    def _read_spec(self) -> pt.PatternSpec:
        b = self.match_group.checkedButton()
        return pt.PatternSpec(tile=self.spec.tile, repeat_w=self.sp_w.value() / 100.0,
                              repeat_type=b.property("key") if b else "straight", seamless=self.chk_seam.isChecked(),
                              blend=self.sl_blend.value() / 100.0, offset_x=self.sp_ox.value() / 100.0,
                              offset_y=self.sp_oy.value() / 100.0)

    def _on_spec(self, *_a) -> None:
        self.spec = self._read_spec()
        self.sl_blend.setEnabled(self.spec.seamless)
        self._update_info()
        self.t.start()

    def _tile_changed(self) -> None:
        has = self.tile is not None
        self.b_use.setEnabled(has)
        if has:
            from app.ui.qtutil import small_rgb
            t = small_rgb(self.tile, (220, 220))
            pm = QPixmap.fromImage(pil_to_qimage(t))
            pm.setDevicePixelRatio(2)
            self.thumb.setPixmap(pm)
            self.lbl_tile.setText(f"{self.name} · {self.tile.width} × {self.tile.height} px")
        self._on_spec()

    def _update_info(self) -> None:
        if self.tile is None:
            self.lbl_h.setText("")
            self.lbl_info.setText("")
            return
        s = self.spec
        rh = s.repeat_w * self.tile.height / self.tile.width
        self.lbl_h.setText(f"Height {rh * 100:.1f} cm (from the tile shape)")
        ppi = self.tile.width / s.repeat_w * 0.0254
        dpi = self.studio.job.print_dpi
        q = "sharp" if ppi >= dpi * 0.75 else "OK from a distance" if ppi >= dpi * 0.4 else "may look soft"
        j = self.studio.job
        self.lbl_info.setText(f"Repeat {s.repeat_w * 100:.1f} × {rh * 100:.1f} cm · {pt.REPEATS[s.repeat_type]} · "
                              f"{ppi:.0f} ppi at this size ({q}) · wall {j.run_width:.2f} × {j.run_height:.2f} m")

    def _render(self) -> None:
        if self.tile is None:
            self.view.set_image(None)
            return
        s = self.spec
        src = pt.PatternSource(self.tile, s)
        j = self.studio.job
        if self.view_group.checkedId() == 1:
            w_m, h_m = src.rw * 3, src.rh * 3
            x0, y0 = s.offset_x, s.offset_y
        else:
            w_m, h_m = j.run_width, j.run_height
            x0, y0 = 0.0, 0.0
        px = 1600
        ow, oh = px, max(1, int(px * h_m / w_m))
        if oh > 1600:
            oh, ow = 1600, max(1, int(1600 * w_m / h_m))
        img = src.render(x0, y0, x0 + w_m, y0 + h_m, ow, oh, fast=True)
        if self.chk_grid.isChecked() or self.view_group.checkedId() == 1:
            d = ImageDraw.Draw(img)
            sx, sy = ow / w_m, oh / h_m
            import math
            i0 = int(math.floor((x0 - s.offset_x) / src.rw))
            for i in range(i0, i0 + int(w_m / src.rw) + 3):
                x = (s.offset_x + i * src.rw - x0) * sx
                d.line([(x, 0), (x, oh)], fill=(26, 115, 232), width=2)
            j0 = int(math.floor((y0 - s.offset_y) / src.rh))
            for k in range(j0, j0 + int(h_m / src.rh) + 3):
                y = (s.offset_y + k * src.rh - y0) * sy
                d.line([(0, y), (ow, y)], fill=(26, 115, 232), width=2)
        self.view.set_image(pil_to_qimage(img), keep_view=False)

    # ------------------------------------------------------------------
    def _set_tile(self, img: Image.Image, name: str) -> None:
        self.tile = img
        self.name = name
        self.spec.tile = ""
        self._tile_changed()

    def choose_tile(self) -> None:
        exts = " ".join("*" + e for e in im.supported_input_extensions())
        path, _ = QFileDialog.getOpenFileName(self, "Choose a pattern tile", "", f"Images ({exts})")
        if path:
            from app.ui.wall_studio import load_design_image
            try:
                tile = load_design_image(Path(path))
            except Exception as exc:
                QMessageBox.warning(self, "Pattern tile", im.load_error_text(path, exc))
                return
            self._set_tile(tile, Path(path).stem)

    def from_design(self) -> None:
        st = self.studio
        if st.design_img is not None:
            self._set_tile(st.design_img, Path(st.job.design_name or "design").stem)

    def from_library(self) -> None:
        from app.ui.jobs_page import LibraryPicker
        from app.ui.wall_studio import load_design_image
        dlg = LibraryPicker(self)
        if dlg.exec() and dlg.chosen is not None:
            it = dlg.chosen
            self._set_tile(load_design_image(jobs.library_dir() / it.file), it.name)
            if it.repeat_cm:
                self.sp_w.setValue(it.repeat_cm)

    def centre(self) -> None:
        if self.tile is None:
            return
        s = self.spec
        j = self.studio.job
        rw = s.repeat_w * (2 if s.repeat_type == "mirror" else 1)
        off = (j.run_width / 2 + j.panels.bleed_left - rw / 2) % rw
        self.sp_ox.setValue(int(round(off * 100)))

    def save_repeat(self) -> None:
        if self.tile is None:
            return
        dpi = self.studio.job.print_dpi
        img = pt.PatternSource(self.tile, self.spec).repeat_file(dpi)
        path, _ = QFileDialog.getSaveFileName(self, "Save one repeat", f"{self.name}_repeat_{dpi}dpi.tif",
                                              "TIFF (*.tif);;PNG (*.png)")
        if not path:
            return
        from app.ui.errors import save_or_warn
        if path.lower().endswith(".png"):
            ok = save_or_warn(self, lambda: img.save(path, "PNG", dpi=(dpi, dpi)), path)
        else:
            ok = save_or_warn(self, lambda: img.save(path, "TIFF", compression="tiff_lzw", dpi=(dpi, dpi)), path)
        if not ok:
            return
        QMessageBox.information(self, "Repeat saved", f"Saved {img.width} × {img.height} px at {dpi} dpi "
                                f"({img.width / dpi * 2.54:.1f} × {img.height / dpi * 2.54:.1f} cm).")

    def use(self) -> None:
        if self.tile is None:
            return
        self.result = (self.tile, self._read_spec(), self.name)
        self.accept()
