"""Generate a synthetic high-volume local database for Windows cold-start QA.

Never uses real credentials, videos, comments, or network requests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rg_youtube_control.db import connect


def seed(path: Path) -> None:
    conn = connect(path)
    try:
        videos = []
        for i in range(1800):
            videos.append((
                f"RGQA{i:08d}",
                "main" if i % 2 else "live",
                f"Тестовий запис №{i} / Чат рулетка",
                "2026-09-01T10:00:00+00:00",
                "public",
                "PT40M",
                i * 120,
                json.dumps({"score": i % 100, "issues": ["description_short"]}),
                "2026-10-24T10:00:00+00:00",
            ))
        conn.executemany(
            """INSERT INTO videos(
               video_id,profile,title,published_at,privacy_status,
               duration,views,audit_json,last_synced_at
               ) VALUES (?,?,?,?,?,?,?,?,?)""",
            videos,
        )
        conn.executemany(
            """INSERT INTO comments(
               comment_id,video_id,author,text,published_at,category,status
               ) VALUES (?,?,?,?,?,?,?)""",
            [
                (
                    f"RGQAC{i:08d}", videos[i % len(videos)][0],
                    "Viewer", f"Comment number {i}",
                    "2026-09-02T12:00:00+00:00", "review", "new",
                )
                for i in range(6000)
            ],
        )
        conn.executemany(
            """INSERT INTO optimization_drafts(
               video_id,new_title,description,updated_at
               ) VALUES (?,?,?,?)""",
            [
                (videos[i][0], videos[i][2], "Перевірка оптимізації", "2026-10-24T10:00:00+00:00")
                for i in range(900)
            ],
        )
        conn.executemany(
            """INSERT INTO action_log(profile,category,action,details,created_at)
               VALUES (?,?,?,?,?)""",
            [
                ("main", "QA", "synthetic", f"row {i}", "2026-10-24T10:00:00+00:00")
                for i in range(3500)
            ],
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1800
        assert conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 6000
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: qa_seed_startup_db.py PATH_TO_SQLITE")
    seed(Path(sys.argv[1]))
    print("SEEDED_LARGE_DATABASE_PASS")
