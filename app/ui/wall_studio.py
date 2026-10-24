"""
Wall Studio – professional wallpaper / mural jobs.

  1 Job & Customer  │  Wall plan (design, doors/windows/furniture,      │ Checks
  2 Wall & items    │  panels, seams, sizes – drag to edit)             │ Room view
  3 Design          │                                                   │ Areas & rolls
  4 Panels & print  │  5 Proof & Print: Proof · Room · Installer · Print · WhatsApp
"""
from __future__ import annotations

import traceback
from dataclasses import replace
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps
from PySide6.QtCore import QEvent, QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QToolButton, QVBoxLayout, QWidget)

from app.core import colour as col
from app.core import imaging as im
from app.core import jobs
from app.core import mockup as mk
from app.core import preflight as pf
from app.core import production as pr
from app.core import units as un
from app.core import wall as wl
from app.ui import share
from app.ui.qtutil import Card, ElidedLabel, hint, icon, pil_to_qimage, section
from app.ui.wall_canvas import WallCanvas

SLATE = "#334155"
WHITE = "#ffffff"
SPIN_UNITS = [("m", "m"), ("cm", "cm"), ("feet", "ft"), ("inches", "in")]
LEVEL_ICON = {"ok": ("check", "#16a34a"), "info": ("help", "#2563eb"), "warn": ("warning", "#d97706"),
              "error": ("warning", "#dc2626")}


def load_design_image(path: Path) -> Image.Image:
    # one copy of the picture, not three (a 250 MP mural is 750 MB a copy)
    img = Image.open(path)
    try:
        img.load()
    finally:
        if img.fp is not None:              # loaded: let the file go (Windows locks open files)
            img.fp.close()
            img.fp = None
    icc = img.info.get("icc_profile")
    ImageOps.exif_transpose(img, in_place=True)
    alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    want = "RGBA" if alpha else "RGB"
    if img.mode != want:
        img = img.convert(want)
    return col.to_srgb(img, icc)


class _RiskSignals(QObject):
    done = Signal(int, object, object)


class RiskJob(QRunnable):
    """Seam risk (detail + faces) in the background."""

    def __init__(self, gen, source, job):
        super().__init__()
        self.gen, self.source, self.job = gen, source, job
        self.signals = _RiskSignals()

    def run(self):
        try:
            from app.core import detect
            ppm = min(220.0, 3000.0 / max(self.job.art_width, 0.1))
            img = pr.render_area(self.source, self.job, 0, 0, self.job.art_width, self.job.art_height, ppm, fast=True)
            risk, faces = detect.seam_risk(img, self.job.art_width)
            boxes = [(f.box[0] / ppm, f.box[1] / ppm, (f.box[0] + f.box[2]) / ppm, (f.box[1] + f.box[3]) / ppm)
                     for f in faces]
            self.signals.done.emit(self.gen, risk, boxes)
        except Exception:
            traceback.print_exc()
            self.signals.done.emit(self.gen, None, [])


def _spin(lo, hi, dec=2, suffix="", step=0.1):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class WallStudioPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.settings = QSettings("ImageResizeShare", "ImageResizeShare")
        self.job: Optional[wl.Job] = None
        self.job_dir: Optional[Path] = None
        self.design_img: Optional[Image.Image] = None
        self.tile_img: Optional[Image.Image] = None
        self.source = None
        self.risk = None
        self.faces = []
        self.gamut_fraction: Optional[float] = None
        self.checks: List[pf.Check] = []
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._gen = 0
        self._loading = False
        self.pool = QThreadPool.globalInstance()
        self._risk_jobs = set()

        self.t_render = QTimer(self, singleShot=True, interval=90, timeout=self._render)
        self.t_risk = QTimer(self, singleShot=True, interval=700, timeout=self._start_risk)
        self.t_save = QTimer(self, singleShot=True, interval=1500, timeout=self.save_now)
        self.t_room = QTimer(self, singleShot=True, interval=500, timeout=self._update_room_thumb)

        self._build()

    # ==================================================================
    # Layout
    # ==================================================================
    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(14)
        left_inner = QWidget()
        left_inner.setObjectName("LeftInner")
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(0, 0, 6, 0)
        left.setSpacing(14)
        left.addWidget(self._job_card())
        left.addWidget(self._wall_card())
        left.addWidget(self._design_card())
        left.addWidget(self._panels_card())
        left.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left_inner)
        scroll.setFixedWidth(386)
        for cb in left_inner.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
        self.cb_wunit.setMinimumContentsLength(3)
        for sp in (self.sp_ww, self.sp_wh):
            sp.setMinimumWidth(96)
        outer.addWidget(scroll)

        mid = QVBoxLayout()
        mid.setSpacing(14)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(self._plan_card(), 1)
        right = QVBoxLayout()
        right.setSpacing(14)
        right.setContentsMargins(0, 0, 4, 0)
        right.addWidget(self._checks_card(), 3)
        right.addWidget(self._room_card(), 2)
        right.addWidget(self._areas_card(), 0)
        rw = QWidget()
        rw.setObjectName("LeftInner")
        rw.setLayout(right)
        rsc = QScrollArea()             # on a short screen the right column scrolls
        rsc.setWidgetResizable(True)
        rsc.setFrameShape(QFrame.Shape.NoFrame)
        rsc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rsc.setWidget(rw)
        rsc.setMinimumWidth(262)
        rsc.setMaximumWidth(306)
        rsc.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        top.addWidget(rsc)
        mid.addLayout(top, 1)
        mid.addWidget(self._tiles_card())
        outer.addLayout(mid, 1)

    def _card(self, title: str, extra: Optional[QWidget] = None) -> Card:
        c = Card()
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch()
        if extra is not None:
            head.addWidget(extra)
        c.lay.addLayout(head)
        return c

    def _more_button(self, actions) -> QToolButton:
        b = QToolButton()
        b.setObjectName("IconBtn")
        b.setIcon(icon("more", "#475569"))
        b.setIconSize(QSize(18, 18))
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        b.setStyleSheet("QToolButton::menu-indicator{image:none;width:0px;}")
        m = QMenu(b)
        for a in actions:
            if a is None:
                m.addSeparator()
            else:
                m.addAction(*a)
        b.setMenu(m)
        return b

    # ---------------- 1. job ----------------
    def _job_card(self) -> QWidget:
        more = self._more_button([("New job", self.new_job), ("Open a job…", lambda: self.main.set_page(2)),
                                  None, ("Duplicate for a reprint", self.duplicate_job),
                                  ("Open the job folder", self.open_folder), ("Save now", self.save_now)])
        c = self._card("1.  Job & Customer", more)
        row = QHBoxLayout()
        self.lbl_job = QLabel("")
        self.lbl_job.setObjectName("PaneTitle")
        row.addWidget(self.lbl_job)
        row.addStretch()
        self.cb_status = QComboBox()
        for s in wl.STATUSES:
            self.cb_status.addItem(s)
        self.cb_status.setToolTip("Job status")
        self.cb_status.currentTextChanged.connect(self._on_status)
        row.addWidget(self.cb_status)
        c.lay.addLayout(row)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.ed_customer, self.ed_phone, self.ed_room = QLineEdit(), QLineEdit(), QLineEdit()
        self.ed_customer.setPlaceholderText("Customer name")
        self.ed_phone.setPlaceholderText("Phone / WhatsApp")
        self.ed_room.setPlaceholderText("Room (e.g. Living room)")
        g.addWidget(self.ed_customer, 0, 0, 1, 2)
        g.addWidget(self.ed_phone, 1, 0)
        g.addWidget(self.ed_room, 1, 1)
        for ed, attr in ((self.ed_customer, "customer"), (self.ed_phone, "phone"), (self.ed_room, "room")):
            ed.editingFinished.connect(lambda ed=ed, attr=attr: self._set_field(attr, ed.text().strip()))
        c.lay.addLayout(g)
        return c

    # ---------------- 2. wall ----------------
    def _wall_card(self) -> QWidget:
        more = self._more_button([("Add a wall (wraps round a corner)", self.add_wall),
                                  ("Remove this wall", self.remove_wall), None,
                                  ("Rename this wall…", self.rename_wall)])
        c = self._card("2.  Wall & Items", more)
        self.wall_tabs = QHBoxLayout()
        self.wall_tabs.setSpacing(6)
        self.wall_group = QButtonGroup(self)
        self.wall_group.setExclusive(True)
        self.wall_group.idClicked.connect(self._select_wall)
        c.lay.addLayout(self.wall_tabs)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(5)
        for i, t in enumerate(("Width", "Height", "Unit")):
            l_ = QLabel(t)
            l_.setObjectName("FieldLabel")
            g.addWidget(l_, 0, i)
        self.sp_ww = _spin(0.1, 100, 2)
        self.sp_wh = _spin(0.1, 30, 2)
        for sp in (self.sp_ww, self.sp_wh):
            sp.setMinimumHeight(38)
        self.cb_wunit = QComboBox()
        for t, v in SPIN_UNITS:
            self.cb_wunit.addItem(t, v)
        g.addWidget(self.sp_ww, 1, 0)
        g.addWidget(self.sp_wh, 1, 1)
        g.addWidget(self.cb_wunit, 1, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        c.lay.addLayout(g)
        self.lbl_wall_ft = hint("")
        c.lay.addWidget(self.lbl_wall_ft)
        self.btn_shape = QPushButton(icon("wall"), " Shape: Rectangle")
        self.btn_shape.setToolTip("Sloped ceiling, gable end, staircase or arched top")
        self.btn_shape.clicked.connect(self.open_shape)
        c.lay.addWidget(self.btn_shape)
        self.sp_ww.valueChanged.connect(lambda v: self._set_wall_size(width=v))
        self.sp_wh.valueChanged.connect(lambda v: self._set_wall_size(height=v))
        self.cb_wunit.currentIndexChanged.connect(self._on_unit)
        self.row_corner = QWidget()
        rc = QHBoxLayout(self.row_corner)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.addWidget(QLabel("Corner to next wall"))
        self.cb_corner = QComboBox()
        for t, v in (("Inside corner", "inside"), ("Outside corner", "outside"), ("Flat (same wall)", "flat")):
            self.cb_corner.addItem(t, v)
        self.cb_corner.currentIndexChanged.connect(self._on_corner)
        rc.addWidget(self.cb_corner, 1)
        c.lay.addWidget(self.row_corner)
        self.btn_measure = QPushButton(icon("camera", WHITE), "  Measure from photo")
        self.btn_measure.setObjectName("AIButton")
        self.btn_measure.setIconSize(QSize(20, 20))
        self.btn_measure.setMinimumHeight(42)
        self.btn_measure.setToolTip("Straighten a phone photo of the wall, then measure doors, windows and furniture")
        self.btn_measure.clicked.connect(self.open_measure)
        c.lay.addWidget(self.btn_measure)
        ih = QHBoxLayout()
        ih.addWidget(section("Doors, windows & furniture"))
        ih.addStretch()
        b_add = QToolButton()
        b_add.setIcon(icon("plus"))
        b_add.setText(" Add")
        b_add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        b_add.setStyleSheet("QToolButton::menu-indicator{image:none;width:0px;}")
        am = QMenu(b_add)
        for k, (label, _f, _c) in wl.OBSTACLE_KINDS.items():
            am.addAction(label, lambda k=k: self.add_item(k))
        b_add.setMenu(am)
        ih.addWidget(b_add)
        c.lay.addLayout(ih)
        self.items = QListWidget()
        self.items.setMaximumHeight(118)
        self.items.currentRowChanged.connect(self._on_item_row)
        c.lay.addWidget(self.items)
        self.item_form = QWidget()
        ig = QGridLayout(self.item_form)
        ig.setContentsMargins(0, 0, 0, 0)
        ig.setHorizontalSpacing(6)
        ig.setVerticalSpacing(4)
        self.it_spins = {}
        for i, (key, lab) in enumerate((("x", "From left"), ("y", "From floor"), ("w", "Width"), ("h", "Height"))):
            l_ = QLabel(lab)
            l_.setObjectName("Hint")
            sp = _spin(0, 100, 2)
            sp.valueChanged.connect(lambda v, key=key: self._set_item(key, v))
            ig.addWidget(l_, 0 if i < 2 else 2, i % 2)
            ig.addWidget(sp, 1 if i < 2 else 3, i % 2)
            self.it_spins[key] = sp
        self.chk_front = QCheckBox("In front of the wall")
        self.chk_front.toggled.connect(lambda v: self._set_item("in_front", v))
        self.chk_blank = QCheckBox("Leave unprinted")
        self.chk_blank.setToolTip("Big windows / openings: no ink there in the panel files (5 cm margin kept)")
        self.chk_blank.toggled.connect(lambda v: self._set_item("blank_print", v))
        ig.addWidget(self.chk_front, 4, 0)
        ig.addWidget(self.chk_blank, 4, 1)
        b_del = QPushButton(icon("trash"), " Remove item")
        b_del.clicked.connect(self.remove_item)
        ig.addWidget(b_del, 5, 0, 1, 2)
        c.lay.addWidget(self.item_form)
        vr = QHBoxLayout()
        vr.addWidget(QLabel("Viewing distance"))
        self.sp_view = _spin(0.3, 20, 1, " m", 0.5)
        self.sp_view.setToolTip("How close people look at the wall – sets the resolution needed")
        self.sp_view.valueChanged.connect(lambda v: self._set_field("view_distance", v))
        vr.addWidget(self.sp_view)
        vr.addStretch()
        c.lay.addLayout(vr)
        return c

    # ---------------- 3. design ----------------
    def _design_card(self) -> QWidget:
        more = self._more_button([("Choose a picture…", self.choose_design),
                                  ("Use the Image Editor picture", self.from_editor),
                                  ("From the design library…", self.from_library),
                                  ("Repeating pattern…", self.open_pattern), None,
                                  ("Expand to fit the wall (no cropping)…", self.expand_design),
                                  ("Text && logo on the design…", self.open_layers), None,
                                  ("Online creative upscale (Replicate)…", self.cloud_upscale),
                                  ("Add this design to the library", self.add_to_library)])
        c = self._card("3.  Design", more)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.thumb = QLabel()
        self.thumb.setFixedSize(92, 70)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background:#eef1f5;border-radius:6px;")
        row.addWidget(self.thumb)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.lbl_design = ElidedLabel("No design yet")
        self.lbl_design.setObjectName("FileName")
        self.lbl_design_px = ElidedLabel("")
        self.lbl_design_px.setObjectName("FileMeta")
        self.lbl_ppi = QLabel("")
        info.addWidget(self.lbl_design)
        info.addWidget(self.lbl_design_px)
        info.addWidget(self.lbl_ppi)
        info.addStretch()
        row.addLayout(info, 1)
        c.lay.addLayout(row)
        br = QHBoxLayout()
        br.setSpacing(6)
        b1 = QPushButton(icon("folder_fill", "#1e293b"), " Choose…")
        b1.clicked.connect(self.choose_design)
        b2 = QPushButton(icon("books"), " Library")
        b2.clicked.connect(self.from_library)
        b3 = QPushButton(icon("home"), " Editor")
        b3.setToolTip("Use the picture from the Image Editor")
        b3.clicked.connect(self.from_editor)
        for b in (b1, b2, b3):
            br.addWidget(b)
        c.lay.addLayout(br)
        pl = QGridLayout()
        pl.setHorizontalSpacing(8)
        l1 = QLabel("Placement")
        l1.setObjectName("FieldLabel")
        pl.addWidget(l1, 0, 0)
        self.cb_place = QComboBox()
        for t, v in (("Fill the wall", "fill"), ("Fit width", "fit_width"), ("Fit height", "fit_height"),
                     ("Custom (drag / Ctrl+wheel)", "custom")):
            self.cb_place.addItem(t, v)
        self.cb_place.currentIndexChanged.connect(self._on_place)
        pl.addWidget(self.cb_place, 0, 1)
        l2 = QLabel("Keep")
        l2.setObjectName("FieldLabel")
        pl.addWidget(l2, 1, 0)
        self.cb_anchor = QComboBox()
        for t, v in (("Centre", ("center", "center")), ("Bottom (horizon)", ("center", "bottom")),
                     ("Top", ("center", "top")), ("Left", ("left", "center")), ("Right", ("right", "center"))):
            self.cb_anchor.addItem(t, v)
        self.cb_anchor.currentIndexChanged.connect(self._on_anchor)
        pl.addWidget(self.cb_anchor, 1, 1)
        pl.setColumnStretch(1, 1)
        c.lay.addLayout(pl)
        fr = QHBoxLayout()
        self.chk_flip = QCheckBox("Mirror")
        self.chk_flip.toggled.connect(lambda v: self._set_placement(flip_h=v))
        fr.addWidget(self.chk_flip)
        fr.addStretch()
        fr.addWidget(QLabel("Background"))
        self.btn_bg = QToolButton()
        self.btn_bg.setFixedSize(28, 28)
        self.btn_bg.setToolTip("Colour shown where the design does not reach")
        self.btn_bg.clicked.connect(self._pick_bg)
        fr.addWidget(self.btn_bg)
        c.lay.addLayout(fr)
        xr = QHBoxLayout()
        xr.setSpacing(6)
        self.btn_expand = QPushButton(icon("fit"), " Expand to fit")
        self.btn_expand.setToolTip("Add picture at the edges so the design fits the wall without cropping")
        self.btn_expand.clicked.connect(self.expand_design)
        self.btn_layers = QPushButton(icon("doc"), " Text && logo")
        self.btn_layers.setToolTip("Add a name, slogan or logo on the wall")
        self.btn_layers.clicked.connect(self.open_layers)
        xr.addWidget(self.btn_expand)
        xr.addWidget(self.btn_layers)
        c.lay.addLayout(xr)
        self.btn_up = QPushButton(icon("sparkle", WHITE), "  AI Upscale for this wall")
        self.btn_up.setObjectName("AIButton")
        self.btn_up.setIconSize(QSize(18, 18))
        self.btn_up.setMinimumHeight(40)
        self.btn_up.clicked.connect(self.ai_upscale)
        c.lay.addWidget(self.btn_up)
        return c

    # ---------------- 4. panels ----------------
    def _panels_card(self) -> QWidget:
        c = self._card("4.  Panels & Print")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        l_ = QLabel("Media width")
        l_.setObjectName("FieldLabel")
        g.addWidget(l_, 0, 0)
        self.cb_media = QComboBox()
        for t, v in wl.MEDIA_WIDTHS:
            self.cb_media.addItem(t, v)
        self.cb_media.addItem("Custom…", -1.0)
        self.cb_media.activated.connect(self._on_media)
        g.addWidget(self.cb_media, 0, 1, 1, 2)
        for r, (lab, attr, tip) in enumerate((("Overlap", "overlap", "Total overlap at each seam (half on each panel). 0 = butt joint"),
                                              ("Bleed sides", "bleed_lr", "Extra print on the left and right edges"),
                                              ("Bleed top/bottom", "bleed_tb", "Extra print at ceiling and floor")), start=1):
            l_ = QLabel(lab)
            l_.setObjectName("FieldLabel")
            l_.setToolTip(tip)
            g.addWidget(l_, r, 0)
            sp = _spin(0, 30, 1, " cm", 0.5)
            sp.setToolTip(tip)
            sp.valueChanged.connect(lambda v, a=attr: self._set_panel(a, v / 100.0))
            setattr(self, f"sp_{attr}", sp)
            g.addWidget(sp, r, 1, 1, 2)
        g.setColumnStretch(1, 1)
        c.lay.addLayout(g)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        for i, (t, v) in enumerate((("Equal", "equal"), ("Full width", "full"), ("Manual", "manual"))):
            b = QPushButton(t)
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setMinimumHeight(34)
            css = ("border-top-left-radius:8px;border-bottom-left-radius:8px;" if i == 0 else
                   "border-top-right-radius:8px;border-bottom-right-radius:8px;" if i == 2 else "")
            b.setStyleSheet(css + "font-size:10pt;")
            self.mode_group.addButton(b, i)
            seg.addWidget(b)
        self.mode_group.idClicked.connect(self._on_panel_mode)
        c.lay.addLayout(seg)
        hr = QHBoxLayout()
        self.cb_order = QComboBox()
        self.cb_order.addItem("Hang left → right", False)
        self.cb_order.addItem("Hang right → left", True)
        self.cb_order.currentIndexChanged.connect(lambda _i: self._set_panel("right_to_left",
                                                                             self.cb_order.currentData()))
        hr.addWidget(self.cb_order, 1)
        b_safe = QPushButton(icon("seams"), " Place seams safely")
        b_safe.setToolTip("Move seams away from faces, text and fine detail (and outside corners)")
        b_safe.clicked.connect(self.safe_seams)
        hr.addWidget(b_safe, 1)
        c.lay.addLayout(hr)
        self.lbl_panels = hint("")
        self.lbl_panels.setTextFormat(Qt.TextFormat.RichText)
        c.lay.addWidget(self.lbl_panels)
        pr_ = QHBoxLayout()
        l_ = QLabel("Print files")
        l_.setObjectName("FieldLabel")
        pr_.addWidget(l_)
        self.cb_preset = QComboBox()
        self.cb_preset.currentIndexChanged.connect(self._on_preset)
        pr_.addWidget(self.cb_preset, 1)
        c.lay.addLayout(pr_)
        self.reload_presets()
        return c

    # ---------------- centre ----------------
    def _plan_card(self) -> QWidget:
        c = Card()
        head = QHBoxLayout()
        head.setSpacing(6)
        t = QLabel("Wall Plan")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        self.lbl_plan = ElidedLabel("")
        self.lbl_plan.setObjectName("Hint")
        head.addWidget(self.lbl_plan, 1)
        self.toggles = {}
        for key, label, tip, on in (("panels", "Panels", "Panels, seams and overlaps", True),
                                    ("items", "Items", "Doors, windows and furniture", True),
                                    ("dims", "Sizes", "Dimension lines", True),
                                    ("risk", "Seam risk", "Faces (red boxes) and busy areas (strip above)", False),
                                    ("proof", "Print colours", "Soft-proof with the print profile", False),
                                    ("gamut", "Gamut", "Colours the printer can't reach (magenta)", False)):
            b = QPushButton(label)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setChecked(on)
            b.setToolTip(f"{label}: {tip}")
            b.setProperty("long", label)
            b.setProperty("short", {"Seam risk": "Risk", "Print colours": "Colours"}.get(label, label))
            b.toggled.connect(lambda v, key=key: self._toggle(key, v))
            head.addWidget(b)
            self.toggles[key] = b
        c.lay.addLayout(head)
        self.canvas = WallCanvas()
        self.canvas.changed.connect(self._on_canvas_changed)
        self.canvas.editStarted.connect(self._snapshot)
        self.canvas.selectionChanged.connect(self._on_canvas_select)
        self.canvas.zoomChanged.connect(self._on_canvas_zoom)
        self.canvas.requestAddItem.connect(lambda wi, k, x, y: self.add_item(k, wi, x, y))
        c.lay.addWidget(self.canvas, 1)
        zr = QHBoxLayout()
        zr.setSpacing(10)

        def ib(name, tip, slot, size=24):
            b = QToolButton()
            b.setObjectName("IconBtn")
            b.setIcon(icon(name, "#1e293b"))
            b.setIconSize(QSize(size, size))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        self.sl_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sl_zoom.setRange(0, 1000)
        self.sl_zoom.setMaximumWidth(240)
        self.sl_zoom.valueChanged.connect(self._on_zoom_slider)
        self.lbl_zoom = QLabel("Fit")
        self.lbl_zoom.setObjectName("ZoomBox")
        self.lbl_zoom.setFixedWidth(96)
        self.lbl_zoom.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zr.addWidget(ib("zoom_out", "Zoom out", lambda: self.canvas.zoom_to(self.canvas.zoom_factor() / 1.25)))
        zr.addWidget(self.sl_zoom, 2)
        zr.addWidget(ib("zoom_in", "Zoom in", lambda: self.canvas.zoom_to(self.canvas.zoom_factor() * 1.25)))
        zr.addSpacing(10)
        zr.addWidget(self.lbl_zoom)
        zr.addSpacing(8)
        zr.addWidget(ib("undo", "Undo (Ctrl+Z)", self.undo, 20))
        zr.addWidget(ib("redo", "Redo (Ctrl+Y)", self.redo, 20))
        zr.addSpacing(8)
        self.lbl_tip = hint("Drag the design to move it · Ctrl+wheel to scale · drag seams and items · right-click for more")
        self.lbl_tip.setWordWrap(False)
        self.lbl_tip.setMinimumWidth(10)
        self.lbl_tip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.canvas.setToolTip(self.lbl_tip.text())
        zr.addWidget(self.lbl_tip, 1)
        zr.addWidget(ib("fit", "Fit (double-click)", self.canvas.fit))
        c.lay.addLayout(zr)
        self.plan_card = c
        return c

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._fit_plan_header()

    def _fit_plan_header(self) -> None:
        """Narrow screens: shorter chip names, no hint line (it stays as the canvas tooltip)."""
        if not hasattr(self, "plan_card"):
            return
        wdt = self.plan_card.width()
        short = wdt < 820
        for b in self.toggles.values():
            t = b.property("short" if short else "long")
            if b.text() != t:
                b.setText(t)
        self.lbl_plan.setVisible(wdt >= 700)
        self.lbl_tip.setVisible(wdt >= 760)

    # ---------------- right ----------------
    def _checks_card(self) -> QWidget:
        c = self._card("Print Checks")
        self.lbl_checks = QLabel("")
        self.lbl_checks.setObjectName("Hint")
        c.lay.addWidget(self.lbl_checks)
        self.list_checks = QListWidget()
        self.list_checks.setWordWrap(True)
        self.list_checks.setStyleSheet("QListWidget{border:none;} QListWidget::item{padding:4px 2px;}")
        self.list_checks.itemClicked.connect(lambda _it: self.open_print())
        self.list_checks.setMinimumHeight(64)
        self.list_checks.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        c.lay.addWidget(self.list_checks, 1)
        return c

    def _room_card(self) -> QWidget:
        c = self._card("Room View")
        self.cb_scene = QComboBox()
        for k, v in mk.SCENES.items():
            self.cb_scene.addItem(v, k)
        self.cb_scene.addItem("Customer's wall photo", "photo")
        self.cb_scene.currentIndexChanged.connect(lambda _i: self.t_room.start())
        c.lay.addWidget(self.cb_scene)
        self.room_thumb = QPushButton()
        self.room_thumb.setObjectName("Flat")
        self.room_thumb.setStyleSheet("min-height: 120px;")     # QSS min-height wins
        self.room_thumb.setIconSize(QSize(268, 150))
        self.room_thumb.installEventFilter(self)
        self._room_px = None
        self.room_thumb.setToolTip("Open the room preview")
        self.room_thumb.clicked.connect(self.open_room)
        c.lay.addWidget(self.room_thumb, 1)
        return c

    def _areas_card(self) -> QWidget:
        c = self._card("Areas & Rolls")
        self.lbl_areas = QLabel("")
        self.lbl_areas.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_areas.setWordWrap(True)
        c.lay.addWidget(self.lbl_areas)
        return c

    def _tiles_card(self) -> QWidget:
        c = self._card("5.  Proof & Print")
        row = QHBoxLayout()
        row.setSpacing(12)

        def tile(obj, ic, colr, text, slot, tip):
            b = QToolButton()
            b.setObjectName(obj)
            b.setIcon(icon(ic, colr))
            b.setIconSize(QSize(34, 34))
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setStyleSheet("min-height: 64px;")      # QSS min-height wins over setMinimumHeight
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        self.tile_proof = tile("TileBlue", "doc", "#1a73e8", "Customer Proof", self.open_proof,
                            "Proof with sizes, room preview, warning and approval box")
        self.tile_room = tile("TilePurple", "sofa", "#6d4aff", "Room Mockup", self.open_room,
                           "See the design in a room or on the customer's photo")
        self.tile_inst = tile("TileGreen", "layers", "#1e293b", "Installer Sheet", self.save_installer,
                           "Hanging plan with numbered panels")
        self.tile_print = tile("TileGreen", "send_print", "#1e293b", "Send to Print", self.open_print,
                            "Preflight checks and print-ready files")
        self.tile_wa = tile("TileWA", "whatsapp", "#1f9d55", "WhatsApp", self.share_whatsapp,
                         "Send the proof or mockup on WhatsApp")
        c.lay.addLayout(row)
        return c

    # ==================================================================
    # Job lifecycle
    # ==================================================================
    def activated(self) -> None:
        if self.job is not None:
            return
        last = self.settings.value("studio_last_job")
        if last and Path(str(last), "job.json").is_file():
            try:
                self.load_job_folder(Path(str(last)))
                return
            except Exception:
                traceback.print_exc()
        self.new_job()

    def can_leave_job(self, what: str) -> bool:
        """Save the open job before another one replaces it. When it can't be saved, ask first
        instead of quietly losing the latest changes."""
        if self.job is None or self.save_now():
            return True
        return QMessageBox.question(
            self, "Job not saved", f"{self.job.job_no} could not be saved, so its latest changes would be "
            f"lost.\n\n{what} anyway?") == QMessageBox.StandardButton.Yes

    def new_job(self) -> bool:
        """Start a new job. Returns False when the user chose to stay on the unsaved one."""
        if not self.can_leave_job("Start a new job"):
            return False
        self.job = wl.Job(job_no=jobs.next_job_no())
        self.job.walls[0].width, self.job.walls[0].height = 3.0, 2.5
        self.job.log("Job created")
        self.job_dir = None
        self.design_img = self.tile_img = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._after_load()
        return True

    def load_job_folder(self, folder) -> None:
        if self.job is not None and (self.job_dir is None or Path(folder) != self.job_dir):
            if not self.can_leave_job("Open the other job"):
                return
        try:
            job = jobs.load_job(Path(folder))
        except FileNotFoundError:
            QMessageBox.warning(self, "Job not found", f"The job folder could not be found:\n{folder}\n\n"
                                "It may have been moved, renamed or deleted.")
            if self.job is None:
                self.new_job()
            return
        except ValueError as exc:
            QMessageBox.warning(self, "Could not open the job", str(exc))
            if self.job is None:
                self.new_job()
            return
        self.job = job
        self.job_dir = Path(folder)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._load_design_files()
        self._after_load()
        self.settings.setValue("studio_last_job", str(self.job_dir))

    def _load_design_files(self) -> None:
        self.design_img = self.tile_img = None
        if not self.job_dir:
            return
        try:
            if self.job.design and (self.job_dir / self.job.design).is_file():
                self.design_img = load_design_image(self.job_dir / self.job.design)
            tile = (self.job.pattern or {}).get("tile")
            if self.job.design_kind == "pattern" and tile and (self.job_dir / tile).is_file():
                self.tile_img = load_design_image(self.job_dir / tile)
        except Exception as exc:
            QMessageBox.warning(self, "Could not open the design", im.load_error_text(self.job_dir / (self.job.design or "design"), exc))

    def _after_load(self) -> None:
        self._rebuild_source()
        self.refresh_forms()
        self.canvas.selected = None
        self.canvas.fit()
        self._changed("all", undoable=False, save=False)

    def save_now(self) -> bool:
        """Save the job. Returns False (after telling the user) when Windows or the disk refused."""
        if self.job is None:
            return True
        self.t_save.stop()
        if self.job_dir is None and not (self.job.customer or self.job.design or self.job.history[1:]
                                         or any(w.obstacles for w in self.job.walls)):
            return True   # an untouched new job is not worth a folder
        try:
            self.job_dir = jobs.save_job(self.job)
        except OSError as exc:
            from app.ui.errors import write_log
            import time as _t
            self.main.statusBar().showMessage("Could not save the job – it will be tried again.", 8000)
            if _t.time() - getattr(self, "_save_warned", 0) > 120:       # don't nag every few seconds
                self._save_warned = _t.time()
                write_log(f"job save failed: {traceback.format_exc()}")
                why = ("the disk is full" if getattr(exc, "errno", None) == 28 else
                       "Windows did not allow it (the folder may be read-only, offline or open in another "
                       "program)")
                QMessageBox.warning(self, "Job not saved", f"{self.job.job_no} could not be saved because {why}."
                                    "\n\nYour changes are still here. The app will try again automatically.")
            self.t_save.start(15000)
            return False
        self.t_save.setInterval(1500)
        self.settings.setValue("studio_last_job", str(self.job_dir))
        if self.design_img is not None and self.source is not None:
            try:
                img, _ppm = pr.render_wall_area(self.source, self.job, 360, fast=True)
                jobs.save_thumb(self.job, img)
            except Exception:
                pass
        return True

    def ensure_dir(self) -> Path:
        if self.job_dir is None:
            self.job_dir = jobs.save_job(self.job)
            self.settings.setValue("studio_last_job", str(self.job_dir))
        return self.job_dir

    def duplicate_job(self) -> None:
        self.save_now()
        if self.job_dir is None:
            return
        k = jobs.duplicate_job(self.job)
        self.load_job_folder(jobs.folder_for(k))
        self.main.statusBar().showMessage(f"New job {k.job_no} – a copy for a reprint.", 5000)

    def open_folder(self) -> None:
        d = self.ensure_dir()
        share.show_in_folder(d / "job.json")

    # ==================================================================
    # Forms <-> job
    # ==================================================================
    def wall_index(self) -> int:
        i = self.wall_group.checkedId()
        return i if 0 <= i < len(self.job.walls) else 0

    def unit(self) -> str:
        return self.cb_wunit.currentData() or "m"

    def refresh_forms(self) -> None:
        j = self.job
        self._loading = True
        try:
            self.lbl_job.setText(j.job_no)
            self.cb_status.setCurrentText(j.status)
            self._style_status()
            self.ed_customer.setText(j.customer)
            self.ed_phone.setText(j.phone)
            self.ed_room.setText(j.room)
            # wall tabs
            cur = min(self.wall_group.checkedId() if self.wall_group.checkedId() >= 0 else 0, len(j.walls) - 1)
            for b in list(self.wall_group.buttons()):
                self.wall_group.removeButton(b)
                b.deleteLater()
            while self.wall_tabs.count():
                it = self.wall_tabs.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            for i, w in enumerate(j.walls):
                b = QPushButton(w.name)
                b.setObjectName("Chip")
                b.setCheckable(True)
                self.wall_group.addButton(b, i)
                self.wall_tabs.addWidget(b)
            add = QPushButton(icon("plus"), "")
            add.setObjectName("Chip")
            add.setToolTip("Add a wall (the design wraps round the corner)")
            add.clicked.connect(self.add_wall)
            self.wall_tabs.addWidget(add)
            self.wall_tabs.addStretch()
            self.wall_group.button(max(0, cur)).setChecked(True)
            unit = j.unit if j.unit in ("m", "cm", "ft", "in") else "m"
            self.cb_wunit.setCurrentIndex(max(0, self.cb_wunit.findData(unit)))
            self.canvas.unit = unit
            self._refresh_wall_fields()
            self.sp_view.setValue(j.view_distance)
            # design
            self.cb_place.setCurrentIndex(max(0, self.cb_place.findData(j.placement.mode)))
            anchor = (j.placement.anchor_x, j.placement.anchor_y)
            for k in range(self.cb_anchor.count()):
                if self.cb_anchor.itemData(k) == anchor:
                    self.cb_anchor.setCurrentIndex(k)
            self.chk_flip.setChecked(j.placement.flip_h)
            self.btn_bg.setStyleSheet(f"background:{j.placement.background};border:1px solid #94a3b8;border-radius:6px;")
            # panels
            sp = j.panels
            k = self.cb_media.findData(sp.media_width)
            if k < 0:
                self.cb_media.insertItem(self.cb_media.count() - 1, f"{sp.media_width * 100:.1f} cm (custom)",
                                         sp.media_width)
                k = self.cb_media.findData(sp.media_width)
            self.cb_media.setCurrentIndex(k)
            self.sp_overlap.setValue(sp.overlap * 100)
            self.sp_bleed_lr.setValue(sp.bleed_left * 100)
            self.sp_bleed_tb.setValue(sp.bleed_top * 100)
            self.mode_group.button({"equal": 0, "full": 1, "manual": 2}.get(sp.mode, 0)).setChecked(True)
            self.cb_order.setCurrentIndex(1 if sp.right_to_left else 0)
            k = self.cb_preset.findText(j.output_preset)
            self.cb_preset.setCurrentIndex(max(0, k))
        finally:
            self._loading = False
        self._refresh_design_info()

    def _refresh_wall_fields(self) -> None:
        j = self.job
        wi = self.wall_index()
        w = j.walls[wi]
        u = self.unit()
        prev = self._loading
        self._loading = True
        try:
            dec = {"m": 2, "cm": 1, "ft": 2, "in": 1}[u]
            for sp, v, hi in ((self.sp_ww, w.width, 100), (self.sp_wh, w.height, 30)):
                sp.setDecimals(dec)
                sp.setRange(un.to_unit(0.1, u), un.to_unit(hi, u))
                sp.setSingleStep({"m": 0.05, "cm": 5, "ft": 0.25, "in": 1}[u])
                sp.setSuffix(f" {u}")
                sp.setValue(un.to_unit(v, u))
            self.lbl_wall_ft.setText(f"{un.ft_in(w.width)} × {un.ft_in(w.height)}  ·  "
                                     f"{un.fmt_area_both(w.area())}" + ("  ·  measured from a photo" if w.photo else ""))
            self.btn_shape.setText(" Shape: " + wl.SHAPES.get(w.shape, "Rectangle").split(" (")[0])
            self.row_corner.setVisible(wi < len(j.walls) - 1)
            self.cb_corner.setCurrentIndex(max(0, self.cb_corner.findData(w.corner_after)))
            self.items.clear()
            for o in w.obstacles:
                it = QListWidgetItem(f"{o.name}  ·  {un.fmt_size(o.w, o.h, u)}" + ("  · in front" if o.in_front else ""))
                pm = QPixmap(12, 12)
                pm.fill(QColor(o.colour))
                it.setIcon(pm)
                it.setData(Qt.ItemDataRole.UserRole, o.id)
                self.items.addItem(it)
            sel = self.canvas.selected
            row = -1
            if sel and sel[0] == wi:
                row = next((k for k, o in enumerate(w.obstacles) if o.id == sel[1]), -1)
            self.items.setCurrentRow(row)
            self._refresh_item_form()
        finally:
            self._loading = prev

    def _current_item(self) -> Optional[wl.Obstacle]:
        w = self.job.walls[self.wall_index()]
        r = self.items.currentRow()
        return w.obstacles[r] if 0 <= r < len(w.obstacles) else None

    def _refresh_item_form(self) -> None:
        o = self._current_item()
        self.item_form.setVisible(o is not None)
        if o is None:
            return
        prev = self._loading
        self._loading = True
        u = self.unit()
        for key in ("x", "y", "w", "h"):
            sp = self.it_spins[key]
            sp.setDecimals({"m": 2, "cm": 1, "ft": 2, "in": 1}[u])
            sp.setRange(0, un.to_unit(100, u))
            sp.setSuffix(f" {u}")
            sp.setValue(un.to_unit(getattr(o, key), u))
        self.chk_front.setChecked(o.in_front)
        self.chk_blank.setChecked(o.blank_print)
        self.chk_blank.setEnabled(not o.in_front)
        self._loading = prev

    def _refresh_design_info(self) -> None:
        j = self.job
        if self.source is None:
            self.thumb.clear()
            self.lbl_design.setText("No design yet")
            self.lbl_design_px.setText("Choose a picture, a library design or a pattern")
            self.lbl_ppi.setText("")
            self.btn_up.setEnabled(False)
            return
        img = self.tile_img if j.design_kind == "pattern" and self.tile_img is not None else self.design_img
        if img is None:
            self.thumb.clear()
            self.lbl_design.setText(j.design_name or "Design")
            self.lbl_design_px.setText("")
            self.lbl_ppi.setText("")
            return
        key = (id(img), img.size, img.mode)
        if getattr(self, "_thumb_key", None) != key:       # only when the design changed (this runs often)
            from app.ui.qtutil import small_rgb
            pm = QPixmap.fromImage(pil_to_qimage(small_rgb(img, (184, 140))))
            pm.setDevicePixelRatio(2)
            self.thumb.setPixmap(pm)
            self._thumb_key = key
        kind = "Pattern · " if j.design_kind == "pattern" else ""
        self.lbl_design.setText(j.design_name or Path(j.design).name)
        self.lbl_design_px.setText(f"{kind}{img.width:,} × {img.height:,} px")
        ppi = float(self.source.ppi)
        lvl, txt = wl.ppi_quality(ppi, j.view_distance)
        bg, fg = {"excellent": ("#dcfce7", "#166534"), "good": ("#dcfce7", "#166534"),
                  "low": ("#fee2e2", "#991b1b")}[lvl]
        self.lbl_ppi.setText(f"{ppi:.0f} ppi at full size")
        self.lbl_ppi.setToolTip(txt)
        self.lbl_ppi.setStyleSheet(f"background:{bg};color:{fg};border-radius:9px;padding:1px 8px;"
                                   "font-size:8.5pt;font-weight:600;")
        self.lbl_ppi.setMaximumWidth(self.lbl_ppi.sizeHint().width() + 4)
        self.btn_up.setEnabled(j.design_kind != "pattern")

    def _style_status(self) -> None:
        c = wl.STATUS_COLOURS.get(self.job.status, "#64748b")
        self.cb_status.setStyleSheet(f"QComboBox{{color:{c};font-weight:700;}}")

    # ---------------- edits ----------------
    def _snapshot(self) -> None:
        self.undo_stack.append(self.job.to_dict())
        if len(self.undo_stack) > 80:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore(self, d: dict) -> None:
        """Undo/redo to a saved state, with its design picture (not only its settings)."""
        before = (self.job.design, self.job.design_kind, (self.job.pattern or {}).get("tile"))
        self.job = wl.Job.from_dict(d)
        if before != (self.job.design, self.job.design_kind, (self.job.pattern or {}).get("tile")):
            self._load_design_files()

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(self.job.to_dict())
        self._restore(self.undo_stack.pop())
        self._rebuild_source()
        self.refresh_forms()
        self._changed("all", undoable=False)

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(self.job.to_dict())
        self._restore(self.redo_stack.pop())
        self._rebuild_source()
        self.refresh_forms()
        self._changed("all", undoable=False)

    def _set_field(self, attr: str, value) -> None:
        if self._loading or getattr(self.job, attr) == value:
            return
        self._snapshot()
        setattr(self.job, attr, value)
        if attr in ("customer", "phone", "room"):
            self._changed("info", undoable=False)
        else:
            self._changed("design")

    def _on_status(self, text: str) -> None:
        if self._loading or not text:
            return
        self.job.set_status(text)
        self._style_status()
        self._changed("info", undoable=False)

    def _set_wall_size(self, width=None, height=None) -> None:
        if self._loading:
            return
        w = self.job.walls[self.wall_index()]
        u = self.unit()
        self._snapshot()
        if width is not None:
            new_w = un.from_unit(width, u)
            if w.shaped and w.width > 0:          # keep the shape in proportion
                for k in ("break_x", "peak_x", "start_x", "end_x"):
                    if k in w.shape_params:
                        w.shape_params[k] = round(float(w.shape_params[k]) * new_w / w.width, 4)
            w.width = new_w
        if height is not None:
            new_h = un.from_unit(height, u)
            if w.shaped and w.height > 0:
                for k in ("left_h", "right_h", "side_h", "rise", "top_left", "top_right"):
                    if k in w.shape_params:
                        w.shape_params[k] = round(float(w.shape_params[k]) * new_h / w.height, 4)
            w.height = new_h
        for o in w.obstacles:
            o.clamp(w.width, w.height)
        self._changed("geometry", undoable=False)

    def _on_unit(self, _i) -> None:
        if self._loading:
            return
        self.job.unit = self.unit()
        self.canvas.unit = self.job.unit
        self._refresh_wall_fields()
        self.canvas.update()
        self._mark_dirty()

    def _on_corner(self, _i) -> None:
        if self._loading:
            return
        self._snapshot()
        self.job.walls[self.wall_index()].corner_after = self.cb_corner.currentData()
        self._changed("seams", undoable=False)

    def _select_wall(self, _i) -> None:
        self._refresh_wall_fields()

    def add_wall(self) -> None:
        self._snapshot()
        h = self.job.walls[-1].height
        self.job.walls.append(wl.Wall(name=f"Wall {len(self.job.walls) + 1}", width=2.0, height=h))
        self.refresh_forms()
        self.wall_group.button(len(self.job.walls) - 1).setChecked(True)
        self._refresh_wall_fields()
        self._changed("geometry", undoable=False)

    def remove_wall(self) -> None:
        if len(self.job.walls) < 2:
            return
        self._snapshot()
        self.job.walls.pop(self.wall_index())
        self.refresh_forms()
        self._changed("geometry", undoable=False)

    def rename_wall(self) -> None:
        w = self.job.walls[self.wall_index()]
        name, ok = QInputDialog.getText(self, "Wall name", "Name:", text=w.name)
        if ok and name.strip():
            w.name = name.strip()
            self.refresh_forms()
            self._mark_dirty()

    def add_item(self, kind: str, wi: Optional[int] = None, x: Optional[float] = None,
                 y: Optional[float] = None) -> None:
        wi = self.wall_index() if wi is None else wi
        w = self.job.walls[wi]
        self._snapshot()
        o = wl.Obstacle.make(kind)
        o.x = (w.width - o.w) / 2 if x is None else x - o.w / 2
        if y is not None and kind not in ("door", "opening", "sofa", "bed", "table", "chair", "cabinet", "plant",
                                          "fireplace", "radiator"):
            o.y = y - o.h / 2
        o.clamp(w.width, w.height)
        w.obstacles.append(o)
        self.canvas.selected = (wi, o.id)
        if self.wall_index() != wi:
            self.wall_group.button(wi).setChecked(True)
        self._refresh_wall_fields()
        self._changed("items", undoable=False)

    def remove_item(self) -> None:
        o = self._current_item()
        if o is None:
            return
        self._snapshot()
        w = self.job.walls[self.wall_index()]
        w.obstacles = [x for x in w.obstacles if x.id != o.id]
        self.canvas.selected = None
        self._refresh_wall_fields()
        self._changed("items", undoable=False)

    def _on_item_row(self, row: int) -> None:
        if self._loading:
            return
        o = self._current_item()
        self.canvas.selected = (self.wall_index(), o.id) if o else None
        self._refresh_item_form()
        self.canvas.update()

    def _set_item(self, key: str, value) -> None:
        if self._loading:
            return
        o = self._current_item()
        if o is None:
            return
        self._snapshot()
        w = self.job.walls[self.wall_index()]
        if key in ("x", "y", "w", "h"):
            setattr(o, key, un.from_unit(value, self.unit()))
            o.clamp(w.width, w.height)
        else:
            setattr(o, key, bool(value))
        self.chk_blank.setEnabled(not o.in_front)
        self._changed("items", undoable=False, refresh_items=False)

    def _on_place(self, _i) -> None:
        if self._loading:
            return
        mode = self.cb_place.currentData()
        self._snapshot()
        if mode == "custom" and self.source is not None:
            wl.to_custom(self.job, self._design_px())
        else:
            self.job.placement.mode = mode
        self._changed("placement", undoable=False)

    def _on_anchor(self, _i) -> None:
        if self._loading:
            return
        ax, ay = self.cb_anchor.currentData()
        self._set_placement(anchor_x=ax, anchor_y=ay)

    def _set_placement(self, **kw) -> None:
        if self._loading:
            return
        self._snapshot()
        self.job.placement = replace(self.job.placement, **kw)
        self._changed("placement", undoable=False)

    def _pick_bg(self) -> None:
        c = QColorDialog.getColor(QColor(self.job.placement.background), self, "Background colour")
        if c.isValid():
            self._set_placement(background=c.name())
            self.btn_bg.setStyleSheet(f"background:{c.name()};border:1px solid #94a3b8;border-radius:6px;")

    def _on_media(self, _i) -> None:
        v = self.cb_media.currentData()
        if v is None:
            return
        if v < 0:
            cm, ok = QInputDialog.getDouble(self, "Media width", "Printable width of your roll (cm):",
                                            self.job.panels.media_width * 100, 20, 600, 1)
            if not ok:
                self.refresh_forms()
                return
            v = cm / 100.0
        self._set_panel("media_width", v)
        self.refresh_forms()

    def _set_panel(self, attr: str, value) -> None:
        if self._loading:
            return
        self._snapshot()
        sp = self.job.panels
        if attr == "bleed_lr":
            sp.bleed_left = sp.bleed_right = value
        elif attr == "bleed_tb":
            sp.bleed_top = sp.bleed_bottom = value
        else:
            setattr(sp, attr, value)
        if attr in ("media_width", "overlap", "bleed_lr") and sp.mode == "manual":
            sp.mode = "equal"
            self.mode_group.button(0).setChecked(True)
        self._changed("geometry" if attr.startswith("bleed") else "seams", undoable=False)

    def _on_panel_mode(self, i: int) -> None:
        self._snapshot()
        mode = ("equal", "full", "manual")[i]
        if mode == "manual":
            wl.set_manual_seams(self.job, wl.current_seams(self.job))
        else:
            self.job.panels.mode = mode
        self._changed("seams", undoable=False)

    def safe_seams(self) -> None:
        if self.risk is None:
            self.main.statusBar().showMessage("Checking the design for faces and detail… try again in a moment.", 4000)
            self._start_risk()
            return
        self._snapshot()
        seams = wl.optimise_seams(self.job, self.risk)
        wl.set_manual_seams(self.job, seams)
        self.mode_group.button(2).setChecked(True)
        self._changed("seams", undoable=False)
        self.main.statusBar().showMessage(f"Seams placed away from faces and fine detail ({len(seams) + 1} panels).",
                                          5000)

    def reload_presets(self) -> None:
        cur = self.cb_preset.currentText() or (self.job.output_preset if self.job else "")
        prev = self._loading
        self._loading = True
        self.cb_preset.clear()
        for p in pr.load_presets():
            self.cb_preset.addItem(p.name)
        k = self.cb_preset.findText(cur)
        self.cb_preset.setCurrentIndex(max(0, k))
        self._loading = prev

    def _on_preset(self, _i) -> None:
        if self._loading or not self.job:
            return
        self.job.output_preset = self.cb_preset.currentText()
        p = pr.find_preset(self.job.output_preset)
        self.job.print_dpi = p.dpi
        self._changed("colour", undoable=False)

    def _toggle(self, key: str, on: bool) -> None:
        c = self.canvas
        if key == "panels":
            c.show_panels = on
        elif key == "items":
            c.show_items = on
        elif key == "dims":
            c.show_dims = on
        elif key == "risk":
            c.show_risk = on
            if on and self.risk is None:
                self._start_risk()
        else:
            self.t_render.start()
        c.update()

    # ---------------- canvas ----------------
    def _on_canvas_changed(self, what: str) -> None:
        live = what.endswith("-live")
        kind = what.replace("-live", "")
        if live:
            if kind == "placement":
                self.t_render.start()
            self._update_side(light=True)
            return
        if kind == "placement":
            self.cb_place.blockSignals(True)
            self.cb_place.setCurrentIndex(self.cb_place.findData("custom"))
            self.cb_place.blockSignals(False)
        if kind == "seams":
            self.mode_group.button(2).setChecked(True)
        self._changed(kind)

    def _on_canvas_select(self, sel) -> None:
        if sel is not None and sel[0] != self.wall_index():
            self.wall_group.button(sel[0]).setChecked(True)
        self._refresh_wall_fields()

    def _on_canvas_zoom(self, _s: float) -> None:
        z = self.canvas.zoom_factor()
        import math
        self.sl_zoom.blockSignals(True)
        self.sl_zoom.setValue(int(round(1000 * math.log(z / 0.3) / math.log(30 / 0.3))))
        self.sl_zoom.blockSignals(False)
        self.lbl_zoom.setText("Fit" if abs(z - 1) < 1e-3 else f"{z * 100:.0f}%")

    def _on_zoom_slider(self, v: int) -> None:
        self.canvas.zoom_to(0.3 * (30 / 0.3) ** (v / 1000.0))

    # ==================================================================
    # Change handling, rendering, checks
    # ==================================================================
    def _changed(self, kind: str, undoable: bool = True, save: bool = True, refresh_items: bool = True) -> None:
        """Something in the job changed: re-render what is needed."""
        if self.job is None:
            return
        if undoable and kind in ("placement", "seams", "items"):
            pass   # canvas drags: snapshot taken lazily below
        self._gen += 1
        if kind in ("all", "design", "placement", "geometry", "colour"):
            self._rebuild_source(keep=kind not in ("all", "design"))
            self.t_render.start()
        if kind in ("all", "design", "placement", "geometry"):
            self.risk = None
            self.canvas.risk = None
            self.canvas.faces = []
            self.t_risk.start()
        if kind in ("items", "geometry", "all") and refresh_items:
            self._refresh_wall_fields()
        self.canvas.set_job(self.job, self._design_px())
        self._refresh_design_info()
        self._update_side()
        self.t_room.start()
        if save:
            self._mark_dirty()

    def _mark_dirty(self) -> None:
        self.t_save.start()

    def _design_px(self):
        if self.source is None:
            return None
        return self.source.size_px

    def _rebuild_source(self, keep: bool = False) -> None:
        j = self.job
        if j is None:
            self.source = None
            return
        from app.core.layers import LayeredSource
        base = self.source.base if isinstance(self.source, LayeredSource) else self.source
        if j.design_kind == "pattern" and self.tile_img is not None:
            base = pr.make_source(j, self.design_img, self.tile_img)
        elif self.design_img is not None:
            if keep and isinstance(base, pr.ImageSource):
                base.job = j
                base.rp = wl.resolve_placement(j, self.design_img.size)
                base.bg = col.rgb_of(j.placement.background or "#ffffff")
            else:
                base = pr.ImageSource(self.design_img, j)
        else:
            base = None
        # text and logos on top
        self.source = LayeredSource(base, j, self.job_dir) if (base is not None and j.layers) else base

    def _render(self) -> None:
        j = self.job
        if j is None:
            return
        if self.source is None:
            self.canvas.set_art(None)
            self.canvas.set_job(j, None)
            return
        self._rebuild_source(keep=True)
        if self.source is None:
            self.canvas.set_art(None)
            self.canvas.set_job(j, None)
            return
        art, _ppm = pr.render_artwork(self.source, j, max_side=1800, fast=True)
        overlay = None
        prof = col.find_profile(pr.find_preset(j.output_preset).colour)
        if prof is not None and self.toggles["proof"].isChecked():
            art = col.soft_proof(art, prof)
        if prof is not None and self.toggles["gamut"].isChecked():
            mask, frac = col.gamut_map(art, prof)
            self.gamut_fraction = frac
            over = Image.new("RGBA", mask.size, (255, 0, 200, 0))
            over.putalpha(mask.point(lambda v: 200 if v else 0))
            overlay = pil_to_qimage(over)
            self._update_side()
        self.canvas.set_art(pil_to_qimage(art), overlay)
        self.canvas.set_job(j, self._design_px())

    def _start_risk(self) -> None:
        if self.source is None or self.job is None:
            return
        job = self._RiskJobCls(self._gen, self.source, self.job.copy())
        job.signals.done.connect(self._risk_done)
        self._risk_jobs.add(job)
        self.pool.start(job)

    _RiskJobCls = RiskJob

    def _risk_done(self, gen, risk, faces) -> None:
        self._risk_jobs = {j for j in self._risk_jobs if j.gen != gen}
        if gen != self._gen or risk is None:
            return
        self.risk = risk
        self.faces = faces
        self.canvas.risk = risk
        self.canvas.faces = faces
        self.canvas.update()
        self._update_side()

    def _update_side(self, light: bool = False) -> None:
        j = self.job
        panels = wl.compute_panels(j)
        widths = sorted({round(p.width * 100, 1) for p in panels})
        u = self.unit()
        self.lbl_panels.setText(
            f"<b>{len(panels)} panel{'s' if len(panels) != 1 else ''}</b> · {', '.join(str(w) for w in widths)} cm wide · "
            + (f"{min(p.height for p in panels) * 100:.0f}–{max(p.height for p in panels) * 100:.0f} cm long"
               if j.uneven and panels and max(p.height for p in panels) - min(p.height for p in panels) > 0.005
               else f"{j.art_height * 100:.1f} cm long")
            + f"<br>Print area {un.fmt_size(j.art_width, j.art_height, u)} incl. bleed")
        self.lbl_plan.setText(f"   {' + '.join(un.fmt_size(w.width, w.height, u) for w in j.walls)}"
                              f"   ·   {un.fmt_area_both(j.wall_area())}")
        if light:
            return
        net = j.wall_area() - j.openings_area()
        ro = wl.rolls_needed(j.run_width, j.run_height, 0.53, 10.05)
        self.lbl_areas.setText(
            f"Wall <b>{un.fmt_area_both(j.wall_area())}</b><br>"
            f"Minus doors &amp; windows <b>{un.fmt_area_both(net)}</b><br>"
            f"Behind furniture {un.fmt_area(j.hidden_area())}<br>"
            f"Print media <b>{un.fmt_area(wl.media_area(j, panels))}</b> ({len(panels)} panels)<br>"
            f"<span style='color:#64748b'>Standard rolls 53 cm × 10 m: {ro.rolls} rolls ({ro.strips} strips)</span>")
        self.checks = pf.run(j, self.source, pr.find_preset(j.output_preset), self.risk, self.gamut_fraction,
                             self.job_dir)
        e, w = pf.counts(self.checks)
        self.lbl_checks.setText("Ready to print ✓" if not e and not w else
                                f"{e} problem{'s' if e != 1 else ''} · {w} warning{'s' if w != 1 else ''} – click to fix")
        self.list_checks.clear()
        for c in self.checks:
            if c.level == "info":
                continue
            name, colr = LEVEL_ICON[c.level]
            it = QListWidgetItem(icon(name, colr), c.title)
            it.setToolTip(c.detail)
            self.list_checks.addItem(it)

    def _update_room_thumb(self) -> None:
        if self.job is None:
            return
        try:
            img = self.room_image(max_w=560, fast=True)
        except Exception:
            traceback.print_exc()
            return
        if img is None:
            self.room_thumb.setIcon(icon("sofa", "#94a3b8"))
            return
        img.thumbnail((536, 300))
        pm = QPixmap.fromImage(pil_to_qimage(img))
        pm.setDevicePixelRatio(2)
        self.room_thumb.setIcon(pm)
        self._room_px = (img.width // 2, img.height // 2)
        self._fit_room_icon()

    def _fit_room_icon(self) -> None:
        """The room picture fills the button, whatever its size, without stretching."""
        if not self._room_px:
            return
        iw, ih = self._room_px
        bw, bh = max(40, self.room_thumb.width() - 12), max(40, self.room_thumb.height() - 10)
        k = min(bw / iw, bh / ih)
        self.room_thumb.setIconSize(QSize(max(1, int(iw * k)), max(1, int(ih * k))))

    def eventFilter(self, obj, ev) -> bool:
        if obj is getattr(self, "room_thumb", None) and ev.type() == QEvent.Type.Resize:
            self._fit_room_icon()
        return super().eventFilter(obj, ev)

    def room_image(self, max_w: int = 1600, fast: bool = False, scene: Optional[str] = None,
                   finish: Optional[str] = None) -> Optional[Image.Image]:
        """Room preview (scene or the customer's photo) for proofs and the thumbnail."""
        j = self.job
        scene = scene or self.cb_scene.currentData()
        finish = finish or j.finish
        wall_img = None
        if self.source is not None:
            wall_img, _ = pr.render_wall_area(self.source, j, max_side=max(600, int(max_w * 0.9)), fast=fast)
        if scene == "photo":
            w = j.walls[0]
            if w.photo and self.job_dir and (self.job_dir / w.photo).is_file() and len(w.corners) == 4 and wall_img:
                from app.core import measure as ms
                photo, _f = ms.load_photo(self.job_dir / w.photo)
                if max(photo.size) > max_w * 1.5:
                    k = max_w * 1.5 / max(photo.size)
                    photo = photo.resize((round(photo.width * k), round(photo.height * k)), Image.Resampling.LANCZOS)
                else:
                    k = 1.0
                corners = [(x * k, y * k) for x, y in w.corners]
                res = ms.solve(ms.Survey(photo.size, corners, width=w.width, height=w.height))
                # wall 0 only: crop its part of the run
                ww = int(round(wall_img.width * w.width / j.run_width))
                wimg = wall_img.crop((0, int(round(wall_img.height * (1 - w.height / j.run_height))), ww,
                                      wall_img.height))
                return mk.photo_mockup(photo, res.H, w.width, w.height, wimg, w.obstacles, finish=finish,
                                   outline=w.outline() if w.shaped else None)
            scene = "living"
        ppm = max_w / (j.run_width + 2 * max(0.8, j.run_width * 0.16))
        return mk.render_room(j.walls, wall_img, scene, ppm=ppm, finish=finish)

    # ==================================================================
    # Design sources
    # ==================================================================
    def _set_design(self, img_or_path, note: str) -> None:
        if isinstance(img_or_path, (str, Path)):          # check it opens before it joins the job
            try:
                load_design_image(Path(img_or_path))
            except Exception as exc:
                QMessageBox.warning(self, "Could not use this design", im.load_error_text(img_or_path, exc))
                return
        self.ensure_dir()
        self._snapshot()
        old_px = self._design_px()
        try:
            jobs.add_design(self.job, img_or_path, note)
        except (OSError, MemoryError) as exc:
            self.undo_stack.pop()
            from app.ui.worker import friendly_error
            QMessageBox.warning(self, "Could not use this design", friendly_error(exc))
            return
        if isinstance(img_or_path, Image.Image) and img_or_path.mode in ("RGB", "RGBA"):
            # a picture made in the app (expand, upscale, the editor): use it as it is, instead of
            # reading back the file just written (two copies of a big mural at once)
            self.design_img, self.tile_img = img_or_path, None
        else:
            self._load_design_files()
        if self.design_img is None:                 # it could not be opened: keep the old design
            self.job = wl.Job.from_dict(self.undo_stack.pop())
            self._load_design_files()
            self._rebuild_source()
            self.refresh_forms()
            return
        new_px = self.design_img.size if self.design_img is not None else None
        if self.job.placement.mode == "custom" and old_px and new_px:
            self.job.placement.scale *= new_px[0] / old_px[0]       # same look after an upscale
        if self.job.status in ("Enquiry", "Measured"):
            self.job.set_status("Designing")
        self.refresh_forms()
        self._changed("design", undoable=False)
        self.save_now()

    def use_image(self, img: Image.Image, name: str) -> None:
        if self.job is None:
            self.activated()
        self._set_design(img, Path(name).stem)

    def choose_design(self) -> None:
        start = self.settings.value("last_open_dir", str(Path.home() / "Pictures"))
        exts = " ".join("*" + e for e in im.supported_input_extensions())
        path, _ = QFileDialog.getOpenFileName(self, "Choose a design", str(start), f"Images ({exts})")
        if path:
            self.settings.setValue("last_open_dir", str(Path(path).parent))
            self._set_design(path, Path(path).stem)

    def from_editor(self) -> None:
        self.main.send_to_studio()

    def from_library(self) -> None:
        from app.ui.jobs_page import LibraryPicker
        dlg = LibraryPicker(self)
        if dlg.exec() and dlg.chosen is not None:
            it = dlg.chosen
            if it.kind == "pattern":
                self._use_pattern_file(jobs.library_dir() / it.file, it.repeat_cm / 100 or 0.53, it.name)
            else:
                self._set_design(jobs.library_dir() / it.file, it.name)

    def _use_pattern_file(self, path: Path, repeat_m: float, name: str) -> None:
        from app.core.pattern import PatternSpec
        self.ensure_dir()
        rel = jobs.add_design(self.job, path, name)
        spec = PatternSpec(tile=rel, repeat_w=repeat_m)
        self.job.design_kind = "pattern"
        self.job.pattern = spec.to_dict()
        self._load_design_files()
        self.refresh_forms()
        self._changed("design", undoable=False)

    def add_to_library(self) -> None:
        if not self.job or not self.job.design or not self.job_dir:
            return
        name, ok = QInputDialog.getText(self, "Add to library", "Name:", text=self.job.design_name or "Design")
        if not ok:
            return
        tags, ok = QInputDialog.getText(self, "Add to library", "Tags (comma separated, e.g. nature, kids):")
        rep = (self.job.pattern or {}).get("repeat_w", 0) * 100 if self.job.design_kind == "pattern" else 0
        jobs.library_add(self.job_dir / self.job.design, name, (tags or "").split(","),
                         self.job.design_kind if self.job.design_kind == "pattern" else "mural", rep)
        self.main.statusBar().showMessage(f"Added '{name}' to the design library.", 4000)

    def ai_upscale(self) -> None:
        if self.design_img is None:
            return
        from app.ui.upscale_dialog import UpscaleDialog
        j = self.job
        dlg = UpscaleDialog(self, self.design_img, j.design_name, self.main.ai, j.print_dpi)
        # pre-fill: make the design big enough for the whole print area at the print DPI
        rp = wl.resolve_placement(j, self.design_img.size)
        width_in = rp.design_w_m / 0.0254
        dlg._fit_w_in = width_in
        dlg.cb_pu.setCurrentIndex(max(0, dlg.cb_pu.findData("ft")))
        dlg.sp_dpi.setValue(j.print_dpi)
        dlg._refresh_fit_spin()
        dlg.b_fit.setChecked(True)
        dlg.applied.connect(lambda img, us, dpi, unit: self._set_design(img, f"AI upscaled {img.width}x{img.height}"))
        dlg.exec()

    def cloud_upscale(self) -> None:
        if self.design_img is None:
            return
        from app.ui.settings_dialogs import CloudUpscaleDialog
        dlg = CloudUpscaleDialog(self, self.design_img)
        if dlg.exec() and dlg.result_img is not None:
            self._set_design(dlg.result_img, f"online upscaled {dlg.result_img.width}x{dlg.result_img.height}")

    # ==================================================================
    # Dialogs
    # ==================================================================
    def open_measure(self) -> None:
        from app.ui.measure_dialog import MeasureDialog
        self.ensure_dir()
        dlg = MeasureDialog(self, self.job, self.wall_index(), self.job_dir)
        if dlg.exec() and dlg.applied:
            self._snapshot()
            wi = self.wall_index()
            w = self.job.walls[wi]
            r = dlg.result_wall
            w.width, w.height = r.width, r.height
            w.obstacles = r.obstacles
            w.photo, w.corners, w.survey = r.photo, r.corners, r.survey
            if self.job.status == "Enquiry":
                self.job.set_status("Measured")
            self.job.log(f"{w.name} measured from a photo: {w.width:.3f} × {w.height:.3f} m")
            self.refresh_forms()
            self._changed("geometry", undoable=False)

    def open_layers(self) -> None:
        if self.source is None:
            QMessageBox.information(self, "Text & logo", "Choose a design first.")
            return
        from app.ui.layers_dialog import LayersDialog
        self.ensure_dir()
        dlg = LayersDialog(self)
        if dlg.exec():
            self._snapshot()
            self.job.layers = dlg.result_layers()
            self.job.log(f"Text & logo: {len(self.job.layers)} item(s)")
            self._changed("design", undoable=False)

    def expand_design(self) -> None:
        if self.design_img is None or self.job.design_kind == "pattern":
            QMessageBox.information(self, "Expand design", "Choose a picture first (patterns repeat, so they "
                                                           "never need expanding).")
            return
        from app.ui.expand_dialog import ExpandDialog
        dlg = ExpandDialog(self)
        if dlg.exec() and dlg.result_img is not None:
            self.job.placement.mode = "fill"
            self.job.placement.anchor_x = self.job.placement.anchor_y = "center"
            self._set_design(dlg.result_img, f"expanded to fit {dlg.result_img.width}x{dlg.result_img.height}")

    def open_shape(self) -> None:
        from app.ui.shape_dialog import ShapeDialog
        wi = self.wall_index()
        dlg = ShapeDialog(self.window(), self.job.walls[wi], self.unit())
        if dlg.exec():
            self._snapshot()
            r = dlg.result_wall()
            w = self.job.walls[wi]
            w.shape, w.shape_params, w.height = r.shape, r.shape_params, r.height
            for o in w.obstacles:
                o.clamp(w.width, w.height)
            self.job.log(f"{w.name} shape: {wl.SHAPES.get(w.shape, w.shape)}")
            self.refresh_forms()
            self._changed("geometry", undoable=False)

    def open_room(self) -> None:
        if self.source is None:
            QMessageBox.information(self, "Room View", "Choose a design first, then see it in a room.")
            return
        from app.ui.room_dialog import RoomDialog
        RoomDialog(self).exec()

    def open_colour(self) -> None:
        if self.source is None:
            QMessageBox.information(self, "Colour", "Choose a design first.")
            return
        from app.ui.colour_dialog import ColourDialog
        dlg = ColourDialog(self)
        if dlg.exec() and dlg.result_img is not None:
            if dlg.pattern:                     # keep it a pattern: only the tile changes
                from app.core.pattern import PatternSpec
                self.ensure_dir()
                self._snapshot()
                spec = PatternSpec.from_dict(self.job.pattern)
                spec.tile = jobs.add_design(self.job, dlg.result_img, f"pattern tile {dlg.result_note}")
                self.job.design_kind = "pattern"
                self.job.pattern = spec.to_dict()
                self._load_design_files()
                self.refresh_forms()
                self._changed("design", undoable=False)
            else:
                self._set_design(dlg.result_img, dlg.result_note)

    def open_pattern(self) -> None:
        from app.ui.pattern_dialog import PatternDialog
        dlg = PatternDialog(self)
        if dlg.exec() and dlg.result is not None:
            tile, spec, name = dlg.result
            self.ensure_dir()
            self._snapshot()
            rel = jobs.add_design(self.job, tile, f"pattern tile {name}")
            spec.tile = rel
            self.job.design_kind = "pattern"
            self.job.pattern = spec.to_dict()
            self._load_design_files()
            self.refresh_forms()
            self._changed("design", undoable=False)

    def open_proof(self) -> None:
        if self.source is None:
            QMessageBox.information(self, "Proof", "Choose a design first.")
            return
        from app.ui.job_docs import ProofDialog
        self.ensure_dir()
        ProofDialog(self).exec()
        self.refresh_forms()
        self._changed("info", undoable=False)

    def open_print(self) -> None:
        from app.ui.print_dialog import PrintDialog
        self.ensure_dir()
        PrintDialog(self).exec()
        self.refresh_forms()
        self._changed("info", undoable=False)

    def save_installer(self) -> None:
        if self.source is None:
            QMessageBox.information(self, "Installer sheet", "Choose a design first.")
            return
        from app.core import documents as docs
        d = self.ensure_dir()
        panels = wl.compute_panels(self.job)
        preset = pr.find_preset(self.job.output_preset)
        names = [pr.panel_filename(self.job, p, len(panels), preset) for p in panels]
        pages = docs.installer_sheet(self.job, self.source, panels, names, jobs.load_business())
        out = d / "print"
        out.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save installation sheet",
                                              str(out / f"{pr.safe_name(self.job.job_no)}_installation_sheet.pdf"),
                                              "PDF (*.pdf)")
        if not path:
            return
        from app.ui.errors import save_or_warn
        if not save_or_warn(self, lambda: pages[0].save(path, "PDF", resolution=150.0, save_all=True,
                                                        append_images=pages[1:]), path):
            return
        share.show_in_folder(Path(path))

    def share_whatsapp(self) -> None:
        """Send the latest proof (or a room mockup) on WhatsApp."""
        if self.job is None:
            return
        f = None
        if self.job.proof_file and self.job_dir and (self.job_dir / self.job.proof_file).is_file():
            p = self.job_dir / self.job.proof_file
            jpg = p.with_suffix(".jpg")
            f = jpg if jpg.is_file() else p
        if f is None:
            img = self.room_image(1600) if self.source is not None else None
            if img is None:
                QMessageBox.information(self, "WhatsApp", "Choose a design first, then share the room preview "
                                        "or a proof on WhatsApp.")
                return
            d = self.ensure_dir()
            rel = jobs.add_file(self.job, "mockups", img, f"{pr.safe_name(self.job.job_no)}_room.jpg")
            f = d / rel
        from PIL import Image as _I
        qimg = None
        if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            try:
                with _I.open(f) as im:
                    qimg = pil_to_qimage(im.convert("RGB"))
            except OSError:
                qimg = None
        share.copy_to_clipboard(qimg, f) if qimg is not None else share.copy_files_to_clipboard([f])
        share.open_whatsapp(self.main.wa_target, self.job.phone or self.main.wa_phone)
        who = f" with {self.job.customer}" if self.job.customer else ""
        if qimg is not None:
            msg = f"{f.name} is copied. Press Ctrl+V in the chat{who}, then Send."
        else:
            msg = (f"{f.name} is copied as a file. Press Ctrl+V in the chat{who} (or attach it as a "
                   f"Document), then Send.")
        QMessageBox.information(self, "WhatsApp", msg)
