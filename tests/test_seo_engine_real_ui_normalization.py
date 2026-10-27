"""Exercise the actual RG YouTube Control manual SEO normalization method."""
import pytest

from rg_youtube_control.ui import MainWindow


def result(tags):
    return {
        "video_id": "UC-zGLdheCE",
        "package": {
            "title": "СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ РФ? РЕАКЦИЯ РОССИЯН",
            "title_variants": [
                "Судимые педагоги: доверят ли им детей?",
                "Школы России и осужденные преподаватели",
                "Учитель после тяжкого преступления: что думают россияне?",
            ],
            "description": (
                "У цьому відео росіяни обговорюють питання викладання у школах "
                "людей із судимістю, безпеку дітей та думки батьків. " * 5
            ),
            "tags": tags,
            "chapters": "",
        },
    }


TAGS = [
    "раша гудбай", "чат рулетка", "школы россии", "осужденные",
    "судимость", "учителя", "педагоги", "россияне",
]


def test_new_engine_eight_tags_pass_the_actual_gui_normalizer():
    video_id, title, description, tags, chapters, variants = (
        MainWindow._normalize_local_seo_package(None, result(TAGS))
    )
    assert video_id == "UC-zGLdheCE"
    assert len(tags) == 8
    assert len(variants) == 3
    assert "links.rginfoua.pp.ua" in description
    assert "donate.rginfoua.pp.ua" in description
    assert chapters == ""


def test_three_tags_are_rejected_before_draft_save():
    with pytest.raises(RuntimeError, match="8"):
        MainWindow._normalize_local_seo_package(None, result(TAGS[:3]))


def test_invalid_ai_chapters_are_discarded_without_blocking_the_draft():
    item = result(TAGS)
    item["package"]["chapters"] = "00:01 Непідтверджений таймкод"
    *_, chapters, _ = MainWindow._normalize_local_seo_package(None, item)
    assert chapters == ""


def test_actual_gui_final_quality_gate_rejects_russian_description():
    proxy_type = type("QualityGateProxy", (), {
        "_looks_ukrainian_description": staticmethod(
            MainWindow._looks_ukrainian_description),
        "_generic_chapters": staticmethod(MainWindow._generic_chapters),
    })
    quality, reasons = MainWindow._package_quality_gate(
        proxy_type(),
        title=result(TAGS)["package"]["title"],
        description=("Обсуждение политических и военных событий в России. " * 8),
        chapters="", tags=TAGS, require_ukrainian=True,
    )
    assert quality == "blocked"
    assert any("не українською" in reason for reason in reasons)



def test_bulk_seo_does_not_abandon_live_ollama_calls():
    # The outer LocalToolWorker already runs this method off the GUI thread.
    # Starting daemon threads with short queue timeouts caused concurrent
    # Ollama sessions and eventual hangs on the creator PC.
    import inspect
    source = inspect.getsource(MainWindow.local_seo_batch)
    assert "threading.Thread" not in source
    assert "daemon=True" not in source
    assert "result_queue.get(" not in source
    assert "prepared.append(generate_sequentially(video_id))" in source
