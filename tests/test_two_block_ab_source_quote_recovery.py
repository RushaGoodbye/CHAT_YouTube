"""Archive A/B fallback: three distinct real quotes may come from two blocks."""
from rg_youtube_control.dialogue_seo import ab_title_issues
from rg_youtube_control.free_tools import _source_quote_ab_titles


def _two_block_report():
    return {"blocks_total": 2, "blocks_with_evidence": 2, "blocks": [
        {"start_stamp": "00:00:00", "topics": [
            {"topic": "звільнення Шойгу", "evidence":
             "Мне кажется что Шойгу просто перевели на другую должность и оставили при власти"},
            {"topic": "корупція у війську", "evidence":
             "Когда появляются такие истории о коррупции в министерстве обороны всем хочется разобраться"},
            {"topic": "стратегія армії", "evidence":
             "Я не понимаю какую стратегию они выбирают и кто теперь будет отвечать за решения"},
        ]},
        {"start_stamp": "00:05:03", "topics": [
            {"topic": "кадрове рішення", "evidence":
             "Всё это выглядит как обычная кадровая перестановка без изменения общей системы"},
            {"topic": "витрати та фінанси", "evidence":
             "Деньги на оборону расходуют огромные и людям важно знать кто отвечает за финансовый контроль"},
            {"topic": "відповідальність", "evidence":
             "Ответственность за ошибки должна быть понятной а не перекладываться с человека на человека"},
        ]},
    ]}


def test_two_blocks_can_yield_three_verified_distinct_review_only_quotes():
    report = _two_block_report()
    variants = _source_quote_ab_titles(
        report, "Увольнение ШОЙГУ - коррупция или все идет по плану?"
    )
    assert len(variants) == 3
    assert not ab_title_issues(variants, report)
    actual_quotes = {
        " ".join(topic["evidence"].split())
        for block in report["blocks"]
        for topic in block["topics"]
    }
    for variant in variants:
        assert variant.startswith("«")
        assert variant.endswith("» | ЧАТ РУЛЕТКА")
        excerpt = variant.split("»", 1)[0][1:].removesuffix("…")
        assert any(quote.startswith(excerpt) for quote in actual_quotes)


def test_only_two_real_quotations_do_not_force_three_fake_ab_titles():
    report = _two_block_report()
    report["blocks"][0]["topics"] = report["blocks"][0]["topics"][:1]
    report["blocks"][1]["topics"] = report["blocks"][1]["topics"][:1]
    assert _source_quote_ab_titles(report) == []


def test_fallback_handles_long_video_without_combinatorial_blowup():
    report = _two_block_report()
    report["blocks"] = report["blocks"] * 60
    variants = _source_quote_ab_titles(report)
    assert len(variants) in (0, 3)
    # No claims or labels are ever created from a model's topic summary.
    if variants:
        assert all(variant.startswith("«") for variant in variants)
