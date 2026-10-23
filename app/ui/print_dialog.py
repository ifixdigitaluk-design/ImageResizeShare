"""Send to Print: preflight with one-click fixes, then the print-ready package."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from app.core import documents as docs
from app.core import jobs
from app.core import preflight as pf
from app.core import production as pr
from app.core import units as un
from app.core import wall as wl
from app.ui import share
from app.ui.preview_dialogs import SheetDialog
from app.ui.qtutil import hint, icon, svg_pixmap
from app.ui.worker import run_bg

LEVEL = {"ok": ("check", "#16a34a"), "info": ("help", "#2563eb"), "warn": ("warning", "#d97706"),
         "error": ("warning", "#dc2626")}
FIX_TEXT = {"upscale": "AI Upscale", "fit_cover": "Fill the wall", "auto_seams": "Place seams safely",
            "proof": "Make a proof", "measure": "Measure", "design": "Choose design", "gamut": "Check colours",
            "bleed": "Use 5 cm bleed", "scale": "Use 50 % scale", "expand": "Expand design"}


class PrintDialog(SheetDialog):
    def __init__(self, studio):
        super().__init__(studio.window(), "send_print", "Send to Print",
                         "Check everything, then make the print-ready files for the print shop or your RIP.",
                         size=(1280, 900))
        self.studio = studio
        self.job = studio.job
        self.running = None
        self.cancelled = False
        self.result: Optional[pr.PackageResult] = None

        row = QHBoxLayout()
        row.setSpacing(18)
        # ---- checks ----
        left = QVBoxLayout()
        left.setSpacing(8)
        t = QLabel("Print checks")
        t.setObjectName("PaneTitle")
        left.addWidget(t)
        self.lbl_sum = QLabel("")
        self.lbl_sum.setTextFormat(Qt.TextFormat.RichText)
        left.addWidget(self.lbl_sum)
        self.checks_box = QWidget()
        self.checks_box.setObjectName("LeftInner")
        self.checks_lay = QVBoxLayout(self.checks_box)
        self.checks_lay.setContentsMargins(0, 0, 6, 0)
        self.checks_lay.setSpacing(8)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(self.checks_box)
        left.addWidget(sc, 1)
        row.addLayout(left, 3)
        # ---- output ----
        right = QVBoxLayout()
        right.setSpacing(10)
        t2 = QLabel("Print files")
        t2.setObjectName("PaneTitle")
        right.addWidget(t2)
        pr_row = QHBoxLayout()
        self.cb_preset = QComboBox()
        for p in pr.load_presets():
            self.cb_preset.addItem(p.name)
        self.cb_preset.setCurrentIndex(max(0, self.cb_preset.findText(self.job.output_preset)))
        self.cb_preset.currentIndexChanged.connect(self._on_preset)
        pr_row.addWidget(self.cb_preset, 1)
        b_ed = QPushButton(icon("gear"), "")
        b_ed.setToolTip("Edit output presets (format, colour profile, DPI, hot folder)")
        b_ed.clicked.connect(self._edit_presets)
        pr_row.addWidget(b_ed)
        right.addLayout(pr_row)
        self.lbl_out = QLabel("")
        self.lbl_out.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_out.setWordWrap(True)
        box = QFrame()
        box.setObjectName("InfoBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.addWidget(self.lbl_out)
        right.addWidget(box)
        t3 = QLabel("Include")
        t3.setObjectName("PaneTitle")
        right.addWidget(t3)
        self.chk_inst = QCheckBox("Installation sheet (hanging plan, PDF)")
        self.chk_inst.setChecked(True)
        self.chk_proof = QCheckBox("The approved customer proof")
        self.chk_proof.setChecked(bool(self.job.proof_file))
        self.chk_proof.setEnabled(bool(self.job.proof_file))
        self.chk_strip = QCheckBox("Test strip (A4 at 100 % with colour patches)")
        self.chk_strip.setChecked(True)
        self.chk_report = QCheckBox("Preflight report")
        self.chk_report.setChecked(True)
        for c in (self.chk_inst, self.chk_proof, self.chk_strip, self.chk_report):
            right.addWidget(c)
        right.addWidget(hint("Every package also has a job ticket (TXT + JSON) and a README for the printer."))
        fr = QHBoxLayout()
        fr.addWidget(QLabel("Save in"))
        self.lbl_dir = QLabel("")
        self.lbl_dir.setObjectName("Hint")
        self.lbl_dir.setWordWrap(True)
        fr.addWidget(self.lbl_dir, 1)
        b_dir = QPushButton("Change…")
        b_dir.clicked.connect(self._choose_dir)
        fr.addWidget(b_dir)
        right.addLayout(fr)
        self.out_dir: Optional[Path] = None
        right.addStretch()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        right.addWidget(self.progress)
        self.lbl_prog = hint("")
        self.lbl_prog.setWordWrap(True)
        right.addWidget(self.lbl_prog)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(430)
        row.addWidget(rw)
        self.body.addLayout(row, 1)

        bot = QHBoxLayout()
        bot.setSpacing(12)
        self.b_folder = QPushButton(icon("folder_open"), "  Open Folder")
        self.b_folder.setObjectName("Light")
        self.b_folder.setVisible(False)
        self.b_folder.clicked.connect(self._open_result)
        bot.addWidget(self.b_folder)
        bot.addStretch()
        self.b_cancel = QPushButton("Stop")
        self.b_cancel.setObjectName("Light")
        self.b_cancel.setVisible(False)
        self.b_cancel.clicked.connect(self._cancel)
        bot.addWidget(self.b_cancel)
        self.b_go = QPushButton(icon("send_print", "#ffffff"), "  Create Print Package")
        self.b_go.setObjectName("Go")
        self.b_go.setIconSize(QSize(20, 20))
        self.b_go.clicked.connect(self.create)
        bot.addWidget(self.b_go)
        self.b_close = QPushButton("Close")
        self.b_close.setObjectName("Light")
        self.b_close.clicked.connect(self._close)
        bot.addWidget(self.b_close)
        self.body.addLayout(bot)
        self._refresh()

    # ------------------------------------------------------------------
    def preset(self) -> pr.OutputPreset:
        return pr.find_preset(self.cb_preset.currentText())

    def _refresh(self) -> None:
        st, j = self.studio, self.job
        st._update_side()
        self.checks = pf.run(j, st.source, self.preset(), st.risk, st.gamut_fraction, st.job_dir)
        while self.checks_lay.count():
            it = self.checks_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for c in self.checks:
            self.checks_lay.addWidget(self._check_row(c))
        self.checks_lay.addStretch()
        e, w = pf.counts(self.checks)
        if e:
            s = f"<span style='color:#dc2626;font-weight:700'>{e} problem{'s' if e != 1 else ''}</span> to fix " \
                f"before printing" + (f" · {w} warning{'s' if w != 1 else ''}" if w else "")
        elif w:
            s = f"<span style='color:#d97706;font-weight:700'>{w} warning{'s' if w != 1 else ''}</span> – " \
                "you can print, but check them first"
        else:
            s = "<span style='color:#16a34a;font-weight:700'>Ready to print ✓</span>"
        self.lbl_sum.setText(s)
        self._update_out()

    def _check_row(self, c: pf.Check) -> QWidget:
        f = QFrame()
        f.setObjectName("InfoBox" if c.level in ("ok", "info") else "WarnBox" if c.level == "warn" else "ErrBox")
        if c.level == "error":
            f.setStyleSheet("#ErrBox{background:#fef2f2;border:1px solid #fecaca;border-radius:10px;}")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(12)
        ic = QLabel()
        name, colr = LEVEL[c.level]
        ic.setPixmap(svg_pixmap(name, colr, 22))
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(c.title)
        t.setStyleSheet("font-weight:600;")
        t.setWordWrap(True)
        col.addWidget(t)
        if c.detail:
            d = QLabel(c.detail)
            d.setObjectName("Hint")
            d.setWordWrap(True)
            col.addWidget(d)
        lay.addLayout(col, 1)
        if c.fix and c.level in ("warn", "error") and c.fix in FIX_TEXT:
            b = QPushButton(FIX_TEXT[c.fix])
            b.setObjectName("Primary")
            b.clicked.connect(lambda _c=False, fx=c.fix: self._fix(fx))
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        return f

    def _fix(self, fx: str) -> None:
        st, j = self.studio, self.job
        try:
            if fx == "upscale":
                st.ai_upscale()
            elif fx == "fit_cover":
                st._snapshot()
                j.placement.mode = "fill"
                st.refresh_forms()
                st._changed("placement", undoable=False)
            elif fx == "auto_seams":
                if st.risk is None:
                    QMessageBox.information(self, "Seams", "Still checking the design for faces and detail – "
                                                           "try again in a moment.")
                    st._start_risk()
                    return
                st.safe_seams()
            elif fx == "expand":
                st.expand_design()
            elif fx == "proof":
                st.open_proof()
            elif fx == "measure":
                st.open_measure()
            elif fx == "design":
                st.choose_design()
            elif fx == "gamut":
                st.open_colour()
            elif fx == "bleed":
                st._snapshot()
                for k in ("top", "bottom", "left", "right"):
                    setattr(j.panels, f"bleed_{k}", max(getattr(j.panels, f"bleed_{k}"), 0.05))
                st.refresh_forms()
                st._changed("geometry", undoable=False)
            elif fx == "scale":
                k = next((i for i in range(self.cb_preset.count()) if "50 %" in self.cb_preset.itemText(i)), -1)
                if k >= 0:
                    self.cb_preset.setCurrentIndex(k)
        except Exception:
            traceback.print_exc()
        self.job = st.job
        self._refresh()

    def _on_preset(self, _i: int) -> None:
        p = self.preset()
        self.job.output_preset = p.name
        self.job.print_dpi = p.dpi
        self.studio.reload_presets()
        self.studio._changed("colour", undoable=False)
        self._refresh()

    def _edit_presets(self) -> None:
        self.studio.main.open_presets()
        cur = self.cb_preset.currentText()
        self.cb_preset.blockSignals(True)
        self.cb_preset.clear()
        for p in pr.load_presets():
            self.cb_preset.addItem(p.name)
        self.cb_preset.setCurrentIndex(max(0, self.cb_preset.findText(cur)))
        self.cb_preset.blockSignals(False)
        self._refresh()

    def _update_out(self) -> None:
        j, p = self.job, self.preset()
        panels = wl.compute_panels(j)
        est = pr.estimate_bytes(j, p)
        ppm = p.dpi * p.scale / un.M_PER_IN
        w0 = max(p_.width for p_ in panels) if panels else 0
        size = f"{est / 1e9:.1f} GB" if est > 1e9 else f"{max(1, est // 1_000_000)} MB"
        self.lbl_out.setText(
            f"<b>{len(panels)} panel files</b> · {p.fmt} · {p.colour}<br>"
            f"{p.dpi} dpi{' at ' + str(int(p.scale * 100)) + ' % scale' if p.scale != 1 else ''} · "
            f"widest panel {w0 * 100:.1f} cm = {int(w0 * ppm):,} px<br>"
            f"Length {j.art_height * 100:.1f} cm incl. bleed · about <b>{size}</b><br>"
            f"<span style='color:#64748b'>{'Labels and marks on each panel' if p.slug else 'No labels (RIP)'}"
            f"{' · mirrored' if p.mirror else ''}{' · zipped' if p.zip_package else ''}"
            f"{' · copied to hot folder' if p.hot_folder else ''}</span>")
        d = self.out_dir or ((self.studio.job_dir or jobs.folder_for(j)) / "print")
        self.lbl_dir.setText(str(d))

    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Save the print package in", str(self.out_dir or Path.home()))
        if d:
            self.out_dir = Path(d)
            self._update_out()

    # ------------------------------------------------------------------
    def create(self) -> None:
        st, j = self.studio, self.job
        if st.source is None:
            QMessageBox.information(self, "Send to Print", "Choose a design first.")
            return
        e, _w = pf.counts(self.checks)
        if e:
            if QMessageBox.question(self, "Send to Print", "There are problems that will show in the print. "
                                    "Make the files anyway?") != QMessageBox.StandardButton.Yes:
                return
        if j.status not in pf.APPROVED_STATES and not j.approved_by:
            if QMessageBox.question(self, "Send to Print", "The customer hasn't approved a proof yet.\n\n"
                                    "Print without approval?") != QMessageBox.StandardButton.Yes:
                return
        job_dir = st.ensure_dir()
        jobs.save_job(j)
        preset = self.preset()
        strip = None
        if self.chk_strip.isChecked():
            strip = docs.test_strip(st.source, j, (j.art_width / 2, j.art_height / 2), (0.297, 0.21), preset.dpi)
        report = pf.report_text(self.checks, j) if self.chk_report.isChecked() else ""
        args = dict(installer_sheet=self.chk_inst.isChecked(),
                    include_proof=self.chk_proof.isChecked(), test_strip=strip, preflight_text=report,
                    business=jobs.load_business(), out_dir=self.out_dir)
        job_copy = j.copy()
        source = st.source
        self.cancelled = False
        self._busy(True)

        def work(progress):
            return pr.make_package(job_copy, job_dir, source, preset, progress=progress,
                                   cancel=lambda: self.cancelled, **args)

        self.running = run_bg(work, self._done, self._failed, self._progress, task="the print package")

    def _busy(self, on: bool) -> None:
        self.progress.setVisible(on)
        self.progress.setValue(0)
        self.b_cancel.setVisible(on)
        self.b_go.setEnabled(not on)
        self.b_close.setEnabled(not on)
        self.cb_preset.setEnabled(not on)

    def _progress(self, f: float, text: str) -> None:
        self.progress.setValue(int(f * 1000))
        self.lbl_prog.setText(text)

    def _cancel(self) -> None:
        self.cancelled = True
        self.lbl_prog.setText("Stopping…")

    def _done(self, res: pr.PackageResult) -> None:
        self.running = None
        self._busy(False)
        self.result = res
        j = self.job
        j.log(f"Print package made: {res.folder.name} ({self.preset().name})")
        if j.status in ("Approved", "Proof sent", "Designing", "Measured", "Enquiry"):
            j.set_status("Printing")
        jobs.save_job(j)
        total = sum(f.stat().st_size for f in res.files if f.exists())
        msg = f"✓ {len(res.files)} files, {total / 1e6:,.0f} MB in {res.folder.name}"
        if res.zip_path:
            msg += f"\nZip for the print shop: {res.zip_path.name}"
        if res.hot_folder_copy:
            msg += f"\nPanels copied to the hot folder: {res.hot_folder_copy}"
        self.lbl_prog.setText(msg)
        self.b_folder.setVisible(True)
        self.studio.refresh_forms()

    def _failed(self, msg: str) -> None:
        self.running = None
        self._busy(False)
        if "Cancelled" in msg or self.cancelled:
            self.lbl_prog.setText("Stopped. Nothing was sent.")
            return
        QMessageBox.warning(self, "Send to Print", f"Could not make the print files:\n{msg}")
        self.lbl_prog.setText("")

    def _open_result(self) -> None:
        if self.result:
            share.show_in_folder(self.result.zip_path or self.result.folder)

    def _close(self) -> None:
        if self.running is None:
            self.accept()

    def reject(self) -> None:
        if self.running is None:
            super().reject()
        else:
            self._cancel()
