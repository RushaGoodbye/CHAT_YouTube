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
