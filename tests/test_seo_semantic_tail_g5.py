"""Guard harmless terminal SRT fragments without losing meaningful claims."""
from rg_youtube_control.seo_evidence_records import build_evidence_records


def test_short_terminal_noisy_fragment_does_not_block_other_grounded_dialogue():
    first={"index":1,"start":0,"end":6,"pieces":1,"text":"На заправці говорили про вартість бензину і питання цін у регіоні",
           "verified":True,"topics":[
               {"topic":"Бензин","summary_uk":"У розмові учасники обговорюють вартість пального.",
                "evidence":"На заправці говорили про вартість бензину і питання цін у регіоні"}]}
    last={"index":2,"start":914,"end":927,"pieces":2,"text":"ну коротко. так.",
          "verified":False,"topics":[]}
    rows=[{"start":0,"duration":6,"text":first["text"]},
          {"start":914,"duration":5,"text":"ну коротко."},
          {"start":926,"duration":1,"text":"так."}]
    report={"blocks_analyzed":2,"blocks_with_evidence":1,"blocks":[first,last]}
    result=build_evidence_records(video_id="MEitKm687xo",timeline_report=report,transcript_rows=rows)
    assert result["complete_evidence_coverage"]
    assert result["nonsemantic_caption_blocks"]==[2]
    assert result["needs_review"] and not result["publication_allowed"]


def test_meaningful_unverified_block_remains_blocked():
    content="Співрозмовник розповідав про суттєві економічні проблеми і зарплати регіону"
    report={"blocks_analyzed":1,"blocks_with_evidence":0,
            "blocks":[{"index":1,"start":0,"end":10,"pieces":1,"text":content,
                       "verified":False,"topics":[]}]}
    rows=[{"start":0,"duration":10,"text":content}]
    result=build_evidence_records(video_id="MEitKm687xo",timeline_report=report,transcript_rows=rows)
    assert result["blocks_without_grounded_quotes"]==[1]
    assert not result["complete_evidence_coverage"]