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


def test_main_seo_pipeline_wires_independent_reviewer_without_publish():
    from pathlib import Path
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    start = source.index("def generate_seo_package_local(")
    section = source[start:]
    assert "review_seo_candidate(" in section
    assert '"seo_independent_review": reviewer_report' in section
    assert '"publication_allowed": False' in section
    assert '"editorial_approved": False' in section


def test_reviewer_warns_on_russianisms_in_suggested_metadata(monkeypatch):
    monkeypatch.setattr(reviewer, "lm_studio_chat", lambda *_a, **_k: (
        '{"verdict":"revise","issues":[],"recommended_changes":'
        '{"title":"Страх доносов у Росії"}}'
    ))
    result = reviewer.review_seo_candidate(draft={}, source_notes=[])
    assert result["reviewer_language_warning"] is True
    assert result["editorial_approved"] is False
    assert result["publication_allowed"] is False


def test_revision_roundtrip_preserves_manual_publication_gate(monkeypatch):
    answers = iter([
        '{"title":"Росіяни бояться доносів: чому мовчать про війну?",'
        '"title_variants":["Страх доносів у РФ","Чому росіяни мовчать?","Свобода слова в Росії"],'
        '"description":"' + "Текст про страх доносів та реальні слова співрозмовника. " * 10 + '",'
        '"tags":["Росія","доноси","свобода слова","чат рулетка","розмова","страх","росіяни","війна"]}',
        '{"verdict":"review","issues":[],"recommended_changes":[]}',
    ])
    monkeypatch.setattr(reviewer, "lm_studio_chat", lambda *_a, **_k: next(answers))
    result = reviewer.revise_seo_candidate(
        draft={"title": "Generic"},
        source_notes=[{"time": "01:23", "quote": "Боюсь доносов"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": [{"field": "title"}]},
    )
    assert result["revised"] is True
    assert result["review"]["review_status"] == "NEEDS_HUMAN_REVIEW"
    assert result["publication_allowed"] is False
    assert result["editorial_approved"] is False


def test_revision_failure_preserves_original(monkeypatch):
    monkeypatch.setattr(reviewer, "lm_studio_chat", lambda *_a, **_k: "")
    draft = {"title": "Original"}
    result = reviewer.revise_seo_candidate(
        draft=draft, source_notes=[{"quote": "source"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": []},
    )
    assert result["candidate"] == draft
    assert result["revised"] is False
    assert result["publication_allowed"] is False
