"""Universal SEO v2 regression: arbitrary topics, quote provenance, no publishing."""
import json

from rg_youtube_control.seo_v2_evidence import (
    evidence_ledger, make_windows, parse_srt, verify_quote,
)
from rg_youtube_control.seo_v2_pipeline import (
    generate_universal_seo, validate_draft,
)


def _srt(words):
    return "\n\n".join(
        f"{i + 1}\n00:00:{i:02d},000 --> 00:00:{i:02d},800\n{line}"
        for i, line in enumerate(words)
    )


def test_ingest_covers_all_cues_and_tail_without_topic_assumptions():
    cues = parse_srt(_srt([
        "Говорили про відновлення мосту.",
        "Мистецтво стало темою суперечки.",
        "Згадали погоду та прогноз.",
    ]))
    assert len(cues) == 3
    windows = make_windows(cues, max_chars=100)
    assert [i for group in windows for i in group] == [0, 1, 2]


def test_ledger_rejects_invented_quote_and_unrelated_cues():
    cues = parse_srt(_srt([
        "Ми говорили про будівництво мосту.",
        "Співрозмовник розповів про погоду.",
    ]))
    accepted = verify_quote("Ми говорили про будівництво мосту.", cues, [0])
    assert accepted is not None and accepted.cue_indices == (0,)
    assert verify_quote("Вони виграли вибори.", cues, [0, 1]) is None
    result = evidence_ledger(cues, [
        {"quote": "Ми говорили про будівництво мосту.", "cue_indices": [0]},
        {"quote": "Вони виграли вибори.", "cue_indices": [0]},
    ])
    assert len(result["accepted"]) == 1
    assert len(result["rejected"]) == 1
    assert result["publication_allowed"] is False


def test_review_gate_rejects_forged_citations_and_numbers():
    cues = parse_srt(_srt(["Ми говорили про архітектуру міста."]))
    ledger = evidence_ledger(cues, [{
        "quote": "Ми говорили про архітектуру міста.", "cue_indices": [0],
    }])
    draft = {
        "title": "Архітектура міста та 1234 нові будівлі",
        "title_variants": ["Перша назва", "Друга назва", "Третя назва"],
        "description": "Міська архітектура і будинки.",
        "tags": ["місто"],
        "support_ids": {
            "title": ["ev_unverified"],
            "description": ["ev_unverified"],
            "title_variants": [["ev_unverified"]] * 3,
            "tags": [["ev_unverified"]],
        },
    }
    gate = validate_draft(draft, ledger, cues)
    assert "UNSUPPORTED_NUMBERS" in gate["issues"]
    assert "TITLE_UNSUPPORTED" in gate["issues"]
    assert "FORMAT_GATE_FAILED" in gate["issues"]
    assert gate["publication_allowed"] is False


def test_v2_accepts_any_content_without_hardcoded_keyword_list():
    source = _srt([
        "Кераміст розповідає про традиційну глазур та випалювання.",
        "Під час розмови згадували особливості глазурування кераміки.",
        "Майстер порівнює способи випалювання керамічних виробів.",
    ])
    state = {"calls": 0, "id": ""}
    def chat(prompt):
        state["calls"] += 1
        if "Extract up to three" in prompt:
            data = json.loads(prompt.split("SOURCE CUES:\n", 1)[1])
            row = data[0]
            return {"quotes": [{"quote": row["text"], "cue_indices": [row["cue"]]}]}
        if "Group these literal" in prompt:
            data = json.loads(prompt.split("EVIDENCE:\n", 1)[1])
            state["id"] = data[0]["evidence_id"]
            return {"topics": [{
                "label_uk": "Глазурування та випалювання кераміки",
                "evidence_ids": [item["evidence_id"] for item in data],
            }]}
        if "You are an accurate" in prompt:
            eid = state["id"]
            return {
                "title": "Як майстер створює кераміку: глазур і випалювання",
                "title_variants": [
                    "Особливості глазурування кераміки",
                    "Кераміка: від глазурування до випалу",
                    "Як випалюють керамічні вироби",
                ],
                "description": "У розмові йдеться про кераміку, глазурування та випалювання. " * 8,
                "tags": [
                    "глазурування кераміки", "випалювання кераміки",
                    "майстер кераміки", "керамічні вироби",
                    "традиційна глазур", "процес випалювання",
                    "вироби з кераміки", "випал кераміки",
                ],
                "support_ids": {
                    "title": [eid], "description": [eid],
                    "title_variants": [[eid]] * 3, "tags": [[eid]] * 8,
                },
            }
        raise AssertionError("Unexpected model prompt")
    result = generate_universal_seo(
        source, chat,
        independent_review=lambda _prompt: {"issues": []},
    )
    assert result["draft"]["title"].startswith("Як майстер")
    assert result["topics"][0]["label_uk"].startswith("Глазурування")
    assert result["status"] in {"REVIEW_REQUIRED", "READY_FOR_HUMAN_REVIEW"}
    assert result["publication_allowed"] is False
    assert result["editorial_approved"] is False
    assert result["evidence"]["source_cues"] == 3
