"""Regression: hundreds of network SRT probes must not freeze startup."""
from pathlib import Path
from types import SimpleNamespace

from rg_youtube_control.nas_srt_index import scan_nas_srt_ids


def test_exact_srt_index_reads_directory_once(tmp_path, monkeypatch):
    import rg_youtube_control.nas_srt_index as index

    for video_id in ("MEitKm687xo", "UC-zGLdheCE", "s3R09Hoocnc"):
        (tmp_path / f"{video_id}.srt").write_text("1", encoding="utf-8")
    (tmp_path / "incorrect_name.srt").write_text("1", encoding="utf-8")
    (tmp_path / "MEitKm687xo.mp4").write_bytes(b"video")

    scans = []
    original = index.os.scandir

    def counting_scandir(folder):
        scans.append(str(folder))
        return original(folder)

    monkeypatch.setattr(index.os, "scandir", counting_scandir)
    ids = scan_nas_srt_ids(tmp_path)
    assert ids == {"MEitKm687xo", "UC-zGLdheCE", "s3R09Hoocnc"}
    assert scans == [str(tmp_path)]


def test_missing_nas_reports_unknown_not_absence(tmp_path):
    assert scan_nas_srt_ids(tmp_path / "NAS_not_connected") is None


def test_gui_optimization_does_not_probe_unc_paths_per_video():
    ui_source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = ui_source.index("    def reload_optimization_queue(")
    end = ui_source.index("\n    def ", start + 5)
    block = ui_source[start:end]
    assert "transcript_ids = (" in block
    assert "(transcript_dir / f" not in block
    assert "transcript_status = (" in block
    assert ".exists()" not in block
    # Background scan never touches GUI widgets or the SQLite connection.
    begin = ui_source.index("    def _start_nas_srt_index(")
    finish = ui_source.index("    @Slot(object)\n    def _receive_nas_srt_index(", begin)
    scanner = ui_source[begin:finish]
    assert "threading.Thread(" in scanner
    assert "daemon=True" in scanner
    assert "scan_nas_srt_ids(Path(target))" in scanner
    assert "self.conn.execute" not in scanner


def test_status_update_uses_only_cached_result_on_main_thread():
    from PySide6.QtCore import Qt
    from rg_youtube_control.ui import MainWindow

    class Item:
        def __init__(self, value):
            self.value = value

        def data(self, role):
            return self.value if role == Qt.ItemDataRole.UserRole else None

        def text(self):
            return self.value

        def setText(self, value):
            self.value = value

        def setForeground(self, *args):
            pass

        def setFont(self, *args):
            pass

    class Table:
        def __init__(self):
            self.items = {
                (0, 3): Item("MEitKm687xo"), (0, 7): Item(""),
                (1, 3): Item("UC-zGLdheCE"), (1, 7): Item(""),
            }

        def rowCount(self):
            return 2

        def item(self, row, col):
            return self.items.get((row, col))

    folder = str(Path("C:/synthetic-nas"))
    stub = SimpleNamespace(
        _nas_srt_scanning=True, _nas_srt_path="",
        _nas_srt_ids=None, optimization_table=Table(),
        _nas_path=lambda key, default: Path(folder),
    )
    MainWindow._receive_nas_srt_index(
        stub, (folder, {"MEitKm687xo"}),
    )
    assert stub._nas_srt_scanning is False
    assert stub._nas_srt_ids == {"MEitKm687xo"}
    assert stub.optimization_table.item(0, 7).text() == "NAS"
    assert stub.optimization_table.item(1, 7).text() == ""
