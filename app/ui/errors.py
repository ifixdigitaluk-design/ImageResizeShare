"""
Safety net: any unexpected error is written to a log file and shown as a short,
friendly message instead of the app closing or silently doing nothing.
"""
from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

_shown: set = set()
COUNT = [0]          # errors seen this session (the self-test checks it)
_log_path: Optional[Path] = None


def log_path() -> Path:
    global _log_path
    if _log_path is None:
        try:
            from app.core.paths import sub_dir
            _log_path = sub_dir("Logs") / "errors.log"
        except Exception:
            _log_path = Path.home() / "ImageResizeShare-errors.log"
    return _log_path


def write_log(text: str) -> None:
    try:
        p = log_path()
        if p.exists() and p.stat().st_size > 2_000_000:          # keep the log small
            p.replace(p.with_suffix(".old.log"))
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}\n")
    except Exception:
        pass


def _friendly(exc: BaseException) -> str:
    if isinstance(exc, MemoryError):
        return "The computer ran out of memory for this size. Try a smaller print size or the 50 % scale preset."
    if isinstance(exc, PermissionError):
        return ("Windows did not allow the file to be written. Close it if it is open in another program "
                "(e.g. a PDF viewer), or choose another folder.")
    if isinstance(exc, FileNotFoundError):
        return "A file could not be found. It may have been moved or deleted."
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "The disk is full. Free some space and try again."
    return "Something went wrong with that action."


def _show(exc: BaseException, key: str) -> None:
    if key in _shown:
        return
    _shown.add(key)
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox

        def show():
            parent = QApplication.activeWindow()
            QMessageBox.warning(parent, "Image Resize & Share",
                                f"{_friendly(exc)}\n\n{type(exc).__name__}: {str(exc)[:300]}\n\n"
                                f"Your jobs are saved. Details were written to:\n{log_path()}")
        QTimer.singleShot(0, show)
    except Exception:
        pass


def install(show_dialogs: bool = True) -> None:
    def hook(t, v, tb):
        txt = "".join(traceback.format_exception(t, v, tb))
        COUNT[0] += 1
        if sys.__stderr__:
            sys.__stderr__.write(txt)
        write_log(txt)
        if show_dialogs and not issubclass(t, KeyboardInterrupt):
            last = traceback.extract_tb(tb)[-1] if tb else None
            _show(v, f"{t.__name__}:{last.filename if last else ''}:{last.lineno if last else ''}")

    sys.excepthook = hook

    def thook(args):
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = thook


def save_or_warn(parent, write, path) -> bool:
    """Run write() (which saves a file); on a Windows/disk problem show a clear message
    instead of an error. Returns True when the file was saved."""
    try:
        write()
        return True
    except OSError as exc:
        write_log(f"save failed: {path}\n{traceback.format_exc()}")
        from PySide6.QtWidgets import QMessageBox
        name = Path(str(path)).name
        if isinstance(exc, PermissionError):
            why = (f"\"{name}\" could not be saved because it is open in another program (for example a "
                   "PDF viewer or Photoshop) or the folder is read-only.\n\nClose it, or choose another "
                   "name or folder, and try again.")
        elif getattr(exc, "errno", None) == 28:
            why = f"\"{name}\" could not be saved because the disk is full. Free some space and try again."
        else:
            why = f"\"{name}\" could not be saved.\n\n{exc}"
        QMessageBox.warning(parent, "Could not save", why)
        return False


def write_bytes_safely(path, data: bytes) -> None:
    """Write a file so that a full disk or a crash can never leave a half-written file (or wipe
    the old one): write next to it, then swap it in."""
    import os
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
