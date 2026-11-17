"""Regression: SRT-approved SEO remains publishable after editor save."""
from rg_youtube_control.seo_readiness import persisted_quality_state, ready_for_youtube


def _state(**overrides):
    args=dict(status="ready", original_generation="legacy", original_quality_state="",
              selected_generation="manual-reviewed-srt-v1", confirmed_srt=True,
              technical_quality="safe")
    args.update(overrides)
    return persisted_quality_state(**args)


def test_editor_confirmation_is_persisted():
    state=_state()
    assert state=="editor_approved"
    approved, errors=ready_for_youtube(status="ready",generation="manual-reviewed-srt-v1",
        quality_state=state, variants=["Волгоградський завод зупинив роботу після вибухів", "У Криму обговорюють перебої руху через міст", "Розмова про евакуацію та рішення місцевих служб"])
    assert approved, errors


def test_legacy_cannot_upgrade_without_srt_confirmation():
    assert _state(confirmed_srt=False)=="review"
    assert _state(selected_generation="legacy")=="review"


def test_technical_failure_blocks_editorial_approval():
    assert _state(technical_quality="blocked")=="review"
    assert _state(status="draft")=="review"


def test_safe_metadata_compatibility():
    assert _state(original_generation="safe-metadata-0.7.6",original_quality_state="safe_metadata",
        selected_generation="safe-metadata-0.7.6",confirmed_srt=False)=="safe_metadata"
