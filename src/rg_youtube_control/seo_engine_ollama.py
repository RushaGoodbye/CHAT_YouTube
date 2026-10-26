"""Local Ollama structured JSON adapter for RG SEO Engine 1.0.

Reads local 127.0.0.1 only. No commercial API and no YouTube writes.
"""
from __future__ import annotations

import json
import urllib.request

from .seo_engine_v1 import SeoDraft, generate_draft


SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "ab_titles": {"type": "array", "minItems": 3, "maxItems": 3,
                      "items": {"type": "string"}},
        "description": {"type": "string"},
        "tags": {"type": "array", "minItems": 3, "maxItems": 15,
                 "items": {"type": "string"}},
        "chapters": {"type": "string"},
    },
    "required": ["title", "ab_titles", "description", "tags", "chapters"],
    "additionalProperties": False,
}


def ollama_json(prompt: str, *, model: str = "qwen3:8b",
                endpoint: str = "http://127.0.0.1:11434",
                timeout: float = 240.0) -> str:
    body = json.dumps({
        "model": model, "stream": False, "format": SCHEMA,
        "messages": [
            {"role": "system", "content": "Return JSON only, grounded in transcript."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.25},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["message"]["content"])


def generate_with_ollama(*, video_id: str, current_title: str,
                         transcript: str, model: str = "qwen3:8b") -> SeoDraft:
    return generate_draft(
        video_id=video_id, current_title=current_title,
        transcript=transcript,
        generate_json=lambda prompt: ollama_json(prompt, model=model),
    )
