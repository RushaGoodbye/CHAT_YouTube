"""One NAS directory enumeration per archive statistics pass, not per video."""
import json


def test_archive_stats_one_directory_enumeration_for_large_channel(
    tmp_path, monkeypatch,
):
    from rg_youtube_control import archive_campaign
    from rg_youtube_control.db import connect

    conn = connect(tmp_path / "data.sqlite")
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    videos = [
        (f"QA{i:06d}", "main", f"Archive {i}", "public", "2026-01-01")
        for i in range(600)
    ]
    conn.executemany(
        "INSERT INTO videos(video_id,profile,title,privacy_status,last_synced_at)"
        " VALUES(?,?,?,?,?)",
        videos,
    )
    conn.commit()

    for i in (0, 1, 10, 99, 599):
        (transcripts / f"QA{i:06d}.srt").write_text("00:00:01 --> 00:00:02\nQA")
    (transcripts / "other_video.srt").write_text("none")
    (transcripts / "QA000002.txt").write_text("not a transcript")

    original_scan = archive_campaign.os.scandir
    calls = []
    def counted_scan(path):
        calls.append(str(path))
        return original_scan(path)
    monkeypatch.setattr(archive_campaign.os, "scandir", counted_scan)
    try:
        stats = archive_campaign.archive_profile_stats(
            conn, "main", transcript_dir=transcripts
        )
        assert stats["archive_total"] == 600
        assert stats["transcripts"] == 5
        assert calls == [str(transcripts)]
    finally:
        conn.close()


def test_archive_stats_missing_transcripts_share_fails_safe(tmp_path):
    from rg_youtube_control.archive_campaign import archive_profile_stats
    from rg_youtube_control.db import connect

    conn = connect(tmp_path / "data.sqlite")
    try:
        conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,last_synced_at)"
            " VALUES(?,?,?,?,?)",
            ("XQA001", "live", "Published", "public", "2026-01-01"),
        )
        conn.commit()
        result = archive_profile_stats(
            conn, "live", transcript_dir=tmp_path / "offline-share"
        )
        assert result["archive_total"] == 1
        assert result["transcripts"] == 0
    finally:
        conn.close()
