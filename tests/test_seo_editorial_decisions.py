import copy
import pytest
from rg_youtube_control.seo_editorial_decisions import (
    create_review_manifest, validate_editorial_decisions, DECISIONS_SCHEMA,
)

def packet():
    return {"records": [
        {"video_id":"AbCdEfGh123","record_id":1,"source_quote":"Verbatim original speech with full evidence.",
         "initial_topic":"Тема джерела","initial_summary":"Відповідна розмова з реальними репліками.",
         "status":"SOURCE_QUOTED_AI_RISK"},
        {"video_id":"AbCdEfGh123","record_id":2,"source_quote":"Another original quotation from the transcript.",
         "initial_topic":"Неперевірена тема","initial_summary":"Твердження потребує перевірки редактором.",
         "status":"BLOCKED"},
    ]}

def submission(p):
    return {"schema":DECISIONS_SCHEMA,"manifest_sha256":create_review_manifest(p)["manifest_sha256"],
            "reviewer":"Editorial reviewer","decisions":[]}

def entry(p,card=0,decision="approve"):
    c=create_review_manifest(p)["cards"][card]
    return {**c,"decision":decision,"note":""}

def test_partial_review_is_not_publication():
    p=packet()
    s=submission(p)
    s["decisions"]=[entry(p)]
    result=validate_editorial_decisions(packet=p,submission=s)
    assert result["reviewed"]==1 and result["pending"]==1
    assert result["g2_accepted"] is False and result["publication_allowed"] is False

def test_source_change_blocks_import():
    p=packet()
    s=submission(p)
    s["decisions"]=[entry(p)]
    p["records"][0]["source_quote"]="A modified source quotation is rejected."
    with pytest.raises(ValueError,match="SOURCE_MANIFEST_MISMATCH"):
        validate_editorial_decisions(packet=p,submission=s)

def test_blocked_card_cannot_be_approved():
    p=packet();s=submission(p)
    s["decisions"]=[entry(p,1)]
    with pytest.raises(ValueError,match="FLAGGED_CARD_REQUIRES_REVISION_OR_REJECTION"):
        validate_editorial_decisions(packet=p,submission=s)

def test_explicit_reject_requires_reason():
    p=packet();s=submission(p)
    s["decisions"]=[entry(p,1,"reject")]
    with pytest.raises(ValueError,match="REJECTION_REQUIRES_REASON"):
        validate_editorial_decisions(packet=p,submission=s)
    s["decisions"][0]["note"]="Wrong interpretation of the source."
    result=validate_editorial_decisions(packet=p,submission=s)
    assert result["decisions"][0]["editorial_approved"] is False

def test_revision_requires_complete_fields_and_note():
    p=packet();s=submission(p)
    d=entry(p,1,"revise")
    d["corrected_topic"]="Уточнення джерела"
    d["corrected_summary"]="Зміст репліки переписано на основі оригіналу."
    d["note"]="Correcting a misattributed claim"
    s["decisions"]=[d]
    result=validate_editorial_decisions(packet=p,submission=s)
    assert result["reviewed"]==1
    assert result["decisions"][0]["corrected_topic"]=="Уточнення джерела"
    assert result["decisions"][0]["publication_allowed"] is False

def test_duplicate_and_forged_decisions_fail():
    p=packet();s=submission(p)
    one=entry(p)
    s["decisions"]=[one,copy.deepcopy(one)]
    with pytest.raises(ValueError,match="DUPLICATE_OR_UNKNOWN_DECISION"):
        validate_editorial_decisions(packet=p,submission=s)
    s["decisions"]=[{**one,"source_quote_sha256":"0"*64}]
    with pytest.raises(ValueError,match="DECISION_SOURCE_CHANGED"):
        validate_editorial_decisions(packet=p,submission=s)

def test_review_manifest_rejects_duplicate_cards():
    p=packet()
    p["records"].append(copy.deepcopy(p["records"][0]))
    with pytest.raises(ValueError,match="DUPLICATE_REVIEW_RECORD"):
        create_review_manifest(p)

def test_missing_reviewer_is_invalid():
    p=packet()
    s=submission(p);s["reviewer"]=" "
    with pytest.raises(ValueError,match="MISSING_REVIEWER"):
        validate_editorial_decisions(packet=p,submission=s)


def test_vague_topic_requires_actual_rewrite_or_rejection():
    p = packet()
    p["records"][0]["status"] = "VAGUE_TOPIC_NEEDS_REVIEW"
    s = submission(p)
    s["decisions"] = [entry(p, 0)]
    with pytest.raises(ValueError, match="FLAGGED_CARD_REQUIRES_REVISION_OR_REJECTION"):
        validate_editorial_decisions(packet=p, submission=s)


def test_context_change_invalidates_existing_editor_decisions():
    p = packet()
    p["records"][0]["source_context"] = "Initial extended source context."
    s = submission(p)
    s["decisions"] = [entry(p, 0)]
    p["records"][0]["source_context"] = "A different extended context."
    with pytest.raises(ValueError, match="SOURCE_MANIFEST_MISMATCH"):
        validate_editorial_decisions(packet=p, submission=s)


def test_provisional_source_cannot_be_approved_without_full_coverage():
    p = packet()
    p["records"][0]["status"] = "PROVISIONAL_SOURCE_REVIEW"
    s = submission(p)
    s["decisions"] = [entry(p, 0)]
    with pytest.raises(ValueError, match="FLAGGED_CARD_REQUIRES_REVISION_OR_REJECTION"):
        validate_editorial_decisions(packet=p, submission=s)
