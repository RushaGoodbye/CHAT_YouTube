"""Cross-video synthetic tests: no video-ID-specific rules or YouTube writes."""
from rg_youtube_control.seo_source_integrity import audit_source, parse_srt

ID_A = "AbCdEfGh123"
ID_B = "QwErTyUi456"


def srt(topic="municipal budget", count=12):
    return "\n\n".join(
        f"{i+1}\n00:{(i*5)//60:02d}:{(i*5)%60:02d},000 --> "
        f"00:{(i*5+4)//60:02d}:{(i*5+4)%60:02d},000\n{topic} and response {i}"
        for i in range(count)
    )


def evaluate(**overrides):
    args = dict(requested_video_id=ID_A, transcript_video_id=ID_A,
                transcript_provenance="youtube_auto", srt_content=srt(),
                video_duration_s=62, verified_topic_anchors=["municipal budget"])
    args.update(overrides)
    return audit_source(**args)


def test_valid_source_stays_review_only():
    result = evaluate()
    assert result["status"] == "NEEDS_REVIEW"
    assert not result["issues"]
    assert result["cue_count"] == 12
    assert not result["publication_allowed"]


def test_wrong_video_id_blocks():
    assert "SOURCE_ID_MISMATCH_OR_UNVERIFIED" in evaluate(
        transcript_video_id=ID_B)["issues"]


def test_unknown_provenance_blocks_even_if_filename_matches():
    assert evaluate(transcript_provenance="renamed_file")["status"] == "BLOCKED_SOURCE"


def test_topic_mismatch_blocks_for_unrelated_sources():
    result = evaluate(verified_topic_anchors=["forest preservation"])
    assert "TOPIC_ANCHORS_NOT_FOUND" in result["issues"]
    assert result["status"] == "BLOCKED_SOURCE"


def test_without_independent_topic_anchor_needs_review():
    result = evaluate(verified_topic_anchors=[])
    assert result["issues"] == ["TOPIC_MATCH_UNVERIFIED"]
    assert result["status"] == "NEEDS_REVIEW"


def test_corrupt_timestamps_block():
    result = evaluate(srt_content="1\n00:00:xx,000 --> 00:00:05,000\nhello")
    assert result["status"] == "BLOCKED_SOURCE"


def test_short_or_truncated_captions_block():
    assert evaluate(srt_content=srt(count=3))["status"] == "BLOCKED_SOURCE"
    assert "INSUFFICIENT_TIMELINE_COVERAGE" in evaluate(
        video_duration_s=600)["issues"]


def test_unverified_video_id_blocks_even_with_matching_words():
    assert evaluate(transcript_video_id=None)["status"] == "BLOCKED_SOURCE"


def test_other_subject_also_passes_same_generic_gate():
    result = evaluate(requested_video_id=ID_B, transcript_video_id=ID_B,
                      srt_content=srt("rail travel"), verified_topic_anchors=["rail travel"])
    assert result["issues"] == []
    assert result["status"] == "NEEDS_REVIEW"


def test_parser_preserves_order_and_text():
    cues = parse_srt(srt("school sports"))
    assert len(cues) == 12
    assert "school sports" in cues[0].text
