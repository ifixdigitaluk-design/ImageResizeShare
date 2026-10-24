"""Main window of Image Resize, Crop & Share (layout follows the design mockups).

  ┌ Image Editor │ Resize  Crop  AI Upscale  Preview │ Download  Print Preview │ WhatsApp Share ┐
  │ 1. Upload Image      │ 3. Image Preview                   │ 4. Crop Image        │
  │ 2. Resize & Crop     │   (zoom slider, %, full screen)     │   Crop Size, Reset   │
  │    Download settings │ 5. Download & Share  [Download Preview] [Closeup Print Preview]
  │                      │                      [Download Print File] [Open in WhatsApp]
"""
from __future__ import annotations

import html
import math
from dataclasses import replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QSplitter, QStackedWidget, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

from app import __version__
from app.core import imaging as im
from app.core import sheets as sh
from app.core.ai_upscale import get_engine
from app.core.presets import CROP_RATIOS, QUICK_PRESETS, SIZE_PRESETS
from app.core.upscale import MODES
from app.ui import share
from app.ui.batch import BatchDialog
from app.ui.preview_dialogs import (CloseupPrintPreviewDialog, DownloadPreviewDialog, FullscreenViewer,
                                    PreviewContext)
from app.ui.proof_dialog import ProofDialog
from app.ui.qtutil import (Card, ElidedLabel, TwoLineButton, app_icon, hint, icon, pil_to_qimage,
                           qimage_to_pil, section, svg_pixmap)
from app.ui.upscale_dialog import UpscaleDialog
from app.ui.views import CloseUpView, CropCanvas, ZoomView
from app.ui.worker import ProcessJob

BLUE = "#155fc0"
WHITE = "#ffffff"
SLATE = "#334155"

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
ZOOM_MIN, ZOOM_MAX = 0.05, 8.0


class ClickFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class Collapsible(QFrame):
    """A header you click to show / hide a section."""

    def __init__(self, title: str, expanded: bool = False, card: bool = False, parent=None):
        super().__init__(parent)
        if card:
            self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*((16, 12, 16, 12) if card else (0, 0, 0, 0)))
        outer.setSpacing(8)
        head = QHBoxLayout()
        self.btn = QToolButton()
        self.btn.setObjectName("Flat")
        self.btn.setText("  " + title)
        self.btn.setCheckable(True)
        self.btn.setChecked(expanded)
        self.btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn.setIconSize(QSize(16, 16))
        self.btn.setStyleSheet("QToolButton{font-weight:600;font-size:%s;background:transparent;border:none;"
                               "padding:2px 0px;color:#0f172a;} QToolButton:checked{background:transparent;"
                               "color:#0f172a;}" % ("11.5pt" if card else "10pt"))
        head.addWidget(self.btn)
        head.addStretch()
        self.summary = QLabel("")
        self.summary.setObjectName("Hint")
        head.addWidget(self.summary)
        outer.addLayout(head)
        self.content = QWidget()
        self.lay = QVBoxLayout(self.content)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        outer.addWidget(self.content)
        self.btn.toggled.connect(self._toggle)
        self._toggle(expanded)

    def _toggle(self, on: bool) -> None:
        self.content.setVisible(on)
        self.btn.setIcon(icon("chev_down" if on else "chev_right", "#475569"))


class MainWindow(QMainWindow):
    processed = Signal()  # emitted after each preview update (used by self-test)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Resize, Crop & Share")
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.resize(1440, 930)
        self.setMinimumSize(1180, 740)

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
        self.result_size = None
        self.custom_color = (255, 255, 255)
        self._oriented_key = None
        self._oriented_qimg = None
        self._last_saved: Optional[Path] = None
        self._cu_pt = None          # close-up point in result pixels
        self._cu_pinned = False
        self._before_upscale = None  # (LoadedImage, EditState, label) to undo an AI upscale
        self._print_override = None  # ((w, h), dpi, PrintSpec) chosen in a preview dialog

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._run_process)
        self._cu_timer = QTimer(self)                 # close-up: real pixels of a big print
        self._cu_timer.setSingleShot(True)
        self._cu_timer.setInterval(120)
        self._cu_timer.timeout.connect(self._request_tile)

        self._build_ui()
        self._build_actions()
        self._load_settings()
        self._set_mode(0)
        self.set_page(0)
        self._refresh_all()

    # ==================================================================
    # UI construction
    # ==================================================================
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_nav())
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)

        # ---------------- page 0: Image Editor (as in the mockup) ----------------
        editor = QWidget()
        cl = QHBoxLayout(editor)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(14)
        left_inner = QWidget()
        left_inner.setObjectName("LeftInner")
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(14)
        left.addWidget(self._build_upload_card())
        left.addWidget(self._build_edit_card(), 1)
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.left_scroll.setWidget(left_inner)
        self.left_scroll.setFixedWidth(384)
        cl.addWidget(self.left_scroll)
        right = QVBoxLayout()
        right.setSpacing(14)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(self._build_preview_card(), 1)
        top.addWidget(self._build_crop_card())
        right.addLayout(top, 1)
        right.addWidget(self._build_share_card())
        cl.addLayout(right, 1)
        self.pages.addWidget(self._scrollable(editor))
        # pages 1 / 2 (Wall Studio, Jobs) are created the first time they are opened
        self.studio = None
        self.jobs_page = None
        self.pages.addWidget(QWidget())
        self.pages.addWidget(QWidget())

        # advanced settings live in one dialog (keeps the main screen like the mockup)
        self.settings_dlg = self._build_settings_dialog()
        self._on_link_toggled(True)

        # ---------- status bar ----------
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
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
    def _build_nav(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("NavBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(0)
        self.nav = {}
        self.mode_tabs = []

        def nav_btn(ic, text, slot, tip):
            b = QToolButton()
            b.setObjectName("NavBtn")
            b.setText(" " + text)
            b.setIcon(icon(ic, "#1e293b"))
            b.setIconSize(QSize(24, 24))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        def sep():
            s = QFrame()
            s.setObjectName("NavSep")
            s.setFixedSize(1, 26)
            return s

        for i, (ic, text, tip) in enumerate((("home", "Image Editor", "Resize, crop, preview and share one image"),
                                              ("wall", "Wall Studio", "Professional wallpaper & mural jobs"),
                                              ("briefcase", "Jobs", "All jobs, design library and showroom"))):
            b = nav_btn(ic, text, lambda _=False, i=i: self.set_page(i), tip)
            lay.addWidget(b)
            self.mode_tabs.append(b)
            self.nav[text] = b
        lay.addSpacing(6)
        lay.addWidget(sep(), 0, Qt.AlignmentFlag.AlignVCenter)

        groups = {
            0: [[("resize", "Resize", lambda: self._set_mode(0), "Resize options (Ctrl+1)"),
                 ("crop", "Crop", lambda: self._set_mode(1), "Crop options (Ctrl+2)"),
                 ("eye", "Preview", self.open_download_preview, "Customer preview with size and area (Ctrl+P)")],
                [("download", "Download", self.save_image, "Download the print file (Ctrl+S)"),
                 ("printer", "Print Preview", self.open_closeup_preview, "Closeup print preview (Ctrl+Shift+P)")],
                [("whatsapp", "WhatsApp Share", self.share_whatsapp, "Prepare and open WhatsApp (Ctrl+W)")]],
            1: [[("ruler", "Measure", lambda: self._studio_call("open_measure"), "Measure a wall from a photo"),
                 ("sofa", "Room View", lambda: self._studio_call("open_room"), "See the design in a room"),
                 ("palette", "Colour", lambda: self._studio_call("open_colour"), "Print check, colour match, colourways"),
                 ("pattern", "Pattern", lambda: self._studio_call("open_pattern"), "Repeating wallpaper pattern")],
                [("doc", "Proof", lambda: self._studio_call("open_proof"), "Customer proof with approval box"),
                 ("send_print", "Send to Print", lambda: self._studio_call("open_print"), "Preflight and print files")],
                [("whatsapp", "WhatsApp Share", lambda: self._studio_call("share_whatsapp"), "Send the proof on WhatsApp")]],
            2: [[("plus", "New Job", lambda: self._jobs_call("new_job"), "Start a new job"),
                 ("calendar", "Installs", lambda: self._jobs_call("show_installs"),
                  "Fitting dates, WhatsApp reminders and finished-job posts"),
                 ("books", "Library", lambda: self._jobs_call("show_library"), "Your design library"),
                 ("play", "Showroom", lambda: self._jobs_call("open_showroom"), "Full-screen gallery for customers")],
                [("user", "Business", self.open_business, "Name, logo and contact on proofs and sheets"),
                 ("send_print", "Presets", self.open_presets, "Print file formats, colour and hot folders"),
                 ("cloud_up", "Online AI", self.open_cloud, "Online upscaling and AI expand (Replicate account)"),
                 ("backup", "Backup", self.open_data, "Data folder (OneDrive / shared), backup and restore"),
                 ("help", "Help", self.open_help_menu, "Send an error report, check for updates, about the app")]],
        }
        self.nav_groups = {}
        for mode, glist in groups.items():
            w = QWidget()
            gl = QHBoxLayout(w)
            gl.setContentsMargins(0, 0, 0, 0)
            gl.setSpacing(0)
            gl.addStretch(1)
            for gi, items in enumerate(glist):
                if gi:
                    gl.addStretch(1)
                    gl.addWidget(sep(), 0, Qt.AlignmentFlag.AlignVCenter)
                    gl.addStretch(1)
                for k, (ic, text, slot, tip) in enumerate(items):
                    if k:
                        gl.addStretch(1)
                    b = nav_btn(ic, text, slot, tip)
                    gl.addWidget(b)
                    self.nav[text if mode == 0 else f"{mode}:{text}"] = b
            gl.addStretch(1)
            self.nav_groups[mode] = w
            lay.addWidget(w, 1)
        return bar

    # ------------------------------------------------------------------
    # Help: error report, updates, about
    # ------------------------------------------------------------------
    def open_help_menu(self) -> None:
        from app.ui import support
        m = QMenu(self)
        m.addAction(icon("bug"), "Send an error report…", lambda: support.send_error_report(self))
        m.addAction(icon("update"), "Check for updates now", lambda: self.check_updates(manual=True))
        auto = m.addAction("Check for updates automatically")
        auto.setCheckable(True)
        auto.setChecked(support.auto_check_enabled())
        auto.toggled.connect(support.set_auto_check)
        m.addSeparator()
        m.addAction(icon("help"), "About Image Resize & Share", lambda: support.show_about(self))
        b = self.nav.get("2:Help")
        m.exec(b.mapToGlobal(b.rect().bottomLeft()) if b is not None else self.cursor().pos())

    def auto_update_check(self) -> None:
        """Once a day, quietly: an update shows as a button in the status bar, never a pop-up."""
        from app.ui import support
        if support.auto_check_due():
            self.check_updates(manual=False)

    def check_updates(self, manual: bool = False) -> None:
        from app.ui import support
        from app.ui.worker import run_bg
        if manual:
            self.statusBar().showMessage("Checking for updates…", 4000)

        def done(rel):
            support.mark_checked()
            if rel is None:
                if manual:
                    QMessageBox.information(self, "Updates", "You have the newest version.")
                return
            if manual:
                support.show_update(self, rel)
            elif not support.skipped(rel):
                self._show_update_button(rel)

        def failed(msg):
            if manual:
                QMessageBox.information(self, "Updates", "Could not check for updates (no internet, or "
                                        f"GitHub could not be reached).\n\n{msg[:200]}")
        run_bg(lambda _p: support.check_for_update(), done, failed)

    def _show_update_button(self, rel: dict) -> None:
        from app.ui import support
        self._update_rel = rel
        if getattr(self, "_update_btn", None) is None:
            self._update_btn = QPushButton(icon("update", "#1a73e8"), "")
            self._update_btn.setFlat(True)
            self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._update_btn.clicked.connect(lambda: support.show_update(self, self._update_rel))
            self.statusBar().addPermanentWidget(self._update_btn)
        self._update_btn.setText(f" Update {rel['label']} available")
        self._update_btn.show()

    def _route(self, editor_fn, studio_name: str) -> None:
        """Shortcuts act on the page that is showing."""
        if self.pages.currentIndex() == 1 and self.studio is not None:
            getattr(self.studio, studio_name)()
        elif self.pages.currentIndex() == 0:
            editor_fn()

    def set_page(self, i: int) -> None:
        """Switch between Image Editor (0), Wall Studio (1) and Jobs (2)."""
        if i != 1 and self.studio is not None and self.pages.currentIndex() == 1 and self.studio.t_save.isActive():
            self.studio.save_now()        # so Jobs and Installs never show (or save over) an older copy
        if i == 1 and self.studio is None:
            from app.ui.wall_studio import WallStudioPage
            self.studio = WallStudioPage(self)
            old = self.pages.widget(1)
            self.pages.insertWidget(1, self._scrollable(self.studio))
            self.pages.removeWidget(old)
            old.deleteLater()
        if i == 2 and self.jobs_page is None:
            from app.ui.jobs_page import JobsPage
            self.jobs_page = JobsPage(self)
            old = self.pages.widget(2)
            self.pages.insertWidget(2, self._scrollable(self.jobs_page))
            self.pages.removeWidget(old)
            old.deleteLater()
        self.pages.setCurrentIndex(i)
        for k, b in enumerate(self.mode_tabs):
            b.setProperty("active", k == i)
            b.style().unpolish(b)
            b.style().polish(b)
        for mode, w in self.nav_groups.items():
            w.setVisible(mode == i)
        self._fit_nav()
        if i == 2 and self.jobs_page is not None:
            self.jobs_page.refresh()
        if i == 1 and self.studio is not None:
            self.studio.activated()

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        """Pages fill the window; on a small screen (e.g. a laptop at 150 % scaling) they scroll
        instead of squeezing buttons and pictures on top of each other."""
        sc = QScrollArea()
        sc.setObjectName("PageScroll")
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(page)
        return sc

    def _fit_nav(self) -> None:
        """Tool buttons in the top bar show only their icons when their names don't fit
        (the name is still in the tooltip)."""
        if not hasattr(self, "nav_groups"):
            return
        mode = self.pages.currentIndex() if hasattr(self, "pages") else 0
        grp = self.nav_groups.get(mode)
        if grp is None:
            return
        btns = [b for b in grp.findChildren(QToolButton) if b.objectName() == "NavBtn"]
        bar = grp.parentWidget()
        tabs = sum(b.sizeHint().width() for b in self.mode_tabs)
        avail = (bar.width() if bar is not None else self.width()) - tabs - 60
        need = 0
        for b in btns:
            if b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon:
                b.setProperty("full_w", b.sizeHint().width())
            need += int(b.property("full_w") or 140) + 10
        style = (Qt.ToolButtonStyle.ToolButtonTextBesideIcon if need <= avail
                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        for b in btns:
            if b.toolButtonStyle() != style:
                b.setToolButtonStyle(style)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._fit_nav()

    def _studio_call(self, name: str) -> None:
        if self.studio is None or self.pages.currentIndex() != 1:
            self.set_page(1)
        getattr(self.studio, name)()

    def _jobs_call(self, name: str) -> None:
        if self.jobs_page is None or self.pages.currentIndex() != 2:
            self.set_page(2)
        getattr(self.jobs_page, name)()

    def open_job(self, folder) -> None:
        """Open a saved job in the Wall Studio."""
        self.set_page(1)
        self.studio.load_job_folder(folder)

    # ------------------------------------------------------------------
    def _card_header(self, card: Card, title: str, extra: Optional[QWidget] = None) -> None:
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch()
        if extra is not None:
            head.addWidget(extra)
        card.lay.addLayout(head)

    def _build_upload_card(self) -> QWidget:
        card = Card()
        more = QToolButton()
        more.setObjectName("IconBtn")
        more.setIcon(icon("more", "#475569"))
        more.setIconSize(QSize(18, 18))
        more.setToolTip("More")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more.setStyleSheet("QToolButton::menu-indicator{image:none;width:0px;}")
        m = QMenu(more)
        m.addAction(icon("paste"), "Paste image (Ctrl+V)", self.paste_image)
        m.addAction(icon("batch"), "Batch resize / convert… (Ctrl+B)", lambda: self.open_batch([]))
        m.addSeparator()
        self.act_to_studio = m.addAction(icon("wall"), "Use this image in Wall Studio", self.send_to_studio)
        self.btn_reset = m.addAction(icon("reset"), "Reset all edits", self.reset_all)
        more.setMenu(m)
        self._card_header(card, "1.  Upload Image", more)
        self.drop_zone = ClickFrame()
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop_zone.clicked.connect(self.open_dialog)
        dz = QVBoxLayout(self.drop_zone)
        dz.setContentsMargins(16, 18, 16, 14)
        dz.setSpacing(6)
        cloud = QLabel()
        cloud.setPixmap(svg_pixmap("cloud", "#334155", 54))
        cloud.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz.addWidget(cloud)
        t = QLabel("Drag & Drop Image Here")
        t.setObjectName("DropTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz.addWidget(t)
        o = QLabel("or")
        o.setObjectName("Muted")
        o.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz.addWidget(o)
        self.btn_open = QPushButton(icon("folder_fill", "#1e293b"), "   Choose Image…")
        self.btn_open.setObjectName("Choose")
        self.btn_open.setIconSize(QSize(24, 24))
        self.btn_open.setMinimumHeight(48)
        self.btn_open.clicked.connect(self.open_dialog)
        dz.addWidget(self.btn_open)
        fmts = ", ".join(e.lstrip(".").upper() for e in self.exts
                         if e not in (".jpeg", ".jfif", ".heif", ".tif", ".ico", ".tga", ".heic", ".avif"))
        f = hint(f"Supported formats: {fmts}")
        f.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dz.addWidget(f)
        card.lay.addWidget(self.drop_zone)

        self.file_card = QFrame()
        self.file_card.setObjectName("FileCard")
        fc = QHBoxLayout(self.file_card)
        fc.setContentsMargins(8, 8, 6, 8)
        fc.setSpacing(12)
        self.thumb = QLabel()
        self.thumb.setFixedSize(96, 72)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fc.addWidget(self.thumb)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.file_name = ElidedLabel("")
        self.file_name.setObjectName("FileName")
        self.file_size_lbl = ElidedLabel("")
        self.file_size_lbl.setObjectName("FileMeta")
        self.file_dims = ElidedLabel("")
        self.file_dims.setObjectName("FileMeta")
        for lab in (self.file_name, self.file_size_lbl, self.file_dims):
            info.addWidget(lab)
        self.badge_row = QWidget()
        brow = QHBoxLayout(self.badge_row)
        brow.setContentsMargins(0, 2, 0, 0)
        brow.setSpacing(6)
        self.up_badge = ElidedLabel("")
        self.up_badge.setObjectName("Badge")
        self.btn_undo_up = QPushButton("Undo")
        self.btn_undo_up.setObjectName("LinkBtn")
        self.btn_undo_up.setToolTip("Go back to the image before AI upscaling")
        self.btn_undo_up.clicked.connect(self.undo_upscale)
        brow.addWidget(self.up_badge, 1)
        brow.addWidget(self.btn_undo_up)
        info.addWidget(self.badge_row)
        info.addStretch()
        fc.addLayout(info, 1)
        self.btn_remove = QToolButton()
        self.btn_remove.setObjectName("IconBtn")
        self.btn_remove.setIcon(icon("close", "#334155"))
        self.btn_remove.setIconSize(QSize(20, 20))
        self.btn_remove.setToolTip("Remove this image")
        self.btn_remove.clicked.connect(self.clear_image)
        fc.addWidget(self.btn_remove, 0, Qt.AlignmentFlag.AlignTop)
        card.lay.addWidget(self.file_card)
        return card

    # ------------------------------------------------------------------
    def _build_edit_card(self) -> QWidget:
        card = Card()
        self._card_header(card, "2.  Resize & Crop")
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.btn_mode_resize = QPushButton(" Resize")
        self.btn_mode_crop = QPushButton(" Crop")
        for b, n in ((self.btn_mode_resize, "resize"), (self.btn_mode_crop, "crop")):
            b.setCheckable(True)
            b.setObjectName("SegBtn")
            b.setIcon(icon(n, SLATE, WHITE))
            b.setIconSize(QSize(22, 22))
            b.setMinimumHeight(50)
            seg.addWidget(b)
        self.btn_mode_resize.setStyleSheet("border-top-left-radius:8px;border-bottom-left-radius:8px;")
        self.btn_mode_crop.setStyleSheet("border-top-right-radius:8px;border-bottom-right-radius:8px;")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.btn_mode_resize, 0)
        self.mode_group.addButton(self.btn_mode_crop, 1)
        self.mode_group.idClicked.connect(self._set_mode)
        card.lay.addLayout(seg)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_resize_page())
        self.stack.addWidget(self._build_crop_page())
        card.lay.addWidget(self.stack)
        card.lay.addStretch()
        return card

    def _build_resize_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)
        self.lbl_w = QLabel("Width (px)")
        self.lbl_h = QLabel("Height (px)")
        for lab in (self.lbl_w, self.lbl_h):
            lab.setObjectName("FieldLabel")
        g.addWidget(self.lbl_w, 0, 0)
        g.addWidget(self.lbl_h, 0, 2)
        self.sp_w = QDoubleSpinBox()
        self.sp_h = QDoubleSpinBox()
        for sp in (self.sp_w, self.sp_h):
            sp.setRange(0, 999999)
            sp.setKeyboardTracking(False)
            sp.setMinimumHeight(44)
            sp.setMinimumWidth(96)
            sp.setStyleSheet("font-size:11.5pt;")
        self.sp_w.valueChanged.connect(self._on_w_changed)
        self.sp_h.valueChanged.connect(self._on_h_changed)
        self.btn_link = QToolButton()
        self.btn_link.setObjectName("LinkToggle")
        self.btn_link.setCheckable(True)
        self.btn_link.setChecked(True)
        self.btn_link.setIconSize(QSize(20, 20))
        self.btn_link.setFixedSize(44, 44)
        self.btn_link.setToolTip("Maintain aspect ratio")
        self.btn_link.toggled.connect(self._on_link_toggled)
        g.addWidget(self.sp_w, 1, 0)
        g.addWidget(self.btn_link, 1, 1)
        g.addWidget(self.sp_h, 1, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        self.chk_ratio = QCheckBox("Maintain aspect ratio")
        self.chk_ratio.setChecked(True)
        self.chk_ratio.toggled.connect(self.btn_link.setChecked)
        lay.addWidget(self.chk_ratio)

        pg = QGridLayout()
        pg.setSpacing(8)
        self.preset_group = QButtonGroup(self)
        self.preset_group.setExclusive(True)
        self.preset_tiles = []
        for i, (label, w, h) in enumerate(QUICK_PRESETS):
            b = TwoLineButton(label, f"{w} × {h}" if w else "")
            b.clicked.connect(lambda _=False, w=w, h=h, l=label: self.apply_preset(w, h, "px", 0, l))
            self.preset_group.addButton(b, i)
            self.preset_tiles.append(b)
            pg.addWidget(b, i // 3, i % 3)
        self.tile_custom = TwoLineButton("Custom", "Custom size")
        self.tile_custom.clicked.connect(self.apply_custom)
        self.preset_group.addButton(self.tile_custom, len(QUICK_PRESETS))
        pg.addWidget(self.tile_custom, 1, 1)
        self.tile_more = TwoLineButton("More sizes", "Wall, print, social")
        self.tile_more.setCheckable(False)
        menu = QMenu(self.tile_more)
        for cat, items in SIZE_PRESETS.items():
            sub = menu.addMenu(cat)
            for (label, w, h, unit, dpi) in items:
                a = sub.addAction(label)
                a.triggered.connect(lambda _=False, w=w, h=h, u=unit, d=dpi, l=label:
                                    self.apply_preset(w, h, u, d, l))
        self.tile_more.setMenu(menu)
        self.tile_more.setStyleSheet("QPushButton::menu-indicator{image:none;width:0px;}")
        pg.addWidget(self.tile_more, 1, 2)
        lay.addLayout(pg)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_ai = QPushButton(icon("sparkle", WHITE), " AI Upscale")
        self.btn_ai.setObjectName("AIButton")
        self.btn_ai.setIconSize(QSize(18, 18))
        self.btn_ai.setMinimumHeight(40)
        self.btn_ai.setToolTip("Lupa-style AI upscaler: 2×–16× or fit a wall / print size (Ctrl+U)")
        self.btn_ai.clicked.connect(self.open_upscale)
        b_more = QPushButton(icon("gear"), " More options")
        b_more.setMinimumHeight(40)
        b_more.setToolTip("Units, fit / fill, background, enlarging quality, print DPI")
        b_more.clicked.connect(lambda: self.open_settings(0))
        row.addWidget(self.btn_ai, 1)
        row.addWidget(b_more, 1)
        lay.addLayout(row)
        self.size_info = hint("")
        self.size_info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.size_info)
        return page

    def _build_crop_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        r = QHBoxLayout()
        lab = QLabel("Aspect ratio")
        lab.setObjectName("FieldLabel")
        r.addWidget(lab)
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
        lay.addLayout(r)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.cr_x, self.cr_y, self.cr_w, self.cr_h = (QSpinBox() for _ in range(4))
        for sp, lab in ((self.cr_x, "X"), (self.cr_y, "Y"), (self.cr_w, "Width"), (self.cr_h, "Height")):
            sp.setRange(0, 999999)
            sp.setKeyboardTracking(False)
            sp.valueChanged.connect(lambda _v, n=lab: self._on_crop_spin(n))
        for i, (t, sp) in enumerate((("Position X (px)", self.cr_x), ("Position Y (px)", self.cr_y))):
            l_ = QLabel(t)
            l_.setObjectName("FieldLabel")
            g.addWidget(l_, 0, i)
            g.addWidget(sp, 1, i)
        lay.addLayout(g)
        self.chk_grid = QCheckBox("Rule-of-thirds grid")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(lambda on: self.canvas.set_grid(on))
        lay.addWidget(self.chk_grid)
        row2 = QHBoxLayout()
        b_all = QPushButton("Select all")
        b_all.clicked.connect(self.crop_select_all)
        b_clear = QPushButton("Clear crop")
        b_clear.clicked.connect(self.crop_clear)
        row2.addWidget(b_all)
        row2.addWidget(b_clear)
        row2.addStretch()
        lay.addLayout(row2)
        lay.addWidget(hint("Drag on the picture in “4. Crop Image”. Drag the corners or edges to adjust, "
                           "drag inside to move. Wheel zooms, right-drag pans."))
        self.crop_info = hint("")
        self.crop_info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.crop_info)
        return page

    # ------------------------------------------------------------------
    def _build_settings_dialog(self) -> QDialog:
        """Resize options + download settings (opened from 'More options' / the print tile)."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Options")
        dlg.setMinimumWidth(460)
        outer = QVBoxLayout(dlg)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        # ---- resize tab
        rt = QWidget()
        ml = QVBoxLayout(rt)
        ml.setSpacing(8)
        ur = QHBoxLayout()
        ur.addWidget(QLabel("Size unit"))
        self.cb_unit = QComboBox()
        self.cb_unit.addItems(list(im.UNITS))
        self.cb_unit.currentTextChanged.connect(lambda _: self._refresh_spins())
        ur.addWidget(self.cb_unit)
        ur.addStretch()
        ur.addWidget(QLabel("Quick enlarge"))
        for k in (2, 3, 4):
            b = QPushButton(f"{k}×")
            b.setToolTip(f"Make the image {k}× bigger (AI Super-Resolution when available)")
            b.clicked.connect(lambda _=False, k=k: self.quick_upscale(k))
            ur.addWidget(b)
        ml.addLayout(ur)
        ml.addWidget(section("If the new shape is different"))
        self.cb_fit = QComboBox()
        for t, v in MODE_ITEMS:
            self.cb_fit.addItem(t, v)
        self.cb_fit.currentIndexChanged.connect(self._on_option_changed)
        ml.addWidget(self.cb_fit)
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
        ml.addLayout(bgrow)
        self.shape_hint = hint("")
        ml.addWidget(self.shape_hint)
        ml.addWidget(section("Enlarging quality"))
        self.cb_up = QComboBox()
        for t, v in UPSCALE_ITEMS:
            self.cb_up.addItem(t, v)
        self.cb_up.currentIndexChanged.connect(self._on_option_changed)
        ml.addWidget(self.cb_up)
        srow = QHBoxLayout()
        self.chk_sharp_auto = QCheckBox("Auto sharpen")
        self.chk_sharp_auto.setChecked(True)
        self.sl_sharp = QSlider(Qt.Orientation.Horizontal)
        self.sl_sharp.setRange(0, 100)
        self.sl_sharp.setValue(30)
        self.sl_sharp.setEnabled(False)
        self.lbl_sharp = QLabel("")
        self.lbl_sharp.setFixedWidth(30)
        self.chk_sharp_auto.toggled.connect(lambda on: (self.sl_sharp.setEnabled(not on),
                                                        self._on_option_changed()))
        self.sl_sharp.valueChanged.connect(lambda v: (self.lbl_sharp.setText(str(v)),
                                                      self._on_option_changed()))
        srow.addWidget(self.chk_sharp_auto)
        srow.addWidget(self.sl_sharp, 1)
        srow.addWidget(self.lbl_sharp)
        ml.addLayout(srow)
        self.chk_allow_up = QCheckBox("Allow enlarging beyond the original size")
        self.chk_allow_up.setChecked(True)
        self.chk_allow_up.toggled.connect(self._on_option_changed)
        ml.addWidget(self.chk_allow_up)
        ml.addStretch()
        tabs.addTab(rt, "Resize")
        # ---- download tab
        dt = QWidget()
        dl = QVBoxLayout(dt)
        dl.setSpacing(8)
        dl.addWidget(section("Print file format"))
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.fmt_group = QButtonGroup(self)
        fmts = [("JPG", "JPG"), ("PNG", "PNG"), ("TIFF", "TIFF (print)"), ("WEBP", "WEBP"), ("PDF", "PDF (print)")]
        self.fmt_buttons = {}
        for i, (key, label) in enumerate(fmts):
            rb = QRadioButton(label)
            self.fmt_group.addButton(rb, i)
            self.fmt_buttons[key] = rb
            g.addWidget(rb, i // 3, i % 3)
            rb.toggled.connect(lambda on, k=key: on and self._on_fmt_changed(k))
        dl.addLayout(g)
        qrow = QHBoxLayout()
        self.lbl_q = QLabel("Quality")
        self.sl_q = QSlider(Qt.Orientation.Horizontal)
        self.sl_q.setObjectName("BlueSlider")
        self.sl_q.setRange(40, 100)
        self.sl_q.setValue(92)
        self.lbl_qv = QLabel("92%")
        self.lbl_qv.setFixedWidth(40)
        self.sl_q.valueChanged.connect(lambda v: (self.lbl_qv.setText(f"{v}%"), self._on_option_changed()))
        qrow.addWidget(self.lbl_q)
        qrow.addWidget(self.sl_q, 1)
        qrow.addWidget(self.lbl_qv)
        dl.addLayout(qrow)
        self.chk_lossless = QCheckBox("WEBP lossless")
        self.chk_lossless.toggled.connect(self._on_option_changed)
        dl.addWidget(self.chk_lossless)
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
        trow.addStretch()
        trow.addWidget(QLabel("Print DPI"))
        self.sp_dpi = QSpinBox()
        self.sp_dpi.setRange(36, 2400)
        self.sp_dpi.setValue(300)
        self.sp_dpi.setKeyboardTracking(False)
        self.sp_dpi.setToolTip("Pixels per inch for print. Wallpaper / murals: 100–150. Photos: 300.")
        self.sp_dpi.valueChanged.connect(self._on_dpi_changed)
        trow.addWidget(self.sp_dpi)
        dl.addLayout(trow)
        self.chk_strip = QCheckBox("Remove photo info (GPS, camera)")
        self.chk_strip.toggled.connect(self._on_option_changed)
        dl.addWidget(self.chk_strip)
        self.chk_open_folder = QCheckBox("Open the folder after saving")
        dl.addWidget(self.chk_open_folder)
        dl.addStretch()
        tabs.addTab(dt, "Download")
        self.settings_tabs = tabs
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        bb.accepted.connect(dlg.accept)
        outer.addWidget(bb)
        self.fmt_buttons["JPG"].setChecked(True)
        return dlg

    def open_settings(self, tab: int = 0) -> None:
        self.settings_tabs.setCurrentIndex(tab)
        self.settings_dlg.show()
        self.settings_dlg.raise_()

    # ------------------------------------------------------------------
    def _build_preview_card(self) -> QWidget:
        card = Card()
        self._card_header(card, "3.  Image Preview")
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.view_out = ZoomView("Your image appears here", bg="#eef1f5")
        self.view_out.setAcceptDrops(False)
        split.addWidget(self.view_out)

        self.cu_pane = QFrame()
        cl = QVBoxLayout(self.cu_pane)
        cl.setContentsMargins(8, 0, 0, 0)
        ch = QHBoxLayout()
        t2 = QLabel("Before / After")
        t2.setObjectName("PaneTitle")
        ch.addWidget(t2)
        ch.addStretch()
        self.cb_cu_zoom = QComboBox()
        for z in (1, 2, 4, 8):
            self.cb_cu_zoom.addItem(f"{z * 100}%", float(z))
        self.cb_cu_zoom.setCurrentIndex(1)
        self.cb_cu_zoom.currentIndexChanged.connect(lambda _: self._update_closeup())
        ch.addWidget(self.cb_cu_zoom)
        cl.addLayout(ch)
        lb = QLabel("Before (original pixels)")
        lb.setObjectName("PaneInfo")
        cl.addWidget(lb)
        self.cu_before = CloseUpView("Hover over the preview")
        cl.addWidget(self.cu_before, 1)
        la = QLabel("After (your result)")
        la.setObjectName("PaneInfo")
        cl.addWidget(la)
        self.cu_after = CloseUpView("to inspect details")
        cl.addWidget(self.cu_after, 1)
        self.cu_hint = hint("Move the mouse over the preview. Click to pin / unpin the spot.")
        cl.addWidget(self.cu_hint)
        split.addWidget(self.cu_pane)
        split.setSizes([700, 260])
        self.cu_pane.setVisible(False)
        card.lay.addWidget(split, 1)

        self.view_out.hovered.connect(self._on_out_hover)
        self.view_out.clicked.connect(self._on_out_click)
        self.view_out.zoomChanged.connect(self._on_view_zoom)

        zr = QHBoxLayout()
        zr.setSpacing(6)

        def ib(name, tip, slot, size=26, checkable=False):
            b = QToolButton()
            b.setObjectName("IconBtn")
            b.setIcon(icon(name, "#1e293b", WHITE if checkable else None))
            b.setIconSize(QSize(size, size))
            b.setToolTip(tip)
            b.setCheckable(checkable)
            if checkable:
                b.toggled.connect(slot)
            else:
                b.clicked.connect(slot)
            return b

        b_out = ib("zoom_out", "Zoom out", lambda: self._zoom_step(1 / 1.25))
        self.sl_zoom = QSlider(Qt.Orientation.Horizontal)
        self.sl_zoom.setRange(0, 1000)
        self.sl_zoom.setMinimumWidth(70)
        self.sl_zoom.setMaximumWidth(260)
        self.sl_zoom.setToolTip("Zoom")
        self.sl_zoom.valueChanged.connect(self._on_zoom_slider)
        b_in = ib("zoom_in", "Zoom in", lambda: self._zoom_step(1.25))
        self.cb_zoom = QLineEdit("Fit")
        self.cb_zoom.setObjectName("ZoomBox")
        self.cb_zoom.setFixedWidth(84)
        self.cb_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cb_zoom.setToolTip("Type a zoom (e.g. 100%) and press Enter. Ctrl+0 = fit")
        self.cb_zoom.returnPressed.connect(lambda: self._on_zoom_text(self.cb_zoom.text()))
        self.b_undo = ib("undo", "Undo (Ctrl+Z)", self.undo, 22)
        self.b_redo = ib("redo", "Redo (Ctrl+Y)", self.redo, 22)
        self.out_info = QLabel("")
        self.out_info.setObjectName("Hint")
        self.out_info.setMinimumWidth(10)
        self.out_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.btn_cu = ib("compare", "Before / after close-up", self._toggle_loupe, 24, checkable=True)
        b_full = ib("fullscreen", "Full screen (F11)", self.open_fullscreen)
        zr.addWidget(b_out)
        zr.addWidget(self.sl_zoom, 2)
        zr.addWidget(b_in)
        zr.addSpacing(6)
        zr.addWidget(self.cb_zoom)
        zr.addSpacing(4)
        zr.addWidget(self.b_undo)
        zr.addWidget(self.b_redo)
        zr.addSpacing(4)
        zr.addWidget(self.out_info, 1)
        zr.addWidget(self.btn_cu)
        zr.addWidget(b_full)
        card.lay.addLayout(zr)
        return card

    def _build_crop_card(self) -> QWidget:
        card = Card()
        card.setMinimumWidth(300)
        card.setMaximumWidth(400)
        self._card_header(card, "4.  Crop Image")
        h = hint("Drag the corners to adjust")
        h.setAlignment(Qt.AlignmentFlag.AlignRight)
        card.lay.addWidget(h)
        self.canvas = CropCanvas()
        self.canvas.setMinimumHeight(150)
        self.canvas.rectChanged.connect(self._on_canvas_rect)
        self.canvas.editStarted.connect(lambda: self._push_undo("canvas-drag"))
        self.canvas.editFinished.connect(lambda: setattr(self, "_undo_key", None))
        card.lay.addWidget(self.canvas, 1)
        lab = QLabel("Crop Size (px)")
        lab.setObjectName("Section")
        card.lay.addWidget(lab)
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(5)
        lw, lh = QLabel("Width"), QLabel("Height")
        for l_ in (lw, lh):
            l_.setObjectName("FieldLabel")
        g.addWidget(lw, 0, 0)
        g.addWidget(lh, 0, 1)
        for sp in (self.cr_w, self.cr_h):
            sp.setMinimumHeight(44)
            sp.setStyleSheet("font-size:11.5pt;")
        g.addWidget(self.cr_w, 1, 0)
        g.addWidget(self.cr_h, 1, 1)
        card.lay.addLayout(g)
        rr = QHBoxLayout()
        rr.setSpacing(2)

        def tb(name, tip, slot):
            b = QToolButton()
            b.setObjectName("IconBtn")
            b.setIcon(icon(name))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            rr.addWidget(b)
            return b

        self.b_rot_l = tb("rot_left", "Rotate left (Ctrl+L)", lambda: self.rotate(False))
        self.b_rot_r = tb("rot_right", "Rotate right (Ctrl+R)", lambda: self.rotate(True))
        self.b_flip_h = tb("flip_h", "Flip horizontally", lambda: self.flip(True))
        self.b_flip_v = tb("flip_v", "Flip vertically", lambda: self.flip(False))
        rr.addStretch()
        b_reset = QPushButton(icon("reset", "#1e293b"), "  Reset Crop")
        b_reset.setObjectName("Light")
        b_reset.setIconSize(QSize(20, 20))
        b_reset.setMinimumHeight(44)
        b_reset.clicked.connect(self.crop_clear)
        rr.addWidget(b_reset)
        card.lay.addLayout(rr)
        return card

    def _build_share_card(self) -> QWidget:
        card = Card()
        self._card_header(card, "5.  Download & Share")
        row = QHBoxLayout()
        row.setSpacing(14)

        def tile(obj, ic, color, text, slot, tip):
            b = QToolButton()
            b.setObjectName(obj)
            b.setIcon(icon(ic, color))
            b.setIconSize(QSize(38, 38))
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setStyleSheet("min-height: 76px;")       # QSS min-height wins over setMinimumHeight
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        def tile_menu(tile_btn, actions):
            tl = QHBoxLayout(tile_btn)
            tl.setContentsMargins(4, 4, 4, 4)
            tl.addStretch()
            mb = QToolButton()
            mb.setObjectName("TileMenu")
            mb.setIcon(icon("more", "#475569"))
            mb.setIconSize(QSize(18, 18))
            mb.setToolTip("Options")
            mb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            mb.setStyleSheet("QToolButton::menu-indicator{image:none;width:0px;}")
            m = QMenu(mb)
            out = []
            for a in actions:
                if a is None:
                    m.addSeparator()
                    continue
                out.append(m.addAction(*a))
            mb.setMenu(m)
            tl.addWidget(mb, 0, Qt.AlignmentFlag.AlignTop)
            return mb, out

        self.tile_preview = tile("TileBlue", "download", "#1a73e8", "Download Preview",
                                 self.open_download_preview, "Customer preview with size, area and note (Ctrl+P)")
        self.tile_closeup = tile("TilePurple", "search", "#6d4aff", "Closeup Print Preview",
                                 self.open_closeup_preview, "Zoom into a spot to check print sharpness")
        self.tile_print = tile("TileGreen", "printer", "#1e293b", "Download Print File",
                               self.save_image, "Save the full-resolution file (Ctrl+S)")
        self.btn_wa = tile("TileWA", "whatsapp", "#1f9d55", "Open in WhatsApp", self.share_whatsapp,
                           "Save, copy and open WhatsApp (Ctrl+W)")
        tile_menu(self.tile_print, [("Download settings…", lambda: self.open_settings(1)),
                                    ("Copy image to clipboard (Ctrl+Shift+C)", self.copy_result),
                                    None, ("Classic proof sheet… (Ctrl+Alt+P)", self.open_proof)])
        self.btn_wa_menu, acts = tile_menu(self.btn_wa, [("Open WhatsApp Web (browser)",),
                                                         ("Open WhatsApp Desktop app",), None,
                                                         ("Open a chat with phone number…",)])
        self.act_wa_web, self.act_wa_desk, self.act_wa_phone = acts
        for a in (self.act_wa_web, self.act_wa_desk):
            a.setCheckable(True)
        self.act_wa_web.setChecked(True)
        self.act_wa_web.triggered.connect(lambda: self._set_wa_target("web"))
        self.act_wa_desk.triggered.connect(lambda: self._set_wa_target("desktop"))
        self.act_wa_phone.triggered.connect(self._ask_phone)
        self.btn_copy = self.btn_wa_menu   # kept for older code paths
        card.lay.addLayout(row)
        self.wa_sub = hint("")
        self.wa_sub.setVisible(False)
        return card

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
        act(QKeySequence.StandardKey.Save, lambda: self._route(self.save_image, "save_now"))
        act(QKeySequence("Ctrl+Shift+C"), self.copy_result)
        act(QKeySequence.StandardKey.Paste, self.paste_image)
        act(QKeySequence.StandardKey.Undo, lambda: self._route(self.undo, "undo"))
        act([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")], lambda: self._route(self.redo, "redo"))
        act(QKeySequence("Ctrl+R"), lambda: self.rotate(True))
        act(QKeySequence("Ctrl+L"), lambda: self.rotate(False))
        act(QKeySequence("Ctrl+1"), lambda: self._set_mode(0))
        act(QKeySequence("Ctrl+2"), lambda: self._set_mode(1))
        act(QKeySequence("Ctrl+U"), self.open_upscale)
        act(QKeySequence("Ctrl+W"), self.share_whatsapp)
        act(QKeySequence("Ctrl+B"), lambda: self.open_batch([]))
        act(QKeySequence("F1"), self.show_help)
        act(QKeySequence("F11"), self.open_fullscreen)
        act(QKeySequence("Ctrl+P"), lambda: self._route(self.open_download_preview, "open_proof"))
        act(QKeySequence("Ctrl+Shift+P"), self.open_closeup_preview)
        act(QKeySequence("Ctrl+Alt+P"), self.open_proof)
        act(QKeySequence("Ctrl+0"), lambda: self.view_out.fit())

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
        self.print_unit = val("print_unit", "in")
        if self.print_unit not in sh.UNITS:
            self.print_unit = "in"
        self._set_wa_target(self.wa_target)
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self._update_out_summary()

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
        s.setValue("print_unit", self.print_unit)
        s.setValue("geometry", self.saveGeometry())

    @staticmethod
    def _select_data(combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    # ==================================================================
    # Loading / removing
    # ==================================================================
    def open_dialog(self) -> None:
        start = self.settings.value("last_open_dir", str(Path.home() / "Pictures"))
        flt = ("Images (" + " ".join("*" + e for e in self.exts) + ");;All files (*.*)")
        path, _ = QFileDialog.getOpenFileName(self, "Choose an image", str(start), flt)
        if path:
            self.load_path(path)

    def load_path(self, path) -> bool:
        # in the background: a big TIFF or phone panorama can take several seconds to open
        from app.ui.worker import BackgroundError, run_with_progress

        def load():
            try:
                return im.load_image(path), None
            except Exception as exc:          # noqa: BLE001 – explained to the user below
                return None, exc
        try:
            li, err = run_with_progress(self, "Opening the picture…", load)
        except BackgroundError as exc:        # e.g. out of memory
            li, err = None, MemoryError(str(exc))
        if li is None:
            QMessageBox.warning(self, "Could not open image", im.load_error_text(path, err))
            return False
        self.settings.setValue("last_open_dir", str(Path(path).parent))
        self._before_upscale = None
        self._set_source(li)
        if li.n_frames > 1:
            self.statusBar().showMessage("Animated image: the first frame is used.", 6000)
        return True

    def _set_source(self, li: im.LoadedImage, upscale_label: str = "") -> None:
        self.src = li
        self.state = im.EditState()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.keep_original = True
        self.tw, self.th = li.image.size
        self.result = None
        self.result_size = None
        self._full = None
        self._cu_pt = None
        self._cu_pinned = False
        self._oriented_key = None
        self._print_override = None
        self.canvas.set_rect(None)
        self.canvas.reset_view()
        from app.ui.qtutil import small_rgb
        pm = QPixmap.fromImage(pil_to_qimage(small_rgb(li.image, (192, 144), keep_alpha=True)))
        pm.setDevicePixelRatio(2)
        self.thumb.setPixmap(pm)
        self.file_name.setText(li.path.name if li.path else "Pasted image")
        self.file_name.setToolTip(str(li.path) if li.path else "")
        self.file_size_lbl.setText(im.human_size(li.file_size) if li.file_size else
                                   ("Upscaled – not saved yet" if upscale_label else "From clipboard"))
        self.file_dims.setText(f"{li.image.width} × {li.image.height} px")
        self.up_badge.setText(upscale_label)
        self._refresh_all(new_image=True)

    def clear_image(self) -> None:
        """Remove the current image (✕ on the file card)."""
        if not self.src:
            return
        self.timer.stop()
        self.gen += 1
        self.src = None
        self.state = im.EditState()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.result = None
        self.result_size = None
        self._full = None
        self._before_upscale = None
        self._print_override = None
        self._cu_pt = None
        self.thumb.clear()
        self.canvas.set_rect(None)
        self._refresh_all()
        self.statusBar().showMessage("Image removed.", 3000)

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
                self._before_upscale = None
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
                self._before_upscale = None
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
        self.lbl_w.setText(f"Width ({unit})")
        self.lbl_h.setText(f"Height ({unit})")
        dec = UNIT_DECIMALS[unit]
        for sp, px, base in ((self.sp_w, self.tw, bw), (self.sp_h, self.th, bh)):
            sp.blockSignals(True)
            sp.setDecimals(dec)
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
        k = min((im.MAX_OUTPUT_PIXELS / (self.tw * self.th)) ** 0.5,     # keep it inside what a PC can handle
                im.MAX_OUTPUT_SIDE / self.tw, im.MAX_OUTPUT_SIDE / self.th)  # (a long strip hits the side limit)
        if k < 1:
            self.tw, self.th = max(1, int(self.tw * k)), max(1, int(self.th * k))
            self.statusBar().showMessage(
                f"Limited to {self.tw} × {self.th} px (up to {im.MAX_OUTPUT_PIXELS // 1_000_000} MP and "
                f"{im.MAX_OUTPUT_SIDE:,} px a side), the largest size the app makes in one file. For bigger walls use Wall Studio (it prints in panels).", 9000)
        self.keep_original = (self.tw, self.th) == self.base_size()
        self._check_preset_buttons()
        self._refresh_spins()
        self._schedule()

    def _on_link_toggled(self, on: bool) -> None:
        self.btn_link.setIcon(icon("link" if on else "unlink", SLATE, WHITE))
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
                if unit == "in" and w >= 48:
                    self.print_unit = "ft"
                elif unit in ("in", "cm", "mm"):
                    self.print_unit = unit
            d = dpi or self.sp_dpi.value()
            tw = im.to_pixels(w, unit, d, 0)
            th = im.to_pixels(h, unit, d, 0)
            if tw > im.MAX_OUTPUT_SIDE or th > im.MAX_OUTPUT_SIDE or tw * th > im.MAX_OUTPUT_PIXELS:
                QMessageBox.information(self, "Too large", f"{tw} × {th} px is above the size limit.")
                return
            self.tw, self.th = tw, th
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

    def apply_custom(self) -> None:
        self.tile_custom.setChecked(True)
        self.sp_w.setFocus()
        self.sp_w.selectAll()
        self.statusBar().showMessage("Type the width and height you need.", 3000)

    def _check_preset_buttons(self) -> None:
        self.preset_group.setExclusive(False)
        matched = False
        for i, (_l, w, h) in enumerate(QUICK_PRESETS):
            on = bool(self.src) and ((w == 0 and self.keep_original) or (w and (w, h) == (self.tw, self.th)))
            self.preset_tiles[i].setChecked(on)
            matched = matched or on
        self.tile_custom.setChecked(bool(self.src) and not matched)
        self.preset_group.setExclusive(True)
        bw, bh = self.base_size()
        self.preset_tiles[0].set_sub(f"{bw} × {bh}" if self.src else "Your image")

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
        dpi = self.sp_dpi.value()
        u = self.print_unit
        lines = [f"<b>Output:</b> {tw} × {th} px  ·  <b>Print:</b> {sh.size_text(tw / dpi, th / dpi, u)} "
                 f"at {dpi} DPI  ·  <b>Area:</b> {sh.area_text(tw / dpi, th / dpi)}"]
        method = self.cb_up.currentData()
        if scale > 1.01 and self.chk_allow_up.isChecked():
            txt = f"<b>Enlarging {scale:.2f}×</b> – "
            if method == im.UPSCALE_STANDARD:
                txt += "<span style='color:#b45309'>Standard can look soft. Try AI Upscale.</span>"
            elif method in (im.UPSCALE_AI_PHOTO, im.UPSCALE_AI_ART):
                if self.ai.available():
                    txt += "<span style='color:#15803d'>AI rebuilds fine detail.</span>"
                else:
                    txt += (f"<span style='color:#b45309'>{self.ai.status_text()} – "
                            "Enhanced will be used.</span>")
            else:
                txt += "<span style='color:#15803d'>Enhanced keeps edges sharp.</span>"
                if scale > 2.5:
                    txt += " For the most detail use <b>AI Upscale</b>."
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
        if hasattr(self, "pages") and self.pages.currentIndex() != 0:
            self.set_page(0)
        self.mode_group.button(idx).setChecked(True)
        self.stack.setCurrentIndex(idx)

    def go_home(self) -> None:
        self.set_page(0)
        self.left_scroll.verticalScrollBar().setValue(0)
        self.view_out.fit()
        self.canvas.reset_view()

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
        cur = self.state.crop or (0, 0, W, H)
        x, y, w, h = self.cr_x.value(), self.cr_y.value(), self.cr_w.value(), self.cr_h.value()
        r = self._current_ratio()
        if r:
            if which == "Height":
                w = round(h * r)
            elif which == "Width":
                h = round(w / r)
        if which in ("Width", "Height"):
            # keep the selection centred where it was
            w, h = min(max(1, w), W), min(max(1, h), H)
            cx, cy = cur[0] + cur[2] / 2, cur[1] + cur[3] / 2
            x = int(min(max(0, round(cx - w / 2)), W - w))
            y = int(min(max(0, round(cy - h / 2)), H - h))
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
        self._check_preset_buttons()
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
            f"<b>Crop:</b> {w} × {h} px &nbsp;→&nbsp; <b>Output:</b> {self.tw} × {self.th} px")

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

    def _update_out_summary(self) -> None:
        if not hasattr(self, "tile_print"):
            return
        fmt = self._fmt()
        q = f" · {self.sl_q.value()}%" if fmt in ("JPG", "WEBP", "PDF") else ""
        self.tile_print.setToolTip(f"Save the full-resolution file (Ctrl+S) – {fmt}{q} · {self.sp_dpi.value()} DPI."
                                   "\nChange it with ⋮ → Download settings.")

    def _on_option_changed(self, *_):
        if hasattr(self, "chk_lossless"):
            fmt = self._fmt()
            lossy = fmt in ("JPG", "WEBP", "PDF") and not (fmt == "WEBP" and self.chk_lossless.isChecked())
            self.sl_q.setEnabled(lossy)
            self._update_out_summary()
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
        self.btn_wa.setToolTip(f"Saves the image, copies it and opens {where}{phone} (Ctrl+W)")

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
        self._full = None             # settings changed: the full-size copy is out of date
        if self.src:
            self.timer.start()

    def _run_process(self) -> None:
        if not self.src:
            return
        if self.jobs:                 # one preview at a time: big prints would pile up and use all memory
            self._rerun = True        # the newest settings run as soon as the current one finishes
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
            if getattr(self, "_rerun", False):
                self._rerun = False
                if self.src and gen != self.gen:
                    self._run_process()
                    return
            self.busy.setVisible(False)

    def _on_result(self, gen: int, res: im.ProcessResult) -> None:
        self._job_done(gen)
        if gen != self.gen or not self.src:
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
            self.out_info.setText(f"<span style='color:#b91c1c'>{html.escape(msg[:80])}</span>")
            self.processed.emit()

    def _update_out_info(self) -> None:
        res = self.result
        if not res or not self.src:
            self.out_info.setText("")
            return
        w, h = res.out_size
        q = f" {res.quality_used}%" if res.quality_used and res.fmt in ("JPG", "WEBP", "PDF") else ""
        about = "≈ " if res.is_preview else ""
        self.out_info.setText(f"{w} × {h} px  ·  {about}{im.human_size(im.estimated_bytes(res))} {res.fmt}{q}   ")
        self.out_info.setToolTip("Big print: you see a screen-sized preview while editing (fast). The close-up "
                                 "shows the real pixels; Download, Share and Print make the full size."
                                 if res.is_preview else "")

    def _oriented_qimage(self):
        key = (id(self.src), self.state.rotation, self.state.flip_h, self.state.flip_v)
        if key != self._oriented_key:
            self._oriented_key = key
            self._oriented_qimg = pil_to_qimage(im.apply_orientation(self.src.image, self.state))
        return self._oriented_qimg

    def _refresh_all(self, new_image: bool = False) -> None:
        has = self.src is not None
        for w in (self.tile_preview, self.tile_closeup, self.tile_print, self.btn_wa, self.btn_reset,
                  self.b_rot_l, self.b_rot_r, self.b_flip_h, self.b_flip_v, self.btn_ai, self.act_to_studio):
            w.setEnabled(has)
        for k in ("Preview", "Download", "Print Preview", "WhatsApp Share"):
            self.nav[k].setEnabled(has)
        self.file_card.setVisible(has)
        up = bool(self._before_upscale) and has
        self.badge_row.setVisible(up)
        if not has:
            self.view_out.set_image(None)
            self.cu_before.set_image(None)
            self.cu_after.set_image(None)
            self.canvas.set_image(None)
            self.out_info.setText("")
            self._update_buttons()
            self._update_size_info()
            self._check_preset_buttons()
            self.sp_w.blockSignals(True)
            self.sp_h.blockSignals(True)
            for sp in (self.sp_w, self.sp_h):
                sp.setDecimals(UNIT_DECIMALS[self._unit()])
            self.sp_w.setValue(0)
            self.sp_h.setValue(0)
            self.sp_w.blockSignals(False)
            self.sp_h.blockSignals(False)
            for sp in (self.cr_x, self.cr_y, self.cr_w, self.cr_h):
                sp.blockSignals(True)
                sp.setValue(0)
                sp.blockSignals(False)
            self.crop_info.setText("")
            return
        qimg = self._oriented_qimage()
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
        self._update_buttons()
        self._schedule()

    def _update_buttons(self) -> None:
        self.b_undo.setEnabled(bool(self.undo_stack))
        self.b_redo.setEnabled(bool(self.redo_stack))

    def _fresh_result(self) -> Optional[im.ProcessResult]:
        """Up-to-date result; computes now if the preview is still pending."""
        if not self.src:
            return None
        if self.result is not None and self.result_gen == self.gen and not self.result.is_preview:
            return self.result
        full = getattr(self, "_full", None)          # the real output, made earlier for these settings
        if full is not None and full[0] == self.gen:
            return full[1]
        if getattr(self, "_preparing", False):      # a second click while it is still working
            return None
        self.timer.stop()
        rs, os_ = self.current_settings()
        src, st, ai = self.src, self.state.copy(), self.ai
        # work in the background so Windows never marks the app "Not responding" on big prints
        from PySide6.QtCore import QEventLoop
        from PySide6.QtWidgets import QProgressDialog
        from app.ui.worker import run_bg
        box = {}
        loop = QEventLoop()

        def done(r):
            box["res"] = r
            loop.quit()

        def failed(msg):
            box["err"] = msg
            loop.quit()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        dlg = None
        self._preparing = True
        try:
            uses_ai = rs.upscale in (im.UPSCALE_AI_PHOTO, im.UPSCALE_AI_ART) and ai is not None and ai.available()
            if (rs.enabled and rs.width * rs.height > 30_000_000) or uses_ai:
                dlg = QProgressDialog("Preparing the full-size image…", "", 0, 0, self)
                dlg.setCancelButton(None)
                dlg.setWindowTitle("Image Resize & Share")
                dlg.setMinimumDuration(0 if not uses_ai else 300)
                dlg.setWindowModality(Qt.WindowModality.WindowModal)
                dlg.show()

            def shown(_f, text):                  # e.g. "AI upscaling… 40%"
                if dlg is not None and text:
                    dlg.setLabelText(text)
            run_bg(lambda p: im.process(src, st, rs, os_, ai, progress=lambda m: p(0, m)), done, failed,
                   on_progress=shown)
            if "res" not in box and "err" not in box:
                loop.exec()
        finally:
            self._preparing = False
            if dlg is not None:
                dlg.close()
                dlg.deleteLater()
            QApplication.restoreOverrideCursor()
        if "err" in box:
            QMessageBox.warning(self, "Could not process image", box["err"])
            return None
        res = box.get("res")
        if res is None:
            return None
        if res.image.width * res.image.height > im.PREVIEW_PIXELS:
            # a big print: keep it for the next export, but keep showing the fast preview
            self._full = (self.gen, res)
            if not (self.result is not None and self.result_gen == self.gen):
                self.timer.start()
            return res
        self.result, self.result_gen = res, self.gen
        self._show_result(res)
        return res

    # ==================================================================
    # Result display, zoom controls and close-up (loupe)
    # ==================================================================
    def _show_result(self, res: im.ProcessResult) -> None:
        old = self.result_size
        # one screen copy shared by the preview and the close-up (a 250 MP print is 1 GB per copy)
        # a big print is shown from a screen-sized preview, but always in output pixels
        pm = QPixmap.fromImage(pil_to_qimage(res.image))
        W, H = res.out_size
        self.view_out.set_image(pm, keep_view=True, logical_size=(W, H))
        self.cu_after.set_image(pm, logical_size=(W, H))
        self._cu_tile = None
        self.cu_before.set_image(self._oriented_qimage())
        self.result_size = (W, H)
        if self._cu_pt is None or old != (W, H):
            if self._cu_pt is not None and old:
                self._cu_pt = (self._cu_pt[0] / old[0] * W, self._cu_pt[1] / old[1] * H)
            else:
                self._cu_pt = (W / 2, H / 2)
        self._update_out_info()
        self._update_closeup()
        self._on_view_zoom(self.view_out.zoom())

    @staticmethod
    def _z_to_slider(z: float) -> int:
        z = min(max(z, ZOOM_MIN), ZOOM_MAX)
        return int(round(1000 * math.log(z / ZOOM_MIN) / math.log(ZOOM_MAX / ZOOM_MIN)))

    @staticmethod
    def _slider_to_z(v: int) -> float:
        return ZOOM_MIN * (ZOOM_MAX / ZOOM_MIN) ** (v / 1000.0)

    def _on_view_zoom(self, z: float) -> None:
        self.sl_zoom.blockSignals(True)
        self.sl_zoom.setValue(self._z_to_slider(z))
        self.sl_zoom.blockSignals(False)
        self.cb_zoom.setText(f"{z * 100:.0f}%")

    def _on_zoom_slider(self, v: int) -> None:
        if self.view_out.has_image():
            self.view_out.zoom_to(self._slider_to_z(v))
            self.cb_zoom.setText(f"{self.view_out.zoom() * 100:.0f}%")

    def _zoom_step(self, f: float) -> None:
        if self.view_out.has_image():
            self.view_out.zoom_to(min(ZOOM_MAX, max(ZOOM_MIN, self.view_out.zoom() * f)))

    def _on_zoom_text(self, text: str) -> None:
        t = text.strip().lower().rstrip("%").strip()
        if t in ("fit", ""):
            self.view_out.fit()
            return
        try:
            z = float(t) / 100.0
        except ValueError:
            self._on_view_zoom(self.view_out.zoom())
            return
        self.view_out.zoom_to(min(ZOOM_MAX, max(ZOOM_MIN, z)))

    def open_fullscreen(self) -> None:
        res = self._fresh_result()
        if not res:
            return
        name = self.src.path.name if self.src and self.src.path else "Image"
        FullscreenViewer(self, pil_to_qimage(res.image),
                         f"{name} – {res.image.width} × {res.image.height} px").run()

    def _toggle_loupe(self, on: bool) -> None:
        self.cu_pane.setVisible(on)
        self._update_closeup()

    def _cu_settings(self):
        rs, _os = self.current_settings()
        return rs

    def _update_closeup(self) -> None:
        if not self.src or not self.result or self._cu_pt is None or not self.btn_cu.isChecked():
            self.view_out.set_marker(None)
            return
        rx, ry = self._cu_pt
        z = self.cb_cu_zoom.currentData() or 2.0
        self.cu_after.look(z, rx, ry)
        sx, sy, k = im.result_to_source((rx, ry), self.src, self.state, self._cu_settings(),
                                        self.result_size)
        self.cu_before.look(z * k, sx, sy)
        vw = self.cu_after.viewport().width() / z
        vh = self.cu_after.viewport().height() / z
        self.view_out.set_marker(QRectF(rx - vw / 2, ry - vh / 2, vw, vh))
        mag = z * k
        self.cu_hint.setText(
            f"Showing {z * 100:.0f}% of the result ({mag:.1f}× the original pixels). "
            + ("Pinned – click to unpin." if self._cu_pinned else "Click to pin this spot."))
        if self.result.is_preview:
            self._cu_view = QRectF(rx - vw / 2, ry - vh / 2, vw, vh)
            t = self.cu_after.tile_rect
            if t is None or not t.contains(self._cu_view.intersected(QRectF(0, 0, *self.result_size))):
                self._cu_timer.start()           # real pixels for this spot, in a moment

    def _request_tile(self) -> None:
        """Make the real output pixels around the close-up spot (a big print is only previewed)."""
        if not self.src or not self.result or not self.result.is_preview or not self.btn_cu.isChecked():
            return
        if getattr(self, "_cu_busy", False):
            self._cu_timer.start()
            return
        W, H = self.result_size
        v = self._cu_view
        m = 0.5                                       # margin: small moves need no new tile
        x0, y0 = max(0, int(v.left() - v.width() * m)), max(0, int(v.top() - v.height() * m))
        x1, y1 = min(W, int(v.right() + v.width() * m) + 1), min(H, int(v.bottom() + v.height() * m) + 1)
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) > 4_000_000:
            return
        from app.ui.worker import run_bg
        src, st, gen = self.src, self.state.copy(), self.gen
        rs, _os = self.current_settings()
        self._cu_busy = True

        def done(img):
            self._cu_busy = False
            if gen == self.gen and self.result is not None and self.result.is_preview:
                self.cu_after.set_tile(QPixmap.fromImage(pil_to_qimage(img)), x0, y0)

        def failed(_msg):
            self._cu_busy = False

        # without AI: it takes seconds per spot and handles one job at a time (it would hold up the
        # AI Upscale window); the full-size Download still uses AI
        run_bg(lambda _p: im.render_region(src, st, rs, (x0, y0, x1, y1), None), done, failed)

    def _on_out_hover(self, x: float, y: float) -> None:
        if self._cu_pinned or not self.result:
            return
        w, h = self.result_size
        if 0 <= x <= w and 0 <= y <= h:
            self._cu_pt = (x, y)
            self._update_closeup()

    def _on_out_click(self, x: float, y: float) -> None:
        self._cu_pinned = not self._cu_pinned
        if self._cu_pinned and self.result:
            self._cu_pt = (min(max(x, 0), self.result_size[0]), min(max(y, 0), self.result_size[1]))
        self._update_closeup()

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

    # ==================================================================
    # AI Upscale studio
    # ==================================================================
    def open_upscale(self) -> None:
        if not self.src:
            self.statusBar().showMessage("Open an image first.", 3000)
            return
        img = im.apply_edits(self.src.image, self.state)
        name = self.src.path.name if self.src.path else None
        dlg = UpscaleDialog(self, img, name, self.ai, self.sp_dpi.value())
        dlg.applied.connect(self._apply_upscaled)
        dlg.exec()

    def _apply_upscaled(self, img, us, dpi: int, unit: str) -> None:
        prev = self._before_upscale[0] if self._before_upscale else (self.src, self.state.copy())
        f = img.width / max(1, im.apply_edits(self.src.image, self.state).width)
        label = f"✨ AI upscaled {f:.1f}×"
        li = replace(self.src, image=img, file_size=0, dpi=None, n_frames=1)
        self._before_upscale = (prev, label)
        if dpi:
            self.sp_dpi.blockSignals(True)
            self.sp_dpi.setValue(dpi)
            self.sp_dpi.blockSignals(False)
            self._update_out_summary()
        if unit:
            self.print_unit = unit
        self._set_source(li, upscale_label=label)
        self.up_badge.setToolTip(f"{MODES[us.mode][0]} · detail {us.detail} · noise {us.denoise} · "
                                 f"texture {us.texture}")
        self.cb_unit.setCurrentText("px")
        self.statusBar().showMessage(f"Now editing the upscaled image ({img.width} × {img.height} px). "
                                     "Download Print File saves it at full resolution.", 8000)

    def undo_upscale(self) -> None:
        if not self._before_upscale:
            return
        (src, state), _label = self._before_upscale
        self._before_upscale = None
        self._set_source(src)
        self.state = state
        self._refresh_all()
        self.statusBar().showMessage("Back to the image before upscaling.", 4000)

    # ==================================================================
    # Customer previews
    # ==================================================================
    def _preview_ctx(self) -> Optional[PreviewContext]:
        res = self._fresh_result()
        if not res:
            self.statusBar().showMessage("Open an image first.", 3000)
            return None
        dpi = self.sp_dpi.value()
        po = self._print_override
        if po and po[0] == res.image.size and po[1] == dpi:
            spec = po[2]
        else:
            spec = sh.PrintSpec.from_pixels(res.image.width, res.image.height, dpi, self.print_unit)
        name = self.src.path.name if self.src and self.src.path else None
        return PreviewContext(res.image, name, dpi, spec, self.wa_target, self.wa_phone,
                              download_original=self.save_image, classic_proof=self.open_proof)

    def _remember_print(self, ctx: PreviewContext, dlg) -> None:
        spec = dlg.spec()
        self._print_override = (ctx.image.size, ctx.dpi, spec)
        self.print_unit = spec.unit
        self._update_size_info()

    def open_download_preview(self) -> None:
        ctx = self._preview_ctx()
        if not ctx:
            return
        dlg = DownloadPreviewDialog(self, ctx)
        dlg.exec()
        self._remember_print(ctx, dlg)

    def open_closeup_preview(self) -> None:
        ctx = self._preview_ctx()
        if not ctx:
            return
        dlg = CloseupPrintPreviewDialog(self, ctx)
        dlg.exec()
        self._remember_print(ctx, dlg)

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
        if self._before_upscale and self.src and self.src.path:
            src_name = f"{self.src.path.stem}_upscaled{self.src.path.suffix}"
        return im.auto_filename(src_name, res.image.width, res.image.height, res.fmt)

    def save_image(self) -> Optional[Path]:
        res = self._fresh_result()
        if not res:
            return None
        start_dir = self.settings.value("last_save_dir", "")
        if not start_dir:
            start_dir = str(self.src.path.parent) if self.src.path else str(Path.home() / "Pictures")
        ext = im.FORMATS[res.fmt]["ext"]
        flt = f"{res.fmt} file (*{ext})"
        path, _ = QFileDialog.getSaveFileName(self, "Download print file",
                                              str(Path(start_dir) / self._default_name(res)), flt)
        if not path:
            return None
        p = Path(path)
        if p.suffix.lower() not in (ext, ".jpeg" if res.fmt == "JPG" else ext, ".tiff" if res.fmt == "TIFF" else ext):
            p = p.with_suffix(ext)
        from app.ui.errors import save_or_warn, write_bytes_safely
        if not save_or_warn(self, lambda: write_bytes_safely(p, res.data), p):
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
            f"Image Resize, Crop & Share {__version__}\n\n"
            "Ctrl+O  Open image          Ctrl+V  Paste image\n"
            "Ctrl+S  Download print file  Ctrl+Shift+C  Copy result\n"
            "Ctrl+U  AI Upscale          Ctrl+W  WhatsApp\n"
            "Ctrl+P  Download Preview    Ctrl+Shift+P  Closeup Print Preview\n"
            "Ctrl+Alt+P  Classic proof sheet   Ctrl+B  Batch mode\n"
            "Ctrl+Z / Ctrl+Y  Undo / Redo     F11  Full screen preview\n"
            "Ctrl+R / Ctrl+L  Rotate right / left\n"
            "Ctrl+1 / Ctrl+2  Resize / Crop\n\n"
            "Preview: mouse wheel = zoom, drag = pan, double-click = 100% / fit.\n\n"
            "Wallpaper & print tips:\n"
            "• Murals are seen from a distance: 100–150 DPI is plenty.\n"
            "• Use AI Upscale → 'Fit a print / wall size' to make a small design big enough.\n"
            "• Check sharpness in Closeup Print Preview before printing.\n"
            "• On WhatsApp, send as Document to avoid compression."))

    # ==================================================================
    # Wall Studio / settings
    # ==================================================================
    def send_to_studio(self) -> None:
        """Use the current (edited) image as the design of a Wall Studio job."""
        res = self._fresh_result()
        if not res:
            return
        name = self.src.path.name if self.src and self.src.path else "image.png"
        self.set_page(1)
        self.studio.use_image(res.image, name)

    def open_business(self) -> None:
        from app.ui.settings_dialogs import BusinessDialog
        BusinessDialog(self).exec()

    def open_presets(self) -> None:
        from app.ui.settings_dialogs import PresetsDialog
        PresetsDialog(self).exec()
        if self.studio is not None:
            self.studio.reload_presets()

    def open_data(self) -> None:
        from app.ui.settings_dialogs import DataDialog
        DataDialog(self).exec()

    def run_auto_backup(self) -> None:
        """Background backup when one is due (Data & Backup settings)."""
        from app.ui.settings_dialogs import auto_backup_due
        d = auto_backup_due()
        if d is None:
            return
        from app.core import backup as bk
        from app.ui.worker import run_bg
        self.statusBar().showMessage("Backing up your jobs in the background…", 4000)

        def work(_p):
            r = bk.backup(d)
            bk.prune(d, 5)
            return r

        run_bg(work, lambda r: self.statusBar().showMessage(f"Backup saved: {r.path.name}", 6000),
               lambda m: self.statusBar().showMessage(f"Automatic backup failed: {m}", 8000),
               task="the automatic backup")

    def open_cloud(self) -> None:
        from app.ui.settings_dialogs import CloudDialog
        CloudDialog(self).exec()

    def closeEvent(self, ev) -> None:
        from app.ui.worker import busy_tasks
        busy = busy_tasks()
        if busy:
            box = QMessageBox(self)
            box.setWindowTitle("Still working")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"The app is still busy: {', '.join(sorted(set(busy)))}.\n\n"
                        "If you close now, those files will not be finished.")
            wait = box.addButton("Wait", QMessageBox.ButtonRole.RejectRole)
            box.addButton("Close anyway", QMessageBox.ButtonRole.DestructiveRole)
            box.setDefaultButton(wait)
            box.exec()
            if box.clickedButton() is wait:
                ev.ignore()
                return
        if self.studio is not None and not self.studio.save_now():
            if QMessageBox.question(self, "Job not saved", "The open job could not be saved.\n\n"
                                    "Close anyway and lose the latest changes?") != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
        self._save_settings()
        self.pool.waitForDone(3000)
        super().closeEvent(ev)
