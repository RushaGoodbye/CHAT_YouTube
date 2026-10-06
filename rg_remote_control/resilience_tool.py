from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAS_ROOT = Path(r"\\AlexLosServer\docker")
STATE = NAS_ROOT / "RG_NAS_STATE"
GOLDEN = NAS_ROOT / "RG_NAS_GOLDEN"
MCP_ROOT = NAS_ROOT / "RG_NAS_MCP"
RUNNER = Path(r"C:\RG_GITHUB_RUNNER")
TASK_KEEPALIVE = "RG_GITHUB_RUNNER_KEEPALIVE"
TASK_BOOT = "RG_GITHUB_RUNNER_BOOT"
OLD_TASK = "RG_GITHUB_RUNNER_WATCHDOG"


def run(argv: list[str], cwd: Path | None = None, timeout: int = 90) -> dict:
    p = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "exit_code": p.returncode,
        "stdout": (p.stdout or "")[-12000:],
        "stderr": (p.stderr or "")[-12000:],
    }


def atomic_json(path: Path, data: dict) -> None:
    last = None
    for attempt in range(5):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise last or OSError("atomic_json failed")


def smb_is_file(path: Path) -> bool:
    for attempt in range(5):
        try:
            return path.is_file()
        except OSError:
            time.sleep(0.4 * (attempt + 1))
    return False


def smb_size(path: Path) -> int:
    for attempt in range(5):
        try:
            return path.stat().st_size
        except OSError:
            time.sleep(0.4 * (attempt + 1))
    return 0


def smb_read_text(path: Path, limit: int | None = None) -> str:
    last = None
    for attempt in range(5):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[-limit:] if limit else text
        except OSError as exc:
            last = exc
            time.sleep(0.4 * (attempt + 1))
    if last:
        raise last
    return ""


def backup_file(path: Path, backup_dir: Path) -> str | None:
    if not path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / path.name
    shutil.copy2(path, dst)
    return str(dst)


def install_runner_persistence() -> dict:
    RUNNER.mkdir(parents=True, exist_ok=True)
    run_cmd = RUNNER / "run.cmd"
    svc_cmd = RUNNER / "svc.cmd"
    if not run_cmd.is_file():
        return {"ok": False, "reason": "run.cmd missing", "runner_dir": str(RUNNER)}

    service = {
        "available": svc_cmd.is_file(),
        "installed": False,
        "started": False,
        "install": None,
        "start": None,
    }

    if svc_cmd.is_file():
        status = run([r"C:\Windows\System32\cmd.exe", "/d", "/c", str(svc_cmd), "status"], cwd=RUNNER, timeout=30)
        service["status_before"] = status
        if status["exit_code"] == 0:
            service["installed"] = True
        else:
            install = run([r"C:\Windows\System32\cmd.exe", "/d", "/c", str(svc_cmd), "install"], cwd=RUNNER, timeout=60)
            service["install"] = install
            status = run([r"C:\Windows\System32\cmd.exe", "/d", "/c", str(svc_cmd), "status"], cwd=RUNNER, timeout=30)
            service["status_after_install"] = status
            service["installed"] = status["exit_code"] == 0

        if service["installed"]:
            start = run([r"C:\Windows\System32\cmd.exe", "/d", "/c", str(svc_cmd), "start"], cwd=RUNNER, timeout=30)
            service["start"] = start
            service["started"] = start["exit_code"] == 0 or "already" in (start["stdout"] + start["stderr"]).lower()

    keepalive = RUNNER / "runner_keepalive.ps1"
    keepalive.write_text(
        r'''$ErrorActionPreference = 'SilentlyContinue'
$root = 'C:\RG_GITHUB_RUNNER'
$log = Join-Path $root 'runner_keepalive.log'
$mutex = New-Object System.Threading.Mutex($false, 'Global\RG_GITHUB_RUNNER_KEEPALIVE_V2')
$locked = $false
try {
  $locked = $mutex.WaitOne(0)
  if (-not $locked) { exit 0 }

  $listener = Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" |
    Where-Object { $_.ExecutablePath -like 'C:\RG_GITHUB_RUNNER\*' -or $_.CommandLine -like '*C:\RG_GITHUB_RUNNER*' }
  $launcher = Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
    Where-Object { $_.CommandLine -like '*C:\RG_GITHUB_RUNNER*run.cmd*' }

  if ($listener) {
    "$(Get-Date -Format o) OK listener=$($listener.ProcessId -join ',')" | Add-Content -Path $log -Encoding UTF8
    exit 0
  }
  if ($launcher) {
    "$(Get-Date -Format o) WAIT launcher=$($launcher.ProcessId -join ',')" | Add-Content -Path $log -Encoding UTF8
    exit 0
  }

  Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c','cd /d C:\RG_GITHUB_RUNNER && call run.cmd' -WindowStyle Hidden
  "$(Get-Date -Format o) STARTED" | Add-Content -Path $log -Encoding UTF8
} finally {
  if ($locked) { $mutex.ReleaseMutex() | Out-Null }
  $mutex.Dispose()
}
''',
        encoding="utf-8",
    )

    cmd = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "{keepalive}"'
    )
    keep = run([
        r"C:\Windows\System32\schtasks.exe", "/Create",
        "/SC", "MINUTE", "/MO", "2",
        "/TN", TASK_KEEPALIVE, "/TR", cmd, "/F"
    ], timeout=30)
    boot = run([
        r"C:\Windows\System32\schtasks.exe", "/Create",
        "/SC", "ONLOGON",
        "/TN", TASK_BOOT, "/TR", cmd, "/F"
    ], timeout=30)

    startup_vbs = None
    appdata = os.environ.get("APPDATA")
    if appdata:
        startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup_dir.mkdir(parents=True, exist_ok=True)
        startup_vbs = startup_dir / "RG_GITHUB_RUNNER_BOOT.vbs"
        ps_cmd = str(keepalive).replace('"', '""')
        startup_vbs.write_text(
            'Set sh = CreateObject("WScript.Shell")\n'
            'sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""' + ps_cmd + '""", 0, False\n',
            encoding="utf-8",
        )

    if keep["exit_code"] == 0:
        run([r"C:\Windows\System32\schtasks.exe", "/Change", "/TN", OLD_TASK, "/DISABLE"], timeout=20)

    return {
        "ok": bool(service["installed"] or keep["exit_code"] == 0),
        "service": service,
        "keepalive_task": keep,
        "boot_task": boot,
        "startup_fallback": str(startup_vbs) if startup_vbs else None,
        "script": str(keepalive),
        "old_watchdog_disabled": keep["exit_code"] == 0,
    }


def patch_autodeploy_loop(loop_path: Path, backup_dir: Path) -> dict:
    if not loop_path.is_file():
        return {"patched": False, "reason": "loop missing", "path": str(loop_path)}

    text = loop_path.read_text(encoding="utf-8", errors="replace")
    if "RG_NAS_MCP_GUARD.sh" in text:
        return {"patched": False, "already": True, "path": str(loop_path)}

    lines = text.splitlines()
    insert_at = None
    indent = ""
    for i, line in enumerate(lines):
        if "RG_NAS_MCP_TICK.sh" in line and not line.lstrip().startswith("#"):
            insert_at = i
            indent = line[: len(line) - len(line.lstrip())]
            break
    if insert_at is None:
        return {"patched": False, "reason": "tick call not found", "path": str(loop_path)}

    backup_file(loop_path, backup_dir)
    lines.insert(insert_at, indent + 'sh "$ROOT/RG_NAS_MCP_GUARD.sh" || true')
    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    tmp = loop_path.with_suffix(loop_path.suffix + ".resilience.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, loop_path)

    verify = loop_path.read_text(encoding="utf-8", errors="replace")
    if "RG_NAS_MCP_GUARD.sh" not in verify or "RG_NAS_MCP_TICK.sh" not in verify:
        raise RuntimeError("autodeploy loop verification failed")
    return {"patched": True, "path": str(loop_path)}


def install() -> dict:
    STATE.mkdir(parents=True, exist_ok=True)
    GOLDEN.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = STATE / "resilience_backups" / stamp

    sources = {
        "RG_NAS_MCP_TICK.sh": ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_TICK.sh",
        "RG_NAS_MCP_GUARD.sh": ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_GUARD.sh",
        "RG_NAS_MCP_AUTO_EDIT_CALL.py": ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_AUTO_EDIT_CALL.py",
        "RG_NAS_MCP_YOUTUBE_CALL.py": ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_YOUTUBE_CALL.py",
        "RG_NAS_MCP_TELEGRAM_CALL.py": ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_TELEGRAM_CALL.py",
    }
    missing = [str(p) for p in sources.values() if not p.is_file()]
    if missing:
        raise RuntimeError("resilience sources missing: " + "; ".join(missing))

    copied = {}
    for name, source in sources.items():
        live = NAS_ROOT / name
        backup_file(live, backup_dir)
        shutil.copy2(source, live)
        shutil.copy2(source, GOLDEN / name)
        copied[name] = {"live": str(live), "golden": str(GOLDEN / name)}

    loop = patch_autodeploy_loop(NAS_ROOT / "RG_NAS_AUTODEPLOY_LOOP.sh", backup_dir)
    runner = install_runner_persistence()

    policy = {
        "schema": "RG_CONTROL_POLICY_V1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "primary_transport": "RG_NAS_MCP",
        "fallback_transport": "GITHUB_ACTIONS",
        "contours": {
            "auto_edit": {
                "namespace": "auto_edit_*",
                "github_permissions": "contents:read",
                "shared_youtube_credentials": False,
            },
            "telegram": {
                "namespace": "telegram_*",
                "github_permissions": "contents:read",
                "shared_youtube_credentials": False,
            },
            "youtube": {
                "namespace": "youtube_*",
                "github_permissions": "contents:read",
                "shared_auto_edit_credentials": False,
            },
        },
        "credential_rule": "No user PAT is shared between contours. Auto Edit and Telegram checkout credentials are non-persistent.",
        "rollback": "backup-before-write",
        "self_heal": "NAS guard before every MCP tick",
    }
    atomic_json(STATE / "RG_CONTROL_POLICY.json", policy)

    result = {
        "schema": "RG_RESILIENCE_INSTALL_V1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "copied": copied,
        "autodeploy_loop": loop,
        "runner": runner,
        "backup_dir": str(backup_dir),
        "policy": policy,
    }
    atomic_json(STATE / "RG_RESILIENCE_INSTALL.json", result)
    return result


def _task_query(name: str) -> dict:
    q = run([r"C:\Windows\System32\schtasks.exe", "/Query", "/TN", name, "/FO", "LIST", "/V"], timeout=20)
    return {
        "exists": q["exit_code"] == 0,
        "exit_code": q["exit_code"],
        "text": (q["stdout"] + q["stderr"])[-5000:],
    }


def queue_roundtrip(timeout: int = 85) -> dict:
    req_root = MCP_ROOT / "AUTO_EDIT_CALLS" / "requests"
    res_root = MCP_ROOT / "AUTO_EDIT_CALLS" / "results"
    err_root = MCP_ROOT / "AUTO_EDIT_CALLS" / "errors"
    req_root.mkdir(parents=True, exist_ok=True)
    res_root.mkdir(parents=True, exist_ok=True)
    err_root.mkdir(parents=True, exist_ok=True)

    request_id = uuid.uuid4().hex
    req = req_root / f"{request_id}.json"
    result = res_root / f"{request_id}.json"
    error = err_root / f"{request_id}.log"
    atomic_json(req, {
        "request_id": request_id,
        "tool": "auto_edit_status",
        "tool_args": {},
    })
    started = time.time()
    while time.time() - started < timeout:
        if smb_is_file(result):
            try:
                data = json.loads(smb_read_text(result))
            except Exception as exc:
                return {"ok": False, "request_id": request_id, "parse_error": repr(exc)}
            return {
                "ok": not bool(data.get("is_error")),
                "request_id": request_id,
                "elapsed_seconds": round(time.time() - started, 1),
                "result": data,
            }
        if smb_is_file(error) and smb_size(error):
            return {
                "ok": False,
                "request_id": request_id,
                "elapsed_seconds": round(time.time() - started, 1),
                "error": smb_read_text(error, 12000),
            }
        time.sleep(2)
    return {
        "ok": False,
        "request_id": request_id,
        "elapsed_seconds": round(time.time() - started, 1),
        "timeout": True,
        "request_still_exists": smb_is_file(req),
    }


def probe(do_roundtrip: bool = True) -> dict:
    files = {}
    requirements = {
        "RG_NAS_MCP_TICK.sh": "AUTO_EDIT_CALL_ROOT",
        "RG_NAS_MCP_GUARD.sh": "RG_CONTROL_CENTER_V1",
        "RG_NAS_MCP_AUTO_EDIT_CALL.py": "auto_edit_",
        "RG_NAS_MCP_YOUTUBE_CALL.py": "youtube_",
        "RG_NAS_MCP_TELEGRAM_CALL.py": "telegram_",
        "RG_NAS_AUTODEPLOY_LOOP.sh": "RG_NAS_MCP_GUARD.sh",
    }
    for name, marker in requirements.items():
        path = NAS_ROOT / name
        row = {"exists": path.is_file()}
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            st = path.stat()
            row.update({
                "size": st.st_size,
                "age_seconds": max(0, int(time.time() - st.st_mtime)),
                "marker_ok": marker in text,
            })
        files[name] = row

    state_files = {}
    for name in (
        "rg_resilience_heartbeat_at",
        "failover_heartbeat_at",
        "RG_CONTROL_CENTER.json",
        "RG_CONTROL_POLICY.json",
        "RG_RESILIENCE_INSTALL.json",
    ):
        path = STATE / name
        row = {"exists": path.is_file()}
        if path.is_file():
            st = path.stat()
            row["age_seconds"] = max(0, int(time.time() - st.st_mtime))
            row["value"] = path.read_text(encoding="utf-8", errors="replace")[-8000:]
        state_files[name] = row

    listener = run([
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-NoProfile", "-NonInteractive", "-Command",
        r"$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'Runner.Listener.exe' -and ($_.CommandLine -like '*C:\RG_GITHUB_RUNNER*' -or $_.ExecutablePath -like 'C:\RG_GITHUB_RUNNER\*') }; $p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    ], timeout=20)

    out = {
        "schema": "RG_CONTROL_PROBE_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "state": state_files,
        "runner": {
            "listener": listener,
            "keepalive": _task_query(TASK_KEEPALIVE),
            "boot": _task_query(TASK_BOOT),
        },
    }
    if do_roundtrip:
        out["auto_edit_roundtrip"] = queue_roundtrip()
    critical_files_ok = all(v.get("exists") and v.get("marker_ok") for v in files.values())
    runner_ok = bool(out["runner"]["keepalive"]["exists"] or out["runner"]["boot"]["exists"])
    roundtrip_ok = bool(out.get("auto_edit_roundtrip", {}).get("ok")) if do_roundtrip else True
    out["status"] = "ok" if critical_files_ok and runner_ok and roundtrip_ok else "degraded"
    atomic_json(STATE / "RG_CONTROL_PROBE.json", out)
    return out


def repair() -> dict:
    before = probe(do_roundtrip=False)
    installation = install()
    after = probe(do_roundtrip=True)
    return {
        "before_status": before.get("status"),
        "installation": installation,
        "after": after,
    }


ACTIONS = {
    "install_rg_resilience": install,
    "probe_rg_resilience": probe,
    "repair_rg_resilience": repair,
}


def main() -> None:
    task_path = Path(sys.argv[1] if len(sys.argv) > 1 else "rg_remote_control/auto_edit_task.json")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    action = str(task.get("action") or "")
    if action not in ACTIONS:
        raise SystemExit("unsupported resilience action: " + action)
    result = ACTIONS[action]()
    print(json.dumps({"action": action, "result": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
