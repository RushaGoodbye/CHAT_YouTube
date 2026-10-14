"""Offline-first SEO evidence quality gate; no YouTube, model, or database writes.

Optional sentence-transformers embeddings enrich lexical coverage. Dependencies
are never imported during app startup. Fallback works with Python stdlib.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path

TOKEN_RE = re.compile(r"[\w\u0400-\u04ff]{3,}", re.UNICODE)
STOP = frozenset("для что этот этой как его она они нас наш ваш или еще уже все тут там коли які під час про при від без що це був була були або але його цей цієї".split())


def tokens(text: str) -> set[str]:
    return {w for w in TOKEN_RE.findall(str(text).casefold()) if w not in STOP}


def lexical_similarity(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def _embedding_similarity(left: str, right: str, model) -> float:
    vectors = model.encode([left, right], normalize_embeddings=True)
    return max(0.0, min(1.0, float(sum(float(x) * float(y) for x, y in zip(vectors[0], vectors[1])))))


def best_similarity(topic: str, texts: list[str], *, embedding_model=None) -> float:
    if embedding_model is None:
        return max((lexical_similarity(topic, t) for t in texts), default=0.0)
    return max((_embedding_similarity(topic, t, embedding_model) for t in texts), default=0.0)


@dataclass(frozen=True)
class SEOAudit:
    ready: bool
    title_variants: int
    important_topics: int
    covered_topics: int
    missing_topics: tuple[str, ...]
    issues: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


def audit_package(
    *,
    evidence_topics: list[str],
    title_variants: list[str],
    description: str,
    tags: list[str] | None = None,
    min_coverage: float = 0.65,
    embedding_model=None,
) -> SEOAudit:
    """Evidence topics MUST come from verified transcript quotations, not a model guess."""
    issues = []
    titles = [str(t).strip() for t in title_variants if str(t).strip()]
    if len(titles) != 3 or len({t.casefold() for t in titles}) != 3:
        issues.append("exactly_three_distinct_titles_required")
    if any(len(t) > 100 for t in titles):
        issues.append("youtube_title_over_100_chars")
    description = str(description or "").strip()
    if not description:
        issues.append("empty_description")
    if len(description) > 5000:
        issues.append("youtube_description_over_5000_chars")
    topics = list(dict.fromkeys(str(t).strip() for t in evidence_topics if str(t).strip()))
    if not topics:
        issues.append("no_verified_topics")
    # Require coverage in the descriptive body, not just in tags or A/B headlines.
    missing = tuple(
        t for t in topics
        if best_similarity(t, [description], embedding_model=embedding_model) < min_coverage
    )
    if missing:
        issues.append("topics_missing_from_description")
    return SEOAudit(
        ready=not issues, title_variants=len(titles),
        important_topics=len(topics), covered_topics=len(topics)-len(missing),
        missing_topics=missing, issues=tuple(issues),
    )


def transcript_paths(
    video_id: str, roots: list[str | Path], *, extensions=(".srt", ".vtt", ".txt")
) -> list[Path]:
    """Safe exact-name lookup; never recursively scan multi-TB NAS trees."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        raise ValueError("invalid_video_id")
    hits = []
    for root in roots:
        root = Path(root)
        for ext in extensions:
            candidate = root / (video_id + ext)
            if candidate.is_file():
                hits.append(candidate)
    return hits


def load_optional_embedding_model(name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
    """Explicit opt-in only: requires separately installed model and cache."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(name, local_files_only=True)


def audit_batch(packages: list[dict], *, min_coverage: float = 0.65, embedding_model=None) -> dict:
    """Evaluate a whole set of *already generated* SEO packages without side effects.

    Input entries contain video_id, evidence_topics, title_variants, description.
    Failing items remain visible and never count as reviewed-ready drafts.
    """
    results = []
    for item in packages:
        video_id = str(item.get("video_id") or "").strip()
        try:
            audit = audit_package(
                evidence_topics=list(item.get("evidence_topics") or []),
                title_variants=list(item.get("title_variants") or []),
                description=str(item.get("description") or ""),
                tags=list(item.get("tags") or []),
                min_coverage=min_coverage,
                embedding_model=embedding_model,
            )
            results.append({"video_id": video_id, **audit.to_dict()})
        except Exception as exc:
            results.append({"video_id": video_id, "ready": False,
                            "issues": ["audit_error:" + type(exc).__name__]})
    return {"total": len(results), "ready": sum(bool(x["ready"]) for x in results),
            "review": sum(not x["ready"] for x in results), "items": results}
