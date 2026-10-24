"""No network/subprocess tool probes on the Qt UI thread."""
from pathlib import Path


def test_external_tool_probe_runs_in_worker():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def refresh_free_tools_status(")
    end = source.index("    def _generate_local_seo_result(", start)
    block = source[start:end]
    assert "LocalToolWorker(probe_free_tools, self)" in block
    assert "worker.succeeded.connect(self._apply_free_tools_status)" in block
    assert "worker.failed.connect(self._free_tools_probe_failed)" in block
    assert "worker.finished.connect(self._free_tools_probe_finished)" in block
    assert "probes = probe_free_tools()" not in block
    assert "worker.isRunning()" in block
