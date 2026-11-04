import copy
import hashlib
import pytest

from rg_youtube_control.seo_long_block_handoff import replace_provisional_with_windows


def setup():
    old={"video_id":"AbCdEfGh123","record_id":5,
         "status":"PROVISIONAL_SOURCE_REVIEW",
         "source_quote":"A provisional prior quote.",
         "source_context":"A provisional prior quote.",
         "initial_topic":"Попередня тема","editorial_approved":False,
         "publication_allowed":False}
    handoff={"records":[old,{"video_id":"MnOpQrSt456","record_id":1,
        "status":"REVISED_NEEDS_HUMAN_REVIEW",
        "source_quote":"A second original quote goes here.",
        "source_context":"A second original quote goes here.",
        "editorial_approved":False,"publication_allowed":False}]}
    windows=[]
    proposals=[]
    for i in range(2):
        quote=f"Verbatim sentence from source window {i}."
        windows.append({"source_covered":True,"start_s":i*60,
            "end_s":(i+1)*60,"verbatim_quote":quote,
            "context_excerpt":quote+" More source context.",
            "quote_sha256":hashlib.sha256(quote.encode()).hexdigest()})
        proposals.append({"window_number":i+1,"current_risk_ai":"low",
            "source_quote_sha256":windows[-1]["quote_sha256"],
            "topic":f"Розмова про зміну {i}",
            "summary_uk":"Співрозмовники обговорюють причини та можливості змін."})
    return handoff,{"windows":windows,"complete_transcript_window_coverage":True},proposals


def test_split_preserves_other_records_and_is_review_only():
    packet,audit,proposals=setup()
    original=copy.deepcopy(packet)
    out=replace_provisional_with_windows(
        handoff=packet,video_id="AbCdEfGh123",block_record_id=5,
        source_audit=audit,proposals=proposals)
    assert len(out["records"])==3
    assert {r["record_id"] for r in out["records"]
            if r["video_id"]=="AbCdEfGh123"}=={501,502}
    assert packet==original
    assert all(not r["editorial_approved"] for r in out["records"])
    assert all(not r["publication_allowed"] for r in out["records"])
    assert all(r["status"]=="PROVISIONAL_SOURCE_REVIEW" for r in out["records"][-2:])


def test_reject_forged_quote():
    packet,audit,proposals=setup()
    audit["windows"][0]["verbatim_quote"]="Fake source quotation."
    with pytest.raises(ValueError,match="WINDOW_QUOTE_MISMATCH"):
        replace_provisional_with_windows(handoff=packet,video_id="AbCdEfGh123",
            block_record_id=5,source_audit=audit,proposals=proposals)


def test_reject_nonlow_or_missing_review():
    packet,audit,proposals=setup()
    proposals[1]["current_risk_ai"]="medium"
    with pytest.raises(ValueError,match="WINDOW_NOT_INDEPENDENTLY_SCREENED"):
        replace_provisional_with_windows(handoff=packet,video_id="AbCdEfGh123",
            block_record_id=5,source_audit=audit,proposals=proposals)


def test_reject_source_gap_and_wrong_provisional():
    packet,audit,proposals=setup()
    audit["complete_transcript_window_coverage"]=False
    with pytest.raises(ValueError,match="INCOMPLETE_WINDOW_SOURCE"):
        replace_provisional_with_windows(handoff=packet,video_id="AbCdEfGh123",
            block_record_id=5,source_audit=audit,proposals=proposals)
    audit["complete_transcript_window_coverage"]=True
    with pytest.raises(ValueError,match="NO_UNIQUE_PROVISIONAL_BLOCK"):
        replace_provisional_with_windows(handoff=packet,video_id="MnOpQrSt456",
            block_record_id=1,source_audit=audit,proposals=proposals)


def test_unreviewed_window_cannot_be_auto_approved():
    from rg_youtube_control.seo_editorial_decisions import create_review_manifest,validate_editorial_decisions
    packet,audit,proposals=setup()
    out=replace_provisional_with_windows(
        handoff=packet,video_id="AbCdEfGh123",block_record_id=5,
        source_audit=audit,proposals=proposals)
    manifest=create_review_manifest(out)
    item=next(x for x in manifest["cards"] if x["record_id"]==501)
    req={"schema":"RG_G2_HUMAN_DECISIONS_V1",
         "manifest_sha256":manifest["manifest_sha256"],
         "reviewer":"editor","decisions":[{**item,"decision":"approve"}]}
    with pytest.raises(ValueError,match="FLAGGED_CARD_REQUIRES_REVISION_OR_REJECTION"):
        validate_editorial_decisions(packet=out,submission=req)
