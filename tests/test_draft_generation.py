from rg_youtube_control.db import (
    annotate_optimization_draft,
    connect,
    get_optimization_draft,
    save_optimization_draft,
)


def test_draft_generation_and_source_metadata_round_trip(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    try:
        save_optimization_draft(
            conn,
            "video-1",
            "Нова назва",
            "Новий опис " * 30,
            "",
            ["РАША ГУДБАЙ", "чат рулетка", "Украина", "Россия", "тег5", "тег6", "тег7", "тег8"],
            status="draft",
            title_variants=["A", "B", "C"],
            generation="local-seo-0.6",
            quality_state="review",
            quality_reason="потрібна перевірка",
            source_title="Стара назва",
            source_description="Старий опис",
            source_tags=["old-1", "old-2"],
        )

        row = get_optimization_draft(conn, "video-1")
        assert row is not None
        assert row["generation"] == "local-seo-0.6"
        assert row["quality_state"] == "review"
        assert row["quality_reason"] == "потрібна перевірка"
        assert row["source_title"] == "Стара назва"
        assert row["source_description"] == "Старий опис"
        assert "old-1" in row["source_tags_json"]

        annotate_optimization_draft(
            conn,
            "video-1",
            quality_state="safe",
            quality_reason="Перевірено користувачем",
        )
        row = get_optimization_draft(conn, "video-1")
        assert row["quality_state"] == "safe"
        assert row["quality_reason"] == "Перевірено користувачем"
        assert row["generation"] == "local-seo-0.6"
    finally:
        conn.close()


def test_existing_schema_gets_generation_columns(tmp_path) -> None:
    conn = connect(tmp_path / "rg.db")
    try:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(optimization_drafts)"
            ).fetchall()
        }
        assert {
            "generation",
            "quality_state",
            "quality_reason",
            "source_title",
            "source_description",
            "source_tags_json",
        }.issubset(columns)
    finally:
        conn.close()
