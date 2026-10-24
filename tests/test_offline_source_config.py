from pathlib import Path
from rg_youtube_control.offline_source_config import (
    local_seo_media_roots, local_whisper_model_dir,
)


def test_media_path_can_be_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("RG_SEO_MEDIA_DIR", str(tmp_path / "my_media"))
    roots = local_seo_media_roots(tmp_path / "data", tmp_path / "transcripts")
    assert roots[0] == tmp_path / "my_media"
    assert roots[1:3] == [tmp_path / "data" / "seo_media", tmp_path / "transcripts" / "media"]
    if __import__("os").name == "nt":
        assert any("RUSHA GOODBYE" in str(root) for root in roots[3:])


def test_model_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RG_SEO_WHISPER_MODEL_DIR", str(tmp_path / "whisper"))
    assert local_whisper_model_dir(tmp_path) == tmp_path / "whisper"


def test_empty_config_preserves_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("RG_SEO_MEDIA_DIR", raising=False)
    monkeypatch.delenv("RG_SEO_WHISPER_MODEL_DIR", raising=False)
    assert local_seo_media_roots(tmp_path, tmp_path)[0] == tmp_path / "seo_media"
    assert local_whisper_model_dir(tmp_path) == tmp_path / "models" / "faster-whisper-large-v3"


def test_confirmed_windows_media_directory_is_configured():
    import os
    source = Path("src/rg_youtube_control/offline_source_config.py").read_text(encoding="utf-8")
    assert "r\"D:\\YOUTUBE\\RUSHA GOODBYE\\Раша GOODBYE\\ГОТОВО\\YouTube\"" in source
    if os.name == "nt":
        from rg_youtube_control.offline_source_config import local_seo_media_roots
        roots = local_seo_media_roots(Path("C:/temp/app"), Path("C:/temp/srt"))
        assert Path("D:\\YOUTUBE\\RUSHA GOODBYE\\Раша GOODBYE\\ГОТОВО\\YouTube") in roots
