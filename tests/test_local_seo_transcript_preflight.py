"""The local SEO button must preflight a reliable source without online requests."""
from pathlib import Path


def test_selected_seo_checks_nas_transcript_before_work():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", begin)
    section = source[begin:end]
    assert "find_local_transcript(" in section
    assert "if not usable_local_transcript and media_path is None:" in section
    assert "repairing_wrong_source = True" in section
    assert "confirmed_dir = self.data_dir / \"seo_verified_transcripts\"" in section
    assert "usable_local_transcript = bool(local_rows)" in section
    assert section.index("if not usable_local_transcript and media_path is None:") < section.index("def task():")
    assert "SEO: відсутня модель Whisper" in section
    assert "SEO: вихідний файл не обрано" in section
    assert "fetch_transcript(" not in section
    assert "generate_srt_offline(" in section
    assert "find_exact_local_media(" in section
    assert "return" in section


def test_existing_draft_is_not_modified_by_preflight():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", begin)
    section = source[begin:end]
    assert "save_optimization_draft(" not in section
    assert "youtube.update" not in section


def test_batch_only_attempts_available_local_transcripts():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = source.index("    def local_seo_batch(")
    end = source.index("    def _save_local_seo_batch(", begin)
    block = source[begin:end]
    assert "available_ids = [" in block
    assert "if find_local_transcript(transcript_dir, video_id)[0]" in block
    assert "candidate_ids = available_ids" in block
    assert block.index("candidate_ids = available_ids") < block.index("def task():")
