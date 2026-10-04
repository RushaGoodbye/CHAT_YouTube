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
