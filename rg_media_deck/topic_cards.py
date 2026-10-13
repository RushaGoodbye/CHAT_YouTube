"""Atomic, offline city/topic cards with source provenance and freshness.

Cards are a local editable cache, never evidence that old web facts remain
current. Note fields are user's private notes; never transmitted to AI unless
user chooses to copy them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import tempfile


def topic_key(topic: str) -> str:
    term = " ".join(str(topic).strip().split())[:140]
    if not term:
        raise ValueError("Укажите тему")
    return term.casefold()


def card_template(topic: str) -> dict:
    key = topic_key(topic)
    return {
        "topic": " ".join(topic.strip().split())[:140],
        "key": key, "notes": "", "links": [],
        "ai": None, "posts": [], "media": [],
        "last_updated": "", "reviewed_at": "",
    }


def sanitize_source_link(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    url = item.get("url", "")
    if isinstance(url, str) and url.startswith("https://") and len(url) < 1500:
        return {"title": str(item.get("title", ""))[:200], "url": url}
    return None


class TopicCards:
    def __init__(self, file: Path):
        self.file = Path(file)
        self._cards = {}
        if self.file.is_file():
            try:
                raw = json.loads(self.file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._cards = {k: v for k, v in list(raw.items())[:2000]
                                   if isinstance(k, str) and isinstance(v, dict)}
            except (OSError, ValueError):
                self._cards = {}

    def get(self, topic: str) -> dict:
        key = topic_key(topic)
        return dict(self._cards.get(key, card_template(topic)))

    def put(self, topic: str, *, notes=None, links=None, ai=None,
            posts=None, media=None) -> dict:
        entry = self.get(topic)
        if notes is not None:
            entry["notes"] = str(notes)[:30000]
        if links is not None:
            entry["links"] = [x for x in
                              (sanitize_source_link(v) for v in links)
                              if x is not None][:200]
        if ai is not None:
            entry["ai"] = {
                "text": str(ai.get("text", ""))[:50000],
                "date": str(ai.get("date", "")),
                "sources": [v for v in
                            (sanitize_source_link(x)
                             for x in ai.get("sources", [])) if v][:150],
                "verified": bool(ai.get("sources")),
            }
        if posts is not None:
            entry["posts"] = [dict(x) for x in posts[:150]]
        if media is not None:
            entry["media"] = [str(p)[:1024] for p in media[:300]]
        entry["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._cards[entry["key"]] = entry
        self.save()
        return dict(entry)

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self._cards, ensure_ascii=False, indent=2)
        file_descriptor, pending = tempfile.mkstemp(
            prefix=".rg_topic_", suffix=".tmp", dir=str(self.file.parent))
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            os.replace(pending, self.file)
        finally:
            if os.path.exists(pending):
                os.unlink(pending)


def recency_label(entry: dict, now: datetime | None = None) -> str:
    ai = entry.get("ai")
    if not isinstance(ai, dict):
        return "AI-справки нет"
    value = ai.get("date", "")
    try:
        date = datetime.fromisoformat(value)
        now = now or datetime.now(timezone.utc)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        hours = max(0, (now - date).total_seconds() / 3600)
    except (ValueError, TypeError):
        return "Дата AI-справки неизвестна"
    if hours > 24 * 7:
        return f"УСТАРЕЛО: {int(hours / 24)} дней"
    if hours > 24:
        return f"Обновлено {int(hours / 24)} дн. назад"
    return f"Обновлено {int(hours)} ч. назад"
