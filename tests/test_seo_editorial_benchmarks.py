import json
from pathlib import Path

ROOT = Path(__file__).parent / "fixtures"
CASES = ("MEitKm687xo", "pUWdQ8k6e4g", "u9y_f4HtEbQ", "GQL6N4jQpI8")


def test_real_video_editorial_benchmark_is_safe_and_complete():
    for video_id in CASES:
        item = json.loads((ROOT / f"seo_editorial_benchmark_{video_id}.json").read_text(encoding="utf-8"))
        assert item["video_id"] == video_id
        assert item["language"] == "uk"
        assert item["publication_allowed"] is False
        assert item["expected_title_variants"] == 3
        assert item["minimum_tags"] >= 8
        assert item["verified_subjects"]
        assert item["must_not_claim"]
        assert item["recommended_title"]
        assert len(item["recommended_title"]) <= 100
