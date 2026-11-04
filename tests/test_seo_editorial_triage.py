import pytest
from rg_youtube_control.seo_editorial_triage import triage_editorial_reviews

def packet():
    return {"video_id":"AbCdEfGh123","records":[
        {"id":1,"block_index":1,"start_s":12,"proposed_topic":"Заява",
         "proposed_summary":"Говорили про заяву","source_quote":"Дослівна цитата",
         "source_context":"Велика репліка з контекстом"},
        {"id":2,"block_index":2,"start_s":44,"proposed_topic":"Тема",
         "proposed_summary":"Обговорювали тему","source_quote":"Інша цитата",
         "source_context":"Другий діалог"}]}

def critique():
    return {"video_id":"AbCdEfGh123","findings":[
        {"id":1,"risk":"low","issues":[],"reason":""},
        {"id":2,"risk":"high","issues":["Potential geographic hallucination"],
         "reason":"Not supported by context"}]}

def test_priority_human_queue_no_auto_approval():
    out=triage_editorial_reviews(packet=packet(),critique=critique())
    assert [x["id"] for x in out["queue"]]==[2,1]
    assert out["priority_count"]==1
    assert out["queue"][0]["source_context"]=="Другий діалог"
    assert out["queue"][0]["reviewer_decision"] is None
    assert all(x["requires_human_review"] for x in out["queue"])
    assert not out["editorial_approved"]
    assert not out["publication_allowed"]

def test_missing_critic_blocked():
    c=critique()
    c["findings"].pop()
    with pytest.raises(ValueError,match="INCOMPLETE_CRITIC_COVERAGE"):
        triage_editorial_reviews(packet=packet(),critique=c)

def test_duplicate_critic_blocked():
    c=critique()
    c["findings"][1]["id"]=1
    with pytest.raises(ValueError,match="INCOMPLETE_CRITIC_COVERAGE"):
        triage_editorial_reviews(packet=packet(),critique=c)

def test_mismatched_video_id_blocked():
    c=critique()
    c["video_id"]="QwErTyUi456"
    with pytest.raises(ValueError,match="REVIEW_SOURCE_MISMATCH"):
        triage_editorial_reviews(packet=packet(),critique=c)

def test_invalid_risk_blocked():
    c=critique()
    c["findings"][1]["risk"]="approved"
    with pytest.raises(ValueError,match="INVALID_CRITIC_FINDING"):
        triage_editorial_reviews(packet=packet(),critique=c)
