"""Customer Proof: the proof sheet, approval record and a test strip."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from app.core import documents as docs
from app.core import jobs
from app.core import mockup as mk
from app.core import production as pr
from app.core import wall as wl
from app.ui import share
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import FreeAfterExec
from app.ui.qtutil import hint, icon, pil_to_qimage
from app.ui.views import ZoomView
from app.ui.worker import run_bg

UNITS = [("m", "m"), ("cm", "cm"), ("feet + inches", "ftin"), ("inches", "in")]


class ApprovalDialog(FreeAfterExec, QDialog):
    def __init__(self, parent, job: wl.Job):
        super().__init__(parent)
        self.setWindowTitle("Record the customer's approval")
        lay = QVBoxLayout(self)
        lay.addWidget(hint(f"Proof v{job.proof_version or 1} for {job.customer or 'the customer'}. "
                           "Keep a record before printing."))
        f = QFormLayout()
        self.ed_name = QLineEdit(job.approved_by or job.customer)
        f.addRow("Approved by", self.ed_name)
        self.ed_date = QDateEdit(QDate.currentDate())
        self.ed_date.setCalendarPopup(True)
        self.ed_date.setDisplayFormat("dd MMM yyyy")
        f.addRow("Date", self.ed_date)
        self.cb_how = QComboBox()
        for h in ("WhatsApp message", "Signed proof", "Email", "In person", "Phone call"):
            self.cb_how.addItem(h)
        f.addRow("How", self.cb_how)
        self.ed_note = QLineEdit()
        self.ed_note.setPlaceholderText("Optional – e.g. ‘OK but make it 5 cm lower’")
        f.addRow("Note", self.ed_note)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class ProofDialog(SheetDialog):
    def __init__(self, studio):
        super().__init__(studio.window(), "doc", "Customer Proof",
                         "The design on the wall with sizes, a room preview, the colour note and an approval box.",
                         size=(1500, 960))
        self.studio = studio
        self.job = studio.job
        self.page: Optional[Image.Image] = None
        self._gen = 0
        self.t = QTimer(self, singleShot=True, interval=200, timeout=self._render)

        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        self.view = ZoomView("Making the proof…", bg="#eef1f5")
        left.addWidget(self.view, 1)
        self.lbl_info = hint("")
        left.addWidget(self.lbl_info)
        row.addLayout(left, 1)

        side = QVBoxLayout()
        side.setSpacing(10)
        st = QLabel("Status")
        st.setObjectName("PaneTitle")
        side.addWidget(st)
        self.lbl_status = QLabel("")
        self.lbl_status.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_status.setWordWrap(True)
        side.addWidget(self.lbl_status)
        frm = QFormLayout()
        frm.setHorizontalSpacing(10)
        frm.setVerticalSpacing(8)
        self.sp_ver = QSpinBox()
        self.sp_ver.setRange(1, 99)
        self.sp_ver.setValue((self.job.proof_version or 0) + 1)
        self.sp_ver.setPrefix("v")
        self.sp_ver.valueChanged.connect(lambda _v: self.t.start())
        frm.addRow("Proof version", self.sp_ver)
        self.cb_room = QComboBox()
        self.cb_room.addItem("No room preview", "")
        for k, v in mk.SCENES.items():
            self.cb_room.addItem(v, k)
        w0 = self.job.walls[0]
        if w0.photo and studio.job_dir and (studio.job_dir / w0.photo).is_file() and len(w0.corners) == 4:
            self.cb_room.addItem("Customer's wall photo", "photo")
        sc = studio.cb_scene.currentData() or "living"
        self.cb_room.setCurrentIndex(max(0, self.cb_room.findData(sc)))
        self.cb_room.currentIndexChanged.connect(lambda _i: self.t.start())
        frm.addRow("Room preview", self.cb_room)
        self.cb_unit = QComboBox()
        for t, v in UNITS:
            self.cb_unit.addItem(t, v)
        self.cb_unit.setCurrentIndex(max(0, self.cb_unit.findData(self.job.unit)))
        self.cb_unit.currentIndexChanged.connect(lambda _i: self.t.start())
        frm.addRow("Sizes in", self.cb_unit)
        side.addLayout(frm)
        self.chk_seams = QCheckBox("Show panel joins (seams)")
        self.chk_seams.toggled.connect(lambda _v: self.t.start())
        side.addWidget(self.chk_seams)
        self.chk_wm = QCheckBox("Watermark ‘PROOF – NOT FOR PRINT’")
        self.chk_wm.setChecked(True)
        self.chk_wm.toggled.connect(lambda _v: self.t.start())
        side.addWidget(self.chk_wm)
        side.addWidget(QLabel("Notes for the customer"))
        self.ed_notes = QPlainTextEdit(self.job.notes)
        self.ed_notes.setPlaceholderText("e.g. Horizon kept at sofa height. Window area left unprinted.")
        self.ed_notes.setMaximumHeight(110)
        self.ed_notes.textChanged.connect(lambda: self.t.start())
        side.addWidget(self.ed_notes)
        side.addSpacing(6)
        b_app = QPushButton(icon("check"), "  Record Approval…")
        b_app.setMinimumHeight(40)
        b_app.clicked.connect(self.record_approval)
        side.addWidget(b_app)
        b_strip = QPushButton(icon("printer"), "  Test Strip (print a sample)…")
        b_strip.setMinimumHeight(40)
        b_strip.setToolTip("A4 piece of the design at 100 % scale with colour patches – print it before the job")
        b_strip.clicked.connect(self.test_strip)
        side.addWidget(b_strip)
        side.addStretch()
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(360)
        row.addWidget(sw)
        self.body.addLayout(row, 1)

        bot = QHBoxLayout()
        bot.setSpacing(12)
        bot.addStretch()
        b_wa = QPushButton(icon("whatsapp", "#1f9d55"), "  Save && Send on WhatsApp")
        b_wa.setObjectName("Light")
        b_wa.clicked.connect(lambda: self.save(whatsapp=True))
        bot.addWidget(b_wa)
        b_save = QPushButton(icon("download", "#ffffff"), "  Save Proof (PDF + JPG)")
        b_save.setObjectName("Dark")
        b_save.clicked.connect(lambda: self.save(whatsapp=False))
        bot.addWidget(b_save)
        b_close = QPushButton("Close")
        b_close.setObjectName("Light")
        b_close.clicked.connect(self.accept)
        bot.addWidget(b_close)
        self.body.addLayout(bot)
        self._update_status()
        QTimer.singleShot(0, self._render)

    # ------------------------------------------------------------------
    def _update_status(self) -> None:
        j = self.job
        c = wl.STATUS_COLOURS.get(j.status, "#64748b")
        txt = f"<span style='color:{c};font-weight:700'>● {j.status}</span>"
        if j.proof_version:
            txt += f" &nbsp;·&nbsp; last proof v{j.proof_version}"
        if j.approved_by:
            txt += f"<br>Approved by <b>{j.approved_by}</b> {j.approved_on}"
        self.lbl_status.setText(txt)

    def _make(self, prm: dict) -> Image.Image:
        st, j = self.studio, self.job
        mock = None
        if prm["room"]:
            mock = st.room_image(max_w=1300, fast=False, scene=prm["room"])
        return docs.proof_sheet(j, st.source, jobs.load_business(), mockup=mock, version=prm["version"],
                                show_seams=prm["seams"], watermark=prm["wm"], notes=prm["notes"], unit=prm["unit"],
                                ppi=float(getattr(st.source, "ppi", 0.0)))

    def _params(self) -> dict:
        return {"room": self.cb_room.currentData(), "version": self.sp_ver.value(),
                "seams": self.chk_seams.isChecked(), "wm": self.chk_wm.isChecked(),
                "notes": self.ed_notes.toPlainText().strip(), "unit": self.cb_unit.currentData()}

    def _render(self) -> None:
        self._gen += 1
        gen = self._gen
        prm = self._params()
        self.lbl_info.setText("Making the proof…")
        # the room picture uses Qt-free code only, but the studio's helper reads a combo: pass the scene in prm
        def job(_p):
            return self._make(prm)

        def done(page):
            if gen != self._gen:
                return
            self.page = page
            self.view.set_image(pil_to_qimage(page), keep_view=self.view.has_image())
            self.lbl_info.setText(f"A3 landscape · proof v{prm['version']} · "
                                  f"{'with' if prm['wm'] else 'without'} watermark")

        run_bg(job, done, lambda m: self.lbl_info.setText(f"Could not make the proof: {m}"))

    # ------------------------------------------------------------------
    def save(self, whatsapp: bool = False) -> None:
        if self.page is None:
            return
        st, j = self.studio, self.job
        d = st.ensure_dir() / "proofs"
        d.mkdir(exist_ok=True)
        v = self.sp_ver.value()
        base = d / f"{pr.safe_name(j.job_no)}_proof_v{v}"
        pdf, jpg = base.with_suffix(".pdf"), base.with_suffix(".jpg")
        if pdf.exists() and not whatsapp:
            if QMessageBox.question(self, "Proof", f"Proof v{v} already exists. Replace it?") != \
                    QMessageBox.StandardButton.Yes:
                return
        self.page.save(pdf, "PDF", resolution=150.0)
        jp = self.page.copy()
        jp.thumbnail((2200, 2200))
        jp.save(jpg, "JPEG", quality=88)
        j.proof_version = v
        j.proof_file = f"proofs/{pdf.name}"
        j.notes = self.ed_notes.toPlainText().strip()
        j.log(f"Proof v{v} saved")
        if j.status in ("Enquiry", "Measured", "Designing"):
            j.set_status("Proof sent")
        from app.ui.errors import save_or_warn
        save_or_warn(self, lambda: jobs.save_job(j), j.job_no)
        self._update_status()
        self.sp_ver.blockSignals(True)
        self.sp_ver.setValue(v)
        self.sp_ver.blockSignals(False)
        if whatsapp:
            share.copy_to_clipboard(pil_to_qimage(jp.convert("RGB")), jpg)
            share.open_whatsapp(st.main.wa_target, j.phone or st.main.wa_phone)
            QMessageBox.information(self, "WhatsApp", f"{jpg.name} is copied. Press Ctrl+V in the chat"
                                    + (f" with {j.customer}" if j.customer else "")
                                    + ", then Send.\n\nThe PDF is in the job's proofs folder.")
        else:
            share.show_in_folder(pdf)

    def record_approval(self) -> None:
        j = self.job
        dlg = ApprovalDialog(self, j)
        if not dlg.exec():
            return
        j.approved_by = dlg.ed_name.text().strip() or j.customer or "customer"
        j.approved_on = dlg.ed_date.date().toString("dd MMM yyyy") + f" ({dlg.cb_how.currentText().lower()})"
        note = dlg.ed_note.text().strip()
        j.log(f"Proof v{j.proof_version or self.sp_ver.value()} approved by {j.approved_by} – "
              f"{dlg.cb_how.currentText()}" + (f": {note}" if note else ""))
        if j.status not in ("Printing", "Printed", "Installed", "Completed"):
            j.set_status("Approved")
        if self.studio.job_dir:
            from app.ui.errors import save_or_warn
            save_or_warn(self, lambda: jobs.save_job(j), j.job_no)
        self._update_status()

    def test_strip(self) -> None:
        st, j = self.studio, self.job
        dlg = QDialog(self)
        dlg.setWindowTitle("Test strip")
        lay = QVBoxLayout(dlg)
        lay.addWidget(hint("A piece of the design at 100 % scale with colour patches. Print it on the real material "
                           "and compare with the screen before printing the whole job."))
        f = QFormLayout()
        cb_size = QComboBox()
        for t, s_ in (("A4 landscape (29.7 × 21 cm)", (0.297, 0.21)), ("A3 landscape (42 × 29.7 cm)", (0.42, 0.297)),
                      ("Full media width × 30 cm", (j.panels.media_width, 0.30))):
            cb_size.addItem(t, s_)
        f.addRow("Size", cb_size)
        cb_where = QComboBox()
        for t, c in (("Centre of the design", (0.5, 0.5)), ("Top left", (0.2, 0.2)), ("Top right", (0.8, 0.2)),
                     ("Bottom left", (0.2, 0.8)), ("Bottom right", (0.8, 0.8)), ("Brightest colours", None)):
            cb_where.addItem(t, c)
        f.addRow("Which part", cb_where)
        sp_dpi = QSpinBox()
        sp_dpi.setRange(50, 600)
        sp_dpi.setValue(j.print_dpi)
        sp_dpi.setSuffix(" dpi")
        f.addRow("Resolution", sp_dpi)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if not dlg.exec():
            return
        where = cb_where.currentData()
        if where is None:
            where = self._most_saturated()
        centre = (where[0] * j.art_width, where[1] * j.art_height)
        from app.ui.worker import BackgroundError, run_with_progress
        src, size_m, dpi_ = st.source, cb_size.currentData(), sp_dpi.value()
        try:
            img = run_with_progress(self, "Making the test strip…",
                                    lambda: docs.test_strip(src, j, centre, size_m, dpi_))
        except BackgroundError as exc:
            QMessageBox.warning(self, "Test strip", f"The test strip could not be made.\n\n{exc}")
            return
        want_w = cb_size.currentData()[0] * sp_dpi.value() / 0.0254
        if img.width < want_w - 2:
            QMessageBox.information(self, "Test strip",
                                    f"At {sp_dpi.value()} dpi the strip is limited to "
                                    f"{img.width / sp_dpi.value() * 2.54:.0f} cm wide so it fits in memory. "
                                    "It is still at 100 % scale.")
        d = st.ensure_dir() / "print"
        d.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save test strip",
                                              str(d / f"{pr.safe_name(j.job_no)}_test_strip.pdf"),
                                              "PDF (*.pdf);;TIFF (*.tif)")
        if not path:
            return
        dpi = sp_dpi.value()
        from app.ui.errors import save_or_warn
        if path.lower().endswith((".tif", ".tiff")):
            ok = save_or_warn(self, lambda: img.save(path, "TIFF", compression="tiff_lzw", dpi=(dpi, dpi)), path)
        else:
            ok = save_or_warn(self, lambda: img.save(path, "PDF", resolution=float(dpi)), path)
        if not ok:
            return
        j.log("Test strip saved")
        share.show_in_folder(Path(path))

    def _most_saturated(self):
        """Where the strongest colours are (they show printer differences best)."""
        import numpy as np
        st, j = self.studio, self.job
        small = pr.render_area(st.source, j, 0, 0, j.art_width, j.art_height, 60 / max(j.art_width, 0.1),
                               fast=True).convert("HSV")
        s = np.asarray(small)[:, :, 1].astype(float)
        if s.size == 0:
            return (0.5, 0.5)
        k = max(3, min(s.shape) // 4)
        from PIL import ImageFilter
        blur = np.asarray(Image.fromarray(s.astype("uint8")).filter(ImageFilter.BoxBlur(k)))
        y, x = np.unravel_index(int(np.argmax(blur)), blur.shape)
        return (min(0.9, max(0.1, x / blur.shape[1])), min(0.9, max(0.1, y / blur.shape[0])))
