from rg_youtube_control import seo_editorial_reviewer as reviewer


def test_reviewer_catches_unverified_claim_and_blocks_publication(monkeypatch):
    monkeypatch.setattr(reviewer, "lm_studio_chat", lambda *_a, **_k: (
        '{"verdict":"revise","issues":[{"field":"title","reason":"unsupported claim","evidence":"00:02"}],'
        '"recommended_changes":["Use exact quotation"]}'
    ))
    result = reviewer.review_seo_candidate(
        draft={"title": "Unsupported event"}, source_notes=[{"time": "00:02", "quote": "hello"}],
    )
    assert result["review_status"] == "NEEDS_REVISION"
    assert result["issues"][0]["field"] == "title"
    assert result["publication_allowed"] is False
    assert result["editorial_approved"] is False


def test_reviewer_empty_response_fails_closed(monkeypatch):
    monkeypatch.setattr(reviewer, "lm_studio_chat", lambda *_a, **_k: "")
    result = reviewer.review_seo_candidate(draft={}, source_notes=[])
    assert result["review_status"] == "REVIEWER_FAILED"
    assert result["publication_allowed"] is False


def test_reviewer_never_grants_publish_even_if_model_claims_approval(monkeypatch):
    monkeypatch.setattr(reviewer, "lm_studio_chat", lambda *_a, **_k: (
        '{"verdict":"approved","issues":[],"recommended_changes":[],"publication_allowed":true}'
    ))
    result = reviewer.review_seo_candidate(draft={}, source_notes=[])
    assert result["review_status"] == "NEEDS_HUMAN_REVIEW"
    assert result["publication_allowed"] is False
