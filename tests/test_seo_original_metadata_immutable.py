"""Regression tests for immutable original SEO metadata."""
import json

from rg_youtube_control.db import (
    annotate_optimization_draft, connect, save_optimization_draft,
)


def test_original_metadata_is_immutable_on_save(tmp_path):
    conn = connect(tmp_path / "qa.sqlite")
    try:
        save_optimization_draft(
            conn, "v1", "Draft A", "Draft description", "", ["draft"],
            source_title="Original", source_description="Original link: https://example.org/",
            source_tags=["original"],
        )
        save_optimization_draft(
            conn, "v1", "Draft B", "Updated description", "", ["updated"],
            source_title="Overwrite", source_description="Overwritten",
            source_tags=["overwrite"],
        )
        row = conn.execute(
            "SELECT * FROM optimization_drafts WHERE video_id='v1'"
        ).fetchone()
        assert row["source_title"] == "Original"
        assert row["source_description"] == "Original link: https://example.org/"
        assert json.loads(row["source_tags_json"]) == ["original"]
        assert row["new_title"] == "Draft B"
    finally:
        conn.close()


def test_original_metadata_is_immutable_on_annotation(tmp_path):
    conn = connect(tmp_path / "qa.sqlite")
    try:
        save_optimization_draft(
            conn, "v1", "Draft", "Draft description", "", [],
            source_title="Original", source_description="Original description",
            source_tags=["original"],
        )
        annotate_optimization_draft(
            conn, "v1", quality_state="needs_review",
            source_title="Overwrite", source_description="Overwrite",
            source_tags=["overwrite"],
        )
        row = conn.execute(
            "SELECT * FROM optimization_drafts WHERE video_id='v1'"
        ).fetchone()
        assert row["source_title"] == "Original"
        assert row["source_description"] == "Original description"
        assert json.loads(row["source_tags_json"]) == ["original"]
        assert row["quality_state"] == "needs_review"
    finally:
        conn.close()


def test_legacy_missing_original_fields_can_be_filled_once(tmp_path):
    conn = connect(tmp_path / "qa.sqlite")
    try:
        save_optimization_draft(conn, "v1", "Draft", "Description", "", [])
        annotate_optimization_draft(
            conn, "v1", source_title="First", source_description="First",
            source_tags=["first"],
        )
        annotate_optimization_draft(
            conn, "v1", source_title="Second", source_description="Second",
            source_tags=["second"],
        )
        row = conn.execute(
            "SELECT * FROM optimization_drafts WHERE video_id='v1'"
        ).fetchone()
        assert row["source_title"] == "First"
        assert row["source_description"] == "First"
        assert json.loads(row["source_tags_json"]) == ["first"]
    finally:
        conn.close()
