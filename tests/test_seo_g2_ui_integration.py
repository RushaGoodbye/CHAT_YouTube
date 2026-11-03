"""G2 end-to-end evidence gate through actual staged UI method, offline."""
from types import SimpleNamespace
import pytest
from rg_youtube_control import ui
from rg_youtube_control.db import connect

VIDEO = "AbCdEfGh123"

def rows():
    return [{"text": f"Today people discuss buses and rail fares in this city {i}",
             "start": i*4.0, "duration": 3.5} for i in range(30)]

@pytest.fixture
def setup(tmp_path,monkeypatch):
    conn = connect(tmp_path/"rg_youtube_control.db")
    conn.close()
    worker=SimpleNamespace(data_dir=tmp_path,current_profile="main")
    monkeypatch.setattr(ui,"cached_public_metadata",lambda *a:{})
    monkeypatch.setattr(ui,"fetch_public_metadata",lambda video_id: {
        "title":"Urban transport discussion","description":"","tags":[],
        "duration":122,"_caption_tracks":{"automatic":{"ru":[]}}})
    monkeypatch.setattr(ui,"fetch_transcript",lambda video_id:rows())
    monkeypatch.setattr(ui,"fetch_transcript_from_public_metadata",lambda *a,**k:rows())
    generated=[]
    monkeypatch.setattr(ui,"generate_seo_package_local",lambda **kw: generated.append(kw) or {"title":"draft","tags":[]})
    monkeypatch.setattr(ui,"evidence_outline_text",lambda report:"evidence draft")
    return worker,generated,monkeypatch

def report(quote):
    return {"blocks_total":1,"blocks_analyzed":1,"blocks_with_evidence":1,
            "blocks":[{"index":1,"start":0.0,"end":119.5,"verified":True,
                "topics":[{"topic":"Міський транспорт",
                 "summary_uk":"Мешканці обговорюють міський транспорт.",
                 "evidence":quote}]}]}

def test_verified_quote_reaches_draft_only(setup):
    worker,generated,monkeypatch=setup
    monkeypatch.setattr(ui,"analyze_all_timeline_blocks",
                        lambda *a,**k:report(rows()[2]["text"]))
    result=ui.MainWindow._generate_local_seo_result(worker,VIDEO,fast_mode=False)
    assert len(generated)==1
    evidence=result["evidence_report"]["source_evidence"]
    assert len(evidence["evidence_records"])==1
    assert evidence["evidence_records"][0]["start_s"]==8.0
    assert evidence["publication_allowed"] is False

def test_hallucinated_quote_blocks_generation(setup):
    worker,generated,monkeypatch=setup
    monkeypatch.setattr(ui,"analyze_all_timeline_blocks",
                        lambda *a,**k:report("The prime minister has resigned unexpectedly."))
    with pytest.raises(RuntimeError,match="G2"):
        ui.MainWindow._generate_local_seo_result(worker,VIDEO,fast_mode=False)
    assert generated==[]

def test_wrong_block_quote_blocks_generation(setup):
    worker,generated,monkeypatch=setup
    wrong=report(rows()[20]["text"])
    wrong["blocks"][0]["end"]=8.0
    monkeypatch.setattr(ui,"analyze_all_timeline_blocks",lambda *a,**k:wrong)
    with pytest.raises(RuntimeError,match="G2"):
        ui.MainWindow._generate_local_seo_result(worker,VIDEO,fast_mode=False)
    assert generated==[]
