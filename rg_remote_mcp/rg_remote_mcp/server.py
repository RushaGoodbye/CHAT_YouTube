from __future__ import annotations

from mcp.server import MCPServer

from .config import settings
from .execops import run_local
from .fsops import copy_path, list_dir, make_dir, read_text, write_text
from .sshops import run_ssh

mcp = MCPServer("RG Remote MCP")


@mcp.tool()
def health() -> dict:
    """Return bridge status without touching managed files or SSH hosts."""
    return {
        "status": "ok",
        "roots": sorted(settings.roots),
        "ssh_aliases": sorted(settings.ssh_aliases),
        "allowed_commands": sorted(settings.allowed_commands),
        "max_read_bytes": settings.max_read_bytes,
        "max_write_bytes": settings.max_write_bytes,
    }


@mcp.tool()
def fs_list(root: str, relative: str = "") -> list[dict]:
    """List one directory inside a configured root alias."""
    return list_dir(settings, root, relative)


@mcp.tool()
def fs_read_text(root: str, relative: str) -> str:
    """Read a UTF-8 text file inside a configured root alias."""
    return read_text(settings, root, relative)


@mcp.tool()
def fs_write_text(
    root: str,
    relative: str,
    content: str,
    create_parents: bool = True,
) -> dict:
    """Atomically write a UTF-8 text file inside a configured root alias."""
    return write_text(
        settings,
        root,
        relative,
        content,
        create_parents=create_parents,
    )


@mcp.tool()
def fs_make_dir(root: str, relative: str) -> str:
    """Create a directory inside a configured root alias."""
    return make_dir(settings, root, relative)


@mcp.tool()
def fs_copy(root: str, source: str, destination: str) -> str:
    """Copy a file or directory inside one configured root alias."""
    return copy_path(settings, root, source, destination)


@mcp.tool()
async def command_run(
    argv: list[str],
    cwd_root: str | None = None,
    cwd_relative: str = "",
    timeout_seconds: int = 120,
) -> dict:
    """Run an allow-listed executable on the NAS without a shell."""
    return await run_local(
        settings,
        argv,
        cwd_root=cwd_root,
        cwd_relative=cwd_relative,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
async def ssh_command_run(
    alias: str,
    argv: list[str],
    timeout_seconds: int = 180,
) -> dict:
    """Run an allow-listed command on a preconfigured SSH host alias."""
    return await run_ssh(
        settings,
        alias,
        argv,
        timeout_seconds=timeout_seconds,
    )


def main() -> None:
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
