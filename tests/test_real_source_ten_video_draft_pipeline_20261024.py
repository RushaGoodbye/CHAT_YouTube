import json
from pathlib import Path
import pytest
from rg_youtube_control import free_tools as seo

VIDEOS = json.loads(Path("tests/fixtures/rg_real_public_transcripts_20261024.json").read_text(encoding="utf-8"))["videos"]

@pytest.mark.parametrize("video", VIDEOS, ids=lambda item: item["video_id"])
def test_real_public_asr_excerpt_runs_to_review_draft(video, monkeypatch):
    quotes = video["real_quote_excerpts"]
    report = {
        "blocks_total": 3, "blocks_with_evidence": 3,
        "blocks": [
            {"verified": True, "start_stamp": "", "topics": [
                {"topic": "Фрагмент публічного діалогу",
                 "summary_uk": "Потребує перевірки",
                 "evidence": quote[:170]}
            ]}
            for quote in quotes
        ],
    }
    source = seo.evidence_outline_text(report)
    proposed = {
        "title": video["published_title"],
        "title_variants": ["Как дела? Ты красиво выглядишь",
                           "Внешность удивила всех", "Привет, как дела?"],
        "description": "Обговорення тем цього випуску потребує перевірки.",
        "tags": ["РАША ГУДБАЙ", "чат рулетка", "Россия",
                 "россияне", "мнение россиян", "вопросы россиянам",
                 "опрос россиян", "разговор с россиянами"],
        "chapters": "",
    }
    monkeypatch.setattr(seo, "ollama_chat", lambda *a, **k:
                        json.dumps(proposed, ensure_ascii=False))
    monkeypatch.setattr(seo, "_recover_title_variants", lambda **k: [])
    monkeypatch.setattr(seo, "_recover_independent_ab_titles", lambda **k: [])
    monkeypatch.setattr(seo, "_source_quote_ab_titles", lambda *a, **k: [])
    result = seo.generate_seo_package_local(
        current_title=video["published_title"],
        transcript=source,
        evidence_report=report,
        is_short=True,
    )
    assert result["title"] == video["published_title"]
    assert result["needs_review"] is True
    assert result["youtube_data_api_quota"] == 0
    assert all(not seo._incidental_ab_quote(t)
               for t in result["title_variants"])
