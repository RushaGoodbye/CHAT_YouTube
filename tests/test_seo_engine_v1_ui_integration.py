from pathlib import Path


def test_manual_single_video_uses_new_engine_and_preserves_batch():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    assert "if stronger_editorial is None and not fast_mode and full_source_text.strip():" in source
    assert "from .seo_engine_ollama import generate_with_ollama" in source
    assert "video_id=video_id," in source
    assert "transcript=full_source_text," in source
    assert '"provider": "ollama:rg-seo-engine-v1"' in source
    assert '"needs_review": True' in source
    assert "elif stronger_editorial is None:" in source
