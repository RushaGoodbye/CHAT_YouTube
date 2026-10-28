"""Cross-topic regression: no per-video SEO policy and no silent publication."""
from pathlib import Path

from rg_youtube_control import free_tools as ft
from rg_youtube_control.dialogue_seo import ab_title_issues
from rg_youtube_control.seo_readiness import ready_for_youtube


def _report(subjects):
    return {
        "blocks_total": 1, "blocks_with_evidence": 1,
        "blocks": [{"verified": True, "start_stamp": "00:00:00",
                    "topics": [
                        {"topic": topic, "summary_uk": topic + " у розмові",
                         "evidence": quote}
                        for topic, quote in subjects
                    ]}],
    }


def test_three_subjects_work_without_any_shoigu_reference(monkeypatch):
    report = _report([
        ("бензин", "Бензин на АЗС подорожал, рассказывают водители"),
        ("зарплати", "У жителей региона зарплаты и доходы стали темой спора"),
        ("пенсії", "Пенсии и социальные выплаты обсуждали в разговоре"),
    ])
    monkeypatch.setattr(ft, "ollama_chat", lambda *args, **kwargs:
                        (_ for _ in ()).throw(RuntimeError("offline")))
    package = ft.generate_seo_package_local(
        current_title="Ціни, зарплати та пенсії в регіоні",
        transcript="Бензин на АЗС, зарплаты и пенсии в регионе",
        evidence_report=report, is_short=True, timeout=1,
    )
    assert len(package["title_variants"]) == 3
    assert package["needs_review"] is True
    assert package["youtube_data_api_quota"] == 0
    assert "непублікаційний" in package["review_reason"]
    ok, _ = ready_for_youtube(
        status="draft", generation="local-seo-real",
        quality_state="needs_review", variants=package["title_variants"],
    )
    assert not ok


def test_unverified_topics_cannot_create_three_titles():
    report = {"blocks": [
        {"verified": False, "topics": [
            {"topic": "вибух", "evidence": "Взрыв на заводе"},
            {"topic": "війна", "evidence": "Война в Европе"},
            {"topic": "економіка", "evidence": "Экономика региона"},
        ]},
    ]}
    assert ft._verified_source_ab_titles(report, "Новини") == []


def test_description_not_tailored_to_a_particular_public_person():
    report = _report([
        ("корупція", "Шойгу коррупция и оборона"),
    ])
    text = ft._deterministic_evidence_description(
        "Шойгу", report, review_unmapped=[],
    )
    assert "версії причин зміни посади Шойгу" not in text
    assert "корупція" in text


def test_version_consistent_for_installer_and_app():
    root = Path(__file__).resolve().parents[1]
    config = (root / "pyproject.toml").read_text(encoding="utf-8")
    module = (root / "src" / "rg_youtube_control" / "__init__.py").read_text(encoding="utf-8")
    assert 'version = "0.7.41"' in config
    assert '__version__ = "0.7.41"' in module


def test_ukrainian_titles_do_not_pass_russian_language_gate():
    report = _report([
        ("бензин", "Бензин на заправках снова дорожает"),
        ("зарплати", "Зарплаты в регионе не хватает"),
        ("пенсії", "Пенсии остаются низкими"),
    ])
    issues = ab_title_issues([
        "Бензин и цены: почему опять подорожало?",
        "Зарплаты в регионе: что говорят?",
        "Пенсии: как люди живут на эти деньги?",
    ], report)
    assert sum("не українською" in issue for issue in issues) == 3


def test_chapter_fallback_never_invents_person_specific_timestamps():
    transcript = "[00:00] Шойгу обговорюють у розмові. [00:43] Інша тема."
    chapters = ft._grounded_chapters_from_transcript(
        current_title="Шойгу та кадрові зміни", transcript=transcript,
    )
    assert "Версії причин зміни Шойгу" not in chapters
    assert "Тимур Іванов і команда Шойгу" not in chapters
    function = (Path(__file__).resolve().parents[1] /
                "src" / "rg_youtube_control" / "free_tools.py").read_text(encoding="utf-8")
    section = function.split("def _grounded_chapters_from_transcript(", 1)[1].split(
        "\ndef _recover_chapters_from_transcript(", 1
    )[0]
    assert "00:43" not in section
    assert "00:00" in section
