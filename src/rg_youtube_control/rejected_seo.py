"""Stable local fingerprints for previously rejected SEO packages."""
import hashlib
import json


def rejected_package_key(video_id: str) -> str:
    return "seo_rejected_fingerprint_" + str(video_id).strip()


def package_fingerprint(title: str, description: str, tags: list[str]) -> str:
    payload = [
        str(title or "").strip(),
        str(description or "").strip(),
        sorted({str(t).strip().casefold() for t in tags if str(t).strip()}),
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
