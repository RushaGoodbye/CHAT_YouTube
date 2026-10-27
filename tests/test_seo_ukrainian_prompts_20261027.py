"""Regression guard: Ukrainian title language across all SEO generator paths."""

from pathlib import Path


def test_editorial_prompts_require_ukrainian_titles():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "rg_youtube_control" / "free_tools.py").read_text(encoding="utf-8")
    required = (
        "основна назва та РІВНО 3 A/B формулювання українською",
        "title: українською, до 100 символів",
        "Створи РІВНО 3 різні варіанти назви YouTube-відео українською",
        "Напиши ОДНУ назву українською, 25-95 символів",
    )
    for instruction in required:
        assert instruction in source, instruction
    forbidden = (
        "формулювання російською",
        "title: російською",
        "відео російською",
        "назву російською",
    )
    for instruction in forbidden:
        assert instruction not in source, instruction
