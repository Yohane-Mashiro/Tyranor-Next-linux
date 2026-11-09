from __future__ import annotations

import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot


class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(object)
    finished = pyqtSignal()


class Worker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            if "on_progress" in kwargs:
                kwargs["on_progress"] = self.signals.progress.emit
            value = self.function(*self.args, **kwargs)
            self.signals.result.emit(value)
        except Exception as exc:
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.signals.error.emit(detail or str(exc))
        finally:
            self.signals.finished.emit()


def start_worker(owner: object, worker: Worker) -> None:
    """Start a worker while keeping its Python wrapper and signals alive."""
    workers = getattr(owner, "_active_workers", None)
    if workers is None:
        workers = []
        setattr(owner, "_active_workers", workers)
    workers.append(worker)

    def finished() -> None:
        if worker in workers:
            workers.remove(worker)

    worker.signals.finished.connect(finished)
    QThreadPool.globalInstance().start(worker)
