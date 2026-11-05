from pathlib import Path
from rg_youtube_control.seo_full_asr import CaptionSegment,window_bounds,recognize_complete_audio,segments_to_srt,compare_asr_transcripts
import json
import pytest

def test_long_stream_windows_cover_entire_duration_without_truncation():
    chunks=window_bounds(11529.3,300)
    assert chunks[0]==(0.0,300.0)
    assert chunks[-1][1]==11529.3
    assert sum(e-s for s,e in chunks)==pytest.approx(11529.3)
    assert len(chunks)==39

def test_segment_srt_correct_timestamps():
    parts=[CaptionSegment(0.1,2.3,"Привіт, Україно!"),CaptionSegment(3601,3603,"Ще один блок")]
    s=segments_to_srt(parts).decode()
    assert "00:00:00,100 --> 00:00:02,300" in s
    assert "01:00:01,000 --> 01:00:03,000" in s

def test_unsorted_segments_rejected():
    with pytest.raises(ValueError,match="UNSORTED_SEGMENTS"):
        segments_to_srt([CaptionSegment(30,40,"Другий"),CaptionSegment(0,10,"Перший")])

def test_complete_audio_covers_every_window_and_does_not_approve(tmp_path):
    source=tmp_path/"audio.mp3"
    source.write_bytes(b"test-stub")
    count=[]
    def extract(src,dst,start,end):
        count.append((start,end))
        dst.write_bytes(b"dummy")
    def recognize(_):
        return [CaptionSegment(.5,2.0,"Тестовий рядок")]
    result=recognize_complete_audio(source=source,output_dir=tmp_path/"out",
       video_id="MEitKm687xo",duration_s=305,chunk_s=300,extract=extract,recognizer=recognize)
    assert result["windows_expected"]==2
    assert result["windows_processed"]==2
    assert result["all_audio_windows_processed"] is True
    assert result["publication_allowed"] is False
    assert count==[(0.0,300.0),(300.0,305.0)]
    assert "00:05:00,500" in Path(result["srt_path"]).read_text("utf-8")
    assert result["srt_sha256"]
    assert not (tmp_path/"out"/"MEitKm687xo.srt").exists()

def test_failed_second_window_never_exposes_partial_srt(tmp_path):
    src=tmp_path/"a.mp3";src.write_bytes(b"dummy")
    calls=0
    def extractor(s,d,a,b):d.write_bytes(b"")
    def recognizer(_):
        nonlocal calls
        calls+=1
        if calls==2: raise RuntimeError("GPU_OOM")
        return [CaptionSegment(.2,1,"Привіт")]
    with pytest.raises(RuntimeError,match="GPU_OOM"):
        recognize_complete_audio(source=src,output_dir=tmp_path/"out",
          video_id="MEitKm687xo",duration_s=350,chunk_s=300,extract=extractor,recognizer=recognizer)
    assert not (tmp_path/"out"/"MEitKm687xo.whisper.srt").exists()
    report=json.loads((tmp_path/"out"/"MEitKm687xo.whisper.asr.json").read_text("utf-8"))
    assert report["status"]=="BLOCKED_INCOMPLETE_TRANSCRIPT"
    assert report["windows_processed"]==1

def test_comparison_does_not_declare_accuracy_winner():
    a=[CaptionSegment(0,2,"Привіт світе")]
    b=[CaptionSegment(0,2,"Привіт Україно")]
    result=compare_asr_transcripts(a,b)
    assert 0<result["lexical_jaccard"]<1
    assert result["winner"] is None
    assert result["human_reference_required_for_accuracy"] is True


def test_near_zero_tail_is_merged_for_parakeet_chunks():
    chunks=window_bounds(60.008,20)
    assert len(chunks)==3
    assert chunks[-1][1]==pytest.approx(60.008)
    assert all(end-start>=10 for start,end in chunks)


def test_parakeet_subword_timestamps_keep_word_boundaries():
    from rg_youtube_control.seo_full_asr import parakeet_tokens_to_segments
    tokens=[" Сьогодні"," ми"," переві","ряємо"," повний"," текст"," розмови","."]
    times=[0.0,1,2,5.8,6.1,7.3,8.9,9]
    result=parakeet_tokens_to_segments(tokens,times,max_segment_s=6)
    assert len(result)>=2
    assert result[0].text.endswith("перевіряємо")
    assert result[1].text.startswith("повний")


def test_parakeet_bad_timestamp_sequence_fails():
    from rg_youtube_control.seo_full_asr import parakeet_tokens_to_segments
    with pytest.raises(ValueError,match="PARAKEET_NONMONOTONIC_TOKEN_TIMES"):
        parakeet_tokens_to_segments(["одне"," два"],[2.0,1.0])