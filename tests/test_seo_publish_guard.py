"""Regression for real main-channel 'Семейная психология' legacy READY bug."""
from pathlib import Path
import ast

from rg_youtube_control.config import DONATE_URL, PROJECT_LINKS_URL
from rg_youtube_control.seo_publish_guard import ready_package_blockers


TITLE = "ЧАТ РУЛЕТКА. Семейная психология"
TAGS = ["РАША ГУДБАЙ", "чат рулетка", "Россия", "Украина", "Семейная", "психология"]
AB = [
    "Семейная психология по-русски: неожиданный диалог в чат-рулетке",
    "Разговор о семье внезапно стал очень показательным",
    "Что не так с семейной логикой? Диалог в чат-рулетке",
]
SCREEN_DESCRIPTION = (
    "#рашагудбай #чатрулетка #семейная\n\n"
    "РАША ГУДБАЙ - розмови у форматі чат-рулетки. "
    "У цьому відео обговорюємо тему, зазначену в назві, "
    "та фіксуємо реальні діалоги без вигадування контексту.\n\n"
    "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n" + PROJECT_LINKS_URL
)


def test_screenshot_legacy_ready_with_generic_description_and_six_tags_is_blocked():
    failures = ready_package_blockers(
        title=TITLE, description=SCREEN_DESCRIPTION,
        chapters="", tags=TAGS, variants=AB,
        original_description="Старий опис з посиланнями",
    )
    assert any("релевантних тегів" in reason for reason in failures)
    assert any("Шаблонний опис" in reason for reason in failures)
    assert any("аналізу транскрипту" in reason for reason in failures)


def test_placeholder_chapters_in_editor_not_treated_as_saved_chapters():
    failures = ready_package_blockers(
        title=TITLE, description=SCREEN_DESCRIPTION,
        chapters="", tags=TAGS, variants=AB,
    )
    assert not any("Непідтверджені шаблонні назви розділів" in f for f in failures)
    actual_placeholder = ready_package_blockers(
        title=TITLE, description=SCREEN_DESCRIPTION,
        chapters="00:00 Вступ\n05:20 Наступний блок\n12:40 Фінальна частина",
        tags=TAGS, variants=AB,
    )
    assert any("Непідтверджені шаблонні назви розділів" in f for f in actual_placeholder)


def test_complete_metadata_without_transcript_is_not_archive_ready():
    specific = (
        "У розмові торкаються Цензура музики та Ціни на бензин. "
        "Співрозмовник каже: Забороняють слухати пісні. "
        "Інший відповідає: Бензин знову подорожчав. "
        "Ці конкретні питання учасники обговорюють у двох різних частинах."
        "\n" + PROJECT_LINKS_URL + "\n" + DONATE_URL
        + "\n#рашагудбай #чатрулетка #цензура"
    )
    failures = ready_package_blockers(
        title="Цензура музики та ціни на бензин у Росії",
        description=specific, chapters="",
        tags=[f"релевантний тег {i}" for i in range(8)],
        variants=AB, original_description="Оригінал " + PROJECT_LINKS_URL,
    )
    assert any("аналізу транскрипту" in f for f in failures)


def test_verified_complete_transcript_can_pass_when_package_is_grounded():
    report = {
        "blocks_total": 2, "blocks_analyzed": 2, "blocks_with_evidence": 2,
        "rows_covered": 48, "source_rows_with_text": 48,
        "source_text_chars": 360, "covered_text_chars": 360,
        "source_text_sha256": "a" * 64, "covered_text_sha256": "a" * 64,
        "source_integrity_verified": True, "unverified_blocks": [],
        "needs_review": False,
        "blocks": [
            {"verified": True, "topics": [{
                "topic": "Цензура музики",
                "evidence": "Забороняють слухати пісні",
                "summary_uk": "Обговорення заборони музики",
            }]},
            {"verified": True, "topics": [{
                "topic": "Ціни на бензин",
                "evidence": "Бензин знову подорожчав",
                "summary_uk": "Ціни на пальне",
            }]},
        ],
    }
    description = (
        "У розмові Цензура музики і Ціни на бензин. "
        "Співрозмовник сказав: Забороняють слухати пісні. "
        "Другий додав: Бензин знову подорожчав. "
        "Це підтверджені теми учасників розмови, які прозвучали "
        "в різних частинах відео. "
        + PROJECT_LINKS_URL + " " + DONATE_URL
        + "\n#рашагудбай #чатрулетка #цензура"
    )
    failures = ready_package_blockers(
        title="Цензура музики та ціни на бензин у Росії",
        description=description, chapters="",
        tags=[f"релевантний тег {i}" for i in range(8)],
        variants=[
            "Заборона пісень у Росії: розмова про цензуру музики",
            "Подорожчання бензину: що відповів російський співрозмовник",
            "Росіянин розповів про цензуру музики й ціни на бензин",
        ],
        original_description="Посилання " + PROJECT_LINKS_URL + " " + DONATE_URL,
        evidence_report=report,
    )
    assert failures == [], failures


def test_ui_enforces_guard_before_any_videos_update():
    source = (Path(__file__).resolve().parents[1]
              / "src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    def method(name):
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == name)
    apply = ast.get_source_segment(source, method("apply_content_package"))
    assert "self._draft_ready_blockers(draft)" in apply
    assert apply.index("self._draft_ready_blockers(draft)") < apply.index(
        "self._quota_update_video("
    )
    accept = ast.get_source_segment(source, method("review_draft_queue"))
    assert "issues.extend(self._draft_ready_blockers(draft))" in accept
    editor = ast.get_source_segment(source, method("edit_content_package"))
    assert "if status == \"ready\" and self._draft_ready_blockers(draft)" in editor
    assert "status = \"draft\"" in editor
