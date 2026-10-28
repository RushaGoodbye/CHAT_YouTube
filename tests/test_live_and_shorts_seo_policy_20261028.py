"""Publication policy: livestream archives do not get chapters, Shorts are skipped."""

import json
from pathlib import Path

from rg_youtube_control import free_tools as ft


def test_livestream_profile_disallows_chapters_even_if_model_invents_them(monkeypatch):
    def model(*_args, **_kwargs):
        return json.dumps({
            "title": "Ціни на бензин: суперечка в чат-рулетці",
            "title_variants": [
                "Ціни на бензин: що думають водії?",
                "Бензин на АЗС: чому подорожчало пальне?",
                "Чат рулетка і бензин: різні погляди учасників",
            ],
            "description": "Учасники обговорюють зміни вартості пального. " * 8,
            "tags": ["РАША ГУДБАЙ", "чат рулетка"],
            "chapters": "00:00 Вступ\n01:12 Підсумок розмови",
        }, ensure_ascii=False)
    monkeypatch.setattr(ft, "ollama_chat", model)
    monkeypatch.setattr(ft, "_description_quality_error", lambda *a, **k: "")
    monkeypatch.setattr(
        ft, "_recover_chapters_from_transcript",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("No live chapters")),
    )
    result = ft.generate_seo_package_local(
        current_title="Розмова про бензин", transcript="[00:00] бензин на АЗС",
        public_context={"profile": "live"}, is_short=False, fast_mode=True,
        timeout=1,
    )
    assert result["chapters"] == ""
    assert result["youtube_data_api_quota"] == 0


def test_local_ui_skips_shorts_and_propagates_live_channel_profile():
    source = (Path(__file__).resolve().parents[1] /
              "src" / "rg_youtube_control" / "ui.py").read_text(encoding="utf-8")
    section = source.split("def _generate_local_seo_result(", 1)[1].split(
        "def _normalize_local_seo_package(", 1
    )[0]
    assert "if 0 < duration_seconds <= 70:" in section
    assert "Shorts не оптимізуємо" in section
    assert 'context_for_model["profile"] = self.current_profile' in section
