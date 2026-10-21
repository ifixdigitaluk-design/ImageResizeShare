"""Main window of Image Resize & Share."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QSplitter, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from app import __version__
from app.core import imaging as im
from app.core.ai_upscale import get_engine
from app.core.presets import CROP_RATIOS, QUICK_PRESETS, SIZE_PRESETS
from app.ui import share
from app.ui.batch import BatchDialog
from app.ui.qtutil import Card, app_icon, hint, icon, pil_to_qimage, qimage_to_pil, section
from app.core import proof
from app.ui.proof_dialog import ProofDialog
from app.ui.views import CloseUpView, CropCanvas, ZoomView
from app.ui.worker import ProcessJob

BLUE = "#155fc0"
WHITE = "#ffffff"

UPSCALE_ITEMS = [
    ("Enhanced – sharp, fast (recommended)", im.UPSCALE_ENHANCED),
    ("AI Super-Resolution – photos (best detail)", im.UPSCALE_AI_PHOTO),
    ("AI Super-Resolution – logos, artwork, text", im.UPSCALE_AI_ART),
    ("Standard – plain Lanczos", im.UPSCALE_STANDARD),
]
MODE_ITEMS = [
    ("Fit – keep whole image, add background", im.MODE_FIT_PAD),
    ("Fit inside – keep whole image, no borders", im.MODE_FIT_INSIDE),
    ("Fill – fill the size, trim edges", im.MODE_FILL),
    ("Stretch – exact size (may distort)", im.MODE_STRETCH),
]
BG_ITEMS = [("White", im.BG_WHITE), ("Black", im.BG_BLACK), ("Blurred photo", im.BG_BLUR),
            ("Transparent (PNG/WEBP)", im.BG_TRANSPARENT), ("Custom colour…", im.BG_CUSTOM)]
UNIT_DECIMALS = {"px": 0, "%": 1, "cm": 2, "mm": 1, "in": 2}


class MainWindow(QMainWindow):
    processed = Signal()  # emitted after each preview update (used by self-test)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Resize & Share")
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(1440, 920)
        self.setMinimumSize(1120, 720)

        self.settings = QSettings("ImageResizeShare", "ImageResizeShare")
        self.ai = get_engine()
        self.pool = QThreadPool.globalInstance()
        self.jobs: set = set()
        self.exts = im.supported_input_extensions()

        self.src: Optional[im.LoadedImage] = None
        self.state = im.EditState()
        self.undo_stack: list = []
        self.redo_stack: list = []
        self._undo_key: Optional[str] = None
        self.tw = self.th = 0
        self.keep_original = True
        self.gen = 0
        self.result: Optional[im.ProcessResult] = None
        self.result_gen = -1
        self.custom_color = (255, 255, 255)
        self._oriented_key = None
        self._oriented_qimg = None
        self._last_saved: Optional[Path] = None
        self._cu_pt = None          # close-up point in result pixels
        self._cu_pinned = False
        self._result_qimg = None

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._run_process)

        self._build_ui()
        self._build_actions()
        self._load_settings()
        self._set_mode(0)
        self._refresh_all()

    # ==================================================================
    # UI construction
    # ==================================================================
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 10)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(14)
        outer.addLayout(top, 1)

        # ---------- left column (scrollable) ----------
        left_inner = QWidget()
        left_inner.setObjectName("LeftInner")
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(0, 0, 6, 0)
        left.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left_inner)
        scroll.setFixedWidth(440)
        top.addWidget(scroll)

        # Mode switch (segmented)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.btn_mode_resize = QPushButton(" Resize Image")
        self.btn_mode_crop = QPushButton(" Crop Image")
        for b, n, side in ((self.btn_mode_resize, "resize", "ModeLeft"),
                           (self.btn_mode_crop, "crop", "ModeRight")):
            b.setCheckable(True)
            b.setObjectName("ModeBtn")
            b.setProperty("class", side)
            b.setIcon(icon(n, "#334155", WHITE))
            b.setIconSize(QSize(20, 20))
            seg.addWidget(b)
        self.btn_mode_resize.setStyleSheet("border-top-left-radius:10px;border-bottom-left-radius:10px;")
        self.btn_mode_crop.setStyleSheet("border-top-right-radius:10px;border-bottom-right-radius:10px;")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_mode_resize, 0)
        self.mode_group.addButton(self.btn_mode_crop, 1)
        self.mode_group.idClicked.connect(self._set_mode)
        left.addLayout(seg)

        left.addWidget(self._build_select_card())
        left.addWidget(self._build_edit_card())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_resize_card())
        self.stack.addWidget(self._build_crop_card())
        left.addWidget(self.stack)
        left.addStretch()

        # ---------- preview ----------
        top.addWidget(self._build_preview_card(), 1)

        # ---------- bottom row ----------
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        bottom.addWidget(self._build_output_card())
        bottom.addWidget(self._build_actions_card(), 1)
        outer.addLayout(bottom)

        # ---------- status bar ----------
        sb = self.statusBar()
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setFixedWidth(120)
        self.busy.setVisible(False)
        self.ai_label = QLabel(self.ai.status_text())
        sb.addPermanentWidget(self.busy)
        sb.addPermanentWidget(self.ai_label)
        help_btn = QToolButton()
        help_btn.setIcon(icon("help"))
        help_btn.setToolTip("Keyboard shortcuts & tips (F1)")
        help_btn.setAutoRaise(True)
        help_btn.clicked.connect(self.show_help)
        sb.addPermanentWidget(help_btn)

    # ------------------------------------------------------------------
    def _build_select_card(self) -> QWidget:
        card = Card("1.  Select Image")
        row = QHBoxLayout()
        self.btn_open = QPushButton(icon("folder", BLUE), "  Choose Image…")
        self.btn_open.setObjectName("Primary")
        self.btn_open.setIconSize(QSize(20, 20))
        self.btn_open.clicked.connect(self.open_dialog)
        row.addWidget(self.btn_open)
        fmts = ", ".join(e.lstrip(".").upper() for e in self.exts
                         if e not in (".jpeg", ".jfif", ".heif", ".tif", ".ico", ".tga"))
        lab = hint(f"Supported: {fmts}")
        row.addWidget(lab, 1)
        card.lay.addLayout(row)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("DropZone")
        dz = QHBoxLayout(self.drop_zone)
        dz.setContentsMargins(10, 10, 10, 10)
        self.thumb = QLabel()
        self.thumb.setFixedSize(112, 84)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz.addWidget(self.thumb)
        info = QVBoxLayout()
        self.file_name = QLabel("No image yet")
        self.file_name.setObjectName("FileName")
        self.file_meta = hint("Drag & drop an image here, or press Ctrl+V to paste one.")
        info.addWidget(self.file_name)
        info.addWidget(self.file_meta)
        info.addStretch()
        dz.addLayout(info, 1)
        card.lay.addWidget(self.drop_zone)

        row2 = QHBoxLayout()
        b_paste = QPushButton(icon("paste"), " Paste")
        b_paste.setToolTip("Paste an image from the clipboard (Ctrl+V)")
        b_paste.clicked.connect(self.paste_image)
        b_batch = QPushButton(icon("batch"), " Batch…")
        b_batch.setToolTip("Resize or convert many images at once")
        b_batch.clicked.connect(lambda: self.open_batch([]))
        row2.addWidget(b_paste)
        row2.addWidget(b_batch)
        row2.addStretch()
        card.lay.addLayout(row2)
        return card

    def _build_edit_card(self) -> QWidget:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(6)
        lab = section("Rotate & Flip")
        row.addWidget(lab)
        row.addStretch()

        def tb(name, tip, slot):
            b = QToolButton()
            b.setIcon(icon(name))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        self.b_rot_l = tb("rot_left", "Rotate left (Ctrl+L)", lambda: self.rotate(False))
        self.b_rot_r = tb("rot_right", "Rotate right (Ctrl+R)", lambda: self.rotate(True))
        self.b_flip_h = tb("flip_h", "Flip horizontally", lambda: self.flip(True))
        self.b_flip_v = tb("flip_v", "Flip vertically", lambda: self.flip(False))
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#e3e8ef;")
        row.addWidget(sep)
        self.b_undo = tb("undo", "Undo (Ctrl+Z)", self.undo)
        self.b_redo = tb("redo", "Redo (Ctrl+Y)", self.redo)
        card.lay.addLayout(row)
        return card

    def _build_resize_card(self) -> QWidget:
        card = Card("2.  Resize Options")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        g.addWidget(QLabel("Width"), 0, 0)
        g.addWidget(QLabel("Height"), 0, 2)
        g.addWidget(QLabel("Unit"), 0, 3)
        self.sp_w = QDoubleSpinBox()
        self.sp_h = QDoubleSpinBox()
        for sp in (self.sp_w, self.sp_h):
            sp.setRange(0, 999999)
            sp.setKeyboardTracking(False)
            sp.setMinimumWidth(110)
        self.sp_w.valueChanged.connect(self._on_w_changed)
        self.sp_h.valueChanged.connect(self._on_h_changed)
        self.btn_link = QToolButton()
        self.btn_link.setCheckable(True)
        self.btn_link.setChecked(True)
        self.btn_link.setIconSize(QSize(20, 20))
        self.btn_link.setToolTip("Maintain aspect ratio")
        self.btn_link.toggled.connect(self._on_link_toggled)
        self.cb_unit = QComboBox()
        self.cb_unit.addItems(list(im.UNITS))
        self.cb_unit.currentTextChanged.connect(lambda _: self._refresh_spins())
        g.addWidget(self.sp_w, 1, 0)
        g.addWidget(self.btn_link, 1, 1)
        g.addWidget(self.sp_h, 1, 2)
        g.addWidget(self.cb_unit, 1, 3)
        card.lay.addLayout(g)

        self.chk_ratio = QCheckBox("Maintain aspect ratio")
        self.chk_ratio.setChecked(True)
        self.chk_ratio.toggled.connect(self.btn_link.setChecked)
        card.lay.addWidget(self.chk_ratio)
        self._on_link_toggled(True)

        # quick presets
        pg = QGridLayout()
        pg.setSpacing(6)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        for i, (label, w, h) in enumerate(QUICK_PRESETS):
            b = QPushButton(label)
            b.setObjectName("Preset")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, w=w, h=h, l=label: self.apply_preset(w, h, "px", 0, l))
            self.preset_group.addButton(b, i)
            pg.addWidget(b, i // 3, i % 3)
        card.lay.addLayout(pg)

        more = QToolButton()
        more.setText("More sizes: WhatsApp, Instagram, Passport, A4…  ▾")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        menu = QMenu(more)
        for cat, items in SIZE_PRESETS.items():
            sub = menu.addMenu(cat)
            for (label, w, h, unit, dpi) in items:
                a = sub.addAction(label)
                a.triggered.connect(lambda _=False, w=w, h=h, u=unit, d=dpi, l=label:
                                    self.apply_preset(w, h, u, d, l))
        more.setMenu(menu)
        card.lay.addWidget(more)

        # quick upscale
        ur = QHBoxLayout()
        ur.addWidget(section("Upscale"))
        for k in (2, 3, 4):
            b = QPushButton(f"{k}×")
            b.setObjectName("Preset")
            b.setToolTip(f"Make the image {k}× bigger with the best available quality "
                         "(AI Super-Resolution when available)")
            b.clicked.connect(lambda _=False, k=k: self.quick_upscale(k))
            ur.addWidget(b)
        ur.addStretch()
        card.lay.addLayout(ur)

        # shape mode / background
        card.lay.addWidget(section("If the new shape is different"))
        self.cb_fit = QComboBox()
        for t, v in MODE_ITEMS:
            self.cb_fit.addItem(t, v)
        self.cb_fit.currentIndexChanged.connect(self._on_option_changed)
        card.lay.addWidget(self.cb_fit)
        bgrow = QHBoxLayout()
        self.lbl_bg = QLabel("Background")
        self.cb_bg = QComboBox()
        for t, v in BG_ITEMS:
            self.cb_bg.addItem(t, v)
        self.cb_bg.activated.connect(self._on_bg_activated)
        self.cb_bg.currentIndexChanged.connect(self._on_option_changed)
        self.btn_color = QToolButton()
        self.btn_color.setFixedSize(30, 30)
        self.btn_color.clicked.connect(self._pick_color)
        bgrow.addWidget(self.lbl_bg)
        bgrow.addWidget(self.cb_bg, 1)
        bgrow.addWidget(self.btn_color)
        card.lay.addLayout(bgrow)
        self.shape_hint = hint("")
        card.lay.addWidget(self.shape_hint)

        # enlarge quality
        card.lay.addWidget(section("Enlarging quality"))
        self.cb_up = QComboBox()
        for t, v in UPSCALE_ITEMS:
            self.cb_up.addItem(t, v)
        self.cb_up.currentIndexChanged.connect(self._on_option_changed)
        card.lay.addWidget(self.cb_up)
        srow = QHBoxLayout()
        self.chk_sharp_auto = QCheckBox("Auto sharpen")
        self.chk_sharp_auto.setChecked(True)
        self.sl_sharp = QSlider(Qt.Orientation.Horizontal)
        self.sl_sharp.setRange(0, 100)
        self.sl_sharp.setValue(30)
        self.sl_sharp.setEnabled(False)
        self.lbl_sharp = QLabel("")
        self.lbl_sharp.setFixedWidth(34)
        self.chk_sharp_auto.toggled.connect(lambda on: (self.sl_sharp.setEnabled(not on),
                                                        self._on_option_changed()))
        self.sl_sharp.valueChanged.connect(lambda v: (self.lbl_sharp.setText(str(v)),
                                                      self._on_option_changed()))
        srow.addWidget(self.chk_sharp_auto)
        srow.addWidget(self.sl_sharp, 1)
        srow.addWidget(self.lbl_sharp)
        card.lay.addLayout(srow)
        self.chk_allow_up = QCheckBox("Allow enlarging beyond the original size")
        self.chk_allow_up.setChecked(True)
        self.chk_allow_up.toggled.connect(self._on_option_changed)
        card.lay.addWidget(self.chk_allow_up)
        self.size_info = hint("")
        self.size_info.setTextFormat(Qt.TextFormat.RichText)
        card.lay.addWidget(self.size_info)
        return card

    def _build_crop_card(self) -> QWidget:
        card = Card("2.  Crop Options")
        r = QHBoxLayout()
        r.addWidget(QLabel("Aspect ratio"))
        self.cb_ratio = QComboBox()
        for label, a, b in CROP_RATIOS:
            self.cb_ratio.addItem(label, (a, b))
        self.cb_ratio.currentIndexChanged.connect(self._on_ratio_changed)
        r.addWidget(self.cb_ratio, 1)
        self.btn_swap = QToolButton()
        self.btn_swap.setText("⇄")
        self.btn_swap.setCheckable(True)
        self.btn_swap.setToolTip("Swap portrait / landscape")
        self.btn_swap.toggled.connect(lambda _: self._on_ratio_changed())
        r.addWidget(self.btn_swap)
        card.lay.addLayout(r)

        card.lay.addWidget(section("Exact position & size (pixels)"))
        g = QGridLayout()
        self.cr_x, self.cr_y, self.cr_w, self.cr_h = (QSpinBox() for _ in range(4))
        for i, (lab, sp) in enumerate((("X", self.cr_x), ("Y", self.cr_y),
                                       ("Width", self.cr_w), ("Height", self.cr_h))):
            sp.setRange(0, 999999)
            sp.setKeyboardTracking(False)
            g.addWidget(QLabel(lab), (i // 2) * 2, i % 2)
            g.addWidget(sp, (i // 2) * 2 + 1, i % 2)
            sp.valueChanged.connect(lambda _v, n=lab: self._on_crop_spin(n))
        card.lay.addLayout(g)

        row = QHBoxLayout()
        self.chk_grid = QCheckBox("Rule-of-thirds grid")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(lambda on: self.canvas.set_grid(on))
        row.addWidget(self.chk_grid)
        row.addStretch()
        card.lay.addLayout(row)
        row2 = QHBoxLayout()
        b_all = QPushButton("Select all")
        b_all.clicked.connect(self.crop_select_all)
        b_clear = QPushButton("Clear crop")
        b_clear.clicked.connect(self.crop_clear)
        row2.addWidget(b_all)
        row2.addWidget(b_clear)
        row2.addStretch()
        card.lay.addLayout(row2)
        card.lay.addWidget(hint("Drag on the image to select. Drag the edges or corners to adjust, "
                                "drag inside to move. Mouse wheel zooms, right-drag pans, "
                                "double-click resets the view."))
        self.crop_info = hint("")
        self.crop_info.setTextFormat(Qt.TextFormat.RichText)
        card.lay.addWidget(self.crop_info)
        return card

    def _build_preview_card(self) -> QWidget:
        card = Card()
        head = QHBoxLayout()
        eye = QLabel()
        eye.setPixmap(icon("eye", "#0f172a").pixmap(22, 22))
        head.addWidget(eye)
        t = QLabel("Preview")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch()
        b_fit = QPushButton(icon("fit"), " Fit")
        b_fit.setToolTip("Fit both images to the window")
        b_100 = QPushButton(icon("zoom"), " 100%")
        b_100.setToolTip("View real pixels to check sharpness")
        b_fit.clicked.connect(lambda: (self.view_orig.fit(), self.view_out.fit()))
        b_100.clicked.connect(lambda: (self.view_orig.actual_size(), self.view_out.actual_size()))
        self.btn_cu = QPushButton(icon("zoom", "#334155", WHITE), " Close-up")
        self.btn_cu.setCheckable(True)
        self.btn_cu.setChecked(True)
        self.btn_cu.setToolTip("Show a magnified before/after close-up next to the preview")
        self.btn_cu.toggled.connect(lambda on: self.cu_pane.setVisible(on))
        b_proof = QPushButton(icon("image", BLUE), " Proof sheet…")
        b_proof.setObjectName("Primary")
        b_proof.setToolTip("Preview with print size, area (sq ft) and note – save or send (Ctrl+P)")
        b_proof.clicked.connect(self.open_proof)
        head.addWidget(b_fit)
        head.addWidget(b_100)
        head.addWidget(self.btn_cu)
        head.addWidget(b_proof)
        card.lay.addLayout(head)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # left pane: original view or crop canvas
        lp = QFrame()
        lp.setObjectName("Card")
        ll = QVBoxLayout(lp)
        ll.setContentsMargins(12, 10, 12, 10)
        self.orig_title = QLabel("Original Image")
        self.orig_title.setObjectName("PaneTitle")
        ll.addWidget(self.orig_title)
        self.left_stack = QStackedWidget()
        self.view_orig = ZoomView("Your image appears here")
        self.view_orig.setAcceptDrops(False)
        self.canvas = CropCanvas()
        self.canvas.rectChanged.connect(self._on_canvas_rect)
        self.canvas.editStarted.connect(lambda: self._push_undo("canvas-drag"))
        self.canvas.editFinished.connect(lambda: setattr(self, "_undo_key", None))
        self.left_stack.addWidget(self.view_orig)
        self.left_stack.addWidget(self.canvas)
        ll.addWidget(self.left_stack, 1)
        self.orig_info = QLabel("")
        self.orig_info.setObjectName("PaneInfo")
        ll.addWidget(self.orig_info)
        split.addWidget(lp)

        rp = QFrame()
        rp.setObjectName("Card")
        rl = QVBoxLayout(rp)
        rl.setContentsMargins(12, 10, 12, 10)
        self.out_title = QLabel("Result")
        self.out_title.setObjectName("PaneTitle")
        rl.addWidget(self.out_title)
        self.view_out = ZoomView("Your processed image appears here")
        self.view_out.setAcceptDrops(False)
        rl.addWidget(self.view_out, 1)
        self.out_info = QLabel("")
        self.out_info.setObjectName("PaneInfo")
        self.out_info.setWordWrap(True)
        rl.addWidget(self.out_info)
        split.addWidget(rp)

        # close-up (loupe) pane: before vs after at the same magnification
        self.cu_pane = QFrame()
        self.cu_pane.setObjectName("Card")
        cl = QVBoxLayout(self.cu_pane)
        cl.setContentsMargins(12, 10, 12, 10)
        ch = QHBoxLayout()
        t2 = QLabel("Close-up")
        t2.setObjectName("PaneTitle")
        ch.addWidget(t2)
        ch.addStretch()
        self.cb_cu_zoom = QComboBox()
        for z in (1, 2, 4, 8):
            self.cb_cu_zoom.addItem(f"{z * 100}%", float(z))
        self.cb_cu_zoom.setCurrentIndex(1)
        self.cb_cu_zoom.setToolTip("Magnification of the result")
        self.cb_cu_zoom.currentIndexChanged.connect(lambda _: self._update_closeup())
        ch.addWidget(self.cb_cu_zoom)
        cl.addLayout(ch)
        lb = QLabel("Before (original pixels)")
        lb.setObjectName("PaneInfo")
        cl.addWidget(lb)
        self.cu_before = CloseUpView("Hover over the result")
        cl.addWidget(self.cu_before, 1)
        la = QLabel("After (your result)")
        la.setObjectName("PaneInfo")
        cl.addWidget(la)
        self.cu_after = CloseUpView("to inspect details")
        cl.addWidget(self.cu_after, 1)
        self.cu_hint = hint("Move the mouse over the preview. Click to pin / unpin the spot.")
        cl.addWidget(self.cu_hint)
        split.addWidget(self.cu_pane)
        split.setSizes([420, 420, 300])

        self.view_out.hovered.connect(self._on_out_hover)
        self.view_out.clicked.connect(self._on_out_click)
        self.view_orig.hovered.connect(self._on_orig_hover)
        self.view_orig.clicked.connect(self._on_orig_click)
        card.lay.addWidget(split, 1)
        return card

    def _build_output_card(self) -> QWidget:
        card = Card()
        card.setMinimumWidth(600)
        head = QHBoxLayout()
        gear = QLabel()
        gear.setPixmap(icon("gear", "#0f172a").pixmap(18, 18))
        head.addWidget(gear)
        t = QLabel("Output Format")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch()
        card.lay.addLayout(head)

        g = QGridLayout()
        g.setHorizontalSpacing(18)
        self.fmt_group = QButtonGroup(self)
        fmts = [("JPG", "JPG (Recommended)"), ("PNG", "PNG (Lossless)"),
                ("WEBP", "WEBP (Smaller)"), ("PDF", "PDF (Print)")]
        self.fmt_buttons = {}
        for i, (key, label) in enumerate(fmts):
            rb = QRadioButton(label)
            self.fmt_group.addButton(rb, i)
            self.fmt_buttons[key] = rb
            g.addWidget(rb, i, 0)
            rb.toggled.connect(lambda on, k=key: on and self._on_fmt_changed(k))

        qrow = QHBoxLayout()
        self.lbl_q = QLabel("Quality")
        self.sl_q = QSlider(Qt.Orientation.Horizontal)
        self.sl_q.setRange(40, 100)
        self.sl_q.setValue(92)
        self.sl_q.setMinimumWidth(150)
        self.lbl_qv = QLabel("92%")
        self.lbl_qv.setFixedWidth(40)
        self.sl_q.valueChanged.connect(lambda v: (self.lbl_qv.setText(f"{v}%"), self._on_option_changed()))
        qrow.addWidget(self.lbl_q)
        qrow.addWidget(self.sl_q, 1)
        qrow.addWidget(self.lbl_qv)
        g.addLayout(qrow, 0, 1, 1, 2)

        self.chk_lossless = QCheckBox("WEBP lossless")
        self.chk_lossless.toggled.connect(self._on_option_changed)
        g.addWidget(self.chk_lossless, 1, 1)
        trow = QHBoxLayout()
        self.chk_target = QCheckBox("Max file size")
        self.sp_target = QSpinBox()
        self.sp_target.setRange(10, 50000)
        self.sp_target.setValue(200)
        self.sp_target.setSuffix(" KB")
        self.sp_target.setKeyboardTracking(False)
        self.sp_target.setEnabled(False)
        self.chk_target.toggled.connect(lambda on: (self.sp_target.setEnabled(on), self._on_option_changed()))
        self.sp_target.valueChanged.connect(self._on_option_changed)
        trow.addWidget(self.chk_target)
        trow.addWidget(self.sp_target)
        g.addLayout(trow, 1, 2)

        drow = QHBoxLayout()
        drow.addWidget(QLabel("Print DPI"))
        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(36, 2400)
        self.sp_dpi.setValue(300)
        self.sp_dpi.setKeyboardTracking(False)
        self.sp_dpi.valueChanged.connect(self._on_dpi_changed)
        drow.addWidget(self.sp_dpi)
        drow.addStretch()
        g.addLayout(drow, 2, 1)
        self.chk_strip = QCheckBox("Remove photo info (GPS, camera)")
        self.chk_strip.toggled.connect(self._on_option_changed)
        g.addWidget(self.chk_strip, 2, 2)
        self.chk_open_folder = QCheckBox("Open folder after saving")
        g.addWidget(self.chk_open_folder, 3, 1, 1, 2)
        card.lay.addLayout(g)
        self.fmt_buttons["JPG"].setChecked(True)
        return card

    def _build_actions_card(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.btn_save = QPushButton(icon("save"), "  Save Image…")
        self.btn_save.setObjectName("BigBtn")
        self.btn_save.setIconSize(QSize(22, 22))
        self.btn_save.setMinimumHeight(64)
        self.btn_save.clicked.connect(self.save_image)

        self.btn_copy = QPushButton(icon("copy"), "  Copy")
        self.btn_copy.setObjectName("BigBtn")
        self.btn_copy.setIconSize(QSize(22, 22))
        self.btn_copy.setMinimumHeight(64)
        self.btn_copy.setToolTip("Copy the result – then press Ctrl+V in WhatsApp, email, Word…")
        self.btn_copy.clicked.connect(self.copy_result)

        wa = QHBoxLayout()
        wa.setSpacing(0)
        self.btn_wa = QPushButton(icon("chat", WHITE), "  Prepare + Open WhatsApp")
        self.btn_wa.setObjectName("WhatsApp")
        self.btn_wa.setIconSize(QSize(26, 26))
        self.btn_wa.setMinimumHeight(64)
        self.btn_wa.setStyleSheet("border-top-right-radius:0px;border-bottom-right-radius:0px;")
        self.btn_wa.clicked.connect(self.share_whatsapp)
        self.btn_wa_menu = QToolButton()
        self.btn_wa_menu.setObjectName("WhatsAppMenu")
        self.btn_wa_menu.setText("▾")
        self.btn_wa_menu.setStyleSheet("color:white;border-top-left-radius:0px;border-bottom-left-radius:0px;")
        self.btn_wa_menu.setMinimumHeight(64)
        self.btn_wa_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(self.btn_wa_menu)
        self.act_wa_web = m.addAction("Open WhatsApp Web (browser)")
        self.act_wa_desk = m.addAction("Open WhatsApp Desktop app")
        for a in (self.act_wa_web, self.act_wa_desk):
            a.setCheckable(True)
        self.act_wa_web.setChecked(True)
        self.act_wa_web.triggered.connect(lambda: self._set_wa_target("web"))
        self.act_wa_desk.triggered.connect(lambda: self._set_wa_target("desktop"))
        m.addSeparator()
        self.act_wa_phone = m.addAction("Open a chat with phone number…")
        self.act_wa_phone.triggered.connect(self._ask_phone)
        self.btn_wa_menu.setMenu(m)
        wa.addWidget(self.btn_wa, 1)
        wa.addWidget(self.btn_wa_menu)
        self.wa_sub = hint("")

        wa_box = QVBoxLayout()
        wa_box.setSpacing(4)
        wa_box.addLayout(wa)
        wa_box.addWidget(self.wa_sub)

        self.btn_reset = QPushButton(icon("reset"), "  Reset")
        self.btn_reset.setObjectName("BigBtn")
        self.btn_reset.setIconSize(QSize(22, 22))
        self.btn_reset.setMinimumHeight(64)
        self.btn_reset.setToolTip("Undo all edits and go back to the original size")
        self.btn_reset.clicked.connect(self.reset_all)

        self.btn_proof = QPushButton(icon("image"), "  Proof")
        self.btn_proof.setObjectName("BigBtn")
        self.btn_proof.setIconSize(QSize(22, 22))
        self.btn_proof.setMinimumHeight(64)
        self.btn_proof.setToolTip("Preview with print size, area (sq ft) and note (Ctrl+P)")
        self.btn_proof.clicked.connect(self.open_proof)

        lay.addWidget(self.btn_save, 2)
        lay.addWidget(self.btn_copy, 1)
        lay.addWidget(self.btn_proof, 1)
        lay.addLayout(wa_box, 3)
        lay.addWidget(self.btn_reset, 1)
        return w

    def _build_actions(self) -> None:
        def act(seq, slot, ctx=Qt.ShortcutContext.WindowShortcut):
            a = QAction(self)
            if isinstance(seq, (list, QKeySequence.StandardKey)):
                a.setShortcuts(seq)
            else:
                a.setShortcut(seq)
            a.setShortcutContext(ctx)
            a.triggered.connect(slot)
            self.addAction(a)
            return a

        act(QKeySequence.StandardKey.Open, self.open_dialog)
        act(QKeySequence.StandardKey.Save, self.save_image)
        act(QKeySequence("Ctrl+Shift+C"), self.copy_result)
        act(QKeySequence.StandardKey.Paste, self.paste_image)
        act(QKeySequence.StandardKey.Undo, self.undo)
        act([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")], self.redo)
        act(QKeySequence("Ctrl+R"), lambda: self.rotate(True))
        act(QKeySequence("Ctrl+L"), lambda: self.rotate(False))
        act(QKeySequence("Ctrl+1"), lambda: self.mode_group.button(0).click())
        act(QKeySequence("Ctrl+2"), lambda: self.mode_group.button(1).click())
        act(QKeySequence("Ctrl+W"), self.share_whatsapp)
        act(QKeySequence("Ctrl+B"), lambda: self.open_batch([]))
        act(QKeySequence("F1"), self.show_help)
        act(QKeySequence("Ctrl+P"), self.open_proof)

    # ==================================================================
    # Settings
    # ==================================================================
    def _load_settings(self) -> None:
        s = self.settings

        def val(key, default, typ=str):
            v = s.value(key, default)
            try:
                if typ is bool:
                    return v in (True, "true", "1", 1)
                return typ(v)
            except (TypeError, ValueError):
                return default

        fmt = val("fmt", "JPG")
        if fmt in self.fmt_buttons:
            self.fmt_buttons[fmt].setChecked(True)
        self.sl_q.setValue(val("quality", 92, int))
        self.sp_dpi.setValue(val("dpi", 300, int))
        self.chk_strip.setChecked(val("strip", False, bool))
        self.chk_open_folder.setChecked(val("open_folder", True, bool))
        self._select_data(self.cb_up, val("upscale", im.UPSCALE_ENHANCED))
        self._select_data(self.cb_fit, val("fit_mode", im.MODE_FIT_PAD))
        self._select_data(self.cb_bg, val("bg", im.BG_WHITE))
        self.cb_unit.setCurrentText(val("unit", "px"))
        self.wa_target = val("wa_target", "web")
        self.wa_phone = val("wa_phone", "")
        self._set_wa_target(self.wa_target)
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("fmt", self._fmt())
        s.setValue("quality", self.sl_q.value())
        s.setValue("dpi", self.sp_dpi.value())
        s.setValue("strip", self.chk_strip.isChecked())
        s.setValue("open_folder", self.chk_open_folder.isChecked())
        s.setValue("upscale", self.cb_up.currentData())
        s.setValue("fit_mode", self.cb_fit.currentData())
        s.setValue("bg", self.cb_bg.currentData())
        s.setValue("unit", self.cb_unit.currentText())
        s.setValue("wa_target", self.wa_target)
        s.setValue("wa_phone", self.wa_phone)
        s.setValue("geometry", self.saveGeometry())

    @staticmethod
    def _select_data(combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    # ==================================================================
    # Loading
    # ==================================================================
    def open_dialog(self) -> None:
        start = self.settings.value("last_open_dir", str(Path.home() / "Pictures"))
        flt = ("Images (" + " ".join("*" + e for e in self.exts) + ");;All files (*.*)")
        path, _ = QFileDialog.getOpenFileName(self, "Choose an image", str(start), flt)
        if path:
            self.load_path(path)

    def load_path(self, path) -> bool:
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            li = im.load_image(path)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Could not open image",
                                f"{Path(path).name} could not be opened.\n\n{exc}")
            return False
        QApplication.restoreOverrideCursor()
        self.settings.setValue("last_open_dir", str(Path(path).parent))
        self._set_source(li)
        if li.n_frames > 1:
            self.statusBar().showMessage("Animated image: the first frame is used.", 6000)
        return True

    def _set_source(self, li: im.LoadedImage) -> None:
        self.src = li
        self.state = im.EditState()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.keep_original = True
        self.tw, self.th = li.image.size
        self.result = None
        self.result_size = None
        self._cu_pt = None
        self._cu_pinned = False
        self._oriented_key = None
        self.canvas.set_rect(None)
        self.canvas.reset_view()
        # thumbnail + info
        th = li.image.copy()
        th.thumbnail((224, 168))
        pm = QPixmap.fromImage(pil_to_qimage(th))
        pm.setDevicePixelRatio(2)
        self.thumb.setPixmap(pm)
        name = li.path.name if li.path else "Pasted image"
        self.file_name.setText(name)
        meta = f"{li.image.width} × {li.image.height} px"
        if li.file_size:
            meta = f"{im.human_size(li.file_size)}  ·  {meta}  ·  {li.original_format}"
        self.file_meta.setText(meta)
        self._refresh_all(new_image=True)

    def paste_image(self) -> None:
        md = QGuiApplication.clipboard().mimeData()
        if md is None:
            return
        if md.hasUrls():
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            files = [f for f in files if Path(f).suffix.lower() in self.exts]
            if len(files) == 1:
                self.load_path(files[0])
                return
            if len(files) > 1:
                self.open_batch(files)
                return
        if md.hasImage():
            qimg = QGuiApplication.clipboard().image()
            if not qimg.isNull():
                self._set_source(im.from_pil(qimage_to_pil(qimg)))
                self.statusBar().showMessage("Pasted image from clipboard.", 4000)
                return
        self.statusBar().showMessage("The clipboard has no image.", 4000)

    # drag & drop -------------------------------------------------------
    def _drop_files(self, ev):
        md = ev.mimeData()
        if md.hasUrls():
            return [u.toLocalFile() for u in md.urls()
                    if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in self.exts]
        return []

    def dragEnterEvent(self, ev) -> None:
        if self._drop_files(ev) or ev.mimeData().hasImage():
            ev.acceptProposedAction()
            self.drop_zone.setProperty("active", True)
            self.drop_zone.style().polish(self.drop_zone)

    def dragLeaveEvent(self, ev) -> None:
        self.drop_zone.setProperty("active", False)
        self.drop_zone.style().polish(self.drop_zone)

    def dropEvent(self, ev) -> None:
        self.dragLeaveEvent(ev)
        files = self._drop_files(ev)
        if len(files) == 1:
            self.load_path(files[0])
        elif len(files) > 1:
            self.open_batch(files)
        elif ev.mimeData().hasImage():
            qimg = ev.mimeData().imageData()
            if qimg is not None:
                self._set_source(im.from_pil(qimage_to_pil(qimg)))
        ev.acceptProposedAction()

    # ==================================================================
    # Geometry edits / undo
    # ==================================================================
    def _push_undo(self, key: Optional[str] = None) -> None:
        if not self.src:
            return
        if key is not None and key == self._undo_key:
            return
        self._undo_key = key
        self.undo_stack.append((self.state.copy(), self.keep_original, self.tw, self.th))
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self._update_buttons()

    def _restore(self, snap) -> None:
        self.state, self.keep_original, self.tw, self.th = snap[0].copy(), snap[1], snap[2], snap[3]
        self._undo_key = None
        self._refresh_all()

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append((self.state.copy(), self.keep_original, self.tw, self.th))
        self._restore(self.undo_stack.pop())

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append((self.state.copy(), self.keep_original, self.tw, self.th))
        self._restore(self.redo_stack.pop())

    def rotate(self, clockwise: bool) -> None:
        if not self.src:
            return
        self._push_undo()
        self.state = im.rotate_state(self.state, self.src.image.size, clockwise)
        if not self.keep_original:
            self.tw, self.th = self.th, self.tw
        self._refresh_all()

    def flip(self, horizontal: bool) -> None:
        if not self.src:
            return
        self._push_undo()
        self.state = im.flip_state(self.state, self.src.image.size, horizontal)
        self._refresh_all()

    def reset_all(self) -> None:
        if not self.src:
            return
        self._push_undo()
        self.state = im.EditState()
        self.keep_original = True
        self.cb_ratio.blockSignals(True)
        self.cb_ratio.setCurrentIndex(0)
        self.cb_ratio.blockSignals(False)
        self._refresh_all()
        self.statusBar().showMessage("Reset to the original image.", 3000)

    # ==================================================================
    # Size logic
    # ==================================================================
    def base_size(self):
        if not self.src:
            return (0, 0)
        return im.edited_size(self.src.image.size, self.state)

    def _unit(self) -> str:
        return self.cb_unit.currentText()

    def _refresh_spins(self) -> None:
        bw, bh = self.base_size()
        unit, dpi = self._unit(), self.sp_dpi.value()
        dec = UNIT_DECIMALS[unit]
        for sp, px, base in ((self.sp_w, self.tw, bw), (self.sp_h, self.th, bh)):
            sp.blockSignals(True)
            sp.setDecimals(dec)
            sp.setSuffix("" if unit == "px" else f" {unit}")
            sp.setValue(im.from_pixels(px, unit, dpi, base) if px else 0)
            sp.blockSignals(False)
        self._update_size_info()

    def _on_w_changed(self, v: float) -> None:
        if not self.src:
            return
        bw, bh = self.base_size()
        self._push_undo("size")
        self.tw = min(im.MAX_OUTPUT_SIDE, im.to_pixels(v or 1, self._unit(), self.sp_dpi.value(), bw))
        if self.btn_link.isChecked():
            self.th = max(1, round(self.tw * bh / bw))
        self._size_edited()

    def _on_h_changed(self, v: float) -> None:
        if not self.src:
            return
        bw, bh = self.base_size()
        self._push_undo("size")
        self.th = min(im.MAX_OUTPUT_SIDE, im.to_pixels(v or 1, self._unit(), self.sp_dpi.value(), bh))
        if self.btn_link.isChecked():
            self.tw = max(1, round(self.th * bw / bh))
        self._size_edited()

    def _size_edited(self) -> None:
        self.keep_original = (self.tw, self.th) == self.base_size()
        self._check_preset_buttons()
        self._refresh_spins()
        self._schedule()

    def _on_link_toggled(self, on: bool) -> None:
        self.btn_link.setIcon(icon("link" if on else "unlink", "#334155", WHITE))
        if self.chk_ratio.isChecked() != on:
            self.chk_ratio.blockSignals(True)
            self.chk_ratio.setChecked(on)
            self.chk_ratio.blockSignals(False)
        if on and self.src and not self.keep_original:
            bw, bh = self.base_size()
            self.th = max(1, round(self.tw * bh / bw))
            self._refresh_spins()
            self._schedule()
        self._update_size_info()

    def _on_dpi_changed(self, _v) -> None:
        if self._unit() in ("cm", "mm", "in") and self.src and not self.keep_original:
            # keep the physical size: more DPI -> more pixels
            dpi, unit = self.sp_dpi.value(), self._unit()
            wv, hv = self.sp_w.value(), self.sp_h.value()
            self._push_undo("size")
            self.tw = min(im.MAX_OUTPUT_SIDE, im.to_pixels(wv, unit, dpi, 0))
            self.th = min(im.MAX_OUTPUT_SIDE, im.to_pixels(hv, unit, dpi, 0))
            self._size_edited()
        self._update_size_info()
        self._on_option_changed()

    def apply_preset(self, w, h, unit, dpi, label="") -> None:
        if not self.src:
            self.statusBar().showMessage("Open an image first.", 3000)
            self._check_preset_buttons()
            return
        self._push_undo()
        if w == 0:
            self.keep_original = True
            self.tw, self.th = self.base_size()
        else:
            if dpi:
                self.sp_dpi.blockSignals(True)
                self.sp_dpi.setValue(dpi)
                self.sp_dpi.blockSignals(False)
                self.cb_unit.blockSignals(True)
                self.cb_unit.setCurrentText(unit)
                self.cb_unit.blockSignals(False)
            d = dpi or self.sp_dpi.value()
            self.tw = im.to_pixels(w, unit, d, 0)
            self.th = im.to_pixels(h, unit, d, 0)
            bw, bh = self.base_size()
            # A preset is an exact box; unlock the ratio when its shape differs
            if abs(self.tw / self.th - bw / bh) > 0.01:
                self.btn_link.blockSignals(True)
                self.btn_link.setChecked(False)
                self.btn_link.blockSignals(False)
                self._on_link_toggled(False)
            self.keep_original = (self.tw, self.th) == (bw, bh)
        self._check_preset_buttons()
        self._refresh_spins()
        self._schedule()
        if label:
            self.statusBar().showMessage(f"Size preset: {label}", 3000)

    def _check_preset_buttons(self) -> None:
        self.preset_group.setExclusive(False)
        for i, (_l, w, h) in enumerate(QUICK_PRESETS):
            b = self.preset_group.button(i)
            b.setChecked(bool(self.src) and ((w == 0 and self.keep_original) or
                                             (w and (w, h) == (self.tw, self.th))))
        self.preset_group.setExclusive(True)

    def _update_size_info(self) -> None:
        if not hasattr(self, "size_info"):
            return
        mode = self.cb_fit.currentData()
        self.cb_bg.setEnabled(mode == im.MODE_FIT_PAD)
        self.lbl_bg.setEnabled(mode == im.MODE_FIT_PAD)
        is_custom = self.cb_bg.currentData() == im.BG_CUSTOM
        self.btn_color.setVisible(is_custom)
        c = QColor(*self.custom_color)
        self.btn_color.setStyleSheet(f"background:{c.name()};border:1px solid #94a3b8;border-radius:6px;")
        if not self.src:
            self.size_info.setText("")
            self.shape_hint.setText("")
            return
        bw, bh = self.base_size()
        tw, th = self.tw, self.th
        shape_diff = abs(tw / th - bw / bh) > 0.005
        self.shape_hint.setVisible(shape_diff)
        self.shape_hint.setText("The new size has a different shape from your image. "
                                "Fit keeps the whole picture (nothing is cut off).")
        scale = max(tw / bw, th / bh) if mode in (im.MODE_FILL, im.MODE_STRETCH) else min(tw / bw, th / bh)
        lines = [f"<b>Output:</b> {tw} × {th} px"]
        dpi = self.sp_dpi.value()
        lines.append(f"<b>Print size:</b> {im.print_size_text(tw, th, dpi)}")
        lines.append(f"<b>Area:</b> {proof.area_label(tw / dpi, th / dpi)}  "
                     f"({proof.area_label(tw / dpi, th / dpi, 'sqm')})")
        method = self.cb_up.currentData()
        if scale > 1.01 and self.chk_allow_up.isChecked():
            txt = f"<b>Enlarging {scale:.2f}×</b> – "
            if method == im.UPSCALE_STANDARD:
                txt += "<span style='color:#b45309'>Standard can look soft. Choose Enhanced or AI.</span>"
            elif method in (im.UPSCALE_AI_PHOTO, im.UPSCALE_AI_ART):
                if self.ai.available():
                    txt += "<span style='color:#15803d'>AI rebuilds fine detail.</span>"
                else:
                    txt += (f"<span style='color:#b45309'>{self.ai.status_text()} – "
                            "Enhanced will be used.</span>")
            else:
                txt += "<span style='color:#15803d'>Enhanced keeps edges sharp.</span>"
                if scale > 2.5:
                    txt += " For the most detail try AI Super-Resolution."
            lines.append(txt)
            ppi = min(bw / (tw / dpi), bh / (th / dpi))
            if ppi < 150:
                lines.append(f"<span style='color:#b45309'>The original has about {ppi:.0f} real pixels "
                             f"per inch at this print size.</span>")
        elif scale < 0.99:
            lines.append(f"<b>Reducing</b> to {scale * 100:.0f}% – sharp downscaling.")
        self.size_info.setText("<br>".join(lines))

    # ==================================================================
    # Crop logic
    # ==================================================================
    def _set_mode(self, idx: int) -> None:
        self.mode_group.button(idx).setChecked(True)
        self.stack.setCurrentIndex(idx)
        self.left_stack.setCurrentIndex(idx)
        self._update_titles()

    def _current_ratio(self) -> Optional[float]:
        a, b = self.cb_ratio.currentData() or (0, 0)
        if a == 0:
            return None
        if a == -1:
            if not self.src:
                return None
            a, b = im.oriented_size(self.src.image.size, self.state)
        r = a / b
        if self.btn_swap.isChecked():
            r = 1 / r
        return r

    def _on_ratio_changed(self, *_):
        self._push_undo()
        self.canvas.set_ratio(self._current_ratio())

    def _on_canvas_rect(self, rect) -> None:
        if not self.src:
            return
        W, H = im.oriented_size(self.src.image.size, self.state)
        self.state.crop = im.clamp_crop(rect, (W, H))
        self._after_crop_change()

    def _on_crop_spin(self, which: str) -> None:
        if not self.src:
            return
        self._push_undo("crop-spin")
        W, H = im.oriented_size(self.src.image.size, self.state)
        x, y, w, h = self.cr_x.value(), self.cr_y.value(), self.cr_w.value(), self.cr_h.value()
        r = self._current_ratio()
        if r:
            if which == "Height":
                w = round(h * r)
            else:
                h = round(w / r)
        self.state.crop = im.clamp_crop((x, y, w, h), (W, H))
        self.canvas.set_rect(self.state.crop)
        self._after_crop_change()

    def _after_crop_change(self) -> None:
        bw, bh = self.base_size()
        if self.keep_original:
            self.tw, self.th = bw, bh
        elif self.btn_link.isChecked():
            self.th = max(1, round(self.tw * bh / bw))
        self._refresh_crop_spins()
        self._refresh_spins()
        self._update_titles()
        self._schedule()

    def _refresh_crop_spins(self) -> None:
        if not self.src:
            return
        W, H = im.oriented_size(self.src.image.size, self.state)
        x, y, w, h = self.state.crop or (0, 0, W, H)
        for sp, v, mx in ((self.cr_x, x, W - 1), (self.cr_y, y, H - 1), (self.cr_w, w, W), (self.cr_h, h, H)):
            sp.blockSignals(True)
            sp.setRange(0 if sp in (self.cr_x, self.cr_y) else 1, mx)
            sp.setValue(v)
            sp.blockSignals(False)
        self.crop_info.setText(
            f"<b>Crop:</b> {w} × {h} px &nbsp;→&nbsp; <b>Output:</b> {self.tw} × {self.th} px"
            "<br>To print or share at a set size, pick it on the Resize tab after cropping.")

    def crop_select_all(self) -> None:
        if not self.src:
            return
        self._push_undo()
        W, H = im.oriented_size(self.src.image.size, self.state)
        self.canvas.set_rect((0, 0, W, H))
        r = self._current_ratio()
        if r:
            self.canvas.set_ratio(r)
        else:
            self.state.crop = None
            self._after_crop_change()

    def crop_clear(self) -> None:
        if not self.src:
            return
        self._push_undo()
        self.state.crop = None
        self.canvas.set_rect(None)
        self._after_crop_change()

    # ==================================================================
    # Options
    # ==================================================================
    def _fmt(self) -> str:
        for k, b in self.fmt_buttons.items():
            if b.isChecked():
                return k
        return "JPG"

    def _on_fmt_changed(self, fmt: str) -> None:
        lossy = fmt in ("JPG", "WEBP", "PDF")
        lossless_webp = fmt == "WEBP" and self.chk_lossless.isChecked()
        self.sl_q.setEnabled(lossy and not lossless_webp)
        self.lbl_q.setEnabled(lossy and not lossless_webp)
        self.chk_lossless.setVisible(fmt == "WEBP")
        self.chk_target.setEnabled(fmt in ("JPG", "WEBP"))
        self._on_option_changed()

    def _on_option_changed(self, *_):
        if hasattr(self, "chk_lossless"):
            fmt = self._fmt()
            lossy = fmt in ("JPG", "WEBP", "PDF") and not (fmt == "WEBP" and self.chk_lossless.isChecked())
            self.sl_q.setEnabled(lossy)
        self._update_size_info()
        self._schedule()

    def _on_bg_activated(self, idx: int) -> None:
        if self.cb_bg.itemData(idx) == im.BG_CUSTOM:
            self._pick_color()

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(*self.custom_color), self, "Background colour")
        if c.isValid():
            self.custom_color = (c.red(), c.green(), c.blue())
            self._update_size_info()
            self._schedule()

    def _set_wa_target(self, target: str) -> None:
        self.wa_target = target
        self.act_wa_web.setChecked(target == "web")
        self.act_wa_desk.setChecked(target == "desktop")
        where = "WhatsApp Web" if target == "web" else "WhatsApp Desktop"
        phone = f" · chat {self.wa_phone}" if getattr(self, "wa_phone", "") else ""
        self.wa_sub.setText(f"Saves the image, copies it and opens {where}{phone}")

    def _ask_phone(self) -> None:
        txt, ok = QInputDialog.getText(
            self, "WhatsApp chat",
            "Phone number with country code (e.g. 447700900123).\nLeave empty to just open WhatsApp:",
            text=self.wa_phone)
        if ok:
            self.wa_phone = share.clean_phone(txt)
            self._set_wa_target(self.wa_target)

    def current_settings(self):
        rs = im.ResizeSettings(
            enabled=not self.keep_original and self.tw > 0 and self.th > 0,
            width=self.tw, height=self.th, mode=self.cb_fit.currentData(),
            background=self.cb_bg.currentData(), custom_color=self.custom_color,
            upscale=self.cb_up.currentData(),
            sharpen=-1 if self.chk_sharp_auto.isChecked() else self.sl_sharp.value(),
            allow_upscale=self.chk_allow_up.isChecked())
        os_ = im.OutputSettings(
            fmt=self._fmt(), quality=self.sl_q.value(), webp_lossless=self.chk_lossless.isChecked(),
            target_kb=self.sp_target.value() if (self.chk_target.isChecked() and self.chk_target.isEnabled()) else 0,
            dpi=self.sp_dpi.value(), strip_metadata=self.chk_strip.isChecked())
        return rs, os_

    # ==================================================================
    # Processing
    # ==================================================================
    def _schedule(self) -> None:
        self.gen += 1
        if self.src:
            self.timer.start()

    def _run_process(self) -> None:
        if not self.src:
            return
        rs, os_ = self.current_settings()
        job = ProcessJob(self.gen, self.src, self.state.copy(), rs, os_, self.ai)
        job.signals.finished.connect(self._on_result)
        job.signals.failed.connect(self._on_failed)
        job.signals.progress.connect(self._on_progress)
        self.jobs.add(job)
        self.busy.setVisible(True)
        self.pool.start(job)

    def _on_progress(self, gen: int, msg: str) -> None:
        if gen == self.gen:
            self.statusBar().showMessage(msg)

    def _job_done(self, gen) -> None:
        self.jobs = {j for j in self.jobs if j.gen != gen}
        if not self.jobs:
            self.busy.setVisible(False)

    def _on_result(self, gen: int, res: im.ProcessResult) -> None:
        self._job_done(gen)
        if gen != self.gen:
            return
        self.result, self.result_gen = res, gen
        self._show_result(res)
        self.ai_label.setText(self.ai.status_text())
        if res.notes:
            self.statusBar().showMessage("  ".join(res.notes), 8000)
        else:
            self.statusBar().clearMessage()
        self._update_size_info()
        self.processed.emit()

    def _on_failed(self, gen: int, msg: str) -> None:
        self._job_done(gen)
        if gen == self.gen:
            self.statusBar().showMessage(f"Problem: {msg}", 10000)
            self.out_info.setText(f"<span style='color:#b91c1c'>{msg}</span>")
            self.processed.emit()

    def _update_out_info(self) -> None:
        res = self.result
        if not res:
            self.out_info.setText("")
            self.out_title.setText("Result")
            return
        w, h = res.image.size
        self.out_title.setText(f"Result  ({w} × {h})")
        q = f", quality {res.quality_used}%" if res.quality_used and res.fmt != "PNG" else ""
        self.out_info.setText(f"Size: {w} × {h} px   ·   File size: {im.human_size(res.size_bytes)} "
                              f"({res.fmt}{q})")

    def _update_titles(self) -> None:
        if not self.src:
            self.orig_title.setText("Original Image" if self.stack.currentIndex() == 0 else "Select crop area")
            self.orig_info.setText("")
            return
        W, H = im.oriented_size(self.src.image.size, self.state)
        if self.stack.currentIndex() == 0:
            self.orig_title.setText(f"Original Image  ({W} × {H})")
        else:
            self.orig_title.setText("Select crop area")
        fs = f"   ·   File size: {im.human_size(self.src.file_size)}" if self.src.file_size else ""
        self.orig_info.setText(f"Size: {W} × {H} px{fs}")

    def _oriented_qimage(self):
        key = (id(self.src), self.state.rotation, self.state.flip_h, self.state.flip_v)
        if key != self._oriented_key:
            self._oriented_key = key
            self._oriented_qimg = pil_to_qimage(im.apply_orientation(self.src.image, self.state))
        return self._oriented_qimg

    def _refresh_all(self, new_image: bool = False) -> None:
        has = self.src is not None
        for w in (self.btn_save, self.btn_copy, self.btn_proof, self.btn_wa, self.btn_reset, self.b_rot_l,
                  self.b_rot_r, self.b_flip_h, self.b_flip_v):
            w.setEnabled(has)
        if not has:
            self.view_orig.set_image(None)
            self.view_out.set_image(None)
            self.cu_before.set_image(None)
            self.cu_after.set_image(None)
            self.canvas.set_image(None)
            self._update_titles()
            self._update_buttons()
            self._update_size_info()
            return
        qimg = self._oriented_qimage()
        self.view_orig.set_image(qimg, keep_view=not new_image)
        self.canvas.set_image(qimg)
        self.canvas.set_ratio(None)
        self.canvas.set_rect(self.state.crop)
        self.canvas._ratio = self._current_ratio()
        bw, bh = self.base_size()
        if self.keep_original:
            self.tw, self.th = bw, bh
        self._refresh_crop_spins()
        self._refresh_spins()
        self._check_preset_buttons()
        self._update_titles()
        self._update_buttons()
        self._schedule()

    def _update_buttons(self) -> None:
        self.b_undo.setEnabled(bool(self.undo_stack))
        self.b_redo.setEnabled(bool(self.redo_stack))

    def _fresh_result(self) -> Optional[im.ProcessResult]:
        """Up-to-date result; computes now if the preview is still pending."""
        if not self.src:
            return None
        if self.result is not None and self.result_gen == self.gen:
            return self.result
        self.timer.stop()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rs, os_ = self.current_settings()
            res = im.process(self.src, self.state.copy(), rs, os_, self.ai)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Could not process image", str(exc))
            return None
        QApplication.restoreOverrideCursor()
        self.result, self.result_gen = res, self.gen
        self._show_result(res)
        return res

    # ==================================================================
    # Result display + close-up (loupe)
    # ==================================================================
    def _show_result(self, res: im.ProcessResult) -> None:
        old = self.result_size if hasattr(self, "result_size") else None
        self._result_qimg = pil_to_qimage(res.image)
        self.view_out.set_image(self._result_qimg, keep_view=True)
        self.cu_after.set_image(self._result_qimg)
        self.cu_before.set_image(self._oriented_qimage())
        self.result_size = res.image.size
        if self._cu_pt is None or old != res.image.size:
            if self._cu_pt is not None and old:
                # keep the same relative spot when the size changes
                self._cu_pt = (self._cu_pt[0] / old[0] * res.image.width,
                               self._cu_pt[1] / old[1] * res.image.height)
            else:
                self._cu_pt = (res.image.width / 2, res.image.height / 2)
        self._update_out_info()
        self._update_closeup()

    def _cu_settings(self):
        rs, _os = self.current_settings()
        return rs

    def _update_closeup(self) -> None:
        if not self.src or not self.result or self._cu_pt is None:
            self.view_out.set_marker(None)
            return
        rx, ry = self._cu_pt
        z = self.cb_cu_zoom.currentData() or 2.0
        self.cu_after.look(z, rx, ry)
        sx, sy, k = im.result_to_source((rx, ry), self.src, self.state, self._cu_settings(),
                                        self.result.image.size)
        self.cu_before.look(z * k, sx, sy)
        # outline the inspected area on the result preview
        vw = self.cu_after.viewport().width() / z
        vh = self.cu_after.viewport().height() / z
        self.view_out.set_marker(QRectF(rx - vw / 2, ry - vh / 2, vw, vh))
        mag = z * k
        self.cu_hint.setText(
            f"Showing {z * 100:.0f}% of the result ({mag:.1f}× the original pixels). "
            + ("Pinned – click to unpin." if self._cu_pinned else "Click to pin this spot."))

    def _on_out_hover(self, x: float, y: float) -> None:
        if self._cu_pinned or not self.result:
            return
        w, h = self.result.image.size
        if 0 <= x <= w and 0 <= y <= h:
            self._cu_pt = (x, y)
            self._update_closeup()

    def _on_out_click(self, x: float, y: float) -> None:
        self._cu_pinned = not self._cu_pinned
        if self._cu_pinned and self.result:
            self._cu_pt = (min(max(x, 0), self.result.image.width), min(max(y, 0), self.result.image.height))
        self._update_closeup()

    def _on_orig_hover(self, x: float, y: float) -> None:
        if self._cu_pinned or not self.result or not self.src:
            return
        rx, ry = im.source_to_result((x, y), self.src, self.state, self._cu_settings(),
                                     self.result.image.size)
        w, h = self.result.image.size
        if 0 <= rx <= w and 0 <= ry <= h:
            self._cu_pt = (rx, ry)
            self._update_closeup()

    def _on_orig_click(self, x: float, y: float) -> None:
        if not self.result or not self.src:
            return
        rx, ry = im.source_to_result((x, y), self.src, self.state, self._cu_settings(),
                                     self.result.image.size)
        self._on_out_click(rx, ry)

    def quick_upscale(self, k: int) -> None:
        if not self.src:
            self.statusBar().showMessage("Open an image first.", 3000)
            return
        self._push_undo()
        bw, bh = self.base_size()
        if bw * k > im.MAX_OUTPUT_SIDE or bh * k > im.MAX_OUTPUT_SIDE:
            QMessageBox.information(self, "Too large",
                                    f"{bw * k} × {bh * k} px is larger than the limit "
                                    f"({im.MAX_OUTPUT_SIDE} px). Try a smaller factor or crop first.")
            return
        self.keep_original = False
        self.tw, self.th = bw * k, bh * k
        self.btn_link.setChecked(True)
        if self.cb_up.currentData() not in (im.UPSCALE_AI_PHOTO, im.UPSCALE_AI_ART):
            self._select_data(self.cb_up, im.UPSCALE_AI_PHOTO if self.ai.available() else im.UPSCALE_ENHANCED)
        self._check_preset_buttons()
        self._refresh_spins()
        self._schedule()
        how = "AI Super-Resolution" if self.cb_up.currentData() in (im.UPSCALE_AI_PHOTO, im.UPSCALE_AI_ART) \
            and self.ai.available() else "Enhanced"
        self.statusBar().showMessage(f"Upscaling {k}× to {self.tw} × {self.th} px with {how}…", 5000)

    def open_proof(self) -> None:
        res = self._fresh_result()
        if not res:
            self.statusBar().showMessage("Open an image first.", 3000)
            return
        name = self.src.path.name if self.src and self.src.path else None
        dlg = ProofDialog(self, res.image, name, self.sp_dpi.value(), self.wa_target, self.wa_phone)
        dlg.exec()

    # ==================================================================
    # Save / copy / share
    # ==================================================================
    def _default_name(self, res: im.ProcessResult) -> str:
        src_name = self.src.path.name if self.src and self.src.path else "image"
        return im.auto_filename(src_name, res.image.width, res.image.height, res.fmt)

    def save_image(self) -> Optional[Path]:
        res = self._fresh_result()
        if not res:
            return None
        start_dir = self.settings.value("last_save_dir", "")
        if not start_dir:
            start_dir = str(self.src.path.parent) if self.src.path else str(Path.home() / "Pictures")
        ext = im.FORMATS[res.fmt]["ext"]
        flt = f"{res.fmt} image (*{ext})"
        path, _ = QFileDialog.getSaveFileName(self, "Save image", str(Path(start_dir) / self._default_name(res)), flt)
        if not path:
            return None
        p = Path(path)
        if p.suffix.lower() not in (ext, ".jpeg" if res.fmt == "JPG" else ext):
            p = p.with_suffix(ext)
        try:
            p.write_bytes(res.data)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return None
        self.settings.setValue("last_save_dir", str(p.parent))
        self._last_saved = p
        self.statusBar().showMessage(f"Saved {p.name} ({im.human_size(res.size_bytes)})", 6000)
        if self.chk_open_folder.isChecked():
            share.show_in_folder(p)
        return p

    def _write_temp(self, res: im.ProcessResult, folder: Path) -> Path:
        p = im.unique_path(folder / self._default_name(res))
        p.write_bytes(res.data)
        return p

    def copy_result(self) -> None:
        res = self._fresh_result()
        if not res:
            return
        try:
            f = self._write_temp(res, share.temp_folder())
        except OSError:
            f = None
        share.copy_to_clipboard(pil_to_qimage(res.image), f)
        self.statusBar().showMessage("Copied! Press Ctrl+V in WhatsApp, email, Word or any app.", 6000)

    def share_whatsapp(self) -> None:
        res = self._fresh_result()
        if not res:
            return
        try:
            path = self._write_temp(res, share.share_folder())
        except OSError as exc:
            QMessageBox.warning(self, "Could not prepare image", str(exc))
            return
        share.copy_to_clipboard(pil_to_qimage(res.image), path)
        opened = share.open_whatsapp(self.wa_target, self.wa_phone)
        where = "WhatsApp Web" if opened == "web" else "WhatsApp Desktop"
        box = QMessageBox(self)
        box.setWindowTitle("Ready to send on WhatsApp")
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<b>Your image is ready and copied.</b> {where} is opening.<br><br>"
            "<b>Quick send:</b> open the chat and press <b>Ctrl+V</b>, then Send.<br><br>"
            "<b>Full quality (no WhatsApp compression):</b> click <b>+</b> / the paper-clip, choose "
            "<b>Document</b>, then pick this file:<br>"
            f"<code>{html.escape(str(path))}</code>")
        b_folder = box.addButton("Show file in folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is b_folder:
            share.show_in_folder(path)

    def open_batch(self, files) -> None:
        rs, os_ = self.current_settings()
        start = str(self.settings.value("last_open_dir", str(Path.home())))
        dlg = BatchDialog(self, files, rs, os_, self.ai, self.exts, start)
        dlg.exec()

    def show_help(self) -> None:
        QMessageBox.information(self, "Shortcuts & tips", (
            f"Image Resize & Share {__version__}\n\n"
            "Ctrl+O  Open image          Ctrl+V  Paste image\n"
            "Ctrl+S  Save                 Ctrl+Shift+C  Copy result\n"
            "Ctrl+W  WhatsApp            Ctrl+B  Batch mode\n"
            "Ctrl+P  Proof sheet (size, sq ft, note)\n"
            "Ctrl+Z / Ctrl+Y  Undo / Redo\n"
            "Ctrl+R / Ctrl+L  Rotate right / left\n"
            "Ctrl+1 / Ctrl+2  Resize / Crop tab\n\n"
            "Preview: mouse wheel = zoom, drag = pan, double-click = 100% / fit.\n"
            "Close-up: hover the preview to inspect, click to pin the spot.\n\n"
            "Quality tips:\n"
            "• For enlarging, use Enhanced or AI Super-Resolution.\n"
            "• JPG at 90–95% looks the same as the original; PNG is lossless.\n"
            "• On WhatsApp, send as Document to avoid compression."))

    def closeEvent(self, ev) -> None:
        self._save_settings()
        self.pool.waitForDone(3000)
        super().closeEvent(ev)
