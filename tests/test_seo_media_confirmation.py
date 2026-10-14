"""Selecting guessed source media must always require human confirmation."""
from pathlib import Path


def test_guessed_media_requires_explicit_selection():
    text = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = text.index("    def local_seo_selected(")
    end = text.index("    def _save_local_seo_result(", begin)
    block = text[begin:end]
    assert "discover_title_candidates(" in block
    assert "QInputDialog.getItem(" in block
    assert "if accepted and selection in labels:" in block
    assert "media_path = candidates[labels.index(selection)][1]" in block
    assert block.index("if accepted and selection in labels:") < block.index(
        "generate_srt_offline("
    )
    assert "youtube.update" not in block
