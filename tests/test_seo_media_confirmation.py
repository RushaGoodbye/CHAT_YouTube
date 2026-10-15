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


def test_manual_media_selection_for_renamed_originals():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", start)
    block = source[start:end]
    assert "QFileDialog.getOpenFileName(" in block
    assert "if reply == QMessageBox.StandardButton.Yes:" in block
    assert "save_verified_media(" in block


def test_picker_cancellation_and_missing_model_have_distinct_explanations():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def local_seo_selected(")
    end = source.index("    def _save_local_seo_result(", start)
    block = source[start:end]
    assert "SEO: вихідний файл не обрано" in block
    assert "SEO: відсутня модель Whisper" in block
    assert block.index('if media_path is None:') < block.index('if not (model_dir / "model.bin").is_file():')
    assert r"D:\YOUTUBE\RUSHA GOODBYE\Раша GOODBYE\ГОТОВО\YouTube" in block
