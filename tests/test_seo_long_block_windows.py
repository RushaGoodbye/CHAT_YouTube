import pytest
from rg_youtube_control.seo_source_integrity import CaptionCue
from rg_youtube_control.seo_long_block_windows import audit_long_block_windows

def cues():
    return [
        CaptionCue(float(s),float(s)+1, "Participant describes the original political dispute clearly.")
        for s in (0,5,10,60,65,70,120,125,130)
    ]

def test_three_windows_covered_but_no_editorial_approval():
    report=audit_long_block_windows(cues=cues(),start_s=0,end_s=180,window_s=60)
    assert len(report["windows"])==3
    assert report["complete_transcript_window_coverage"]
    assert report["total_cues"]==9
    assert all(w["verbatim_quote"] in w["context_excerpt"] for w in report["windows"])
    assert all(not w["semantic_verified"] for w in report["windows"])
    assert report["publication_allowed"] is False

def test_one_sparse_window_blocks_complete_coverage():
    sparse=cues()[:-3]
    report=audit_long_block_windows(cues=sparse,start_s=0,end_s=180,window_s=60)
    assert not report["complete_transcript_window_coverage"]
    assert report["windows"][2]["quote_sha256"] is None
    assert report["windows"][2]["verbatim_quote"]==""

def test_unsorted_or_bad_range_rejected():
    with pytest.raises(ValueError,match="UNSORTED"):
        audit_long_block_windows(cues=list(reversed(cues())),start_s=0,end_s=180)
    with pytest.raises(ValueError,match="INVALID_WINDOW"):
        audit_long_block_windows(cues=cues(),start_s=90,end_s=40)
    with pytest.raises(ValueError,match="INVALID_WINDOW"):
        audit_long_block_windows(cues=cues(),start_s=0,end_s=180,window_s=5)

def test_quote_is_exact_original_source():
    inputs=[CaptionCue(0,1,"a"),CaptionCue(2,3,"Whole source sentence."),CaptionCue(4,5,"more")]
    report=audit_long_block_windows(cues=inputs,start_s=0,end_s=30,window_s=30)
    assert report["windows"][0]["verbatim_quote"]=="Whole source sentence."
    assert report["windows"][0]["source_covered"]
