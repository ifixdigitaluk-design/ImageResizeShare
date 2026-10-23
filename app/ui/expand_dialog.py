"""Expand Design: add picture at the sides (or top/bottom) so it fits the wall without cropping."""
from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from app.core import expand as ex
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon, pil_to_qimage
from app.ui.views import ZoomView
from app.ui.worker import run_bg

PREVIEW_MAX = 1400


class ExpandDialog(SheetDialog):
    def __init__(self, studio):
        super().__init__(studio.window(), "fit", "Expand Design to Fit the Wall",
                         "Add new picture at the sides or top so the whole design fits the wall – nothing is cut off.",
                         size=(1440, 900))
        self.studio = studio
        j = studio.job
        self.design = studio.design_img
        self.aspect = j.art_width / j.art_height
        self.result_img: Optional[Image.Image] = None
        self.ai_img: Optional[Image.Image] = None
        self._busy = False
        small = self.design.convert("RGB").copy()
        small.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.Resampling.LANCZOS)
        self.small = small
        self.k = small.width / self.design.width

        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        self.view = ZoomView("", bg="#eef1f5")
        left.addWidget(self.view, 1)
        self.lbl_info = hint("")
        self.lbl_info.setWordWrap(True)
        left.addWidget(self.lbl_info)
        row.addLayout(left, 1)

        side = QVBoxLayout()
        side.setSpacing(10)
        box = QFrame()
        box.setObjectName("InfoBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 10, 14, 10)
        self.lbl_fit = QLabel("")
        self.lbl_fit.setWordWrap(True)
        self.lbl_fit.setTextFormat(Qt.TextFormat.RichText)
        bl.addWidget(self.lbl_fit)
        side.addWidget(box)
        t = QLabel("Where to add")
        t.setObjectName("PaneTitle")
        side.addWidget(t)
        self.cb_where = QComboBox()
        wider = self.aspect > self.design.width / self.design.height
        opts = ([("Both sides equally", "even"), ("Only on the left", "left"), ("Only on the right", "right")]
                if wider else [("Top and bottom equally", "even"), ("Only at the top", "top"),
                               ("Only at the bottom", "bottom")])
        for txt, v in opts:
            self.cb_where.addItem(txt, v)
        if not wider:
            self.cb_where.setCurrentIndex(1)          # usually sky above, floor stays where it is
        self.cb_where.currentIndexChanged.connect(lambda _i: self._changed())
        side.addWidget(self.cb_where)
        t2 = QLabel("How")
        t2.setObjectName("PaneTitle")
        side.addWidget(t2)
        self.method_group = QButtonGroup(self)
        tips = {"mirror": "Good for landscapes, plants and abstract designs",
                "stretch": "Good for skies, sea and plain backgrounds",
                "blur": "Soft blurred edges – the quickest, safe for any picture",
                "ai": "Draws new matching picture (uses your Replicate account, a few cents)"}
        for i, (k, name) in enumerate(ex.METHODS.items()):
            rb = QRadioButton(name)
            rb.setProperty("method", k)
            self.method_group.addButton(rb, i)
            side.addWidget(rb)
            h = hint(tips[k])
            h.setContentsMargins(26, 0, 0, 0)
            side.addWidget(h)
            if k == "mirror":
                rb.setChecked(True)
        self.method_group.idClicked.connect(lambda _i: self._changed())
        self.ai_box = QWidget()
        al = QVBoxLayout(self.ai_box)
        al.setContentsMargins(26, 0, 0, 0)
        self.ed_prompt = QLineEdit()
        self.ed_prompt.setPlaceholderText("Optional: describe what to add, e.g. ‘more pine forest and lake’")
        al.addWidget(self.ed_prompt)
        self.b_ai = QPushButton(icon("sparkle", "#ffffff"), "  Make it with AI")
        self.b_ai.setObjectName("AIButton")
        self.b_ai.clicked.connect(self.run_ai)
        al.addWidget(self.b_ai)
        side.addWidget(self.ai_box)
        side.addStretch()
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(380)
        row.addWidget(sw)
        self.body.addLayout(row, 1)

        bot = QHBoxLayout()
        self.lbl_status = hint("")
        bot.addWidget(self.lbl_status, 1)
        self.b_use = QPushButton(icon("check", "#ffffff"), "  Use Expanded Design")
        self.b_use.setObjectName("Go")
        self.b_use.clicked.connect(self.use)
        bot.addWidget(self.b_use)
        b_c = QPushButton("Cancel")
        b_c.setObjectName("Light")
        b_c.clicked.connect(self.reject)
        bot.addWidget(b_c)
        self.body.addLayout(bot)
        self._changed()

    # ------------------------------------------------------------------
    def method(self) -> str:
        b = self.method_group.checkedButton()
        return b.property("method") if b else "mirror"

    def plan(self, size=None) -> ex.ExpandPlan:
        return ex.plan(size or self.design.size, self.aspect, self.cb_where.currentData())

    def _changed(self) -> None:
        m = self.method()
        self.ai_box.setVisible(m == "ai")
        pl = self.plan()
        j = self.studio.job
        ppm = pl.out_size[0] / j.art_width
        crop = ex.crop_fraction(self.design.size, self.aspect)
        self.lbl_fit.setText(
            f"Design {self.design.width} × {self.design.height} px · wall + bleed "
            f"{j.art_width:.2f} × {j.art_height:.2f} m<br>"
            + (f"<b>‘Fill the wall’ would cut off {crop * 100:.0f}%</b> of the design.<br>Expanding adds "
               f"{pl.describe(ppm)}." if not pl.empty else "<b>The design already has the wall's shape.</b>"))
        self.b_use.setEnabled(not pl.empty and (m != "ai" or self.ai_img is not None))
        if m == "ai":
            if self.ai_img is not None:
                self._show(self.ai_img)
            else:
                self._show(ex.expand_offline(self.small, self.plan(self.small.size), "mirror"), ghost=True)
                self.lbl_info.setText("Preview of the area the AI will fill. Press ‘Make it with AI’.")
            return
        self._show(ex.expand_offline(self.small, self.plan(self.small.size), m))

    def _show(self, img: Image.Image, ghost: bool = False) -> None:
        ps = self.plan(self.small.size)
        pl = ps if img.size == ps.out_size else self.plan()
        k = img.width / pl.out_size[0]
        vis = img.convert("RGB").copy()
        d = ImageDraw.Draw(vis, "RGBA")
        x0, y0 = pl.left * k, pl.top * k
        x1, y1 = x0 + pl.size[0] * k, y0 + pl.size[1] * k
        if ghost:
            for r in ((0, 0, vis.width, y0), (0, y1, vis.width, vis.height), (0, y0, x0, y1), (x1, y0, vis.width, y1)):
                if r[2] > r[0] and r[3] > r[1]:
                    d.rectangle(r, fill=(109, 74, 255, 90))
        d.rectangle([x0, y0, x1, y1], outline=(255, 255, 255, 230), width=max(2, vis.width // 400))
        self.view.set_image(pil_to_qimage(vis), keep_view=False)
        if not ghost:
            self.lbl_info.setText("White frame = the original design (unchanged). Everything outside it is new.")

    # ------------------------------------------------------------------
    def run_ai(self) -> None:
        if self._busy:
            return
        token = str(QSettings("ImageResizeShare", "ImageResizeShare").value("replicate_token", "") or "")
        if not token:
            QMessageBox.information(self, "AI expand", "Add your Replicate API token first: Jobs → Online "
                                                       "Upscaling. It is the same account used for online upscaling.")
            return
        self._busy = True
        self.b_ai.setEnabled(False)
        img, pl, prompt = self.design, self.plan(), self.ed_prompt.text().strip()

        def job(progress):
            return ex.expand_ai(img, pl, token, prompt, progress=lambda m: progress(0, m))

        def done(res):
            self._busy = False
            self.b_ai.setEnabled(True)
            self.ai_img = res
            self.lbl_status.setText("AI expansion ready – check the edges, then use it.")
            self._changed()

        def failed(msg):
            self._busy = False
            self.b_ai.setEnabled(True)
            self.lbl_status.setText("")
            QMessageBox.warning(self, "AI expand", msg)

        run_bg(job, done, failed, lambda _f, t: self.lbl_status.setText(t))

    def use(self) -> None:
        m = self.method()
        if m == "ai":
            if self.ai_img is None:
                return
            self.result_img = self.ai_img
            self.accept()
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self.result_img = ex.expand_offline(self.design, self.plan(), m)
        finally:
            self.unsetCursor()
        self.accept()
