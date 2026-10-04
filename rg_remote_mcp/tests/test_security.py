from pathlib import Path

import pytest

import rg_remote_mcp.worker as worker
from rg_remote_mcp.hubclient import WORKERS, _base


def test_worker_path_escape_blocked(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(worker, "ROOT", root.resolve())

    with pytest.raises(ValueError):
        worker._path("../escape.txt")


def test_worker_path_stays_inside_root(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(worker, "ROOT", root.resolve())

    resolved = worker._path("folder/file.txt")
    assert resolved == (root / "folder" / "file.txt").resolve()


def test_hub_has_exactly_three_contours():
    assert set(WORKERS) == {"youtube", "telegram", "auto_edit"}
    assert _base("youtube").endswith("youtube-worker:8780")
    assert _base("telegram").endswith("telegram-worker:8780")
    assert _base("auto_edit").endswith("auto-edit-worker:8780")


def test_unknown_contour_blocked():
    with pytest.raises(ValueError):
        _base("other")
