"""Regression: an SEO draft must never replace its original source snapshot."""
from __future__ import annotations

import json

from rg_youtube_control.db import (
    annotate_optimization_draft,
    connect,
    get_optimization_draft,
    save_optimization_draft,
)


def _save(conn, *, title, description, tags, source_title=None,
          source_description=None, source_tags=None):
    save_optimization_draft(
        conn, "video-1", title, description, "", tags,
        status="draft", title_variants=["A", "B", "C"],
        generation="local-seo-evidence-0.7.9",
        source_title=source_title,
        source_description=source_description,
        source_tags=source_tags,
    )


def test_original_source_snapshot_survives_repeated_generation(tmp_path):
    conn = connect(tmp_path / "snapshot.db")
    try:
        _save(conn, title="First proposal", description="First generated text",
              tags=["generated1"], source_title="Original title",
              source_description="Original description",
              source_tags=["original1"])
        _save(conn, title="Second proposal", description="Second generated text",
              tags=["generated2"], source_title="Wrong new original title",
              source_description="Wrong new original description",
              source_tags=["wrong"])
        row = get_optimization_draft(conn, "video-1")
        assert row["new_title"] == "Second proposal"
        assert row["description"] == "Second generated text"
        assert json.loads(row["tags_json"]) == ["generated2"]
        assert row["source_title"] == "Original title"
        assert row["source_description"] == "Original description"
        assert json.loads(row["source_tags_json"]) == ["original1"]
    finally:
        conn.close()


def test_empty_original_description_is_immutable(tmp_path):
    conn = connect(tmp_path / "empty.db")
    try:
        _save(conn, title="Draft A", description="Generated A", tags=[],
              source_title="Original", source_description="", source_tags=[])
        _save(conn, title="Draft B", description="Generated B", tags=["generated"],
              source_title="Changed", source_description="Generated A",
              source_tags=["wrong"])
        row = get_optimization_draft(conn, "video-1")
        assert row["source_description"] == ""
        assert json.loads(row["source_tags_json"]) == []
    finally:
        conn.close()


def test_missing_snapshot_can_be_captured_once_for_legacy_draft(tmp_path):
    conn = connect(tmp_path / "legacy.db")
    try:
        _save(conn, title="Old draft", description="Old draft text", tags=[])
        _save(conn, title="Regenerated", description="New draft text", tags=[],
              source_title="Real original", source_description="Real original text",
              source_tags=["old"])
        _save(conn, title="Third", description="Third text", tags=[],
              source_title="Wrong", source_description="Wrong", source_tags=["wrong"])
        row = get_optimization_draft(conn, "video-1")
        assert row["source_title"] == "Real original"
        assert row["source_description"] == "Real original text"
        assert json.loads(row["source_tags_json"]) == ["old"]
    finally:
        conn.close()


def test_annotation_cannot_replace_captured_snapshot(tmp_path):
    conn = connect(tmp_path / "annotate.db")
    try:
        _save(conn, title="Draft", description="Draft text", tags=[],
              source_title="Original", source_description="Original text",
              source_tags=["original"])
        annotate_optimization_draft(
            conn, "video-1", source_title="Wrong",
            source_description="Wrong", source_tags=["wrong"],
            quality_state="safe",
        )
        row = get_optimization_draft(conn, "video-1")
        assert row["quality_state"] == "safe"
        assert row["source_title"] == "Original"
        assert row["source_description"] == "Original text"
        assert json.loads(row["source_tags_json"]) == ["original"]
    finally:
        conn.close()
