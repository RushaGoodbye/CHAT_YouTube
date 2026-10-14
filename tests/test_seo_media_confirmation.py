"""Historical candidates must be confirmed before media transcription."""
from pathlib import Path


def test_local_seo_confirms_and_saves_historical_match():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", begin)
    block = source[begin:end]
    assert "historical_media_candidates(" in block
    assert "QInputDialog.getItem(" in block
    assert "QMessageBox.question(" in block
    assert "if reply == QMessageBox.StandardButton.Yes:" in block
    assert "save_verified_media(" in block
    assert block.index("save_verified_media(") < block.index("generate_srt_offline(")
    assert "youtube.update" not in block
