"""Batch CLI is read-only and does not abort on one broken video."""
import json
from pathlib import Path

from rg_youtube_control import seo_v2_cli


def _srt(text: str) -> str:
    return f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n"


def test_batch_keeps_separate_reports_and_isolates_failures(tmp_path, monkeypatch):
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "a.srt").write_text(_srt("Справжній матеріал."), encoding="utf-8")
    (folder / "b.srt").write_text(_srt("Інший матеріал."), encoding="utf-8")
    output_dir = tmp_path / "results"

    def generate(srt, _candidate, independent_review=None):
        assert independent_review is not None
        if "Інший" in srt:
            raise RuntimeError("MODEL_FAILED")
        return {
            "status": "READY_FOR_HUMAN_REVIEW",
            "evidence": {"source_cues": 1, "accepted": [{"quote": "Справжній"}]},
            "publication_allowed": False,
            "draft": {"title": "Про матеріал"},
        }

    monkeypatch.setattr(seo_v2_cli, "generate_universal_seo", generate)
    exit_code = seo_v2_cli.main([
        "--input-dir", str(folder), "--output-dir", str(output_dir),
    ])
    assert exit_code == 2
    assert (output_dir / "a.seo_v2_review.json").is_file()
    assert not (output_dir / "b.seo_v2_review.json").exists()
    report = json.loads((output_dir / "_batch_summary.json").read_text("utf-8"))
    assert report["count"] == 2
    assert [row["status"] for row in report["results"]] == [
        "READY_FOR_HUMAN_REVIEW", "FAILED_REVIEW_REQUIRED",
    ]
    assert all(row["publication_allowed"] is False for row in report["results"])
    assert "Справжній матеріал" in (folder / "a.srt").read_text("utf-8")


def test_single_srt_preview_never_overwrites_srt(tmp_path, monkeypatch):
    source = tmp_path / "original.srt"
    original = _srt("Говорять про освіту.")
    source.write_text(original, encoding="utf-8")
    def generate(_srt, _candidate, independent_review=None):
        return {
            "status": "REVIEW_REQUIRED",
            "evidence": {"source_cues": 1, "accepted": []},
            "publication_allowed": False,
        }
    monkeypatch.setattr(seo_v2_cli, "generate_universal_seo", generate)
    assert seo_v2_cli.main([str(source)]) == 2
    assert source.read_text("utf-8") == original
    assert source.with_suffix(".seo_v2_review.json").is_file()
