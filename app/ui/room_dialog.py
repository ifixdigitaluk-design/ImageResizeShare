"""Room Mockup: the design in a room (true scale) or on the customer's own photo."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget)

from app.core import jobs
from app.core import mockup as mk
from app.core import production as pr
from app.ui import share
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon, pil_to_qimage
from app.ui.views import ZoomView
from app.ui.worker import run_bg

SCENE_ICONS = {"living": "sofa", "bedroom": "layers", "office": "briefcase", "cafe": "grid", "empty": "wall",
               "photo": "camera"}


class RoomDialog(SheetDialog):
    def __init__(self, studio):
        super().__init__(studio.window(), "sofa", "Room Mockup",
                         "See the design on the wall at true scale – in a room or on the customer's own photo.",
                         size=(1500, 940))
        self.studio = studio
        self.job = studio.job
        self.img: Optional[Image.Image] = None
        self._gen = 0
        self.t = QTimer(self, singleShot=True, interval=120, timeout=self._render)
        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        self.view = ZoomView("Rendering…", bg="#eef1f5")
        left.addWidget(self.view, 1)
        self.lbl_info = hint("")
        left.addWidget(self.lbl_info)
        row.addLayout(left, 1)

        side = QVBoxLayout()
        side.setSpacing(10)
        t = QLabel("Room")
        t.setObjectName("PaneTitle")
        side.addWidget(t)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.scene_group = QButtonGroup(self)
        scenes = list(mk.SCENES.items()) + [("photo", "Customer's photo")]
        for i, (key, name) in enumerate(scenes):
            b = QToolButton()
            b.setObjectName("PresetTile")
            b.setCheckable(True)
            b.setIcon(icon(SCENE_ICONS.get(key, "wall"), "#334155"))
            b.setIconSize(QSize(26, 26))
            b.setText(name)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setMinimumSize(QSize(150, 70))
            b.setProperty("scene", key)
            self.scene_group.addButton(b, i)
            grid.addWidget(b, i // 2, i % 2)
        side.addLayout(grid)
        self.scene_group.idClicked.connect(lambda _i: self.t.start())
        has_photo = self._has_photo()
        cur = studio.cb_scene.currentData() or "living"
        if cur == "photo" and not has_photo:
            cur = "living"
        for b in self.scene_group.buttons():
            if b.property("scene") == "photo":
                b.setEnabled(has_photo)
                if not has_photo:
                    b.setToolTip("Use ‘Measure from photo’ first – then the design can go on the customer's own wall")
            if b.property("scene") == cur:
                b.setChecked(True)
        self.chk_items = QCheckBox("Show this wall's doors, windows and furniture")
        self.chk_items.setChecked(any(w.obstacles for w in self.job.walls))
        self.chk_items.toggled.connect(lambda _v: self.t.start())
        side.addWidget(self.chk_items)
        self.chk_corners = QCheckBox("Show corners between walls")
        self.chk_corners.setChecked(True)
        self.chk_corners.toggled.connect(lambda _v: self.t.start())
        side.addWidget(self.chk_corners)
        lt = QHBoxLayout()
        lt.addWidget(QLabel("Room light (photo)"))
        self.sl_light = QSlider(Qt.Orientation.Horizontal)
        self.sl_light.setRange(40, 100)
        self.sl_light.setValue(85)
        self.sl_light.valueChanged.connect(lambda _v: self.t.start())
        lt.addWidget(self.sl_light, 1)
        side.addLayout(lt)

        t2 = QLabel("Material & finish")
        t2.setObjectName("PaneTitle")
        side.addWidget(t2)
        mf = QHBoxLayout()
        self.cb_mat = QComboBox()
        for m in mk.MATERIALS:
            self.cb_mat.addItem(m)
        self.cb_mat.setCurrentText(self.job.material)
        self.cb_fin = QComboBox()
        for f in mk.FINISHES:
            self.cb_fin.addItem(f)
        self.cb_fin.setCurrentText(self.job.finish)
        mf.addWidget(self.cb_mat, 2)
        mf.addWidget(self.cb_fin, 1)
        side.addLayout(mf)
        self.cb_mat.currentTextChanged.connect(self._on_material)
        self.cb_fin.currentTextChanged.connect(self._on_material)
        self.swatch = QLabel()
        self.swatch.setFixedHeight(190)
        self.swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.swatch.setStyleSheet("background:#eef1f5;border-radius:8px;")
        side.addWidget(self.swatch)
        side.addWidget(hint("15 × 15 cm close-up of the design on this material (illustration)."))
        side.addStretch()
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(340)
        row.addWidget(sw)
        self.body.addLayout(row, 1)

        bot = QHBoxLayout()
        bot.setSpacing(12)
        bot.addStretch()
        b_wa = QPushButton(icon("whatsapp", "#1f9d55"), "  Copy for WhatsApp")
        b_wa.setObjectName("Light")
        b_wa.clicked.connect(self.copy_whatsapp)
        bot.addWidget(b_wa)
        b_opt = QPushButton(icon("compare"), "  Options Sheet…")
        b_opt.setObjectName("Light")
        b_opt.setToolTip("One page with the design in several rooms or colourways for the customer to choose")
        b_opt.clicked.connect(self.options_sheet)
        bot.addWidget(b_opt)
        b_save = QPushButton(icon("download", "#ffffff"), "  Save Mockup")
        b_save.setObjectName("Dark")
        b_save.clicked.connect(self.save)
        bot.addWidget(b_save)
        b_close = QPushButton("Close")
        b_close.setObjectName("Light")
        b_close.clicked.connect(self.accept)
        bot.addWidget(b_close)
        self.body.addLayout(bot)
        QTimer.singleShot(0, self._render)
        QTimer.singleShot(0, self._update_swatch)

    # ------------------------------------------------------------------
    def _has_photo(self) -> bool:
        w = self.job.walls[0]
        d = self.studio.job_dir
        return bool(w.photo and d and (d / w.photo).is_file() and len(w.corners) == 4)

    def scene(self) -> str:
        b = self.scene_group.checkedButton()
        return b.property("scene") if b else "living"

    def _params(self) -> dict:
        return {"scene": self.scene(), "finish": self.cb_fin.currentText(), "items": self.chk_items.isChecked(),
                "corners": self.chk_corners.isChecked(), "light": self.sl_light.value() / 100.0}

    def _make(self, prm: dict, max_w: int = 1800, fast: bool = False) -> Optional[Image.Image]:
        """Runs in the background: uses only `prm`, never the widgets."""
        st, j = self.studio, self.job
        scene, finish = prm["scene"], prm["finish"]
        if scene == "photo":
            if not self._has_photo() or st.source is None:
                return None
            from app.core import measure as ms
            w = j.walls[0]
            photo, _f = ms.load_photo(st.job_dir / w.photo)
            k = min(1.0, max_w * 1.2 / max(photo.size))
            if k < 1:
                photo = photo.resize((round(photo.width * k), round(photo.height * k)), Image.Resampling.LANCZOS)
            corners = [(x * k, y * k) for x, y in w.corners]
            res = ms.solve(ms.Survey(photo.size, corners, width=w.width, height=w.height))
            wall_img, _ = pr.render_wall_area(st.source, j, max_side=max(800, int(max_w * 0.9)), fast=fast)
            ww = int(round(wall_img.width * w.width / j.run_width))
            wimg = wall_img.crop((0, int(round(wall_img.height * (1 - w.height / j.run_height))), ww,
                                  wall_img.height))
            return mk.photo_mockup(photo, res.H, w.width, w.height, wimg, w.obstacles,
                                   light=prm["light"], finish=finish, outline=w.outline() if w.shaped else None)
        wall_img = None
        if st.source is not None:
            wall_img, _ = pr.render_wall_area(st.source, j, max_side=max(800, int(max_w * 0.9)), fast=fast)
        ppm = max_w / (j.run_width + 2 * max(0.8, j.run_width * 0.16))
        return mk.render_room(j.walls, wall_img, scene, ppm=ppm, use_wall_items=prm["items"],
                              finish=finish, show_corners=prm["corners"])

    def _render(self) -> None:
        self._gen += 1
        gen = self._gen
        self.lbl_info.setText("Rendering…")

        prm = self._params()

        def job(_p):
            return self._make(prm, 1800, fast=False)

        def done(img):
            if gen != self._gen:
                return
            self.img = img
            if img is None:
                self.view.set_image(None)
                self.lbl_info.setText("Choose a design first.")
                return
            self.view.set_image(pil_to_qimage(img), keep_view=self.view.has_image())
            j = self.job
            self.lbl_info.setText(f"{self.scene_group.checkedButton().text()} · wall "
                                  f"{' + '.join(f'{w.width:.2f} × {w.height:.2f} m' for w in j.walls)} · "
                                  f"{self.cb_mat.currentText()}, {self.cb_fin.currentText().lower()} · "
                                  "illustration – real colours depend on the printer and material")

        run_bg(job, done, lambda m: self.lbl_info.setText(f"Could not render: {m}"))

    def _on_material(self, _t=None) -> None:
        self.job.material = self.cb_mat.currentText()
        self.job.finish = self.cb_fin.currentText()
        self.studio._mark_dirty()
        self._update_swatch()
        self.t.start()

    def _update_swatch(self) -> None:
        st = self.studio
        if st.source is None:
            return
        try:
            j = self.job
            cx, cy = j.art_width / 2, j.art_height / 2
            crop = st.source.render(cx - 0.075, cy - 0.075, cx + 0.075, cy + 0.075, 600, 600)
            sw = mk.material_swatch(crop, self.cb_mat.currentText(), self.cb_fin.currentText(), 150, 600)
            sw.thumbnail((380, 380))
            pm = QPixmap.fromImage(pil_to_qimage(sw))
            pm.setDevicePixelRatio(2)
            self.swatch.setPixmap(pm)
        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------------
    def save(self) -> None:
        if self.img is None:
            return
        st = self.studio
        d = st.ensure_dir() / "mockups"
        d.mkdir(exist_ok=True)
        name = f"{pr.safe_name(self.job.job_no)}_{self.scene()}_mockup.jpg"
        path, _ = QFileDialog.getSaveFileName(self, "Save room mockup", str(d / name), "JPEG (*.jpg);;PNG (*.png)")
        if not path:
            return
        p = Path(path)
        from app.ui.errors import save_or_warn
        if p.suffix.lower() == ".png":
            ok = save_or_warn(self, lambda: self.img.save(p, "PNG"), p)
        else:
            ok = save_or_warn(self, lambda: self.img.convert("RGB").save(p, "JPEG", quality=92), p)
        if not ok:
            return
        try:
            self.job.mockup_file = p.relative_to(st.job_dir).as_posix()
        except ValueError:
            pass
        self.job.log(f"Room mockup saved ({self.scene()})")
        st._mark_dirty()
        share.show_in_folder(p)

    def copy_whatsapp(self) -> None:
        if self.img is None:
            return
        st = self.studio
        rel = jobs.add_file(self.job, "mockups", self.img, f"{pr.safe_name(self.job.job_no)}_{self.scene()}_mockup.jpg")
        f = st.ensure_dir() / rel
        share.copy_to_clipboard(pil_to_qimage(self.img.convert("RGB")), f)
        share.open_whatsapp(st.main.wa_target, self.job.phone or st.main.wa_phone)
        QMessageBox.information(self, "WhatsApp", "The mockup is copied. Press Ctrl+V in the chat"
                                + (f" with {self.job.customer}" if self.job.customer else "") + ", then Send.")

    def options_sheet(self) -> None:
        """Several rooms (or colourways) on one page for the customer to choose."""
        st = self.studio
        if st.source is None:
            return
        from app.core import colour as col
        from app.core import documents as docs
        from PySide6.QtWidgets import QInputDialog
        kinds = ["The design in 4 rooms", "4 colourways in this room"]
        k, ok = QInputDialog.getItem(self, "Options sheet", "Show:", kinds, 0, False)
        if not ok:
            return
        scene = self.scene() if self.scene() != "photo" else "living"
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            opts = []
            j = self.job
            ppm = 1100 / (j.run_width + 2 * max(0.8, j.run_width * 0.16))
            wall_img, _ = pr.render_wall_area(st.source, j, max_side=1000, fast=True)
            if k == kinds[0]:
                for sc in ("living", "bedroom", "office", "empty"):
                    opts.append((mk.SCENES[sc], mk.render_room(j.walls, wall_img, sc, ppm=ppm,
                                                              use_wall_items=self.chk_items.isChecked(),
                                                              finish=self.cb_fin.currentText())))
            else:
                for name in ("Original", "Warm", "Cool", "Monochrome"):
                    wimg = col.colourway(wall_img, name)
                    opts.append((name, mk.render_room(j.walls, wimg, scene, ppm=ppm,
                                                      use_wall_items=self.chk_items.isChecked(),
                                                      finish=self.cb_fin.currentText())))
            page = docs.options_sheet(j, opts, jobs.load_business())
        finally:
            self.unsetCursor()
        d = st.ensure_dir() / "proofs"
        d.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save options sheet",
                                              str(d / f"{pr.safe_name(j.job_no)}_options.pdf"),
                                              "PDF (*.pdf);;JPEG (*.jpg)")
        if not path:
            return
        p = Path(path)
        from app.ui.errors import save_or_warn

        def write():
            if p.suffix.lower() in (".jpg", ".jpeg"):
                page.save(p, "JPEG", quality=90)
            else:
                page.save(p, "PDF", resolution=150.0)
                page.save(p.with_suffix(".jpg"), "JPEG", quality=88)
        if not save_or_warn(self, write, p):
            return
        j.log("Options sheet saved")
        st._mark_dirty()
        share.show_in_folder(p)
