"""Background processing so the window never freezes."""
from __future__ import annotations

import traceback

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
            traceback.print_exc()
            self.signals.failed.emit(self.gen, str(exc))
