"""SEO must not bind local media using renamed YouTube titles."""
from pathlib import Path


def test_local_seo_does_not_guess_media_by_current_title():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", begin)
    block = source[begin:end]
    assert "find_exact_local_media(" in block
    assert "discover_title_candidates(" not in block
    assert "QInputDialog.getItem(" not in block
    assert "generate_srt_offline(" in block
    assert "youtube.update" not in block
