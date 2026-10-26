import json
from pathlib import Path
import pytest
from rg_youtube_control.free_tools import _deterministic_evidence_description, _description_quality_error

FIXTURES = json.loads(Path("tests/fixtures/rg_real_public_transcripts_20261024.json").read_text(encoding="utf-8"))["videos"]

@pytest.mark.parametrize("item", FIXTURES, ids=lambda item: item["video_id"])
def test_real_transcript_excerpts_generate_safe_manual_review_description(item):
    excerpts = item["real_quote_excerpts"]
    assert len(excerpts) == 3
    assert item["published_title"]
    evidence_report = {
        "blocks": [
            {"verified": True, "topics": [{
                "topic": "Тему потрібно перевірити",
                "evidence": text[:180],
                "summary_uk": "Машинна транскрипція"
            }]} for text in excerpts
        ]
    }
    notes = []
    result = _deterministic_evidence_description(item["published_title"], evidence_report, review_notes=notes)
    assert 260 <= len(result) <= 950
    assert not _description_quality_error(result, " ".join(excerpts))
    assert "РАША ГУДБАЙ" in result

def test_real_source_coverage():
    assert len(FIXTURES) == 10
    assert len({item["video_id"] for item in FIXTURES}) == 10
