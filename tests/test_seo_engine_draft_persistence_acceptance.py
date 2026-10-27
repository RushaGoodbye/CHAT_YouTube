"""New-engine review drafts persist and reopen without altering source video data."""
import json

from rg_youtube_control.db import connect, get_optimization_draft, save_optimization_draft
from rg_youtube_control.optimization import safe_description_fix, validate_content_package
from rg_youtube_control.seo_engine_v1 import SeoDraft


def test_offline_seo_draft_roundtrip_in_isolated_sqlite(tmp_path):
    database = tmp_path / "qa_only.sqlite"
    video_id = "UC-zGLdheCE"
    draft = SeoDraft(
        video_id=video_id,
        title="СУДИМЫЕ ПЕДАГОГИ В ШКОЛАХ РФ? РЕАКЦИЯ РОССИЯН",
        ab_titles=("Школы и судимость: что скажут родители?",
                   "Осужденные преподаватели: доверят ли им детей?",
                   "Педагоги после преступления: спор в России"),
        description=("У цьому відео росіяни обговорюють судимих учителів, "
                     "важливість безпеки дітей у школах та позиції батьків. " * 5),
        tags=("раша гудбай", "чат рулетка", "судимость", "осужденные",
              "школы россии", "педагоги", "учителя", "россияне"),
        chapters="",
    )
    cleaned = safe_description_fix(draft.description, draft.title).after
    check = validate_content_package(
        draft.title, cleaned, draft.chapters,
        list(draft.tags), list(draft.ab_titles),
    )
    assert check.ready, check.errors
    db = connect(database)
    try:
        save_optimization_draft(
            db, video_id, draft.title, cleaned, draft.chapters,
            list(draft.tags), "draft", list(draft.ab_titles),
            generation="ollama:rg-seo-engine-v1",
            quality_state="needs_review",
            source_title="Могут ли осужденные работать в школах РФ?",
        )
    finally:
        db.close()

    reopened = connect(database)
    try:
        saved = get_optimization_draft(reopened, video_id)
        assert saved is not None
        assert saved["status"] == "draft"
        assert saved["new_title"] == draft.title
        assert saved["description"] == cleaned
        assert json.loads(saved["tags_json"]) == list(draft.tags)
        assert json.loads(saved["title_variants_json"]) == list(draft.ab_titles)
        assert saved["generation"] == "ollama:rg-seo-engine-v1"
        assert saved["quality_state"] == "needs_review"
    finally:
        reopened.close()
