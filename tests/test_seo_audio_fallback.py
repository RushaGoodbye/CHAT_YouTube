"""Offline only: audio fallback provenance and cache safety."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

from rg_youtube_control.seo_audio_fallback import (
    cached_unreviewed_audio_srt, acquire_full_srt_from_public_youtube_audio
)


def make_cache(tmp_path):
    vid="MEitKm687xo"
    srt=tmp_path/(vid+".whisper.srt")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nТест\n",encoding="utf-8")
    payload={
        "video_id":vid,"duration_s":60,"all_audio_windows_processed":True,
        "windows_expected":1,"windows_processed":1,
        "srt_sha256":hashlib.sha256(srt.read_bytes()).hexdigest(),
        "publication_allowed":False,
    }
    (tmp_path/(vid+".whisper.asr.json")).write_text(json.dumps(payload),encoding="utf-8")
    source={
        "video_id":vid,"yt_dlp_video_id":vid,
        "method":"youtube_audio_download",
    }
    (tmp_path/(vid+".whisper.audio_source.json")).write_text(json.dumps(source),encoding="utf-8")
    return vid,srt


def test_valid_unreviewed_full_audio_cache_is_reusable(tmp_path):
    vid,srt=make_cache(tmp_path)
    assert cached_unreviewed_audio_srt(
        video_id=vid,cache_dir=tmp_path,duration_s=60
    )==srt
    assert cached_unreviewed_audio_srt(
        video_id=vid,cache_dir=tmp_path,duration_s=120
    ) is None


def test_tampered_audio_transcript_is_not_reused(tmp_path):
    vid,srt=make_cache(tmp_path)
    srt.write_text("tampered",encoding="utf-8")
    assert cached_unreviewed_audio_srt(
        video_id=vid,cache_dir=tmp_path,duration_s=60
    ) is None


def test_mismatched_youtube_audio_id_is_blocked_before_asr(tmp_path,monkeypatch):
    from rg_youtube_control import seo_audio_fallback as mod
    touched=[]
    class Downloader:
        def __init__(self,options):self.options=options
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def extract_info(self,url,download):
            assert download is True
            return {"id":"NAXPGr6hY_g","duration":60}
    monkeypatch.setitem(sys.modules,"yt_dlp",SimpleNamespace(YoutubeDL=Downloader))
    monkeypatch.setattr(mod,"recognize_complete_audio",lambda **kwargs:touched.append(kwargs))
    import pytest
    with pytest.raises(ValueError,match="DOWNLOADED_VIDEO_ID_MISMATCH"):
        acquire_full_srt_from_public_youtube_audio(
            video_id="MEitKm687xo",cache_dir=tmp_path,duration_s=60
        )
    assert touched==[]


def test_no_missing_caption_download_on_valid_cache(tmp_path,monkeypatch):
    from rg_youtube_control import seo_audio_fallback as mod
    vid,srt=make_cache(tmp_path)
    monkeypatch.setitem(sys.modules,"yt_dlp",None)
    result=acquire_full_srt_from_public_youtube_audio(
        video_id=vid,cache_dir=tmp_path,duration_s=60
    )
    assert result["srt_path"]==str(srt)
    assert result["publication_allowed"] is False