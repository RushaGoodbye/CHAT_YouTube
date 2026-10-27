from pathlib import Path


def test_bulk_seo_stops_repeated_failures_and_reports_errors():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    batch = source.split("    def local_seo_batch(", 1)[1].split(
        "    def _save_local_seo_batch(", 1
    )[0]
    assert "failure_streak >= 5" in batch
    assert "failure_reasons[reason_key] >= 3" in batch
    assert '"stopped_early": stopped_early' in batch
    assert "помилка {attempted}/{max_attempts}" in batch


def test_bulk_seo_failures_reported_in_final_dialog():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    save = source.split("    def _save_local_seo_batch(", 1)[1].split(
        "    def local_seo_selected(", 1
    )[0]
    assert 'if result.get("stopped_early"):' in save
    assert "reason_text +=" in save

def test_batch_uses_proven_interactive_editor_not_fast_experimental_mode():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    batch = source.split("    def local_seo_batch(", 1)[1].split(
        "    def _save_local_seo_batch(", 1
    )[0]
    assert "generate_sequentially(video_id)" in batch
    assert "daemon=True" not in batch
    assert "fast_mode=False" in batch
    assert "fast_mode=True" not in batch

def test_bulk_prefers_nas_but_allows_api_fallback():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    batch = source.split("    def local_seo_batch(", 1)[1].split(
        "    def _save_local_seo_batch(", 1
    )[0]
    assert 'f"{video_id}.srt"' in batch
    assert 'candidate_ids = sorted(' in batch
    assert 'candidate_ids = [' not in batch
    assert "fast_mode=False" in batch
