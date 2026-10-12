"""The NAS agent must never reopen RG YouTube Control after a user closes it."""
import importlib.util
from pathlib import Path


def _agent():
    path = Path("rg_remote_control/alexpc_agent.py").resolve()
    spec = importlib.util.spec_from_file_location("rg_alexpc_agent_gui_manual", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gui_service_check_never_starts_closed_gui(monkeypatch, tmp_path):
    agent = _agent()
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "x86"))
    installed = tmp_path / "RG YouTube Control" / "RG YouTube Control.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"mock")
    monkeypatch.setattr(agent, "_processes_json", lambda *_: "")
    monkeypatch.setattr(
        agent.subprocess, "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Closing GUI must not trigger a restart")
        ),
    )
    for _ in range(3):
        state = agent.ensure_youtube_gui()
        assert state["launch_policy"] == "manual"
        assert state["mode"] == "manual"
        assert state["started"] is False
        assert state["running"] is False


def test_gui_status_can_report_running_without_relaunch(monkeypatch, tmp_path):
    agent = _agent()
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "x86"))
    installed = tmp_path / "RG YouTube Control" / "RG YouTube Control.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"mock")
    monkeypatch.setattr(agent, "_processes_json", lambda *_: '{"ProcessId":123}')
    state = agent.ensure_youtube_gui()
    assert state["running"] is True
    assert state["started"] is False
    assert state["gui_process_untouched"] is True


def test_agent_service_snapshot_preserves_ollama(monkeypatch):
    agent = _agent()
    monkeypatch.setattr(agent, "ensure_youtube_gui",
                        lambda: {"launch_policy": "manual", "started": False})
    monkeypatch.setattr(agent, "ensure_ollama",
                        lambda: {"ok": True, "qwen3_8b": True})
    state = agent.service_snapshot()
    assert state["youtube_gui"]["started"] is False
    assert state["ollama"]["ok"] is True
