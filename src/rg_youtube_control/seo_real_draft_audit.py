"""Read-only offline audit of existing SEO drafts and verified timeline evidence.

Reads a SQLite DB in immutable/query-only mode; never sends YouTube requests,
downloads models, changes drafts or recurses into multi-TB media folders.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path
from rg_youtube_control.seo_intelligence import audit_batch


def run(db_path: Path, evidence_dir: Path, *, max_videos: int = 30) -> dict:
    if not db_path.is_file():
        raise FileNotFoundError(f"missing_database: {db_path}")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    packages = []
    skipped = []
    with sqlite3.connect(uri, uri=True, timeout=20) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            """SELECT d.video_id, v.title AS title, d.description, d.tags_json
               FROM optimization_drafts d
               JOIN videos v ON v.video_id=d.video_id
               WHERE v.profile IN ('main','live')
               ORDER BY d.video_id LIMIT ?""", (max_videos,)
        ).fetchall()
    for row in rows:
        vid = str(row["video_id"])
        evidence_file = evidence_dir / (vid + ".json")
        if not evidence_file.is_file():
            skipped.append({"video_id": vid, "reason": "verified_evidence_missing"})
            continue
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
        topics = [
            str(topic.get("topic") or "").strip()
            for block in evidence.get("blocks") or []
            for topic in block.get("topics") or []
            if isinstance(topic, dict) and str(topic.get("evidence") or "").strip()
        ]
        if not topics:
            skipped.append({"video_id": vid, "reason": "no_quoted_topics"})
            continue
        packages.append({
            "video_id": vid,
            "evidence_topics": topics,
            # Existing draft is treated as one title, never fabricate A/B variants.
            "title_variants": [str(row["title"] or "")],
            "description": str(row["description"] or ""),
            "tags": json.loads(row["tags_json"] or "[]"),
        })
    audit = audit_batch(packages)
    cache_dir = evidence_dir.parent / "seo_evidence_cache"
    cache_present = cache_dir.is_dir()
    cache_files_sample = sum(1 for _ in __import__("itertools").islice(cache_dir.glob("*.json"), 1001)) if cache_present else 0
    return {"schema": "RG_REAL_DRAFT_AUDIT_V2", "read_only": True,
            "evidence_lookup": "per_video_report",
            "block_cache_present": cache_present,
            "block_cache_files_sample": cache_files_sample,
            "block_cache_hashed_not_video_indexed": True,
            "youtube_writes": 0, "database_writes": 0,
            "inspected": len(rows), "audited": len(packages), "skipped": skipped,
            "audit": audit}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--max-videos", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.database, args.evidence, max_videos=args.max_videos)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
