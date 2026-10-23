"""Jobs list, design library and the customer showroom."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app.core import jobs
from app.core import mockup as mk
from app.core import wall as wl
from app.ui import share
from app.ui.qtutil import FreeAfterExec
from app.ui.qtutil import Card, hint, icon, pil_to_qimage

SLATE = "#334155"


def _pix(path: Optional[Path], size: int) -> QPixmap:
    if path and Path(path).is_file():
        pm = QPixmap(str(path))
        if not pm.isNull():
            return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    pm = QPixmap(size, size)
    pm.fill(QColor("#eef1f5"))
    return pm


class JobsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(14)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.seg = QButtonGroup(self)
        segs = (("  Jobs", "briefcase"), ("  Installs", "calendar"), ("  Design Library", "books"))
        for i, (t, ic) in enumerate(segs):
            b = QPushButton(icon(ic, SLATE, "#ffffff"), t)
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setMinimumHeight(44)
            b.setMinimumWidth(200)
            b.setIconSize(QSize(20, 20))
            b.setStyleSheet("border-top-left-radius:8px;border-bottom-left-radius:8px;" if i == 0 else
                            "border-top-right-radius:8px;border-bottom-right-radius:8px;" if i == len(segs) - 1
                            else "")
            self.seg.addButton(b, i)
            seg.addWidget(b)
        seg.addStretch()
        outer.addLayout(seg)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._jobs_view())
        from app.ui.installs_view import InstallsView
        self.installs = InstallsView(self.main, self)
        self.stack.addWidget(self.installs)
        self.library = LibraryView(self.main, self)
        self.stack.addWidget(self.library)
        outer.addWidget(self.stack, 1)
        self.seg.idClicked.connect(self._on_seg)
        self.seg.button(0).setChecked(True)

    # ------------------------------------------------------------------
    def _jobs_view(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        c = Card()
        head = QHBoxLayout()
        t = QLabel("Jobs")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search customer, job number, room…")
        self.search.textChanged.connect(lambda _t: self.refresh())
        head.addWidget(self.search, 1)
        self.cb_status = QComboBox()
        self.cb_status.addItem("All statuses", "")
        self.cb_status.addItem("Open (not completed)", "open")
        for s in wl.STATUSES:
            self.cb_status.addItem(s, s)
        self.cb_status.currentIndexChanged.connect(lambda _i: self.refresh())
        head.addWidget(self.cb_status)
        for ic, txt, fn in (("plus", " New job", self.new_job), ("wall", " Open", self.open_selected),
                            ("copy", " Reprint", self.duplicate), ("folder_open", " Folder", self.open_folder),
                            ("trash", " Delete", self.delete)):
            b = QPushButton(icon(ic), txt)
            b.clicked.connect(fn)
            head.addWidget(b)
        c.lay.addLayout(head)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "Job", "Customer", "Room", "Walls (m)", "Status", "Updated"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setIconSize(QSize(72, 48))
        self.table.verticalHeader().setDefaultSectionSize(56)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._show_details)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_selected())
        c.lay.addWidget(self.table, 1)
        self.lbl_count = hint("")
        c.lay.addWidget(self.lbl_count)
        row.addWidget(c, 1)
        d = Card()
        t2 = QLabel("Job details")
        t2.setObjectName("CardTitle")
        d.lay.addWidget(t2)
        self.d_thumb = QLabel()
        self.d_thumb.setFixedHeight(200)
        self.d_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.d_thumb.setStyleSheet("background:#eef1f5;border-radius:8px;")
        d.lay.addWidget(self.d_thumb)
        self.d_info = QLabel("")
        self.d_info.setTextFormat(Qt.TextFormat.RichText)
        self.d_info.setWordWrap(True)
        d.lay.addWidget(self.d_info)
        h = QLabel("History")
        h.setObjectName("Section")
        d.lay.addWidget(h)
        self.d_hist = QListWidget()
        self.d_hist.setWordWrap(True)
        d.lay.addWidget(self.d_hist, 1)
        b = QPushButton(icon("wall", "#ffffff"), "  Open in Wall Studio")
        b.setObjectName("Dark")
        b.setMinimumHeight(44)
        b.clicked.connect(self.open_selected)
        d.lay.addWidget(b)
        dw = QWidget()
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(d)
        dw.setFixedWidth(360)
        row.addWidget(dw)
        return w

    def refresh(self) -> None:
        q = self.search.text().strip().lower()
        st = self.cb_status.currentData()
        rows = []
        for s in jobs.list_jobs():
            if q and q not in f"{s.job_no} {s.customer} {s.room}".lower():
                continue
            if st == "open" and s.status in ("Completed", "Cancelled"):
                continue
            if st and st != "open" and s.status != st:
                continue
            rows.append(s)
        self.rows = rows
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            it = QTableWidgetItem()
            it.setIcon(QIcon(_pix(s.thumb, 96)))
            self.table.setItem(r, 0, it)
            for c, v in enumerate((s.job_no, s.customer, s.room, s.walls), start=1):
                self.table.setItem(r, c, QTableWidgetItem(v))
            si = QTableWidgetItem("● " + s.status)
            si.setForeground(QColor(wl.STATUS_COLOURS.get(s.status, "#64748b")))
            self.table.setItem(r, 5, si)
            try:
                upd = datetime.fromisoformat(s.updated).strftime("%d %b %Y %H:%M")
            except Exception:
                upd = s.updated
            self.table.setItem(r, 6, QTableWidgetItem(upd))
        self.lbl_count.setText(f"{len(rows)} job{'s' if len(rows) != 1 else ''} · saved in {jobs.jobs_dir()}")
        if rows:
            self.table.selectRow(0)
        else:
            self._show_details()

    def _selected(self):
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(getattr(self, "rows", [])) else None

    def _show_details(self) -> None:
        s = self._selected()
        if s is None:
            self.d_thumb.clear()
            self.d_info.setText("<span style='color:#64748b'>No job selected. Start one with <b>New job</b>.</span>")
            self.d_hist.clear()
            return
        self.d_thumb.setPixmap(_pix(s.thumb, 320))
        try:
            j = jobs.load_job(s.folder)
        except Exception:
            return
        self.d_info.setText(
            f"<b style='font-size:12pt'>{j.job_no}</b> &nbsp; <span style='color:{wl.STATUS_COLOURS.get(j.status)}'>"
            f"● {j.status}</span><br>{j.customer or '—'} · {j.phone or ''}<br>{j.room or ''}<br>"
            f"Wall area {j.wall_area():.2f} m² · {len(wl.compute_panels(j))} panels · proof v{j.proof_version}"
            + (f"<br>Approved by {j.approved_by} {j.approved_on}" if j.approved_by else ""))
        self.d_hist.clear()
        for h in reversed(j.history[-40:]):
            try:
                t = datetime.fromisoformat(h["time"]).strftime("%d %b %H:%M")
            except Exception:
                t = h.get("time", "")
            self.d_hist.addItem(f"{t}  ·  {h.get('event', '')}")

    def new_job(self) -> None:
        self.main.set_page(1)
        self.main.studio.new_job()

    def open_selected(self) -> None:
        s = self._selected()
        if s:
            self.main.open_job(s.folder)

    def duplicate(self) -> None:
        s = self._selected()
        if not s:
            return
        k = jobs.duplicate_job(jobs.load_job(s.folder))
        self.refresh()
        self.main.statusBar().showMessage(f"{k.job_no} created as a reprint of {s.job_no}.", 5000)

    def open_folder(self) -> None:
        s = self._selected()
        if s:
            share.show_in_folder(s.folder / "job.json")

    def delete(self) -> None:
        s = self._selected()
        if not s:
            return
        if QMessageBox.question(self, "Delete job", f"Move {s.job_no} ({s.customer}) to the deleted jobs folder?\n"
                                "Nothing is erased – you can move it back from Jobs/_deleted.") \
                != QMessageBox.StandardButton.Yes:
            return
        st = self.main.studio
        if st is not None and st.job_dir == s.folder:
            st.t_save.stop()
            st.job, st.job_dir = None, None
            st.settings.remove("studio_last_job")
        try:
            jobs.delete_job(s.folder)
        except OSError as exc:
            from app.ui.worker import friendly_error
            QMessageBox.warning(self, "Delete job", "The job could not be moved. A file in it may be open in "
                                "another program.\n\n" + friendly_error(exc))
        self.refresh()

    def _on_seg(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        w = self.stack.widget(i)
        if hasattr(w, "refresh"):
            w.refresh()

    def show_library(self) -> None:
        self.seg.button(2).setChecked(True)
        self._on_seg(2)

    def show_installs(self) -> None:
        self.seg.button(1).setChecked(True)
        self._on_seg(1)

    def open_showroom(self) -> None:
        Showroom(self.main).run()


# ======================================================================
# Library
# ======================================================================
class LibraryView(QWidget):
    def __init__(self, main, page):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        c = Card()
        head = QHBoxLayout()
        t = QLabel("Design Library")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or tag…")
        self.search.textChanged.connect(lambda _t: self.refresh())
        head.addWidget(self.search, 1)
        self.cb_tag = QComboBox()
        self.cb_tag.currentIndexChanged.connect(lambda _i: self.refresh(keep_tags=True))
        head.addWidget(self.cb_tag)
        for ic, txt, fn in (("plus", " Add designs…", self.add), ("tag", " Tags…", self.edit_tags),
                            ("trash", " Remove", self.remove), ("wall", " Use in job", self.use),
                            ("play", " Showroom", lambda: Showroom(self.main).run())):
            b = QPushButton(icon(ic), txt)
            b.clicked.connect(fn)
            head.addWidget(b)
        c.lay.addLayout(head)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(220, 160))
        self.grid.setGridSize(QSize(240, 206))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSpacing(8)
        self.grid.setWordWrap(True)
        self.grid.itemDoubleClicked.connect(lambda _it: self.use())
        c.lay.addWidget(self.grid, 1)
        self.lbl = hint("")
        c.lay.addWidget(self.lbl)
        lay.addWidget(c)
        self.items: List[jobs.LibraryItem] = []
        self.refresh()

    def refresh(self, keep_tags: bool = False) -> None:
        if not keep_tags:
            cur = self.cb_tag.currentData()
            self.cb_tag.blockSignals(True)
            self.cb_tag.clear()
            self.cb_tag.addItem("All tags", "")
            for t in jobs.library_tags():
                self.cb_tag.addItem(t, t)
            k = self.cb_tag.findData(cur)
            self.cb_tag.setCurrentIndex(max(0, k))
            self.cb_tag.blockSignals(False)
        self.items = jobs.library_search(self.search.text(), self.cb_tag.currentData() or "")
        self.grid.clear()
        for it in self.items:
            th = jobs.library_thumb(it)
            li = QListWidgetItem(QIcon(_pix(th, 220)), it.name + (f"\n{', '.join(it.tags)}" if it.tags else ""))
            li.setToolTip(f"{it.name}\n{it.kind}{' · repeat ' + str(it.repeat_cm) + ' cm' if it.repeat_cm else ''}")
            self.grid.addItem(li)
        self.lbl.setText(f"{len(self.items)} design{'s' if len(self.items) != 1 else ''} · {jobs.library_dir()}")

    def _cur(self) -> Optional[jobs.LibraryItem]:
        r = self.grid.currentRow()
        return self.items[r] if 0 <= r < len(self.items) else None

    def add(self) -> None:
        exts = "*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp *.heic"
        paths, _ = QFileDialog.getOpenFileNames(self, "Add designs to the library", "", f"Images ({exts})")
        if not paths:
            return
        tags, ok = QInputDialog.getText(self, "Tags", "Tags for these designs (comma separated):")
        kind = "mural"
        if QMessageBox.question(self, "Type", "Are these repeating pattern tiles (wallpaper repeats)?\n"
                                "Yes = pattern tiles · No = murals / photos") == QMessageBox.StandardButton.Yes:
            kind = "pattern"
        rep = 0.0
        if kind == "pattern":
            rep, ok2 = QInputDialog.getDouble(self, "Repeat size", "Width of one repeat (cm):", 53.0, 1, 500, 1)
        bad = []
        for p in paths:
            try:
                with Image.open(p) as f:
                    f.load()
                jobs.library_add(p, tags=(tags or "").split(","), kind=kind, repeat_cm=rep)
            except Exception as exc:
                from app.core.imaging import load_error_text
                bad.append(load_error_text(p, exc))
        self.refresh()
        if bad:
            QMessageBox.warning(self, "Library", "These were not added:\n\n" + "\n".join(bad[:8]) +
                                (f"\n… and {len(bad) - 8} more" if len(bad) > 8 else ""))

    def edit_tags(self) -> None:
        it = self._cur()
        if not it:
            return
        txt, ok = QInputDialog.getText(self, "Tags", f"Tags for {it.name}:", text=", ".join(it.tags))
        if ok:
            it.tags = [t.strip().lower() for t in txt.split(",") if t.strip()]
            jobs.library_update(it)
            self.refresh()

    def remove(self) -> None:
        it = self._cur()
        if it and QMessageBox.question(self, "Remove", f"Remove {it.name} from the library?") == \
                QMessageBox.StandardButton.Yes:
            jobs.library_remove(it)
            self.refresh()

    def use(self) -> None:
        it = self._cur()
        if not it:
            return
        self.main.set_page(1)
        st = self.main.studio
        if it.kind == "pattern":
            st._use_pattern_file(jobs.library_dir() / it.file, (it.repeat_cm or 53) / 100, it.name)
        else:
            st._set_design(jobs.library_dir() / it.file, it.name)


class LibraryPicker(FreeAfterExec, QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Choose from the design library")
        self.resize(980, 700)
        self.chosen: Optional[jobs.LibraryItem] = None
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or tag…")
        lay.addWidget(self.search)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(200, 140))
        self.grid.setGridSize(QSize(220, 186))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.itemDoubleClicked.connect(lambda _i: self._ok())
        lay.addWidget(self.grid, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.search.textChanged.connect(lambda _t: self._fill())
        self._fill()

    def _fill(self) -> None:
        self.items = jobs.library_search(self.search.text())
        self.grid.clear()
        for it in self.items:
            self.grid.addItem(QListWidgetItem(QIcon(_pix(jobs.library_thumb(it), 200)), it.name))
        if not self.items:
            self.grid.addItem("The library is empty – add designs in Jobs → Design Library")

    def _ok(self) -> None:
        r = self.grid.currentRow()
        if 0 <= r < len(self.items):
            self.chosen = self.items[r]
            self.accept()


# ======================================================================
# Showroom (full-screen, for customers)
# ======================================================================
class Showroom(FreeAfterExec, QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("QDialog{background:#111318;} QLabel{color:#e5e7eb;background:transparent;}"
                           "QListWidget{background:#111318;border:none;color:#e5e7eb;font-size:11pt;}"
                           "QListWidget::item:selected{background:#1f2937;border-radius:10px;}"
                           "QPushButton{background:#1f2937;color:#e5e7eb;border:1px solid #374151;border-radius:8px;"
                           "padding:8px 14px;} QPushButton:hover{background:#273244;}"
                           "QComboBox,QLineEdit,QDoubleSpinBox{background:#1f2937;color:#e5e7eb;border:1px solid #374151;}")
        biz = jobs.load_business()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 18, 28, 18)
        top = QHBoxLayout()
        t = QLabel(biz.get("name") or "Wallpaper Showroom")
        t.setStyleSheet("font-size:20pt;font-weight:700;")
        top.addWidget(t)
        top.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(lambda _t: self._fill())
        top.addWidget(self.search)
        self.cb_tag = QComboBox()
        self.cb_tag.addItem("All", "")
        for tg in jobs.library_tags():
            self.cb_tag.addItem(tg.title(), tg)
        self.cb_tag.currentIndexChanged.connect(lambda _i: self._fill())
        top.addWidget(self.cb_tag)
        bx = QPushButton("✕  Exit (Esc)")
        bx.clicked.connect(self.accept)
        top.addWidget(bx)
        lay.addLayout(top)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(340, 240))
        self.grid.setGridSize(QSize(370, 290))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.itemClicked.connect(lambda _i: self._open(self.grid.currentRow()))
        self.stack.addWidget(self.grid)
        det = QWidget()
        dl = QVBoxLayout(det)
        dr = QHBoxLayout()
        bb = QPushButton("←  All designs")
        bb.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        dr.addWidget(bb)
        self.d_name = QLabel("")
        self.d_name.setStyleSheet("font-size:16pt;font-weight:700;")
        dr.addWidget(self.d_name, 1)
        dr.addWidget(QLabel("Room"))
        self.cb_scene = QComboBox()
        for k, v in mk.SCENES.items():
            self.cb_scene.addItem(v, k)
        self.cb_scene.addItem("Design only", "")
        self.cb_scene.currentIndexChanged.connect(lambda _i: self._render())
        dr.addWidget(self.cb_scene)
        dr.addWidget(QLabel("Wall"))
        self.sp_w = QDoubleSpinBox()
        self.sp_w.setRange(1, 20)
        self.sp_w.setValue(4.0)
        self.sp_w.setSuffix(" m")
        self.sp_h = QDoubleSpinBox()
        self.sp_h.setRange(1, 6)
        self.sp_h.setValue(2.6)
        self.sp_h.setSuffix(" m")
        for sp in (self.sp_w, self.sp_h):
            sp.valueChanged.connect(lambda _v: self._t.start())
            dr.addWidget(sp)
        b_prev = QPushButton("◀")
        b_prev.clicked.connect(lambda: self._step(-1))
        b_next = QPushButton("▶")
        b_next.clicked.connect(lambda: self._step(1))
        dr.addWidget(b_prev)
        dr.addWidget(b_next)
        b_use = QPushButton("Start a job with this design")
        b_use.clicked.connect(self._use)
        dr.addWidget(b_use)
        dl.addLayout(dr)
        self.d_img = QLabel()
        self.d_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(self.d_img, 1)
        self.stack.addWidget(det)
        self._t = QTimer(self, singleShot=True, interval=250, timeout=self._render)
        self.cur = -1
        for seq, fn in (("Esc", self.accept), ("Left", lambda: self._step(-1)), ("Right", lambda: self._step(1))):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self._fill()

    def run(self) -> int:
        self.showFullScreen()
        return self.exec()

    def _fill(self) -> None:
        self.items = jobs.library_search(self.search.text(), self.cb_tag.currentData() or "")
        self.grid.clear()
        for it in self.items:
            self.grid.addItem(QListWidgetItem(QIcon(_pix(jobs.library_thumb(it, 640), 340)), it.name))

    def _open(self, i: int) -> None:
        if not 0 <= i < len(self.items):
            return
        self.cur = i
        self.d_name.setText(self.items[i].name)
        self.stack.setCurrentIndex(1)
        self._render()

    def _step(self, d: int) -> None:
        if self.stack.currentIndex() == 1 and self.items:
            self._open((self.cur + d) % len(self.items))

    def _render(self) -> None:
        if not 0 <= self.cur < len(self.items):
            return
        it = self.items[self.cur]
        with Image.open(jobs.library_dir() / it.file) as f:
            f.draft("RGB", (2400, 2400))
            img = ImageOps.exif_transpose(f).convert("RGB")
            img.thumbnail((2400, 2400))
        scene = self.cb_scene.currentData()
        box = self.d_img.size()
        if scene:
            w = wl.Wall(width=self.sp_w.value(), height=self.sp_h.value())
            wall_w, wall_h = w.width, w.height
            if it.kind == "pattern":
                from app.core.pattern import PatternSource, PatternSpec
                src = PatternSource(img, PatternSpec(repeat_w=(it.repeat_cm or 53) / 100))
                art = src.render(0, 0, wall_w, wall_h, 1600, int(1600 * wall_h / wall_w))
            else:
                art = ImageOps.fit(img, (1600, int(1600 * wall_h / wall_w)), Image.Resampling.LANCZOS)
            ppm = max(80.0, min(240.0, box.width() / (wall_w + 2 * max(0.8, wall_w * 0.16))))
            img = mk.render_room([w], art, scene, ppm=ppm)
        img.thumbnail((max(200, box.width()), max(200, box.height())))
        self.d_img.setPixmap(QPixmap.fromImage(pil_to_qimage(img)))

    def _use(self) -> None:
        if not 0 <= self.cur < len(self.items):
            return
        it = self.items[self.cur]
        self.accept()
        self.main.set_page(1)
        st = self.main.studio
        st.new_job()
        st.job.walls[0].width, st.job.walls[0].height = self.sp_w.value(), self.sp_h.value()
        if it.kind == "pattern":
            st._use_pattern_file(jobs.library_dir() / it.file, (it.repeat_cm or 53) / 100, it.name)
        else:
            st._set_design(jobs.library_dir() / it.file, it.name)
