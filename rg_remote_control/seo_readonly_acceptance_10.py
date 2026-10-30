"""Ten real-video SEO acceptance on the creator's existing Windows machine.

READ-ONLY: opens the app's SQLite database with mode=ro/query_only and
reads only configured NAS SRT files. It neither imports drafts nor calls any
YouTube endpoint. QA caches/reports live exclusively in RUNNER_TEMP.

Passing this machine check means *structurally eligible for human review*.
It never means the titles are approved, or that content was published.
"""
from __future__ import annotations

import argparse
import time as _wall_clock
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rg_youtube_control.config import DEFAULT_NAS_TRANSCRIPTS_PATH
from rg_youtube_control.dialogue_seo import (ab_title_issues,
                                              analyze_all_timeline_blocks,
                                              evidence_outline_text)
from rg_youtube_control.free_tools import (DEFAULT_OLLAMA_MODEL,
                                           generate_seo_package_local,
                                           load_srt_transcript, ollama_chat,
                                           fetch_transcript, _description_quality_error)
def _incidental_ab_quote(title: str) -> bool:
    """Reject incidental pleasantries and appearance-based SEO headlines."""
    text = " ".join(str(title or "").casefold().split())
    return bool(re.search(
        r"(?:\bкак\s+дела\b|\bкак\s+поживаете\b|"
        r"\bпривет(?:ствую)?\b|\bздравствуй(?:те)?\b|"
        r"\bдо\s+свидания\b|\bспасибо\s+за\s+(?:разговор|беседу)\b|"
        r"\bяк\s+справи\b|\bдякую\s+за\s+розмову\b|"
        r"\b(?:выглядишь|выглядите|виглядаєш|виглядаєте)\b|"
        r"\b(?:красивый|красивая|красивые|красивий|красива|гарна|гарний)\b|"
        r"\b(?:внешность|зовнішність)\b|"
        r"\b(?:твои|ваши|твої|ваші)\s+(?:глаза|волосы|очі|волосся)\b)",
        text,
    ))
from rg_youtube_control.optimization import safe_description_fix

MAIN_IDS = (
    "MEitKm687xo", "u9y_f4HtEbQ", "dmDUcD1unbM",
    "MClldsur_0s", "ZstT-QQyacA", "LM0vkW9YoKg",
    "GQL6N4jQpI8", "-Bu_aDIvEs4", "mdPMyIy5A70",
    "DywWeHtnuhM",
)
LIVE_IDS = ("4ItkxMPI1GA", "fdHXrCyw3Lw")
VALID_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# In-process only, bounded by the selected batch. Public subtitles fetched
# during the read-only preflight must be reused by the exact same video ID.
# Without this cache the second request can be rate-limited, wasting the
# successful preflight and producing false PUBLIC_CAPTIONS_UNAVAILABLE.
_PREFLIGHT_PUBLIC_CAPTIONS: dict[str, list[dict]] = {}

def _private_caption_file(cache_dir: Path, video_id: str) -> Path:
    if not VALID_ID.fullmatch(video_id):
        raise ValueError("Invalid video ID for public caption cache")
    return Path(cache_dir) / (video_id + ".json")


def _read_private_caption_cache(
    cache_dir: Path | None, video_id: str, duration: int,
) -> list[dict]:
    """Read *public* captions from a private runner-only cache, max 14 days.

    Never use a caption file for a different video ID. The cache is opt-in,
    disabled in production and outside the checked-out GitHub repository.
    """
    if cache_dir is None:
        return []
    path = _private_caption_file(cache_dir, video_id)
    try:
        if not path.is_file() or path.stat().st_size > 6_000_000:
            return []
        record = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict)
                or record.get("video_id") != video_id
                or record.get("source") != "public_captions"
                or not (0 <= _wall_clock.time() - float(record.get("created", 0)) <= 14 * 86400)):
            return []
        rows = record.get("rows")
        if not isinstance(rows, list) or len(rows) < 10 or len(rows) > 50_000:
            return []
        if any(not isinstance(row, dict)
               or not isinstance(row.get("text"), str)
               or len(row["text"]) > 5000
               for row in rows):
            return []
        if duration > 0 and max(
            float(row.get("start") or 0) + float(row.get("duration") or 0)
            for row in rows
        ) < duration * 0.75:
            return []
        return rows
    except (OSError, TypeError, ValueError, OverflowError, KeyError, json.JSONDecodeError):
        return []


def _write_private_caption_cache(
    cache_dir: Path | None, video_id: str, rows: list[dict],
) -> None:
    """Keep successful public source fetches private; never cache NAS SRT."""
    if cache_dir is None or len(rows) < 10:
        return
    path = _private_caption_file(cache_dir, video_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "video_id": video_id,
            "source": "public_captions",
            "created": _wall_clock.time(),
            "rows": rows,
        }
        content = json.dumps(record, ensure_ascii=False)
        if len(content.encode("utf-8")) > 6_000_000:
            return
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except (OSError, ValueError, TypeError):
        pass



_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def _duration_seconds(value: object) -> int:
    """YouTube videos.duration uses ISO 8601 (PT1H2M3S), not integer seconds."""
    text = str(value or "").strip()
    if not text:
        return 0
    if text.isdecimal():
        return int(text)
    # Legacy builds save MM:SS or HH:MM:SS.
    if re.fullmatch(r"\d{1,4}:[0-5]?\d(?::[0-5]?\d)?", text):
        seconds = 0
        for part in text.split(":"):
            seconds = seconds * 60 + int(part)
        return seconds
    match = _DURATION.fullmatch(text)
    if match is None:
        raise ValueError("Invalid synchronized duration format")
    units = {key: float(amount or 0) for key, amount in match.groupdict().items()}
    return round(
        units["days"] * 86400 + units["hours"] * 3600
        + units["minutes"] * 60 + units["seconds"]
    )



def get_video_inputs(db_file: Path, video_id: str) -> dict:
    """Read public metadata + NAS configuration with no SQLite mutations."""
    if not VALID_ID.fullmatch(video_id):
        raise ValueError("Invalid video ID")
    uri = db_file.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=12) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        row = db.execute(
            "SELECT video_id,profile,title,duration FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Video ID not present in app's synchronized database")
        setting = db.execute(
            "SELECT value FROM settings WHERE key='nas_transcripts_path'"
        ).fetchone()
        configured = str(setting["value"] or "").strip() if setting else ""
        return {
            "video_id": video_id,
            "profile": str(row["profile"] or ""),
            "title": str(row["title"] or ""),
            "duration": _duration_seconds(row["duration"]),
            "transcript_root": configured or DEFAULT_NAS_TRANSCRIPTS_PATH,
        }


def _safe_error_code(exc: Exception) -> str:
    """Bounded SEO failure class without leaking private captions or drafts."""
    message = str(exc).casefold()
    cases = (
        ("need at least 8 grounded tags", "TAGS_INSUFFICIENT"),
        ("need exactly 3 title variants", "AB_VARIANTS_INCOMPLETE"),
        ("grounded description failed final check", "DESCRIPTION_GROUNDING_FAILED"),
        ("description quality failed", "DESCRIPTION_QUALITY_FAILED"),
        ("missing description", "DESCRIPTION_MISSING"),
        ("missing title", "TITLE_MISSING"),
        ("no evidence-backed dialogue blocks", "EVIDENCE_MISSING"),
        ("локальна seo-генерація не пройшла валідацію", "LOCAL_SEO_VALIDATION_FAILED"),
    )
    for fragment, code in cases:
        if fragment in message:
            if code == "LOCAL_SEO_VALIDATION_FAILED":
                for nested_fragment, nested_code in cases[:-1]:
                    if nested_fragment in message:
                        return nested_code
            return code
    return "LOCAL_SEO_OTHER_ERROR"


def run_one(
    video_id: str,
    *,
    database: Path,
    qa_cache: Path,
    model: str = DEFAULT_OLLAMA_MODEL,
    allow_public_captions: bool = False,
    private_caption_cache: Path | None = None,
) -> dict:
    started = time.monotonic()
    stage = "source_metadata"
    result = {
        "video_id": video_id,
        "status": "BLOCKED",
        "youtube_api_calls": 0,
        "youtube_writes": 0,
        "production_db_writes": 0,
        "production_draft_writes": 0,
        "review_required": True,
    }
    try:
        metadata = get_video_inputs(database, video_id)
        result["profile"] = metadata["profile"]
        title = metadata["title"]
        if not title:
            raise RuntimeError("Video metadata has no title")
        folder = Path(metadata["transcript_root"])
        srt = folder / (video_id + ".srt")
        stage = "transcript_fetch"
        result["srt_present"] = srt.is_file()
        duration = metadata["duration"]

        def valid_captions(cues: list[dict]) -> bool:
            if len(cues) < 10:
                return False
            end = max(
                float(row.get("start") or 0) + float(row.get("duration") or 0)
                for row in cues
            )
            return not (duration > 0 and end < duration * 0.75)

        rows: list[dict] = []
        if srt.is_file():
            result["transcript_source"] = "local_srt"
            try:
                rows = load_srt_transcript(srt)
            except (OSError, ValueError, RuntimeError, UnicodeError):
                if not allow_public_captions:
                    raise
                result["local_srt_unusable"] = True
            if rows and not valid_captions(rows) and allow_public_captions:
                result["local_srt_unusable"] = True
                rows = []
        if not rows and allow_public_captions:
            # Public captions are obtained only for this exact video ID;
            # no cookies, videos or production database writes.
            result["transcript_source"] = "public_captions"
            cached = _PREFLIGHT_PUBLIC_CAPTIONS.pop(video_id, None)
            if cached is None:
                cached = _read_private_caption_cache(
                    private_caption_cache, video_id, duration,
                ) or None
            if cached is not None:
                rows = cached
                result["caption_cache_reused"] = True
                result["caption_preflight_reused"] = True
                result["public_caption_reads"] = 0
            else:
                result["public_caption_reads"] = 1
                rows = fetch_transcript(video_id)
                if valid_captions(rows):
                    _write_private_caption_cache(private_caption_cache, video_id, rows)
        if not rows and not allow_public_captions and not srt.is_file():
            raise RuntimeError("NAS SRT missing; no YouTube fallback is allowed in QA")
        if len(rows) < 10:
            raise RuntimeError("Incomplete transcript: fewer than ten caption rows")
        last_second = max(
            float(row.get("start") or 0) + float(row.get("duration") or 0)
            for row in rows
        )
        if duration > 0 and last_second < duration * 0.75:
            raise RuntimeError("Transcript coverage below 75% of synchronized duration")
        stage = "evidence_analysis"
        report = analyze_all_timeline_blocks(
            rows,
            model=model,
            chat=ollama_chat,
            cache_dir=qa_cache / video_id,
            timeout=180.0,
        )
        blocks = int(report.get("blocks_total") or 0)
        grounded = int(report.get("blocks_with_evidence") or 0)
        result.update(
            {
                "srt_cues": len(rows),
                "video_duration_seconds": duration,
                "last_caption_second": round(last_second, 1),
                "timeline_blocks": blocks,
                "grounded_blocks": grounded,
                "evidence_cache_hits": int(report.get("cache_hits") or 0),
            }
        )
        if grounded == 0:
            raise RuntimeError("No evidence-backed dialogue blocks")
        # Diagnostic counts only: never upload private quotations, SRT text,
        # model titles or topic names into GitHub job logs. Distinguish real
        # source insufficiency from an A/B fallback integration failure.
        from rg_youtube_control.source_ab_lexical import (
            _grounded_labels, source_grounded_ukrainian_ab,
        )
        recognized_subjects = set()
        verified_quote_count = 0
        for block in report.get("blocks") or []:
            if not isinstance(block, dict) or block.get("verified") is False:
                continue
            for topic in block.get("topics") or []:
                if not isinstance(topic, dict):
                    continue
                quote = str(topic.get("evidence") or "").strip()
                if not quote:
                    continue
                verified_quote_count += 1
                recognized_subjects.update(_grounded_labels(quote))
        safe_ab_diag = {}
        safe_ab = source_grounded_ukrainian_ab(
            report, title, diagnostics=safe_ab_diag,
        )
        result["source_quote_count"] = verified_quote_count
        result["recognized_source_subject_count"] = len(recognized_subjects)
        result["deterministic_ab_ready"] = len(safe_ab) == 3
        # Safe-only counts and error-code buckets, never evidence text.
        result["source_ab_diagnostics"] = safe_ab_diag
        stage = "seo_generation"
        package = generate_seo_package_local(
            current_title=title,
            current_description="",
            current_tags=[],
            transcript=evidence_outline_text(report),
            public_context={"title": title, "duration": duration, "profile": metadata["profile"]},
            model=model,
            is_short=duration <= 70,
            fast_mode=False,
            timeout=240.0,
            evidence_report=report,
        )
        main = str(package.get("title") or "")
        ab = list(package.get("title_variants") or [])
        description = str(package.get("description") or "")
        tags = list(package.get("tags") or [])
        stage = "editorial_quality_gate"
        issues = ab_title_issues(ab, report) if ab else ["Missing A/B titles"]
        quality = _description_quality_error(
            description, evidence_outline_text(report), max_chars=950
        )
        preview = safe_description_fix(description, main).after
        conditions = {
            "three_ab_titles": len(ab) == 3,
            "ab_grounded": not issues,
            "no_incidental_headlines": not any(
                _incidental_ab_quote(t) for t in [main] + ab
            ),
            "description_quality": not quality,
            "eight_tags": len(tags) >= 8,
            "full_timeline_with_evidence": grounded == blocks,
            "channel_links": "links.rginfoua.pp.ua" in preview,
            "donation_links": "donate.rginfoua.pp.ua" in preview,
            "live_has_no_chapters": (
                str(metadata["profile"]).casefold() not in
                {"live", "livestream", "stream"}
                or not str(package.get("chapters") or "").strip()
            ),
        }
        result.update({
            "checks": conditions,
            "ab_issue_count": len(issues),
            # Only bounded diagnostic codes. Never export generated titles,
            # transcript excerpts or NAS paths to GitHub Actions logs.
            "ab_issue_categories": sorted({
                "unsupported_topic" if "непідтверджен" in issue or "підтверджених тематичних" in issue or "дослівні цитати" in issue
                else "duplicated_hook" if "повторюють" in issue or "сюжетну опору" in issue
                else "asr_noise" if "розпізнавання" in issue
                else "generic_hook" if "надто загальний" in issue or "загальною реплікою" in issue
                else "title_length_or_count" if "20-100" in issue or "рівно 3" in issue
                else "other"
                for issue in issues
            }),
            "ungrounded_block_count": max(0, blocks - grounded),
            "ab_count": len(ab),
            "tags_count": len(tags),
            "description_length": len(description),
            "flagged_topic_count": len(package.get(
                "evidence_editorial_review") or []),
            "status": (
                "DRAFT_READY_FOR_HUMAN_REVIEW"
                if all(conditions.values())
                else "NEEDS_REVIEW"
            ),
        })
    except Exception as exc:
        # The result is uploaded as a CI artifact. Never echo captions,
        # a local NAS path, an Ollama response or an exception containing
        # someone else's words into that public/private GitHub artifact.
        known = (
            "Invalid video ID",
            "Video ID not present in app's synchronized database",
            "Video metadata has no title",
            "NAS SRT missing; no YouTube fallback is allowed in QA",
            "Incomplete SRT: fewer than ten caption rows",
            "SRT coverage below 75% of synchronized video duration",
            "No evidence-backed dialogue blocks",
            "Invalid synchronized duration format",
        )
        message = str(exc)
        result["error_type"] = type(exc).__name__
        result["error_stage"] = stage
        result["error_code"] = (
            "PUBLIC_CAPTIONS_UNAVAILABLE"
            if stage == "transcript_fetch" and result.get("transcript_source") == "public_captions"
            else "LOCAL_TRANSCRIPT_INVALID"
            if stage == "transcript_fetch" and result.get("transcript_source") == "local_srt"
            else _safe_error_code(exc)
        )
        if message == "Invalid synchronized duration format":
            # Report format metadata only, never the actual database field.
            try:
                with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
                    raw = db.execute("SELECT duration FROM videos WHERE video_id=?", (video_id,)).fetchone()
                value = str(raw[0] or "") if raw else ""
                result["duration_shape"] = (
                    "colon" if ":" in value else
                    "iso8601" if value.upper().startswith("P") else
                    "number" if value.replace(".", "", 1).isdigit() else
                    "other"
                )
                result["duration_char_count"] = len(value)
            except Exception:
                pass
        result["error"] = (
            message if message in known
            else "Local content-validation or dependency failure; "
                 "review details on the source machine"
        )
    result["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return result


def select_existing_srt_videos(
    db_file: Path, profile: str, limit: int,
    preferred: tuple[str, ...] = (),
    allow_public_captions: bool = False,
    preflight_captions: bool = False,
    private_caption_cache: Path | None = None,
) -> list[str]:
    """Select same-ID subtitles, optionally proving access before costly SEO.

    Local DB is strictly query-only; no caption bytes or filenames are
    uploaded. Public subtitle reads have no YouTube Data API quota.
    """
    if not 1 <= limit <= 20 or profile not in {"main", "live"}:
        raise ValueError("Invalid source selection")
    uri = db_file.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=12) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        setting = db.execute(
            "SELECT value FROM settings WHERE key='nas_transcripts_path'"
        ).fetchone()
        configured = str(setting["value"] or "").strip() if setting else ""
        root = Path(configured or DEFAULT_NAS_TRANSCRIPTS_PATH)
        rows = db.execute(
            """SELECT video_id,duration
               FROM videos
               WHERE profile=? AND scheduled_publish_at IS NULL
                 AND COALESCE(privacy_status,'public')='public'
               ORDER BY COALESCE(views,0) DESC, video_id
               LIMIT 2000""",
            (profile,),
        ).fetchall()

    preferred_set = {vid: index for index, vid in enumerate(preferred)}
    ordered = sorted(
        rows,
        key=lambda row: (
            0 if (root / (str(row["video_id"] or "") + ".srt")).is_file() else 1,
            preferred_set.get(str(row["video_id"] or ""), len(preferred)),
        ),
    )
    chosen: list[str] = []
    for row in ordered[:max(30, limit * 5)]:
        video_id = str(row["video_id"] or "")
        if not VALID_ID.fullmatch(video_id):
            continue
        try:
            duration = _duration_seconds(row["duration"])
        except (ValueError, TypeError):
            continue
        if 0 < duration <= 70:
            continue
        local = root / (video_id + ".srt")
        if not local.is_file() and not allow_public_captions:
            continue
        if preflight_captions:
            cues: list[dict] = []
            if local.is_file():
                try:
                    cues = load_srt_transcript(local)
                except (OSError, ValueError, RuntimeError, UnicodeError):
                    cues = []
            def covers(candidates: list[dict]) -> bool:
                return (
                    len(candidates) >= 10
                    and (duration <= 0 or max(
                        float(item.get("start") or 0)
                        + float(item.get("duration") or 0)
                        for item in candidates
                    ) >= duration * 0.75)
                )
            source_was_public = False
            freshly_fetched = False
            if not covers(cues) and allow_public_captions:
                cues = _read_private_caption_cache(
                    private_caption_cache, video_id, duration,
                )
                source_was_public = covers(cues)
                if not source_was_public:
                    try:
                        cues = fetch_transcript(video_id)
                        source_was_public = True
                        freshly_fetched = True
                    except Exception:
                        continue  # unreadable public captions: try next real video
            if not covers(cues):
                continue
            if source_was_public:
                # Public-only: in-memory for this job and optional private
                # cache for future read-only QA runs. Never NAS or GitHub.
                _PREFLIGHT_PUBLIC_CAPTIONS[video_id] = cues
                if freshly_fetched:
                    _write_private_caption_cache(
                        private_caption_cache, video_id, cues,
                    )
        chosen.append(video_id)
        if len(chosen) >= limit:
            break
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-ids", nargs="+", default=list(MAIN_IDS))
    parser.add_argument("--auto-main", type=int, default=0)
    parser.add_argument("--auto-live", type=int, default=0)
    parser.add_argument(
        "--allow-public-captions", action="store_true",
        help="Public subtitle reads only, zero YouTube Data API quota; never write",
    )
    parser.add_argument(
        "--preflight-captions", action="store_true",
        help="Verify source caption coverage before accepting each video",
    )
    parser.add_argument(
        "--private-caption-cache", type=Path, default=None,
        help="Opt-in private runner-only cache for public captions (14 days); no production writes",
    )
    parser.add_argument("--db", type=Path, default=(
        Path(os.environ.get("LOCALAPPDATA", ".")) /
        "RGYouTubeControl" / "rg_youtube_control.db"
    ))
    parser.add_argument(
        "--output", type=Path,
        default=Path(os.environ.get("RUNNER_TEMP", ".")) / "rg_seo_qa_summary.json",
    )
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    args = parser.parse_args(argv)
    # Reuse only hashed, verified evidence per exact transcript and model in
    # the optional private runner QA directory. Never store in the working
    # GitHub checkout or touch the app's production SQLite database.
    qa_cache = (
        args.private_caption_cache.parent / "seo_qa_verified_evidence"
        if args.private_caption_cache is not None
        else Path(os.environ.get("RUNNER_TEMP", ".")) / "rg_seo_qa_cache"
    )
    # Accept both separate IDs and a comma-delimited batch. The CSV form
    # avoids argparse treating valid YouTube IDs starting with '-' as options.
    video_ids = [
        item.strip() for group in args.video_ids
        for item in str(group).split(",") if item.strip()
    ]
    auto_requested = args.auto_main + args.auto_live
    if args.auto_main or args.auto_live:
        if not (0 <= args.auto_main <= 20 and 0 <= args.auto_live <= 20
                and 1 <= auto_requested <= 25):
            parser.error("Invalid automatic source selection size")
        video_ids = (
            (select_existing_srt_videos(
                args.db, "main", args.auto_main, MAIN_IDS,
                allow_public_captions=args.allow_public_captions,
                preflight_captions=args.preflight_captions,
                private_caption_cache=args.private_caption_cache,
            ) if args.auto_main else [])
            + (select_existing_srt_videos(
                args.db, "live", args.auto_live, LIVE_IDS,
                allow_public_captions=args.allow_public_captions,
                preflight_captions=args.preflight_captions,
                private_caption_cache=args.private_caption_cache,
            ) if args.auto_live else [])
        )
    if not video_ids and not auto_requested:
        parser.error("Expected at least one video ID")
    if len(video_ids) > 25 or len(set(video_ids)) != len(video_ids):
        parser.error("Expected at most 25 unique video IDs")
    if any(not VALID_ID.fullmatch(video_id) for video_id in video_ids):
        parser.error("Invalid video ID in input batch")
    checked = []
    for video_id in video_ids:
        checked.append(run_one(
            video_id, database=args.db, qa_cache=qa_cache, model=args.model,
            allow_public_captions=args.allow_public_captions,
            private_caption_cache=args.private_caption_cache,
        ))
    status = "READY_FOR_HUMAN_REVIEW" if (
        checked and (not auto_requested or len(checked) == auto_requested)
        and all(row["status"] == "DRAFT_READY_FOR_HUMAN_REVIEW" for row in checked)
    ) else "BLOCKED"
    summary = {
        "schema": "RG_SEO_REAL_READONLY_ACCEPTANCE_V1",
        "status": status,
        "read_only": True,
        "video_count": len(checked),
        "requested_video_count": auto_requested or len(checked),
        "source_shortfall_count": max(0, auto_requested - len(checked)),
        "results": checked,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=True), flush=True)
    return 0 if status == "READY_FOR_HUMAN_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
