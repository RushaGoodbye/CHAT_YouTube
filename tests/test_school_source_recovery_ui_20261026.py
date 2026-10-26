from pathlib import Path

def test_wrong_nas_school_video_recovers_exact_id_before_evidence_analysis():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    before_analysis = source.split("evidence_report = analyze_all_timeline_blocks(")[0]
    assert "title_school_crime" in before_analysis
    assert "from_youtube = fetch_transcript(video_id)" in before_analysis
    assert "transcript_source = \"youtube-transcript-api-recovered\"" in before_analysis
    assert "SOURCE_VIDEO_MISMATCH" in before_analysis
    assert "full_source_text = youtube_text" in before_analysis
