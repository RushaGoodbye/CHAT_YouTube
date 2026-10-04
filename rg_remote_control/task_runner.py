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
    ]
    out = {}
    for name in names:
        path = state / name
        if path.is_file():
            out[name] = path.read_text(encoding="utf-8", errors="replace").strip()[-2000:]
        else:
            out[name] = None
    audit = state / "nas-command-bus.log"
    if audit.is_file():
        lines = audit.read_text(encoding="utf-8", errors="replace").splitlines()
        out["audit_tail"] = lines[-30:]
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
    "probe_environment": probe_environment,
    "stage_remote_mcp_to_nas": stage_remote_mcp_to_nas,
    "probe_ssh_config": probe_ssh_config,
    "probe_nas_ssh_auth": probe_nas_ssh_auth,
    "probe_nas_mcp_inventory": probe_nas_mcp_inventory,
    "probe_nas_telegram_mcp_fast": probe_nas_telegram_mcp_fast,
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
