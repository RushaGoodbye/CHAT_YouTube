import pytest
from rg_youtube_control.seo_evidence_records import build_evidence_records

VID = "AbCdEfGh123"


def row(text, start=0.0):
    return {"text": text, "start": start, "duration": 4.0}


def report(quote, verified=True, **extra):
    block = {
        "index": 1, "start": 0.0, "end": 4.0, "verified": verified,
        "topics": [{"topic": "Тема розмови", "summary_uk": "Учасник висловлює позицію.",
                    "evidence": quote}],
    }
    block.update(extra)
    return {"blocks_analyzed": 1, "blocks_with_evidence": int(verified),
            "blocks": [block]}


def test_grounded_speech_preserves_quote_and_timestamp():
    q = "Our town is discussing bus and rail transport."
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q, start=64.0, end=68.0), transcript_rows=[row(q, 64.0)])
    assert len(result["evidence_records"]) == 1
    item = result["evidence_records"][0]
    assert item["start_s"] == 64.0
    assert item["verbatim_quote"] == q
    assert item["statement_kind"] == "attributed_speech"
    assert not item["factual_truth_verified"]
    assert result["publication_allowed"] is False


def test_question_not_treated_as_external_fact():
    q = "Why are tickets so expensive now?"
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q), transcript_rows=[row(q)])
    assert result["evidence_records"][0]["statement_kind"] == "question"
    assert result["needs_review"]


def test_hallucinated_quote_is_rejected():
    result = build_evidence_records(video_id=VID,
        timeline_report=report("The minister resigned last night"),
        transcript_rows=[row("We discussed the climate and weather today")])
    assert result["evidence_records"] == []
    assert result["rejected_evidence"][0]["reason"] == "QUOTE_NOT_IN_SOURCE"


def test_two_different_topics_remain_distinct():
    quote1 = "This city needs a new tram service."
    quote2 = "Our schools need additional teachers."
    first = report(quote1)["blocks"][0]
    second = report(quote2, index=2, start=15.0, end=19.0)["blocks"][0]
    merged = {"blocks_analyzed": 2, "blocks_with_evidence": 2,
              "blocks": [first, second]}
    result = build_evidence_records(video_id=VID,timeline_report=merged,
        transcript_rows=[row(quote1),row(quote2,15.0)])
    assert len(result["evidence_records"]) == 2
    assert [r["start_s"] for r in result["evidence_records"]] == [0.0,15.0]


def test_unverified_blocks_not_presented_as_evidence():
    q = "We might go to the beach today."
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q, verified=False),transcript_rows=[row(q)])
    assert result["evidence_records"] == []


def test_no_fake_provenance_from_invalid_video_id():
    with pytest.raises(ValueError,match="INVALID_VIDEO_ID"):
        build_evidence_records(video_id="not-a-youtube-id",
            timeline_report=report("A test quotation with sufficient length."),
            transcript_rows=[row("A test quotation with sufficient length.")])


def test_quote_spanning_rows_requires_block_text():
    q = "The city council voted today about new"
    r1 = row("The city council voted today",0)
    r2 = row("about new bus lanes",4)
    result = build_evidence_records(video_id=VID,
        timeline_report=report(q, end=8.0),transcript_rows=[r1,r2])
    assert len(result["evidence_records"]) == 1
    assert result["evidence_records"][0]["timestamp_precision"] == "timeline_block"
    assert result["evidence_records"][0]["factual_truth_verified"] is False


def test_quote_repeated_elsewhere_must_not_shift_evidence_to_wrong_block():
    quote = "We should discuss the city transport budget."
    early = row(quote, 10.0)
    other = row("This is a completely unrelated exchange.", 80.0)
    result = build_evidence_records(video_id=VID,
        timeline_report=report(quote, start=75.0, end=85.0),
        transcript_rows=[early, other])
    assert result["evidence_records"] == []
    assert result["rejected_evidence"][0]["reason"] == "QUOTE_NOT_IN_SOURCE"


@pytest.mark.parametrize("quote,kind", [
    ("Я думаю, що транспорт треба покращити.", "opinion"),
    ("Мне кажется, это слишком дорого.", "opinion"),
    ("Кажуть, нібито його звільнили.", "allegation"),
    ("По слухам будет новое решение.", "allegation"),
    ("Вчера здесь открыли новый мост.", "attributed_speech"),
    ("Почему никто не проверяет эту информацию?", "question"),
])
def test_speech_attribution_never_becomes_verified_fact(quote, kind):
    result = build_evidence_records(video_id=VID,
        timeline_report=report(quote), transcript_rows=[row(quote)])
    assert result["evidence_records"][0]["statement_kind"] == kind
    assert result["evidence_records"][0]["factual_truth_verified"] is False


def test_partial_block_grounding_is_not_reported_as_complete():
    supported = "A city resident discusses public bus transport."
    unsupported = "A completely invented claim about an unknown event."
    blocks = [report(supported)["blocks"][0],
              report(unsupported, index=2, start=20.0, end=24.0)["blocks"][0]]
    batch = {"blocks_analyzed": 2, "blocks_with_evidence": 2, "blocks": blocks}
    result = build_evidence_records(video_id=VID, timeline_report=batch,
                                    transcript_rows=[row(supported, 0.0),
                                                     row("Some other topic is discussed.", 20.0)])
    assert result["blocks_without_grounded_quotes"] == [2]
    assert result["complete_evidence_coverage"] is False
    assert len(result["evidence_records"]) == 1


def test_generator_outline_cannot_include_rejected_model_assertion():
    from rg_youtube_control.seo_evidence_records import grounded_evidence_outline
    quote = "Residents discussed several alternatives for regional train services."
    false_claim = "THE SECRET MINISTER RESIGNED TODAY"
    batch = report(quote, start=5.0, end=9.0)
    batch["blocks"][0]["topics"].append({
        "topic": false_claim, "summary_uk": false_claim,
        "evidence": "This quotation does not occur in the actual captions."})
    result = build_evidence_records(video_id=VID,
        timeline_report=batch, transcript_rows=[row(quote, 5.0)])
    outline = grounded_evidence_outline(result)
    assert quote in outline
    assert false_claim not in outline
    assert len(result["rejected_evidence"]) == 1


def test_generator_outline_refuses_partial_evidence():
    from rg_youtube_control.seo_evidence_records import grounded_evidence_outline
    with pytest.raises(ValueError, match="INCOMPLETE_GROUNDED_EVIDENCE"):
        grounded_evidence_outline({
            "evidence_records": [{"start_s":0, "topic":"test",
                "verbatim_quote":"source", "statement_kind":"attributed_speech"}],
            "blocks_without_grounded_quotes": [2]})



def test_additional_srt_cues_are_integrated_but_remain_review_only():
    from rg_youtube_control.seo_evidence_records import grounded_evidence_outline
    first = "Residents discussed the local railway timetable for the next month."
    second = "The other speaker asked about the cost of traveling to work every day."
    third = "They also talked about public buses operating in their district."
    source = [row(first, 0), row(second, 4), row(third, 8)]
    result = build_evidence_records(
        video_id=VID, timeline_report=report(first, end=13.0),
        transcript_rows=source,
    )
    candidates = result["source_cue_candidates"]
    assert len(candidates) == 3
    assert all(x["source_precision"] == "single_original_cue" for x in candidates)
    assert all(x["factual_truth_verified"] is False for x in candidates)
    assert result["source_cue_candidates_review_only"] is True
    assert result["publication_allowed"] is False
    enriched = grounded_evidence_outline(result)
    assert second in enriched and third in enriched
    assert enriched.count(first) == 1
    assert second not in grounded_evidence_outline(result, include_source_cues=False)


def test_expanded_evidence_does_not_rescue_hallucinated_model_quote():
    from rg_youtube_control.seo_evidence_records import grounded_evidence_outline
    invented = "A fictional official resigned yesterday without any source evidence."
    authentic = "We talked about the morning bus schedule and public transportation costs."
    result = build_evidence_records(
        video_id=VID, timeline_report=report(invented, end=10),
        transcript_rows=[row(authentic, 0)],
    )
    assert result["evidence_records"] == []
    assert result["source_cue_candidates"]
    assert not result["complete_evidence_coverage"]
    with pytest.raises(ValueError, match="INCOMPLETE_GROUNDED_EVIDENCE"):
        grounded_evidence_outline(result)


def test_unverified_timeline_window_never_enters_expanded_context():
    from rg_youtube_control.seo_evidence_records import grounded_evidence_outline
    first = "People discussed the timetable for the city's public buses."
    unsupported = "A witness discussed prices at the regional wholesale market."
    blocks = [report(first)["blocks"][0],
              report(unsupported, index=2, verified=False, start=50, end=60)["blocks"][0]]
    batch = {"blocks_analyzed": 2, "blocks_with_evidence": 1, "blocks": blocks}
    result = build_evidence_records(
        video_id=VID, timeline_report=batch,
        transcript_rows=[row(first, 0), row(unsupported, 50)],
    )
    assert all(x["block_index"] == 1 for x in result["source_cue_candidates"])
    assert unsupported not in grounded_evidence_outline(result)
    assert not result["source_cue_candidates"][0]["factual_truth_verified"]


def test_source_candidates_safely_ignored_without_integrity_marker():
    from rg_youtube_control.seo_evidence_records import grounded_evidence_outline
    source = {
        "evidence_records": [{"start_s": 0, "topic": "Автобуси",
          "statement_kind": "attributed_speech", "verbatim_quote": "Real quote."}],
        "blocks_without_grounded_quotes": [],
        "source_cue_candidates": [{
            "source_quote": "FAKE INJECTED SOURCE", "start_s": 2,
            "source_precision": "single_original_cue", "factual_truth_verified": False,
        }],
    }
    assert "FAKE INJECTED SOURCE" not in grounded_evidence_outline(source)
