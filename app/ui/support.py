"""Help: send an error report, check for updates, about the app."""
from __future__ import annotations

import json
import platform
import re
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout)

import app as app_pkg
from app import __version__, build_number
from app.ui import errors, share
from app.ui.qtutil import icon

APP = "Image Resize & Share"


# ======================================================================
# Error report
# ======================================================================
def _os_name() -> str:
    """Without starting other programs (platform.platform() runs 'ver' / 'uname', which can fail or
    flash a console window in the packaged app)."""
    try:
        if sys.platform.startswith("win"):
            v = sys.getwindowsversion()
            name = "11" if v.major == 10 and v.build >= 22000 else str(v.major)
            return f"Windows {name} (build {v.build})"
        import os
        u = os.uname()
        return f"{u.sysname} {u.release} {u.machine}"
    except Exception:
        return sys.platform


def system_info() -> str:
    """Facts about this PC that help find a problem (no pictures, jobs or customer details)."""
    lines = [f"{APP} {__version__} (build {build_number() or 'local'})",
             f"Made: {datetime.now():%Y-%m-%d %H:%M}",
             f"Windows/OS: {_os_name()}",
             f"Python {platform.python_version()} ({'packaged app' if getattr(sys, 'frozen', False) else 'from source'})"]
    try:
        import PySide6
        from PIL import __version__ as pil
        lines.append(f"Qt for Python {PySide6.__version__}, Pillow {pil}")
    except Exception:
        pass
    try:
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.geometry()
            lines.append(f"Screen {g.width()}×{g.height()} at {scr.devicePixelRatio() * 100:.0f} % scale")
    except Exception:
        pass
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ave", ctypes.c_ulonglong)]
            m = MS()
            m.len = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            lines.append(f"Memory {m.total / 2**30:.1f} GB, {m.avail / 2**30:.1f} GB free")
    except Exception:
        pass
    try:
        from app.core import paths
        lines.append(f"Data folder: {paths.base_dir()}")
    except Exception:
        pass
    lines.append(f"Errors this session: {errors.COUNT[0]}")
    return "\n".join(lines)


def make_report() -> Path:
    """A zip with the error log and system_info(), ready to send."""
    out = share.temp_folder() / f"ImageResizeShare-error-report-{datetime.now():%Y%m%d-%H%M}.zip"
    log = errors.log_path()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about-this-pc.txt", system_info())
        for p in (log, log.with_suffix(".old.log")):
            if p.is_file():
                z.write(p, p.name)
        if not log.is_file():
            z.writestr("errors.log", "(no errors recorded)")
    return out


def error_count_in_log() -> int:
    try:
        return errors.log_path().read_text(encoding="utf-8", errors="replace").count("\n===== ")
    except OSError:
        return 0


class ErrorReportDialog(QDialog):
    """Make the report and send it: email / WhatsApp to support when set up, or copy / show the file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Send an error report")
        self.report: Optional[Path] = None
        lay = QVBoxLayout(self)
        n = error_count_in_log()
        intro = QLabel(
            f"<b>{'No problems recorded yet.' if n == 0 else f'{n} problem(s) recorded on this PC.'}</b><br><br>"
            "The report is a small zip file with the app's error list and facts about this PC "
            "(Windows version, screen, memory). It has <b>no pictures, jobs or customer details</b> "
            "– only file and folder names that appear in error messages.")
        intro.setWordWrap(True)
        intro.setMinimumWidth(440)
        lay.addWidget(intro)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("Hint")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        if app_pkg.SUPPORT_EMAIL:
            b = QPushButton(icon("doc"), " Email it")
            b.clicked.connect(self.email)
            row.addWidget(b)
        if app_pkg.SUPPORT_WHATSAPP:
            b = QPushButton(icon("whatsapp"), " WhatsApp")
            b.clicked.connect(self.whatsapp)
            row.addWidget(b)
        b = QPushButton(icon("copy"), " Copy the file")
        b.setToolTip("Then paste it (Ctrl+V) into an email or a WhatsApp chat")
        b.clicked.connect(self.copy)
        row.addWidget(b)
        b = QPushButton(icon("folder_open"), " Show the file")
        b.clicked.connect(self.show_file)
        row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

    def _report(self) -> Optional[Path]:
        try:
            self.report = make_report()
            return self.report
        except OSError as exc:
            QMessageBox.warning(self, "Error report", f"The report could not be made:\n{exc}")
            return None

    def copy(self) -> None:
        p = self._report()
        if p:
            share.copy_files_to_clipboard([p])
            self.status.setText(f"Copied {p.name}. Paste it (Ctrl+V) into an email or a WhatsApp chat.")

    def show_file(self) -> None:
        p = self._report()
        if p:
            share.show_in_folder(p)
            self.status.setText(f"{p.name} is selected in the folder that opened.")

    def email(self) -> None:
        p = self._report()
        if not p:
            return
        share.show_in_folder(p)
        body = (f"Hello,\n\nPlease find my {APP} error report attached ({p.name}).\n\n"
                "What I was doing when it happened:\n\n\n" + system_info().split("\n")[0])
        url = QUrl(f"mailto:{app_pkg.SUPPORT_EMAIL}")
        from PySide6.QtCore import QUrlQuery
        q = QUrlQuery()
        q.addQueryItem("subject", f"{APP} error report")
        q.addQueryItem("body", body)
        url.setQuery(q)
        QDesktopServices.openUrl(url)
        self.status.setText(f"Attach {p.name} (selected in the folder that opened) to the email, then send.")

    def whatsapp(self) -> None:
        p = self._report()
        if not p:
            return
        share.copy_files_to_clipboard([p])
        main = self.parent().window() if self.parent() is not None else None
        share.open_whatsapp(getattr(main, "wa_target", "web"), app_pkg.SUPPORT_WHATSAPP,
                            f"{APP} error report – what I was doing: ")
        self.status.setText("The report is copied. In the chat press Ctrl+V, then Send.")


def send_error_report(parent=None) -> None:
    ErrorReportDialog(parent).exec()


# ======================================================================
# Updates
# ======================================================================
def version_tuple(text: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:4])


def current_version() -> Tuple[int, ...]:
    v = version_tuple(__version__)
    return v + (0,) * (3 - len(v)) + (build_number(),)


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": f"ImageResizeShare/{__version__}",
                                               "Accept": "application/vnd.github+json, application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_releases(timeout: float = 8.0) -> list:
    """Releases, newest information first (raises on network problems): from UPDATE_JSON_URL
    (a latest.json made by the GitHub build) when set, else from the repository's GitHub Releases."""
    if app_pkg.UPDATE_JSON_URL:
        d = _get_json(app_pkg.UPDATE_JSON_URL, timeout)
        return [{"tag_name": f"windows-v{d['version']}.{int(d.get('build', 0))}",
                 "html_url": d.get("url", ""), "body": d.get("notes", "")}]
    return _get_json(f"https://api.github.com/repos/{app_pkg.UPDATE_REPO}/releases?per_page=30", timeout)


def newest_windows_release(releases: list) -> Optional[dict]:
    """The newest Windows release ('windows-v3.1.2.57' tags). Older '1.0.x' tags are ignored."""
    best = None
    for rel in releases:
        tag = str(rel.get("tag_name", ""))
        if not tag.startswith("windows-v") or rel.get("draft") or rel.get("prerelease"):
            continue
        v = version_tuple(tag)
        if len(v) < 3 or v[0] < 2:            # 'windows-v1.0.N' came from before versions were tagged
            continue
        v = v + (0,) * (4 - len(v))
        if best is None or v > best[0]:
            best = (v, rel)
    if best is None:
        return None
    v, rel = best
    return {"version": v, "label": ".".join(str(x) for x in v[:3]), "build": v[3],
            "url": rel.get("html_url") or f"https://github.com/{app_pkg.UPDATE_REPO}/releases",
            "notes": (rel.get("body") or "")[:1500]}


def check_for_update() -> Optional[dict]:
    """The newest release if it is newer than this copy, else None (raises on network problems)."""
    rel = newest_windows_release(fetch_releases())
    if rel and rel["version"] > current_version():
        return rel
    return None


def show_update(parent, rel: dict) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle("Update available")
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(f"<b>{APP} {rel['label']}</b> is available (build {rel['build']}).<br>"
                f"You have {__version__} (build {build_number() or 'local'}).")
    if rel.get("notes"):
        box.setInformativeText(rel["notes"][:600])
    get = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
    skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is get:
        QDesktopServices.openUrl(QUrl(rel["url"]))
    elif box.clickedButton() is skip:
        QSettings("ImageResizeShare", "ImageResizeShare").setValue("update_skip", rel["label"] + f".{rel['build']}")


def auto_check_enabled() -> bool:
    return QSettings("ImageResizeShare", "ImageResizeShare").value("update_check", True, type=bool)


def set_auto_check(on: bool) -> None:
    QSettings("ImageResizeShare", "ImageResizeShare").setValue("update_check", bool(on))


def auto_check_due() -> bool:
    """Once a day at most, and not when turned off."""
    if not auto_check_enabled():
        return False
    s = QSettings("ImageResizeShare", "ImageResizeShare")
    last = s.value("update_last_check", 0.0, type=float)
    return datetime.now().timestamp() - last > 20 * 3600


def mark_checked() -> None:
    QSettings("ImageResizeShare", "ImageResizeShare").setValue("update_last_check", datetime.now().timestamp())


def skipped(rel: dict) -> bool:
    return QSettings("ImageResizeShare", "ImageResizeShare").value("update_skip", "") == \
        rel["label"] + f".{rel['build']}"


# ======================================================================
# About
# ======================================================================
def show_about(parent=None) -> None:
    from app.core import paths
    QMessageBox.about(
        parent, f"About {APP}",
        f"<b>{APP}</b><br>Version {__version__} (build {build_number() or 'local'})<br><br>"
        f"Data folder: {paths.base_dir()}<br>Error log: {errors.log_path()}<br><br>"
        f"Updates: <a href='https://github.com/{app_pkg.UPDATE_REPO}/releases'>"
        f"github.com/{app_pkg.UPDATE_REPO}/releases</a>")
