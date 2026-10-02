import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROFILE_TARGETS

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  profile TEXT,
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
CREATE TABLE IF NOT EXISTS optimization_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  history_id INTEGER,
  video_id TEXT NOT NULL,
  profile TEXT NOT NULL,
  reason TEXT NOT NULL,
  changed_fields TEXT NOT NULL DEFAULT '',
  optimized_at TEXT NOT NULL,
  UNIQUE(history_id)
);
CREATE INDEX IF NOT EXISTS idx_optimization_events_profile_date
  ON optimization_events(profile, optimized_at DESC);
CREATE TABLE IF NOT EXISTS optimization_drafts (
  video_id TEXT PRIMARY KEY,
  new_title TEXT NOT NULL,
  description TEXT NOT NULL,
  chapters TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  title_variants_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_optimization_drafts_status
  ON optimization_drafts(status, updated_at DESC);
CREATE TABLE IF NOT EXISTS video_analytics_cache (
  video_id TEXT PRIMARY KEY,
  profile TEXT NOT NULL,
  period_days INTEGER NOT NULL DEFAULT 90,
  analytics_views INTEGER NOT NULL DEFAULT 0,
  engaged_views INTEGER NOT NULL DEFAULT 0,
  watch_minutes REAL NOT NULL DEFAULT 0,
  avd_seconds REAL NOT NULL DEFAULT 0,
  subs_gained INTEGER NOT NULL DEFAULT 0,
  impressions INTEGER NOT NULL DEFAULT 0,
  ctr_percent REAL NOT NULL DEFAULT 0,
  start_date TEXT,
  end_date TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_analytics_cache_profile
  ON video_analytics_cache(profile, updated_at DESC);
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
    _ensure_column(conn, "videos", "profile", "TEXT")
    _ensure_column(
        conn,
        "optimization_drafts",
        "title_variants_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    for profile, channel_id in PROFILE_TARGETS.items():
        conn.execute(
            "UPDATE videos SET profile=? "
            "WHERE (profile IS NULL OR profile='') AND channel_id=?",
            (profile, channel_id),
        )
    conn.commit()
    return conn

def upsert_video_analytics(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    profile: str,
    period_days: int,
    analytics_views: int,
    engaged_views: int,
    watch_minutes: float,
    avd_seconds: float,
    subs_gained: int,
    impressions: int,
    ctr_percent: float,
    start_date: str,
    end_date: str,
) -> None:
    conn.execute(
        """
        INSERT INTO video_analytics_cache(
          video_id,profile,period_days,analytics_views,engaged_views,
          watch_minutes,avd_seconds,subs_gained,impressions,ctr_percent,
          start_date,end_date,updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
          profile=excluded.profile,
          period_days=excluded.period_days,
          analytics_views=excluded.analytics_views,
          engaged_views=excluded.engaged_views,
          watch_minutes=excluded.watch_minutes,
          avd_seconds=excluded.avd_seconds,
          subs_gained=excluded.subs_gained,
          impressions=excluded.impressions,
          ctr_percent=excluded.ctr_percent,
          start_date=excluded.start_date,
          end_date=excluded.end_date,
          updated_at=excluded.updated_at
        """,
        (
            video_id,
            profile,
            int(period_days),
            int(analytics_views),
            int(engaged_views),
            float(watch_minutes),
            float(avd_seconds),
            int(subs_gained),
            int(impressions),
            float(ctr_percent),
            start_date,
            end_date,
            utc_now(),
        ),
    )


def commit_video_analytics(conn: sqlite3.Connection) -> None:
    conn.commit()


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
            video_id,profile,channel_id,title,published_at,scheduled_publish_at,
            privacy_status,duration,views,audit_json,last_synced_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
          profile=excluded.profile,
          channel_id=excluded.channel_id,title=excluded.title,
          published_at=excluded.published_at,
          scheduled_publish_at=excluded.scheduled_publish_at,
          privacy_status=excluded.privacy_status,
          duration=excluded.duration,
          views=excluded.views,audit_json=excluded.audit_json,
          last_synced_at=excluded.last_synced_at""",
        (
            item["video_id"], item.get("profile"), item.get("channel_id"),
            item.get("title", ""), item.get("published_at"),
            item.get("scheduled_publish_at"), item.get("privacy_status"),
            item.get("duration"), int(item.get("views") or 0),
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



def record_optimization_event(
    conn: sqlite3.Connection,
    *,
    history_id: int | None,
    video_id: str,
    profile: str,
    reason: str,
    changed_fields: str,
    optimized_at: str | None = None,
) -> int:
    cursor = conn.execute(
        """INSERT OR IGNORE INTO optimization_events(
            history_id,video_id,profile,reason,changed_fields,optimized_at
        ) VALUES(?,?,?,?,?,?)""",
        (history_id, video_id, profile, reason, changed_fields, optimized_at or utc_now()),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)

def optimization_events(
    conn: sqlite3.Connection, profile: str, limit: int = 30
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.event_id,e.history_id,e.video_id,e.profile,e.reason,
                  e.changed_fields,e.optimized_at,v.title
           FROM optimization_events e
           LEFT JOIN videos v ON v.video_id=e.video_id
           WHERE e.profile=?
           ORDER BY e.optimized_at DESC,e.event_id DESC
           LIMIT ?""",
        (profile, int(limit)),
    ).fetchall()

def save_optimization_draft(
    conn: sqlite3.Connection,
    video_id: str,
    new_title: str,
    description: str,
    chapters: str,
    tags: list[str] | None,
    status: str = "draft",
    title_variants: list[str] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO optimization_drafts(
            video_id,new_title,description,chapters,tags_json,title_variants_json,
            status,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
          new_title=excluded.new_title,
          description=excluded.description,
          chapters=excluded.chapters,
          tags_json=excluded.tags_json,
          title_variants_json=excluded.title_variants_json,
          status=excluded.status,
          updated_at=excluded.updated_at""",
        (
            video_id,
            new_title,
            description,
            chapters,
            json.dumps(tags or [], ensure_ascii=False),
            json.dumps(title_variants or [], ensure_ascii=False),
            status,
            utc_now(),
        ),
    )
    conn.commit()

def get_optimization_draft(
    conn: sqlite3.Connection,
    video_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT video_id,new_title,description,chapters,tags_json,
                  title_variants_json,status,updated_at
           FROM optimization_drafts
           WHERE video_id=?""",
        (video_id,),
    ).fetchone()

def set_optimization_draft_status(
    conn: sqlite3.Connection,
    video_id: str,
    status: str,
) -> None:
    conn.execute(
        "UPDATE optimization_drafts SET status=?,updated_at=? WHERE video_id=?",
        (status, utc_now(), video_id),
    )
    conn.commit()

def database_integrity_cleanup(conn: sqlite3.Connection) -> dict[str, Any]:
    integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
    integrity = ", ".join(str(row[0]) for row in integrity_rows) or "unknown"

    orphan_queries = {
        "comments": (
            "SELECT COUNT(*) FROM comments c "
            "WHERE NOT EXISTS (SELECT 1 FROM videos v WHERE v.video_id=c.video_id)"
        ),
        "metadata_history": (
            "SELECT COUNT(*) FROM metadata_history h "
            "WHERE NOT EXISTS (SELECT 1 FROM videos v WHERE v.video_id=h.video_id)"
        ),
        "optimization_events": (
            "SELECT COUNT(*) FROM optimization_events e "
            "WHERE NOT EXISTS (SELECT 1 FROM videos v WHERE v.video_id=e.video_id)"
        ),
        "optimization_drafts": (
            "SELECT COUNT(*) FROM optimization_drafts d "
            "WHERE NOT EXISTS (SELECT 1 FROM videos v WHERE v.video_id=d.video_id)"
        ),
        "video_analytics_cache": (
            "SELECT COUNT(*) FROM video_analytics_cache a "
            "WHERE NOT EXISTS (SELECT 1 FROM videos v WHERE v.video_id=a.video_id)"
        ),
    }
    orphans = {
        table: int(conn.execute(query).fetchone()[0])
        for table, query in orphan_queries.items()
    }

    duplicate_snapshots = int(
        conn.execute(
            """SELECT COALESCE(SUM(n - 1), 0)
               FROM (
                 SELECT COUNT(*) AS n
                 FROM metadata_history
                 GROUP BY video_id,title,description,tags_json,reason
                 HAVING COUNT(*) > 1
               )"""
        ).fetchone()[0]
    )

    deleted = {}
    for table in (
        "comments",
        "metadata_history",
        "optimization_events",
        "optimization_drafts",
        "video_analytics_cache",
    ):
        cursor = conn.execute(
            f"DELETE FROM {table} "
            "WHERE NOT EXISTS ("
            f"SELECT 1 FROM videos v WHERE v.video_id={table}.video_id"
            ")"
        )
        deleted[table] = int(cursor.rowcount if cursor.rowcount >= 0 else 0)

    conn.commit()
    return {
        "integrity": integrity,
        "orphans": orphans,
        "deleted": deleted,
        "duplicate_snapshots": duplicate_snapshots,
    }
