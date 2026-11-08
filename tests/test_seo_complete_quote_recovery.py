import json
from rg_youtube_control.seo_evidence_recovery import recover_missing_source_blocks

def test_completed_caption_preferred_to_long_fragment():
    transcript=[
      {"start":0,"text":"The person is speaking a very long complex phrase with many diverse words that ends in","duration":2},
      {"start":1,"text":"The people are discussing the situation at the neighborhood market today.","duration":2}
    ]
    report={"blocks_analyzed":1,"blocks_with_evidence":1,"blocks":[
      {"index":1,"start":0,"end":3,"verified":True,"topics":[
        {"topic":"Модель","summary_uk":"Вигадане твердження",
         "evidence":"This fake quote never appeared in original captions."}]}]}
    messages=[]
    def mock(messages_arg, **kw):
        messages.append(messages_arg[-1]["content"])
        return json.dumps({"topic":"Ситуація на ринку",
          "summary_uk":"Співрозмовник обговорює події на місцевому ринку."})
    out=recover_missing_source_blocks(video_id="AbCdEfGh123",
       timeline_report=report,transcript_rows=transcript,
       chat=mock,model="local")
    assert out["complete_evidence_coverage"]
    assert report["blocks"][0]["topics"][-1]["evidence"]==transcript[1]["text"]
    assert out["publication_allowed"] is False
