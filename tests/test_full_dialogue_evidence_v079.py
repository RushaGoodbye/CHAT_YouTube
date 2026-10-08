import json
from pathlib import Path

from rg_youtube_control.dialogue_seo import (
    analyze_all_timeline_blocks,
    evidence_outline_text,
    preserve_outline_topics,
    split_timeline,
)


def _rows(count=120):
    # Multiple clear themes spread across a 40-minute archive compilation.
    subjects = [
        ("Путин", "розмова про Путіна і відповідальність влади"),
        ("релігія", "суперечка про релігію та відповіді співрозмовника"),
        ("бензин", "питання про ціни на бензин та АЗС"),
        ("корупція", "позиція щодо корупції серед чиновників"),
        ("пропаганда", "спір про російську пропаганду"),
        ("війна", "оцінки війни Росії проти України"),
    ]
    result = []
    for i in range(count):
        name, fragment = subjects[min(len(subjects) - 1, i * len(subjects) // count)]
        result.append({
            "text": f"{name}. Співрозмовник розповідає: {fragment} у власних словах. Частина {i}.",
            "start": i * 20,
            "duration": 6,
        })
    return result


def _fake_chat(messages, **kwargs):
    text = messages[-1]["content"].split("ФРАГМЕНТ ", 1)[-1].split(":\n", 1)[-1]
    evidence = text[:100].strip()
    # Ensure grounded, not inferred names: every evidence string appears
    # literally in that exact source block.
    title = evidence.split(". ", 1)[0]
    return json.dumps({
        "topics": [{
            "topic": f"Тема: {title[:75]}",
            "summary_uk": f"Співрозмовник згадує тему «{title[:60]}» у своєму діалозі.",
            "evidence": evidence,
        }]
    }, ensure_ascii=False)


def test_no_transcript_parts_are_dropped():
    rows = _rows()
    blocks = split_timeline(rows, max_chars=550, max_span_seconds=160)
    all_text = " ".join(b["text"] for b in blocks)
    assert len(blocks) > 15
    assert sum(b["pieces"] for b in blocks) == len(rows)
    for row in rows:
        assert row["text"] in all_text
    assert blocks[0]["start"] == 0
    assert blocks[-1]["start"] > 2000
    assert all(len(item["text"]) <= 550 for item in blocks)


def test_every_timeline_block_is_grounded_and_cached(tmp_path):
    rows = _rows(30)
    calls = []
    def chat(*args, **kwargs):
        calls.append(1)
        return _fake_chat(*args, **kwargs)
    messages = []
    kwargs = dict(
        model="qwen3:8b",
        chat=chat,
        cache_dir=tmp_path,
        progress=messages.append,
        max_chars=550,
        max_span_seconds=170,
    )
    result = analyze_all_timeline_blocks(rows, **kwargs)
    assert result["blocks_total"] > 4
    assert result["blocks_total"] == result["blocks_analyzed"]
    assert result["blocks_with_evidence"] == result["blocks_total"]
    assert result["unverified_blocks"] == []
    assert result["rows_covered"] == len(rows)
    assert len(calls) == result["blocks_total"]
    assert messages[-1].startswith("Аналіз фрагментів:")
    assert evidence_outline_text(result).count("ТЕМА:") >= result["blocks_total"]
    again = analyze_all_timeline_blocks(rows, **kwargs)
    assert again["cache_hits"] == result["blocks_total"]
    assert len(calls) == result["blocks_total"]


def test_model_hallucinated_evidence_is_not_accepted(tmp_path):
    rows = _rows(9)
    def ungrounded(*_args, **_kwargs):
        return json.dumps({
            "topics": [{
                "topic": "Фантастична тема",
                "summary_uk": "Співрозмовники розповіли про вигадану подію.",
                "evidence": "Цієї цитати ніколи не було в субтитрах."
            }]
        }, ensure_ascii=False)
    result = analyze_all_timeline_blocks(
        rows, model="test", chat=ungrounded,
        cache_dir=tmp_path, max_chars=500,
    )
    assert result["needs_review"]
    assert result["blocks_with_evidence"] == 0
    assert len(result["unverified_blocks"]) == result["blocks_total"]
    assert not any(tmp_path.glob("*.json"))
    assert "НЕПЕРЕВІРЕНИЙ ФРАГМЕНТ" in evidence_outline_text(result)


def test_topic_retention_adds_late_dialogues_to_description():
    report = {
        "blocks": [
            {"topics": [{"topic": "Путін і влада"}]},
            {"topics": [{"topic": "Релігія і віра"}]},
            {"topics": [{"topic": "Заяви про бензин"}]},
            {"topics": [{"topic": "Корупція чиновників"}]},
            {"topics": [{"topic": "Російська пропаганда"}]},
            {"topics": [{"topic": "Війна проти України"}]},
        ]
    }
    text, omitted = preserve_outline_topics(
        "У цьому випуску обговорюють Путін і влада.", report
    )
    assert not omitted
    assert "Війна проти України" in text
    assert "Релігія і віра" in text
    assert "Заяви про бензин" in text
    assert text.count("Путін і влада") == 1


def test_topic_retention_does_not_silently_cut_when_description_is_full():
    report = {"blocks": [
        {"topics": [{"topic": f"Різна тема {i} про українські слова і діалоги"}]}
        for i in range(18)
    ]}
    text, omitted = preserve_outline_topics("Важлива розмова. " * 16, report, max_body_bytes=470)
    assert omitted
    assert len(text.encode("utf-8")) <= 470
    assert all(item not in text for item in omitted)


def test_wiring_uses_full_transcript_rows_not_first_12000_characters():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _generate_local_seo_result(")
    end = source.index("    def _normalize_local_seo_package(", start)
    body = source[start:end]
    assert "analyze_all_timeline_blocks(" in body
    assert "transcript_rows," in body
    assert "evidence_report=evidence_report" in body
    assert "transcript = evidence_outline_text(evidence_report)" in body
    assert "blocks_with_evidence" in body
    assert "cache_dir=self.data_dir" in body
    assert 'fast_mode else 300.0' in body
    assert 'context_for_model.pop("_caption_tracks", None)' in body


def test_review_only_and_preview_discloses_coverage():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    assert 'generation="local-seo-evidence-0.7.9"' in source
    assert '"draft" if requires_review else "ready"' in source
    assert "з доказовими цитатами" in source
    assert "Межі діалогів не визначаються без розмітки" in source
