import json
from pathlib import Path

from rg_youtube_control.seo_caption_manifest import (
    make_source_manifest, audit_caption_file,
)

VID = "AbCdEfGh123"
OTHER = "QwErTyUi456"


def srt():
    return "\n\n".join(
        f"{i+1}\n00:{i*5//60:02d}:{i*5%60:02d},000 --> "
        f"00:{(i*5+4)//60:02d}:{(i*5+4)%60:02d},000\ncity transit {i}"
        for i in range(12)
    ).encode()


def set_up(tmp_path, *, vid=VID, content=None):
    p = tmp_path / "video.srt"
    raw = srt() if content is None else content
    p.write_bytes(raw)
    manifest = make_source_manifest(
        video_id=vid, srt_bytes=raw,
        source_url=f"https://www.youtube.com/watch?v={vid}",
        acquisition_method="youtube_auto",
        acquired_at="2026-11-03T12:00:00Z",
        duration_s=62, verification="youtube_caption_response",
    )
    p.with_suffix(".source.json").write_text(json.dumps(manifest), encoding="utf-8")
    return p


def audit(p, **kwargs):
    return audit_caption_file(video_id=VID, path=p, duration_s=62,
                              verified_topic_anchors=("city transit",), **kwargs)


def test_valid_captions_still_require_review(tmp_path):
    assert audit(set_up(tmp_path))["status"] == "NEEDS_REVIEW"


def test_wrong_video_id_blocks(tmp_path):
    assert audit(set_up(tmp_path, vid=OTHER))["status"] == "BLOCKED_SOURCE"


def test_tampered_captions_block(tmp_path):
    p = set_up(tmp_path)
    p.write_bytes(srt() + b"manipulated")
    assert "CAPTION_HASH_MISMATCH" in audit(p)["issues"]


def test_missing_manifest_blocks(tmp_path):
    p = set_up(tmp_path)
    p.with_suffix(".source.json").unlink()
    assert audit(p)["status"] == "BLOCKED_SOURCE"


def test_duration_mismatch_blocks(tmp_path):
    p = set_up(tmp_path)
    assert audit_caption_file(video_id=VID, path=p, duration_s=120)["status"] == "BLOCKED_SOURCE"


def test_unverified_manual_filename_not_enough(tmp_path):
    p = set_up(tmp_path)
    record = p.with_suffix(".source.json")
    value = json.loads(record.read_text())
    value["verification"] = "renamed_to_match"
    record.write_text(json.dumps(value))
    assert audit(p)["status"] == "BLOCKED_SOURCE"


def test_corrupted_manifest_json_blocks(tmp_path):
    p = set_up(tmp_path)
    p.with_suffix(".source.json").write_text("{broken")
    assert audit(p)["status"] == "BLOCKED_SOURCE"


def test_different_subject_same_generic_gate(tmp_path):
    p = set_up(tmp_path)
    assert audit_caption_file(video_id=VID, path=p, duration_s=62,
                              verified_topic_anchors=("unrelated",))["status"] == "BLOCKED_SOURCE"


def test_url_spoofing_cannot_fake_provenance(tmp_path):
    p = set_up(tmp_path)
    record = p.with_suffix(".source.json")
    value = json.loads(record.read_text())
    value["source_url"] = f"https://evil.example.com/redirect?v={VID}"
    record.write_text(json.dumps(value))
    assert audit(p)["status"] == "BLOCKED_SOURCE"


def test_url_id_mismatch_does_not_accept_id_elsewhere(tmp_path):
    p = set_up(tmp_path)
    record = p.with_suffix(".source.json")
    value = json.loads(record.read_text())
    value["source_url"] = f"https://www.youtube.com/watch?v={OTHER}&note={VID}"
    record.write_text(json.dumps(value))
    assert audit(p)["status"] == "BLOCKED_SOURCE"


def test_invalid_acquisition_time_blocks(tmp_path):
    p = set_up(tmp_path)
    record = p.with_suffix(".source.json")
    value = json.loads(record.read_text())
    value["acquired_at"] = "2026-11-03"
    record.write_text(json.dumps(value))
    assert audit(p)["status"] == "BLOCKED_SOURCE"
