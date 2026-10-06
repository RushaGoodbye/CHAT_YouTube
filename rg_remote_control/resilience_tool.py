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

  $listeners = @(Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" |
    Where-Object { $_.ExecutablePath -like 'C:\RG_GITHUB_RUNNER\*' -or $_.CommandLine -like '*C:\RG_GITHUB_RUNNER*' })
  $launcher = Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" |
    Where-Object { $_.CommandLine -like '*C:\RG_GITHUB_RUNNER*run.cmd*' }

  if ($listeners.Count -gt 1) {
    $ordered = @($listeners | Sort-Object CreationDate)
    $keep = $ordered[0]
    $extras = @($ordered | Select-Object -Skip 1)
    foreach ($x in $extras) {
      Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue
    }
    "$(Get-Date -Format o) DEDUP keep=$($keep.ProcessId) stopped=$($extras.ProcessId -join ',')" | Add-Content -Path $log -Encoding UTF8
    $listeners = @($keep)
  }

  if ($listeners.Count -eq 1) {
    "$(Get-Date -Format o) OK listener=$($listeners[0].ProcessId)" | Add-Content -Path $log -Encoding UTF8
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



AGENT_LOCAL = Path(r"C:\RG_AGENT")
AGENT_NAS = MCP_ROOT / "ALEXPC"
TASK_AGENT_KEEPALIVE = "RG_ALEXPC_AGENT_KEEPALIVE"
TASK_AGENT_BOOT = "RG_ALEXPC_AGENT_BOOT"


def _copy_tree_replace(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def mirror_runtime_bundle_to_nas() -> dict:
    bundle = AGENT_NAS / "BUNDLE"
    bundle.mkdir(parents=True, exist_ok=True)

    copied = {}
    for rel in ("rg_remote_control", "src"):
        source = ROOT / rel
        target = bundle / rel
        if not source.exists():
            copied[rel] = {"ok": False, "reason": "missing", "source": str(source)}
            continue
        _copy_tree_replace(source, target)
        copied[rel] = {"ok": True, "source": str(source), "target": str(target)}

    for name in ("run_app.py", "pyproject.toml", "requirements.txt"):
        source = ROOT / name
        target = bundle / name
        if source.is_file():
            shutil.copy2(source, target)
            copied[name] = {"ok": True, "target": str(target)}
        else:
            copied[name] = {"ok": False, "reason": "missing"}

    manifest = {
        "schema": "RG_ALEXPC_BUNDLE_V1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(ROOT),
        "github_required_at_runtime": False,
    }
    atomic_json(bundle / "bundle_manifest.json", manifest)
    return {"bundle": str(bundle), "copied": copied, "manifest": manifest}


def install_alexpc_agent() -> dict:
    AGENT_LOCAL.mkdir(parents=True, exist_ok=True)
    (AGENT_LOCAL / "state").mkdir(parents=True, exist_ok=True)

    source = ROOT / "rg_remote_control" / "alexpc_agent.py"
    if not source.is_file():
        raise RuntimeError(f"AlexPC agent source missing: {source}")

    mirror = mirror_runtime_bundle_to_nas()
    local_agent = AGENT_LOCAL / "alexpc_agent.py"
    try:
        old_agent_bytes = local_agent.read_bytes() if local_agent.is_file() else b""
    except Exception:
        old_agent_bytes = b""
    new_agent_bytes = source.read_bytes()
    agent_changed = old_agent_bytes != new_agent_bytes
    shutil.copy2(source, local_agent)

    if agent_changed:
        run([
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoProfile", "-NonInteractive", "-Command",
            r"$p=Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*C:\RG_AGENT\alexpc_agent.py*' }; foreach($x in @($p)){ Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }"
        ], timeout=20)
        time.sleep(1)

    python_exe = Path(sys.executable)
    if not python_exe.is_file():
        raise RuntimeError(f"Python executable missing: {python_exe}")

    keepalive = AGENT_LOCAL / "agent_keepalive.ps1"
    keepalive.write_text(
        rf'''$ErrorActionPreference = 'SilentlyContinue'
$agent = 'C:\RG_AGENT\alexpc_agent.py'
$python = '{str(python_exe).replace("'", "''")}'
$mutex = New-Object System.Threading.Mutex($false, 'Global\RG_ALEXPC_AGENT_KEEPALIVE')
$locked = $false
try {{
  $locked = $mutex.WaitOne(0)
  if (-not $locked) {{ exit 0 }}
  $p = @(Get-CimInstance Win32_Process | Where-Object {{
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
    $_.CommandLine -like '*C:\RG_AGENT\alexpc_agent.py*'
  }})
  if ($p.Count -eq 0) {{
    Start-Process -FilePath $python -ArgumentList ('"' + $agent + '"') -WindowStyle Hidden
  }}
}} finally {{
  if ($locked) {{ $mutex.ReleaseMutex() | Out-Null }}
  $mutex.Dispose()
}}
''',
        encoding="utf-8",
    )

    cmd = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "{keepalive}"'
    )
    keep = run([
        r"C:\Windows\System32\schtasks.exe", "/Create",
        "/SC", "MINUTE", "/MO", "1",
        "/TN", TASK_AGENT_KEEPALIVE, "/TR", cmd, "/F"
    ], timeout=30)
    boot = run([
        r"C:\Windows\System32\schtasks.exe", "/Create",
        "/SC", "ONLOGON",
        "/TN", TASK_AGENT_BOOT, "/TR", cmd, "/F"
    ], timeout=30)

    if keep["exit_code"] == 0:
        run([
            r"C:\Windows\System32\schtasks.exe", "/Change",
            "/TN", TASK_AGENT_KEEPALIVE, "/ENABLE"
        ], timeout=20)
    if boot["exit_code"] == 0:
        run([
            r"C:\Windows\System32\schtasks.exe", "/Change",
            "/TN", TASK_AGENT_BOOT, "/ENABLE"
        ], timeout=20)

    appdata = os.environ.get("APPDATA")
    startup_vbs = None
    if appdata:
        startup = (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        startup.mkdir(parents=True, exist_ok=True)
        startup_vbs = startup / "RG_ALEXPC_AGENT.vbs"
        ps = str(keepalive).replace('"', '""')
        startup_vbs.write_text(
            'Set sh = CreateObject("WScript.Shell")\n'
            'sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass '
            '-WindowStyle Hidden -File ""' + ps + '""", 0, False\n',
            encoding="utf-8",
        )

    run_value = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "{keepalive}"'
    )
    registry = run([
        r"C:\Windows\System32\reg.exe",
        "ADD",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
        "/V", "RG_ALEXPC_AGENT",
        "/T", "REG_SZ",
        "/D", run_value,
        "/F",
    ], timeout=20)

    first = run([
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(keepalive)
    ], timeout=30)
    time.sleep(4)

    probe = run([
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-NoProfile", "-NonInteractive", "-Command",
        r"$p=Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*C:\RG_AGENT\alexpc_agent.py*' }; $p | Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    ], timeout=20)

    nas_status = AGENT_NAS / "status" / "alexpc_agent.json"
    startup_ready = bool(startup_vbs and startup_vbs.is_file())
    return {
        "ok": bool(
            keep["exit_code"] == 0
            and (boot["exit_code"] == 0 or startup_ready)
            and probe["stdout"].strip()
            and nas_status.is_file()
        ),
        "agent_changed": agent_changed,
        "startup_ready": startup_ready,
        "python": str(python_exe),
        "local_agent": str(local_agent),
        "keepalive_script": str(keepalive),
        "keepalive_task": keep,
        "boot_task": boot,
        "startup_fallback": str(startup_vbs) if startup_vbs else None,
        "registry_autostart": registry,
        "first_start": first,
        "process_probe": probe,
        "nas_status": str(nas_status),
        "nas_status_exists": nas_status.is_file(),
        "mirror": mirror,
        "github_required_at_runtime": False,
    }


def disable_github_runner_autostart() -> dict:
    schtasks = r"C:\Windows\System32\schtasks.exe"
    disabled = {}
    for name in (
        "RG_GITHUB_RUNNER_KEEPALIVE",
        "RG_GITHUB_RUNNER_BOOT",
        "RG_GITHUB_RUNNER_WATCHDOG",
    ):
        row = run([schtasks, "/Change", "/TN", name, "/DISABLE"], timeout=20)
        disabled[name] = row

    appdata = os.environ.get("APPDATA")
    removed = []
    if appdata:
        startup = (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        for name in (
            "RG_GITHUB_RUNNER_BOOT.vbs",
            "RG_GITHUB_RUNNER.vbs",
            "RG_GITHUB_RUNNER_GUARD.vbs",
        ):
            path = startup / name
            try:
                if path.is_file():
                    path.unlink()
                    removed.append(str(path))
            except Exception:
                pass

    return {
        "autostart_disabled": True,
        "tasks": disabled,
        "startup_files_removed": removed,
        "manual_fallback": r"C:\RG_GITHUB_RUNNER\run.cmd",
        "note": "GitHub runner remains installed for manual fallback, but is no longer a runtime dependency.",
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




def repair_nas_scheduler_runtime() -> dict:
    """Ensure NAS autodeploy, guard and MCP tick are alive without GitHub."""
    ssh = r"C:\WINDOWS\System32\OpenSSH\ssh.exe"
    if not Path(ssh).is_file():
        return {
            "ok": False,
            "reason": "ssh_missing",
            "ssh": ssh,
        }

    script = r'''
set -eu
ROOT=/volume1/docker
STATE="$ROOT/RG_NAS_STATE"
HB="$STATE/rg_resilience_heartbeat_at"
CENTER="$STATE/RG_CONTROL_CENTER.json"

age_file() {
  P="$1"
  if [ ! -f "$P" ]; then
    echo 999999
    return
  fi
  NOW="$(date +%s)"
  MT="$(stat -c %Y "$P" 2>/dev/null || echo 0)"
  echo $((NOW-MT))
}

BEFORE="$(age_file "$HB")"
CONTAINER="missing"
RESTARTED="false"

if docker inspect rg-nas-autodeploy >/dev/null 2>&1; then
  CONTAINER="$(docker inspect -f '{{.State.Status}}' rg-nas-autodeploy 2>/dev/null || echo unknown)"
  if [ "$CONTAINER" != "running" ] || [ "$BEFORE" -gt 120 ]; then
    docker restart rg-nas-autodeploy >/dev/null
    RESTARTED="true"
    sleep 3
    CONTAINER="$(docker inspect -f '{{.State.Status}}' rg-nas-autodeploy 2>/dev/null || echo unknown)"
  fi
fi

# A direct guard/tick pass makes recovery immediate even if the loop is
# between iterations. These scripts are NAS-local and do not use GitHub.
if [ -f "$ROOT/RG_NAS_MCP_GUARD.sh" ]; then
  sh "$ROOT/RG_NAS_MCP_GUARD.sh" >/tmp/rg_guard_repair.log 2>&1 || true
fi
if [ -f "$ROOT/RG_NAS_MCP_TICK.sh" ]; then
  sh "$ROOT/RG_NAS_MCP_TICK.sh" >/tmp/rg_tick_repair.log 2>&1 || true
fi

sleep 2
AFTER="$(age_file "$HB")"
CENTER_AGE="$(age_file "$CENTER")"

printf 'container=%s\n' "$CONTAINER"
printf 'restarted=%s\n' "$RESTARTED"
printf 'heartbeat_age_before=%s\n' "$BEFORE"
printf 'heartbeat_age_after=%s\n' "$AFTER"
printf 'control_center_age=%s\n' "$CENTER_AGE"
printf '%s\n' '---guard---'
tail -n 80 /tmp/rg_guard_repair.log 2>/dev/null || true
printf '%s\n' '---tick---'
tail -n 80 /tmp/rg_tick_repair.log 2>/dev/null || true
'''
    result = run(
        [
            ssh,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=yes",
            "AlexLosServer",
            "sh", "-c", script,
        ],
        timeout=180,
    )

    values = {}
    for line in (result.get("stdout") or "").splitlines():
        if "=" in line and not line.startswith("---"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()

    try:
        hb_after = int(values.get("heartbeat_age_after", "999999"))
    except Exception:
        hb_after = 999999
    try:
        center_after = int(values.get("control_center_age", "999999"))
    except Exception:
        center_after = 999999

    return {
        "ok": bool(
            result["exit_code"] == 0
            and values.get("container") == "running"
            and hb_after <= 120
            and center_after <= 120
        ),
        "values": values,
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][-12000:],
        "stderr": result["stderr"][-12000:],
        "github_required": False,
    }



def stage_mcp_source_to_nas() -> dict:
    source = ROOT / "rg_remote_mcp"
    target = MCP_ROOT / "SOURCE"
    if not source.is_dir():
        raise RuntimeError(f"RG NAS MCP source missing: {source}")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    request = MCP_ROOT / "DEPLOY_REQUEST"
    request.write_text(
        datetime.now(timezone.utc).isoformat() + "\n",
        encoding="utf-8",
    )
    return {
        "source": str(source),
        "target": str(target),
        "deploy_request": str(request),
        "deploy_requested": request.is_file(),
    }


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
    mcp_stage = stage_mcp_source_to_nas()
    nas_scheduler = repair_nas_scheduler_runtime()
    agent = install_alexpc_agent()
    runner_fallback = disable_github_runner_autostart()

    policy = {
        "schema": "RG_CONTROL_POLICY_V1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "primary_transport": "RG_NAS_MCP_ALEXPC_AGENT",
        "fallback_transport": "GITHUB_ACTIONS_MANUAL_ONLY",
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
        "self_heal": "NAS guard + local AlexPC agent keepalive",
        "github_required_at_runtime": False,
    }
    atomic_json(STATE / "RG_CONTROL_POLICY.json", policy)

    result = {
        "schema": "RG_RESILIENCE_INSTALL_V1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "copied": copied,
        "autodeploy_loop": loop,
        "mcp_stage": mcp_stage,
        "nas_scheduler": nas_scheduler,
        "alexpc_agent": agent,
        "github_runner_fallback": runner_fallback,
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


def agent_roundtrip(timeout: int = 70) -> dict:
    base = AGENT_NAS / "auto_edit"
    req_root = base / "requests"
    res_root = base / "results"
    err_root = base / "errors"
    req_root.mkdir(parents=True, exist_ok=True)
    res_root.mkdir(parents=True, exist_ok=True)
    err_root.mkdir(parents=True, exist_ok=True)

    request_id = uuid.uuid4().hex
    req = req_root / f"{request_id}.json"
    result = res_root / f"{request_id}.json"
    error = err_root / f"{request_id}.json"
    atomic_json(req, {
        "request_id": request_id,
        "action": "inspect_auto_edit_stream_result",
        "args": {"stream": "901"},
        "timeout_seconds": 180,
    })

    started = time.time()
    while time.time() - started < timeout:
        if smb_is_file(result):
            try:
                data = json.loads(smb_read_text(result))
            except Exception as exc:
                return {"ok": False, "request_id": request_id, "parse_error": repr(exc)}
            return {
                "ok": bool(data.get("ok")),
                "request_id": request_id,
                "elapsed_seconds": round(time.time() - started, 1),
                "result": data,
            }
        if smb_is_file(error) and smb_size(error):
            try:
                data = json.loads(smb_read_text(error))
            except Exception:
                data = {"raw": smb_read_text(error, 12000)}
            return {
                "ok": False,
                "request_id": request_id,
                "elapsed_seconds": round(time.time() - started, 1),
                "error": data,
            }
        time.sleep(1)
    return {
        "ok": False,
        "request_id": request_id,
        "elapsed_seconds": round(time.time() - started, 1),
        "timeout": True,
        "request_still_exists": smb_is_file(req),
    }



def inspect_resilience_runtime() -> dict:
    def safe_text(path: Path, limit: int = 12000):
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-limit:] if path.is_file() else None
        except Exception as exc:
            return {"error": repr(exc)}

    def inventory(path: Path):
        rows=[]
        try:
            if not path.exists():
                return {"exists": False, "items": []}
            for p in sorted(path.iterdir(), key=lambda x: x.name.casefold()):
                try:
                    rows.append({
                        "name": p.name,
                        "type": "dir" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else None,
                        "age_seconds": max(0, int(time.time()-p.stat().st_mtime)),
                    })
                except Exception as exc:
                    rows.append({"name": p.name, "error": repr(exc)})
            return {"exists": True, "items": rows[:200]}
        except Exception as exc:
            return {"exists": False, "error": repr(exc), "items": rows}

    agent_status = AGENT_NAS / "status" / "alexpc_agent.json"
    local_error = AGENT_LOCAL / "state" / "last_error.json"
    local_status = AGENT_LOCAL / "state" / "agent_status.json"
    deploy_status = STATE / "mcp_deploy_status"
    deploy_log = STATE / "mcp-deploy.log"
    tick_log = STATE / "mcp-tick.log"
    auto_loop = NAS_ROOT / "RG_NAS_AUTODEPLOY_LOOP.sh"
    tick = NAS_ROOT / "RG_NAS_MCP_TICK.sh"

    proc = run([
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-NoProfile","-NonInteractive","-Command",
        r"$p=Get-CimInstance Win32_Process | Where-Object { "
        r"(($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and "
        r"$_.CommandLine -like '*C:\RG_AGENT\alexpc_agent.py*' }; "
        r"$p | Select-Object ProcessId,CreationDate,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    ], timeout=20)

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "agent_process": proc,
        "agent_status": safe_text(agent_status),
        "agent_local_status": safe_text(local_status),
        "agent_last_error": safe_text(local_error),
        "agent_queues": {
            contour: {
                name: inventory(AGENT_NAS / contour / name)
                for name in ("requests","processing","results","errors")
            }
            for contour in ("auto_edit","youtube","telegram")
        },
        "legacy_auto_edit_queues": {
            name: inventory(MCP_ROOT / "AUTO_EDIT_CALLS" / name)
            for name in ("requests","results","errors")
        },
        "deploy": {
            "request_exists": (MCP_ROOT / "DEPLOY_REQUEST").exists(),
            "status": safe_text(deploy_status),
            "log": safe_text(deploy_log, 20000),
        },
        "nas_runtime": {
            "tick_log": safe_text(tick_log, 20000),
            "guard_heartbeat": safe_text(STATE / "rg_resilience_heartbeat_at"),
            "failover_heartbeat": safe_text(STATE / "failover_heartbeat_at"),
            "control_center": safe_text(STATE / "RG_CONTROL_CENTER.json"),
            "autodeploy_loop_exists": auto_loop.is_file(),
            "autodeploy_loop": safe_text(auto_loop, 16000),
            "tick_exists": tick.is_file(),
            "tick": safe_text(tick, 20000),
            "auto_deploy_log": safe_text(STATE / "auto-deploy.log", 20000),
        },
        "nas_ssh_runtime": run([
            r"C:\Windows\System32\OpenSSH\ssh.exe",
            "-o","BatchMode=yes","-o","ConnectTimeout=5","-o","StrictHostKeyChecking=yes",
            "AlexLosServer",
            "sh","-lc",
            "ps w | grep -E 'RG_NAS_(AUTODEPLOY_LOOP|MCP_TICK)' | grep -v grep || true; "
            "docker ps --format '{{.Names}} {{.Status}}' | grep -E 'rg-nas-mcp|rg-mcp-' || true"
        ], timeout=15),
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

    listener_count = 0
    try:
        raw_listener = (listener.get("stdout") or "").strip()
        if raw_listener:
            parsed_listener = json.loads(raw_listener)
            listener_count = len(parsed_listener) if isinstance(parsed_listener, list) else 1
    except Exception:
        listener_count = 0

    out = {
        "schema": "RG_CONTROL_PROBE_V1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "state": state_files,
        "runner": {
            "listener": listener,
            "listener_count": listener_count,
            "keepalive": _task_query(TASK_KEEPALIVE),
            "boot": _task_query(TASK_BOOT),
        },
        "alexpc_agent": {
            "keepalive": _task_query(TASK_AGENT_KEEPALIVE),
            "boot": _task_query(TASK_AGENT_BOOT),
            "startup_fallback_exists": bool(
                os.environ.get("APPDATA")
                and (
                    Path(os.environ["APPDATA"])
                    / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                    / "RG_ALEXPC_AGENT.vbs"
                ).is_file()
            ),
            "nas_status_exists": (AGENT_NAS / "status" / "alexpc_agent.json").is_file(),
            "nas_status_age_seconds": (
                max(0, int(time.time() - (AGENT_NAS / "status" / "alexpc_agent.json").stat().st_mtime))
                if (AGENT_NAS / "status" / "alexpc_agent.json").is_file()
                else None
            ),
        },
    }
    if do_roundtrip:
        out["auto_edit_roundtrip"] = queue_roundtrip()
        out["alexpc_agent_roundtrip"] = agent_roundtrip()
    critical_files_ok = all(v.get("exists") and v.get("marker_ok") for v in files.values())
    agent_info = out.get("alexpc_agent", {})
    agent_ok = bool(
        agent_info.get("keepalive", {}).get("exists")
        and (agent_info.get("boot", {}).get("exists") or agent_info.get("startup_fallback_exists"))
        and agent_info.get("nas_status_exists")
        and agent_info.get("nas_status_age_seconds") is not None
        and agent_info.get("nas_status_age_seconds") <= 30
    )
    guard_state = out.get("state", {})
    guard_ok = bool(
        guard_state.get("rg_resilience_heartbeat_at", {}).get("exists")
        and guard_state.get("rg_resilience_heartbeat_at", {}).get("age_seconds", 9999) <= 120
        and guard_state.get("RG_CONTROL_CENTER.json", {}).get("exists")
        and guard_state.get("RG_CONTROL_CENTER.json", {}).get("age_seconds", 9999) <= 120
    )
    roundtrip_ok = bool(
        (out.get("auto_edit_roundtrip", {}).get("ok") if do_roundtrip else True)
        and (out.get("alexpc_agent_roundtrip", {}).get("ok") if do_roundtrip else True)
    )
    out["health"] = {
        "critical_files_ok": critical_files_ok,
        "alexpc_agent_ok": agent_ok,
        "nas_guard_ok": guard_ok,
        "roundtrip_ok": roundtrip_ok,
        "github_required_at_runtime": False,
    }
    out["status"] = "ok" if critical_files_ok and agent_ok and guard_ok and roundtrip_ok else "degraded"
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
    "inspect_rg_resilience_runtime": inspect_resilience_runtime,
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
