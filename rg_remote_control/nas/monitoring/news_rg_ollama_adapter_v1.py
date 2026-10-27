#!/usr/bin/env python3
"""NEWS RG Ollama dry-run adapter. No Telegram or database writes."""
import argparse
import base64
import json
import re
import sys
import urllib.request

URL = "http://192.168.50.166:11434"
MODEL = "qwen3:8b"

def call(url, payload=None, timeout=90):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["selftest", "probe", "draft"])
    p.add_argument("--text", default="")
    p.add_argument("--text-b64", default="")
    args = p.parse_args()
    if args.command == "selftest":
        assert MODEL == "qwen3:8b" and URL.startswith("http://192.168.50.")
        assert len(re.findall(r"[^\W_]+", "TEST_NEWS", re.UNICODE)) < 7
        assert len(re.findall(r"[^\W_]+", "У Києві відкрили новий громадський простір площею 500 квадратних метрів.", re.UNICODE)) >= 7
        assert base64.b64decode(base64.b64encode("Київ".encode())).decode() == "Київ"
        print("NEWS_RG_OLLAMA_ADAPTER_SELFTEST_PASS")
        return
    if args.command == "probe":
        models = call(URL + "/api/tags", timeout=5).get("models", [])
        ok = any(m.get("name") == MODEL for m in models if isinstance(m, dict))
        print(json.dumps({"status": "MODEL_AVAILABLE" if ok else "MODEL_UNAVAILABLE", "read_only": True}))
        if not ok: sys.exit(2)
        return
    if args.text_b64:
        try:
            args.text = base64.b64decode(args.text_b64, validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise SystemExit("Invalid UTF-8 Base64 input") from exc
    if not args.text.strip() or len(args.text) > 12000:
        raise SystemExit("Input length must be 1..12000 characters")
    tokens = re.findall(r"[^\W_]+", args.text, re.UNICODE)
    if len(tokens) < 7 or not re.search(r"[А-Яа-яІіЇїЄєҐґ]", args.text):
        print(json.dumps({"status":"REJECTED_INSUFFICIENT_FACTS","telegram_calls":0,"db_writes":0,"publications":0}))
        return
    instruction = ("Ти редактор новин українською. Перепиши коротко як Telegram-чернетку. "
                   "Не вигадуй дати, числа, джерела, цитати чи підтвердження. "
                   "Зберігай атрибуцію заяв. Виведи лише текст чернетки.\n\n" + args.text)
    try:
        response = call(URL + "/api/generate", {"model": MODEL, "stream": False, "think": False,
            "prompt": instruction, "options": {"temperature": 0.1, "num_predict": 500}}, timeout=120)
        draft = response.get("response", "")
        if not isinstance(draft, str) or not draft.strip(): raise ValueError("empty response")
        print(json.dumps({"status": "DRAFT_ONLY_REVIEW_REQUIRED_UNVERIFIED", "draft": draft.strip(),
            "factual_verification": "NOT_PERFORMED", "telegram_calls": 0, "db_writes": 0, "publications": 0}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"status": "SAFE_STOP", "error_type": type(exc).__name__,
            "telegram_calls": 0, "db_writes": 0, "publications": 0}))
        sys.exit(1)

if __name__ == "__main__":
    main()
