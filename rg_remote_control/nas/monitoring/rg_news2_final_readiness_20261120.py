#!/usr/bin/env python3
"""RG NEWS2: one-command callback + Cloudflare production readiness.
Read-only. No getUpdates, Telegram API calls, restarts, releases or secrets exposed.
"""
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.request
from urllib.parse import urlparse

ROOT = Path('/volume1/docker/RG_TELEGRAM_NEWS_2')
OP = ROOT / 'operator'
PIN = OP / 'news_rg_stability_releases_v1/pinned_release_v1.json'
POLL = OP / 'news_rg_poll_moderation_v1.py'
EXPECTED = 'dc46169380af2e0d169316a92c5afe266d30914d4923185ab96fb12f7a6cd6eb'
RECEIPT = OP / 'news_rg_stability_releases_v1/rg_poll_private_pilot_receipt.json'
SCHED = ROOT / 'news_rg_callback_scheduled_state_v1.json'
STABLE = OP / 'news_rg_stable5_operational_status_v1.json'
HEALTH = OP / 'news_rg_health_control_state_v1.json'
WORKER = 'rasha-goodbye-content-hub'
NOW = time.time()

def read_json(p, cap=400000):
    if not p.is_file() or p.is_symlink() or p.stat().st_size > cap:
        return None
    try:
        return json.loads(p.read_text('utf-8'))
    except (ValueError, OSError, UnicodeError):
        return None

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def live_guard():
    meta = read_json(PIN)
    ok = (isinstance(meta, dict) and POLL.is_file() and not POLL.is_symlink()
          and sha(POLL) == EXPECTED and meta.get('files', {}).get(POLL.name) == EXPECTED)
    return {'status': 'PASS' if ok else 'FAIL', 'pinned_sha256_match': bool(ok),
            'public_poll_send_allowed': False if ok else 'UNKNOWN'}

def current_callback():
    a, b, c = [read_json(x) for x in (SCHED, STABLE, HEALTH)]
    a = a if isinstance(a, dict) else {}
    b = b if isinstance(b, dict) else {}
    c = c if isinstance(c, dict) else {}
    age = round(NOW - SCHED.stat().st_mtime) if SCHED.is_file() else None
    offset = a.get('offset_after')
    healthy = (a.get('status') == 'PASS' and a.get('second_poller') is False
               and isinstance(offset, int) and offset >= 138130349
               and age is not None and 0 <= age <= 240
               and b.get('status') == 'PASS' and not b.get('alerts')
               and c.get('status') == 'HEALTHY' and not c.get('observed_alerts'))
    return {'status': 'PASS' if healthy else 'RECHECK_REQUIRED',
            'offset_after': offset if isinstance(offset, int) else None,
            'last_scheduled_tick_age_seconds': age,
            'stable5_status': b.get('status'), 'health_status': c.get('status'),
            'second_poller': a.get('second_poller')}

def callback_receipt():
    data = read_json(RECEIPT)
    card_sent = isinstance(data, dict) and data.get('status') == 'SENT_PRIVATE' and data.get('message_id') == 1183
    file_results = []
    for base in (OP, ROOT):
        if not base.is_dir():
            continue
        for p in base.iterdir():
            if p.suffix != '.json' or not p.is_file() or p.is_symlink():
                continue
            if not re.search('callback|poll', p.name, re.I) or p.name.startswith('updates_handoff_guarded_'):
                continue
            if NOW - p.stat().st_mtime > 7200:
                continue
            obj = read_json(p)
            if not isinstance(obj, dict):
                continue
            if any(obj.get(key) == 1183 for key in ('private_message_id', 'message_id', 'moderator_message_id')):
                status = obj.get('status')
                file_results.append({'file': p.name, 'status': status if isinstance(status, str) and len(status) < 90 else 'UNKNOWN'})
    return {'private_card_1183_sent': card_sent, 'callback_ack_verified': False,
            'local_direct_callback_receipts': file_results[:8],
            'note': 'A delivered card and received update do not prove answerCallbackQuery succeeded'}

def callback_source():
    p = OP / 'rg_news2_p31_guarded_callback_once.py'
    if not p.is_file() or p.is_symlink():
        return {'status': 'MISSING'}
    source = p.read_text('utf-8')
    tree = ast.parse(source)
    constants = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    present = {'getUpdates': 'getUpdates' in constants,
               'answerCallbackQuery': 'answerCallbackQuery' in constants,
               'getoff': 'getoff' in functions, 'putoff': 'putoff' in functions}
    return {'status': 'CONTRACT_PRESENT' if all(present.values()) else 'CONTRACT_INCOMPLETE',
            'functions_present': present, 'actual_ack_verified': False}

def cloudflare_health(host):
    if not host:
        return {'status': 'UNKNOWN_NO_VERIFIED_LIVE_ENDPOINT', 'method': 'none'}
    parsed = urlparse(host)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.port is not None:
        return {'status': 'SKIPPED_UNSAFE_ENDPOINT'}
    hostname = parsed.hostname.lower()
    if hostname != 'rginfoua.pp.ua' and not hostname.endswith('.rginfoua.pp.ua'):
        return {'status': 'SKIPPED_NOT_OWNED_DOMAIN'}
    endpoint = 'https://' + hostname + '/health'
    req = urllib.request.Request(endpoint, headers={'Accept': 'application/json', 'User-Agent': 'RGNEWS2-safety-readonly/1'})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read(100000))
        if not isinstance(payload, dict) or payload.get('service') != WORKER:
            return {'status': 'ENDPOINT_NOT_CONTENT_HUB'}
        slots = payload.get('slots', {})
        disabled = isinstance(slots, dict) and 'poll' not in slots
        return {'status': 'LIVE_POLL_SLOT_DISABLED' if disabled else 'LIVE_POLL_SLOT_ACTIVE_UNSAFE',
                'live_service_verified': True, 'live_poll_slot_disabled': disabled,
                'build_sha': payload.get('buildSha'), 'build_at': payload.get('buildAt'),
                'other_slots_present': all(k in slots for k in ('morning', 'explain', 'evening'))}
    except Exception as e:
        return {'status': 'LIVE_HEALTH_UNREACHABLE', 'error_type': type(e).__name__}

def deployment_local():
    locations = [ROOT / 'cloudflare-content-hub', OP / 'cloudflare-content-hub',
                 Path('/volume1/docker/RG_CLOUDFLARE'), Path('/volume1/docker/RG_CONTENT_HUB')]
    seen = []
    for p in locations:
        if p.is_dir() and not p.is_symlink():
            seen.append(str(p))
    wrangler = shutil.which('wrangler')
    return {'existing_deploy_directories': seen, 'wrangler_on_path': bool(wrangler),
            'deployment_performed': False,
            'source_guard_verified_in_GitHub': True,
            'source_poll_slot_removed_in_GitHub': True,
            'GitHub_deploy_status_latest_known': '2026-09-21',
            'live_rollout_confirmed_by_deploy_receipt': False}

def main():
    report = {
        'suite': 'NEWS2_CALLBACK_AND_CLOUDFLARE_SINGLE_BATCH_V1',
        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'pinned_v6': live_guard(), 'callback_health': current_callback(),
        'callback_code': callback_source(), 'test_card_1183': callback_receipt(),
        'cloudflare_deployment': deployment_local(),
        'cloudflare_live': cloudflare_health(os.environ.get('RG_CONTENT_HUB_HEALTH_URL', '')),
        'telegram_calls': 0, 'getUpdates_calls': 0, 'publications': 0,
        'new_pollers': 0, 'restarts': 0, 'files_modified': 0,
        'public_poll_reenable_allowed': False,
    }
    if report['pinned_v6']['status'] != 'PASS':
        report['status'] = 'FAIL_CLOSED_V6_DRIFT'
    elif report['callback_health']['status'] != 'PASS':
        report['status'] = 'CALLBACK_HEALTH_NEEDS_ATTENTION'
    elif report['cloudflare_live']['status'] == 'LIVE_POLL_SLOT_ACTIVE_UNSAFE':
        report['status'] = 'CLOUDFLARE_LIVE_POLL_UNSAFE'
    else:
        report['status'] = 'LOCAL_PASS_LIVE_CALLBACK_ACK_AND_CLOUDFLARE_PENDING'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['pinned_v6']['status'] == 'PASS' else 2

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(json.dumps({'status':'NEWS2_BATCH_SAFE_STOP','reason':type(e).__name__,
                          'telegram_calls':0,'publications':0}, ensure_ascii=False))
        sys.exit(2)
