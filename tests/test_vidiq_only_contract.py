"""Enforce the accepted product contract: vidIQ is the sole SEO author."""
import pytest


def test_legacy_zero_quota_button_only_opens_vidiq():
    from rg_youtube_control.ui import MainWindow
    class Dummy:
        opened=0
        def review_vidiq_proposals(self):
            self.opened += 1
    dummy=Dummy()
    MainWindow.prepare_zero_quota_batch(dummy)
    assert dummy.opened == 1


def test_legacy_generator_fails_closed():
    from rg_youtube_control.ui import MainWindow
    with pytest.raises(RuntimeError, match="vidIQ"):
        MainWindow._generate_local_seo_result(object(), "abcdefghijk")


def test_legacy_result_saver_fails_closed():
    from rg_youtube_control.ui import MainWindow
    with pytest.raises(RuntimeError, match="vidIQ"):
        MainWindow._save_local_seo_result(object(), {})
