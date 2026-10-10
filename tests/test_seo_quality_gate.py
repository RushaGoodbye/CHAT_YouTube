from rg_youtube_control.seo_quality_gate import review_seo_package


def _report(topic="Цензура музики"):
    return {
        "blocks": [{
            "start_stamp": "00:01",
            "topics": [{
                "topic": topic, "summary_uk": "Заборона пісень",
                "evidence": "Забороняють слухати пісні",
            }],
        }],
        "needs_review": False,
    }


def test_missing_variants_requires_review():
    issues = review_seo_package(
        title="Росіянин розповів про цензуру музики",
        description="Цензура музики стала темою діалогу",
        variants=[],
        evidence_report=_report(),
    )
    assert any("3 назви" in value for value in issues)


def test_missing_grounded_topic_requires_review():
    issues = review_seo_package(
        title="Росіянин розповів про цензуру музики",
        description="Інша тема, жодної згадки",
        variants=[
            "Росіянин розповідає про цензуру музики",
            "Заборона музики викликала дискусію",
            "Які пісні забороняють у Росії сьогодні",
        ],
        evidence_report=_report(),
    )
    assert any("відсутня" in value for value in issues)


def test_absent_evidence_prevents_ready():
    issues = review_seo_package(
        title="Росіянин розповів про цензуру музики",
        description="Цензура музики",
        variants=[
            "Росіянин розповідає про цензуру музики",
            "Заборона музики викликала дискусію",
            "Які пісні забороняють у Росії сьогодні",
        ],
        evidence_report=None,
    )
    assert any("Немає звіту" in value for value in issues)


def test_missing_evidence_quote_forces_review():
    issues = review_seo_package(
        title="Росіянин розповів про цензуру музики",
        description="Цензура музики. Заборона пісень.",
        variants=[
            "Росіянин розповідає про цензуру музики",
            "Заборона музики викликала дискусію",
            "Які пісні забороняють у Росії сьогодні",
        ],
        evidence_report=_report(),
    )
    assert any("жодної дослівної цитати" in issue for issue in issues)


def test_preserved_evidence_quote_not_flagged():
    issues = review_seo_package(
        title="Росіянин розповів про цензуру музики",
        description="Цензура музики. Забороняють слухати пісні.",
        variants=[
            "Росіянин розповідає про цензуру музики",
            "Заборона музики викликала дискусію",
            "Які пісні забороняють у Росії сьогодні",
        ],
        evidence_report=_report(),
    )
    assert not any("жодної дослівної цитати" in issue for issue in issues)


def test_one_quote_is_enough_even_if_other_quote_is_paraphrased():
    report = _report()
    report["blocks"].append({
        "start_stamp": "00:22",
        "topics": [{
            "topic": "Цензура музики",
            "summary_uk": "Контроль плейлистів",
            "evidence": "Інша перевірена цитата",
        }],
    })
    issues = review_seo_package(
        title="Росіянин розповів про цензуру музики",
        description="Цензура музики. Забороняють слухати пісні. Далі обговорили контроль.",
        variants=[
            "Росіянин розповідає про цензуру музики",
            "Заборона музики викликала дискусію",
            "Які пісні забороняють у Росії сьогодні",
        ],
        evidence_report=report,
    )
    assert not any("жодної дослівної цитати" in issue for issue in issues)


def _complete_report():
    return {
        "blocks_total": 2,
        "blocks_analyzed": 2,
        "blocks_with_evidence": 2,
        "rows_covered": 48,
        "source_rows_total": 48,
        "source_rows_with_text": 48,
        "source_text_chars": 360,
        "covered_text_chars": 360,
        "source_text_sha256": "a" * 64,
        "covered_text_sha256": "a" * 64,
        "source_integrity_verified": True,
        "unverified_blocks": [],
        "needs_review": False,
        "blocks": [
            {"index": 1, "start_stamp": "00:00:00", "verified": True, "topics": [
                {"topic": "Цензура музики", "summary_uk": "Обговорення заборони музики",
                 "evidence": "Забороняють слухати пісні"},
            ]},
            {"index": 2, "start_stamp": "00:15:00", "verified": True, "topics": [
                {"topic": "Ціни на бензин", "summary_uk": "Співрозмовник говорить про бензин",
                 "evidence": "Бензин знову подорожчав"},
            ]},
        ],
    }


def _complete_package(report):
    return review_seo_package(
        title="Цензура музики та ціни на бензин у Росії",
        description=(
            "У розмові: Цензура музики. Забороняють слухати пісні. "
            "Ціни на бензин: Бензин знову подорожчав."
        ),
        variants=[
            "Заборона пісень у Росії: розмова про цензуру музики",
            "Подорожчання бензину: що відповів російський співрозмовник",
            "Росіянин розповів про цензуру музики й ціни на бензин",
        ],
        evidence_report=report,
    )


def test_genuinely_complete_transcript_report_has_no_coverage_warning():
    issues = _complete_package(_complete_report())
    assert not any("Неповне покриття" in issue for issue in issues)
    assert not any("Не всі часові фрагменти" in issue for issue in issues)


def test_transcript_missing_late_block_cannot_be_marked_ready():
    report = _complete_report()
    report["blocks"].pop()
    report["needs_review"] = False
    issues = _complete_package(report)
    assert any("Неповне покриття" in issue for issue in issues)


def test_inconsistent_caption_count_blocks_ready_even_with_all_topics_present():
    report = _complete_report()
    report["rows_covered"] = 0
    issues = _complete_package(report)
    assert any("Неповне покриття" in issue for issue in issues)


def test_missing_evidence_or_unverified_blocks_do_not_pass_silent_review():
    report = _complete_report()
    report["blocks"][1]["topics"][0]["evidence"] = ""
    report["unverified_blocks"] = [2]
    report["needs_review"] = False
    issues = _complete_package(report)
    assert any("доказової цитати" in issue for issue in issues)
    assert any("потребує ручного перегляду" in issue for issue in issues)


def test_missing_analyzer_counters_requires_manual_review():
    report = _complete_report()
    for key in ("blocks_total", "blocks_analyzed", "rows_covered", "blocks_with_evidence"):
        report.pop(key)
    issues = _complete_package(report)
    assert any("Неповне покриття" in issue for issue in issues)


def test_mismatched_transcript_fingerprint_blocks_ready():
    report = _complete_report()
    report["covered_text_sha256"] = "b" * 64
    issues = _complete_package(report)
    assert any("Цілісність транскрипту" in issue for issue in issues)


def test_absent_transcript_fingerprint_blocks_ready():
    report = _complete_report()
    for key in ("source_text_sha256", "covered_text_sha256", "source_integrity_verified"):
        report.pop(key)
    issues = _complete_package(report)
    assert any("Цілісність транскрипту" in issue for issue in issues)


def test_original_donation_urls_cannot_disappear_in_rewrite():
    report = _complete_report()
    issues = review_seo_package(
        title="Цензура музики та ціни на бензин у Росії",
        description="Цензура музики. Забороняють слухати пісні. Ціни на бензин.",
        variants=[
            "Заборона пісень у Росії: розмова про цензуру музики",
            "Подорожчання бензину: що відповів російський співрозмовник",
            "Росіянин розповів про цензуру музики й ціни на бензин",
        ],
        evidence_report=report,
        original_description="Допомога: https://donate.rginfoua.pp.ua та https://links.rginfoua.pp.ua",
    )
    assert any("втратив посилання" in issue for issue in issues)


def test_preserved_original_urls_do_not_trigger_retention_warning():
    report = _complete_report()
    issues = review_seo_package(
        title="Цензура музики та ціни на бензин у Росії",
        description=("Цензура музики. Забороняють слухати пісні. Ціни на бензин. "
                     "https://donate.rginfoua.pp.ua https://links.rginfoua.pp.ua"),
        variants=[
            "Заборона пісень у Росії: розмова про цензуру музики",
            "Подорожчання бензину: що відповів російський співрозмовник",
            "Росіянин розповів про цензуру музики й ціни на бензин",
        ],
        evidence_report=report,
        original_description="https://links.rginfoua.pp.ua https://donate.rginfoua.pp.ua",
    )
    assert not any("втратив посилання" in issue for issue in issues)


def test_removal_of_all_original_tags_requires_manual_review():
    report = _complete_report()
    issues = review_seo_package(
        title="Цензура музики та ціни на бензин у Росії",
        description="Цензура музики. Забороняють слухати пісні. Ціни на бензин.",
        variants=[
            "Заборона пісень у Росії: розмова про цензуру музики",
            "Подорожчання бензину: що відповів російський співрозмовник",
            "Росіянин розповів про цензуру музики й ціни на бензин",
        ],
        evidence_report=report,
        original_tags=["чат рулетка", "Раша Гудбай"],
        tags=[],
    )
    assert any("усі теги" in issue for issue in issues)


def test_replacement_of_original_tags_remains_allowed():
    report = _complete_report()
    issues = review_seo_package(
        title="Цензура музики та ціни на бензин у Росії",
        description="Цензура музики. Забороняють слухати пісні. Ціни на бензин.",
        variants=[
            "Заборона пісень у Росії: розмова про цензуру музики",
            "Подорожчання бензину: що відповів російський співрозмовник",
            "Росіянин розповів про цензуру музики й ціни на бензин",
        ],
        evidence_report=report,
        original_tags=["старий загальний тег"],
        tags=["ціни на бензин"],
    )
    assert not any("усі теги" in issue for issue in issues)
