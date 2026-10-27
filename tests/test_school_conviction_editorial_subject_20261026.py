from rg_youtube_control.free_tools import _deterministic_evidence_description

def test_verified_school_teaching_and_conviction_is_editorial_subject():
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Могут ли осужденные за тяжкие преступления преподавать в школах РФ?",
        "evidence": "Могут ли осужденные за тяжкие преступления преподавать в школах?"
    }]}]}
    review = []
    text = _deterministic_evidence_description(
        "Могут ли осужденные преподавать в школах РФ?", report, review_topics=review
    )
    assert "засуджених" in text
    assert "школах" in text
    assert review == []
    assert len(text) >= 260
    assert "другий шанс" in text
    assert "безпеку учнів" in text
    assert "законодавстві РФ" in text
