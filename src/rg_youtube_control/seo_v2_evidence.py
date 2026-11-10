"""Universal SEO v2: source ingest and immutable evidence ledger.

This module is independent of old free_tools, specific channel topics and model
providers. It never publishes or alters existing video metadata.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    start_ms: int
    end_ms: int
    quote: str
    cue_indices: tuple[int, ...]


def _ms(value: str) -> int:
    stamp = value.strip().replace(",", ".")
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})\.(\d{1,3})", stamp)
    if not match:
        raise ValueError("Invalid SRT timestamp: " + value)
    hours, minutes, seconds, fraction = match.groups()
    if int(minutes) > 59 or int(seconds) > 59:
        raise ValueError("SRT timestamp out of range")
    return ((int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)) * 1000
            + int(fraction.ljust(3, "0")))


def parse_srt(source: str) -> list[Cue]:
    """Parse every valid SRT cue; no prefix sample and no inferred speakers."""
    rows: list[Cue] = []
    blocks = re.split(r"\n\s*\n", source.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff"))
    for block in blocks:
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines:
            continue
        times = re.fullmatch(r"\s*(\S+)\s*-->\s*(\S+)(?:\s+.*)?", lines[0])
        if not times:
            continue
        start, end = _ms(times.group(1)), _ms(times.group(2))
        text = " ".join(" ".join(lines[1:]).split())
        if start > end or not text:
            continue
        rows.append(Cue(start, end, text))
    if not rows:
        raise ValueError("SRT has no readable caption cues")
    return sorted(rows, key=lambda cue: (cue.start_ms, cue.end_ms))


def make_windows(cues: list[Cue], *, max_chars: int = 3500,
                 max_ms: int = 240000) -> list[list[int]]:
    """Partition all cues into bounded windows without dropping the tail."""
    if max_chars < 100 or max_ms < 1000:
        raise ValueError("Invalid source window budget")
    windows: list[list[int]] = []
    indices: list[int] = []
    length = 0
    for index, cue in enumerate(cues):
        if indices and (
            length + len(cue.text) + 1 > max_chars
            or cue.start_ms - cues[indices[0]].start_ms > max_ms
        ):
            windows.append(indices)
            indices, length = [], 0
        indices.append(index)
        length += len(cue.text) + 1
    if indices:
        windows.append(indices)
    return windows


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), re.UNICODE)


def _same_words(quote: str, source: str) -> bool:
    """Allow punctuation/spacing differences, never altered source words."""
    target, words = _tokens(quote), _tokens(source)
    return bool(target) and any(
        words[index:index + len(target)] == target
        for index in range(len(words) - len(target) + 1)
    )


def verify_quote(quote: str, cues: list[Cue], indices: Iterable[int],
                 *, max_cues: int = 3) -> Evidence | None:
    """Ground a proposed verbatim quote in at most three contiguous cues."""
    quote = " ".join(str(quote or "").split())
    if not 8 <= len(quote) <= 350:
        return None
    positions = sorted(set(int(i) for i in indices))
    for pos, start_index in enumerate(positions):
        if start_index < 0 or start_index >= len(cues):
            continue
        for length in range(1, max_cues + 1):
            slice_indices = positions[pos:pos + length]
            if len(slice_indices) != length or slice_indices != list(range(start_index, start_index + length)):
                break
            if any(cues[j + 1].start_ms - cues[j].end_ms > 12000
                   for j in slice_indices[:-1]):
                break
            joined = " ".join(cues[j].text for j in slice_indices)
            if _same_words(quote, joined):
                fingerprint = hashlib.sha256(
                    json.dumps([start_index, slice_indices[-1], quote.casefold()],
                               ensure_ascii=False).encode("utf-8")
                ).hexdigest()[:16]
                return Evidence(
                    evidence_id="ev_" + fingerprint,
                    start_ms=cues[start_index].start_ms,
                    end_ms=cues[slice_indices[-1]].end_ms,
                    quote=quote,
                    cue_indices=tuple(slice_indices),
                )
    return None


def evidence_ledger(cues: list[Cue], proposals: Iterable[dict[str, Any]],
                    *, max_cues: int = 3) -> dict[str, Any]:
    """Record rejected quotes separately. Never promote a model summary."""
    accepted: list[Evidence] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for proposed in proposals:
        quote = str(proposed.get("quote") or "")
        try:
            indices = proposed.get("cue_indices") or []
            found = verify_quote(quote, cues, indices, max_cues=max_cues)
        except (ValueError, TypeError):
            found = None
        if found is None:
            rejected.append({"quote": quote[:350], "reason": "NOT_IN_SRT"})
        elif found.evidence_id not in seen:
            accepted.append(found)
            seen.add(found.evidence_id)
    return {
        "schema": "RG_SEO_EVIDENCE_V2",
        "source_cues": len(cues),
        "accepted": [asdict(item) for item in accepted],
        "rejected": rejected,
        "review_required": bool(rejected) or not accepted,
        "publication_allowed": False,
    }
