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
