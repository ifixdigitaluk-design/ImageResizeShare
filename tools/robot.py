"""Click-everything robot: a QA helper that drives the real app like an impatient user.

It opens the main window offscreen, loads good and bad pictures, then clicks every button,
fills every box with odd values, changes every list and tab, opens every dialog (and the
dialogs inside them) and accepts or cancels them at random. File pickers, message boxes and
input boxes are answered automatically. Every unexpected error is collected; the run fails
if there were any.

    QT_QPA_PLATFORM=offscreen python tools/robot.py [scenario ...] [--seed N] [--rounds N] [--mem] [--out DIR]

On Linux, run it with MALLOC_MMAP_THRESHOLD_=1048576 so big pictures are given back to the system
when freed, as Windows does (otherwise Linux keeps them and memory looks far higher than on a PC).
--mem prints the memory used and the biggest pictures still held after each scenario.
--out DIR copies the robot's step log (and the app's error log, if any) there at the end (used by CI).

Scenarios: nav, editor, files, studio, dialogs, extreme, jobs (default: all).
Your real jobs are never touched: everything runs in a temporary IRS_HOME.
"""
from __future__ import annotations

import faulthandler
import os
import random
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = Path(tempfile.mkdtemp(prefix="irs_robot_"))
os.environ["IRS_HOME"] = str(TMP / "home")
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")      # Linux: the app's settings go here, not yours

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QEventLoop, QSettings, QtMsgType, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QColor, QDesktopServices, QFont  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QApplication,  # noqa: E402
                               QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QInputDialog, QLineEdit, QListWidget, QMenu, QMessageBox,
                               QPlainTextEdit, QRadioButton, QSpinBox, QTabWidget, QTableWidget,
                               QTextEdit, QWidget)

ERRORS: list[str] = []


class _Log(list):
    """Kept in memory and written as it goes, so a crash still shows the last steps."""
    def append(self, line):
        super().append(line)
        try:
            with open(TMP / "robot.log", "a", encoding="utf-8") as f:
                f.write(f"{time.monotonic():.1f} {line}\n")
        except OSError:
            pass


LOG: list[str] = _Log()
RNG = random.Random(1)
MAX_DEPTH = 2
CLICKS_PER_ROOT = 60
_depth = [0]
_scenario = ["?"]
_skip_words = ("quit", "exit")


# ---------------------------------------------------------------- fixtures
def make_fixtures() -> dict:
    d = TMP / "files"
    d.mkdir(parents=True)
    f = {}
    img = Image.new("RGB", (1600, 1100), (40, 110, 190))
    dr = ImageDraw.Draw(img)
    for i in range(0, 1600, 40):
        dr.line([(i, 0), (i, 1100)], fill=(250, 250, 250), width=3)
    dr.rectangle([500, 300, 900, 1000], fill=(120, 70, 30))          # a "door"
    f["good"] = d / "قالین تصویر – good.jpg"                           # Urdu name
    img.save(f["good"], quality=92)
    f["png_alpha"] = d / "alpha.png"
    Image.new("RGBA", (800, 600), (200, 30, 30, 120)).save(f["png_alpha"])
    f["tiny"] = d / "tiny.png"
    Image.new("RGB", (1, 1), (0, 0, 0)).save(f["tiny"])
    f["strip"] = d / "strip.png"
    Image.new("RGB", (4000, 8), (0, 200, 0)).save(f["strip"])
    f["tall"] = d / "tall.png"
    Image.new("RGB", (6, 3000), (0, 0, 200)).save(f["tall"])
    f["cmyk"] = d / "cmyk.jpg"
    Image.new("CMYK", (500, 400), (0, 80, 80, 0)).save(f["cmyk"])
    f["gray16"] = d / "gray16.png"
    Image.new("I;16", (300, 200), 30000).save(f["gray16"])
    f["pal"] = d / "palette.gif"
    img.convert("P").resize((400, 300)).save(f["pal"])
    f["empty"] = d / "empty.jpg"
    f["empty"].write_bytes(b"")
    f["corrupt"] = d / "corrupt.jpg"
    f["corrupt"].write_bytes(os.urandom(5000))
    raw = f["good"].read_bytes()
    f["truncated"] = d / "truncated.jpg"
    f["truncated"].write_bytes(raw[: len(raw) // 3])
    f["text_as_png"] = d / "notes.png"
    f["text_as_png"].write_text("not a picture")
    f["missing"] = d / "deleted.jpg"
    return f


FX: dict = {}


def pick_open(kind: str = "") -> str:
    """What the robot 'chooses' in an Open dialog."""
    r = RNG.random()
    if r < 0.12:
        return ""                                   # Cancel
    if _scenario[0] in ("files", "extreme") or r < 0.45:
        return str(RNG.choice(list(FX.values())))
    return str(RNG.choice([FX["good"], FX["png_alpha"], FX["cmyk"], FX["pal"]]))


def pick_save(suffix: str = ".jpg") -> str:
    r = RNG.random()
    if r < 0.12:
        return ""
    out = TMP / "out"
    out.mkdir(exist_ok=True)
    if r < 0.2:                                     # read-only file
        p = out / f"locked{suffix}"
        p.write_bytes(b"x")
        p.chmod(0o444)
        return str(p)
    if r < 0.25:                                    # folder that doesn't exist
        return str(out / "gone" / f"x{suffix}")
    return str(out / f"saved_{RNG.randint(0, 9999)} ✓{suffix}")


def _suffix(filter_: str) -> str:
    import re
    m = re.search(r"\*(\.\w+)", filter_ or "")
    return m.group(1) if m else ".jpg"


# ---------------------------------------------------------------- automatic answers
def install_patches() -> None:
    def gofn(*a, **k):
        p = pick_open()
        return p, ""

    def gofns(*a, **k):
        p = pick_open()
        return ([p, str(FX["good"])] if p else []), ""

    def gsfn(parent=None, caption="", dir_="", filter_="", *a, **k):
        filt = k.get("filter", filter_) or (a[0] if a else "")
        return pick_save(_suffix(filt)), ""

    def gdir(*a, **k):
        if RNG.random() < 0.2:
            return ""
        p = TMP / "dirs" / f"d{RNG.randint(0, 99)}"
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    QFileDialog.getOpenFileName = staticmethod(gofn)
    QFileDialog.getOpenFileNames = staticmethod(gofns)
    QFileDialog.getSaveFileName = staticmethod(gsfn)
    QFileDialog.getExistingDirectory = staticmethod(gdir)

    def mb_static(default_ok):
        def f(parent, title, text="", buttons=None, default=None, *a, **k):
            LOG.append(f"msg: {title}: {str(text)[:120]!r}")
            if buttons is None:
                return QMessageBox.StandardButton.Ok
            opts = [b for b in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Cancel,
                                QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Discard)
                    if buttons & b]
            return RNG.choice(opts) if opts else QMessageBox.StandardButton.Ok
        return staticmethod(f)

    for name in ("question", "warning", "information", "critical"):
        setattr(QMessageBox, name, mb_static(True))
    QMessageBox.about = staticmethod(lambda parent, title, text: LOG.append(f"about: {title}"))

    odd_text = ["", " ", "Test", "x" * 300, "60 x 90 cm", "abc", "-5", "0", "١٢٣", "قالین", "a/b\\c:*?", "\n\n"]

    def gtext(*a, **k):
        return RNG.choice(odd_text), RNG.random() > 0.15

    def gnum(*a, **k):
        lo = k.get("minValue", None)
        v = RNG.choice([0, 1, 50, 99999, -1, 0.1])
        if lo is not None:
            v = max(v, lo)
        return v, RNG.random() > 0.15

    def gdouble(parent, title, label, value=0.0, minValue=-2147483647, maxValue=2147483647, *a, **k):
        v = RNG.choice([minValue, maxValue, value, (minValue + maxValue) / 2])
        return max(minValue, min(maxValue, v)), RNG.random() > 0.15

    def gitem(parent, title, label, items, *a, **k):
        items = list(items)
        return (RNG.choice(items) if items else ""), RNG.random() > 0.15

    QInputDialog.getText = staticmethod(gtext)
    QInputDialog.getMultiLineText = staticmethod(gtext)
    QInputDialog.getInt = staticmethod(gnum)
    QInputDialog.getDouble = staticmethod(gdouble)
    QInputDialog.getItem = staticmethod(gitem)
    QColorDialog.getColor = staticmethod(
        lambda *a, **k: QColor() if RNG.random() < 0.2 else QColor(RNG.randint(0, 255), 30, 200))
    QDesktopServices.openUrl = staticmethod(lambda *a, **k: LOG.append(f"openUrl {a[0]}") or True)
    from app.ui import support                       # "Check for updates": no internet in tests
    support.fetch_releases = lambda *a, **k: [{"tag_name": "windows-v9.9.9.1", "html_url": "https://example.invalid"}]
    import subprocess
    subprocess.Popen = lambda *a, **k: LOG.append(f"Popen {a}")      # never start other programs
    if hasattr(os, "startfile"):
        os.startfile = lambda *a, **k: None

    orig_dialog_exec = QDialog.exec
    orig_mb_exec = QMessageBox.exec

    def dialog_exec(self, *a, **k):
        name = type(self).__name__
        LOG.append(f"{'  ' * _depth[0]}dialog {name} {self.windowTitle()!r}")
        if isinstance(self, QMessageBox):
            return mbox_exec(self)
        self.show()
        pump(0.05)
        if _depth[0] < MAX_DEPTH:
            _depth[0] += 1
            try:
                explore(self, CLICKS_PER_ROOT // 2)
            finally:
                _depth[0] -= 1
        try:
            if not self.isVisible():                 # one of its buttons closed it
                return QDialog.result(self)
            if RNG.random() < 0.5:
                self.accept()
            else:
                self.reject()
            pump(0.02)
            return QDialog.result(self)
        except RuntimeError:                         # deleted meanwhile
            return 0

    def mbox_exec(self, *a, **k):
        _answered.add(id(self))
        LOG.append(f"msgbox {self.text()[:100]!r}")
        btns = self.buttons()
        if btns:
            b = RNG.choice(btns)
            self.show()
            b.click()
            pump(0.01)
            try:
                return QDialog.result(self)
            except RuntimeError:
                return 0
        return QMessageBox.StandardButton.Ok

    QDialog.exec = dialog_exec
    QMessageBox.exec = mbox_exec
    QDialog.exec_ = dialog_exec
    _ = orig_dialog_exec, orig_mb_exec

    # Menus and plain message boxes: PySide ignores a replaced QMenu.exec / QMessageBox.exec on the
    # class, so answer them when they appear instead (works however they are opened).
    from PySide6.QtCore import QEvent, QObject, QTimer

    def answer_menu(menu) -> None:
        try:
            if not menu.isVisible():
                return
            acts = [x for x in menu.actions() if x.isEnabled() and not x.isSeparator() and x.isVisible()]
            LOG.append(f"menu {[x.text() for x in acts]}")
            menu.close()
            if not acts or RNG.random() < 0.15:
                return
            act = RNG.choice(acts)
            while act.menu() is not None:               # a sub-menu: pick in it
                sub = [x for x in act.menu().actions() if x.isEnabled() and not x.isSeparator()]
                if not sub:
                    return
                act = RNG.choice(sub)
            act.trigger()
        except RuntimeError:                            # deleted meanwhile
            pass

    def answer_box(box) -> None:
        try:
            if not box.isVisible() or id(box) in _answered:
                return
            _answered.add(id(box))
            LOG.append(f"msgbox {box.text()[:100]!r}")
            btns = box.buttons()
            if btns:
                RNG.choice(btns).click()
            else:
                box.close()
        except RuntimeError:
            pass

    class _Answer(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Show:
                if isinstance(obj, QMenu):
                    QTimer.singleShot(0, lambda m=obj: answer_menu(m))
                elif isinstance(obj, QMessageBox) and id(obj) not in _answered:
                    QTimer.singleShot(0, lambda b=obj: answer_box(b))
            return False

    global _ANSWER
    _ANSWER = _Answer()
    QApplication.instance().installEventFilter(_ANSWER)


_answered: set = set()
_ANSWER = None


# ---------------------------------------------------------------- driving
def free_closed() -> None:
    """The robot never starts app.exec(), so Qt would never free closed dialogs (deleteLater waits
    for the main event loop). Free them like the real app does, between top-level steps."""
    from PySide6.QtCore import QCoreApplication, QEvent
    if _depth[0] == 0:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def pump(seconds: float = 0.05) -> None:
    app = QApplication.instance()
    end = time.monotonic() + seconds
    while True:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if time.monotonic() >= end:
            break
        time.sleep(0.005)


def wait_background(limit: float = 60) -> None:
    from app.ui import worker
    from PySide6.QtCore import QThreadPool
    end = time.monotonic() + limit
    pool = QThreadPool.globalInstance()
    while (worker._RUNNING or pool.activeThreadCount()) and time.monotonic() < end:
        pump(0.05)
    pump(0.05)


def alive(w) -> bool:
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def label_of(w) -> str:
    t = ""
    try:
        t = w.text() if hasattr(w, "text") else ""
    except Exception:
        pass
    return (t or w.toolTip() or w.objectName() or type(w).__name__).replace("\n", " ")[:40]


def candidates(root: QWidget) -> list:
    out = []
    for cls in (QAbstractButton, QComboBox, QAbstractSpinBox, QLineEdit, QAbstractSlider, QTabWidget,
                QListWidget, QTableWidget, QPlainTextEdit, QTextEdit):
        for w in root.findChildren(cls):
            try:
                if w.isVisible() and w.isEnabled() and w.window() is root.window():
                    out.append(w)
            except RuntimeError:
                pass
    return out


ODD_LINE = ["", "0", "-1", "999999", "1e9", "abc", "  12  ", "x" * 500, "07700 900123", "+44 (0)7700 900123",
            "قالین", "a/b\\c:*?\"<>|", "12,5", "nan", "inf"]


def act(w) -> str:
    """Do one thing to a widget. Returns what was done."""
    if isinstance(w, QAbstractButton):
        if any(s in label_of(w).lower() for s in _skip_words):
            return ""
        if isinstance(w, (QCheckBox, QRadioButton)) or w.isCheckable():
            w.click()
        else:
            w.click()
        return f"click {label_of(w)!r}"
    if isinstance(w, QComboBox):
        if w.count():
            if w.isEditable() and RNG.random() < 0.3:
                w.setEditText(RNG.choice(ODD_LINE))
                if w.lineEdit():
                    w.lineEdit().editingFinished.emit()
                return f"combo text {w.objectName()}"
            i = RNG.randrange(w.count())
            w.setCurrentIndex(i)
            w.activated.emit(i)
            return f"combo {w.itemText(i)[:30]!r}"
        return ""
    if isinstance(w, (QSpinBox, QDoubleSpinBox)):
        v = RNG.choice([w.minimum(), w.maximum(), w.minimum() + (w.maximum() - w.minimum()) * RNG.random(),
                        w.value()])
        if isinstance(w, QSpinBox):
            v = int(v)
        w.setValue(v)
        w.editingFinished.emit()
        return f"spin {type(w).__name__}={v}"
    if isinstance(w, QAbstractSpinBox):
        w.stepUp() if RNG.random() < 0.5 else w.stepDown()
        return "step"
    if isinstance(w, QLineEdit):
        if w.isReadOnly():
            return ""
        w.setText(RNG.choice(ODD_LINE))
        w.textEdited.emit(w.text())
        w.editingFinished.emit()
        if RNG.random() < 0.3:
            w.returnPressed.emit()
        return f"type {w.text()[:20]!r}"
    if isinstance(w, QAbstractSlider):
        w.setValue(RNG.choice([w.minimum(), w.maximum(), (w.minimum() + w.maximum()) // 2]))
        w.sliderReleased.emit()
        return f"slide {w.value()}"
    if isinstance(w, QTabWidget):
        if w.count():
            w.setCurrentIndex(RNG.randrange(w.count()))
        return f"tab {w.currentIndex()}"
    if isinstance(w, (QListWidget,)):
        if w.count():
            it = w.item(RNG.randrange(w.count()))
            w.setCurrentItem(it)
            w.itemClicked.emit(it)
            if RNG.random() < 0.3:
                w.itemDoubleClicked.emit(it)
        return "list"
    if isinstance(w, QTableWidget):
        if w.rowCount() and w.columnCount():
            r, c = RNG.randrange(w.rowCount()), RNG.randrange(w.columnCount())
            w.setCurrentCell(r, c)
            w.cellClicked.emit(r, c)
            if RNG.random() < 0.3:
                w.cellDoubleClicked.emit(r, c)
        return "table"
    if isinstance(w, (QPlainTextEdit, QTextEdit)):
        if not w.isReadOnly():
            w.setPlainText(RNG.choice(ODD_LINE))
        return "text"
    return ""


DEADLINE = [0.0]          # each scenario gets a time limit, so one giant print can't stall the run


def explore(root: QWidget, budget: int) -> None:
    done = 0
    tried: set = set()
    while done < budget and time.monotonic() < DEADLINE[0]:
        try:
            if not alive(root) or not root.isVisible():
                return
            ws = [w for w in candidates(root) if id(w) not in tried] or candidates(root)
        except RuntimeError:
            return
        if not ws:
            return
        w = RNG.choice(ws)
        tried.add(id(w))
        try:
            what = act(w)
        except RuntimeError as exc:
            if "already deleted" in str(exc):
                continue
            raise
        if what:
            LOG.append(f"{'  ' * _depth[0]}{_scenario[0]}: {what}")
        done += 1
        pump(0.02)
        wait_background(8)
        free_closed()


def on_qt_message(mode, ctx, msg):
    noisy = ("propagateSizeHints", "This plugin does not support", "QFont::setPointSize", "Fontconfig",
             "Targets are not supported", "QWindowsWindow", "setGeometry", "QPainter::begin",
             "QBasicTimer", "Unknown property", "OpenType support missing")
    if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) or (
            mode == QtMsgType.QtWarningMsg and not any(n in msg for n in noisy)):
        LOG.append(f"QT {mode.name}: {msg}")
        if mode != QtMsgType.QtWarningMsg:
            ERRORS.append(f"[{_scenario[0]}] Qt: {msg}")


# ---------------------------------------------------------------- scenarios
def sc_editor(w):
    w.set_page(0)
    w.load_path(str(FX["good"]))
    pump(0.3)
    wait_background()
    explore(w.pages.currentWidget(), CLICKS_PER_ROOT)


def sc_files(w):
    w.set_page(0)
    for k, p in FX.items():
        LOG.append(f"files: load {k}")
        w.load_path(str(p))
        pump(0.1)
        wait_background()
        explore(w.pages.currentWidget(), 6)
    w.set_page(1)
    pump(0.1)
    explore(w.pages.currentWidget(), 20)


def sc_studio(w):
    w.set_page(1)
    pump(0.2)
    explore(w.pages.currentWidget(), CLICKS_PER_ROOT)


def sc_dialogs(w):
    for page in (0, 1, 2):
        w.set_page(page)
        pump(0.2)
        root = w.pages.currentWidget()
        btns = [b for b in candidates(root) if isinstance(b, QAbstractButton)]
        RNG.shuffle(btns)
        for b in btns[:40]:
            if time.monotonic() > DEADLINE[0]:
                return
            if alive(b) and b.isVisible() and b.isEnabled():
                LOG.append(f"dialogs: click {label_of(b)!r}")
                b.click()
                pump(0.05)
                wait_background(8)
                free_closed()


def sc_extreme(w):
    global CLICKS_PER_ROOT
    keep = CLICKS_PER_ROOT
    CLICKS_PER_ROOT = 120
    try:
        for page in (0, 1, 0, 1):
            w.set_page(page)
            if page == 0:
                w.load_path(str(RNG.choice([FX["tiny"], FX["strip"], FX["tall"], FX["gray16"]])))
                wait_background()
            explore(w.pages.currentWidget(), 60)
    finally:
        CLICKS_PER_ROOT = keep


def sc_jobs(w):
    w.set_page(2)
    pump(0.2)
    jp = w.jobs_page
    for fn in ("show_library", "show_installs"):
        if hasattr(jp, fn):
            getattr(jp, fn)()
            pump(0.1)
            explore(w.pages.currentWidget(), 30)
    explore(w.pages.currentWidget(), CLICKS_PER_ROOT)


def mem_report(top: int = 6) -> str:
    """The biggest pictures still in memory and what holds them (finds leaks)."""
    import gc
    from PySide6.QtGui import QImage, QPixmap
    gc.collect()
    rows = []
    every = gc.get_objects()
    for o in every:
        try:
            if isinstance(o, Image.Image) and getattr(o, "im", None) is not None:
                mb = o.width * o.height * len(o.getbands()) / 1e6
            elif isinstance(o, (QImage, QPixmap)) and not o.isNull():
                mb = o.width() * o.height() * 4 / 1e6
            else:
                continue
        except Exception:
            continue
        if mb < 20:
            continue
        holders = []
        for r in gc.get_referrers(o):
            if r is every or r is rows:
                continue
            if isinstance(r, dict):
                holders.extend(str(k) for k, v in r.items() if v is o)
            else:
                names = [k for k, v in getattr(r, "__dict__", {}).items() if v is o]
                holders.append(f"{type(r).__name__}.{names[0]}" if names else type(r).__name__)
        rows.append((mb, f"{type(o).__name__} {getattr(o, 'size', '')} {mb:.0f} MB held by {holders[:4]}"))
    rows.sort(reverse=True)
    return "\n".join(r for _, r in rows[:top]) or "(no big pictures)"


def sc_nav(w):
    """The top bar of each page (Download, Room View, Send to Print, Help …) and the page tabs."""
    from PySide6.QtWidgets import QToolButton
    for page in (0, 1, 2, 1, 0):
        w.set_page(page)
        if page == 0 and w.src is None:
            w.load_path(str(FX["good"]))
            wait_background()
        pump(0.1)
        bar = w.nav_groups[page]
        btns = [b for b in bar.findChildren(QToolButton) if b.isVisible() and b.isEnabled()]
        RNG.shuffle(btns)
        for b in btns:
            if time.monotonic() > DEADLINE[0]:
                return
            if alive(b) and b.isVisible() and b.isEnabled():
                LOG.append(f"nav: click {label_of(b)!r}")
                b.click()
                pump(0.05)
                wait_background(8)
                free_closed()
                if w.pages.currentIndex() != page:       # a button may switch pages: come back
                    w.set_page(page)


SCENARIOS = {"nav": sc_nav, "editor": sc_editor, "files": sc_files, "studio": sc_studio, "dialogs": sc_dialogs,
             "extreme": sc_extreme, "jobs": sc_jobs}


def main() -> int:
    args = sys.argv[1:]
    seed = 1
    rounds = 1
    if "--seed" in args:
        i = args.index("--seed")
        seed = int(args[i + 1])
        del args[i:i + 2]
    if "--rounds" in args:
        i = args.index("--rounds")
        rounds = int(args[i + 1])
        del args[i:i + 2]
    out_dir = None
    if "--out" in args:
        i = args.index("--out")
        out_dir = Path(args[i + 1])
        del args[i:i + 2]
    args = [a for a in args if a != "--mem"]
    names = args or list(SCENARIOS)
    faulthandler.enable()
    faulthandler.dump_traceback_later(1500, exit=True)

    from app.ui import errors
    from app.ui.main_window import MainWindow
    from app.ui.qtutil import app_icon
    from app.ui.style import QSS

    errors.install(show_dialogs=False)
    real_hook = sys.excepthook

    def hook(t, v, tb):
        ERRORS.append(f"[{_scenario[0]}] " + "".join(traceback.format_exception(t, v, tb)))
        real_hook(t, v, tb)
    sys.excepthook = hook

    app = QApplication(sys.argv[:1])
    app.setOrganizationName("ImageResizeShare-robot")      # never touch the real app's settings
    app.setApplicationName("Image Resize & Share (robot)")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())
    # The app keeps its settings under a fixed name (on Windows in the registry). Keep a copy of yours
    # and put it back at the end, so the robot's random choices never stay in your settings.
    real = QSettings("ImageResizeShare", "ImageResizeShare")
    saved = {k: real.value(k) for k in real.allKeys()}

    def restore_settings():
        st = QSettings("ImageResizeShare", "ImageResizeShare")
        st.clear()
        for k, v in saved.items():
            st.setValue(k, v)
        st.sync()
    import atexit
    atexit.register(restore_settings)
    real.remove("studio_last_job")
    qInstallMessageHandler(on_qt_message)
    FX.update(make_fixtures())
    install_patches()

    w = MainWindow()
    w.show()
    pump(0.3)
    for r in range(rounds):
        for n in names:
            RNG.seed(f"{seed}-{r}-{n}")
            _scenario[0] = n
            before = len(ERRORS)
            t0 = time.monotonic()
            DEADLINE[0] = t0 + 240
            try:
                SCENARIOS[n](w)
                wait_background(120)
            except Exception:
                ERRORS.append(f"[{n}] robot step failed: " + traceback.format_exc())
            # a dialog the robot left open would block the next scenario
            for top in QApplication.topLevelWidgets():
                if top is not w and isinstance(top, QDialog) and top.isVisible():
                    top.reject()
            pump(0.1)
            free_closed()
            print(f"{n:8s} round {r + 1}: {len(ERRORS) - before} error(s), {time.monotonic() - t0:.0f}s",
                  flush=True)
            if "--mem" in sys.argv:
                import resource
                rss = int(open("/proc/self/statm").read().split()[1]) * resource.getpagesize() / 1e6
                print(f"  memory now {rss:.0f} MB\n" + mem_report(), flush=True)
    try:
        if hasattr(w, "studio") and hasattr(w.studio, "save_now"):
            w.studio.save_now()
    except Exception:
        ERRORS.append("[end] " + traceback.format_exc())
    print(f"log: {TMP / 'robot.log'}")
    if out_dir is not None:
        import shutil
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in (TMP / "robot.log", errors.log_path()):
            try:
                shutil.copy(f, out_dir / f"seed{seed}_{Path(f).name}")
            except OSError:
                pass
    if errors.COUNT[0] and not ERRORS:
        ERRORS.append(f"{errors.COUNT[0]} error(s) in {errors.log_path()}")
    if ERRORS:
        print(f"\nROBOT FOUND {len(ERRORS)} ERROR(S)\n")
        seen = set()
        for e in ERRORS:
            key = e.strip().splitlines()[-1]
            if key in seen:
                continue
            seen.add(key)
            print(e.rstrip(), "\n" + "-" * 70)
        restore_settings()
        os._exit(1)
    print("ROBOT OK")
    restore_settings()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
