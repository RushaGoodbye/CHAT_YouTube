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
