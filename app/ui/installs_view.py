"""Installs: fitting dates, WhatsApp reminders, installed photos and before/after posts."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps
from PySide6.QtCore import QDate, QSize, Qt, QTime
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDateEdit, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                               QTimeEdit, QVBoxLayout, QWidget)

from app.core import jobs
from app.core import posts
from app.core import production as pr
from app.core import wall as wl
from app.ui import share
from app.ui.qtutil import Card, hint, icon, pil_to_qimage


class InstallsView(QWidget):
    def __init__(self, main, page):
        super().__init__()
        self.main = main
        self.page = page
        self.job: Optional[wl.Job] = None
        self.folder: Optional[Path] = None
        self.rows: List = []
        self.post_img: Optional[Image.Image] = None
        self._loading = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)

        c = Card()
        head = QHBoxLayout()
        t = QLabel("Installations")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch()
        self.lbl_today = hint("")
        head.addWidget(self.lbl_today)
        c.lay.addLayout(head)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["When", "Time", "Job", "Customer", "Phone", "Room", "Installer",
                                              "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.folder and self.main.open_job(self.folder))
        c.lay.addWidget(self.table, 1)
        c.lay.addWidget(hint("Booked fittings first (soonest at the top), then approved jobs that still need a date. "
                             "Double-click to open the job."))
        row.addWidget(c, 1)

        # ---- details ----
        d = Card()
        inner = QWidget()
        inner.setObjectName("LeftInner")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)
        self.lbl_job = QLabel("Choose a job")
        self.lbl_job.setObjectName("CardTitle")
        self.lbl_job.setWordWrap(True)
        lay.addWidget(self.lbl_job)
        f = QFormLayout()
        f.setVerticalSpacing(8)
        self.ed_date = QDateEdit()
        self.ed_date.setCalendarPopup(True)
        self.ed_date.setDisplayFormat("ddd dd MMM yyyy")
        self.ed_time = QTimeEdit()
        self.ed_time.setDisplayFormat("HH:mm")
        self.ed_installer = QLineEdit()
        self.ed_installer.setPlaceholderText("Who is fitting it")
        dr = QHBoxLayout()
        dr.addWidget(self.ed_date, 1)
        dr.addWidget(self.ed_time)
        f.addRow("Fitting", self._wrap(dr))
        f.addRow("Installer", self.ed_installer)
        lay.addLayout(f)
        sr = QHBoxLayout()
        b_save = QPushButton(icon("calendar"), " Save date")
        b_save.clicked.connect(self.save_date)
        sr.addWidget(b_save)
        b_clear = QPushButton("No date")
        b_clear.clicked.connect(self.clear_date)
        sr.addWidget(b_clear)
        sr.addStretch()
        lay.addLayout(sr)

        s1 = QLabel("WhatsApp reminder")
        s1.setObjectName("PaneTitle")
        lay.addWidget(s1)
        self.ed_msg = QPlainTextEdit()
        self.ed_msg.setMinimumHeight(110)
        lay.addWidget(self.ed_msg)
        wr = QHBoxLayout()
        b_wa = QPushButton(icon("whatsapp", "#1f9d55"), " Send on WhatsApp")
        b_wa.clicked.connect(self.send_reminder)
        wr.addWidget(b_wa)
        b_cp = QPushButton(icon("copy"), " Copy")
        b_cp.clicked.connect(lambda: QApplication.clipboard().setText(self.ed_msg.toPlainText()))
        wr.addWidget(b_cp)
        wr.addStretch()
        lay.addLayout(wr)

        s2 = QLabel("Finished job")
        s2.setObjectName("PaneTitle")
        lay.addWidget(s2)
        self.photos = QListWidget()
        self.photos.setViewMode(QListWidget.ViewMode.IconMode)
        self.photos.setIconSize(QSize(96, 72))
        self.photos.setGridSize(QSize(108, 84))
        self.photos.setFixedHeight(100)
        self.photos.setMovement(QListWidget.Movement.Static)
        lay.addWidget(self.photos)
        pr_ = QHBoxLayout()
        b_add = QPushButton(icon("camera"), " Add photos…")
        b_add.clicked.connect(self.add_photos)
        pr_.addWidget(b_add)
        b_done = QPushButton(icon("check"), " Mark installed")
        b_done.clicked.connect(self.mark_installed)
        pr_.addWidget(b_done)
        pr_.addStretch()
        lay.addLayout(pr_)

        s3 = QLabel("Before / after post")
        s3.setObjectName("PaneTitle")
        lay.addWidget(s3)
        pf = QFormLayout()
        self.cb_size = QComboBox()
        for k, v in posts.SIZE_NAMES.items():
            self.cb_size.addItem(v, k)
        pf.addRow("Size", self.cb_size)
        self.cb_before = QComboBox()
        pf.addRow("Before", self.cb_before)
        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText("Optional title, e.g. ‘Living room mural’")
        pf.addRow("Title", self.ed_title)
        lay.addLayout(pf)
        b_make = QPushButton(icon("sparkle", "#ffffff"), "  Make Post")
        b_make.setObjectName("AIButton")
        b_make.clicked.connect(self.make_post)
        lay.addWidget(b_make)
        self.post_view = QLabel()
        self.post_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.post_view.setStyleSheet("background:#eef1f5;border-radius:8px;")
        self.post_view.setMinimumHeight(60)
        lay.addWidget(self.post_view)
        self.ed_caption = QPlainTextEdit()
        self.ed_caption.setMaximumHeight(90)
        lay.addWidget(self.ed_caption)
        orow = QHBoxLayout()
        b_cpp = QPushButton(icon("copy"), " Copy picture")
        b_cpp.clicked.connect(self.copy_post)
        orow.addWidget(b_cpp)
        b_cpc = QPushButton(" Copy caption")
        b_cpc.clicked.connect(lambda: QApplication.clipboard().setText(self.ed_caption.toPlainText()))
        orow.addWidget(b_cpc)
        b_of = QPushButton(icon("folder_open"), "")
        b_of.setToolTip("Open the posts folder")
        b_of.clicked.connect(self.open_posts)
        orow.addWidget(b_of)
        orow.addStretch()
        lay.addLayout(orow)
        lay.addStretch()
        from PySide6.QtWidgets import QComboBox as _CB
        for cb in inner.findChildren(_CB):
            cb.setSizeAdjustPolicy(_CB.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(10)
        self.ed_date.setMinimumWidth(150)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setWidget(inner)
        d.lay.addWidget(sc)
        dw = QWidget()
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(d)
        dw.setFixedWidth(430)
        self.details = inner
        row.addWidget(dw)
        self.details.setEnabled(False)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        keep = self.folder
        dated, to_book = posts.upcoming(jobs.list_jobs())
        today = date.today()
        self.lbl_today.setText(f"Today {today:%a %d %b %Y}")
        self.rows = [s for _d, s in dated] + to_book
        self.table.setRowCount(len(self.rows))
        for r, s in enumerate(self.rows):
            if s.install_date:
                d = datetime.strptime(s.install_date, "%Y-%m-%d").date()
                delta = (d - today).days
                when = ("Today" if delta == 0 else "Tomorrow" if delta == 1 else
                        f"Overdue ({d:%d %b})" if delta < 0 else f"{d:%a %d %b}")
            else:
                when = "Needs a date"
            vals = (when, s.install_time, s.job_no, s.customer, s.phone, s.room, s.installer, s.status)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v or "")
                if c == 0:
                    it.setForeground(QColor("#dc2626" if when.startswith("Overdue") else
                                            "#d97706" if when in ("Today", "Tomorrow") else
                                            "#64748b" if when == "Needs a date" else "#0f172a"))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if c == 7:
                    it.setForeground(QColor(wl.STATUS_COLOURS.get(v, "#64748b")))
                self.table.setItem(r, c, it)
        k = next((i for i, s in enumerate(self.rows) if s.folder == keep), 0 if self.rows else -1)
        if k >= 0:
            self.table.selectRow(k)
        else:
            self._show(None)

    def _on_select(self) -> None:
        r = self.table.currentRow()
        self._show(self.rows[r].folder if 0 <= r < len(self.rows) else None)

    def _studio_open(self, folder: Path) -> bool:
        st = self.main.studio
        return st is not None and st.job is not None and st.job_dir is not None and \
            Path(st.job_dir).resolve() == Path(folder).resolve()

    def _show(self, folder: Optional[Path]) -> None:
        self.details.setEnabled(folder is not None)
        self.folder = folder
        if folder is None:
            self.job = None
            self.lbl_job.setText("Choose a job")
            return
        if self._studio_open(folder):
            self.main.studio.save_now()
        try:
            self.job = jobs.load_job(folder)
        except Exception as exc:
            self.lbl_job.setText(f"Could not open the job: {exc}")
            return
        j = self.job
        self._loading = True
        self.lbl_job.setText(f"{j.job_no} · {j.customer or 'customer'}" + (f" · {j.room}" if j.room else ""))
        d = QDate.fromString(j.install_date, "yyyy-MM-dd") if j.install_date else QDate.currentDate().addDays(1)
        self.ed_date.setDate(d)
        t = QTime.fromString(j.install_time, "HH:mm") if j.install_time else QTime(10, 0)
        self.ed_time.setTime(t)
        self.ed_installer.setText(j.installer)
        self.ed_msg.setPlainText(posts.reminder_text(self._preview_job(), jobs.load_business()))
        self.ed_caption.setPlainText(posts.caption_text(j, jobs.load_business()))
        self._fill_photos()
        self.cb_before.clear()
        w0 = j.walls[0]
        if w0.photo and (folder / w0.photo).is_file():
            self.cb_before.addItem("Survey photo of the wall", folder / w0.photo)
        for rel in j.installed_photos[:-1]:
            self.cb_before.addItem(f"Photo {Path(rel).name}", folder / rel)
        self.cb_before.addItem("No before picture (after only)", None)
        self.post_view.clear()
        self.post_view.setMinimumHeight(60)
        self.post_img = None
        self._loading = False

    def _preview_job(self) -> wl.Job:
        j = self.job.copy()
        j.install_date = self.ed_date.date().toString("yyyy-MM-dd")
        j.install_time = self.ed_time.time().toString("HH:mm")
        j.installer = self.ed_installer.text().strip()
        return j

    def _fill_photos(self) -> None:
        self.photos.clear()
        for rel in self.job.installed_photos:
            p = self.folder / rel
            if not p.is_file():
                continue
            try:
                with Image.open(p) as im:
                    im.draft("RGB", (240, 180))
                    t = ImageOps.exif_transpose(im).convert("RGB")
                    t.thumbnail((192, 144))
                pm = QPixmap.fromImage(pil_to_qimage(t))
                pm.setDevicePixelRatio(2)
                it = QListWidgetItem(QIcon(pm), "")
                it.setData(Qt.ItemDataRole.UserRole, rel)
                it.setToolTip(Path(rel).name)
                self.photos.addItem(it)
            except Exception:
                continue
        if self.photos.count():
            self.photos.setCurrentRow(self.photos.count() - 1)

    def _save(self, event: str) -> None:
        self.job.log(event)
        jobs.save_job(self.job)
        if self._studio_open(self.folder):
            self.main.studio.load_job_folder(self.folder)

    # ------------------------------------------------------------------
    def save_date(self) -> None:
        if self.job is None:
            return
        j = self.job
        j.install_date = self.ed_date.date().toString("yyyy-MM-dd")
        j.install_time = self.ed_time.time().toString("HH:mm")
        j.installer = self.ed_installer.text().strip()
        day, dt = posts.nice_date(j.install_date)
        self._save(f"Fitting booked: {day} {dt} {j.install_time}" + (f" ({j.installer})" if j.installer else ""))
        self.ed_msg.setPlainText(posts.reminder_text(j, jobs.load_business()))
        self.refresh()

    def clear_date(self) -> None:
        if self.job is None:
            return
        self.job.install_date = self.job.install_time = ""
        self._save("Fitting date removed")
        self.refresh()

    def send_reminder(self) -> None:
        if self.job is None:
            return
        if not self.job.phone:
            QMessageBox.information(self, "WhatsApp", "This job has no phone number. Add it in Wall Studio → Job "
                                                      "& Customer, or copy the message and send it yourself.")
            return
        share.open_whatsapp(self.main.wa_target, self.job.phone, self.ed_msg.toPlainText())
        self.job.log("WhatsApp reminder opened")
        jobs.save_job(self.job)

    def add_photos(self) -> None:
        if self.job is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Photos of the finished wall", "",
                                                "Photos (*.jpg *.jpeg *.png *.heic *.webp)")
        if not paths:
            return
        d = self.folder / "installed"
        d.mkdir(exist_ok=True)
        for p in paths:
            src = Path(p)
            name = f"{len(self.job.installed_photos) + 1:02d}_{pr.safe_name(src.stem)}.jpg"
            try:
                with Image.open(src) as im:
                    img = ImageOps.exif_transpose(im).convert("RGB")
                img.thumbnail((3000, 3000))
                img.save(d / name, "JPEG", quality=92)
            except Exception as exc:
                QMessageBox.warning(self, "Photos", f"Could not add {src.name}:\n{exc}")
                continue
            self.job.installed_photos.append(f"installed/{name}")
        self._save(f"{len(paths)} finished photo(s) added")
        self._show(self.folder)

    def mark_installed(self) -> None:
        if self.job is None:
            return
        if self.job.status not in ("Completed",):
            self.job.set_status("Installed")
        if not self.job.install_date:
            self.job.install_date = date.today().isoformat()
        self._save("Marked as installed")
        self.refresh()

    def _after_image(self) -> Optional[Image.Image]:
        it = self.photos.currentItem()
        rel = it.data(Qt.ItemDataRole.UserRole) if it else (self.job.installed_photos[-1]
                                                             if self.job.installed_photos else None)
        if rel and (self.folder / rel).is_file():
            with Image.open(self.folder / rel) as im:
                return ImageOps.exif_transpose(im).convert("RGB")
        if self.job.mockup_file and (self.folder / self.job.mockup_file).is_file():
            with Image.open(self.folder / self.job.mockup_file) as im:
                return im.convert("RGB")
        return None

    def make_post(self) -> None:
        if self.job is None:
            return
        after = self._after_image()
        if after is None:
            QMessageBox.information(self, "Post", "Add a photo of the finished wall first (or save a room mockup "
                                                  "in Wall Studio).")
            return
        before = None
        bp = self.cb_before.currentData()
        if bp and Path(bp).is_file():
            with Image.open(bp) as im:
                before = ImageOps.exif_transpose(im).convert("RGB")
        size = self.cb_size.currentData()
        img = posts.make_post(after, jobs.load_business(), size, before, self.ed_title.text().strip())
        d = self.folder / "posts"
        d.mkdir(exist_ok=True)
        out = d / f"{pr.safe_name(self.job.job_no)}_{size}_{datetime.now():%H%M%S}.jpg"
        img.save(out, "JPEG", quality=92)
        self.post_img = img
        prev = img.copy()
        prev.thumbnail((780, 520))
        pm = QPixmap.fromImage(pil_to_qimage(prev))
        pm.setDevicePixelRatio(2)
        self.post_view.setPixmap(pm)
        self.post_view.setMinimumHeight(prev.height // 2 + 8)
        self.job.log(f"Post made: {out.name}")
        jobs.save_job(self.job)

    def copy_post(self) -> None:
        if self.post_img is None:
            return
        share.copy_to_clipboard(pil_to_qimage(self.post_img))
        self.main.statusBar().showMessage("Post copied – paste it into WhatsApp, Instagram or Facebook.", 5000)

    def open_posts(self) -> None:
        if self.folder is not None:
            d = self.folder / "posts"
            d.mkdir(exist_ok=True)
            share.show_in_folder(d)
