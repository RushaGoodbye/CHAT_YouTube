"""Prevent slow QObject accumulation after repeated batch and probe workers."""
import inspect


def test_qthread_disposes_finished_wrappers():
    from rg_youtube_control.ui import LocalToolWorker

    source = inspect.getsource(LocalToolWorker.__init__)
    assert "self.finished.connect(self.deleteLater)" in source
