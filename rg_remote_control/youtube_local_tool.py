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
    source_running = False
    source_processes = ""
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

        src_proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$p=Get-CimInstance Win32_Process | Where-Object { "
                    "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
                    "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*' }; "
                    "$p | Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
                    "ConvertTo-Json -Compress"
                ),
            ],
            text=True,
            capture_output=True,
            timeout=20,
        )
        source_processes = (src_proc.stdout or "").strip()
        source_running = bool(
            source_processes
            and source_processes not in {"null", "[]"}
        )

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
        pyproject_path = candidate / "pyproject.toml"
        exe_path = candidate / "RG YouTube Control.exe"
        source_version = ""
        if pyproject_path.is_file():
            try:
                match = re.search(
                    r'^version = "([^"]+)"',
                    pyproject_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ),
                    re.MULTILINE,
                )
                source_version = match.group(1) if match else ""
            except Exception:
                source_version = ""
        source_candidates.append({
            "path": str(candidate),
            "exists": candidate.exists(),
            "run_app": (candidate / "run_app.py").is_file(),
            "pyproject": pyproject_path.is_file(),
            "source_version": source_version,
            "exe": exe_path.is_file(),
            "exe_size": exe_path.stat().st_size if exe_path.is_file() else 0,
            "exe_mtime": (
                datetime.fromtimestamp(
                    exe_path.stat().st_mtime,
                    timezone.utc,
                ).isoformat()
                if exe_path.is_file()
                else ""
            ),
        })

    exe_version = {}
    installed_exe = Path(r"C:\Program Files\RG YouTube Control\RG YouTube Control.exe")
    if installed_exe.is_file() and os.name == "nt":
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$v=(Get-Item -LiteralPath '"
                    + str(installed_exe).replace("'", "''")
                    + "').VersionInfo; "
                    "$v | Select-Object FileVersion,ProductVersion,ProductName | "
                    "ConvertTo-Json -Compress"
                ),
            ],
            text=True,
            capture_output=True,
            timeout=20,
        )
        raw_version = (proc.stdout or "").strip()
        if raw_version:
            try:
                exe_version = json.loads(raw_version)
            except Exception:
                exe_version = {"raw": raw_version}

    gh_available = bool(shutil.which("gh"))
    gh_authenticated = False
    gh_account = ""
    if gh_available:
        auth = subprocess.run(
            ["gh", "auth", "status", "--hostname", "github.com"],
            text=True,
            capture_output=True,
            timeout=20,
        )
        gh_authenticated = auth.returncode == 0
        auth_text = (auth.stdout or "") + "\n" + (auth.stderr or "")
        account_match = re.search(
            r"Logged in to github\.com account ([^\s(]+)",
            auth_text,
            re.IGNORECASE,
        )
        if account_match:
            gh_account = account_match.group(1)

    shortcut_targets = []
    startup_matches = []
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", ""))
        shortcut_paths = [
            Path.home() / "Desktop" / "RG YouTube Control.lnk",
            appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "RG YouTube Control.lnk",
            appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "RG YouTube Control.lnk",
        ]
        for path in shortcut_paths:
            if not path.is_file():
                shortcut_targets.append({"path": str(path), "exists": False})
                continue
            command = (
                "$ws=New-Object -ComObject WScript.Shell; "
                "$s=$ws.CreateShortcut('"
                + str(path).replace("'", "''")
                + "'); "
                "[pscustomobject]@{TargetPath=$s.TargetPath;Arguments=$s.Arguments;"
                "WorkingDirectory=$s.WorkingDirectory} | ConvertTo-Json -Compress"
            )
            proc = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                text=True,
                capture_output=True,
                timeout=20,
            )
            raw = (proc.stdout or "").strip()
            try:
                info = json.loads(raw) if raw else {}
            except Exception:
                info = {"raw": raw}
            shortcut_targets.append(
                {"path": str(path), "exists": True, "target": info}
            )

        task_cmd = (
            "$items=Get-ScheduledTask -ErrorAction SilentlyContinue | "
            "Where-Object { $_.TaskName -match 'RG|YouTube|CHAT_YouTube' -or "
            "(($_.Actions | Out-String) -match 'RG YouTube|CHAT_YouTube|run_app.py') }; "
            "$items | ForEach-Object { "
            "[pscustomobject]@{TaskName=$_.TaskName;TaskPath=$_.TaskPath;"
            "State=$_.State;Actions=($_.Actions | Out-String).Trim()} "
            "} | ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                task_cmd,
            ],
            text=True,
            capture_output=True,
            timeout=30,
        )
        raw = (proc.stdout or "").strip()
        try:
            startup_matches = json.loads(raw) if raw else []
        except Exception:
            startup_matches = {"raw": raw}

    return {
        "youtube_api_calls": 0,
        "installs": installs,
        "running": running,
        "processes": process_text,
        "source_running": source_running,
        "source_processes": source_processes,
        "source_candidates": source_candidates,
        "shortcut_targets": shortcut_targets,
        "scheduled_task_matches": startup_matches,
        "installed_exe_version": exe_version,
        "gh_available": gh_available,
        "gh_authenticated": gh_authenticated,
        "gh_account": gh_account,
    }



def _stop_all_rg_youtube_gui_processes() -> dict:
    """Stop both legacy installed EXE and source GUI before relaunch."""
    import subprocess

    if os.name != "nt":
        return {"stopped": [], "windows": False}

    command = (
        "$items=Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -eq 'RG YouTube Control.exe') -or "
        "(($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
        "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*') }; "
        "$stopped=@(); "
        "foreach($p in $items){ "
        "$stopped += [pscustomobject]@{id=[int]$p.ProcessId;name=$p.Name;path=$p.ExecutablePath}; "
        "Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue "
        "}; "
        "$stopped | ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Could not stop existing RG YouTube Control GUI processes: "
            + ((proc.stderr or proc.stdout) or "")[-3000:]
        )
    raw = (proc.stdout or "").strip()
    try:
        stopped = json.loads(raw) if raw else []
    except Exception:
        stopped = raw
    return {"stopped": stopped, "windows": True}


def _stop_non_private_source_gui_processes(target: Path) -> dict:
    """Remove stale source GUI processes not running from the private venv."""
    import subprocess

    if os.name != "nt":
        return {"removed": [], "windows": False}

    keep = target / ".venv" / "Scripts" / "pythonw.exe"
    command = (
        "$keep='"
        + str(keep).replace("'", "''")
        + "'; "
        "$items=Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
        "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*' }; "
        "$removed=@(); "
        "foreach($p in $items){ "
        "if(-not $p.ExecutablePath -or $p.ExecutablePath -ne $keep){ "
        "$removed += [pscustomobject]@{id=[int]$p.ProcessId;path=$p.ExecutablePath}; "
        "Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue "
        "} }; "
        "$removed | ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Could not remove stale RG YouTube Control source process: "
            + ((proc.stderr or proc.stdout) or "")[-3000:]
        )
    raw = (proc.stdout or "").strip()
    try:
        removed = json.loads(raw) if raw else []
    except Exception:
        removed = raw
    return {"removed": removed, "windows": True}


def stop_legacy_installed_gui() -> dict:
    """Stop only the obsolete Program Files EXE so the source shortcut can be used."""
    import subprocess

    if os.name != "nt":
        return {"youtube_api_calls": 0, "stopped": [], "windows": False}

    command = (
        "$items=Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -eq 'RG YouTube Control.exe' -and "
        "$_.ExecutablePath -like 'C:\\Program Files\\RG YouTube Control\\*' }; "
        "$stopped=@(); "
        "foreach($p in $items){ "
        "$stopped += [pscustomobject]@{id=[int]$p.ProcessId;path=$p.ExecutablePath}; "
        "Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue "
        "}; "
        "$stopped | ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Could not stop legacy installed GUI: "
            + ((proc.stderr or proc.stdout) or "")[-3000:]
        )
    raw = (proc.stdout or "").strip()
    try:
        stopped = json.loads(raw) if raw else []
    except Exception:
        stopped = raw
    return {
        "youtube_api_calls": 0,
        "stopped": stopped,
        "desktop_shortcut": str(Path.home() / "Desktop" / "RG YouTube Control.lnk"),
        "source_version": (
            re.search(
                r'^version = "([^"]+)"',
                (Path.home() / "CHAT_YouTube-main" / "pyproject.toml").read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                re.MULTILINE,
            ).group(1)
            if (Path.home() / "CHAT_YouTube-main" / "pyproject.toml").is_file()
            and re.search(
                r'^version = "([^"]+)"',
                (Path.home() / "CHAT_YouTube-main" / "pyproject.toml").read_text(
                    encoding="utf-8",
                    errors="replace",
                ),
                re.MULTILINE,
            )
            else ""
        ),
    }


def _source_python(target: Path, *, windowed: bool = False) -> Path:
    scripts = target / ".venv" / "Scripts"
    candidate = scripts / ("pythonw.exe" if windowed else "python.exe")
    if candidate.is_file():
        return candidate
    if windowed:
        fallback = Path(sys.executable).with_name("pythonw.exe")
        if fallback.is_file():
            return fallback
    return Path(sys.executable)


def prepare_source_runtime() -> dict:
    """Create/update the private venv used by the local source GUI."""
    import subprocess

    target = Path.home() / "CHAT_YouTube-main"
    pyproject = target / "pyproject.toml"
    run_app = target / "run_app.py"
    if not pyproject.is_file() or not run_app.is_file():
        raise RuntimeError(f"RG YouTube Control source is incomplete: {target}")

    venv_dir = target / ".venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    if not venv_python.is_file():
        created = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            cwd=str(target),
            text=True,
            capture_output=True,
            timeout=180,
        )
        if created.returncode != 0:
            raise RuntimeError(
                "venv creation failed: "
                + ((created.stderr or created.stdout) or "")[-4000:]
            )

    install = subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-e",
            ".",
        ],
        cwd=str(target),
        text=True,
        capture_output=True,
        timeout=900,
    )
    if install.returncode != 0:
        raise RuntimeError(
            "dependency install failed: "
            + ((install.stderr or install.stdout) or "")[-8000:]
        )

    probe = subprocess.run(
        [
            str(venv_python),
            "-c",
            (
                "import PySide6, googleapiclient, google.auth, keyring, "
                "yt_dlp, youtube_transcript_api; "
                "print(PySide6.__version__)"
            ),
        ],
        cwd=str(target),
        text=True,
        capture_output=True,
        timeout=60,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            "runtime import probe failed: "
            + ((probe.stderr or probe.stdout) or "")[-4000:]
        )

    match = re.search(
        r'^version = "([^"]+)"',
        pyproject.read_text(encoding="utf-8", errors="replace"),
        re.MULTILINE,
    )
    return {
        "youtube_api_calls": 0,
        "target": str(target),
        "version": match.group(1) if match else "",
        "venv": str(venv_dir),
        "python": str(venv_python),
        "pythonw": str(venv_dir / "Scripts" / "pythonw.exe"),
        "pyside6_version": (probe.stdout or "").strip(),
        "install_tail": (install.stdout or "")[-2500:],
    }

def sync_and_launch_source() -> dict:
    """Safely update the fixed local source checkout and launch it."""
    import subprocess
    import time

    target = Path.home() / "CHAT_YouTube-main"
    if not target.is_dir():
        raise RuntimeError(f"Local source folder not found: {target}")
    source_src = ROOT / "src"
    if not source_src.is_dir():
        raise RuntimeError(f"Fresh source folder not found: {source_src}")

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup = target / "BACKUPS" / f"source_before_sync_{stamp}"
    backup.mkdir(parents=True, exist_ok=True)

    target_src = target / "src"
    if target_src.exists():
        shutil.copytree(target_src, backup / "src")
    for name in ("run_app.py", "pyproject.toml", "requirements.txt"):
        src_file = target / name
        if src_file.is_file():
            shutil.copy2(src_file, backup / name)

    if target_src.exists():
        shutil.rmtree(target_src)
    shutil.copytree(source_src, target_src)
    for name in ("run_app.py", "pyproject.toml", "requirements.txt"):
        src_file = ROOT / name
        if src_file.is_file():
            shutil.copy2(src_file, target / name)

    version_match = re.search(
        r'^version = "([^"]+)"',
        (target / "pyproject.toml").read_text(
            encoding="utf-8",
            errors="replace",
        ),
        re.MULTILINE,
    )
    version = version_match.group(1) if version_match else ""

    stopped = _stop_all_rg_youtube_gui_processes()
    time.sleep(1)

    executable = _source_python(target, windowed=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target / "src")
    env.pop("RUNNER_TRACKING_ID", None)

    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)

    proc = subprocess.Popen(
        [str(executable), str(target / "run_app.py")],
        cwd=str(target),
        env=env,
        creationflags=creationflags,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    time.sleep(5)
    stale_cleanup = _stop_non_private_source_gui_processes(target)
    time.sleep(1)
    running = False
    process_text = ""
    if os.name == "nt":
        verify = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$p=Get-CimInstance Win32_Process | Where-Object { "
                    "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
                    "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*' }; "
                    "$p | Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
                    "ConvertTo-Json -Compress"
                ),
            ],
            text=True,
            capture_output=True,
            timeout=20,
        )
        process_text = (verify.stdout or "").strip()
        running = bool(
            process_text and process_text not in {"null", "[]"}
        )

    if not running:
        raise RuntimeError(
            f"Source {version or 'current'} was synced, but the GUI process was not detected."
        )

    return {
        "youtube_api_calls": 0,
        "target": str(target),
        "backup": str(backup),
        "version": version,
        "python": str(executable),
        "pid": proc.pid,
        "running": running,
        "processes": process_text,
        "stopped_before_launch": stopped,
        "stale_cleanup": stale_cleanup,
    }


def launch_diagnostic() -> dict:
    """Run the updated source briefly and report why it exits."""
    import subprocess
    import time

    target = Path.home() / "CHAT_YouTube-main"
    python = _source_python(target, windowed=False)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(target / "src")
    proc = subprocess.Popen(
        [str(python), str(target / "run_app.py")],
        cwd=str(target),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(6)
    code = proc.poll()
    if code is None:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        return {
            "youtube_api_calls": 0,
            "stayed_alive": True,
            "exit_code": None,
            "stdout": (out or "")[-4000:],
            "stderr": (err or "")[-8000:],
        }

    out, err = proc.communicate(timeout=5)
    return {
        "youtube_api_calls": 0,
        "stayed_alive": False,
        "exit_code": int(code),
        "stdout": (out or "")[-4000:],
        "stderr": (err or "")[-8000:],
    }


def sync_recent_live_for_today() -> dict:
    """Sync only recent LIVE-channel videos and return scheduled candidates."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from rg_youtube_control.db import connect
    from rg_youtube_control.service import sync_videos, today_quota_units
    from rg_youtube_control.youtube_api import YouTubeClient

    conn = connect(_db_path())
    try:
        before = today_quota_units(conn)
        client = YouTubeClient(profile="live")
        client.credentials()
        rows = sync_videos(client, conn, limit=20)
        after = today_quota_units(conn)

        kyiv_today = datetime.now(ZoneInfo("Europe/Kyiv")).date()
        scheduled = []
        for row in rows:
            raw = str(row.get("scheduled_publish_at") or "")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                kyiv_dt = dt.astimezone(ZoneInfo("Europe/Kyiv"))
                is_today = kyiv_dt.date() == kyiv_today
                kyiv_iso = kyiv_dt.isoformat()
            except Exception:
                is_today = False
                kyiv_iso = ""
            scheduled.append({
                "video_id": row.get("video_id"),
                "profile": row.get("profile"),
                "title": row.get("title"),
                "scheduled_publish_at": raw,
                "scheduled_kyiv": kyiv_iso,
                "is_today_kyiv": is_today,
                "privacy_status": row.get("privacy_status"),
                "audit": row.get("audit"),
            })

        return {
            "youtube_api_calls": max(0, after - before),
            "synced": len(rows),
            "today_kyiv": kyiv_today.isoformat(),
            "scheduled": scheduled,
            "today_scheduled": [
                item for item in scheduled if item["is_today_kyiv"]
            ],
        }
    finally:
        conn.close()


def find_today_upcoming_live_broadcasts() -> dict:
    """Find upcoming broadcasts on the LIVE channel with minimal quota."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from rg_youtube_control.db import connect, upsert_video
    from rg_youtube_control.metadata_audit import audit
    from rg_youtube_control.service import (
        READ_REQUEST_COST,
        record_quota_units,
        today_quota_units,
    )
    from rg_youtube_control.youtube_api import YouTubeClient

    conn = connect(_db_path())
    try:
        before = today_quota_units(conn)
        client = YouTubeClient(profile="live")
        client.credentials()
        response = client.service().liveBroadcasts().list(
            part="id,snippet,status",
            mine=True,
            maxResults=50,
        ).execute()
        record_quota_units(
            conn,
            READ_REQUEST_COST,
            purpose="service",
        )
        broadcasts = response.get("items", []) or []
        ids = [str(item.get("id") or "") for item in broadcasts if item.get("id")]
        details = []
        if ids:
            details, requests = client.video_details_with_request_count(ids)
            record_quota_units(
                conn,
                int(requests) * READ_REQUEST_COST,
                purpose="service",
            )

        details_by_id = {str(item.get("id")): item for item in details}
        kyiv = ZoneInfo("Europe/Kyiv")
        kyiv_today = datetime.now(kyiv).date()
        result_items = []

        for item in broadcasts:
            video_id = str(item.get("id") or "")
            snippet = item.get("snippet", {}) or {}
            raw_start = str(snippet.get("scheduledStartTime") or "")
            try:
                start_dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                kyiv_dt = start_dt.astimezone(kyiv)
                is_today = kyiv_dt.date() == kyiv_today
                kyiv_iso = kyiv_dt.isoformat()
            except Exception:
                kyiv_dt = None
                is_today = False
                kyiv_iso = ""

            detail = details_by_id.get(video_id, {})
            dsn = detail.get("snippet", {}) or {}
            dst = detail.get("status", {}) or {}
            dct = detail.get("contentDetails", {}) or {}
            stats = detail.get("statistics", {}) or {}
            title = str(dsn.get("title") or snippet.get("title") or "")
            description = str(dsn.get("description") or snippet.get("description") or "")
            tags = dsn.get("tags") or []
            audit_result = audit(
                description,
                tags,
                title,
                dct.get("duration"),
            )
            if detail:
                upsert_video(
                    conn,
                    {
                        "video_id": video_id,
                        "profile": "live",
                        "channel_id": dsn.get("channelId"),
                        "title": title,
                        "published_at": dsn.get("publishedAt"),
                        "scheduled_publish_at": raw_start or dst.get("publishAt"),
                        "privacy_status": dst.get("privacyStatus"),
                        "duration": dct.get("duration"),
                        "views": int(stats.get("viewCount") or 0),
                        "audit": {
                            "score": audit_result.score,
                            "issues": list(audit_result.issues),
                        },
                    },
                )

            result_items.append({
                "video_id": video_id,
                "title": title,
                "scheduled_start": raw_start,
                "scheduled_kyiv": kyiv_iso,
                "is_today_kyiv": is_today,
                "privacy_status": dst.get("privacyStatus"),
                "description_chars": len(description),
                "tags_count": len(tags),
                "audit_issues": list(audit_result.issues),
                "life_cycle_status": (
                    item.get("status", {}) or {}
                ).get("lifeCycleStatus"),
            })

        after = today_quota_units(conn)
        return {
            "youtube_api_calls": max(0, after - before),
            "today_kyiv": kyiv_today.isoformat(),
            "upcoming_count": len(result_items),
            "upcoming": result_items,
            "today_upcoming": [
                item for item in result_items if item["is_today_kyiv"]
            ],
        }
    finally:
        conn.close()


def optimize_scheduled_stream(task: dict) -> dict:
    """Apply a metadata-only package to one scheduled stream safely."""
    from rg_youtube_control.db import (
        connect,
        log_action,
        record_optimization_event,
        save_metadata_snapshot,
        save_optimization_draft,
    )
    from rg_youtube_control.service import (
        READ_REQUEST_COST,
        VIDEO_UPDATE_COST,
        quota_budget_status,
        record_quota_units,
        today_quota_units,
    )
    from rg_youtube_control.youtube_api import YouTubeClient

    args = task.get("args") or {}
    video_id = str(args.get("video_id") or "").strip()
    profile = str(args.get("profile") or "live").strip()
    description = str(args.get("description") or "").strip()
    tags = [str(x).strip() for x in (args.get("tags") or []) if str(x).strip()]
    if not video_id:
        raise RuntimeError("video_id is required")
    if not description or len(description) > 5000:
        raise RuntimeError("description must be 1..5000 chars")
    if not tags or len(", ".join(tags)) > 500:
        raise RuntimeError("tags are empty or exceed 500 chars")

    conn = connect(_db_path())
    try:
        budget = quota_budget_status(conn)
        # update_video = 1 read + videos.update; final verify = 1 read.
        required = VIDEO_UPDATE_COST + READ_REQUEST_COST
        if int(budget["spendable"]) < required:
            raise RuntimeError(
                f"Not enough quota above reserve: need {required}, "
                f"spendable {budget['spendable']}"
            )

        client = YouTubeClient(profile=profile)
        client.credentials()
        before_units = today_quota_units(conn)

        items, requests = client.video_details_with_request_count([video_id])
        record_quota_units(
            conn,
            int(requests) * READ_REQUEST_COST,
            purpose="service",
        )
        if not items:
            raise RuntimeError(f"Video not found: {video_id}")

        current = items[0]
        snippet = current.get("snippet", {}) or {}
        current_title = str(snippet.get("title") or "")
        current_description = str(snippet.get("description") or "")
        current_tags = list(snippet.get("tags") or [])

        history_id = save_metadata_snapshot(
            conn,
            video_id,
            current_title,
            current_description,
            current_tags,
            "before_today_scheduled_stream_optimization",
        )
        save_optimization_draft(
            conn,
            video_id,
            current_title,
            description,
            "",
            tags,
            "ready",
            [current_title],
        )

        client.update_video(
            video_id,
            title=current_title,
            description=description,
            tags=tags,
        )
        record_quota_units(
            conn,
            VIDEO_UPDATE_COST,
            purpose="video",
        )

        verified, verify_requests = client.video_details_with_request_count(
            [video_id]
        )
        record_quota_units(
            conn,
            int(verify_requests) * READ_REQUEST_COST,
            purpose="service",
        )
        if not verified:
            raise RuntimeError("Final verification returned no video")
        verified_snippet = verified[0].get("snippet", {}) or {}
        if str(verified_snippet.get("title") or "") != current_title:
            raise RuntimeError("Title changed unexpectedly")
        if str(verified_snippet.get("description") or "") != description:
            raise RuntimeError("Description verification failed")
        if list(verified_snippet.get("tags") or []) != tags:
            raise RuntimeError("Tags verification failed")

        save_optimization_draft(
            conn,
            video_id,
            current_title,
            description,
            "",
            tags,
            "applied",
            [current_title],
        )
        record_optimization_event(
            conn,
            history_id=history_id,
            video_id=video_id,
            profile=profile,
            reason="today_scheduled_stream_priority",
            changed_fields="опис + теги",
        )
        log_action(
            conn,
            profile=profile,
            category="заплановані",
            action="Сьогоднішній стрім оптимізовано",
            details=(
                f"{video_id}; title unchanged; "
                f"description {len(current_description)}->{len(description)}; "
                f"tags {len(current_tags)}->{len(tags)}"
            ),
        )
        after_units = today_quota_units(conn)
        return {
            "video_id": video_id,
            "profile": profile,
            "title": current_title,
            "title_changed": False,
            "description_before_chars": len(current_description),
            "description_after_chars": len(description),
            "tags_before": len(current_tags),
            "tags_after": len(tags),
            "draft_status": "applied",
            "verified": True,
            "youtube_api_units_tracked": max(0, after_units - before_units),
            "reserve": budget["reserve"],
        }
    finally:
        conn.close()


def verify_stream_901_after_partial_update() -> dict:
    """Recover quota accounting and inspect Stream 901 after API normalization."""
    from rg_youtube_control.db import connect, get_setting, set_setting
    from rg_youtube_control.service import (
        READ_REQUEST_COST,
        VIDEO_UPDATE_COST,
        record_quota_units,
        today_quota_units,
    )
    from rg_youtube_control.youtube_api import YouTubeClient

    video_id = "K-yK-cDQij0"
    marker_key = "quota_repair_stream901_partial_update_2026-10-05"
    conn = connect(_db_path())
    try:
        before = today_quota_units(conn)
        if get_setting(conn, marker_key, "0") != "1":
            record_quota_units(
                conn,
                VIDEO_UPDATE_COST,
                purpose="video",
            )
            set_setting(conn, marker_key, "1")

        client = YouTubeClient(profile="live")
        client.credentials()
        items, requests = client.video_details_with_request_count([video_id])
        record_quota_units(
            conn,
            int(requests) * READ_REQUEST_COST,
            purpose="service",
        )
        if not items:
            raise RuntimeError(f"Video not found: {video_id}")
        snippet = items[0].get("snippet", {}) or {}
        after = today_quota_units(conn)
        return {
            "video_id": video_id,
            "title": str(snippet.get("title") or ""),
            "description": str(snippet.get("description") or ""),
            "description_chars": len(str(snippet.get("description") or "")),
            "tags": list(snippet.get("tags") or []),
            "tags_count": len(list(snippet.get("tags") or [])),
            "quota_units_added_this_recovery": max(0, after - before),
            "quota_repair_marker": get_setting(conn, marker_key, "0"),
        }
    finally:
        conn.close()


def finalize_stream_901_local_state() -> dict:
    """Finalize Stream 901 local state after verified YouTube update."""
    from rg_youtube_control.db import (
        connect,
        latest_metadata_snapshot,
        log_action,
        record_optimization_event,
        set_optimization_draft_status,
    )

    video_id = "K-yK-cDQij0"
    conn = connect(_db_path())
    try:
        row = conn.execute(
            "SELECT status FROM optimization_drafts WHERE video_id=?",
            (video_id,),
        ).fetchone()
        before_status = str(row["status"] or "") if row else ""
        if row:
            set_optimization_draft_status(conn, video_id, "applied")

        existing = conn.execute(
            """SELECT event_id
               FROM optimization_events
               WHERE video_id=? AND reason='today_scheduled_stream_priority'
               LIMIT 1""",
            (video_id,),
        ).fetchone()
        event_id = int(existing["event_id"]) if existing else 0
        if not existing:
            snap = latest_metadata_snapshot(conn, video_id)
            history_id = int(snap["history_id"]) if snap else None
            event_id = record_optimization_event(
                conn,
                history_id=history_id,
                video_id=video_id,
                profile="live",
                reason="today_scheduled_stream_priority",
                changed_fields="опис + теги",
            )

        logged = conn.execute(
            """SELECT log_id FROM action_log
               WHERE profile='live'
                 AND category='заплановані'
                 AND action='Сьогоднішній стрім оптимізовано'
                 AND details LIKE ?
               LIMIT 1""",
            (f"%{video_id}%",),
        ).fetchone()
        if not logged:
            log_action(
                conn,
                profile="live",
                category="заплановані",
                action="Сьогоднішній стрім оптимізовано",
                details=(
                    f"{video_id}; verified on YouTube; "
                    "title unchanged; description optimized; 15 tags"
                ),
            )

        after = conn.execute(
            "SELECT status FROM optimization_drafts WHERE video_id=?",
            (video_id,),
        ).fetchone()
        return {
            "youtube_api_calls": 0,
            "video_id": video_id,
            "before_status": before_status,
            "after_status": str(after["status"] or "") if after else "",
            "optimization_event_id": event_id,
            "verified_youtube_state": True,
        }
    finally:
        conn.close()


def _write_rg_youtube_icon(path: Path) -> None:
    """Create a clean RG/YouTube-style 256px icon using only stdlib."""
    import binascii
    import struct
    import zlib

    size = 256
    radius = 54
    pixels = bytearray()

    def inside_round_rect(x: int, y: int) -> bool:
        if radius <= x < size - radius:
            return True
        if radius <= y < size - radius:
            return True
        cx = radius if x < radius else size - radius - 1
        cy = radius if y < radius else size - radius - 1
        return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2

    # 5x7 bitmap letters. Intentionally geometric to stay legible at 16-32px.
    glyphs = {
        "R": (
            "11110",
            "10001",
            "10001",
            "11110",
            "10100",
            "10010",
            "10001",
        ),
        "G": (
            "01111",
            "10000",
            "10000",
            "10111",
            "10001",
            "10001",
            "01110",
        ),
    }
    scale = 14
    glyph_w = 5 * scale
    glyph_h = 7 * scale
    gap = 14
    total_w = glyph_w * 2 + gap
    start_x = (size - total_w) // 2
    start_y = (size - glyph_h) // 2 + 2

    def glyph_pixel(x: int, y: int) -> bool:
        for index, letter in enumerate(("R", "G")):
            gx = start_x + index * (glyph_w + gap)
            gy = start_y
            if gx <= x < gx + glyph_w and gy <= y < gy + glyph_h:
                col = (x - gx) // scale
                row = (y - gy) // scale
                return glyphs[letter][row][col] == "1"
        return False

    for y in range(size):
        pixels.append(0)  # PNG filter byte
        for x in range(size):
            if not inside_round_rect(x, y):
                pixels.extend((0, 0, 0, 0))
                continue

            # Deep YouTube red with a subtle vertical gradient.
            red = max(205, 255 - int(34 * y / (size - 1)))
            green = 0
            blue = 46 if y < size // 2 else 34

            # Soft inner border.
            edge = min(x, y, size - 1 - x, size - 1 - y)
            if edge < 5:
                red = max(170, red - 28)
                blue = max(18, blue - 10)

            if glyph_pixel(x, y):
                pixels.extend((255, 255, 255, 255))
            else:
                pixels.extend((red, green, blue, 255))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
        + chunk(b"IEND", b"")
    )

    # ICO containing the PNG image.
    ico = (
        struct.pack("<HHH", 0, 1, 1)
        + struct.pack(
            "<BBBBHHII",
            0,  # 256 width
            0,  # 256 height
            0,
            0,
            1,
            32,
            len(png),
            22,
        )
        + png
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico)


def brand_shortcuts() -> dict:
    """Create polished desktop/Start Menu shortcuts for the source runtime."""
    import subprocess

    target = Path.home() / "CHAT_YouTube-main"
    run_app = target / "run_app.py"
    executable = target / ".venv" / "Scripts" / "pythonw.exe"
    if not run_app.is_file():
        raise RuntimeError(f"run_app.py not found: {run_app}")
    if not executable.is_file():
        raise RuntimeError(f"pythonw.exe not found: {executable}")

    appdata = Path(
        os.environ.get(
            "APPDATA",
            str(Path.home() / "AppData" / "Roaming"),
        )
    )
    desktop = Path.home() / "Desktop"
    programs = (
        appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )
    startup = programs / "Startup"
    icon_path = target / "assets" / "RG YouTube Control.ico"
    _write_rg_youtube_icon(icon_path)

    shortcuts = (
        desktop / "RG YouTube Control.lnk",
        programs / "RG YouTube Control.lnk",
        startup / "RG YouTube Control.lnk",
    )

    def ps_quote(value: str) -> str:
        return value.replace("'", "''")

    for path in shortcuts:
        path.parent.mkdir(parents=True, exist_ok=True)
        command = (
            "$ws=New-Object -ComObject WScript.Shell; "
            "$s=$ws.CreateShortcut('"
            + ps_quote(str(path))
            + "'); "
            "$s.TargetPath='"
            + ps_quote(str(executable))
            + "'; "
            "$s.Arguments='\""
            + ps_quote(str(run_app))
            + "\"'; "
            "$s.WorkingDirectory='"
            + ps_quote(str(target))
            + "'; "
            "$s.IconLocation='"
            + ps_quote(str(icon_path))
            + ",0'; "
            "$s.Description='RG YouTube Control - YouTube management and SEO'; "
            "$s.Save()"
        )
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            text=True,
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "Shortcut create failed: "
                + ((proc.stderr or proc.stdout) or "")[-3000:]
            )

    # Refresh Explorer icon cache/view.
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$shell=New-Object -ComObject Shell.Application; "
                "$shell.Windows() | ForEach-Object { try { $_.Refresh() } catch {} }"
            ),
        ],
        text=True,
        capture_output=True,
        timeout=20,
    )

    return {
        "youtube_api_calls": 0,
        "target": str(target),
        "executable": str(executable),
        "arguments": f'"{run_app}"',
        "working_directory": str(target),
        "icon": str(icon_path),
        "icon_exists": icon_path.is_file(),
        "desktop_shortcut": str(shortcuts[0]),
        "desktop_shortcut_exists": shortcuts[0].is_file(),
        "start_menu_shortcut": str(shortcuts[1]),
        "start_menu_shortcut_exists": shortcuts[1].is_file(),
        "startup_shortcut": str(shortcuts[2]),
        "startup_shortcut_exists": shortcuts[2].is_file(),
    }


def ensure_gui_startup() -> dict:
    """Create desktop/startup launchers and start the GUI in user context."""
    import subprocess
    import time

    target = Path.home() / "CHAT_YouTube-main"
    run_app = target / "run_app.py"
    if not run_app.is_file():
        raise RuntimeError(f"run_app.py not found: {run_app}")

    executable = _source_python(target, windowed=True)

    pyproject = target / "pyproject.toml"
    version = ""
    if pyproject.is_file():
        match = re.search(
            r'^version = "([^"]+)"',
            pyproject.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        version = match.group(1) if match else ""

    appdata = Path(
        os.environ.get(
            "APPDATA",
            str(Path.home() / "AppData" / "Roaming"),
        )
    )
    desktop = Path.home() / "Desktop"
    programs = (
        appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )
    startup = programs / "Startup"
    desktop.mkdir(parents=True, exist_ok=True)
    programs.mkdir(parents=True, exist_ok=True)
    startup.mkdir(parents=True, exist_ok=True)

    def _ps_quote(value: str) -> str:
        return value.replace("'", "''")

    def create_shortcut(path: Path) -> None:
        command = (
            "$ws=New-Object -ComObject WScript.Shell; "
            "$s=$ws.CreateShortcut('"
            + _ps_quote(str(path))
            + "'); $s.TargetPath='"
            + _ps_quote(str(executable))
            + "'; $s.Arguments='\""
            + _ps_quote(str(run_app))
            + "\"'; $s.WorkingDirectory='"
            + _ps_quote(str(target))
            + "'; $s.Description='RG YouTube Control'; $s.Save()"
        )
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            text=True,
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "Shortcut create failed: "
                + ((proc.stderr or proc.stdout) or "")[-2000:]
            )

    desktop_shortcut = desktop / "RG YouTube Control.lnk"
    programs_shortcut = programs / "RG YouTube Control.lnk"
    startup_shortcut = startup / "RG YouTube Control.lnk"
    create_shortcut(desktop_shortcut)
    create_shortcut(programs_shortcut)
    create_shortcut(startup_shortcut)

    stopped = _stop_all_rg_youtube_gui_processes()
    time.sleep(1)

    # Launch through the interactive Windows shell instead of as a child of
    # the GitHub runner. The runner cleans up child processes at job end.
    shell_launch = subprocess.run(
        [
            "explorer.exe",
            str(desktop_shortcut),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if shell_launch.returncode not in (0, 1):
        raise RuntimeError(
            "Windows shell launch failed: "
            + ((shell_launch.stderr or shell_launch.stdout) or "")[-3000:]
        )

    time.sleep(8)
    stale_cleanup = _stop_non_private_source_gui_processes(target)
    time.sleep(1)
    verify = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$p=Get-CimInstance Win32_Process | Where-Object { "
                "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
                "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*' }; "
                "$p | Select-Object ProcessId,Name,ExecutablePath,CommandLine | "
                "ConvertTo-Json -Compress"
            ),
        ],
        text=True,
        capture_output=True,
        timeout=20,
    )
    process_text = (verify.stdout or "").strip()
    running = bool(
        process_text
        and process_text not in {"null", "[]"}
    )

    return {
        "youtube_api_calls": 0,
        "version": version,
        "target": str(target),
        "desktop_shortcut": str(desktop_shortcut),
        "desktop_shortcut_exists": desktop_shortcut.is_file(),
        "programs_shortcut": str(programs_shortcut),
        "programs_shortcut_exists": programs_shortcut.is_file(),
        "startup_shortcut": str(startup_shortcut),
        "startup_shortcut_exists": startup_shortcut.is_file(),
        "pid": None,
        "launch_via": "explorer-shortcut",
        "running": running,
        "processes": process_text,
        "stopped_before_launch": stopped,
        "stale_cleanup": stale_cleanup,
    }


def cleanup_gui_processes() -> dict:
    """Keep only the private-venv RG YouTube Control GUI process."""
    import subprocess

    target = Path.home() / "CHAT_YouTube-main"
    keep = target / ".venv" / "Scripts" / "pythonw.exe"
    if not keep.is_file():
        raise RuntimeError(f"Private GUI runtime not found: {keep}")

    command = (
        "$keep='"
        + str(keep).replace("'", "''")
        + "'; "
        "$items=Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
        "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*' }; "
        "$removed=@(); "
        "foreach($p in $items){ "
        "if($p.ExecutablePath -and ($p.ExecutablePath -ne $keep)){ "
        "$removed += [int]$p.ProcessId; "
        "Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue "
        "} }; "
        "$alive=Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') "
        "-and $_.CommandLine -like '*CHAT_YouTube-main*run_app.py*' }; "
        "[pscustomobject]@{removed=$removed;alive=$alive} | "
        "ConvertTo-Json -Depth 5 -Compress"
    )
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "GUI process cleanup failed: "
            + ((proc.stderr or proc.stdout) or "")[-3000:]
        )
    raw = (proc.stdout or "").strip()
    payload = {}
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
    return {
        "youtube_api_calls": 0,
        "keep": str(keep),
        "result": payload,
    }


def enable_archive_priority_campaign() -> dict:
    """Enable the safe archive campaign without spending YouTube quota."""
    from rg_youtube_control.db import connect, get_setting
    from rg_youtube_control.service import (
        quota_budget_status,
        set_archive_priority_mode,
    )

    conn = connect(_db_path())
    try:
        before = {
            "archive_priority_mode": get_setting(
                conn, "archive_priority_mode", "0"
            ),
            "safe_metadata_autopilot_main": get_setting(
                conn, "safe_metadata_autopilot_main", "0"
            ),
            "safe_metadata_autopilot_live": get_setting(
                conn, "safe_metadata_autopilot_live", "0"
            ),
        }
        set_archive_priority_mode(
            conn,
            True,
            profiles=("main", "live"),
        )
        after = {
            "archive_priority_mode": get_setting(
                conn, "archive_priority_mode", "0"
            ),
            "safe_metadata_autopilot_main": get_setting(
                conn, "safe_metadata_autopilot_main", "0"
            ),
            "safe_metadata_autopilot_live": get_setting(
                conn, "safe_metadata_autopilot_live", "0"
            ),
        }
        scheduled_ready = int(
            conn.execute(
                """SELECT COUNT(*)
                   FROM videos v
                   JOIN optimization_drafts d ON d.video_id=v.video_id
                   WHERE v.scheduled_publish_at IS NOT NULL
                     AND d.status='ready'"""
            ).fetchone()[0]
        )
        return {
            "youtube_api_calls": 0,
            "before": before,
            "after": after,
            "scheduled_ready": scheduled_ready,
            "quota_budget": quota_budget_status(conn),
            "note": (
                "Archive priority mode owns quota spending; "
                "scheduled ready packages are applied first."
            ),
        }
    finally:
        conn.close()


def apply_ready_scheduled_batch() -> dict:
    """Apply ready scheduled packages before archive work, preserving reserve."""
    from rg_youtube_control.db import (
        connect,
        log_action,
        record_optimization_event,
        save_metadata_snapshot,
        set_optimization_draft_status,
    )
    from rg_youtube_control.optimization import (
        compose_description,
        sanitize_imported_package_description,
        validate_content_package,
    )
    from rg_youtube_control.service import (
        READ_REQUEST_COST,
        VIDEO_UPDATE_COST,
        mark_quota_exhausted,
        quota_budget_status,
        record_quota_units,
        today_quota_units,
    )
    from rg_youtube_control.youtube_api import YouTubeClient

    conn = connect(_db_path())
    try:
        rows = conn.execute(
            """SELECT v.video_id,v.profile,v.title,v.scheduled_publish_at,
                      d.new_title,d.description,d.chapters,d.tags_json,
                      d.title_variants_json
               FROM videos v
               JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.scheduled_publish_at IS NOT NULL
                 AND d.status='ready'
               ORDER BY v.scheduled_publish_at ASC"""
        ).fetchall()
        if not rows:
            return {
                "youtube_api_calls": 0,
                "ready_found": 0,
                "changed": 0,
                "verified": 0,
                "errors": [],
            }

        budget = quota_budget_status(conn)
        if bool(budget["exhausted"]):
            raise RuntimeError("YouTube quota is exhausted")

        # Worst case per item: update_video contains one read + one write (51),
        # plus one shared preflight read and one shared final verification read.
        affordable = max(
            0,
            (int(budget["spendable"]) - 2 * READ_REQUEST_COST)
            // VIDEO_UPDATE_COST,
        )
        rows = rows[:affordable]
        if not rows:
            raise RuntimeError(
                "No scheduled item fits above the protected quota reserve"
            )

        backup_path = _backup_database(conn)
        before_units = today_quota_units(conn)

        by_profile: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_profile.setdefault(str(row["profile"] or "main"), []).append(row)

        changed_ids: list[str] = []
        prepared_by_id: dict[str, dict] = {}
        errors: list[str] = []

        for profile, profile_rows in by_profile.items():
            client = YouTubeClient(profile=profile)
            client.credentials()
            ids = [str(row["video_id"]) for row in profile_rows]

            current_items, requests = client.video_details_with_request_count(ids)
            record_quota_units(
                conn,
                int(requests) * READ_REQUEST_COST,
                purpose="service",
            )
            current_by_id = {
                str(item.get("id") or ""): item
                for item in current_items
            }

            for row in profile_rows:
                video_id = str(row["video_id"])
                try:
                    current = current_by_id.get(video_id)
                    if not current:
                        raise RuntimeError("video metadata not found")

                    new_title = str(row["new_title"] or "").strip()
                    description = str(row["description"] or "").strip()
                    chapters = str(row["chapters"] or "").strip()
                    tags = [
                        str(item).strip()
                        for item in json.loads(row["tags_json"] or "[]")
                        if str(item).strip()
                    ]
                    variants = [
                        str(item).strip()
                        for item in json.loads(
                            row["title_variants_json"] or "[]"
                        )
                        if str(item).strip()
                    ]

                    sanitized = sanitize_imported_package_description(
                        description,
                        new_title,
                    )
                    description = sanitized.after
                    check = validate_content_package(
                        new_title,
                        description,
                        chapters,
                        tags,
                        variants,
                    )
                    if check.errors:
                        raise RuntimeError(
                            "package validation: " + "; ".join(check.errors)
                        )
                    final_description = compose_description(
                        description,
                        chapters,
                    )
                    if len(final_description) > 5000:
                        raise RuntimeError(
                            f"final description is {len(final_description)} chars"
                        )

                    snippet = current.get("snippet", {}) or {}
                    current_title = str(snippet.get("title") or "")
                    current_description = str(
                        snippet.get("description") or ""
                    )
                    current_tags = list(snippet.get("tags") or [])

                    history_id = save_metadata_snapshot(
                        conn,
                        video_id,
                        current_title,
                        current_description,
                        current_tags,
                        "before_scheduled_package_batch",
                    )

                    fresh_budget = quota_budget_status(conn)
                    if int(fresh_budget["spendable"]) < VIDEO_UPDATE_COST:
                        raise RuntimeError(
                            "protected quota reserve reached"
                        )

                    client.update_video(
                        video_id,
                        title=new_title,
                        description=final_description,
                        tags=tags,
                    )
                    record_quota_units(
                        conn,
                        VIDEO_UPDATE_COST,
                        purpose="video",
                    )
                    prepared_by_id[video_id] = {
                        "profile": profile,
                        "title": new_title,
                        "description": final_description,
                        "tags": tags,
                        "history_id": history_id,
                    }
                    changed_ids.append(video_id)
                except Exception as exc:
                    if "quotaexceeded" in str(exc).casefold():
                        mark_quota_exhausted(conn)
                    errors.append(f"{video_id}: {exc}")
                    if "quota" in str(exc).casefold():
                        break

        verified = 0
        verified_ids: list[str] = []
        for profile in sorted(
            {item["profile"] for item in prepared_by_id.values()}
        ):
            ids = [
                video_id
                for video_id, item in prepared_by_id.items()
                if item["profile"] == profile
            ]
            client = YouTubeClient(profile=profile)
            client.credentials()
            items, requests = client.video_details_with_request_count(ids)
            record_quota_units(
                conn,
                int(requests) * READ_REQUEST_COST,
                purpose="service",
            )
            actual = {
                str(item.get("id") or ""): item
                for item in items
            }
            for video_id in ids:
                expected = prepared_by_id[video_id]
                item = actual.get(video_id)
                if not item:
                    errors.append(
                        f"{video_id}: final verification missing video"
                    )
                    continue
                snippet = item.get("snippet", {}) or {}
                title_ok = (
                    str(snippet.get("title") or "") == expected["title"]
                )
                description_ok = (
                    str(snippet.get("description") or "")
                    == expected["description"]
                )
                returned_tags = list(snippet.get("tags") or [])
                expected_tags = list(expected["tags"])
                tags_ok = sorted(
                    returned_tags,
                    key=str.casefold,
                ) == sorted(
                    expected_tags,
                    key=str.casefold,
                )
                if not (title_ok and description_ok and tags_ok):
                    errors.append(
                        f"{video_id}: verification mismatch "
                        f"title={title_ok} description={description_ok} "
                        f"tags={tags_ok}"
                    )
                    continue

                set_optimization_draft_status(
                    conn,
                    video_id,
                    "applied",
                )
                record_optimization_event(
                    conn,
                    history_id=expected["history_id"],
                    video_id=video_id,
                    profile=profile,
                    reason="scheduled_package_batch",
                    changed_fields="назва + опис + теги",
                )
                verified += 1
                verified_ids.append(video_id)

        log_action(
            conn,
            profile="main",
            category="заплановані",
            action="Пакет застосовано",
            details=(
                f"готових {len(rows)}; записано {len(changed_ids)}; "
                f"перевірено {verified}; помилок {len(errors)}; "
                f"резерв {budget['reserve']}"
            ),
        )
        after_units = today_quota_units(conn)
        return {
            "ready_found": len(rows),
            "changed": len(changed_ids),
            "verified": verified,
            "verified_ids": verified_ids,
            "errors": errors,
            "backup": str(backup_path),
            "youtube_api_units_tracked": max(
                0,
                after_units - before_units,
            ),
            "quota_after": quota_budget_status(conn),
        }
    finally:
        conn.close()


def inspect_ready_scheduled_mismatches() -> dict:
    """Read actual metadata for scheduled drafts still marked ready after a write."""
    from rg_youtube_control.db import connect
    from rg_youtube_control.optimization import (
        compose_description,
        sanitize_imported_package_description,
    )
    from rg_youtube_control.service import (
        READ_REQUEST_COST,
        record_quota_units,
        today_quota_units,
    )
    from rg_youtube_control.youtube_api import YouTubeClient

    conn = connect(_db_path())
    try:
        rows = conn.execute(
            """SELECT v.video_id,v.profile,v.title,
                      d.new_title,d.description,d.chapters,d.tags_json
               FROM videos v
               JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.scheduled_publish_at IS NOT NULL
                 AND d.status='ready'
               ORDER BY v.scheduled_publish_at ASC"""
        ).fetchall()
        before = today_quota_units(conn)
        result = []
        by_profile: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_profile.setdefault(str(row["profile"] or "main"), []).append(row)

        for profile, profile_rows in by_profile.items():
            client = YouTubeClient(profile=profile)
            client.credentials()
            ids = [str(row["video_id"]) for row in profile_rows]
            items, requests = client.video_details_with_request_count(ids)
            record_quota_units(
                conn,
                int(requests) * READ_REQUEST_COST,
                purpose="service",
            )
            actual = {str(item.get("id") or ""): item for item in items}
            for row in profile_rows:
                video_id = str(row["video_id"])
                item = actual.get(video_id, {})
                snippet = item.get("snippet", {}) or {}
                expected_title = str(row["new_title"] or "").strip()
                expected_description = sanitize_imported_package_description(
                    str(row["description"] or "").strip(),
                    expected_title,
                ).after
                expected_description = compose_description(
                    expected_description,
                    str(row["chapters"] or "").strip(),
                )
                expected_tags = [
                    str(x).strip()
                    for x in json.loads(row["tags_json"] or "[]")
                    if str(x).strip()
                ]
                actual_title = str(snippet.get("title") or "")
                actual_description = str(snippet.get("description") or "")
                actual_tags = list(snippet.get("tags") or [])
                result.append({
                    "video_id": video_id,
                    "title_match": actual_title == expected_title,
                    "description_match": actual_description == expected_description,
                    "expected_description_chars": len(expected_description),
                    "actual_description_chars": len(actual_description),
                    "expected_description": expected_description,
                    "actual_description": actual_description,
                    "expected_tags": expected_tags,
                    "actual_tags": actual_tags,
                    "tags_match_casefold_set": {
                        str(x).casefold() for x in expected_tags
                    } == {
                        str(x).casefold() for x in actual_tags
                    },
                })
        after = today_quota_units(conn)
        return {
            "youtube_api_units_tracked": max(0, after - before),
            "ready_count": len(rows),
            "items": result,
        }
    finally:
        conn.close()

def set_vidiq_budget_state(task: dict) -> dict:
    """Sync the local shared vidIQ counter from an external balance check."""
    from rg_youtube_control.db import connect, log_action
    from rg_youtube_control.vidiq_budget import sync_external_balance

    args = task.get("args") or {}
    limit = int(args.get("max_renewable_credits") or 2000)
    renewable = int(args.get("renewable_credits") or 0)
    add_on = int(args.get("add_on_credits") or 0)
    reset_at = str(args.get("reset_at") or "").strip()
    plan = str(args.get("plan") or "AIR Boost").strip()

    conn = connect(_db_path())
    try:
        status = sync_external_balance(
            conn,
            max_renewable_credits=limit,
            renewable_credits=renewable,
            reset_at=reset_at,
            add_on_credits=add_on,
            plan=plan,
        )
        log_action(
            conn,
            profile="main",
            category="vidIQ",
            action="Синхронізація балансу",
            details=(
                f"{status.used}/{status.limit} використано; "
                f"залишок {status.remaining}; reset {status.reset_at}"
            ),
        )
        return {
            "youtube_api_calls": 0,
            "plan": status.plan,
            "limit": status.limit,
            "used": status.used,
            "remaining": status.remaining,
            "reserve": status.reserve,
            "reset_at": status.reset_at,
        }
    finally:
        conn.close()


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
    elif action == "youtube_local_stop_legacy_gui":
        result = stop_legacy_installed_gui()
    elif action == "youtube_local_sync_and_launch_source":
        result = sync_and_launch_source()
    elif action == "youtube_local_launch_diagnostic":
        result = launch_diagnostic()
    elif action == "youtube_local_sync_recent_live_for_today":
        result = sync_recent_live_for_today()
    elif action == "youtube_local_find_today_upcoming_live_broadcasts":
        result = find_today_upcoming_live_broadcasts()
    elif action == "youtube_local_optimize_scheduled_stream":
        result = optimize_scheduled_stream(task)
    elif action == "youtube_local_verify_stream901_partial_update":
        result = verify_stream_901_after_partial_update()
    elif action == "youtube_local_finalize_stream901":
        result = finalize_stream_901_local_state()
    elif action == "youtube_local_ensure_gui_startup":
        result = ensure_gui_startup()
    elif action == "youtube_local_brand_shortcuts":
        result = brand_shortcuts()
    elif action == "youtube_local_prepare_source_runtime":
        result = prepare_source_runtime()
    elif action == "youtube_local_cleanup_gui_processes":
        result = cleanup_gui_processes()
    elif action == "youtube_local_enable_archive_priority":
        result = enable_archive_priority_campaign()
    elif action == "youtube_local_apply_ready_scheduled_batch":
        result = apply_ready_scheduled_batch()
    elif action == "youtube_local_inspect_scheduled_mismatches":
        result = inspect_ready_scheduled_mismatches()
    elif action == "youtube_local_set_vidiq_budget_state":
        result = set_vidiq_budget_state(task)
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
