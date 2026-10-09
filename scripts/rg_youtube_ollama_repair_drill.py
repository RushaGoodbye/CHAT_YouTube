"""One-shot isolated repair drill. Never touches the source checkout."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback
import time

def main():
    source = Path.cwd().resolve()
    expected = source / "scripts" / "rg_youtube_seo_repair_agent.py"
    if not expected.is_file():
        raise SystemExit("Run from the extracted PR #86 repository folder")
    report = source / "rg_youtube_ollama_drill_result.json"
    state = {"status": "RUNNING", "stage": "initialize", "started_at": time.time(),
             "run_id": f"{int(time.time())}-{os.getpid()}"}
    def save(**values):
        state.update(values)
        report.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print("STAGE:", state.get("stage"), "STATUS:", state.get("status"), flush=True)
    save()
    try:
        return run_drill(source, save, state)
    except Exception as exc:
        save(status="ERROR", stage="exception", error=repr(exc), traceback=traceback.format_exc()[-3500:])
        raise

def run_drill(source, save, state):
    save(stage="create_sandbox")
    with tempfile.TemporaryDirectory(prefix="RG_YOUTUBE_AUTOFIX_DRILL_") as tmp:
        sandbox = Path(tmp) / "checkout"
        shutil.copytree(source, sandbox, ignore=shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", ".pytest_cache", "*.pyc"))
        target = sandbox / "src/rg_youtube_control/rejected_seo.py"
        original = target.read_text(encoding="utf-8")
        source_target = source / "src/rg_youtube_control/rejected_seo.py"
        needle = 'return hashlib.sha256(raw.encode("utf-8")).hexdigest()'
        if original.count(needle) != 1:
            raise SystemExit("Expected fingerprint implementation has changed; drill stopped")
        target.write_text(original.replace(needle, 'return "broken-fingerprint"'), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(sandbox / "src")}
        venv_python = source / ".venv" / "Scripts" / "python.exe"
        interpreter = str(venv_python) if venv_python.is_file() else sys.executable
        print("TEST INTERPRETER:", interpreter, flush=True)
        print("SANDBOX:", sandbox, flush=True)
        print("TEST ERROR: deliberately broken fingerprints (sandbox only)", flush=True)
        save(stage="ollama_repair_running", sandbox_created=True)
        # Stream a fresh log and heartbeat while Ollama works; never show stale results.
        log_path = source / "rg_youtube_ollama_drill_live.log"
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [interpreter, "-u", "scripts/rg_youtube_seo_repair_agent.py", "--apply"],
                cwd=sandbox, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            save(agent_pid=proc.pid, log_file=str(log_path))
            last_pos = 0
            last_heartbeat = 0
            timed_out = False
            while proc.poll() is None:
                with log_path.open("r", encoding="utf-8", errors="replace") as current:
                    current.seek(last_pos)
                    chunk = current.read()
                    last_pos = current.tell()
                if chunk:
                    print(chunk, end="", flush=True)
                elapsed = time.monotonic() - started
                if elapsed - last_heartbeat >= 20:
                    save(stage="ollama_repair_running", elapsed_seconds=int(elapsed))
                    last_heartbeat = elapsed
                if elapsed > 900:
                    proc.kill()
                    proc.wait()
                    timed_out = True
                    break
                time.sleep(1)
            with log_path.open("r", encoding="utf-8", errors="replace") as current:
                current.seek(last_pos)
                tail = current.read()
            if tail:
                print(tail, end="", flush=True)
        output = log_path.read_text(encoding="utf-8", errors="replace")
        if timed_out:
            save(status="TIMEOUT", stage="ollama_repair_running",
                 timeout_seconds=900, stdout=output[-4000:])
            return 2
        save(stage="verify_result", agent_exit_code=proc.returncode,
             elapsed_seconds=int(time.monotonic() - started), stdout=output[-5500:], stderr="")
        fixed = target.read_text(encoding="utf-8")
        repaired = proc.returncode == 0 and fixed != original.replace(needle, 'return "broken-fingerprint"') and source_target.read_text(encoding="utf-8") == original
        result = {
            "drill": "rg_youtube_ollama_repair_v1",
            "status": "PASS" if repaired else "NOT_PASSED",
            "agent_exit_code": proc.returncode,
            "source_checkout_unchanged": source_target.read_text(encoding="utf-8") == original,
            "sandbox_repaired": repaired,
        }
        save(**result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if repaired else 1

if __name__ == "__main__":
    raise SystemExit(main())
