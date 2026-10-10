"""Offline tests: private description recovery must be source-grounded and safe."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rg_youtube_private_description_repair import grounded_description


def test_repair_covers_verified_topics_quote_and_original_urls():
    source = "Перша нотатка https://donate.rginfoua.pp.ua/ та https://links.rginfoua.pp.ua/"
    report = {"blocks": [
        {"verified": True, "topics": [{
            "topic": "Ціни на бензин у Росії",
            "evidence": "Бензин дорожает, но никто не объясняет почему",
        }]},
        {"verified": True, "topics": [{
            "topic": "Російська пропаганда і війна",
            "evidence": "По телевизору всё время говорят про войну",
        }]},
    ]}
    repaired = grounded_description("Розмова про поточні події.", source, report)
    assert "Ціни на бензин у Росії" in repaired
    assert "Російська пропаганда і війна" in repaired
    assert ("Бензин дорожает, но никто не объясняет почему" in repaired
            or "По телевизору всё время говорят про войну" in repaired)
    assert "https://donate.rginfoua.pp.ua/" in repaired
    assert "https://links.rginfoua.pp.ua/" in repaired
    assert len(repaired) <= 5000


def test_no_verified_topics_never_creates_description():
    assert grounded_description(
        "Старий опис", "https://donate.rginfoua.pp.ua",
        {"blocks": [{"verified": False, "topics": [{"topic": "Вигадана тема"}]}]},
    ) == ""


def test_excessive_verified_topics_fail_closed_instead_of_truncating():
    report = {"blocks": [
        {"verified": True, "topics": [{
            "topic": ("Дуже довга точна тема зі свідчення учасника " + str(n) + " ") * 3,
            "evidence": "Точна відповідь із субтитрів без вигадки",
        }]}
        for n in range(120)
    ]}
    assert grounded_description(
        "Опис", "https://donate.rginfoua.pp.ua", report
    ) == ""


def test_cyrillic_source_topics_are_limited_in_characters_not_utf8_bytes():
    report = {"blocks": [
        {"verified": True, "topics": [{
            "topic": "Ціни на паливо та черги на автозаправках",
            "evidence": "У нас длинные очереди за бензином и много вопросов",
        }]}
    ]}
    # Valid Unicode text easily exceeds 3900 bytes while fitting in YouTube.
    description = ("Це підтверджена розмова співрозмовників. " * 55)
    result = grounded_description(
        description,
        "https://donate.rginfoua.pp.ua/",
        report,
    )
    assert result
    assert len(result.encode("utf-8")) > 3900
    assert len(result) <= 5000
    assert "Ціни на паливо та черги" in result
