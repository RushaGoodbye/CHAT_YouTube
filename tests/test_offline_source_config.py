from pathlib import Path
from rg_youtube_control.offline_source_config import (
    local_seo_media_roots, local_whisper_model_dir,
)


def test_media_path_can_be_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("RG_SEO_MEDIA_DIR", str(tmp_path / "my_media"))
    roots = local_seo_media_roots(tmp_path / "data", tmp_path / "transcripts")
    assert roots[0] == tmp_path / "my_media"
    assert roots[1:] == [tmp_path / "data" / "seo_media", tmp_path / "transcripts" / "media"]


def test_model_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RG_SEO_WHISPER_MODEL_DIR", str(tmp_path / "whisper"))
    assert local_whisper_model_dir(tmp_path) == tmp_path / "whisper"


def test_empty_config_preserves_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("RG_SEO_MEDIA_DIR", raising=False)
    monkeypatch.delenv("RG_SEO_WHISPER_MODEL_DIR", raising=False)
    assert local_seo_media_roots(tmp_path, tmp_path)[0] == tmp_path / "seo_media"
    assert local_whisper_model_dir(tmp_path) == tmp_path / "models" / "faster-whisper-large-v3"
