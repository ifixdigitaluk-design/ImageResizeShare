"""Where the app's bundled assets and the user's data live (no Qt here)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

_base_dir: Path | None = None


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel


def documents_dir() -> Path:
    if sys.platform.startswith("win"):
        try:  # real Documents folder (handles OneDrive redirection)
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # CSIDL_PERSONAL
            if buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def set_base_dir(path: str | Path | None) -> None:
    global _base_dir
    _base_dir = Path(path) if path else None


_default_dir: Path | None = None


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".write_test"
        t.write_text("ok", encoding="utf-8")
        t.unlink()
        return True
    except OSError:
        return False


def default_dir() -> Path:
    """Documents/Image Resize & Share - or, when Windows blocks Documents (Controlled folder
    access, a broken OneDrive link), a folder in the user's local app data instead."""
    global _default_dir
    if _default_dir is None:
        d = documents_dir() / "Image Resize & Share"
        if not _writable(d):
            alt = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")) / "Image Resize & Share"
            if _writable(alt):
                d = alt
        _default_dir = d
    return _default_dir


def base_dir() -> Path:
    """Root for jobs, library and settings: ~/Documents/Image Resize & Share (or $IRS_HOME)."""
    if _base_dir is not None:
        d = _base_dir
    elif os.environ.get("IRS_HOME"):
        d = Path(os.environ["IRS_HOME"])
    else:
        d = default_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def sub_dir(name: str) -> Path:
    d = base_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d
