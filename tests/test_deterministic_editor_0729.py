from rg_youtube_control.free_tools import _deterministic_evidence_description


def test_no_private_motives_from_screenshot():
    report = {"blocks": [{"verified": True, "topics": [
        {"evidence": "Шойгу коррупция и оборона"},
        {"evidence": "Шойгу война и стратегия"},
    ]}]}
    description = _deterministic_evidence_description("Шойгу и Путин", report)
    assert "Путін утримував" not in description
    assert "контролювати цей процес" not in description
    assert "корупція" in description
    assert "Міністерство оборони" in description
    assert "Шойгу" in description
    assert len(description) >= 260


def test_fail_closed_without_verified_subjects():
    import pytest
    with pytest.raises(ValueError, match="No verified"):
        _deterministic_evidence_description("Тема", {"blocks": []})


def test_unverified_block_not_used():
    import pytest
    with pytest.raises(ValueError, match="No verified"):
        _deterministic_evidence_description("Шойгу", {
            "blocks": [{"verified": False, "topics": [
                {"evidence": "коррупция"},
            ]}],
        })

def test_editor_not_model_authored_when_evidence_is_verified():
    from pathlib import Path
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    method = source.split("def generate_seo_package_local(", 1)[1]
    assert "if evidence_report:\n                # One deterministic editorial pass" in method
    assert "grounded_evidence_description = (" in method
    assert method.count("_deterministic_evidence_description(") == 1
    assert method.index("_deterministic_evidence_description(") < method.index(
        "for attempt in range("
    )
    assert "description_candidate = grounded_evidence_description" in method


def test_primary_seo_button_visible():
    from pathlib import Path
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    assert 'QPushButton("Створити SEO вибраного")' in source
    assert "seo_selected_guided_btn.clicked.connect(self.local_seo_selected)" in source
    assert "            seo_selected_guided_btn,\n            prepare_guided_btn," in source

def test_non_substantive_qa_label_does_not_block_real_topics():
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "дискусія про відповідь на запитання",
         "evidence": "Відповідь на запитання ведучого"},
        {"topic": "корупція", "evidence": "коррупция"},
    ]}]}
    result = _deterministic_evidence_description("Діалог", report)
    assert "корупція" in result
    assert "відповідь на запитання" not in result
