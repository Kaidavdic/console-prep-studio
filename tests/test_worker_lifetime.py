"""Regression test for the bug that made the whole app vanish.

The old code did `self.worker = None` inside a slot connected to a signal the
worker emits from its own run(). That freed the C++ QThread while it was still
running; Qt called std::terminate and the process died with no traceback — which
is what the user saw as "the app closed fully after it finished downloading".

`retire_on_finish` must only release the worker after QThread.finished, which Qt
emits once run() has actually returned.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop, Signal, QTimer  # noqa: E402

from cps.ui.worker import _Worker, retire_on_finish  # noqa: E402


class _Emitter(_Worker):
    """Mimics a pipeline worker: reports 'done' from inside run(), then keeps going."""
    reported = Signal(str)

    def work(self) -> None:
        self.reported.emit("finished")
        # the old bug window: the main thread handles the signal while run()
        # is still on the stack
        self.msleep(120)


class _Boom(_Worker):
    crashed = Signal(str)

    def work(self) -> None:
        raise RuntimeError("kaboom")

    def on_crash(self, exc: Exception) -> None:
        self.crashed.emit(str(exc))


@pytest.fixture
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _spin_until(app, predicate, timeout_ms=5000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: predicate() and loop.quit())
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()


def test_worker_is_not_released_inside_its_own_signal(qapp):
    holder = {"worker": _Emitter()}
    seen = []
    finished_when_released = []

    w = holder["worker"]

    def release():
        # the state that matters: run() must already be over at this point,
        # otherwise Qt tears down a live QThread and the process aborts
        finished_when_released.append(w.isFinished())
        holder["worker"] = None

    # the slot handling the worker's own signal must NOT drop the reference
    w.reported.connect(lambda msg: seen.append(msg))
    retire_on_finish(w, release)
    w.start()

    _spin_until(qapp, lambda: holder["worker"] is None)

    assert seen == ["finished"], "the worker's signal never reached the main thread"
    assert holder["worker"] is None, "worker should be released once finished fired"
    assert finished_when_released == [True], \
        "released while run() was still on the stack - this is the crash"


def test_exception_in_work_does_not_escape_the_thread(qapp):
    w = _Boom()
    got = []
    w.crashed.connect(got.append)
    w.start()
    _spin_until(qapp, lambda: w.isFinished())
    assert got == ["kaboom"], "on_crash should turn the exception into a signal"
    assert w.isFinished()
