import json
import pytest
from rg_youtube_control.seo_g2_cohort import build_g2_cohort

def test_sparse_real_inventory_never_creates_fake_holdout(tmp_path):
    out=build_g2_cohort(caption_dir=tmp_path)
    assert out["available_real_verified_sources"] == 0
    assert out["missing_for_acceptance"] == 40
    assert out["acceptance_cohort_ready"] is False
    assert out["holdout_locked"] == []
    assert out["review"] == []
    assert out["publication_allowed"] is False

def test_missing_manifest_excluded_not_guessed(tmp_path):
    (tmp_path/"MEitKm687xo.srt").write_text(
        "1\n00:00:00,000 --> 00:00:03,000\nTest spoken words\n",encoding="utf-8"
    )
    out=build_g2_cohort(caption_dir=tmp_path)
    assert not out["acceptance_cohort_ready"]
    assert out["available_real_verified_sources"] == 0
    assert len(out["excluded"]) == 1

def test_cannot_relax_acceptance_threshold(tmp_path):
    with pytest.raises(ValueError,match="G2_ACCEPTANCE_COHORT_TOO_SMALL"):
        build_g2_cohort(caption_dir=tmp_path,review_size=3,holdout_size=1)

def test_bad_caption_manifest_never_passes(tmp_path):
    (tmp_path/"MEitKm687xo.srt").write_text(
        "1\n00:00:00,000 --> 00:00:03,000\nTest spoken words\n",encoding="utf-8"
    )
    (tmp_path/"MEitKm687xo.source.json").write_text(
        json.dumps({"video_id":"MEitKm687xo","duration_s":3,
                    "sha256":"made-up"}),encoding="utf-8"
    )
    out=build_g2_cohort(caption_dir=tmp_path)
    assert out["available_real_verified_sources"] == 0
    assert out["editorial_approved"] is False


def test_new_holdout_never_contains_previously_used_sources(tmp_path, monkeypatch):
    monkeypatch.setattr("rg_youtube_control.seo_g2_cohort.audit_caption_file",
                        lambda **kw: {"status":"PASS"})
    ids=[]
    for i in range(40):
        video_id=f"V{i:010d}"
        ids.append(video_id)
        (tmp_path/(video_id+".srt")).write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nTest caption\n",encoding="utf-8")
        (tmp_path/(video_id+".source.json")).write_text(
            json.dumps({"duration_s":60+i*120}),encoding="utf-8")
    known=set(ids[:3])
    out=build_g2_cohort(caption_dir=tmp_path,previously_used_ids=known)
    assert out["acceptance_cohort_ready"]
    assert len(out["review"])==30
    assert len(out["holdout_locked"])==10
    holdout_ids={x["video_id"] for x in out["holdout_locked"]}
    review_ids={x["video_id"] for x in out["review"]}
    assert not holdout_ids.intersection(known)
    assert known.issubset(review_ids)
    assert not holdout_ids.intersection(review_ids)
    assert len(holdout_ids | review_ids)==40
    assert out["publication_allowed"] is False
