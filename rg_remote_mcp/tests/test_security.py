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


def test_compose_has_three_isolated_workers():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "youtube-worker:" in compose
    assert "telegram-worker:" in compose
    assert "auto-edit-worker:" in compose
    assert "youtube_net:" in compose
    assert "telegram_net:" in compose
    assert "auto_edit_net:" in compose
    assert "127.0.0.1:8765:8765" in compose


def test_workers_are_not_published_to_host():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    worker_blocks = [
        compose.split("youtube-worker:", 1)[1].split("telegram-worker:", 1)[0],
        compose.split("telegram-worker:", 1)[1].split("auto-edit-worker:", 1)[0],
        compose.split("auto-edit-worker:", 1)[1].split("networks:", 1)[0],
    ]
    for block in worker_blocks:
        assert "ports:" not in block


def test_no_cross_contour_copy_tool_exists():
    from rg_remote_mcp.server import mcp
    source = Path("rg_remote_mcp/server.py").read_text(encoding="utf-8")
    assert "cross_contour" not in source
    assert "source_contour" not in source
    assert "destination_contour" not in source
