import json

from rg_youtube_control.verified_media_registry import get_verified_media


def test_verified_mapping_uses_exact_id_and_existing_media(tmp_path):
    video = tmp_path / "renamed-video.mp4"
    video.write_bytes(b"media")
    registry = tmp_path / "verified_media.json"
    registry.write_text(json.dumps({
        "AbCdEfGhI12": {"path": str(video), "verified": True},
        "AbCdEfGhI13": {"path": str(video), "verified": False},
    }), encoding="utf-8")
    assert get_verified_media(registry, "AbCdEfGhI12") == video
    assert get_verified_media(registry, "AbCdEfGhI13") is None
    assert get_verified_media(registry, "AbCdEfGhI14") is None


def test_registry_rejects_missing_or_unverified(tmp_path):
    registry = tmp_path / "verified_media.json"
    registry.write_text(json.dumps({
        "AbCdEfGhI12": {"path": str(tmp_path / "missing.mp4"), "verified": True}
    }), encoding="utf-8")
    assert get_verified_media(registry, "AbCdEfGhI12") is None
    assert get_verified_media(tmp_path / "not-there.json", "AbCdEfGhI12") is None
