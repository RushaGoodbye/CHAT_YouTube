"""Regression from real 0.7.16 preview: description 761 -> 1740, A/B hidden."""
from pathlib import Path

from rg_youtube_control.dialogue_seo import preserve_outline_topics
from rg_youtube_control.free_tools import _description_quality_error


def test_final_grounded_synopsis_is_not_a_timeline_dump():
    report = {"blocks": [
        {"topics": [{"topic": f"Тема {i:02d}: розмова про події та питання громадян"}]}
        for i in range(25)
    ]}
    source = (
        "Співрозмовник розповідає про загиблих знайомих та ставлення до війни. "
        "Він пояснює, як змінилася його позиція щодо відповідальності людей. "
        "Також порівнює погляди мешканців різних регіонів."
    )
    description, omitted = preserve_outline_topics(
        source, report, max_topic_bullets=2, max_body_bytes=2300
    )
    assert description.startswith(source)
    assert description.count("• ") <= 2
    assert len(omitted) >= 23
    assert "Тема 24" in description
    assert all(topic not in description for topic in omitted)


def test_extended_1700_character_generated_description_is_not_ok():
    long_description = (
        "Співрозмовник розповідає про війну і пояснює свою позицію. "
        "Він згадує важливі події з розмови та думки родичів. "
        "Наприкінці детально обговорює суспільну відповідальність. "
    ) * 12
    assert len(long_description) > 1150
    assert _description_quality_error(long_description, max_chars=950) == "too_long"


def test_generator_prompt_and_final_guard_agree_on_brevity():
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    function = source.split("def generate_seo_package_local(", 1)[1].split(
        "\ndef _comment_reply_safe_novelty_ok(", 1
    )[0]
    assert "400-900" in function
    assert "400-2400" not in function
    assert 'max_topic_bullets=2' in function
    assert 'max_body_bytes=2300' in function
    assert '{"max_chars": 950}' in function
    assert 'len(description) > (1150 if evidence_report else 5000)' in function


def test_qa_preview_includes_all_three_ab_titles_and_review_warning():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    method = source.split("def _preview_deep_content_package(", 1)[1].split(
        "\n    def _quota_write_available(", 1
    )[0]
    assert "title_variants: list[str] | None = None" in method
    assert '"ТРИ A/B НАЗВИ · окремо від основної назви"' in method
    assert "quality_note.setWordWrap(True)" in method
    assert '"Зберегти як чернетку · без YouTube"' in method
    save_method = source.split("def _save_local_seo_result(", 1)[1].split(
        "\n    def export_public_comments_zero_api(", 1
    )[0]
    assert "title_variants=variants" in save_method
    assert 'review_reason=str(package.get("review_reason") or "")' in save_method
