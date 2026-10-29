from rg_youtube_control import free_tools as seo

def test_long_live_ab_quote_recovery_has_bounded_triplet_search(monkeypatch):
    report = {"blocks": []}
    for i in range(300):
        quote = (
            f"q{i:05d} r{i:05d} Открытое обсуждение нового порядка оплаты "
            "и отчетности в регионе"
        )
        report["blocks"].append({
            "verified": True,
            "start_stamp": "",
            "topics": [{"topic": f"Питання {i}", "evidence": quote}]
        })
    calls = []
    def reject_all(titles, report):
        calls.append(tuple(titles))
        return ["Не використовувати"]
    monkeypatch.setattr(seo, "ab_title_issues", reject_all)
    result = seo._source_quote_ab_titles(report)
    assert result == []
    assert 0 < len(calls) <= 7140
