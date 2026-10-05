from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(argv: list[str], cwd: Path | None = None, timeout: int = 600) -> dict:
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        shell=False,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-20000:],
    }


def probe_environment() -> dict:
    import socket

    checks = {
        "nas_share": Path(r"\\AlexLosServer\RG_AUTO_EDIT").exists(),
        "youtube_share": Path(r"\\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL").exists(),
        "ssh_exe": shutil.which("ssh"),
        "powershell_exe": shutil.which("powershell"),
        "pwsh_exe": shutil.which("pwsh"),
        "git_exe": shutil.which("git"),
        "docker_exe": shutil.which("docker"),
    }
    try:
        checks["nas_dns"] = socket.gethostbyname("AlexLosServer")
    except Exception as exc:
        checks["nas_dns_error"] = repr(exc)
    return checks


def stage_remote_mcp_to_nas() -> dict:
    import socket

    source = ROOT / "rg_remote_mcp"
    destination = Path(r"\\AlexLosServer\RG_AUTO_EDIT\REMOTE_MCP\SOURCE")
    if not source.is_dir():
        raise RuntimeError(f"Source not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".env", "secrets", "__pycache__", ".pytest_cache"),
    )
    marker = destination.parent / "STAGED_FROM_GITHUB.txt"
    marker.write_text(
        "RG Remote MCP source staged via AlexPC GitHub runner.\n",
        encoding="utf-8",
    )
    ssh_open = False
    ssh_error = None
    try:
        with socket.create_connection(("192.168.50.32", 22), timeout=3):
            ssh_open = True
    except Exception as exc:
        ssh_error = repr(exc)
    return {
        "destination": str(destination),
        "files_staged": sum(1 for p in destination.rglob("*") if p.is_file()),
        "nas_ssh_port_22": ssh_open,
        "nas_ssh_error": ssh_error,
    }


def probe_ssh_config() -> dict:
    home = Path.home()
    ssh_dir = home / ".ssh"
    files = []
    if ssh_dir.is_dir():
        for p in sorted(ssh_dir.iterdir(), key=lambda x: x.name.casefold()):
            try:
                files.append({
                    "name": p.name,
                    "type": "dir" if p.is_dir() else "file",
                    "size": p.stat().st_size if p.is_file() else None,
                })
            except Exception:
                pass

    resolved = run(
        [r"C:\WINDOWS\System32\OpenSSH\ssh.exe", "-G", "AlexLosServer"],
        timeout=30,
    )
    safe_lines = []
    for line in str(resolved.get("stdout") or "").splitlines():
        key = line.split(" ", 1)[0].casefold() if line else ""
        if key in {
            "hostname", "user", "port", "identityfile",
            "identitiesonly", "stricthostkeychecking",
            "userknownhostsfile",
        }:
            safe_lines.append(line)
    return {
        "ssh_dir_exists": ssh_dir.is_dir(),
        "ssh_files": files,
        "resolved_config": safe_lines,
    }


def probe_nas_ssh_auth() -> dict:
    ssh = r"C:\WINDOWS\System32\OpenSSH\ssh.exe"
    result = run(
        [
            ssh,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=yes",
            "AlexLosServer",
            "echo", "RG_NAS_SSH_OK",
        ],
        timeout=15,
    )
    return {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "authenticated": "RG_NAS_SSH_OK" in result["stdout"],
    }


def probe_nas_mcp_inventory() -> dict:
    root = Path(r"\\AlexLosServer\RG_AUTO_EDIT")
    if not root.is_dir():
        return {"root_exists": False, "matches": []}

    terms = ("telegram", "tg", "mcp", "bot")
    matches = []
    max_depth = 5

    for path in root.rglob("*"):
        try:
            rel = path.relative_to(root)
            if len(rel.parts) > max_depth:
                continue
            name = path.name.casefold()
            if any(term in name for term in terms):
                item = {
                    "path": str(rel),
                    "type": "dir" if path.is_dir() else "file",
                }
                if path.is_file():
                    item["size"] = path.stat().st_size
                matches.append(item)
                if len(matches) >= 250:
                    break
        except Exception:
            continue

    compose_candidates = []
    for path in root.rglob("*"):
        try:
            rel = path.relative_to(root)
            if len(rel.parts) > max_depth or not path.is_file():
                continue
            if path.name.casefold() in {
                "docker-compose.yml",
                "docker-compose.yaml",
                "compose.yml",
                "compose.yaml",
            }:
                text = path.read_text(encoding="utf-8", errors="replace")
                low = text.casefold()
                if any(term in low for term in ("telegram", "mcp", "bot")):
                    compose_candidates.append({
                        "path": str(rel),
                        "snippet": "\n".join(
                            line for line in text.splitlines()
                            if any(term in line.casefold() for term in ("telegram", "mcp", "bot"))
                        )[:4000],
                    })
        except Exception:
            continue

    return {
        "root_exists": True,
        "matches": matches,
        "compose_candidates": compose_candidates,
    }


def probe_nas_telegram_mcp_fast() -> dict:
    root = Path(r"\\AlexLosServer\RG_AUTO_EDIT")
    if not root.is_dir():
        return {"root_exists": False, "matches": []}

    terms = ("telegram", "mcp", "bot")
    queue = [(root, 0)]
    seen_dirs = 0
    matches = []
    compose = []

    while queue and seen_dirs < 500:
        current, depth = queue.pop(0)
        seen_dirs += 1
        try:
            entries = list(current.iterdir())
        except Exception:
            continue

        for path in entries:
            try:
                rel = path.relative_to(root)
                low = path.name.casefold()
                if any(term in low for term in terms):
                    matches.append({
                        "path": str(rel),
                        "type": "dir" if path.is_dir() else "file",
                        "size": path.stat().st_size if path.is_file() else None,
                    })
                if (
                    path.is_file()
                    and path.name.casefold() in {
                        "docker-compose.yml", "docker-compose.yaml",
                        "compose.yml", "compose.yaml",
                    }
                    and path.stat().st_size <= 200000
                ):
                    text = path.read_text(encoding="utf-8", errors="replace")
                    if any(term in text.casefold() for term in terms):
                        compose.append({
                            "path": str(rel),
                            "hits": [
                                line.strip()
                                for line in text.splitlines()
                                if any(term in line.casefold() for term in terms)
                            ][:40],
                        })
                if path.is_dir() and depth < 3:
                    name = path.name.casefold()
                    if name not in {"backups", "cache", "runtime", "__pycache__", ".git"}:
                        queue.append((path, depth + 1))
            except Exception:
                continue

    return {
        "root_exists": True,
        "dirs_scanned": seen_dirs,
        "matches": matches[:200],
        "compose_candidates": compose[:50],
    }


def list_nas_project_roots() -> dict:
    root = Path(r"\\AlexLosServer\RG_AUTO_EDIT")
    if not root.is_dir():
        return {"root_exists": False, "entries": []}
    entries = []
    for p in sorted(root.iterdir(), key=lambda x: x.name.casefold()):
        try:
            item = {"name": p.name, "type": "dir" if p.is_dir() else "file"}
            if p.is_dir():
                children = []
                for c in sorted(p.iterdir(), key=lambda x: x.name.casefold())[:80]:
                    children.append({
                        "name": c.name,
                        "type": "dir" if c.is_dir() else "file",
                    })
                item["children"] = children
            entries.append(item)
        except Exception as exc:
            entries.append({"name": p.name, "error": repr(exc)})
    return {"root_exists": True, "entries": entries}


def probe_nas_shares() -> dict:
    result = run(
        [r"C:\WINDOWS\System32\net.exe", "view", r"\\AlexLosServer"],
        timeout=30,
    )
    return {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def probe_nas_telegram_locations() -> dict:
    roots = [
        Path(r"\\AlexLosServer\RushaGoodbye"),
        Path(r"\\AlexLosServer\docker"),
    ]
    result = {}
    for root in roots:
        items = []
        if root.is_dir():
            for p in sorted(root.iterdir(), key=lambda x: x.name.casefold())[:150]:
                try:
                    item = {"name": p.name, "type": "dir" if p.is_dir() else "file"}
                    if p.is_dir():
                        children = []
                        for c in sorted(p.iterdir(), key=lambda x: x.name.casefold())[:80]:
                            children.append({
                                "name": c.name,
                                "type": "dir" if c.is_dir() else "file",
                            })
                        item["children"] = children
                    items.append(item)
                except Exception as exc:
                    items.append({"name": p.name, "error": repr(exc)})
        result[str(root)] = items
    return result


def probe_telegram_production_layout() -> dict:
    root = Path(r"\\AlexLosServer\docker\RG_DEPLOY")
    monitor = Path(r"\\AlexLosServer\docker\RG_MONITOR")
    work = Path(r"\\AlexLosServer\docker\RG_NAS_WORK")
    out = {}
    for name, path in (("RG_DEPLOY", root), ("RG_MONITOR", monitor), ("RG_NAS_WORK", work)):
        items = []
        if path.is_dir():
            for p in sorted(path.rglob("*"), key=lambda x: str(x).casefold()):
                try:
                    rel = p.relative_to(path)
                    if len(rel.parts) > 3:
                        continue
                    items.append({
                        "path": str(rel),
                        "type": "dir" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else None,
                    })
                    if len(items) >= 250:
                        break
                except Exception:
                    continue
        out[name] = items

    compose = root / "compose.yaml"
    if compose.is_file() and compose.stat().st_size <= 200000:
        text = compose.read_text(encoding="utf-8", errors="replace")
        safe = []
        for line in text.splitlines():
            low = line.casefold()
            if any(secret in low for secret in ("token", "password", "secret", "api_key", "apikey")):
                safe.append(line.split(":", 1)[0] + ": <redacted>")
            else:
                safe.append(line)
        out["compose"] = "\n".join(safe)
    return out


def probe_nas_identity() -> dict:
    ps = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
    cmd = (
        "Get-SmbConnection | "
        "Where-Object {$_.ServerName -ieq 'AlexLosServer'} | "
        "Select-Object ServerName,ShareName,UserName,Dialect | "
        "ConvertTo-Json -Depth 3 -Compress"
    )
    result = run([ps, "-NoProfile", "-Command", cmd], timeout=30)
    return {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "home_share_exists": Path(r"\\AlexLosServer\home").is_dir(),
    }


def probe_nas_home_connection() -> dict:
    result = run(
        [r"C:\WINDOWS\System32\net.exe", "use", r"\\AlexLosServer\home"],
        timeout=30,
    )
    return {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def install_and_probe_nas_ssh_key() -> dict:
    key_dir = Path(r"C:\RG_GITHUB_RUNNER\keys")
    key_dir.mkdir(parents=True, exist_ok=True)
    key = key_dir / "rg_nas_mcp_ed25519"
    pub = Path(str(key) + ".pub")
    keygen = r"C:\WINDOWS\System32\OpenSSH\ssh-keygen.exe"
    ssh = r"C:\WINDOWS\System32\OpenSSH\ssh.exe"

    if not key.is_file() or not pub.is_file():
        generated = run(
            [
                keygen,
                "-t", "ed25519",
                "-N", "",
                "-C", "rg-nas-mcp-alexpc",
                "-f", str(key),
            ],
            timeout=30,
        )
        if generated["exit_code"] != 0:
            raise RuntimeError("ssh-keygen failed: " + generated["stderr"][-1000:])

    public_line = pub.read_text(encoding="utf-8").strip()
    if not public_line.startswith("ssh-ed25519 "):
        raise RuntimeError("Unexpected public key format")

    nas_ssh = Path(r"\\AlexLosServer\home\.ssh")
    nas_ssh.mkdir(parents=True, exist_ok=True)
    authorized = nas_ssh / "authorized_keys"
    existing = authorized.read_text(encoding="utf-8", errors="replace") if authorized.exists() else ""
    if public_line not in existing.splitlines():
        with authorized.open("a", encoding="utf-8", newline="\n") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(public_line + "\n")

    fp = run([keygen, "-lf", str(pub)], timeout=15)
    fingerprint = fp["stdout"].strip()

    attempts = []
    success_user = None
    for user in ("Alex Los", "AlexLos", "alexlos", "fauto"):
        result = run(
            [
                ssh,
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5",
                "-o", "StrictHostKeyChecking=yes",
                "-i", str(key),
                "-l", user,
                "AlexLosServer",
                "echo", "RG_NAS_SSH_OK",
            ],
            timeout=15,
        )
        ok = "RG_NAS_SSH_OK" in result["stdout"]
        attempts.append({
            "user": user,
            "exit_code": result["exit_code"],
            "ok": ok,
            "stderr": result["stderr"][-500:],
        })
        if ok:
            success_user = user
            break

    return {
        "public_key_installed": True,
        "authorized_keys_path": str(authorized),
        "fingerprint": fingerprint,
        "success_user": success_user,
        "attempts": attempts,
        "private_key_path": str(key),
    }


def probe_nas_command_bus() -> dict:
    root = Path(r"\\AlexLosServer\docker")
    targets = [
        root / "RG_NAS_COMMAND_BUS.sh",
        root / "RG_NAS_CONTROL.sh",
        root / "RG_NAS_AUTO_DEPLOY.sh",
    ]
    result = {}
    for path in targets:
        if path.is_file() and path.stat().st_size <= 100000:
            text = path.read_text(encoding="utf-8", errors="replace")
            result[path.name] = text
        else:
            result[path.name] = None

    rc = root / "RG_REMOTE_COMMANDER"
    items = []
    if rc.is_dir():
        for p in sorted(rc.rglob("*"), key=lambda x: str(x).casefold()):
            try:
                rel = p.relative_to(rc)
                if len(rel.parts) <= 3:
                    items.append({
                        "path": str(rel),
                        "type": "dir" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else None,
                    })
                if len(items) >= 200:
                    break
            except Exception:
                continue
    result["RG_REMOTE_COMMANDER"] = items
    return result


def sync_nas_command_bus_mcp() -> dict:
    import hashlib
    from datetime import datetime, timezone

    expected_blob = "a0f5285547ac5653e9cc9b6844fe94032bd60633"
    source = ROOT / "rg_remote_control" / "nas" / "RG_NAS_COMMAND_BUS.sh"
    if not source.is_file():
        raise RuntimeError(f"Vendored command bus missing: {source}")
    payload = source.read_bytes()

    actual_blob = hashlib.sha1(
        f"blob {len(payload)}\0".encode("ascii") + payload
    ).hexdigest()
    if actual_blob != expected_blob:
        raise RuntimeError(
            f"Unexpected command bus blob: {actual_blob}; expected {expected_blob}"
        )
    if b"mcp-deploy)" not in payload or b"mcp-status)" not in payload:
        raise RuntimeError("MCP actions missing from vendored command bus")

    target = Path(r"\\AlexLosServer\docker\RG_NAS_COMMAND_BUS.sh")
    if not target.is_file():
        raise RuntimeError(f"Live command bus missing: {target}")

    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = state / f"RG_NAS_COMMAND_BUS.before_mcp_{stamp}.sh"
    shutil.copy2(target, backup)

    with target.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())

    written = target.read_bytes()
    written_blob = hashlib.sha1(
        f"blob {len(written)}\0".encode("ascii") + written
    ).hexdigest()
    if written_blob != expected_blob:
        with target.open("wb") as handle:
            handle.write(backup.read_bytes())
        raise RuntimeError("Live command bus verification failed; backup restored")

    return {
        "updated": True,
        "git_blob": written_blob,
        "bytes": len(written),
        "backup": str(backup),
        "mcp_actions": ["mcp-deploy", "mcp-status"],
    }

def probe_command_bus_state() -> dict:
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    names = [
        "nas_command_bus_last_id",
        "nas_command_bus_error",
        "scheduler_last_check_at",
        "scheduler_last_check_status",
        "scheduler_dispatch_at",
        "scheduler_dispatch_ok_at",
        "scheduler_dispatch_error",
        "failover_heartbeat_at",
        "failover_mode",
        "failover_takeover_at",
        "failover_last_check_at",
        "failover_last_check_status",
        "last_deploy_status",
        "deploy_stage",
    ]
    out = {}
    for name in names:
        path = state / name
        if path.is_file():
            out[name] = {
                "value": path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()[-2000:],
                "mtime": path.stat().st_mtime,
            }
        else:
            out[name] = None
    audit = state / "nas-command-bus.log"
    if audit.is_file():
        lines = audit.read_text(encoding="utf-8", errors="replace").splitlines()
        out["audit_tail"] = lines[-40:]
    log = state / "auto-deploy.log"
    if log.is_file():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        out["auto_deploy_tail"] = lines[-100:]
    return out


def sync_nas_scheduler_tick() -> dict:
    import hashlib
    from datetime import datetime, timezone

    expected_blob = "499fd06d91fdab32950c69abad04cad27b26beea"
    source = ROOT / "rg_remote_control" / "nas" / "RG_NAS_SCHEDULER_TICK.sh"
    if not source.is_file():
        raise RuntimeError(f"Vendored scheduler missing: {source}")
    payload = source.read_bytes()
    actual_blob = hashlib.sha1(
        f"blob {len(payload)}\0".encode("ascii") + payload
    ).hexdigest()
    if actual_blob != expected_blob:
        raise RuntimeError(
            f"Unexpected scheduler blob: {actual_blob}; expected {expected_blob}"
        )
    if b'sh "$ROOT/RG_NAS_COMMAND_BUS.sh"' not in payload:
        raise RuntimeError("Scheduler does not contain shell-based command bus launch")

    target = Path(r"\\AlexLosServer\docker\RG_NAS_SCHEDULER_TICK.sh")
    if not target.is_file():
        raise RuntimeError(f"Live scheduler missing: {target}")

    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = state / f"RG_NAS_SCHEDULER_TICK.before_mcp_{stamp}.sh"
    shutil.copy2(target, backup)

    with target.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())

    written = target.read_bytes()
    written_blob = hashlib.sha1(
        f"blob {len(written)}\0".encode("ascii") + written
    ).hexdigest()
    if written_blob != expected_blob:
        with target.open("wb") as handle:
            handle.write(backup.read_bytes())
        raise RuntimeError("Scheduler verification failed; backup restored")

    return {
        "updated": True,
        "git_blob": written_blob,
        "bytes": len(written),
        "backup": str(backup),
        "launch_mode": "sh",
    }


def wait_for_mcp_command_bus() -> dict:
    import time

    target_id = "mcp-deploy-20261004-01"
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    last_file = state / "nas_command_bus_last_id"
    error_file = state / "nas_command_bus_error"
    audit_file = state / "nas-command-bus.log"

    started = time.time()
    observations = []
    while time.time() - started < 240:
        last_id = (
            last_file.read_text(encoding="utf-8", errors="replace").strip()
            if last_file.is_file()
            else ""
        )
        error = (
            error_file.read_text(encoding="utf-8", errors="replace").strip()
            if error_file.is_file()
            else ""
        )
        if not observations or observations[-1].get("last_id") != last_id:
            observations.append({
                "elapsed": int(time.time() - started),
                "last_id": last_id or None,
                "error": error or None,
            })
        if last_id == target_id:
            tail = []
            if audit_file.is_file():
                tail = audit_file.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()[-40:]
            return {
                "processed": True,
                "target_id": target_id,
                "elapsed_seconds": int(time.time() - started),
                "observations": observations,
                "audit_tail": tail,
            }
        time.sleep(10)

    return {
        "processed": False,
        "target_id": target_id,
        "elapsed_seconds": int(time.time() - started),
        "observations": observations,
        "current_error": (
            error_file.read_text(encoding="utf-8", errors="replace").strip()
            if error_file.is_file()
            else None
        ),
    }


def probe_scheduler_history() -> dict:
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    files = [
        "scheduler_last_check_at",
        "scheduler_last_check_status",
        "scheduler_dispatch_at",
        "scheduler_dispatch_ok_at",
        "scheduler_dispatch_error",
        "failover_heartbeat_at",
        "failover_mode",
        "failover_takeover_at",
        "failover_last_check_at",
        "failover_last_check_status",
        "last_deploy_status",
        "deploy_stage",
    ]
    out = {}
    for name in files:
        p = state / name
        if p.exists():
            out[name] = {
                "value": p.read_text(encoding="utf-8", errors="replace").strip()[-2000:]
                if p.is_file() else None,
                "mtime": p.stat().st_mtime,
            }
        else:
            out[name] = None
    log = state / "auto-deploy.log"
    if log.is_file():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        out["auto_deploy_tail"] = lines[-120:]
    return out


def probe_contour_mounts() -> dict:
    paths = {
        "youtube": [
            r"\\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL",
        ],
        "telegram": [
            r"\\AlexLosServer\docker\RG_DEPLOY\cloudflare-video-moderation",
            r"\\AlexLosServer\docker\RG_MONITOR\app",
            r"\\AlexLosServer\docker\RG_MONITOR\public_monitor",
            r"\\AlexLosServer\docker\RG_MONITOR\data",
            r"\\AlexLosServer\docker\RG_MONITOR\logs",
            r"\\AlexLosServer\docker\RG_NAS_WORK",
            r"\\AlexLosServer\docker\RG_NAS_STATE",
            r"\\AlexLosServer\docker\RG_NAS_CONTROL",
        ],
        "auto_edit": [
            r"\\AlexLosServer\RG_AUTO_EDIT\BACKUPS",
            r"\\AlexLosServer\RG_AUTO_EDIT\CACHE",
            r"\\AlexLosServer\RG_AUTO_EDIT\CONTROL",
            r"\\AlexLosServer\RG_AUTO_EDIT\DASHBOARD",
            r"\\AlexLosServer\RG_AUTO_EDIT\DATABASE",
            r"\\AlexLosServer\RG_AUTO_EDIT\DIAGNOSTICS",
            r"\\AlexLosServer\RG_AUTO_EDIT\DISASTER_RECOVERY",
            r"\\AlexLosServer\RG_AUTO_EDIT\LEARNING",
            r"\\AlexLosServer\RG_AUTO_EDIT\LOGS",
            r"\\AlexLosServer\RG_AUTO_EDIT\PROJECTS",
            r"\\AlexLosServer\RG_AUTO_EDIT\RUNS",
            r"\\AlexLosServer\RG_AUTO_EDIT\THUMBNAIL_ASSETS",
            r"\\AlexLosServer\RG_AUTO_EDIT\UPDATES",
        ],
    }
    result = {}
    for contour, contour_paths in paths.items():
        result[contour] = [
            {"path": path, "exists": Path(path).exists()}
            for path in contour_paths
        ]
    return result


def probe_nas_cached_identity() -> dict:
    result = run(
        [r"C:\WINDOWS\System32\cmdkey.exe", "/list"],
        timeout=30,
    )
    lines = result["stdout"].splitlines()
    hits = []
    current = []
    for line in lines:
        if line.strip().lower().startswith("target:"):
            if current:
                block = "\n".join(current)
                if "alexlosserver" in block.casefold():
                    hits.append(block)
            current = [line.strip()]
        elif current:
            if line.strip():
                current.append(line.strip())
    if current:
        block = "\n".join(current)
        if "alexlosserver" in block.casefold():
            hits.append(block)
    safe = []
    for block in hits:
        keep = []
        for line in block.splitlines():
            low = line.casefold()
            if low.startswith("target:") or low.startswith("user:") or low.startswith("username:"):
                keep.append(line)
        safe.append(keep)
    return {
        "exit_code": result["exit_code"],
        "entries": safe,
    }


def request_local_mcp_deploy() -> dict:
    import time
    from datetime import datetime, timezone

    remote_root = Path(r"\\AlexLosServer\RG_AUTO_EDIT\REMOTE_MCP")
    source = remote_root / "SOURCE"
    required = [
        source / "docker-compose.yml",
        source / "Dockerfile",
        source / "Dockerfile.worker",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("MCP source incomplete: " + "; ".join(missing))

    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    status_file = state / "mcp_deploy_status"
    log_file = state / "mcp-deploy.log"
    request = remote_root / "DEPLOY_REQUEST"

    before_status_mtime = status_file.stat().st_mtime if status_file.is_file() else 0
    requested_at = datetime.now(timezone.utc).isoformat()
    request.write_text(
        "RG NAS MCP local deploy request\n" + requested_at + "\n",
        encoding="utf-8",
    )
    request_mtime = request.stat().st_mtime

    observations = []
    started = time.time()
    while time.time() - started < 420:
        status = (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else ""
        )
        status_mtime = status_file.stat().st_mtime if status_file.is_file() else 0
        request_exists = request.exists()
        if (
            not observations
            or observations[-1].get("status") != status
            or observations[-1].get("request_exists") != request_exists
        ):
            observations.append({
                "elapsed": int(time.time() - started),
                "status": status or None,
                "request_exists": request_exists,
            })

        fresh = status_mtime >= request_mtime and status_mtime > before_status_mtime
        if fresh and status in {"OK", "ERROR"}:
            log_tail = []
            if log_file.is_file():
                log_tail = log_file.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()[-120:]
            return {
                "requested_at": requested_at,
                "processed": True,
                "status": status,
                "elapsed_seconds": int(time.time() - started),
                "observations": observations,
                "log_tail": log_tail,
            }
        time.sleep(10)

    log_tail = []
    if log_file.is_file():
        log_tail = log_file.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()[-120:]
    return {
        "requested_at": requested_at,
        "processed": False,
        "status": (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else None
        ),
        "request_exists": request.exists(),
        "elapsed_seconds": int(time.time() - started),
        "observations": observations,
        "log_tail": log_tail,
    }


def probe_local_mcp_deploy() -> dict:
    remote_root = Path(r"\\AlexLosServer\RG_AUTO_EDIT\REMOTE_MCP")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    request = remote_root / "DEPLOY_REQUEST"
    status_file = state / "mcp_deploy_status"
    log_file = state / "mcp-deploy.log"
    return {
        "request_exists": request.exists(),
        "status": (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else None
        ),
        "log_tail": (
            log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]
            if log_file.is_file()
            else []
        ),
    }


def probe_remote_commander_runtime() -> dict:
    root = Path(r"\\AlexLosServer\docker\RG_REMOTE_COMMANDER")
    targets = [
        root / "compose.yaml",
        root / "Dockerfile",
        root / "home" / ".claude-server-commander" / "config.json",
        root / "home" / ".desktop-commander-device" / "device.json",
    ]
    out = {}
    for path in targets:
        item = {"exists": path.exists()}
        if path.is_file():
            item["size"] = path.stat().st_size
            if path.name in {"compose.yaml", "Dockerfile"} and path.stat().st_size <= 20000:
                item["content"] = path.read_text(encoding="utf-8", errors="replace")
            elif path.name == "config.json" and path.stat().st_size <= 20000:
                text = path.read_text(encoding="utf-8", errors="replace")
                try:
                    data = json.loads(text)
                    safe = {
                        k: v for k, v in data.items()
                        if k.casefold() not in {"token","password","secret","apikey","api_key"}
                    }
                    item["safe_json"] = safe
                except Exception:
                    item["parse_error"] = True
        out[str(path.relative_to(root))] = item
    return out


def install_live_mcp_autodeploy_hook() -> dict:
    from datetime import datetime, timezone

    live = Path(r"\\AlexLosServer\docker\RG_NAS_AUTO_DEPLOY.sh")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    if not live.is_file():
        raise RuntimeError(f"Live auto-deploy missing: {live}")

    text = live.read_text(encoding="utf-8", errors="replace")
    begin = "# RG_NAS_MCP_LOCAL_HOOK_BEGIN"
    end = "# RG_NAS_MCP_LOCAL_HOOK_END"
    if begin in text and end in text:
        return {"updated": False, "reason": "already_installed"}

    anchor = 'mkdir -p "$STATE_DIR" "$WORK_DIR"\n'
    if anchor not in text:
        raise RuntimeError("Safe insertion anchor not found")

    hook = r'''
# RG_NAS_MCP_LOCAL_HOOK_BEGIN
MCP_LOCAL_DIR="/volume1/RG_AUTO_EDIT/REMOTE_MCP/SOURCE"
MCP_LOCAL_REQUEST="/volume1/RG_AUTO_EDIT/REMOTE_MCP/DEPLOY_REQUEST"
MCP_LOCAL_STATUS="$STATE_DIR/mcp_deploy_status"
MCP_LOCAL_LOG="$STATE_DIR/mcp-deploy.log"

if [ -f "$MCP_LOCAL_REQUEST" ]; then
  printf '%s\n' "RUNNING" > "$MCP_LOCAL_STATUS"
  if [ ! -f "$MCP_LOCAL_DIR/docker-compose.yml" ]; then
    printf '%s\n' "Missing $MCP_LOCAL_DIR/docker-compose.yml" > "$MCP_LOCAL_LOG"
    printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
  elif docker compose version >/dev/null 2>&1; then
    if docker compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" up -d --build > "$MCP_LOCAL_LOG" 2>&1; then
      docker compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" ps >> "$MCP_LOCAL_LOG" 2>&1 || true
      printf '%s\n' "OK" > "$MCP_LOCAL_STATUS"
    else
      printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
    fi
  elif command -v docker-compose >/dev/null 2>&1; then
    if docker-compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" up -d --build > "$MCP_LOCAL_LOG" 2>&1; then
      docker-compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" ps >> "$MCP_LOCAL_LOG" 2>&1 || true
      printf '%s\n' "OK" > "$MCP_LOCAL_STATUS"
    else
      printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
    fi
  else
    printf '%s\n' "Docker Compose unavailable" > "$MCP_LOCAL_LOG"
    printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
  fi
  rm -f "$MCP_LOCAL_REQUEST" 2>/dev/null || true
fi
# RG_NAS_MCP_LOCAL_HOOK_END
'''

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state.mkdir(parents=True, exist_ok=True)
    backup = state / f"RG_NAS_AUTO_DEPLOY.before_mcp_hook_{stamp}.sh"
    shutil.copy2(live, backup)

    updated = text.replace(anchor, anchor + hook + "\n", 1)
    temp = live.with_name(live.name + ".mcp-hook.tmp")
    temp.write_text(updated, encoding="utf-8", newline="\n")
    os.replace(temp, live)

    verify = live.read_text(encoding="utf-8", errors="replace")
    if begin not in verify or end not in verify:
        shutil.copy2(backup, live)
        raise RuntimeError("Hook verification failed; backup restored")

    return {
        "updated": True,
        "backup": str(backup),
        "bytes": live.stat().st_size,
        "hook": "RG_NAS_MCP_LOCAL_HOOK",
    }


def probe_live_mcp_hook() -> dict:
    live = Path(r"\\AlexLosServer\docker\RG_NAS_AUTO_DEPLOY.sh")
    remote_root = Path(r"\\AlexLosServer\RG_AUTO_EDIT\REMOTE_MCP")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    text = live.read_text(encoding="utf-8", errors="replace") if live.is_file() else ""
    status_file = state / "mcp_deploy_status"
    log_file = state / "mcp-deploy.log"
    return {
        "live_exists": live.is_file(),
        "hook_present": "# RG_NAS_MCP_LOCAL_HOOK_BEGIN" in text and "# RG_NAS_MCP_LOCAL_HOOK_END" in text,
        "request_exists": (remote_root / "DEPLOY_REQUEST").exists(),
        "status": status_file.read_text(encoding="utf-8", errors="replace").strip() if status_file.is_file() else None,
        "log_exists": log_file.is_file(),
        "log_tail": log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-80:] if log_file.is_file() else [],
    }


def probe_autodeploy_container_layout() -> dict:
    root = Path(r"\\AlexLosServer\docker")
    matches = []
    names = {
        "compose.yaml", "compose.yml",
        "docker-compose.yaml", "docker-compose.yml"
    }
    queue = [(root, 0)]
    seen = 0
    while queue and seen < 400:
        current, depth = queue.pop(0)
        seen += 1
        try:
            entries = list(current.iterdir())
        except Exception:
            continue
        for path in entries:
            try:
                if path.is_dir() and depth < 3:
                    if path.name.casefold() not in {"rg_nas_work","rg_nas_state","rg_nas_backup","node_modules",".git"}:
                        queue.append((path, depth + 1))
                if path.is_file() and path.name.casefold() in names and path.stat().st_size <= 100000:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    low = text.casefold()
                    if "rg-nas-autodeploy" in low or "rg_nas_auto_deploy" in low or "rg_nas_autodeploy" in low:
                        matches.append({
                            "path": str(path.relative_to(root)),
                            "content": text,
                        })
            except Exception:
                continue
    return {"dirs_scanned": seen, "matches": matches[:20]}


def probe_nas_autodeploy_runtime() -> dict:
    root = Path(r"\\AlexLosServer\docker")
    candidates = []
    for base in [
        root / "RG_NAS_AUTODEPLOY",
        root / "RG_NAS_CONTROL",
        root,
    ]:
        if not base.exists():
            continue
        for name in ("compose.yaml","compose.yml","docker-compose.yml","docker-compose.yaml"):
            path = base / name
            if path.is_file() and path.stat().st_size <= 50000:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "rg-nas-autodeploy" in text.casefold() or "RG_NAS_AUTO_DEPLOY.sh" in text:
                    candidates.append({
                        "path": str(path),
                        "content": text,
                    })
    dockerfiles = []
    for path in root.glob("RG_NAS*/Dockerfile"):
        try:
            if path.stat().st_size <= 50000:
                dockerfiles.append({
                    "path": str(path),
                    "content": path.read_text(encoding="utf-8", errors="replace"),
                })
        except Exception:
            pass
    return {
        "compose_candidates": candidates,
        "dockerfiles": dockerfiles,
        "docker_root_marker": (root / "RG_NAS_STATE").exists(),
        "remote_mcp_under_docker": (root / "RG_NAS_MCP").exists(),
    }


def stage_mcp_to_docker_root() -> dict:
    source = ROOT / "rg_remote_mcp"
    destination = Path(r"\\AlexLosServer\docker\RG_NAS_MCP\SOURCE")
    request = destination.parent / "DEPLOY_REQUEST"
    if not source.is_dir():
        raise RuntimeError(f"Source not found: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            ".env", "secrets", "__pycache__", ".pytest_cache"
        ),
    )
    request.write_text(
        "RG NAS MCP deploy request from AlexPC runner\n",
        encoding="utf-8",
    )
    return {
        "destination": str(destination),
        "files_staged": sum(1 for p in destination.rglob("*") if p.is_file()),
        "request": str(request),
        "request_exists": request.exists(),
    }


def migrate_live_mcp_hook_to_docker_root() -> dict:
    from datetime import datetime, timezone

    live = Path(r"\\AlexLosServer\docker\RG_NAS_AUTO_DEPLOY.sh")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    if not live.is_file():
        raise RuntimeError(f"Live auto-deploy missing: {live}")

    text = live.read_text(encoding="utf-8", errors="replace")
    old_dir = 'MCP_LOCAL_DIR="/volume1/RG_AUTO_EDIT/REMOTE_MCP/SOURCE"'
    old_req = 'MCP_LOCAL_REQUEST="/volume1/RG_AUTO_EDIT/REMOTE_MCP/DEPLOY_REQUEST"'
    new_dir = 'MCP_LOCAL_DIR="/volume1/docker/RG_NAS_MCP/SOURCE"'
    new_req = 'MCP_LOCAL_REQUEST="/volume1/docker/RG_NAS_MCP/DEPLOY_REQUEST"'

    if new_dir in text and new_req in text:
        return {"updated": False, "reason": "already_migrated"}
    if old_dir not in text or old_req not in text:
        raise RuntimeError("Expected MCP hook paths not found")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state.mkdir(parents=True, exist_ok=True)
    backup = state / f"RG_NAS_AUTO_DEPLOY.before_mcp_docker_root_{stamp}.sh"
    shutil.copy2(live, backup)

    updated = text.replace(old_dir, new_dir).replace(old_req, new_req)
    temp = live.with_name(live.name + ".mcp-docker-root.tmp")
    temp.write_text(updated, encoding="utf-8", newline="\n")
    os.replace(temp, live)

    verify = live.read_text(encoding="utf-8", errors="replace")
    if new_dir not in verify or new_req not in verify:
        shutil.copy2(backup, live)
        raise RuntimeError("MCP hook migration failed; backup restored")

    return {
        "updated": True,
        "backup": str(backup),
        "source_root": "/volume1/docker/RG_NAS_MCP/SOURCE",
        "request_path": "/volume1/docker/RG_NAS_MCP/DEPLOY_REQUEST",
    }


def probe_docker_root_mcp_deploy() -> dict:
    remote_root = Path(r"\\AlexLosServer\docker\RG_NAS_MCP")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    request = remote_root / "DEPLOY_REQUEST"
    status_file = state / "mcp_deploy_status"
    log_file = state / "mcp-deploy.log"
    return {
        "source_exists": (remote_root / "SOURCE" / "docker-compose.yml").is_file(),
        "request_exists": request.exists(),
        "status": (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else None
        ),
        "log_tail": (
            log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-160:]
            if log_file.is_file()
            else []
        ),
    }


def wait_docker_root_mcp_deploy() -> dict:
    import time

    remote_root = Path(r"\\AlexLosServer\docker\RG_NAS_MCP")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    request = remote_root / "DEPLOY_REQUEST"
    status_file = state / "mcp_deploy_status"
    log_file = state / "mcp-deploy.log"

    started = time.time()
    observations = []
    while time.time() - started < 480:
        request_exists = request.exists()
        status = (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else ""
        )
        if (
            not observations
            or observations[-1]["request_exists"] != request_exists
            or observations[-1]["status"] != (status or None)
        ):
            observations.append({
                "elapsed": int(time.time() - started),
                "request_exists": request_exists,
                "status": status or None,
            })

        if not request_exists and status in {"OK", "ERROR"}:
            log_tail = (
                log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
                if log_file.is_file()
                else []
            )
            return {
                "processed": True,
                "status": status,
                "elapsed_seconds": int(time.time() - started),
                "observations": observations,
                "log_tail": log_tail,
            }
        time.sleep(10)

    return {
        "processed": False,
        "request_exists": request.exists(),
        "status": (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else None
        ),
        "elapsed_seconds": int(time.time() - started),
        "observations": observations,
        "log_tail": (
            log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            if log_file.is_file()
            else []
        ),
    }


def upgrade_live_mcp_hook_autodetect_volume() -> dict:
    from datetime import datetime, timezone

    live = Path(r"\\AlexLosServer\docker\RG_NAS_AUTO_DEPLOY.sh")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    if not live.is_file():
        raise RuntimeError(f"Live auto-deploy missing: {live}")

    text = live.read_text(encoding="utf-8", errors="replace")
    begin = "# RG_NAS_MCP_LOCAL_HOOK_BEGIN"
    end = "# RG_NAS_MCP_LOCAL_HOOK_END"
    start = text.find(begin)
    finish = text.find(end)
    if start < 0 or finish < 0 or finish < start:
        raise RuntimeError("Existing MCP hook block not found")
    finish += len(end)

    hook = r'''# RG_NAS_MCP_LOCAL_HOOK_BEGIN
MCP_LOCAL_DIR="/volume1/docker/RG_NAS_MCP/SOURCE"
MCP_LOCAL_REQUEST="/volume1/docker/RG_NAS_MCP/DEPLOY_REQUEST"
MCP_LOCAL_STATUS="$STATE_DIR/mcp_deploy_status"
MCP_LOCAL_LOG="$STATE_DIR/mcp-deploy.log"
MCP_AUTO_ROOT_FILE="$STATE_DIR/mcp_auto_edit_host_root"

if [ -f "$MCP_LOCAL_REQUEST" ]; then
  printf '%s\n' "RUNNING" > "$MCP_LOCAL_STATUS"
  : > "$MCP_LOCAL_LOG"

  MCP_AUTO_ROOT=""
  for MCP_CANDIDATE in \
    /volume1/RG_AUTO_EDIT \
    /volume2/RG_AUTO_EDIT \
    /volume3/RG_AUTO_EDIT \
    /volume4/RG_AUTO_EDIT \
    /volume5/RG_AUTO_EDIT \
    /volume6/RG_AUTO_EDIT \
    /volume7/RG_AUTO_EDIT \
    /volume8/RG_AUTO_EDIT
  do
    if docker run --rm \
      --mount "type=bind,src=$MCP_CANDIDATE,dst=/probe,readonly" \
      node:22-bookworm-slim \
      sh -c 'test -d /probe/YOUTUBE_CONTROL' \
      >/dev/null 2>&1
    then
      MCP_AUTO_ROOT="$MCP_CANDIDATE"
      break
    fi
  done

  if [ -z "$MCP_AUTO_ROOT" ]; then
    printf '%s\n' "RG_AUTO_EDIT host root was not found on /volume1..8" >> "$MCP_LOCAL_LOG"
    printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
  elif [ ! -f "$MCP_LOCAL_DIR/docker-compose.yml" ]; then
    printf '%s\n' "Missing $MCP_LOCAL_DIR/docker-compose.yml" >> "$MCP_LOCAL_LOG"
    printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
  else
    printf '%s\n' "$MCP_AUTO_ROOT" > "$MCP_AUTO_ROOT_FILE"
    printf 'RG_AUTO_EDIT_HOST_ROOT=%s\n' "$MCP_AUTO_ROOT" >> "$MCP_LOCAL_LOG"

    if docker compose version >/dev/null 2>&1; then
      if RG_AUTO_EDIT_HOST_ROOT="$MCP_AUTO_ROOT" \
        docker compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" \
        up -d --build >> "$MCP_LOCAL_LOG" 2>&1
      then
        RG_AUTO_EDIT_HOST_ROOT="$MCP_AUTO_ROOT" \
          docker compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" \
          ps >> "$MCP_LOCAL_LOG" 2>&1 || true
        printf '%s\n' "OK" > "$MCP_LOCAL_STATUS"
      else
        printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
      fi
    elif command -v docker-compose >/dev/null 2>&1; then
      if RG_AUTO_EDIT_HOST_ROOT="$MCP_AUTO_ROOT" \
        docker-compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" \
        up -d --build >> "$MCP_LOCAL_LOG" 2>&1
      then
        RG_AUTO_EDIT_HOST_ROOT="$MCP_AUTO_ROOT" \
          docker-compose -p rg-nas-mcp -f "$MCP_LOCAL_DIR/docker-compose.yml" \
          ps >> "$MCP_LOCAL_LOG" 2>&1 || true
        printf '%s\n' "OK" > "$MCP_LOCAL_STATUS"
      else
        printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
      fi
    else
      printf '%s\n' "Docker Compose unavailable" >> "$MCP_LOCAL_LOG"
      printf '%s\n' "ERROR" > "$MCP_LOCAL_STATUS"
    fi
  fi

  rm -f "$MCP_LOCAL_REQUEST" 2>/dev/null || true
fi
# RG_NAS_MCP_LOCAL_HOOK_END'''

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state.mkdir(parents=True, exist_ok=True)
    backup = state / f"RG_NAS_AUTO_DEPLOY.before_mcp_autodetect_{stamp}.sh"
    shutil.copy2(live, backup)

    updated = text[:start] + hook + text[finish:]
    temp = live.with_name(live.name + ".mcp-autodetect.tmp")
    temp.write_text(updated, encoding="utf-8", newline="\n")
    os.replace(temp, live)

    verify = live.read_text(encoding="utf-8", errors="replace")
    if (
        "MCP_AUTO_ROOT_FILE" not in verify
        or "/volume8/RG_AUTO_EDIT" not in verify
        or 'RG_AUTO_EDIT_HOST_ROOT="$MCP_AUTO_ROOT"' not in verify
    ):
        shutil.copy2(backup, live)
        raise RuntimeError("Autodetect hook verification failed; backup restored")

    return {
        "updated": True,
        "backup": str(backup),
        "probe_range": ["/volume1/RG_AUTO_EDIT", "/volume8/RG_AUTO_EDIT"],
        "request_path": "/volume1/docker/RG_NAS_MCP/DEPLOY_REQUEST",
    }


def install_mcp_protocol_smoke_hook() -> dict:
    from datetime import datetime, timezone

    live = Path(r"\\AlexLosServer\docker\RG_NAS_AUTO_DEPLOY.sh")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    if not live.is_file():
        raise RuntimeError(f"Live auto-deploy missing: {live}")

    text = live.read_text(encoding="utf-8", errors="replace")
    marker = "# RG_NAS_MCP_PROTOCOL_SMOKE_HOOK"
    if marker in text:
        return {"updated": False, "reason": "already_installed"}

    anchor = "# RG_NAS_MCP_LOCAL_HOOK_END"
    pos = text.find(anchor)
    if pos < 0:
        raise RuntimeError("MCP deploy hook end marker not found")
    pos += len(anchor)

    hook = r'''

# RG_NAS_MCP_PROTOCOL_SMOKE_HOOK
MCP_SMOKE_REQUEST="/volume1/docker/RG_NAS_MCP/SMOKE_REQUEST"
MCP_SMOKE_STATUS="$STATE_DIR/mcp_smoke_status"
MCP_SMOKE_LOG="$STATE_DIR/mcp-smoke.log"

if [ -f "$MCP_SMOKE_REQUEST" ]; then
  printf '%s\n' "RUNNING" > "$MCP_SMOKE_STATUS"
  if docker inspect rg-nas-mcp-hub >/dev/null 2>&1; then
    if docker exec rg-nas-mcp-hub python -m rg_remote_mcp.smoke > "$MCP_SMOKE_LOG" 2>&1; then
      printf '%s\n' "OK" > "$MCP_SMOKE_STATUS"
    else
      printf '%s\n' "ERROR" > "$MCP_SMOKE_STATUS"
    fi
  else
    printf '%s\n' "rg-nas-mcp-hub missing" > "$MCP_SMOKE_LOG"
    printf '%s\n' "ERROR" > "$MCP_SMOKE_STATUS"
  fi
  rm -f "$MCP_SMOKE_REQUEST" 2>/dev/null || true
fi
'''

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state.mkdir(parents=True, exist_ok=True)
    backup = state / f"RG_NAS_AUTO_DEPLOY.before_mcp_smoke_{stamp}.sh"
    shutil.copy2(live, backup)

    updated = text[:pos] + hook + text[pos:]
    temp = live.with_name(live.name + ".mcp-smoke.tmp")
    temp.write_text(updated, encoding="utf-8", newline="\n")
    os.replace(temp, live)

    verify = live.read_text(encoding="utf-8", errors="replace")
    if marker not in verify or "rg_remote_mcp.smoke" not in verify:
        shutil.copy2(backup, live)
        raise RuntimeError("MCP smoke hook verification failed; backup restored")

    return {
        "updated": True,
        "backup": str(backup),
        "request_path": "/volume1/docker/RG_NAS_MCP/SMOKE_REQUEST",
    }


def request_mcp_protocol_smoke() -> dict:
    import time
    from datetime import datetime, timezone

    root = Path(r"\\AlexLosServer\docker\RG_NAS_MCP")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")
    request = root / "SMOKE_REQUEST"
    status_file = state / "mcp_smoke_status"
    log_file = state / "mcp-smoke.log"

    before = status_file.stat().st_mtime if status_file.is_file() else 0
    request.write_text(
        datetime.now(timezone.utc).isoformat() + "\n",
        encoding="utf-8",
    )
    request_mtime = request.stat().st_mtime

    started = time.time()
    observations = []
    while time.time() - started < 420:
        status = (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else ""
        )
        mtime = status_file.stat().st_mtime if status_file.is_file() else 0
        exists = request.exists()
        if (
            not observations
            or observations[-1]["status"] != (status or None)
            or observations[-1]["request_exists"] != exists
        ):
            observations.append({
                "elapsed": int(time.time() - started),
                "status": status or None,
                "request_exists": exists,
            })
        fresh = mtime >= request_mtime and mtime > before
        if fresh and not exists and status in {"OK", "ERROR"}:
            return {
                "processed": True,
                "status": status,
                "elapsed_seconds": int(time.time() - started),
                "observations": observations,
                "log": (
                    log_file.read_text(encoding="utf-8", errors="replace")[-20000:]
                    if log_file.is_file()
                    else ""
                ),
            }
        time.sleep(10)

    return {
        "processed": False,
        "status": (
            status_file.read_text(encoding="utf-8", errors="replace").strip()
            if status_file.is_file()
            else None
        ),
        "request_exists": request.exists(),
        "observations": observations,
        "log": (
            log_file.read_text(encoding="utf-8", errors="replace")[-20000:]
            if log_file.is_file()
            else ""
        ),
    }


def enable_one_minute_mcp_tick() -> dict:
    from datetime import datetime, timezone

    source = ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_TICK.sh"
    live_tick = Path(r"\\AlexLosServer\docker\RG_NAS_MCP_TICK.sh")
    live_loop = Path(r"\\AlexLosServer\docker\RG_NAS_AUTODEPLOY_LOOP.sh")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")

    if not source.is_file():
        raise RuntimeError(f"Tick source missing: {source}")
    if not live_loop.is_file():
        raise RuntimeError(f"Live loop missing: {live_loop}")

    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    tick_backup = None
    if live_tick.is_file():
        tick_backup = state / f"RG_NAS_MCP_TICK.before_1min_{stamp}.sh"
        shutil.copy2(live_tick, tick_backup)
    shutil.copy2(source, live_tick)

    loop_text = live_loop.read_text(encoding="utf-8", errors="replace")
    loop_backup = state / f"RG_NAS_AUTODEPLOY_LOOP.before_mcp_1min_{stamp}.sh"
    shutil.copy2(live_loop, loop_backup)

    block = (
        '  if [ -f "$ROOT/RG_NAS_MCP_TICK.sh" ]; then\n'
        '    sh "$ROOT/RG_NAS_MCP_TICK.sh" >> "$STATE/mcp-tick.log" 2>&1 || true\n'
        '  fi\n\n'
    )
    if "RG_NAS_MCP_TICK.sh" not in loop_text:
        anchor = '  SCHED_AGE="$(heartbeat_age "$SCHEDULER_HEARTBEAT")"\n\n'
        if anchor not in loop_text:
            raise RuntimeError("Live loop insertion anchor not found")
        loop_text = loop_text.replace(anchor, anchor + block, 1)
        temp = live_loop.with_name(live_loop.name + ".mcp-1min.tmp")
        temp.write_text(loop_text, encoding="utf-8", newline="\n")
        os.replace(temp, live_loop)

    verify_loop = live_loop.read_text(encoding="utf-8", errors="replace")
    verify_tick = live_tick.read_text(encoding="utf-8", errors="replace")
    if 'CHECK_INTERVAL=60' not in verify_loop:
        raise RuntimeError("Live loop is not configured for 60-second checks")
    if "RG_NAS_MCP_TICK.sh" not in verify_loop:
        raise RuntimeError("MCP tick invocation was not installed")
    if 'SMOKE_REQUEST' not in verify_tick or 'DEPLOY_REQUEST' not in verify_tick:
        raise RuntimeError("MCP tick script verification failed")

    return {
        "enabled": True,
        "interval_seconds": 60,
        "tick_path": str(live_tick),
        "loop_path": str(live_loop),
        "loop_backup": str(loop_backup),
        "tick_backup": str(tick_backup) if tick_backup else None,
        "production_autodeploy_interval_unchanged": True,
    }


def run_telegram_mcp_smoke() -> dict:
    ssh = r"C:\\WINDOWS\\System32\\OpenSSH\\ssh.exe"
    result = run(
        [
            ssh,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=yes",
            "AlexLosServer",
            "docker", "exec", "rg-nas-mcp-hub",
            "python", "-m", "rg_remote_mcp.telegram_smoke",
        ],
        timeout=120,
    )
    return {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "telegram_only": True,
    }


def probe_cloudflare_mcp_gateway_options() -> dict:
    roots = [
        Path(r"\\AlexLosServer\docker"),
        Path(r"\\AlexLosServer\RG_AUTO_EDIT"),
    ]
    terms = ("cloudflared", "cloudflare", "tunnel")
    matches = []
    max_files = 3000
    seen = 0
    for root in roots:
        if not root.exists():
            continue
        queue = [(root, 0)]
        while queue and seen < max_files:
            current, depth = queue.pop(0)
            try:
                entries = list(current.iterdir())
            except Exception:
                continue
            for path in entries:
                seen += 1
                try:
                    low = path.name.casefold()
                    if any(term in low for term in terms):
                        matches.append({
                            "path": str(path),
                            "type": "dir" if path.is_dir() else "file",
                            "size": path.stat().st_size if path.is_file() else None,
                        })
                    if path.is_dir() and depth < 3:
                        if low not in {"backups","cache","logs",".git","runtime"}:
                            queue.append((path, depth+1))
                except Exception:
                    continue
    return {
        "matches": matches[:200],
        "scanned": seen,
    }


def telegram_mcp_call() -> dict:
    import asyncio
    import importlib.util

    task_path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "rg_remote_control" / "task.json")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    args = task.get("args") or {}
    tool = str(args.get("tool") or "").strip()
    tool_args = args.get("tool_args") or {}

    if not tool.startswith("telegram_"):
        raise RuntimeError("Only telegram_* RG NAS MCP tools are allowed")
    if not isinstance(tool_args, dict):
        raise RuntimeError("tool_args must be an object")

    if importlib.util.find_spec("mcp") is None:
        install = run(
            [sys.executable, "-m", "pip", "install", "--user", "mcp==2.3.0"],
            timeout=300,
        )
        if install["exit_code"] != 0:
            raise RuntimeError(
                "Failed to install MCP client: " + install["stderr"]
            )

    from mcp import Client

    async def _call():
        async with Client("http://192.168.50.32:8765/mcp") as client:
            result = await client.call_tool(tool, tool_args)
            content = []
            for item in result.content or []:
                entry = {"type": getattr(item, "type", None)}
                text_value = getattr(item, "text", None)
                if text_value is not None:
                    entry["text"] = text_value
                content.append(entry)
            return {
                "tool": tool,
                "is_error": bool(result.is_error),
                "structured_content": result.structured_content,
                "content": content,
            }

    return asyncio.run(_call())


def enable_auto_edit_mcp_bridge() -> dict:
    from datetime import datetime, timezone

    source_tick = ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_TICK.sh"
    source_helper = ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_AUTO_EDIT_CALL.py"
    live_tick = Path(r"\\AlexLosServer\docker\RG_NAS_MCP_TICK.sh")
    live_helper = Path(r"\\AlexLosServer\docker\RG_NAS_MCP_AUTO_EDIT_CALL.py")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")

    if not source_tick.is_file() or not source_helper.is_file():
        raise RuntimeError("Auto Edit MCP bridge sources are missing")

    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    backups = {}
    for live, source, label in (
        (live_tick, source_tick, "tick"),
        (live_helper, source_helper, "helper"),
    ):
        if live.is_file():
            backup = state / f"{live.name}.before_auto_edit_bridge_{stamp}"
            shutil.copy2(live, backup)
            backups[label] = str(backup)
        shutil.copy2(source, live)

    tick_text = live_tick.read_text(encoding="utf-8", errors="replace")
    helper_text = live_helper.read_text(encoding="utf-8", errors="replace")
    if "AUTO_EDIT_CALL_ROOT" not in tick_text:
        raise RuntimeError("Auto Edit call queue is missing from live MCP tick")
    if 'tool.startswith("auto_edit_")' not in helper_text:
        raise RuntimeError("Auto Edit-only tool guard is missing from live helper")
    if "YOUTUBE_CALL_ROOT" not in tick_text:
        raise RuntimeError("YouTube call queue disappeared from shared MCP tick")

    return {
        "enabled": True,
        "interval_seconds": 60,
        "tick": str(live_tick),
        "helper": str(live_helper),
        "backups": backups,
        "youtube_queue_preserved": True,
    }


def probe_auto_edit_mcp_bridge() -> dict:
    import time

    root = Path(r"\\AlexLosServer\docker")
    mcp_root = root / "RG_NAS_MCP"
    state = root / "RG_NAS_STATE"
    live_loop = root / "RG_NAS_AUTODEPLOY_LOOP.sh"
    live_tick = root / "RG_NAS_MCP_TICK.sh"
    live_helper = root / "RG_NAS_MCP_AUTO_EDIT_CALL.py"
    tick_log = state / "mcp-tick.log"
    heartbeat = state / "failover_heartbeat_at"
    requests = mcp_root / "AUTO_EDIT_CALLS" / "requests"
    results = mcp_root / "AUTO_EDIT_CALLS" / "results"
    errors = mcp_root / "AUTO_EDIT_CALLS" / "errors"

    def info(path: Path) -> dict:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        return {
            "exists": True,
            "size": stat.st_size if path.is_file() else None,
            "mtime_epoch": int(stat.st_mtime),
            "age_seconds": max(0, int(time.time() - stat.st_mtime)),
        }

    loop_text = live_loop.read_text(encoding="utf-8", errors="replace") if live_loop.is_file() else ""
    tick_text = live_tick.read_text(encoding="utf-8", errors="replace") if live_tick.is_file() else ""

    return {
        "loop": {
            **info(live_loop),
            "has_tick_call": "RG_NAS_MCP_TICK.sh" in loop_text,
            "check_interval_60": "CHECK_INTERVAL=60" in loop_text,
        },
        "tick": {
            **info(live_tick),
            "has_auto_edit_queue": "AUTO_EDIT_CALL_ROOT" in tick_text,
            "has_youtube_queue": "YOUTUBE_CALL_ROOT" in tick_text,
        },
        "helper": info(live_helper),
        "tick_log": {
            **info(tick_log),
            "tail": (
                tick_log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
                if tick_log.is_file()
                else []
            ),
        },
        "failover_heartbeat": {
            **info(heartbeat),
            "value": (
                heartbeat.read_text(encoding="utf-8", errors="replace").strip()
                if heartbeat.is_file()
                else None
            ),
        },
        "queues": {
            "requests": sorted(p.name for p in requests.glob("*.json")) if requests.is_dir() else [],
            "results": sorted(p.name for p in results.glob("*.json")) if results.is_dir() else [],
            "errors": sorted(p.name for p in errors.glob("*.log")) if errors.is_dir() else [],
        },
    }


def enable_youtube_mcp_bridge() -> dict:
    from datetime import datetime, timezone

    source_tick = ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_TICK.sh"
    source_helper = ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_YOUTUBE_CALL.py"
    live_tick = Path(r"\\AlexLosServer\docker\RG_NAS_MCP_TICK.sh")
    live_helper = Path(r"\\AlexLosServer\docker\RG_NAS_MCP_YOUTUBE_CALL.py")
    state = Path(r"\\AlexLosServer\docker\RG_NAS_STATE")

    if not source_tick.is_file() or not source_helper.is_file():
        raise RuntimeError("YouTube MCP bridge sources are missing")

    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    backups = {}
    for live, source, label in (
        (live_tick, source_tick, "tick"),
        (live_helper, source_helper, "helper"),
    ):
        if live.is_file():
            backup = state / f"{live.name}.before_youtube_bridge_{stamp}"
            shutil.copy2(live, backup)
            backups[label] = str(backup)
        shutil.copy2(source, live)

    tick_text = live_tick.read_text(encoding="utf-8", errors="replace")
    helper_text = live_helper.read_text(encoding="utf-8", errors="replace")
    if "YOUTUBE_CALL_ROOT" not in tick_text:
        raise RuntimeError("YouTube call queue is missing from live MCP tick")
    if 'tool.startswith("youtube_")' not in helper_text:
        raise RuntimeError("YouTube-only tool guard is missing from live helper")

    return {
        "enabled": True,
        "interval_seconds": 60,
        "tick": str(live_tick),
        "helper": str(live_helper),
        "backups": backups,
    }


def probe_youtube_mcp_bridge() -> dict:
    import time

    root = Path(r"\\AlexLosServer\docker")
    mcp_root = root / "RG_NAS_MCP"
    state = root / "RG_NAS_STATE"
    live_loop = root / "RG_NAS_AUTODEPLOY_LOOP.sh"
    live_tick = root / "RG_NAS_MCP_TICK.sh"
    live_helper = root / "RG_NAS_MCP_YOUTUBE_CALL.py"
    tick_log = state / "mcp-tick.log"
    heartbeat = state / "failover_heartbeat_at"
    requests = mcp_root / "YOUTUBE_CALLS" / "requests"
    results = mcp_root / "YOUTUBE_CALLS" / "results"
    errors = mcp_root / "YOUTUBE_CALLS" / "errors"

    def info(path: Path) -> dict:
        if not path.exists():
            return {"exists": False}
        stat = path.stat()
        return {
            "exists": True,
            "size": stat.st_size if path.is_file() else None,
            "mtime_epoch": int(stat.st_mtime),
            "age_seconds": max(0, int(time.time() - stat.st_mtime)),
        }

    loop_text = live_loop.read_text(encoding="utf-8", errors="replace") if live_loop.is_file() else ""
    tick_text = live_tick.read_text(encoding="utf-8", errors="replace") if live_tick.is_file() else ""

    return {
        "loop": {
            **info(live_loop),
            "has_tick_call": "RG_NAS_MCP_TICK.sh" in loop_text,
            "check_interval_60": "CHECK_INTERVAL=60" in loop_text,
        },
        "tick": {
            **info(live_tick),
            "has_youtube_queue": "YOUTUBE_CALL_ROOT" in tick_text,
        },
        "helper": info(live_helper),
        "tick_log": {
            **info(tick_log),
            "tail": (
                tick_log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
                if tick_log.is_file()
                else []
            ),
        },
        "failover_heartbeat": {
            **info(heartbeat),
            "value": (
                heartbeat.read_text(encoding="utf-8", errors="replace").strip()
                if heartbeat.is_file()
                else None
            ),
        },
        "queues": {
            "requests": sorted(p.name for p in requests.glob("*.json")) if requests.is_dir() else [],
            "results": sorted(p.name for p in results.glob("*.json")) if results.is_dir() else [],
            "errors": sorted(p.name for p in errors.glob("*.log")) if errors.is_dir() else [],
        },
    }



def probe_youtube_tick_runtime() -> dict:
    import time

    root = Path(r"\\AlexLosServer\docker")
    state = root / "RG_NAS_STATE"
    mcp_root = root / "RG_NAS_MCP"
    live_loop = root / "RG_NAS_AUTODEPLOY_LOOP.sh"
    live_tick = root / "RG_NAS_MCP_TICK.sh"
    requests = mcp_root / "YOUTUBE_CALLS" / "requests"
    results = mcp_root / "YOUTUBE_CALLS" / "results"
    errors = mcp_root / "YOUTUBE_CALLS" / "errors"

    loop_text = live_loop.read_text(encoding="utf-8", errors="replace") if live_loop.is_file() else ""
    loop_lines = loop_text.splitlines()
    tick_context = []
    for i, line in enumerate(loop_lines):
        if "RG_NAS_MCP_TICK.sh" in line:
            start = max(0, i - 8)
            end = min(len(loop_lines), i + 12)
            for n in range(start, end):
                text_line = loop_lines[n]
                low = text_line.casefold()
                if any(key in low for key in ("token", "password", "secret", "api_key", "apikey")):
                    text_line = text_line.split("=", 1)[0] + "=<redacted>"
                tick_context.append({"line": n + 1, "text": text_line})
            break

    request_details = []
    if requests.is_dir():
        for path in sorted(requests.glob("*.json"))[:20]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                request_details.append({
                    "name": path.name,
                    "age_seconds": max(0, int(time.time() - path.stat().st_mtime)),
                    "request_id": str(payload.get("request_id") or ""),
                    "tool": str(payload.get("tool") or ""),
                    "tool_args_keys": sorted((payload.get("tool_args") or {}).keys())
                        if isinstance(payload.get("tool_args") or {}, dict)
                        else [],
                })
            except Exception as exc:
                request_details.append({"name": path.name, "error": repr(exc)})

    ssh = r"C:\WINDOWS\System32\OpenSSH\ssh.exe"
    ssh_result = run(
        [
            ssh,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=yes",
            "AlexLosServer",
            "sh", "/volume1/docker/RG_NAS_MCP_TICK.sh",
        ],
        timeout=90,
    )

    def names(path: Path, pattern: str) -> list[str]:
        return sorted(p.name for p in path.glob(pattern)) if path.is_dir() else []

    tick_log = state / "mcp-tick.log"
    return {
        "loop_exists": live_loop.is_file(),
        "tick_exists": live_tick.is_file(),
        "tick_context": tick_context,
        "requests_before_manual_tick": request_details,
        "manual_tick": {
            "exit_code": ssh_result["exit_code"],
            "stdout": ssh_result["stdout"][-8000:],
            "stderr": ssh_result["stderr"][-8000:],
        },
        "queues_after_manual_tick": {
            "requests": names(requests, "*.json"),
            "results": names(results, "*.json"),
            "errors": names(errors, "*.log"),
        },
        "tick_log": {
            "exists": tick_log.is_file(),
            "tail": (
                tick_log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
                if tick_log.is_file()
                else []
            ),
        },
    }



def youtube_mcp_batch() -> dict:
    import time
    import uuid

    task_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else ROOT / "rg_remote_control" / "youtube_task.json"
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    args = task.get("args") or {}
    calls = args.get("calls") or []
    if not isinstance(calls, list) or not calls:
        raise RuntimeError("calls must be a non-empty array")
    if len(calls) > 30:
        raise RuntimeError("youtube_mcp_batch supports at most 30 calls")

    root = Path(r"\\AlexLosServer\docker\RG_NAS_MCP\YOUTUBE_CALLS")
    requests = root / "requests"
    results = root / "results"
    errors = root / "errors"
    requests.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    errors.mkdir(parents=True, exist_ok=True)

    pending = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise RuntimeError(f"call {index} must be an object")
        tool = str(call.get("tool") or "").strip()
        tool_args = call.get("tool_args") or {}
        if not tool.startswith("youtube_"):
            raise RuntimeError(f"call {index}: only youtube_* tools are allowed")
        if not isinstance(tool_args, dict):
            raise RuntimeError(f"call {index}: tool_args must be an object")

        request_id = uuid.uuid4().hex
        request_file = requests / f"{request_id}.json"
        payload = {
            "request_id": request_id,
            "tool": tool,
            "tool_args": tool_args,
        }
        temp = request_file.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, request_file)
        pending.append({
            "index": index,
            "request_id": request_id,
            "tool": tool,
            "request_file": request_file,
            "result_file": results / f"{request_id}.json",
            "error_file": errors / f"{request_id}.log",
        })

    started = time.time()
    timeout_seconds = max(90, min(180, int(args.get("timeout_seconds") or 120)))
    finished = {}

    while time.time() - started < timeout_seconds and len(finished) < len(pending):
        for item in pending:
            index = item["index"]
            if index in finished:
                continue
            result_file = item["result_file"]
            error_file = item["error_file"]
            request_file = item["request_file"]

            try:
                result_ready = result_file.is_file()
                error_ready = error_file.is_file()
                request_exists = request_file.exists()
            except OSError as exc:
                # SMB shares can briefly return WinError 59 while the NAS is
                # reachable. Treat that as a transient transport condition and
                # retry on the next polling cycle instead of failing the batch.
                item["last_fs_error"] = repr(exc)
                continue

            if result_ready:
                try:
                    payload = json.loads(
                        result_file.read_text(encoding="utf-8", errors="replace")
                    )
                except OSError as exc:
                    item["last_fs_error"] = repr(exc)
                    continue
                except Exception as exc:
                    payload = {
                        "request_id": item["request_id"],
                        "tool": item["tool"],
                        "is_error": True,
                        "error": f"invalid result JSON: {exc!r}",
                    }
                try:
                    result_file.unlink()
                except Exception:
                    pass
                finished[index] = payload
                continue

            if error_ready and not request_exists:
                try:
                    error = error_file.read_text(
                        encoding="utf-8", errors="replace"
                    )[-12000:]
                except OSError as exc:
                    item["last_fs_error"] = repr(exc)
                    continue
                try:
                    error_file.unlink()
                except Exception:
                    pass
                finished[index] = {
                    "request_id": item["request_id"],
                    "tool": item["tool"],
                    "is_error": True,
                    "error": error,
                }

        if len(finished) < len(pending):
            time.sleep(2)

    timed_out = []
    for item in pending:
        if item["index"] not in finished:
            timed_out.append({
                "index": item["index"],
                "request_id": item["request_id"],
                "tool": item["tool"],
            })

    ordered = []
    for item in pending:
        index = item["index"]
        ordered.append({
            "index": index,
            **finished.get(index, {
                "request_id": item["request_id"],
                "tool": item["tool"],
                "is_error": True,
                "error": "timeout",
            }),
        })

    return {
        "transport": "RG NAS MCP YouTube bridge batch",
        "elapsed_seconds": int(time.time() - started),
        "count": len(pending),
        "completed": len(finished),
        "timed_out": timed_out,
        "results": ordered,
    }


def youtube_mcp_call() -> dict:
    import time
    import uuid

    task_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else ROOT / "rg_remote_control" / "youtube_task.json"
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    args = task.get("args") or {}
    tool = str(args.get("tool") or "").strip()
    tool_args = args.get("tool_args") or {}

    if not tool.startswith("youtube_"):
        raise RuntimeError("Only youtube_* RG NAS MCP tools are allowed")
    if not isinstance(tool_args, dict):
        raise RuntimeError("tool_args must be an object")

    root = Path(r"\\AlexLosServer\docker\RG_NAS_MCP\YOUTUBE_CALLS")
    requests = root / "requests"
    results = root / "results"
    errors = root / "errors"
    requests.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    errors.mkdir(parents=True, exist_ok=True)

    request_id = uuid.uuid4().hex
    request_file = requests / f"{request_id}.json"
    result_file = results / f"{request_id}.json"
    error_file = errors / f"{request_id}.log"

    payload = {
        "request_id": request_id,
        "tool": tool,
        "tool_args": tool_args,
    }
    temp = request_file.with_suffix(".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temp, request_file)

    started = time.time()
    timeout_seconds = 90
    last_fs_error = None
    while time.time() - started < timeout_seconds:
        try:
            result_ready = result_file.is_file()
            error_ready = error_file.is_file()
            request_exists = request_file.exists()
        except OSError as exc:
            last_fs_error = repr(exc)
            time.sleep(2)
            continue

        if result_ready:
            try:
                result = json.loads(
                    result_file.read_text(encoding="utf-8", errors="replace")
                )
            except OSError as exc:
                last_fs_error = repr(exc)
                time.sleep(2)
                continue
            try:
                result_file.unlink()
            except Exception:
                pass
            return {
                "transport": "RG NAS MCP YouTube bridge",
                "elapsed_seconds": int(time.time() - started),
                **result,
            }
        if error_ready and not request_exists:
            try:
                error = error_file.read_text(
                    encoding="utf-8", errors="replace"
                )[-12000:]
            except OSError as exc:
                last_fs_error = repr(exc)
                time.sleep(2)
                continue
            try:
                error_file.unlink()
            except Exception:
                pass
            raise RuntimeError("RG NAS MCP YouTube call failed: " + error)
        time.sleep(2)

    raise RuntimeError(
        f"RG NAS MCP YouTube call timed out after {timeout_seconds}s"
    )


def auto_edit_mcp_call() -> dict:
    import time
    import uuid

    task_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else ROOT / "rg_remote_control" / "auto_edit_task.json"
    )
    task = json.loads(task_path.read_text(encoding="utf-8"))
    args = task.get("args") or {}
    tool = str(args.get("tool") or "").strip()
    tool_args = args.get("tool_args") or {}

    if not tool.startswith("auto_edit_"):
        raise RuntimeError("Only auto_edit_* RG NAS MCP tools are allowed")
    if not isinstance(tool_args, dict):
        raise RuntimeError("tool_args must be an object")

    if os.name == "nt":
        root = Path(r"\\AlexLosServer\docker\RG_NAS_MCP\AUTO_EDIT_CALLS")
        requests = root / "requests"
        results = root / "results"
        errors = root / "errors"
        requests.mkdir(parents=True, exist_ok=True)
        results.mkdir(parents=True, exist_ok=True)
        errors.mkdir(parents=True, exist_ok=True)

        request_id = uuid.uuid4().hex
        request_file = requests / f"{request_id}.json"
        result_file = results / f"{request_id}.json"
        error_file = errors / f"{request_id}.log"

        payload = {
            "request_id": request_id,
            "tool": tool,
            "tool_args": tool_args,
        }
        temp = request_file.with_suffix(".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temp, request_file)

        started = time.time()
        timeout_seconds = 150
        while time.time() - started < timeout_seconds:
            if result_file.is_file():
                result = json.loads(
                    result_file.read_text(encoding="utf-8", errors="replace")
                )
                try:
                    result_file.unlink()
                except Exception:
                    pass
                return {
                    "transport": "RG NAS MCP Auto Edit queue bridge",
                    "elapsed_seconds": int(time.time() - started),
                    **result,
                }
            if error_file.is_file() and not request_file.exists():
                error = error_file.read_text(
                    encoding="utf-8", errors="replace"
                )[-12000:]
                try:
                    error_file.unlink()
                except Exception:
                    pass
                raise RuntimeError(
                    "RG NAS MCP Auto Edit call failed: " + error
                )
            time.sleep(2)

        raise RuntimeError(
            f"RG NAS MCP Auto Edit call timed out after {timeout_seconds}s"
        )

    import tempfile

    helper = ROOT / "rg_remote_control" / "nas" / "RG_NAS_MCP_AUTO_EDIT_CALL.py"
    if not helper.is_file():
        raise RuntimeError("Auto Edit MCP helper is missing")

    request = {
        "request_id": uuid.uuid4().hex,
        "tool": tool,
        "tool_args": tool_args,
    }

    with tempfile.TemporaryDirectory(prefix="rg_auto_edit_mcp_") as tmp:
        request_path = Path(tmp) / "request.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False),
            encoding="utf-8",
        )

        copy_helper = run(
            ["docker", "cp", str(helper), "rg-nas-mcp-hub:/tmp/rg_auto_edit_call.py"],
            timeout=60,
        )
        if copy_helper["exit_code"] != 0:
            raise RuntimeError(
                "Failed to copy Auto Edit MCP helper: " + copy_helper["stderr"]
            )

        copy_request = run(
            ["docker", "cp", str(request_path), "rg-nas-mcp-hub:/tmp/rg_auto_edit_request.json"],
            timeout=60,
        )
        if copy_request["exit_code"] != 0:
            raise RuntimeError(
                "Failed to copy Auto Edit MCP request: " + copy_request["stderr"]
            )

        try:
            result = run(
                [
                    "docker", "exec", "rg-nas-mcp-hub",
                    "python", "/tmp/rg_auto_edit_call.py",
                    "/tmp/rg_auto_edit_request.json",
                ],
                timeout=180,
            )
        finally:
            run(
                [
                    "docker", "exec", "rg-nas-mcp-hub",
                    "rm", "-f",
                    "/tmp/rg_auto_edit_call.py",
                    "/tmp/rg_auto_edit_request.json",
                ],
                timeout=30,
            )

    if result["exit_code"] != 0:
        raise RuntimeError(
            "RG NAS MCP Auto Edit call failed: " + result["stderr"][-12000:]
        )

    try:
        payload = json.loads(result["stdout"])
    except Exception as exc:
        raise RuntimeError(
            "RG NAS MCP Auto Edit returned invalid JSON: "
            + result["stdout"][-12000:]
        ) from exc

    if str(payload.get("tool") or "") != tool:
        raise RuntimeError("RG NAS MCP Auto Edit response tool mismatch")

    return {
        "transport": "RG NAS MCP Auto Edit local bridge",
        **payload,
    }


def ensure_github_runner_persistence() -> dict:
    runner_dir = Path(r"C:\RG_GITHUB_RUNNER")
    run_cmd = runner_dir / "run.cmd"
    svc_cmd = runner_dir / "svc.cmd"

    if not run_cmd.is_file():
        raise RuntimeError(f"GitHub runner run.cmd not found: {run_cmd}")

    service = {
        "available": svc_cmd.is_file(),
        "installed": False,
        "install_attempted": False,
        "install_exit_code": None,
        "install_stdout": "",
        "install_stderr": "",
    }

    if svc_cmd.is_file():
        status = run(
            [r"C:\WINDOWS\System32\cmd.exe", "/d", "/c", str(svc_cmd), "status"],
            cwd=runner_dir,
            timeout=30,
        )
        status_text = (status.get("stdout") or "") + "\n" + (status.get("stderr") or "")
        service["status_before"] = status_text[-4000:]
        service["installed"] = status["exit_code"] == 0

        if not service["installed"]:
            install = run(
                [r"C:\WINDOWS\System32\cmd.exe", "/d", "/c", str(svc_cmd), "install"],
                cwd=runner_dir,
                timeout=60,
            )
            service["install_attempted"] = True
            service["install_exit_code"] = install["exit_code"]
            service["install_stdout"] = install["stdout"][-4000:]
            service["install_stderr"] = install["stderr"][-4000:]

            status = run(
                [r"C:\WINDOWS\System32\cmd.exe", "/d", "/c", str(svc_cmd), "status"],
                cwd=runner_dir,
                timeout=30,
            )
            status_text = (status.get("stdout") or "") + "\n" + (status.get("stderr") or "")
            service["status_after"] = status_text[-4000:]
            service["installed"] = status["exit_code"] == 0

    startup_file = None
    fallback_enabled = False
    watchdog = {
        "script": None,
        "task_name": "RG_GITHUB_RUNNER_WATCHDOG",
        "task_created": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
    }

    if not service["installed"]:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is unavailable; cannot install startup fallback")

        startup_dir = (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        startup_dir.mkdir(parents=True, exist_ok=True)
        startup_file = startup_dir / "RG_GITHUB_RUNNER.vbs"
        vbs = (
            'Set WshShell = CreateObject("WScript.Shell")\r\n'
            'WshShell.Run "cmd.exe /c ""cd /d C:\\RG_GITHUB_RUNNER && call run.cmd""", 0, False\r\n'
        )
        startup_file.write_text(vbs, encoding="utf-8", newline="")
        fallback_enabled = startup_file.is_file()

        watchdog_script = runner_dir / "runner_watchdog.ps1"
        watchdog_script.write_text(
            (
                "$ErrorActionPreference = 'SilentlyContinue'\n"
                "$root = 'C:\\RG_GITHUB_RUNNER'\n"
                "$listener = Get-CimInstance Win32_Process -Filter \"Name='Runner.Listener.exe'\" | "
                "Where-Object { $_.CommandLine -like '*C:\\RG_GITHUB_RUNNER*' }\n"
                "if (-not $listener) {\n"
                "  Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c','cd /d C:\\RG_GITHUB_RUNNER && call run.cmd' -WindowStyle Hidden\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        watchdog["script"] = str(watchdog_script)
        task_command = (
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
            '-File "C:\\RG_GITHUB_RUNNER\\runner_watchdog.ps1"'
        )
        task = run(
            [
                r"C:\WINDOWS\System32\schtasks.exe",
                "/Create",
                "/SC", "MINUTE",
                "/MO", "1",
                "/TN", watchdog["task_name"],
                "/TR", task_command,
                "/F",
            ],
            timeout=30,
        )
        watchdog["exit_code"] = task["exit_code"]
        watchdog["stdout"] = task["stdout"][-4000:]
        watchdog["stderr"] = task["stderr"][-4000:]
        watchdog["task_created"] = task["exit_code"] == 0

    persistent = bool(
        service["installed"]
        or fallback_enabled
        or watchdog["task_created"]
    )
    return {
        "runner_dir": str(runner_dir),
        "service": service,
        "startup_fallback": {
            "enabled": fallback_enabled,
            "path": str(startup_file) if startup_file else None,
        },
        "watchdog": watchdog,
        "persistent": persistent,
        "note": (
            "Service is installed and will start with Windows."
            if service["installed"]
            else (
                "Per-user startup fallback and one-minute watchdog are installed."
                if watchdog["task_created"]
                else "Hidden per-user startup fallback is installed and will start at next sign-in."
            )
        ),
    }


def youtube_program_local_status() -> dict:
    """Read RG YouTube Control local SQLite state without calling YouTube API."""
    import sqlite3
    from datetime import datetime, timezone

    base = Path(
        os.environ.get(
            "LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local"),
        )
    )
    data_dir = base / "RGYouTubeControl"
    db_path = data_dir / "rg_youtube_control.db"
    if not db_path.is_file():
        return {
            "database_exists": False,
            "data_dir": str(data_dir),
            "db_path": str(db_path),
            "youtube_api_calls": 0,
        }

    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row

    def scalar(sql: str, params: tuple = ()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0

    def grouped(sql: str, params: tuple = ()) -> dict:
        return {
            str(row[0] or "unknown"): int(row[1] or 0)
            for row in conn.execute(sql, params).fetchall()
        }

    settings = {
        str(row["key"]): str(row["value"])
        for row in conn.execute(
            """
            SELECT key, value
            FROM settings
            WHERE key IN (
              'current_profile',
              'archive_priority_mode',
              'safe_metadata_autopilot_main',
              'safe_metadata_autopilot_live',
              'youtube_quota_reserve_units'
            )
            ORDER BY key
            """
        ).fetchall()
    }

    try:
        from zoneinfo import ZoneInfo
        quota_day = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        quota_day = datetime.now(timezone.utc).date().isoformat()

    quota_prefix = f"youtube_quota_%_{quota_day}"
    quota = {
        str(row["key"]): str(row["value"])
        for row in conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key",
            (quota_prefix,),
        ).fetchall()
    }

    audit_issues: dict[str, int] = {}
    for row in conn.execute("SELECT audit_json FROM videos").fetchall():
        try:
            payload = json.loads(str(row["audit_json"] or "{}"))
        except Exception:
            payload = {}
        for issue in payload.get("issues") or []:
            key = str(issue)
            audit_issues[key] = audit_issues.get(key, 0) + 1

    recent_actions = []
    for row in conn.execute(
        """
        SELECT profile, category, action, details, created_at
        FROM action_log
        ORDER BY log_id DESC
        LIMIT 12
        """
    ).fetchall():
        recent_actions.append({
            "profile": row["profile"],
            "category": row["category"],
            "action": row["action"],
            "details": str(row["details"] or "")[-1000:],
            "created_at": row["created_at"],
        })

    scheduled_details = []
    for row in conn.execute(
        """
        SELECT
          v.video_id, v.profile, v.title, v.views,
          v.scheduled_publish_at, v.privacy_status, v.audit_json,
          d.status AS draft_status, d.new_title AS draft_title,
          d.description AS draft_description, d.chapters AS draft_chapters,
          d.tags_json AS draft_tags
        FROM videos v
        LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
        WHERE COALESCE(v.scheduled_publish_at,'') <> ''
        ORDER BY v.scheduled_publish_at
        """
    ).fetchall():
        try:
            audit_payload = json.loads(str(row["audit_json"] or "{}"))
        except Exception:
            audit_payload = {}
        try:
            draft_tags = json.loads(str(row["draft_tags"] or "[]"))
        except Exception:
            draft_tags = []
        scheduled_details.append({
            "video_id": row["video_id"],
            "profile": row["profile"],
            "title": row["title"],
            "views": int(row["views"] or 0),
            "scheduled_publish_at": row["scheduled_publish_at"],
            "privacy_status": row["privacy_status"],
            "audit_issues": audit_payload.get("issues") or [],
            "draft_status": row["draft_status"],
            "draft_title": row["draft_title"],
            "draft_description_chars": len(str(row["draft_description"] or "")),
            "draft_chapters_lines": len([
                line for line in str(row["draft_chapters"] or "").splitlines()
                if line.strip()
            ]),
            "draft_tags_count": len(draft_tags) if isinstance(draft_tags, list) else 0,
        })

    blocked_details = []
    for row in conn.execute(
        """
        SELECT
          d.video_id, d.new_title, d.description, d.chapters,
          d.tags_json, d.title_variants_json, d.updated_at,
          v.profile, v.title, v.views, v.audit_json
        FROM optimization_drafts d
        LEFT JOIN videos v ON v.video_id=d.video_id
        WHERE d.status='blocked'
        ORDER BY d.updated_at DESC
        """
    ).fetchall():
        try:
            tags = json.loads(str(row["tags_json"] or "[]"))
        except Exception:
            tags = []
        try:
            variants = json.loads(str(row["title_variants_json"] or "[]"))
        except Exception:
            variants = []
        try:
            audit_payload = json.loads(str(row["audit_json"] or "{}"))
        except Exception:
            audit_payload = {}
        reasons = []
        title_value = str(row["new_title"] or "").strip()
        description_value = str(row["description"] or "").strip()
        chapters_value = str(row["chapters"] or "").strip()
        if not title_value:
            reasons.append("empty_title")
        if len(title_value) > 100:
            reasons.append("title_over_100")
        if not description_value:
            reasons.append("empty_description")
        if len(description_value) > 5000:
            reasons.append("description_over_5000")
        chapter_lines = [line for line in chapters_value.splitlines() if line.strip()]
        if chapters_value and len(chapter_lines) < 3:
            reasons.append("chapters_under_3")
        if not isinstance(tags, list) or not tags:
            reasons.append("no_tags")
        if isinstance(tags, list) and len(", ".join(str(x) for x in tags)) > 500:
            reasons.append("tags_over_500")
        blocked_details.append({
            "video_id": row["video_id"],
            "profile": row["profile"],
            "current_title": row["title"],
            "new_title": row["new_title"],
            "views": int(row["views"] or 0),
            "audit_issues": audit_payload.get("issues") or [],
            "description_chars": len(description_value),
            "description_lines": len(description_value.splitlines()),
            "description_hashtags": len(__import__("re").findall(r"(?<!\\w)#[\\wА-Яа-яІіЇїЄєҐґ]+", description_value)),
            "description_head": description_value[:900],
            "description_tail": description_value[-1400:],
            "chapters_lines": len(chapter_lines),
            "tags_count": len(tags) if isinstance(tags, list) else 0,
            "title_variants_count": len(variants) if isinstance(variants, list) else 0,
            "likely_block_reasons": reasons,
            "updated_at": row["updated_at"],
        })

    top_ready = []
    for row in conn.execute(
        """
        SELECT
          d.video_id, d.new_title, d.updated_at,
          v.profile, v.title, v.views, v.scheduled_publish_at, v.audit_json
        FROM optimization_drafts d
        LEFT JOIN videos v ON v.video_id=d.video_id
        WHERE d.status='ready'
        ORDER BY
          CASE WHEN COALESCE(v.scheduled_publish_at,'') <> '' THEN 0 ELSE 1 END,
          COALESCE(v.views,0) DESC,
          d.updated_at ASC
        LIMIT 30
        """
    ).fetchall():
        try:
            audit_payload = json.loads(str(row["audit_json"] or "{}"))
        except Exception:
            audit_payload = {}
        top_ready.append({
            "video_id": row["video_id"],
            "profile": row["profile"],
            "current_title": row["title"],
            "new_title": row["new_title"],
            "views": int(row["views"] or 0),
            "scheduled_publish_at": row["scheduled_publish_at"],
            "audit_issues": audit_payload.get("issues") or [],
            "updated_at": row["updated_at"],
        })

    result = {
        "database_exists": True,
        "data_dir": str(data_dir),
        "db_path": str(db_path),
        "db_size_bytes": db_path.stat().st_size,
        "current_profile": settings.get("current_profile", "main"),
        "settings": settings,
        "quota_day_pt": quota_day,
        "quota": quota,
        "videos_total": scalar("SELECT COUNT(*) FROM videos"),
        "videos_by_profile": grouped(
            "SELECT COALESCE(profile,'unknown'), COUNT(*) FROM videos GROUP BY COALESCE(profile,'unknown')"
        ),
        "scheduled_by_profile": grouped(
            """
            SELECT COALESCE(profile,'unknown'), COUNT(*)
            FROM videos
            WHERE COALESCE(scheduled_publish_at,'') <> ''
            GROUP BY COALESCE(profile,'unknown')
            """
        ),
        "drafts_by_status": grouped(
            "SELECT COALESCE(status,'unknown'), COUNT(*) FROM optimization_drafts GROUP BY COALESCE(status,'unknown')"
        ),
        "drafts_by_profile": grouped(
            """
            SELECT COALESCE(v.profile,'unknown'), COUNT(*)
            FROM optimization_drafts d
            LEFT JOIN videos v ON v.video_id=d.video_id
            GROUP BY COALESCE(v.profile,'unknown')
            """
        ),
        "deep_review_by_status": grouped(
            "SELECT COALESCE(status,'unknown'), COUNT(*) FROM deep_review_state GROUP BY COALESCE(status,'unknown')"
        ),
        "comments_by_status": grouped(
            "SELECT COALESCE(status,'unknown'), COUNT(*) FROM comments GROUP BY COALESCE(status,'unknown')"
        ),
        "new_comments_by_category": grouped(
            """
            SELECT COALESCE(category,'unknown'), COUNT(*)
            FROM comments
            WHERE status='new'
            GROUP BY COALESCE(category,'unknown')
            """
        ),
        "moderation_locked_comments": scalar(
            "SELECT COUNT(*) FROM comments WHERE status='moderation_locked'"
        ),
        "audit_issues": dict(sorted(audit_issues.items(), key=lambda item: (-item[1], item[0]))),
        "scheduled_details": scheduled_details,
        "blocked_details": blocked_details,
        "top_ready": top_ready,
        "recent_actions": recent_actions,
        "youtube_api_calls": 0,
    }
    conn.close()
    return result


def launch_auto_edit_studio() -> dict:
    if os.name != "nt":
        raise RuntimeError("launch_auto_edit_studio must run on AlexPC/Windows")

    import subprocess
    import time

    launcher = Path(
        r"C:\Users\fauto\AppData\Local\Programs\RG Auto Edit\rg_studio_main.py"
    )
    if not launcher.is_file():
        raise RuntimeError(f"RG Auto Edit launcher not found: {launcher}")

    ps_query = (
        "$p=Get-CimInstance Win32_Process | "
        "Where-Object { "
        "(($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and "
        "(($_.CommandLine -like '*rg_studio_main.py*') -or "
        "($_.CommandLine -like '*rg_studio_ui.py*')) "
        "}; "
        "$p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )

    probe = run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_query],
        timeout=30,
    )
    existing_text = (probe.get("stdout") or "").strip()
    if existing_text and existing_text not in {"null", "[]"}:
        return {
            "launched": False,
            "already_running": True,
            "processes": existing_text,
            "launcher": str(launcher),
        }

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.is_file() else Path(sys.executable)

    env = os.environ.copy()
    env.pop("RUNNER_TRACKING_ID", None)

    creationflags = 0
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)

    proc = subprocess.Popen(
        [str(exe), str(launcher)],
        cwd=str(launcher.parent),
        env=env,
        creationflags=creationflags,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    time.sleep(5)

    verify = run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_query],
        timeout=30,
    )
    running_text = (verify.get("stdout") or "").strip()
    if not running_text or running_text in {"null", "[]"}:
        raise RuntimeError("RG Auto Edit Studio process was not detected after launch")

    return {
        "launched": True,
        "already_running": False,
        "pid": proc.pid,
        "python": str(exe),
        "launcher": str(launcher),
        "processes": running_text,
    }


def inspect_auto_edit_live_code() -> dict:
    if os.name != "nt":
        raise RuntimeError("inspect_auto_edit_live_code must run on AlexPC/Windows")

    roots = [
        Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App"),
        Path(r"C:\Users\fauto\AppData\Local\Programs\RG Auto Edit"),
    ]
    targets = [
        "rg_studio_ui.py",
        "rg_studio_postrun.py",
        "rg_multi_dialogue.py",
        "rg_production_wrapper.py",
        "rg_auto_edit_config.json",
    ]
    patterns = [
        "POSTRUN", "dialogue", "expected", "xml_count", "batch",
        "_batch_next", "queue", "RUN_STATE", "screenshot", "RG_BATCH_STATE",
    ]
    out = {}
    for root in roots:
        if not root.exists():
            continue
        for name in targets:
            path = root / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rows = text.splitlines()
            hits = []
            for idx, row in enumerate(rows):
                low = row.lower()
                if any(p.lower() in low for p in patterns):
                    a = max(0, idx - 8)
                    b = min(len(rows), idx + 18)
                    hits.append({
                        "line": idx + 1,
                        "snippet": "\n".join(f"{i+1}: {rows[i]}" for i in range(a, b)),
                    })
                    if len(hits) >= 40:
                        break
            out[str(path)] = {
                "size": path.stat().st_size,
                "mtime": path.stat().st_mtime,
                "hits": hits,
            }
    return out


def inspect_auto_edit_runtime_state() -> dict:
    if os.name != "nt":
        raise RuntimeError("inspect_auto_edit_runtime_state must run on AlexPC/Windows")

    import ast

    backend = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
    local = Path(os.getenv("LOCALAPPDATA") or str(Path.home()))
    queue_file = local / "RG_Auto_Edit" / "studio_batch_queue.json"
    screens = Path(r"\\Desktop-v7gg0en\record\Screens")
    video_root = Path(r"\\Desktop-v7gg0en\record")
    audio_root = video_root / "sound"

    out = {"inputs": {}, "queue_state": None, "functions": {}}

    for stream in ("889","890","891","892"):
        shot_names = []
        try:
            shot_names = sorted(
                p.name for p in screens.glob(f"{stream}-*.jpg")
                if p.is_file()
            )
        except Exception as exc:
            shot_names = [f"ERROR:{exc}"]
        out["inputs"][stream] = {
            "video": (video_root / f"{stream}.mp4").is_file(),
            "audio": (audio_root / f"{stream}.mp3").is_file(),
            "screenshots": shot_names,
        }

    if queue_file.is_file():
        try:
            out["queue_state"] = json.loads(
                queue_file.read_text(encoding="utf-8-sig", errors="replace")
            )
        except Exception as exc:
            out["queue_state"] = {"error": repr(exc), "path": str(queue_file)}
    else:
        out["queue_state"] = {"missing": True, "path": str(queue_file)}

    for filename in ("rg_studio_ui.py", "rg_studio_postrun.py"):
        path = backend / filename
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        rows = source.splitlines()
        try:
            tree = ast.parse(source)
        except Exception as exc:
            out["functions"][filename] = {"parse_error": repr(exc)}
            continue
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                want = (
                    filename == "rg_studio_ui.py"
                    and (name.startswith("batch_") or name.startswith("_batch") or name in {"on_finished"})
                ) or (
                    filename == "rg_studio_postrun.py"
                    and name in {"main","run","postrun","build_postrun_qa","verify_outputs"}
                )
                if want:
                    a = max(0, int(node.lineno)-1)
                    b = min(len(rows), int(getattr(node,"end_lineno",node.lineno)))
                    found[name] = "\n".join(
                        f"{i+1}: {rows[i]}" for i in range(a,b)
                    )
        out["functions"][filename] = found
    return out


def locate_auto_edit_missing_screens() -> dict:
    if os.name != "nt":
        raise RuntimeError("locate_auto_edit_missing_screens must run on AlexPC/Windows")
    import fnmatch

    patterns = ("889-*.jpg","890-*.jpg","892-4.jpg")
    roots = [
        Path(r"\\Desktop-v7gg0en\record"),
        Path(r"F:\RG_AUTO_EDIT"),
        Path(r"C:\Users\fauto\AppData\Local\RG_Auto_Edit"),
    ]
    found = {p: [] for p in patterns}
    scanned = []
    for root in roots:
        if not root.exists():
            scanned.append({"root":str(root),"exists":False})
            continue
        scanned.append({"root":str(root),"exists":True})
        try:
            for dp, ds, fs in os.walk(root):
                low = str(dp).lower()
                if any(x in low for x in ("\\venv","\\__pycache__","\\site-packages")):
                    ds[:] = []
                    continue
                for name in fs:
                    for pat in patterns:
                        if fnmatch.fnmatch(name, pat):
                            path = Path(dp) / name
                            try:
                                found[pat].append({
                                    "path": str(path),
                                    "size": path.stat().st_size,
                                    "mtime": path.stat().st_mtime,
                                })
                            except Exception:
                                found[pat].append({"path": str(path)})
                if sum(len(v) for v in found.values()) >= 100:
                    break
        except Exception as exc:
            scanned[-1]["error"] = repr(exc)
    return {"patterns": found, "scanned": scanned}


def apply_auto_edit_completeness_hotfix() -> dict:
    if os.name != "nt":
        raise RuntimeError("apply_auto_edit_completeness_hotfix must run on AlexPC/Windows")

    import datetime
    import py_compile

    path = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\rg_studio_postrun.py")
    if not path.is_file():
        raise RuntimeError(f"Postrun file missing: {path}")

    source = path.read_text(encoding="utf-8")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\release_backups") / f"PRE_COMPLETENESS_HOTFIX_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / path.name)

    marker = '    def add(n,ok,d="",critical=True):checks.append({"name":n,"ok":bool(ok),"detail":str(d),"critical":critical})\n'
    if marker not in source:
        raise RuntimeError("Postrun insertion marker not found")

    if "RG_EXPECTED_DIALOGUE_COMPLETENESS_V1" not in source:
        patch = marker + '''    # RG_EXPECTED_DIALOGUE_COMPLETENESS_V1
    def _dialogue_key(p):
        import re
        n=Path(p).name
        m=re.match(r"^RG_EDITED_"+re.escape(str(a.stream))+r"(?:_(\\\\d+))?(?:_SHORTS|_UNCENSORED)?\\\\.xml$",n,re.I)
        if not m:return None
        return m.group(1) or "MAIN"
    primary_ids={x for x in (_dialogue_key(p) for p in outs) if x}
    uncensored_ids=set()
    for p in root.glob(f"RG_EDITED_{a.stream}*_UNCENSORED.xml"):
        k=_dialogue_key(p)
        if k:uncensored_ids.add(k)
    missing_expected=sorted(uncensored_ids-primary_ids,key=lambda x:(x!="MAIN",int(x) if x.isdigit() else -1))
    expected_ids=sorted(primary_ids|uncensored_ids,key=lambda x:(x!="MAIN",int(x) if x.isdigit() else -1))
    add("Повнота діалогів",not missing_expected,
        ("PASS • expected="+",".join(expected_ids)) if not missing_expected
        else ("MISSING PRIMARY XML: "+",".join(missing_expected)+" • expected="+",".join(expected_ids)),
        True)
'''
        source = source.replace(marker, patch, 1)

    temp = path.with_suffix(".py.hotfix.tmp")
    temp.write_text(source,encoding="utf-8")
    py_compile.compile(str(temp), doraise=True)
    os.replace(temp,path)
    py_compile.compile(str(path), doraise=True)

    return {
        "patched": True,
        "path": str(path),
        "backup": str(backup_dir),
        "guard": "RG_EXPECTED_DIALOGUE_COMPLETENESS_V1",
    }


def inspect_auto_edit_execution_functions() -> dict:
    if os.name != "nt":
        raise RuntimeError("inspect_auto_edit_execution_functions must run on AlexPC/Windows")
    import ast
    path = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App\rg_studio_ui.py")
    source = path.read_text(encoding="utf-8", errors="replace")
    rows = source.splitlines()
    tree = ast.parse(source)
    wanted = {
        "_start_stream","_command","_finished","start","start_process","on_finished",
        "_save_batch_ui_state","_load_batch_ui_state","_batch_next",
        "_run_postrun","_archive_run","_finish_run","_start_process","_collect_outputs","_start_postrun_qa","_postrun_finished","_finalize_run",
    }
    out={}
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in wanted:
            a=max(0,int(node.lineno)-1)
            b=min(len(rows),int(getattr(node,"end_lineno",node.lineno)))
            out[node.name]="\n".join(f"{i+1}: {rows[i]}" for i in range(a,b))
    return out


def start_auto_edit_recovery_queue() -> dict:
    if os.name != "nt":
        raise RuntimeError("start_auto_edit_recovery_queue must run on AlexPC/Windows")

    import datetime
    import subprocess
    import textwrap
    import uuid

    task_path = Path(sys.argv[1] if len(sys.argv) > 1 else "rg_remote_control/auto_edit_task.json")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    requested = [str(x).strip() for x in ((task.get("args") or {}).get("streams") or [])]
    streams = list(dict.fromkeys(x for x in requested if x.isdigit()))
    if not streams or len(streams) > 12:
        raise RuntimeError("Recovery queue requires 1..12 numeric stream ids")

    app = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit App")
    data = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data")
    local = Path(os.getenv("LOCALAPPDATA") or str(Path.home()))
    runtime_candidates = [
        local / "Programs" / "RG Auto Edit Runtime" / "venv" / "Scripts" / "python.exe",
        Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"),
    ]
    runtime = next((p for p in runtime_candidates if p.is_file()), None)
    if runtime is None:
        raise RuntimeError("RG Auto Edit runtime python not found")

    # Do not launch a second production backend.
    probe = run(
        [
            "powershell.exe","-NoProfile","-NonInteractive","-Command",
            "$p=Get-CimInstance Win32_Process | Where-Object { "
            "(($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and "
            "(($_.CommandLine -like '*rg_production_wrapper.py*') -or ($_.CommandLine -like '*rg_multi_dialogue.py*')) "
            "}; $p | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        ],
        timeout=30,
    )
    active = (probe.get("stdout") or "").strip()
    if active and active not in {"null","[]"}:
        raise RuntimeError("Production backend is already running: " + active[:2000])

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"RECOVERY_{stamp}_{uuid.uuid4().hex[:8]}"
    run_dir = data / "control_runs" / session_id
    run_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "session_id": session_id,
        "streams": streams,
        "app": str(app),
        "data": str(data),
        "runtime": str(runtime),
        "video_root": r"\\Desktop-v7gg0en\record",
        "audio_root": r"\\Desktop-v7gg0en\record\sound",
        "screen_root": r"\\Desktop-v7gg0en\record\Screens",
        "queue_state": str(local / "RG_Auto_Edit" / "studio_batch_queue.json"),
        "status_file": str(run_dir / "RECOVERY_QUEUE_STATUS.json"),
        "run_dir": str(run_dir),
    }
    plan_path = run_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    helper = r'''from __future__ import annotations
import json, os, re, subprocess, sys, time, traceback
from pathlib import Path

plan=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
streams=[str(x) for x in plan["streams"]]
app=Path(plan["app"]); data=Path(plan["data"]); runtime=Path(plan["runtime"])
video_root=plan["video_root"]; audio_root=plan["audio_root"]; screen_root=plan["screen_root"]
queue_state=Path(plan["queue_state"]); status_file=Path(plan["status_file"]); run_dir=Path(plan["run_dir"])
sys.path.insert(0,str(app))

from rg_server_resolver import resolve_video, resolve_audio, resolve_screenshots
from rg_production_stability import acquire_stream_lock, release_stream_lock
from rg_studio_resilience import build_run_package, update_state, new_run_session

rows=[{"stream":s,"status":"ОЧІКУЄ","progress":"0%","stage":"—","elapsed":"—","eta":"—","detail":"Recovery queue"} for s in streams]
state={"schema":"RG_STUDIO_BATCH_UI_V2","updated_at":time.time(),"running":True,"paused":False,
       "session_id":plan["session_id"],"queue":streams,"rows":rows}

def atomic_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,path)

def publish():
    state["updated_at"]=time.time()
    atomic_json(queue_state,state)
    atomic_json(status_file,state)

def row(stream):
    return next(x for x in rows if x["stream"]==stream)

def setrow(stream,**kw):
    row(stream).update({k:str(v) for k,v in kw.items()})
    publish()

def primary_from_log(lines,stream):
    out=[]
    seen=set()
    target=(app/stream).resolve()
    for line in lines:
        if "ГОТОВО:" not in line:
            continue
        raw=line.split("ГОТОВО:",1)[1].strip()
        try:p=Path(raw)
        except Exception:continue
        n=p.name.upper()
        if p.suffix.lower()!=".xml" or "_SHORTS" in n or "_UNCENSORED" in n:
            continue
        try:
            if p.resolve().parent != target:
                continue
        except Exception:
            continue
        sp=str(p)
        if sp not in seen:
            seen.add(sp);out.append(sp)
    return out

publish()
overall_ok=True
for stream in streams:
    started=time.time()
    lock=None
    log_path=run_dir/f"{stream}_STUDIO_RUN.log"
    lines=[]
    try:
        setrow(stream,status="ПЕРЕВІРКА",stage="INPUT_CHECK",progress="0%",elapsed="00:00:00",detail="Перевірка input")
        try:
            resolve_video(video_root,stream)
            resolve_audio(audio_root,stream)
            shots=resolve_screenshots(screen_root,stream)
        except Exception as exc:
            overall_ok=False
            setrow(stream,status="ПОМИЛКА",stage="INPUT_CHECK",progress="0%",elapsed="00:00:00",
                   detail=f"{type(exc).__name__}: {str(exc)[:180]}")
            continue

        lock=acquire_stream_lock(stream,owner_pid=os.getpid(),owner="RG Auto Edit Recovery Queue")
        run_id=str((lock or {}).get("run_id") or "")
        try:
            new_run_session(stream,run_id=run_id,status="RUNNING",started_at=started,outputs=[],last_stage="START",error_code=None,error_tail=[])
        except Exception:
            pass

        setrow(stream,status="ПРАЦЮЄ",stage="START",progress="1%",elapsed="00:00:00",detail=f"Запущено • screenshots={len(shots or [])}")
        cmd=[str(runtime),"-u","-X","utf8",str(app/"rg_production_wrapper.py"),
             "--backend",str(app/"rg_multi_dialogue.py"),
             "--video-root",video_root,"--audio-root",audio_root,"--screen-root",screen_root,
             "--video-stream",stream,"--audio-stream",stream,
             "--output",str(app/f"RG_EDITED_{stream}.xml"),
             "--config",str(app/"rg_auto_edit_config.json"),
             "--model","large-v3","--device","auto","--stream-start","auto"]
        env=os.environ.copy();env["PYTHONUTF8"]="1";env["PYTHONIOENCODING"]="utf-8"
        env["RG_BATCH_MODE"]="1";env["RG_BATCH_SESSION_ID"]=plan["session_id"]
        with log_path.open("w",encoding="utf-8") as lf:
            p=subprocess.Popen(cmd,cwd=str(app),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                               text=True,encoding="utf-8",errors="replace",bufsize=1)
            for raw in p.stdout:
                line=raw.rstrip("\r\n");lines.append(line);lf.write(line+"\n");lf.flush()
                m=re.search(r"RGPROGRESS\|([0-9.]+)\|([^|]+)\|(.*)",line)
                if m:
                    setrow(stream,status="ПРАЦЮЄ",progress=f"{float(m.group(1)):.0f}%",stage=m.group(2),
                           elapsed=time.strftime("%H:%M:%S",time.gmtime(max(0,time.time()-started))),detail=m.group(3)[:160])
            rc=p.wait()
        if rc!=0:
            overall_ok=False
            try:update_state(stream,status="BACKEND_ERROR",outputs=[],error_code=rc,error_tail=lines[-40:])
            except Exception:pass
            setrow(stream,status="ПОМИЛКА",stage="BACKEND_ERROR",progress=row(stream).get("progress","0%"),
                   elapsed=time.strftime("%H:%M:%S",time.gmtime(max(0,time.time()-started))),
                   detail=f"Backend code {rc}")
            continue

        outputs=primary_from_log(lines,stream)
        if not outputs:
            folder=app/stream
            outputs=[str(p) for p in sorted(folder.glob(f"RG_EDITED_{stream}*.xml"))
                     if "_SHORTS" not in p.name.upper() and "_UNCENSORED" not in p.name.upper()]

        setrow(stream,status="ПРАЦЮЄ",stage="POSTRUN_QA",progress="99%",
               elapsed=time.strftime("%H:%M:%S",time.gmtime(max(0,time.time()-started))),detail=f"QA • {len(outputs)} primary XML")
        qcmd=[str(runtime),"-u","-X","utf8",str(app/"rg_studio_postrun.py"),
              "--stream",stream,"--folder",str(app/stream),"--outputs-json",json.dumps(outputs,ensure_ascii=False),
              "--started-at",str(started)]
        q=subprocess.run(qcmd,cwd=str(app),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace")
        qa_text=(q.stdout or "")+"\n"+(q.stderr or "")
        with log_path.open("a",encoding="utf-8") as lf:lf.write(qa_text)
        result=None
        for line in (q.stdout or "").splitlines():
            if line.startswith("RGPOSTRUN|"):
                try:result=json.loads(line.split("|",1)[1])
                except Exception:pass
        passed=bool(result and result.get("passed") and q.returncode==0)
        package=None
        if result:
            try:
                package,_table=build_run_package(stream,outputs,result,log_path,None)
            except Exception as exc:
                with log_path.open("a",encoding="utf-8") as lf:lf.write("\nRUN PACKAGE ERROR: "+repr(exc)+"\n")
        try:update_state(stream,status="COMPLETE" if passed else "NEEDS_CHECK",outputs=outputs,run_package=str(package) if package else None)
        except Exception:pass

        if passed:
            setrow(stream,status="ГОТОВО",stage="DONE",progress="100%",
                   elapsed=time.strftime("%H:%M:%S",time.gmtime(max(0,time.time()-started))),
                   detail=f"QA PASS • {len(outputs)} XML")
        else:
            overall_ok=False
            bad=[str(x.get("name")) for x in ((result or {}).get("checks") or []) if not x.get("ok")]
            setrow(stream,status="ПОМИЛКА",stage="POSTRUN_QA",progress="100%",
                   elapsed=time.strftime("%H:%M:%S",time.gmtime(max(0,time.time()-started))),
                   detail=("QA FAIL • "+", ".join(bad[:5])) if bad else f"QA process code {q.returncode}")
    except Exception as exc:
        overall_ok=False
        with log_path.open("a",encoding="utf-8") as lf:
            lf.write("\nRECOVERY RUNNER EXCEPTION:\n"+traceback.format_exc()+"\n")
        setrow(stream,status="ПОМИЛКА",stage="RECOVERY_ERROR",progress=row(stream).get("progress","0%"),
               elapsed=time.strftime("%H:%M:%S",time.gmtime(max(0,time.time()-started))),detail=f"{type(exc).__name__}: {str(exc)[:180]}")
    finally:
        if lock is not None:
            try:release_stream_lock(stream,str((lock or {}).get("run_id") or ""))
            except Exception:pass

state["running"]=False
state["finished_at"]=time.time()
state["overall_ok"]=overall_ok
publish()
'''
    helper_path = run_dir / "recovery_queue_runner.py"
    helper_path.write_text(textwrap.dedent(helper), encoding="utf-8")

    env = os.environ.copy()
    env.pop("RUNNER_TRACKING_ID", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    flags = getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0) | getattr(subprocess,"DETACHED_PROCESS",0)
    proc = subprocess.Popen(
        [str(runtime),"-u",str(helper_path),str(plan_path)],
        cwd=str(run_dir),env=env,creationflags=flags,close_fds=True,
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    if proc.poll() is not None:
        raise RuntimeError(f"Recovery queue exited immediately with code {proc.returncode}")

    return {
        "started": True,
        "pid": proc.pid,
        "session_id": session_id,
        "streams": streams,
        "status_file": str(run_dir / "RECOVERY_QUEUE_STATUS.json"),
        "queue_state": str(local / "RG_Auto_Edit" / "studio_batch_queue.json"),
        "runner": str(helper_path),
    }


def inspect_auto_edit_recovery_queue() -> dict:
    if os.name != "nt":
        raise RuntimeError("inspect_auto_edit_recovery_queue must run on AlexPC/Windows")
    data = Path(r"F:\RG_AUTO_EDIT\RG Auto Edit Data\control_runs")
    candidates = sorted(data.glob("RECOVERY_*"), key=lambda p:p.stat().st_mtime, reverse=True)
    if not candidates:
        return {"found": False}
    root = candidates[0]
    status = root / "RECOVERY_QUEUE_STATUS.json"
    out = {"found": True, "session": root.name, "status_file": str(status)}
    if status.is_file():
        try:out["status"]=json.loads(status.read_text(encoding="utf-8-sig"))
        except Exception as exc:out["status_error"]=repr(exc)
    logs={}
    for p in sorted(root.glob("*_STUDIO_RUN.log")):
        try:logs[p.name]=p.read_text(encoding="utf-8",errors="replace").splitlines()[-40:]
        except Exception as exc:logs[p.name]=[repr(exc)]
    out["log_tails"]=logs
    return out


def health() -> dict:
    usage = shutil.disk_usage(Path.home())
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cwd": str(Path.cwd()),
        "disk_free_gb": round(usage.free / (1024 ** 3), 1),
    }


def deploy_remote_mcp() -> dict:
    if os.name == "nt":
        raise RuntimeError("deploy_remote_mcp is a NAS/Linux task")
    return run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=ROOT / "rg_remote_mcp",
        timeout=1200,
    )


def remote_mcp_status() -> dict:
    if os.name == "nt":
        raise RuntimeError("remote_mcp_status is a NAS/Linux task")
    return run(
        ["docker", "compose", "ps"],
        cwd=ROOT / "rg_remote_mcp",
        timeout=120,
    )


ACTIONS = {
    "health": health,
    "ensure_github_runner_persistence": ensure_github_runner_persistence,
    "probe_environment": probe_environment,
    "stage_remote_mcp_to_nas": stage_remote_mcp_to_nas,
    "probe_ssh_config": probe_ssh_config,
    "probe_nas_ssh_auth": probe_nas_ssh_auth,
    "probe_nas_mcp_inventory": probe_nas_mcp_inventory,
    "probe_nas_telegram_mcp_fast": probe_nas_telegram_mcp_fast,
    "probe_contour_mounts": probe_contour_mounts,
    "probe_nas_cached_identity": probe_nas_cached_identity,
    "request_local_mcp_deploy": request_local_mcp_deploy,
    "probe_local_mcp_deploy": probe_local_mcp_deploy,
    "probe_remote_commander_runtime": probe_remote_commander_runtime,
    "install_live_mcp_autodeploy_hook": install_live_mcp_autodeploy_hook,
    "probe_live_mcp_hook": probe_live_mcp_hook,
    "probe_nas_autodeploy_runtime": probe_nas_autodeploy_runtime,
    "stage_mcp_to_docker_root": stage_mcp_to_docker_root,
    "migrate_live_mcp_hook_to_docker_root": migrate_live_mcp_hook_to_docker_root,
    "probe_docker_root_mcp_deploy": probe_docker_root_mcp_deploy,
    "wait_docker_root_mcp_deploy": wait_docker_root_mcp_deploy,
    "upgrade_live_mcp_hook_autodetect_volume": upgrade_live_mcp_hook_autodetect_volume,
    "install_mcp_protocol_smoke_hook": install_mcp_protocol_smoke_hook,
    "request_mcp_protocol_smoke": request_mcp_protocol_smoke,
    "enable_one_minute_mcp_tick": enable_one_minute_mcp_tick,
    "probe_cloudflare_mcp_gateway_options": probe_cloudflare_mcp_gateway_options,
    "run_telegram_mcp_smoke": run_telegram_mcp_smoke,
    "telegram_mcp_call": telegram_mcp_call,
    "youtube_mcp_call": youtube_mcp_call,
    "youtube_mcp_batch": youtube_mcp_batch,
    "youtube_program_local_status": youtube_program_local_status,
    "auto_edit_mcp_call": auto_edit_mcp_call,
    "launch_auto_edit_studio": launch_auto_edit_studio,
    "inspect_auto_edit_live_code": inspect_auto_edit_live_code,
    "inspect_auto_edit_runtime_state": inspect_auto_edit_runtime_state,
    "locate_auto_edit_missing_screens": locate_auto_edit_missing_screens,
    "apply_auto_edit_completeness_hotfix": apply_auto_edit_completeness_hotfix,
    "inspect_auto_edit_execution_functions": inspect_auto_edit_execution_functions,
    "start_auto_edit_recovery_queue": start_auto_edit_recovery_queue,
    "inspect_auto_edit_recovery_queue": inspect_auto_edit_recovery_queue,
    "enable_auto_edit_mcp_bridge": enable_auto_edit_mcp_bridge,
    "probe_auto_edit_mcp_bridge": probe_auto_edit_mcp_bridge,
    "enable_youtube_mcp_bridge": enable_youtube_mcp_bridge,
    "probe_youtube_mcp_bridge": probe_youtube_mcp_bridge,
    "probe_youtube_tick_runtime": probe_youtube_tick_runtime,
    "probe_autodeploy_container_layout": probe_autodeploy_container_layout,
    "list_nas_project_roots": list_nas_project_roots,
    "probe_nas_shares": probe_nas_shares,
    "probe_nas_telegram_locations": probe_nas_telegram_locations,
    "probe_telegram_production_layout": probe_telegram_production_layout,
    "probe_nas_identity": probe_nas_identity,
    "probe_nas_home_connection": probe_nas_home_connection,
    "install_and_probe_nas_ssh_key": install_and_probe_nas_ssh_key,
    "probe_nas_command_bus": probe_nas_command_bus,
    "sync_nas_command_bus_mcp": sync_nas_command_bus_mcp,
    "probe_command_bus_state": probe_command_bus_state,
    "sync_nas_scheduler_tick": sync_nas_scheduler_tick,
    "wait_for_mcp_command_bus": wait_for_mcp_command_bus,
    "probe_scheduler_history": probe_scheduler_history,
    "deploy_remote_mcp": deploy_remote_mcp,
    "remote_mcp_status": remote_mcp_status,
}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    task_path = Path(sys.argv[1] if len(sys.argv) > 1 else "rg_remote_control/task.json")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    action = str(task.get("action") or "")
    fn = ACTIONS.get(action)
    if fn is None:
        raise SystemExit(f"Unsupported action: {action}")
    result = fn()
    print(json.dumps({"action": action, "result": result}, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and int(result.get("exit_code", 0)) != 0:
        return int(result["exit_code"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
