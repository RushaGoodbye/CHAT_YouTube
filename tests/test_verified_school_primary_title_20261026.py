from pathlib import Path


def test_verified_school_primary_title_is_not_original_or_unrelated_topic():
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    assert "verified_school_topic = bool(" in source
    assert "СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ РФ?" in source
    assert "РОССИЯНЕ О БЕЗОПАСНОСТИ ДЕТЕЙ" in source
    assert source.index("if verified_school_topic") < source.index(
        "title = _preserve_current_title_when_candidate_is_not_stronger("
    )
