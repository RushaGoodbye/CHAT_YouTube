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
  privacy_status TEXT,
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
"""

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
        """INSERT INTO videos(video_id,channel_id,title,published_at,privacy_status,views,audit_json,last_synced_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
          channel_id=excluded.channel_id,title=excluded.title,
          published_at=excluded.published_at,privacy_status=excluded.privacy_status,
          views=excluded.views,audit_json=excluded.audit_json,last_synced_at=excluded.last_synced_at""",
        (
            item["video_id"], item.get("channel_id"), item.get("title", ""),
            item.get("published_at"), item.get("privacy_status"),
            int(item.get("views") or 0), json.dumps(item.get("audit", {}), ensure_ascii=False),
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