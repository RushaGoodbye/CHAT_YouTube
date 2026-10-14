#!/usr/bin/env python3
"""Safely stage a photo-first moderation patch in the installed News2 module.

Default: dry run. Apply requires explicit --apply; backup is mandatory.
Does not call Telegram API, open gates, alter SQLite, or invoke getUpdates.
"""
from __future__ import annotations
import argparse
import datetime
import pathlib
import py_compile
import shutil
import tempfile

SOURCE = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2/rg_moderation.py")
REPLACEMENTS = (
    (
        "WHERE c.status='awaiting_moderation' AND c.photo_reviewed=1 AND d.candidate_id IS NULL",
        "WHERE c.status IN ('awaiting_moderation','awaiting_photo_review') AND d.candidate_id IS NULL",
    ),
    (
        "if item['status']!='awaiting_moderation' or item['photo_reviewed']!=1:",
        "if item['status'] not in ('awaiting_moderation','awaiting_photo_review'):",
    ),
    (
        'db.execute("UPDATE candidates SET status=?,updated_at=? WHERE id=? AND status=\'awaiting_moderation\' AND photo_reviewed=1",\n                           (status,rg_news.now(),key)).rowcount',
        'db.execute("UPDATE candidates SET status=?,photo_reviewed=CASE WHEN ?=\'approve\' THEN 1 ELSE photo_reviewed END,updated_at=? WHERE id=? AND status IN (\'awaiting_moderation\',\'awaiting_photo_review\')",\n                           (status,decision,rg_news.now(),key)).rowcount',
    ),
)

def patch(original: str) -> str:
    out = original
    for old, new in REPLACEMENTS:
        if out.count(old) != 1:
            raise ValueError("PATCH_ANCHOR_MISMATCH: abort without changes")
        out = out.replace(old, new, 1)
    compile(out, str(SOURCE), "exec")
    return out

def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("check", "apply"))
    args = p.parse_args()
    if not SOURCE.is_file() or SOURCE.is_symlink():
        raise SystemExit("BLOCKED: moderation module missing or symlinked")
    before = SOURCE.read_text("utf-8")
    after = patch(before)
    if args.mode == "check":
        print("PHOTO_FIRST_PATCH_CHECK_PASS; no files changed; no Telegram calls")
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = SOURCE.with_name("rg_moderation.py.pre_photo_first_" + stamp + ".bak")
    if backup.exists():
        raise SystemExit("BLOCKED: backup collision")
    shutil.copy2(SOURCE, backup)
    # Atomic write after mandatory backup.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=SOURCE.parent, prefix=".rg_moderation_", delete=False) as fp:
        temp_path = pathlib.Path(fp.name)
        fp.write(after)
    temp_path.chmod(SOURCE.stat().st_mode & 0o777)
    temp_path.replace(SOURCE)
    print("PHOTO_FIRST_PATCH_APPLIED; backup=" + str(backup))
    print("MODERATION_GATE_UNCHANGED; OWNER_UNCHANGED; PUBLISH_GATE_UNCHANGED")

if __name__ == "__main__":
    main()
