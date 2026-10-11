#!/usr/bin/env python3
"""Read-only Cloudflare Worker hotspot audit on the Telegram NAS deployment."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path("/volume1/docker/RG_ALERTS_DEPLOY")
ALLOWED = {".js", ".mjs", ".cjs", ".ts", ".tsx"}
PATTERNS = {
    "do_namespace_access": r"\.get\s*\(.*\)|idFrom(Name|String)\s*\(",
    "do_stub_fetch": r"\b(stub|durableObject|durable_object|room)\.fetch\s*\(",
    "kv_read": r"\b(?:KV|kv|STATE|CACHE|CONFIG|store|namespace)\.get\s*\(",
    "kv_write": r"\b(?:KV|kv|STATE|CACHE|CONFIG|store|namespace)\.put\s*\(",
    "external_fetch": r"\bfetch\s*\(",
    "scheduled_entrypoint": r"\bscheduled\s*\(",
    "alarm": r"\b(?:setAlarm|getAlarm|alarm)\s*\(",
    "loop": r"\b(?:while|for)\s*\(",
    "retry": r"\b(?:retry|backoff|setInterval|setTimeout)\b",
}
SKIP = {"node_modules", ".git", "dist", "build", ".wrangler", "coverage"}

def scan(root):
    results = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in ALLOWED or any(x in SKIP for x in path.parts):
            continue
        if path.is_symlink() or path.stat().st_size > 1_000_000:
            continue
        text = path.read_text("utf-8", errors="replace")
        hits = []
        for lineno, line in enumerate(text.splitlines(), 1):
            matched = [name for name, regex in PATTERNS.items() if re.search(regex, line)]
            if matched:
                hits.append({"line": lineno, "signals": matched})
        if hits:
            results.append({"file": str(path.relative_to(root)), "signals": hits[:100], "total_hit_lines": len(hits)})
    return results

def main():
    if "--selftest" in sys.argv:
        assert re.search(PATTERNS["alarm"], "state.storage.setAlarm(now)")
        assert re.search(PATTERNS["external_fetch"], "await fetch(url)")
        print(json.dumps({"selftest": "PASS", "modifications": 0, "cloudflare_requests": 0}))
        return
    if not ROOT.is_dir():
        print(json.dumps({"status": "ROOT_NOT_FOUND", "root": str(ROOT)}))
        raise SystemExit(2)
    results = scan(ROOT)
    print(json.dumps({"status": "READ_ONLY", "files_with_signals": len(results), "results": results}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
