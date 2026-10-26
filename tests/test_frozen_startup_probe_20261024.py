"""QA marker must be emitted only from a running Qt event loop."""
from pathlib import Path


def test_frozen_startup_probe_is_opt_in_and_uses_qt_timer():
    main = Path("src/rg_youtube_control/main.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert 'os.environ.get("RG_YT_QA_SMOKE_FILE", "").strip()' in main
    assert "QTimer.singleShot(5000, finish_smoke)" in main
    assert '"visible": window.isVisible()' in main
    assert '"tab_count": window.tabs.count()' in main
    assert "Smoke test frozen GUI first paint and event loop" in workflow
    assert 'FROZEN_GUI_FIRST_PAINT_PASS' in workflow


def test_late_startup_probe_checks_archive_recovery_window():
    main = Path("src/rg_youtube_control/main.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert 'RG_YT_QA_STABILITY_FILE' in main
    assert "QTimer.singleShot(20000, finish_stability_probe)" in main
    assert "Check GUI after delayed archive recovery starts" in workflow
    assert "LATE_START_QT_RESPONSIVE_PASS" in workflow
