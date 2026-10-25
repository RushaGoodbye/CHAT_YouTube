"""Regression: user-confirmed TXT is not silently replaced by NAS SRT."""
from __future__ import annotations

from itertools import product
from pathlib import Path

from rg_youtube_control.seo_transcript_choice import compare_timed_to_verified


def _tokens(prefix):
    return [a + b + c + prefix for a, b, c in list(product("abcdef", repeat=3))[:60]]


def _source_pair(shared=True):
    text = "Шойгу " + " ".join(_tokens("source"))
    original = [{"start": 0.0, "duration": 0.0, "untimed": True, "text": text}]
    alternate = ("Шойгу " + " ".join(_tokens("source"))) if shared else (
        "Шойгу " + " ".join(_tokens("other"))
    )
    cues = [
        {"start": i * 12., "duration": 11., "text": alternate}
        for i in range(18)
    ]
    return original, cues


def test_faithful_timed_source_is_offered_but_not_auto_selected():
    manual, timed = _source_pair()
    result = compare_timed_to_verified(
        "Увольнение Шойгу — коррупция или план?", manual, timed,
        published_duration=217,
    )
    assert result.offer_timed
    assert result.reason == "verified_candidate"
    assert result.timed_cues == 18
    assert result.last_second == 215
    assert manual[0]["untimed"] is True  # no mutation


def test_different_conversation_with_same_named_subject_is_not_accepted():
    manual, timed = _source_pair(shared=False)
    result = compare_timed_to_verified("Увольнение Шойгу?", manual, timed)
    assert not result.offer_timed
    assert result.reason == "content_mismatch"


def test_timed_track_missing_named_subject_does_not_override_text():
    manual, timed = _source_pair()
    for cue in timed:
        cue["text"] = cue["text"].replace("Шойгу", "Погода")
    result = compare_timed_to_verified("Увольнение Шойгу?", manual, timed)
    assert not result.offer_timed
    assert result.reason == "subject_mismatch"


def test_partial_caption_coverage_is_not_offered():
    manual, timed = _source_pair()
    result = compare_timed_to_verified(
        "Увольнение Шойгу?", manual, timed, published_duration=1000,
    )
    assert not result.offer_timed
    assert result.reason == "short_coverage"


def test_untimed_candidate_is_not_offered():
    manual, timed = _source_pair()
    for cue in timed:
        cue["start"] = 0.0
        cue["duration"] = 0.0
    result = compare_timed_to_verified("Увольнение Шойгу?", manual, timed)
    assert not result.offer_timed
    assert result.reason == "incomplete_timing"


def test_desktop_only_switches_with_explicit_confirmation_and_worker_rechecks():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    pre = source.split("    def local_seo_selected(", 1)[1].split("    def _save_local_seo_result(", 1)[0]
    worker = source.split("    def _generate_local_seo_result(", 1)[1].split("\n    def ", 1)[0]
    assert 'transcript_preference = ""' in pre
    assert "QMessageBox.question(" in pre
    assert "transcript_preference = source_key" in pre
    assert "if transcript_preference:" in worker
    assert "compare_timed_to_verified(" in worker
    assert '"operator-confirmed-" + candidate_label' in worker
    assert "find_local_transcript(" in worker
