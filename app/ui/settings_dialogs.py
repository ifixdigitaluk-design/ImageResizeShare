"""Business details, output presets and online (Replicate) upscaling settings."""
from __future__ import annotations

import traceback
from dataclasses import replace
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from app.core import cloud
from app.core import colour as col
from app.core import jobs
from app.core import production as pr
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon


class BusinessDialog(SheetDialog):
    """Your business details – printed on proofs, installation and survey sheets."""

    def __init__(self, parent):
        super().__init__(parent, "user", "Business Details",
                         "Shown on customer proofs, installation sheets and survey sheets", size=(640, 640))
        self.data = jobs.load_business()
        form = QFormLayout()
        form.setSpacing(10)
        self.eds = {}
        for key, label, ph in (("name", "Business name", "e.g. iFix Digital Prints"),
                               ("phone", "Phone", ""), ("email", "Email", ""), ("website", "Website", ""),
                               ("address", "Address", ""),
                               ("country_code", "Country code", "for WhatsApp, e.g. 44 (UK), 92 (Pakistan)")):
            ed = QLineEdit(self.data.get(key, ""))
            ed.setPlaceholderText(ph)
            form.addRow(label, ed)
            self.eds[key] = ed
        if not self.data.get("country_code"):
            from app.ui.share import default_country_code
            guess = default_country_code()
            if guess:
                self.eds["country_code"].setPlaceholderText(f"{guess} (from this computer's region)")
        self.eds["country_code"].setToolTip("Customer numbers typed the local way (07700 900123) are sent to "
                                            "WhatsApp with this code in front (447700900123).")
        self.eds["country_code"].setMaximumWidth(260)
        lr = QHBoxLayout()
        self.logo_lbl = QLabel()
        self.logo_lbl.setFixedSize(160, 70)
        self.logo_lbl.setStyleSheet("background:#f6f8fb;border-radius:6px;")
        self.logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lr.addWidget(self.logo_lbl)
        b = QPushButton(icon("folder_fill", "#1e293b"), " Choose logo…")
        b.clicked.connect(self._logo)
        lr.addWidget(b)
        b2 = QPushButton("Remove")
        b2.clicked.connect(lambda: self._set_logo(""))
        lr.addWidget(b2)
        lr.addStretch()
        form.addRow("Logo", lr)
        self.terms = QPlainTextEdit(self.data.get("terms", ""))
        self.terms.setPlaceholderText("Optional terms printed under the approval box")
        self.terms.setFixedHeight(90)
        form.addRow("Terms", self.terms)
        self.body.addLayout(form)
        self.body.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        self.body.addWidget(bb)
        self._set_logo(self.data.get("logo", ""))

    def _set_logo(self, path: str) -> None:
        pm = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        if pm.isNull():
            self.data["logo"] = ""
            self.logo_lbl.setPixmap(QPixmap())
            self.logo_lbl.setText("No logo")
            return
        self.data["logo"] = path
        self.logo_lbl.setPixmap(pm.scaled(150, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))

    def _logo(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Logo", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not p:
            return
        if QPixmap(p).isNull():
            QMessageBox.warning(self, "Logo", f"{Path(p).name} can't be opened as a picture. "
                                "Choose a PNG or JPG file (a PNG with a clear background looks best).")
            return
        self._set_logo(p)

    def _save(self) -> None:
        for k, ed in self.eds.items():
            self.data[k] = ed.text().strip()
        self.data["terms"] = self.terms.toPlainText().strip()
        jobs.save_business(self.data)
        self.accept()


class PresetsDialog(SheetDialog):
    """Output presets: file format, colour profile, resolution, scale, slug, hot folder."""

    def __init__(self, parent):
        super().__init__(parent, "send_print", "Output Presets",
                         "How print files are made – match what your printer or RIP expects", size=(900, 660))
        self.presets = pr.load_presets()
        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        self.lst = QListWidget()
        self.lst.currentRowChanged.connect(self._show)
        left.addWidget(self.lst, 1)
        br = QHBoxLayout()
        b_new = QPushButton(icon("plus"), " New")
        b_new.clicked.connect(self._new)
        b_dup = QPushButton(icon("copy"), " Duplicate")
        b_dup.clicked.connect(self._dup)
        b_del = QPushButton(icon("trash"), " Delete")
        b_del.clicked.connect(self._del)
        for b in (b_new, b_dup, b_del):
            br.addWidget(b)
        left.addLayout(br)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(330)
        row.addWidget(lw)
        form = QFormLayout()
        form.setSpacing(9)
        self.ed_name = QLineEdit()
        self.cb_fmt = QComboBox()
        self.cb_fmt.addItems(["TIFF", "PDF", "JPG", "PNG"])
        self.cb_col = QComboBox()
        for p in col.list_profiles():
            self.cb_col.addItem(p.name)
        self.cb_intent = QComboBox()
        self.cb_intent.addItems(list(col.INTENTS))
        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(36, 1440)
        self.cb_scale = QComboBox()
        for t, v in (("100 % (full size)", 1.0), ("50 %", 0.5), ("25 %", 0.25), ("10 %", 0.1)):
            self.cb_scale.addItem(t, v)
        self.chk_slug = QCheckBox("Job / panel labels above and below the print (slug)")
        self.chk_marks = QCheckBox("Crop marks and overlap guides in the slug")
        self.chk_mirror = QCheckBox("Mirror the print (backlit / window film)")
        self.chk_blank = QCheckBox("Leave openings marked 'leave unprinted' white")
        self.chk_zip = QCheckBox("Also make a .zip of the package")
        self.ed_hot = QLineEdit()
        self.ed_hot.setPlaceholderText("Optional: RIP hot folder – panels are copied there")
        hb = QPushButton("Browse…")
        hb.clicked.connect(self._hot)
        hr = QHBoxLayout()
        hr.addWidget(self.ed_hot, 1)
        hr.addWidget(hb)
        b_icc = QPushButton(icon("plus"), " Add your printer / media profile (.icc)…")
        b_icc.clicked.connect(self._add_icc)
        form.addRow("Name", self.ed_name)
        form.addRow("Format", self.cb_fmt)
        form.addRow("Colour", self.cb_col)
        form.addRow("", b_icc)
        form.addRow("Rendering intent", self.cb_intent)
        form.addRow("Resolution (dpi)", self.sp_dpi)
        form.addRow("Scale", self.cb_scale)
        for c in (self.chk_slug, self.chk_marks, self.chk_mirror, self.chk_blank, self.chk_zip):
            form.addRow("", c)
        form.addRow("Hot folder", hr)
        self.note = hint("Built-in presets can't be changed – duplicate one to make your own.")
        form.addRow("", self.note)
        fw = QWidget()
        fw.setLayout(form)
        row.addWidget(fw, 1)
        self.body.addLayout(row, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        self.body.addWidget(bb)
        self._fill()

    def _fill(self, select: Optional[str] = None) -> None:
        self.lst.blockSignals(True)
        self.lst.clear()
        for p in self.presets:
            self.lst.addItem(("🔒 " if p.builtin else "") + p.name)
        self.lst.blockSignals(False)
        idx = next((i for i, p in enumerate(self.presets) if p.name == select), 0)
        self.lst.setCurrentRow(idx)
        self._show(idx)

    def _cur(self) -> Optional[pr.OutputPreset]:
        i = self.lst.currentRow()
        return self.presets[i] if 0 <= i < len(self.presets) else None

    def _show(self, i: int) -> None:
        self._commit_prev = None
        p = self._cur()
        if p is None:
            return
        self._editing = p
        widgets = (self.ed_name, self.cb_fmt, self.cb_col, self.cb_intent, self.sp_dpi, self.cb_scale,
                   self.chk_slug, self.chk_marks, self.chk_mirror, self.chk_blank, self.chk_zip, self.ed_hot)
        self.ed_name.setText(p.name)
        self.cb_fmt.setCurrentText(p.fmt)
        self.cb_col.setCurrentText(p.colour)
        self.cb_intent.setCurrentText(p.intent)
        self.sp_dpi.setValue(p.dpi)
        self.cb_scale.setCurrentIndex(max(0, self.cb_scale.findData(p.scale)))
        self.chk_slug.setChecked(p.slug)
        self.chk_marks.setChecked(p.marks)
        self.chk_mirror.setChecked(p.mirror)
        self.chk_blank.setChecked(p.blank_openings)
        self.chk_zip.setChecked(p.zip_package)
        self.ed_hot.setText(p.hot_folder)
        for w in widgets:
            w.setEnabled(not p.builtin)
        self.note.setVisible(p.builtin)

    def _commit(self) -> None:
        p = getattr(self, "_editing", None)
        if p is None or p.builtin:
            return
        i = self.presets.index(p)
        self.presets[i] = replace(p, name=self.ed_name.text().strip() or p.name, fmt=self.cb_fmt.currentText(),
                                  colour=self.cb_col.currentText(), intent=self.cb_intent.currentText(),
                                  dpi=self.sp_dpi.value(), scale=self.cb_scale.currentData(),
                                  slug=self.chk_slug.isChecked(), marks=self.chk_marks.isChecked(),
                                  mirror=self.chk_mirror.isChecked(), blank_openings=self.chk_blank.isChecked(),
                                  zip_package=self.chk_zip.isChecked(), hot_folder=self.ed_hot.text().strip())
        self._editing = self.presets[i]

    def _new(self) -> None:
        self._commit()
        p = pr.OutputPreset(f"My preset {len(self.presets) + 1}")
        self.presets.append(p)
        self._fill(p.name)

    def _dup(self) -> None:
        self._commit()
        p = self._cur()
        if p:
            q = replace(p, name=p.name + " (copy)", builtin=False)
            self.presets.append(q)
            self._fill(q.name)

    def _del(self) -> None:
        p = self._cur()
        if p and not p.builtin:
            self.presets.remove(p)
            self._editing = None
            self._fill()

    def _hot(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "RIP hot folder")
        if d:
            self.ed_hot.setText(d)

    def _add_icc(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Printer / media ICC profile", "", "ICC profiles (*.icc *.icm)")
        if not p:
            return
        try:
            prof = col.add_user_profile(p)
        except Exception as exc:
            QMessageBox.warning(self, "Profile", f"That file isn't a valid ICC profile.\n{exc}")
            return
        self.cb_col.addItem(prof.name)
        self.cb_col.setCurrentText(prof.name)

    def _save(self) -> None:
        self._commit()
        names = [p.name for p in self.presets]
        if len(set(names)) != len(names):
            QMessageBox.warning(self, "Presets", "Two presets have the same name.")
            return
        pr.save_presets(self.presets)
        self.accept()


class CloudDialog(SheetDialog):
    def __init__(self, parent):
        super().__init__(parent, "cloud_up", "Online AI",
                         "Optional – creative upscaling and AI ‘expand the design’ with your Replicate account",
                         size=(660, 480))
        self.s = QSettings("ImageResizeShare", "ImageResizeShare")
        txt = QLabel("Offline AI upscaling (Real-ESRGAN) is built in and free. For extra 'creative' detail and for "
                     "AI that draws new picture at the edges (Expand to fit), connect your own "
                     "<a href='https://replicate.com/account/api-tokens'>Replicate</a> account. Images are uploaded "
                     "to Replicate and you pay them per image (usually a few cents).")
        txt.setWordWrap(True)
        txt.setOpenExternalLinks(True)
        self.body.addWidget(txt)
        form = QFormLayout()
        self.ed = QLineEdit(str(self.s.value("replicate_token", "")))
        self.ed.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed.setPlaceholderText("r8_…")
        form.addRow("API token", self.ed)
        self.body.addLayout(form)
        self.status = hint("")
        self.body.addWidget(self.status)
        self.body.addStretch()
        row = QHBoxLayout()
        bt = QPushButton("Test connection")
        bt.clicked.connect(self._test)
        row.addWidget(bt)
        row.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        self.body.addLayout(row)

    def _test(self) -> None:
        try:
            who = cloud.check_token(self.ed.text().strip())
            self.status.setText(f"✓ Connected as {who}")
        except cloud.CloudError as e:
            self.status.setText(f"✗ {e}")

    def _save(self) -> None:
        self.s.setValue("replicate_token", self.ed.text().strip())
        self.accept()


class _Sig(QObject):
    done = Signal(object, str)
    progress = Signal(str)


class _CloudJob(QRunnable):
    def __init__(self, img, token, model, factor, creativity, resemblance):
        super().__init__()
        self.args = (img, token, model, factor, creativity, resemblance)
        self.sig = _Sig()

    def run(self):
        img, token, model, factor, c, r = self.args
        try:
            out = cloud.upscale(img, token, model, factor, c, r, progress=self.sig.progress.emit)
            self.sig.done.emit(out, "")
        except Exception as e:
            traceback.print_exc()
            self.sig.done.emit(None, str(e))


class CloudUpscaleDialog(SheetDialog):
    def __init__(self, parent, img: Image.Image):
        super().__init__(parent, "cloud_up", "Online Creative Upscale",
                         "Runs on Replicate with your account – the design is uploaded", size=(620, 520))
        self.img = img
        self.result_img: Optional[Image.Image] = None
        self.s = QSettings("ImageResizeShare", "ImageResizeShare")
        form = QFormLayout()
        self.cb_model = QComboBox()
        self.cb_model.addItems(list(cloud.MODELS))
        self.cb_model.setCurrentIndex(1)
        self.sp_f = QDoubleSpinBox()
        self.sp_f.setRange(2, 4)
        self.sp_f.setValue(2)
        self.sp_f.setSuffix(" ×")
        self.sp_c = QDoubleSpinBox()
        self.sp_c.setRange(0, 1)
        self.sp_c.setSingleStep(0.05)
        self.sp_c.setValue(0.35)
        self.sp_r = QDoubleSpinBox()
        self.sp_r.setRange(0, 3)
        self.sp_r.setSingleStep(0.1)
        self.sp_r.setValue(0.6)
        form.addRow("Model", self.cb_model)
        form.addRow("Enlarge", self.sp_f)
        form.addRow("Creativity (new detail)", self.sp_c)
        form.addRow("Resemblance (stay true)", self.sp_r)
        self.body.addLayout(form)
        self.body.addWidget(hint(f"Design: {img.width:,} × {img.height:,} px. Big images cost more and take longer – "
                                 "for murals, upscale online 2×, then use the offline AI to reach the wall size."))
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setVisible(False)
        self.body.addWidget(self.bar)
        self.status = hint("")
        self.body.addWidget(self.status)
        self.body.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        self.b_go = QPushButton(icon("sparkle", "#ffffff"), "  Upscale online")
        self.b_go.setObjectName("AIButton")
        self.b_go.setMinimumHeight(44)
        self.b_go.clicked.connect(self._go)
        b_c = QPushButton("Cancel")
        b_c.setObjectName("Light")
        b_c.setMinimumHeight(44)
        b_c.clicked.connect(self.reject)
        row.addWidget(self.b_go)
        row.addWidget(b_c)
        self.body.addLayout(row)

    def _go(self) -> None:
        token = str(self.s.value("replicate_token", ""))
        if not token:
            CloudDialog(self).exec()
            token = str(self.s.value("replicate_token", ""))
            if not token:
                return
        self.b_go.setEnabled(False)
        self.bar.setVisible(True)
        self.job = _CloudJob(self.img, token, self.cb_model.currentText(), self.sp_f.value(), self.sp_c.value(),
                             self.sp_r.value())
        self.job.setAutoDelete(False)
        self.job.sig.progress.connect(self.status.setText)
        self.job.sig.done.connect(self._done)
        QThreadPool.globalInstance().start(self.job)

    def _done(self, img, err: str) -> None:
        self.bar.setVisible(False)
        self.b_go.setEnabled(True)
        if err:
            self.status.setText(f"✗ {err}")
            return
        self.result_img = img
        self.accept()


# ======================================================================
# Data folder & backup
# ======================================================================
def startup_data_dir() -> Optional[str]:
    """Use the data folder chosen in Data & Backup (unless a test set IRS_HOME).

    Returns the chosen folder when it cannot be found (e.g. a USB drive that is not plugged
    in) so the app can tell the user, instead of silently showing an empty job list."""
    import os
    from app.core import paths
    if os.environ.get("IRS_HOME"):
        return None
    d = str(QSettings("ImageResizeShare", "ImageResizeShare").value("data_dir", "") or "")
    if not d:
        return None
    if Path(d).is_dir():
        paths.set_base_dir(d)
        return None
    return d


def auto_backup_due() -> Optional[Path]:
    """The auto-backup folder if a backup is due now, else None."""
    import os
    from datetime import datetime, timedelta
    from app.core import backup as bk
    if os.environ.get("IRS_HOME"):
        return None
    s = QSettings("ImageResizeShare", "ImageResizeShare")
    if str(s.value("auto_backup", "false")).lower() not in ("true", "1"):
        return None
    d = str(s.value("auto_backup_dir", "") or "")
    if not d or not Path(d).is_dir():
        return None
    try:
        days = max(1, int(s.value("auto_backup_days", 1) or 1))
    except (TypeError, ValueError):
        days = 1
    last = bk.last_backup(Path(d))
    if last is None or datetime.now() - last >= timedelta(days=days):
        return Path(d)
    return None


class DataDialog(SheetDialog):
    """Where jobs are kept (e.g. OneDrive or a shared folder) and backups."""

    def __init__(self, parent):
        from app.core import paths
        super().__init__(parent, "folder_open", "Data & Backup",
                         "Where your jobs and library are kept, and how they are backed up", size=(760, 640))
        self.s = QSettings("ImageResizeShare", "ImageResizeShare")
        self.running = False
        t = QLabel("Data folder")
        t.setObjectName("PaneTitle")
        self.body.addWidget(t)
        r = QHBoxLayout()
        self.lbl_dir = QLabel(str(paths.base_dir()))
        self.lbl_dir.setWordWrap(True)
        self.lbl_dir.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        r.addWidget(self.lbl_dir, 1)
        b = QPushButton("Change…")
        b.clicked.connect(self.change_dir)
        r.addWidget(b)
        bo = QPushButton(icon("folder_open"), "")
        bo.setToolTip("Open the data folder")
        bo.clicked.connect(lambda: __import__("app.ui.share", fromlist=["share"]).show_in_folder(paths.base_dir()))
        r.addWidget(bo)
        self.body.addLayout(r)
        h = hint("Tip: choose a folder inside OneDrive, Google Drive or Dropbox – or a shared network folder – and "
                 "set the same folder on your other shop PC. Both then see the same jobs and library. "
                 "Don't open the same job on two PCs at the same time.")
        h.setWordWrap(True)
        self.body.addWidget(h)

        t2 = QLabel("Backup")
        t2.setObjectName("PaneTitle")
        self.body.addWidget(t2)
        self.chk_print = QCheckBox("Include print packages (large panel files – they can always be made again)")
        self.body.addWidget(self.chk_print)
        br = QHBoxLayout()
        b1 = QPushButton(icon("download"), "  Back up now…")
        b1.clicked.connect(self.backup_now)
        br.addWidget(b1)
        b2 = QPushButton(icon("upload"), "  Restore from a backup…")
        b2.clicked.connect(self.restore)
        br.addWidget(b2)
        br.addStretch()
        self.body.addLayout(br)
        ar = QHBoxLayout()
        self.chk_auto = QCheckBox("Back up automatically every")
        self.chk_auto.setChecked(str(self.s.value("auto_backup", "false")).lower() in ("true", "1"))
        ar.addWidget(self.chk_auto)
        self.sp_days = QSpinBox()
        self.sp_days.setRange(1, 30)
        self.sp_days.setValue(int(self.s.value("auto_backup_days", 1) or 1))
        self.sp_days.setSuffix(" day(s)")
        ar.addWidget(self.sp_days)
        ar.addWidget(QLabel("to"))
        self.ed_auto = QLineEdit(str(self.s.value("auto_backup_dir", "") or ""))
        self.ed_auto.setPlaceholderText("Choose a folder, e.g. on a USB drive or OneDrive")
        ar.addWidget(self.ed_auto, 1)
        ba = QPushButton("…")
        ba.setFixedWidth(34)
        ba.clicked.connect(self._choose_auto)
        ar.addWidget(ba)
        self.body.addLayout(ar)
        self.body.addWidget(hint("Automatic backups run in the background when the app starts. The last 5 are kept."))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.body.addWidget(self.progress)
        self.status = hint("")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.body.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        self.body.addWidget(bb)

    def _choose_auto(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Automatic backup folder", self.ed_auto.text() or str(Path.home()))
        if d:
            self.ed_auto.setText(d)

    def _save(self) -> None:
        if self.chk_auto.isChecked() and not Path(self.ed_auto.text().strip()).is_dir():
            QMessageBox.information(self, "Backup", "Choose a folder for the automatic backups first.")
            return
        self.s.setValue("auto_backup", self.chk_auto.isChecked())
        self.s.setValue("auto_backup_days", self.sp_days.value())
        self.s.setValue("auto_backup_dir", self.ed_auto.text().strip())
        self.accept()

    def _run(self, fn, done_text) -> None:
        from app.ui.worker import run_bg
        self.running = True
        self.progress.setVisible(True)
        self.progress.setValue(0)

        def done(res):
            self.running = False
            self.progress.setVisible(False)
            self.status.setText(done_text(res))

        def failed(msg):
            self.running = False
            self.progress.setVisible(False)
            QMessageBox.warning(self, "Data & Backup", msg)

        run_bg(fn, done, failed, lambda f, t: (self.progress.setValue(int(f * 1000)), self.status.setText(t)),
               task="the backup / restore")

    def backup_now(self) -> None:
        if self.running:
            return
        from app.core import backup as bk
        d = QFileDialog.getExistingDirectory(self, "Save the backup in", self.ed_auto.text() or str(Path.home()))
        if not d:
            return
        inc = self.chk_print.isChecked()
        self._run(lambda p: bk.backup(Path(d), inc, progress=p),
                  lambda r: f"✓ Backed up {r.files} files ({r.bytes / 1e6:,.0f} MB) to {r.path}")

    def restore(self) -> None:
        if self.running:
            return
        from app.core import backup as bk
        f, _ = QFileDialog.getOpenFileName(self, "Restore from a backup", self.ed_auto.text() or str(Path.home()),
                                           "Backups (*.zip)")
        if not f:
            return
        if QMessageBox.question(self, "Restore", "Add the jobs and designs from this backup?\n\n"
                                "Jobs you already have are only replaced when the backup's copy is newer. "
                                "Nothing else is overwritten.") != QMessageBox.StandardButton.Yes:
            return
        self._run(lambda p: bk.restore(Path(f), progress=p),
                  lambda r: f"✓ Restored: {r.jobs_added} new job(s), {r.jobs_updated} updated, {r.jobs_kept} kept "
                            f"as they were, {r.other_files} other file(s).")

    def change_dir(self) -> None:
        if self.running:
            return
        from app.core import backup as bk
        from app.core import paths
        cur = paths.base_dir()
        main = self.parent()
        if main is not None and getattr(main, "studio", None) is not None:
            main.studio.save_now()
        d = QFileDialog.getExistingDirectory(self, "Keep jobs and the library in", str(cur.parent))
        if not d or Path(d) == cur:
            return
        new = Path(d)
        if new.name != "Image Resize & Share" and not (new / "Jobs").is_dir():
            new = new / "Image Resize & Share"
        new.mkdir(parents=True, exist_ok=True)
        has_here = (cur / "Jobs").is_dir() and any((cur / "Jobs").iterdir())
        copy = False
        if has_here:
            ans = QMessageBox.question(self, "Data folder", f"Copy your current jobs and library to\n{new}?\n\n"
                                       "Yes = copy them (nothing is deleted here).\nNo = start using the new folder "
                                       "as it is (e.g. it already has the jobs from your other PC).",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                       QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                return
            copy = ans == QMessageBox.StandardButton.Yes

        def switch(_res=None):
            self.s.setValue("data_dir", str(new))
            paths.set_base_dir(new)
            self.lbl_dir.setText(str(new))
            self.status.setText("✓ Now using this folder. The Jobs list shows the jobs kept there.")
            if main is not None and getattr(main, "studio", None) is not None:
                main.studio.job = None
                main.studio.settings.remove("studio_last_job")
                main.studio.activated()
            if main is not None and getattr(main, "jobs_page", None) is not None:
                main.jobs_page.refresh()

        if copy:
            self._run(lambda p: bk.copy_data(cur, new, p), lambda n: (switch(), f"✓ Copied {n} files. Now using {new}")[1])
        else:
            switch()
