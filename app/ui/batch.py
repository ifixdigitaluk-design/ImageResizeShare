"""Batch mode: resize / convert many images at once."""
from __future__ import annotations

from dataclasses import replace
import re
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QVBoxLayout)

from app.core import imaging as im
from app.ui.errors import write_bytes_safely
from app.ui.qtutil import FreeAfterExec
from app.ui.qtutil import hint, icon, section

R_KEEP, R_PERCENT, R_FIT, R_EXACT = range(4)


class BatchThread(QThread):
    progress = Signal(int, int, str)
    done = Signal(int, list)

    def __init__(self, files, out_dir, mode, w, h, pct, rs, os_, ai, pattern):
        super().__init__()
        self.files, self.out_dir = files, Path(out_dir)
        self.mode, self.w, self.h, self.pct = mode, w, h, pct
        self.rs, self.os_, self.ai, self.pattern = rs, os_, ai, pattern
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok, errors = 0, []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(self.files):
            if self._cancel:
                break
            self.progress.emit(i, len(self.files), Path(f).name)
            try:
                try:
                    src = im.load_image(f)
                except Exception as exc:
                    errors.append(im.load_error_text(f, exc))
                    continue
                W, H = src.image.size
                rs = replace(self.rs)
                if self.mode == R_KEEP:
                    rs.enabled = False
                elif self.mode == R_PERCENT:
                    rs.width = max(1, round(W * self.pct / 100))
                    rs.height = max(1, round(H * self.pct / 100))
                    rs.mode = im.MODE_STRETCH
                elif self.mode == R_FIT:
                    rs.width, rs.height, rs.mode = self.w, self.h, im.MODE_FIT_INSIDE
                else:
                    rs.width, rs.height = self.w, self.h
                res = im.process(src, im.EditState(), rs, self.os_, self.ai)
                ow, oh = res.image.size
                name = (self.pattern.replace("{name}", Path(f).stem)
                        .replace("{w}", str(ow)).replace("{h}", str(oh)))
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or Path(f).stem
                out = im.unique_path(self.out_dir / (name[:120] + im.FORMATS[self.os_.fmt]["ext"]))
                write_bytes_safely(out, res.data)
                ok += 1
            except MemoryError:
                errors.append(f"{Path(f).name}: not enough memory for this size.")
            except PermissionError:
                errors.append(f"{Path(f).name}: the output folder is read-only or the file is open elsewhere.")
            except OSError as exc:
                errors.append(f"{Path(f).name}: " + ("the disk is full." if getattr(exc, "errno", None) == 28
                                                     else str(exc)))
            except Exception as exc:
                errors.append(f"{Path(f).name}: {exc}")
        self.progress.emit(len(self.files), len(self.files), "")
        self.done.emit(ok, errors)


class BatchDialog(FreeAfterExec, QDialog):
    def __init__(self, parent, files, rs: im.ResizeSettings, os_: im.OutputSettings,
                 ai, exts, start_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Batch resize & convert")
        self.setMinimumSize(620, 560)
        self.rs, self.os_, self.ai, self.exts = rs, os_, ai, exts
        self.thread = None
        self.start_dir = start_dir

        lay = QVBoxLayout(self)
        lay.addWidget(section("Images"))
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_add = QPushButton(icon("image"), " Add images…")
        b_dir = QPushButton(icon("folder"), " Add folder…")
        b_rm = QPushButton("Remove selected")
        b_clr = QPushButton("Clear")
        for b in (b_add, b_dir, b_rm, b_clr):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        b_add.clicked.connect(self.add_files)
        b_dir.clicked.connect(self.add_folder)
        b_rm.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        b_clr.clicked.connect(self.list.clear)

        lay.addWidget(section("Size"))
        g = QGridLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Keep original size (convert only)", "Scale by percentage",
                            "Fit within W × H (keep shape, no borders)",
                            "Exact W × H (uses the shape option from the main window)"])
        self.mode.setCurrentIndex(R_FIT)
        self.w = QSpinBox(); self.w.setRange(1, im.MAX_OUTPUT_SIDE); self.w.setValue(rs.width or 1080)
        self.h = QSpinBox(); self.h.setRange(1, im.MAX_OUTPUT_SIDE); self.h.setValue(rs.height or 1080)
        self.pct = QSpinBox(); self.pct.setRange(1, 1600); self.pct.setValue(50); self.pct.setSuffix(" %")
        g.addWidget(self.mode, 0, 0, 1, 4)
        g.addWidget(QLabel("Width (px)"), 1, 0); g.addWidget(self.w, 1, 1)
        g.addWidget(QLabel("Height (px)"), 1, 2); g.addWidget(self.h, 1, 3)
        g.addWidget(QLabel("Percentage"), 2, 0); g.addWidget(self.pct, 2, 1)
        lay.addLayout(g)
        self.mode.currentIndexChanged.connect(self._mode_changed)

        lay.addWidget(section("Output"))
        fmt_txt = os_.fmt + (f", quality {os_.quality}%" if im.FORMATS[os_.fmt]["lossy"] else "")
        if os_.target_kb:
            fmt_txt += f", max {os_.target_kb} KB"
        lay.addWidget(hint(f"Format: {fmt_txt}. Enlarge quality: {rs.upscale}. "
                           "(Change these in the main window.)"))
        o = QGridLayout()
        self.out = QLineEdit()
        b_out = QPushButton("Browse…")
        b_out.clicked.connect(self.pick_out)
        self.pattern = QLineEdit("{name}_{w}x{h}")
        o.addWidget(QLabel("Save to"), 0, 0); o.addWidget(self.out, 0, 1); o.addWidget(b_out, 0, 2)
        o.addWidget(QLabel("File name"), 1, 0); o.addWidget(self.pattern, 1, 1)
        o.addWidget(hint("{name} = original name, {w} {h} = new size"), 1, 2)
        lay.addLayout(o)

        self.bar = QProgressBar(); self.bar.setTextVisible(False)
        self.status = QLabel("")
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        br = QHBoxLayout()
        br.addStretch()
        self.b_run = QPushButton(icon("batch", "#155fc0"), " Start")
        self.b_run.setObjectName("Primary")
        self.b_close = QPushButton("Close")
        br.addWidget(self.b_run); br.addWidget(self.b_close)
        lay.addLayout(br)
        self.b_run.clicked.connect(self.start)
        self.b_close.clicked.connect(self.close_or_cancel)

        self.add_paths(files)
        self._mode_changed(self.mode.currentIndex())

    # ------------------------------------------------------------------
    def _mode_changed(self, i):
        self.w.setEnabled(i in (R_FIT, R_EXACT))
        self.h.setEnabled(i in (R_FIT, R_EXACT))
        self.pct.setEnabled(i == R_PERCENT)

    def add_paths(self, paths):
        existing = {self.list.item(i).text() for i in range(self.list.count())}
        for p in paths:
            p = str(p)
            if Path(p).suffix.lower() in self.exts and p not in existing:
                self.list.addItem(p)
                existing.add(p)
        if self.list.count() and not self.out.text():
            self.out.setText(str(Path(self.list.item(0).text()).parent / "resized"))

    def add_files(self):
        flt = "Images (" + " ".join("*" + e for e in self.exts) + ")"
        files, _ = QFileDialog.getOpenFileNames(self, "Add images", self.start_dir, flt)
        self.add_paths(files)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder", self.start_dir)
        if d:
            self.add_paths(sorted(str(p) for p in Path(d).iterdir() if p.is_file()))

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Save to folder", self.out.text())
        if d:
            self.out.setText(d)

    def start(self):
        files = [self.list.item(i).text() for i in range(self.list.count())]
        if not files:
            QMessageBox.information(self, "Batch", "Add some images first.")
            return
        if not self.out.text().strip():
            QMessageBox.information(self, "Batch", "Choose an output folder.")
            return
        self.b_run.setEnabled(False)
        self.b_close.setText("Cancel")
        self.bar.setRange(0, len(files))
        self.thread = BatchThread(files, self.out.text().strip(), self.mode.currentIndex(),
                                  self.w.value(), self.h.value(), self.pct.value(),
                                  self.rs, self.os_, self.ai, self.pattern.text() or "{name}")
        self.thread.progress.connect(self._on_progress)
        self.thread.done.connect(self._on_done)
        self.thread.start()

    def _on_progress(self, i, n, name):
        self.bar.setValue(i)
        self.status.setText(f"Processing {i + 1} of {n}: {name}" if name else "Finishing…")

    def _on_done(self, ok, errors):
        self.b_run.setEnabled(True)
        self.b_close.setText("Close")
        msg = f"Done: {ok} image(s) saved to {self.out.text()}"
        if errors:
            msg += f"\n\n{len(errors)} failed:\n" + "\n".join(errors[:15])
        self.status.setText(f"Done – {ok} saved, {len(errors)} failed.")
        QMessageBox.information(self, "Batch complete", msg)
        self.thread = None

    def close_or_cancel(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.cancel()
            self.status.setText("Cancelling…")
        else:
            self.accept()

    def closeEvent(self, ev):
        if self.thread is not None and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait(5000)
        super().closeEvent(ev)
