from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rg_youtube_control.optimization import (  # noqa: E402
    safe_description_fix,
    validate_content_package,
)

HASHTAG_LINE_RE = re.compile(
    r"(?m)^\s*(?:#[\wА-Яа-яІіЇїЄєҐґ]+\s*){1,15}$",
    re.UNICODE,
)
ENGLISH_WORDS = {
    "the", "and", "that", "this", "with", "from", "for", "what", "why",
    "when", "where", "who", "how", "his", "her", "their", "they", "you",
    "your", "was", "were", "are", "is", "not", "but", "then", "into",
    "about", "after", "before", "because", "asked", "says", "said",
    "russia", "russian", "alexander",
}


def _data_dir() -> Path:
    fallback = Path.home() / "AppData" / "Local"
    base = Path(os.environ.get("LOCALAPPDATA", str(fallback)))
    return base / "RGYouTubeControl"


def _db_path() -> Path:
    return _data_dir() / "rg_youtube_control.db"


def _latin_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    latin = sum(
        1
        for ch in letters
        if ("a" <= ch.casefold() <= "z")
    )
    return latin / len(letters)


def _looks_english_duplicate(paragraph: str) -> bool:
    value = " ".join(paragraph.split())
    if len(value) < 180:
        return False
    if _latin_ratio(value) < 0.84:
        return False
    words = [item.casefold() for item in re.findall(r"[A-Za-z']+", value)]
    common = sum(1 for word in words if word in ENGLISH_WORDS)
    return common >= 8


def _drop_english_duplicate(description: str) -> tuple[str, bool, str]:
    value = (description or "").strip()
    hashtag = HASHTAG_LINE_RE.search(value)
    if hashtag:
        prefix = value[:hashtag.start()].rstrip()
        suffix = value[hashtag.start():].lstrip()
    else:
        markers = [
            value.find("УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:"),
            value.find("УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:"),
        ]
        markers = [item for item in markers if item >= 0]
        split_at = min(markers) if markers else len(value)
        prefix = value[:split_at].rstrip()
        suffix = value[split_at:].lstrip()

    paragraphs = re.split(r"\n\s*\n", prefix)
    start = None
    for index, paragraph in enumerate(paragraphs):
        if _looks_english_duplicate(paragraph):
            start = index
            if index > 0:
                previous = " ".join(paragraphs[index - 1].split()).casefold()
                if (
                    "english" in previous
                    or "англій" in previous
                    or "🇬🇧" in previous
                ):
                    start = index - 1
            break

    if start is None:
        return value, False, ""

    removed = "\n\n".join(paragraphs[start:]).strip()
    kept = "\n\n".join(paragraphs[:start]).rstrip()
    result = kept
    if suffix:
        result = (result + "\n\n" + suffix).strip()
    return result, True, removed[:500]


def _canonicalize_hashtags(description: str) -> str:
    """Keep the canonical hashtag-only line; de-hash inline mentions elsewhere."""
    value = (description or "").strip()
    match = HASHTAG_LINE_RE.search(value)
    if not match:
        return value
    before = value[:match.start()]
    canonical = match.group(0).strip()
    after = value[match.end():]
    inline_re = re.compile(r"(?<!\w)#([\wА-Яа-яІіЇїЄєҐґ]+)", re.UNICODE)
    before = inline_re.sub(r"\1", before)
    after = inline_re.sub(r"\1", after)
    return (before.rstrip() + "\n\n" + canonical + "\n" + after.lstrip()).strip()


def _repair_candidate(row: sqlite3.Row) -> dict:
    title = str(row["new_title"] or row["current_title"] or "").strip()
    before = str(row["description"] or "").strip()
    chapters = str(row["chapters"] or "").strip()
    try:
        tags = json.loads(str(row["tags_json"] or "[]"))
    except Exception:
        tags = []
    try:
        variants = json.loads(str(row["title_variants_json"] or "[]"))
    except Exception:
        variants = []

    without_english, removed_english, removed_preview = _drop_english_duplicate(before)
    fixed = safe_description_fix(without_english, title).after.strip()
    fixed = _canonicalize_hashtags(fixed)
    fixed = re.sub(r"\n{3,}", "\n\n", fixed)

    check = validate_content_package(
        title=title,
        description=fixed,
        chapters=chapters,
        tags=tags if isinstance(tags, list) else [],
        title_variants=variants if isinstance(variants, list) else [],
    )
    return {
        "video_id": row["video_id"],
        "profile": row["profile"],
        "title": title,
        "before_chars": len(before),
        "after_chars": len(fixed),
        "removed_chars": len(before) - len(fixed),
        "removed_english_duplicate": removed_english,
        "removed_preview": removed_preview,
        "hashtags_before": len(re.findall(r"(?<!\w)#[\wА-Яа-яІіЇїЄєҐґ]+", before)),
        "hashtags_after": len(re.findall(r"(?<!\w)#[\wА-Яа-яІіЇїЄєҐґ]+", fixed)),
        "ready": bool(check.ready and len(fixed) <= 5000),
        "errors": list(check.errors),
        "warnings": list(check.warnings),
        "_fixed_description": fixed,
    }


def _blocked_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          d.video_id, d.new_title, d.description, d.chapters,
          d.tags_json, d.title_variants_json, d.updated_at,
          v.profile, v.title AS current_title
        FROM optimization_drafts d
        LEFT JOIN videos v ON v.video_id=d.video_id
        WHERE d.status='blocked'
        ORDER BY d.updated_at DESC
        """
    ).fetchall()


def _backup_database(conn: sqlite3.Connection) -> Path:
    backup_dir = _data_dir() / "BACKUPS"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = backup_dir / f"zero_quota_blocked_repair_{stamp}.db"
    backup = sqlite3.connect(target)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    return target


def run(mode: str) -> dict:
    db_path = _db_path()
    if not db_path.is_file():
        raise RuntimeError(f"RG YouTube Control DB not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = _blocked_rows(conn)
        candidates = [_repair_candidate(row) for row in rows]
        public = [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in candidates
        ]

        if mode == "preview":
            return {
                "mode": "preview",
                "youtube_api_calls": 0,
                "blocked_found": len(rows),
                "ready_after_repair": sum(1 for item in candidates if item["ready"]),
                "candidates": public,
            }

        if mode != "apply":
            raise RuntimeError(f"Unknown mode: {mode}")

        if not candidates:
            return {
                "mode": "apply",
                "youtube_api_calls": 0,
                "changed": 0,
                "backup": None,
                "candidates": [],
            }

        unsafe = [item["video_id"] for item in candidates if not item["ready"]]
        if unsafe:
            raise RuntimeError(
                "Repair aborted. Candidates still failing validation: "
                + ", ".join(unsafe)
            )

        backup_path = _backup_database(conn)
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            for item in candidates:
                conn.execute(
                    """
                    UPDATE optimization_drafts
                    SET description=?, status='ready', updated_at=?
                    WHERE video_id=? AND status='blocked'
                    """,
                    (
                        item["_fixed_description"],
                        now,
                        item["video_id"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO action_log(profile,category,action,details,created_at)
                    VALUES(?,?,?,?,?)
                    """,
                    (
                        item["profile"],
                        "seo",
                        "zero_quota_blocked_repair",
                        json.dumps(
                            {
                                "video_id": item["video_id"],
                                "before_chars": item["before_chars"],
                                "after_chars": item["after_chars"],
                                "removed_english_duplicate": item["removed_english_duplicate"],
                                "youtube_api_calls": 0,
                            },
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )

        remaining = conn.execute(
            "SELECT COUNT(*) FROM optimization_drafts WHERE status='blocked'"
        ).fetchone()[0]
        return {
            "mode": "apply",
            "youtube_api_calls": 0,
            "backup": str(backup_path),
            "changed": len(candidates),
            "blocked_remaining": int(remaining or 0),
            "candidates": public,
        }
    finally:
        conn.close()



def quota_plan_status() -> dict:
    """Calculate the next fresh quota-day plan from local SQLite only."""
    from zoneinfo import ZoneInfo

    from rg_youtube_control.optimization import is_safe_archive_candidate
    from rg_youtube_control.service import (
        READ_REQUEST_COST,
        SAFE_METADATA_ITEM_COST,
        VIDEO_UPDATE_COST,
        YOUTUBE_DAILY_QUOTA_DEFAULT,
        reserve_safe_daily_batch_capacity,
    )

    db_path = _db_path()
    if not db_path.is_file():
        raise RuntimeError(f"RG YouTube Control DB not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        settings = {
            str(row["key"]): str(row["value"])
            for row in conn.execute(
                "SELECT key,value FROM settings"
            ).fetchall()
        }
        reserve = int(settings.get("youtube_quota_reserve_units", "500") or 500)
        fresh_spendable = max(0, YOUTUBE_DAILY_QUOTA_DEFAULT - reserve)

        scheduled_by_profile: dict[str, int] = {}
        ready_drafts_by_profile: dict[str, int] = {}
        safe_by_profile: dict[str, int] = {}

        for profile in ("main", "live"):
            scheduled_by_profile[profile] = int(
                conn.execute(
                    """SELECT COUNT(*)
                       FROM videos v
                       JOIN optimization_drafts d ON d.video_id=v.video_id
                       WHERE v.profile=?
                         AND v.scheduled_publish_at IS NOT NULL
                         AND d.status='ready'""",
                    (profile,),
                ).fetchone()[0]
            )
            ready_drafts_by_profile[profile] = int(
                conn.execute(
                    """SELECT COUNT(*)
                       FROM optimization_drafts d
                       JOIN videos v ON v.video_id=d.video_id
                       WHERE v.profile=? AND d.status='ready'""",
                    (profile,),
                ).fetchone()[0]
            )

            safe_count = 0
            for row in conn.execute(
                """SELECT audit_json
                   FROM videos
                   WHERE profile=?
                     AND privacy_status='public'
                     AND scheduled_publish_at IS NULL""",
                (profile,),
            ).fetchall():
                try:
                    issues = list(
                        json.loads(str(row["audit_json"] or "{}")).get(
                            "issues", []
                        )
                    )
                except Exception:
                    issues = []
                if is_safe_archive_candidate(issues):
                    safe_count += 1
            safe_by_profile[profile] = safe_count

        scheduled_total = sum(scheduled_by_profile.values())
        scheduled_cost = (
            scheduled_total * SAFE_METADATA_ITEM_COST
            + (READ_REQUEST_COST if scheduled_total else 0)
        )
        remaining_after_scheduled = max(
            0,
            fresh_spendable - scheduled_cost,
        )
        archive_capacity = reserve_safe_daily_batch_capacity(
            remaining_after_scheduled,
            500,
        )

        main_archive = min(safe_by_profile["main"], archive_capacity)
        left = max(0, archive_capacity - main_archive)
        live_archive = min(safe_by_profile["live"], left)

        pt_day = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        return {
            "quota_day_pt": pt_day,
            "youtube_api_calls": 0,
            "daily_quota": YOUTUBE_DAILY_QUOTA_DEFAULT,
            "reserve": reserve,
            "fresh_spendable": fresh_spendable,
            "scheduled_ready_by_profile": scheduled_by_profile,
            "scheduled_total": scheduled_total,
            "scheduled_estimated_cost": scheduled_cost,
            "remaining_after_scheduled": remaining_after_scheduled,
            "safe_archive_candidates_by_profile": safe_by_profile,
            "ready_drafts_by_profile": ready_drafts_by_profile,
            "safe_archive_capacity_after_scheduled": archive_capacity,
            "recommended_first_day": {
                "scheduled": scheduled_total,
                "archive_main": main_archive,
                "archive_live": live_archive,
                "estimated_total_videos": (
                    scheduled_total + main_archive + live_archive
                ),
            },
        }
    finally:
        conn.close()


def runtime_status() -> dict:
    """Read the installed RG YouTube Control version from Windows registry."""
    import subprocess

    installs: list[dict] = []
    if os.name == "nt":
        import winreg

        roots = [
            ("HKLM", winreg.HKEY_LOCAL_MACHINE),
            ("HKCU", winreg.HKEY_CURRENT_USER),
        ]
        views = [
            ("64", winreg.KEY_WOW64_64KEY),
            ("32", winreg.KEY_WOW64_32KEY),
        ]
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        for root_name, root in roots:
            for view_name, view_flag in views:
                try:
                    key = winreg.OpenKey(
                        root,
                        base,
                        0,
                        winreg.KEY_READ | view_flag,
                    )
                except OSError:
                    continue
                try:
                    count = winreg.QueryInfoKey(key)[0]
                    for index in range(count):
                        try:
                            sub_name = winreg.EnumKey(key, index)
                            sub = winreg.OpenKey(key, sub_name)
                            try:
                                name = str(
                                    winreg.QueryValueEx(
                                        sub, "DisplayName"
                                    )[0]
                                )
                            except OSError:
                                name = ""
                            if name.casefold() != "rg youtube control":
                                sub.Close()
                                continue
                            def value(field: str) -> str:
                                try:
                                    return str(
                                        winreg.QueryValueEx(sub, field)[0]
                                    )
                                except OSError:
                                    return ""
                            installs.append({
                                "root": root_name,
                                "view": view_name,
                                "key": sub_name,
                                "display_name": name,
                                "display_version": value("DisplayVersion"),
                                "install_location": value("InstallLocation"),
                                "uninstall_string": value("UninstallString"),
                            })
                            sub.Close()
                        except OSError:
                            continue
                finally:
                    key.Close()

    running = False
    process_text = ""
    if os.name == "nt":
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$p=Get-Process | Where-Object { "
                    "$_.ProcessName -like 'RG YouTube Control*' }; "
                    "$p | Select-Object Id,ProcessName,Path | "
                    "ConvertTo-Json -Compress"
                ),
            ],
            text=True,
            capture_output=True,
            timeout=20,
        )
        process_text = (proc.stdout or "").strip()
        running = bool(process_text and process_text not in {"null", "[]"})

    source_candidates = []
    candidate_paths = [
        Path.home() / "CHAT_YouTube-main",
        Path.home() / "CHAT_YouTube",
        Path(r"C:\RG_YOUTUBE_CONTROL"),
        Path(r"C:\Program Files\RG YouTube Control"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "RG YouTube Control",
    ]
    for candidate in candidate_paths:
        if not str(candidate):
            continue
        source_candidates.append({
            "path": str(candidate),
            "exists": candidate.exists(),
            "run_app": (candidate / "run_app.py").is_file(),
            "pyproject": (candidate / "pyproject.toml").is_file(),
            "exe": (candidate / "RG YouTube Control.exe").is_file(),
        })

    return {
        "youtube_api_calls": 0,
        "installs": installs,
        "running": running,
        "processes": process_text,
        "source_candidates": source_candidates,
    }

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    task_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "rg_remote_control" / "youtube_task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    action = str(task.get("action") or "")
    if action == "youtube_local_repair_preview":
        result = run("preview")
    elif action == "youtube_local_repair_apply":
        result = run("apply")
    elif action == "youtube_local_quota_plan_status":
        result = quota_plan_status()
    elif action == "youtube_local_runtime_status":
        result = runtime_status()
    else:
        raise RuntimeError(f"Unsupported YouTube local action: {action}")

    print(json.dumps(
        {"action": action, "result": result},
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
