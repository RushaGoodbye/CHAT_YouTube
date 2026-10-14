"""The local SEO button must preflight a reliable source without online requests."""
from pathlib import Path


def test_selected_seo_checks_nas_transcript_before_work():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", begin)
    section = source[begin:end]
    assert 'transcript_file = transcript_dir / f"{video_id}.srt"' in section
    assert "if not transcript_file.is_file():" in section
    assert section.index("if not transcript_file.is_file():") < section.index("def task():")
    assert "Генерацію не запускали" in section
    assert "return" in section


def test_existing_draft_is_not_modified_by_preflight():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", begin)
    section = source[begin:end]
    assert "save_optimization_draft(" not in section
    assert "youtube.update" not in section
