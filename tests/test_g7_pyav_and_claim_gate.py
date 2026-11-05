"""G7 candidate build must use PyAV version tested with faster-whisper."""
from pathlib import Path

def test_frozen_asr_uses_pinned_compatible_av():
    base=Path(__file__).resolve().parents[1]
    requirements=(base/"requirements.txt").read_text(encoding="utf-8")
    pyproject=(base/"pyproject.toml").read_text(encoding="utf-8")
    assert "av==18.1.0" in requirements.splitlines()
    assert '"av==18.1.0"' in pyproject
    assert "faster-whisper" in requirements

def test_source_claim_gate_stays_review_only():
    from rg_youtube_control.seo_grounded_claims import generate_attributed_claim_description
    text,reason,report=generate_attributed_claim_description(
        report={"blocks":[]},current_title="Тема",model="unused",chat=lambda *a,**k:None
    )
    assert text=="" and reason=="INSUFFICIENT_DISTINCT_SOURCE_QUOTES"
    assert report["publication_allowed"] is False

def test_no_unproven_new_subject_on_short_quote():
    from rg_youtube_control.seo_grounded_claims import _validate_claim
    original={"quote":"Война в России стала предметом спора, люди обсуждают происходящее"}
    candidate={"text":"Співрозмовник говорить про Путіна, соціальні виплати та бюджет міста."}
    assert _validate_claim(candidate,original) in {
        "UNSUPPORTED_NAMED_ENTITY","CLAIM_ADDS_UNCORROBORATED_SUBJECTS","NOT_SOURCE_SPECIFIC"
    }