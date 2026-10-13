import pytest
from rg_youtube_control.seo_video_evidence import (
    fingerprint_transcript, build_video_evidence, store_video_evidence,
    read_video_evidence, evidence_path,
)

ROWS=[{"start": 0, "text": "паливна криза"}]
TIMELINE={"blocks_total":1,"blocks_with_evidence":1,
          "blocks":[{"start":0,"end":20,"topics":[{"topic":"паливна криза","evidence":"паливна криза"}]}]}


def test_per_video_report_round_trip_and_transcript_invalidation(tmp_path):
    p=build_video_evidence("MEitKm687xo",ROWS,TIMELINE,transcript_source="nas-srt")
    store_video_evidence(tmp_path,"MEitKm687xo",p)
    assert read_video_evidence(tmp_path,"MEitKm687xo",
        transcript_sha256=fingerprint_transcript(ROWS))["verified_topics"][0]["topic"]=="паливна криза"
    assert read_video_evidence(tmp_path,"MEitKm687xo",transcript_sha256="changed") is None
    assert read_video_evidence(tmp_path,"OTHERid123") is None


def test_video_mismatch_and_invalid_id_do_not_write(tmp_path):
    p=build_video_evidence("MEitKm687xo",ROWS,TIMELINE,transcript_source="nas-srt")
    with pytest.raises(ValueError):
        store_video_evidence(tmp_path,"otherVideo123",p)
    with pytest.raises(ValueError):
        evidence_path(tmp_path,"../../escape")
    assert not list(tmp_path.iterdir())


def test_no_unverified_evidence_map():
    with pytest.raises(ValueError):
        build_video_evidence("MEitKm687xo",ROWS,{"blocks_with_evidence":0},transcript_source="nas")
