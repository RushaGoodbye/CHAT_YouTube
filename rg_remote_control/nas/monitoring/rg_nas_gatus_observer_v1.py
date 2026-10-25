#!/usr/bin/env python3
"""Read-only NAS state observer. Only explicit --push sends status to LOCAL Gatus.

No Telegram Bot API, Cloudflare, queue, or public channel access.
Compatible with Python 3.9+ on Synology.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import stat
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MAX_AGE_SECONDS = 900
GATUS_KEYS = {
    "scheduler": "rg-nas_scheduler",
    "control-center": "rg-nas_control-center",
    "telegram-components": "rg-nas_telegram-components",
}


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp missing timezone")
    return parsed.astimezone(timezone.utc)


def _fresh(value: str, now: datetime, max_age: int) -> bool:
    seconds = (now - _timestamp(value)).total_seconds()
    return -120 <= seconds <= max_age


def observe(root: pathlib.Path, now: datetime | None = None, max_age: int = MAX_AGE_SECONDS) -> dict:
    now = now or datetime.now(timezone.utc)
    state = root / "RG_NAS_STATE"
    results = {}

    def read(name: str) -> str:
        return (state / name).read_text(encoding="utf-8").strip()

    def assess(key: str, timestamp_name: str, status_name: str | None = None, json_status: bool = False) -> None:
        try:
            if json_status:
                payload = json.loads(read(timestamp_name))
                timestamp = str(payload["updated_at"])
                status = str(payload["status"])
                good_status = status == "ok"
            else:
                timestamp = read(timestamp_name)
                status = read(status_name) if status_name else "OK"
                good_status = status == "OK"
            fresh = _fresh(timestamp, now, max_age)
            good = fresh and good_status
            reason = "OK" if good else ("stale heartbeat" if not fresh else "status=" + status[:60])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            good = False
            reason = "invalid or missing state: " + type(exc).__name__
        results[key] = {"success": good, "reason": reason}

    assess("scheduler", "scheduler_last_check_at", "scheduler_last_check_status")
    assess("control-center", "RG_CONTROL_CENTER.json", json_status=True)
    assess("telegram-components", "telegram_scheduler_components_checked_at", "telegram_scheduler_components_status")
    return results


def _read_secret(path: pathlib.Path) -> str:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("token file must not allow group or other access (chmod 600)")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32 or any(char.isspace() for char in value):
        raise ValueError("token must contain at least 32 non-whitespace characters")
    return value


def push(results: dict, url: str, token: str) -> None:
    # Deliberately disallow arbitrary remote URLs and public-facing reporting.
    if url not in {"http://127.0.0.1:18080", "http://localhost:18080", "http://gatus:8080"}:
        raise ValueError("Gatus URL must be local loopback or the isolated compose service")
    for key, result in results.items():
        params = {"success": str(result["success"]).lower()}
        if not result["success"]:
            params["error"] = result["reason"]
        destination = f"{url}/api/v1/endpoints/{GATUS_KEYS[key]}/external?{urlencode(params)}"
        req = Request(destination, data=b"", headers={"Authorization": "Bearer " + token}, method="POST")
        with urlopen(req, timeout=4) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Gatus push returned HTTP {response.status}")


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--root", type=pathlib.Path, default=pathlib.Path("/volume1/docker"))
    cli.add_argument("--max-age", type=int, default=MAX_AGE_SECONDS)
    cli.add_argument("--push", action="store_true", help="POST to LOCAL Gatus only")
    cli.add_argument("--token-file", type=pathlib.Path, default=pathlib.Path("/volume1/docker/RG_NAS_MONITOR/token"))
    cli.add_argument("--url", default="http://127.0.0.1:18080")
    opts = cli.parse_args(argv)
    if opts.max_age <= 0 or opts.max_age > 3600:
        cli.error("max-age must be 1..3600 seconds")
    results = observe(opts.root, max_age=opts.max_age)
    if opts.push:
        push(results, opts.url, _read_secret(opts.token_file))
    print(json.dumps({"schema": "RG_NAS_OBSERVER_V1", "pushed": opts.push, "checks": results},
                     ensure_ascii=False, sort_keys=True))
    return 0 if all(v["success"] for v in results.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
