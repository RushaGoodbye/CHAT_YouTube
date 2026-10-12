"""Regression from full real-video Shoigu QA: do not lose good metadata."""
import json
from pathlib import Path

from rg_youtube_control.dialogue_seo import ab_title_issues
from rg_youtube_control import free_tools


MAIN = "Увольнение Шойгу: коррупция или план?"
AB = [
    "Шойгу и Путин: почему увольнение стало стратегическим шагом",
    "Стратегия без войны: почему Шойгу уволили",
    "Коррупция или план: что движет увольнением",
]


def test_main_title_duplicate_detects_real_local_ollama_output():
    issues = ab_title_issues(AB, primary_title=MAIN)
    assert any("A/B варіант 3 повторює основну назву" in x for x in issues)


def test_ukrainian_proofread_can_correct_grammar_without_new_claims(monkeypatch):
    original = (
        "У цьому відео співрозмовники обговорюють причини кадрового рішення "
        "щодо Шойгу. Частина людей вважає, що зміна посади пов'язана з "
        "корупцією, інші припускають, що це планове рухається. "
        "Також згадують позицію Путіна та ставлення до військової стратегії. "
        "Учасники висловлюють власні версії та запитання."
    )
    improved = original.replace("це планове рухається", "це планова кадрова перестановка")
    calls = []
    def chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        return json.dumps({"description": improved}, ensure_ascii=False)
    monkeypatch.setattr(free_tools, "ollama_chat", chat)
    report = {"blocks": [{"topics": [{"evidence": "Всё идет по плану, а коррупция в армии обсуждается"}]}]}
    answer = free_tools._proofread_ukrainian_synopsis(
        original, model="test", current_title=MAIN, report=report,
    )
    assert answer == improved
    assert len(calls) == 1
    assert "ПІДТВЕРДЖЕНІ ДОСЛІВНІ РЕПЛІКИ" in calls[0]


def test_proofreading_rejects_unrelated_new_story(monkeypatch):
    source = "У цьому випуску співрозмовники обговорюють Шойгу і його зміну посади. " * 6
    def ungrounded(*_args, **_kwargs):
        return json.dumps({"description": "Нова ракетна атака й перемога на фронті. " * 12}, ensure_ascii=False)
    monkeypatch.setattr(free_tools, "ollama_chat", ungrounded)
    assert free_tools._proofread_ukrainian_synopsis(
        source, model="test", current_title=MAIN, report={"blocks":[]}
    ) == " ".join(source.split())


def test_app_loads_real_saved_editorial_baseline_before_generation():
    src = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    block = src.split("    def _generate_local_seo_result(", 1)[1].split(
        "    def _normalize_local_seo_package(", 1
    )[0]
    assert 'SELECT description FROM optimization_drafts WHERE video_id=?' in block
    assert 'context["description_source"] = "saved-seo-draft"' in block
    assert 'context["previous_draft_description"] = previous_draft_description' in block


def test_app_preserves_existing_chapters_and_tags_before_draft_save():
    src = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    block = src.split("    def _save_local_seo_result(", 1)[1].split(
        "    def export_public_comments_zero_api(", 1
    )[0]
    assert "previous = get_optimization_draft(self.conn, video_id)" in block
    assert "preserved_chapters = True" in block
    assert "or preserved_chapters" in block
    assert "необхідна перевірка" not in block or "потрібна перевірка таймкодів" in block
    assert "tags.append(old_tag)" in block
