"""0.7.37: user-confirmed untimed text must be safe and never invent timings."""
from pathlib import Path

import pytest

from rg_youtube_control.verified_text_import import (
    import_verified_text,
    load_verified_text,
)
from rg_youtube_control.dialogue_seo import split_timeline, analyze_all_timeline_blocks

VIDEO_ID = "MEitKm687xo"
TITLE = "Увольнение ШОЙГУ - коррупция или все идет по плану?"
REAL_CONTENT = (
    "Ведущий спрашивает о причинах увольнения Шойгу и о коррупции. "
    "Собеседники обсуждают связь Шойгу с Путиным, назначение Белоусова "
    "и военные расходы России. Упоминают заместителя Тимура Иванова, "
    "обвинения во взятках, причины перевода Шойгу в Совет безопасности. "
) * 8
WRONG_CONTENT = (
    "В Чечне говорят о войне, Дагестане, отношениях между народами. "
    "Спикеры рассказывают о бесплатной еде и поведении соседей. "
) * 8


def test_import_saves_checked_exact_id_and_no_timestamp_fabrication(tmp_path):
    source = tmp_path / "vidiq-transcription.txt"
    source.write_text(REAL_CONTENT, encoding="utf-8")
    target = import_verified_text(
        tmp_path / "app", VIDEO_ID, source, current_title=TITLE,
    )
    assert target.name == f"{VIDEO_ID}.txt"
    assert source.read_text(encoding="utf-8") == REAL_CONTENT
    rows, origin = load_verified_text(tmp_path / "app", VIDEO_ID)
    assert origin == "manual-confirmed-untimed-text"
    assert len(rows) == 1 and rows[0]["untimed"] is True
    assert rows[0]["start"] == 0.0 and rows[0]["duration"] == 0.0
    assert "Тимура Иванова" in rows[0]["text"]
    blocks = split_timeline(rows, max_chars=550, max_span_seconds=300)
    assert len(blocks) >= 2
    assert all(b["untimed"] is True for b in blocks)
    assert all(b["start_stamp"] == "без таймкоду" for b in blocks)
    assert all(b["end_stamp"] == "без таймкоду" for b in blocks)


def test_reject_wrong_subject_and_do_not_modify_nas(tmp_path):
    nas = tmp_path / "NAS"
    nas.mkdir()
    bad = nas / f"{VIDEO_ID}.srt"
    bad.write_text(WRONG_CONTENT, encoding="utf-8")
    wrong_txt = tmp_path / "wrong.txt"
    wrong_txt.write_text(WRONG_CONTENT, encoding="utf-8")
    with pytest.raises(ValueError, match="Шойгу"):
        import_verified_text(
            tmp_path / "app", VIDEO_ID, wrong_txt, current_title=TITLE,
        )
    assert not (tmp_path / "app" / "seo_verified_text").exists()
    assert bad.read_text(encoding="utf-8") == WRONG_CONTENT


def test_import_never_silently_overwrites_approved_file(tmp_path):
    text = tmp_path / "transcript.txt"
    text.write_text(REAL_CONTENT, encoding="utf-8")
    import_verified_text(tmp_path / "app", VIDEO_ID, text, current_title=TITLE)
    with pytest.raises(FileExistsError):
        import_verified_text(
            tmp_path / "app", VIDEO_ID, text, current_title=TITLE,
        )


def test_checksum_and_video_id_provenance_fail_closed(tmp_path):
    text = tmp_path / "transcript.txt"
    text.write_text(REAL_CONTENT, encoding="utf-8")
    stored = import_verified_text(
        tmp_path / "app", VIDEO_ID, text, current_title=TITLE,
    )
    stored.write_text("tampered " + REAL_CONTENT, encoding="utf-8")
    assert load_verified_text(tmp_path / "app", VIDEO_ID) == ([], "")
    assert load_verified_text(tmp_path / "app", "NOT_VALID") == ([], "")


def test_untimed_report_does_not_create_fake_chapter_timestamps(tmp_path):
    row = {
        "start": 0, "duration": 0, "text": REAL_CONTENT, "untimed": True,
    }
    sample_quote = "Ведущий спрашивает о причинах увольнения Шойгу"
    def chat(*args, **kw):
        return ('{"topics":[{"topic":"Увольнение Шойгу",'
                '"summary_uk":"Обговорення причин звільнення та корупції у владі",'
                '"evidence":"' + sample_quote + '"}]}')
    report = analyze_all_timeline_blocks(
        [row], model="fake-test-model", chat=chat,
        max_chars=4500, max_span_seconds=300,
    )
    assert report["blocks_total"] >= 1
    assert report["blocks_with_evidence"] >= 1
    assert all(block["start_stamp"] == "без таймкоду" for block in report["blocks"])
    assert all(block["end_stamp"] == "без таймкоду" for block in report["blocks"])


def test_gui_import_prioritized_over_wrong_nas_and_forces_review():
    src = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    gen = src.split("    def _generate_local_seo_result(",1)[1].split("\n    def ",1)[0]
    assert gen.index("load_verified_text(") < gen.index("find_local_transcript(")
    assert 'if transcript_source == "manual-confirmed-untimed-text":' in gen
    assert 'package["needs_review"] = True' in gen
    assert 'package["chapters"] = ""' in gen
    selected = src.split("    def local_seo_selected(",1)[1].split("\n    def ",1)[0]
    assert "Імпортувати підтверджений TXT без таймкодів" in selected
    assert "import_verified_text(" in selected
    assert "verified_media.json" in selected
    preview = src.split("    def _preview_deep_content_package(",1)[1].split("\n    def ",1)[0]
    assert "Часових міток немає" in preview
