"""
Running Hermes without freezing the window.

Every call into :mod:`hermes_control.cli` blocks — some for minutes, because
an install or a model turn genuinely takes minutes. Qt repaints on one thread,
so each of those calls goes to a worker and comes back as a signal.

Two shapes cover everything the app needs: :class:`Job` for a call that
returns once, and :class:`StreamJob` for a chat turn that speaks as it goes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


class Job(QThread):
    """Run one callable off the UI thread and deliver its result."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[], Any], parent: QObject | None = None):
        super().__init__(parent)
        self._work = work

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            result = self._work()
        except Exception as exc:  # a worker must never take the app down
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(result)


class StreamJob(QThread):
    """Consume an iterator of events, emitting each one as it arrives."""

    event = Signal(object)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, source: Callable[[], Iterator[Any]],
                 parent: QObject | None = None):
        super().__init__(parent)
        self._source = source
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            for item in self._source():
                if self._stop:
                    break
                self.event.emit(item)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_ok.emit()


class JobRunner(QObject):
    """Keeps worker threads alive long enough to finish.

    A ``QThread`` that goes out of scope while running is a crash, and the
    obvious ``Job(...).start()`` does exactly that. Everything goes through
    here so there is one owner.
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._live: list[QThread] = []

    def run(self, work: Callable[[], Any],
            on_done: Callable[[Any], None] | None = None,
            on_failed: Callable[[str], None] | None = None) -> Job:
        job = Job(work, self)
        if on_done is not None:
            job.done.connect(on_done)
        if on_failed is not None:
            job.failed.connect(on_failed)
        self._keep(job)
        job.start()
        return job

    def stream(self, source: Callable[[], Iterator[Any]],
               on_event: Callable[[Any], None],
               on_finished: Callable[[], None] | None = None,
               on_failed: Callable[[str], None] | None = None) -> StreamJob:
        job = StreamJob(source, self)
        job.event.connect(on_event)
        if on_finished is not None:
            job.finished_ok.connect(on_finished)
        if on_failed is not None:
            job.failed.connect(on_failed)
        self._keep(job)
        job.start()
        return job

    def _keep(self, job: QThread) -> None:
        self._live.append(job)
        job.finished.connect(lambda: self._live.remove(job)
                             if job in self._live else None)

    def wait_all(self, msec: int = 3000) -> None:
        for job in list(self._live):
            job.wait(msec)
