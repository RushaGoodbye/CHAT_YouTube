#!/usr/bin/env python3
"""NEWS2 hotfix canonical project footer, excluding pinned V6.
No Telegram calls, public sends, process restarts or pinned release edits.
"""
import ast
import datetime
import json
import os
import pathlib
import re
import sys
import tarfile
import tempfile

ROOT = pathlib.Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP = ROOT / 'operator'
PINNED = OP / 'news_rg_stability_releases_v1/pinned_release_v1.json'
GUARD = OP / 'news_rg_poll_moderation_v1.py'
KNOWN_GUARD_SHA = 'dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
OLD = 'УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ'
NEW = 'УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ РАША ГУДБАЙ'
TARGETS = (
    'news_rg_project_footer_v1.py',
    'news_rg_organic_post_v1.py',
    'news_rg_youtube_top_schedule_v1.py',
    'rg_shorts_v3.py',
    'news_rg_alert_24h_cleanup_v1.py',
)
PATTERN = re.compile(re.escape(OLD) + r'(?!\s+РАША\s+ГУДБАЙ)')
def output(**kwargs):
    print(json.dumps(kwargs, indent=2, ensure_ascii=False))
def safe(p):
    return p.is_file() and not p.is_symlink() and p.stat().st_size < 1500000
def digest(p):
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if not safe(PINNED) or not safe(GUARD):
        raise RuntimeError('PINNED_RELEASE_UNAVAILABLE')
    if digest(GUARD) != KNOWN_GUARD_SHA:
        raise RuntimeError('V6_GUARD_INTEGRITY_FAILED')
    manifest = json.loads(PINNED.read_text('utf8'))
    files = manifest.get('files')
    if not isinstance(files, dict) or files.get(GUARD.name) != KNOWN_GUARD_SHA:
        raise RuntimeError('PINNED_MANIFEST_INTEGRITY_FAILED')
    protected = {pathlib.Path(k).name for k in files.keys()}
    changes = []
    skipped_pinned = []
    checked = []
    for name in TARGETS:
        for parent in (ROOT, OP):
            p = parent / name
            if not safe(p):
                continue
            text = p.read_text('utf8')
            count = len(PATTERN.findall(text))
            checked.append(str(p.relative_to(ROOT)))
            if count == 0:
                continue
            if p.name in protected:
                skipped_pinned.append(str(p.relative_to(ROOT)))
                continue
            fixed = PATTERN.sub(NEW, text)
            ast.parse(fixed, filename=p.name)
            changes.append((p, text.encode('utf8'), fixed.encode('utf8'), count))
    # No partial work: halt if a live target is also pinned.
    if skipped_pinned:
        return output(status='SAFE_STOP_PINNED_PUBLISHER_REQUIRES_REPIN',
                      pinned_publishers=skipped_pinned,
                      files_examined=checked, files_modified=0,
                      v6_integrity='PASS', telegram_calls=0, publications=0)
    if not changes:
        return output(status='NO_OLD_FOOTER_IN_ACTIVE_SOURCES',
                      files_examined=checked, files_modified=0,
                      v6_integrity='PASS', telegram_calls=0, publications=0)
    folder = OP / 'cta_footer_backups'
    if folder.is_symlink():
        raise RuntimeError('UNSAFE_BACKUP_DIRECTORY')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive = folder / ('active_footer_before_' + stamp + '.tar.gz')
    if archive.exists() or archive.is_symlink():
        raise RuntimeError('BACKUP_ALREADY_EXISTS')
    with tarfile.open(archive, 'x:gz') as z:
        for p, original, fixed, count in changes:
            z.add(p, arcname=str(p.relative_to(ROOT)), recursive=False)
    os.chmod(archive, 0o600)
    done = []
    try:
        for p, original, fixed, count in changes:
            fd, temporary = tempfile.mkstemp(prefix='.rgcta_', dir=str(p.parent))
            try:
                os.fchmod(fd, p.stat().st_mode & 0o777)
                with os.fdopen(fd, 'wb') as out:
                    out.write(fixed)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temporary, p)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            done.append((p, original))
        if digest(GUARD) != KNOWN_GUARD_SHA:
            raise RuntimeError('GUARD_CHANGED_DURING_PATCH')
        for p, original, fixed, count in changes:
            if p.read_bytes() != fixed:
                raise RuntimeError('POST_WRITE_CONTENT_MISMATCH')
            ast.parse(p.read_text('utf8'), filename=p.name)
    except Exception:
        for p, original in done:
            p.write_bytes(original)
        raise
    return output(status='ACTIVE_FOOTER_PATCHED',
                  exact_footer=NEW,
                  link='https://links.rginfoua.pp.ua/',
                  existing_link_markup_preserved=True,
                  files_examined=checked,
                  files_patched=[{'file':str(p.relative_to(ROOT)),'old_occurrences':n} for p,_,_,n in changes],
                  backup=archive.name,
                  v6_integrity='PASS',
                  pinned_poll_module='UNCHANGED',
                  public_poll_reenabled=False,
                  live_publishing_smoke_test='NOT_PERFORMED',
                  telegram_calls=0,publications=0)
if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        output(status='CTA_SAFE_STOP', error_type=type(exc).__name__,
               public_poll_reenabled=False, telegram_calls=0,publications=0)
        sys.exit(2)
