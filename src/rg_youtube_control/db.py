import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  channel_id TEXT,
  title TEXT NOT NULL,
  published_at TEXT,
  scheduled_publish_at TEXT,
  privacy_status TEXT,
  duration TEXT,
  views INTEGER DEFAULT 0,
  audit_json TEXT DEFAULT '{}',
  last_synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
  comment_id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  parent_id TEXT,
  author TEXT,
  text TEXT NOT NULL,
  published_at TEXT,
  category TEXT NOT NULL DEFAULT 'review',
  status TEXT NOT NULL DEFAULT 'new',
  reply_text TEXT,
  replied_at TEXT,
  raw_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_comments_status ON comments(status);
CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);
CREATE TABLE IF NOT EXISTS metadata_history (
  history_id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metadata_history_video
  ON metadata_history(video_id, created_at DESC);
"""

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_column(conn, "videos", "scheduled_publish_at", "TEXT")
    _ensure_column(conn, "videos", "duration", "TEXT")
    return conn

def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()

def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def upsert_video(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO videos(
            video_id,channel_id,title,published_at,scheduled_publish_at,
            privacy_status,duration,views,audit_json,last_synced_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
          channel_id=excluded.channel_id,title=excluded.title,
          published_at=excluded.published_at,
          scheduled_publish_at=excluded.scheduled_publish_at,
          privacy_status=excluded.privacy_status,
          duration=excluded.duration,
          views=excluded.views,audit_json=excluded.audit_json,
          last_synced_at=excluded.last_synced_at""",
        (
            item["video_id"], item.get("channel_id"), item.get("title", ""),
            item.get("published_at"), item.get("scheduled_publish_at"),
            item.get("privacy_status"), item.get("duration"),
            int(item.get("views") or 0),
            json.dumps(item.get("audit", {}), ensure_ascii=False),
            utc_now(),
        ),
    )
    conn.commit()

def upsert_comment(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO comments(comment_id,video_id,parent_id,author,text,published_at,category,status,reply_text,raw_json)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(comment_id) DO UPDATE SET
          author=excluded.author,text=excluded.text,category=excluded.category,
          raw_json=excluded.raw_json""",
        (
            item["comment_id"], item["video_id"], item.get("parent_id"),
            item.get("author"), item.get("text", ""), item.get("published_at"),
            item.get("category", "review"), item.get("status", "new"),
            item.get("reply_text"), json.dumps(item.get("raw", {}), ensure_ascii=False),
        ),
    )
    conn.commit()

def mark_replied(conn: sqlite3.Connection, comment_id: str, reply_text: str) -> None:
    conn.execute(
        "UPDATE comments SET status='replied',reply_text=?,replied_at=? WHERE comment_id=?",
        (reply_text, utc_now(), comment_id),
    )
    conn.commit()

def set_comment_status(conn: sqlite3.Connection, comment_id: str, status: str) -> None:
    conn.execute(
        "UPDATE comments SET status=? WHERE comment_id=?",
        (status, comment_id),
    )
    conn.commit()


def save_metadata_snapshot(
    conn: sqlite3.Connection,
    video_id: str,
    title: str,
    description: str,
    tags: list[str] | None,
    reason: str,
) -> int:
    cursor = conn.execute(
        """INSERT INTO metadata_history(
            video_id,title,description,tags_json,reason,created_at
        ) VALUES(?,?,?,?,?,?)""",
        (
            video_id,
            title,
            description,
            json.dumps(tags or [], ensure_ascii=False),
            reason,
            utc_now(),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)

def latest_metadata_snapshot(
    conn: sqlite3.Connection,
    video_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT history_id,video_id,title,description,tags_json,reason,created_at
           FROM metadata_history
           WHERE video_id=?
           ORDER BY history_id DESC
           LIMIT 1""",
        (video_id,),
    ).fetchone()