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
