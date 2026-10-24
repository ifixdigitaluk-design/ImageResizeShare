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
    px = qimg.width() * qimg.height()
    if px > 36_000_000:
        # a huge print would make Windows' clipboard (and the app pasting it) very slow; chats
        # resize photos anyway. The file itself (below) keeps the full size.
        from PySide6.QtCore import Qt
        k = (36_000_000 / px) ** 0.5
        qimg = qimg.scaled(max(1, int(qimg.width() * k)), max(1, int(qimg.height() * k)),
                           Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    md.setImageData(qimg)
    if file_path is not None:
        md.setUrls([QUrl.fromLocalFile(str(file_path))])
    QApplication.clipboard().setMimeData(md)


def copy_files_to_clipboard(paths) -> None:
    """Put files (e.g. a PDF) on the clipboard so they can be pasted into a chat or folder."""
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    QApplication.clipboard().setMimeData(md)


def show_in_folder(path: Path) -> None:
    path = Path(path)
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


# country calling codes for the computer's region (used when a number is typed the local way, "07700 …")
_CC = {"UnitedKingdom": "44", "Pakistan": "92", "India": "91", "UnitedArabEmirates": "971",
       "SaudiArabia": "966", "Qatar": "974", "Kuwait": "965", "Oman": "968", "Bahrain": "973",
       "Bangladesh": "880", "Ireland": "353", "UnitedStates": "1", "Canada": "1", "Australia": "61",
       "NewZealand": "64", "SouthAfrica": "27", "Nigeria": "234", "Kenya": "254", "Germany": "49",
       "France": "33", "Spain": "34", "Italy": "39", "Netherlands": "31", "Turkey": "90", "Turkiye": "90",
       "Malaysia": "60", "Singapore": "65", "Egypt": "20", "SriLanka": "94", "Nepal": "977"}


def default_country_code() -> str:
    """The shop's country code: Business details, else guessed from the computer's region."""
    try:
        from app.core import jobs
        cc = re.sub(r"\D", "", jobs.load_business().get("country_code", ""))
        if cc:
            return cc
    except Exception:
        pass
    try:
        from PySide6.QtCore import QLocale
        loc = QLocale.system()
        terr = loc.territory() if hasattr(loc, "territory") else loc.country()
        return _CC.get(QLocale.territoryToString(terr).replace(" ", "")
                       if hasattr(QLocale, "territoryToString") else QLocale.countryToString(terr).replace(" ", ""), "")
    except Exception:
        return ""


def clean_phone(phone: str, country_code: str | None = None) -> str:
    """Digits WhatsApp understands: international format without + or 00.

    "07700 900123" (typed the local way) becomes "447700900123" for a UK shop,
    "+92 300 1234567" / "0092 300…" become "923001234567"."""
    raw = (phone or "").strip().replace("(0)", "")      # "+44 (0)7700 …" is written but not dialled
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        cc = re.sub(r"\D", "", country_code if country_code is not None else default_country_code())
        if cc:
            return cc + digits[1:]
    return digits


def open_whatsapp(target: str = "web", phone: str = "", text: str = "") -> str:
    """Open WhatsApp (optionally with a message typed in). Returns "desktop" / "web"."""
    from urllib.parse import quote
    phone = clean_phone(phone)
    q = f"&text={quote(text)}" if text else ""
    if target == "desktop":
        url = (f"whatsapp://send?phone={phone}{q}" if phone else
               (f"whatsapp://send?text={quote(text)}" if text else "whatsapp://"))
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
    url = (f"https://web.whatsapp.com/send?phone={phone}{q}" if phone else
           (f"https://web.whatsapp.com/send?text={quote(text)}" if text else "https://web.whatsapp.com/"))
    QDesktopServices.openUrl(QUrl(url))
    return "web"
