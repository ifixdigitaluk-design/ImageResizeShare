"""Clipboard, folder and WhatsApp helpers (Windows-friendly)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QMimeData, QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import QApplication

APP_DIR_NAME = "Image Resize & Share"


def share_folder() -> Path:
    pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    base = Path(pics) if pics else Path.home()
    d = base / APP_DIR_NAME / "WhatsApp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def temp_folder() -> Path:
    d = Path(tempfile.gettempdir()) / "ImageResizeShare"
    d.mkdir(parents=True, exist_ok=True)
    return d


def copy_to_clipboard(qimg: QImage, file_path: Path | None = None) -> None:
    """Put the image on the clipboard as pixels AND as a file.

    * Browsers (WhatsApp Web) and most apps paste the pixels.
    * WhatsApp Desktop / File Explorer paste the actual file, so the format
      and quality you chose are kept.
    """
    md = QMimeData()
    md.setImageData(qimg)
    if file_path is not None:
        md.setUrls([QUrl.fromLocalFile(str(file_path))])
    QApplication.clipboard().setMimeData(md)


def show_in_folder(path: Path) -> None:
    path = Path(path)
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def clean_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def open_whatsapp(target: str = "web", phone: str = "") -> str:
    """Open WhatsApp. Returns which one was opened ("desktop" / "web")."""
    phone = clean_phone(phone)
    if target == "desktop":
        url = f"whatsapp://send?phone={phone}" if phone else "whatsapp://"
        ok = False
        if sys.platform.startswith("win"):
            try:
                os.startfile(url)  # type: ignore[attr-defined]
                ok = True
            except OSError:
                ok = False
        else:
            ok = QDesktopServices.openUrl(QUrl(url))
        if ok:
            return "desktop"
    url = f"https://web.whatsapp.com/send?phone={phone}" if phone else "https://web.whatsapp.com/"
    QDesktopServices.openUrl(QUrl(url))
    return "web"
