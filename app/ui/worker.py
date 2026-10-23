"""Background processing so the window never freezes."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from app.core import imaging


class WorkerSignals(QObject):
    finished = Signal(int, object)   # generation, ProcessResult
    failed = Signal(int, str)
    progress = Signal(int, str)


class ProcessJob(QRunnable):
    def __init__(self, gen, src, state, rs, os_, ai_engine):
        super().__init__()
        self.setAutoDelete(False)
        self.gen = gen
        self.args = (src, state, rs, os_, ai_engine)
        self.signals = WorkerSignals()

    def run(self) -> None:
        src, st, rs, os_, ai = self.args
        try:
            res = imaging.process(src, st, rs, os_, ai,
                                  progress=lambda m: self.signals.progress.emit(self.gen, m))
            self.signals.finished.emit(self.gen, res)
        except MemoryError:
            self.signals.failed.emit(self.gen, "Not enough memory for this size. Try a smaller size.")
        except Exception as exc:
            self.signals.failed.emit(self.gen, friendly_error(exc))


class _FuncSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float, str)


class FuncJob(QRunnable):
    """Run fn(progress) in the thread pool; progress(fraction, text) may be called from fn."""

    def __init__(self, fn):
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = _FuncSignals()
        self.cancelled = False

    def run(self) -> None:
        try:
            res = self.fn(lambda f, t="": self.signals.progress.emit(float(f), str(t)))
            self.signals.done.emit(res)
        except MemoryError:
            self.signals.failed.emit("Not enough memory. Try a smaller size.")
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(friendly_error(exc))


def friendly_error(exc: BaseException) -> str:
    """A short message a user can act on (the details go to the log file)."""
    if type(exc).__name__ == "Cancelled" or "Cancelled" in str(exc):
        return "Cancelled"                       # the user pressed Cancel: not an error
    txt = traceback.format_exc()
    try:
        from app.ui.errors import write_log
        write_log(txt)
    except Exception:
        pass
    traceback.print_exc()
    name = getattr(exc, "filename", None)
    name = Path(str(name)).name if name else ""
    if isinstance(exc, PermissionError):
        return ((f"\"{name}\" " if name else "A file ") + "could not be written. It may be open in another "
                "program (a PDF viewer, Photoshop, the printer software) or the folder is read-only. "
                "Close it and try again.")
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return "The disk is full. Free some space and try again."
    if isinstance(exc, FileNotFoundError):
        return (f"\"{name}\" " if name else "A file ") + "could not be found. It may have been moved or deleted."
    return str(exc) or exc.__class__.__name__


_RUNNING = set()
BUSY: dict = {}        # job -> what it is doing, for work that writes files (print package, backup)


def busy_tasks() -> list:
    return list(BUSY.values())


def run_bg(fn, on_done, on_failed=None, on_progress=None, task: str = "") -> FuncJob:
    """Start fn in the background; callbacks run on the GUI thread.

    `task` names work that writes files; closing the app while it runs asks first."""
    from PySide6.QtCore import QThreadPool
    job = FuncJob(fn)
    _RUNNING.add(job)
    if task:
        BUSY[job] = task

    def _safe(fn, *a):
        try:
            fn(*a)
        except RuntimeError as exc:
            # the window that asked for the work was closed meanwhile: nothing to update
            if "already deleted" not in str(exc):
                raise

    def _fin(res):
        _RUNNING.discard(job)
        BUSY.pop(job, None)
        _safe(on_done, res)

    def _err(msg):
        _RUNNING.discard(job)
        BUSY.pop(job, None)
        if on_failed:
            _safe(on_failed, msg)

    job.signals.done.connect(_fin)
    job.signals.failed.connect(_err)
    if on_progress:
        job.signals.progress.connect(lambda f, t: _safe(on_progress, f, t))
    QThreadPool.globalInstance().start(job)
    return job
