from rg_youtube_control.metadata_audit import audit

def test_short_under_60_seconds_does_not_require_chapters():
    result = audit("", [], "Тестовий ролик", "PT59S")
    assert "no_chapters" not in result.issues

def test_labeled_short_under_3_minutes_does_not_require_chapters():
    result = audit("", [], "Тест #shorts", "PT2M30S")
    assert "no_chapters" not in result.issues

def test_regular_video_still_requires_chapters():
    result = audit("", [], "Звичайне відео", "PT2M30S")
    assert "no_chapters" in result.issues
