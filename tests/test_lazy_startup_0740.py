"""0.7.40 GUI startup regression: do not synchronously fill four hidden tables."""
from pathlib import Path
import re


def _ui():
    return Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")


def _method(name):
    src = _ui()
    i = src.index(f"    def {name}(")
    j = src.find("\n    def ", i + 8)
    return src[i:j if j > i else len(src)]


def test_initial_window_never_schedules_hidden_full_table_loads():
    init = _method("__init__")
    assert "QTimer.singleShot(100, self._startup_load_videos)" not in init
    assert "QTimer.singleShot(300, self._startup_load_optimization)" not in init
    assert "QTimer.singleShot(500, self._startup_load_comments)" not in init
    assert "QTimer.singleShot(700, self._startup_load_actions)" not in init
    assert "self._startup_views_ready = True" in init
    assert "QTimer.singleShot(200, self._startup_finish)" in init
    assert "self._startup_trace(\"APP_CONSTRUCT_BEGIN\")" in init
    assert "self._startup_trace(\"DATABASE_OPENED\")" in init


def test_tab_views_open_only_on_demand_not_preemptively():
    method = _method("_load_requested_tab")
    for index, method_name in [
        (1, "_startup_load_videos"), (2, "_startup_load_optimization"),
        (3, "_startup_load_comments"), (6, "_startup_load_actions"),
        (8, "refresh_archive_dashboard"),
    ]:
        assert f"{index}: self.{method_name}" in method
    assert "self._startup_loaded_tabs.add(index)" in method
    assert "self._startup_loaded_tabs.discard(index)" in method
    change = _method("_on_main_tab_changed")
    assert "QTimer.singleShot(" in change
    assert "self._load_requested_tab(target)" in change


def test_optimization_first_load_is_cooperative_and_search_cancels_old_batches():
    method = _method("reload_optimization_queue")
    assert "self._optimization_render_epoch" in method
    assert "def render_rows(offset: int, limit: int)" in method
    assert "prepared[offset:offset + limit], start=offset" in method
    assert "def next_batch(start_index: int = 0)" in method
    assert "chunk = 20" in method
    assert "QTimer.singleShot(" in method
    assert "self._startup_defer_optimization" in method
    assert "if self._optimization_render_epoch != epoch" in method
    # Non-startup callers preserve synchronous semantics for existing tests.
    assert "render_rows(0, len(prepared))" in method
    assert "finish_rows()" in method


def test_archive_does_not_block_before_first_paint():
    build = _method("_build_archive_dashboard_tab")
    assert "self.refresh_archive_dashboard()" not in build
    optimization_build = _method("_build_optimization_tab")
    assert "self._refresh_archive_campaign_summary()" not in optimization_build
    init = _method("__init__")
    assert "self._startup_traced" in init
    assert "self.refresh_free_tools_status)" in init
    assert "QTimer.singleShot(20_000," in init
    finish = _method("_startup_finish")
    assert 'self._startup_trace("FIRST_PAINT_READY")' in finish


def test_tracing_before_and_after_blocking_stage():
    trace = _method("_startup_traced")
    assert 'self._startup_trace("START " + action)' in trace
    assert 'self._startup_trace(f"END {action} elapsed={elapsed}s")' in trace
    assert "finally:" in trace
    logger = _method("_startup_trace")
    assert 'self._startup_trace_path.open("a", encoding="utf-8")' in logger
    assert "except OSError:" in logger


def test_no_youtube_or_nas_write_added_during_startup():
    startup = _method("_load_requested_tab") + _method("_startup_finish")
    for operation in ("update_video(", "save_optimization_draft(", "os.replace(", "generate_srt_offline("):
        assert operation not in startup
