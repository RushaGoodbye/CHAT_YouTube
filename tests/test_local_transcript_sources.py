"""Offline caption reuse regression cases."""
from rg_youtube_control.local_transcript_sources import find_local_transcript


def test_vtt_cache_by_exact_video_id(tmp_path):
    (tmp_path / "AbCdEfGhI12.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nРозмова про економіку\n",
        encoding="utf-8",
    )
    rows, source = find_local_transcript(tmp_path, "AbCdEfGhI12")
    assert source == "nas-vtt"
    assert rows and "економіку" in rows[0]["text"]


def test_does_not_guess_by_stream_or_title(tmp_path):
    (tmp_path / "886_2.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nШойгу\n",
        encoding="utf-8",
    )
    assert find_local_transcript(tmp_path, "AbCdEfGhI12") == ([], "")


def test_corrupt_file_falls_back_to_vtt(tmp_path):
    (tmp_path / "AbCdEfGhI12.srt").write_text("garbage", encoding="utf-8")
    (tmp_path / "AbCdEfGhI12.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nСубтитри\n",
        encoding="utf-8",
    )
    rows, source = find_local_transcript(tmp_path, "AbCdEfGhI12")
    assert rows and source == "nas-vtt"


def test_untrusted_path_id_rejected(tmp_path):
    assert find_local_transcript(tmp_path, "../escape!") == ([], "")


def test_language_suffixed_caption_reused(tmp_path):
    (tmp_path / "AbCdEfGhI12.uk.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nСубтитри українською\n",
        encoding="utf-8",
    )
    rows, source = find_local_transcript(tmp_path, "AbCdEfGhI12")
    assert source == "nas-vtt"
    assert rows and "українською" in rows[0]["text"]


def test_similar_video_id_does_not_match(tmp_path):
    (tmp_path / "AbCdEfGhI13.uk.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nСторонні субтитри\n",
        encoding="utf-8",
    )
    assert find_local_transcript(tmp_path, "AbCdEfGhI12") == ([], "")
