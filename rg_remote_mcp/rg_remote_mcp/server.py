from __future__ import annotations

from mcp.server import MCPServer

from .config import settings
from .contours import CONTOURS
from .execops import run_local
from .fsops import copy_path, list_dir, make_dir, read_text, write_text
from .sshops import run_ssh

mcp = MCPServer("RG NAS MCP Hub")


@mcp.tool()
def health() -> dict:
    """Return hub status and isolated contour capabilities."""
    return {
        "status": "ok",
        "server": "RG NAS MCP Hub",
        "contours": {
            name: {
                "root": str(contour.root),
                "allowed_commands": sorted(contour.allowed_commands),
            }
            for name, contour in CONTOURS.items()
        },
        "ssh_aliases": sorted(settings.ssh_aliases),
        "max_read_bytes": settings.max_read_bytes,
        "max_write_bytes": settings.max_write_bytes,
    }


def _register_contour(name: str) -> None:
    async def command(
        argv: list[str],
        cwd_relative: str = "",
        timeout_seconds: int = 120,
    ) -> dict:
        return await run_local(
            settings,
            name,
            argv,
            cwd_relative=cwd_relative,
            timeout_seconds=timeout_seconds,
        )

    async def ssh_command(
        alias: str,
        argv: list[str],
        timeout_seconds: int = 180,
    ) -> dict:
        return await run_ssh(
            settings,
            name,
            alias,
            argv,
            timeout_seconds=timeout_seconds,
        )

    def fs_list(relative: str = "") -> list[dict]:
        return list_dir(settings, name, relative)

    def fs_read_text(relative: str) -> str:
        return read_text(settings, name, relative)

    def fs_write_text(
        relative: str,
        content: str,
        create_parents: bool = True,
    ) -> dict:
        return write_text(
            settings,
            name,
            relative,
            content,
            create_parents=create_parents,
        )

    def fs_make_dir(relative: str) -> str:
        return make_dir(settings, name, relative)

    def fs_copy(source: str, destination: str) -> str:
        return copy_path(settings, name, source, destination)

    command.__name__ = f"{name}_command_run"
    ssh_command.__name__ = f"{name}_ssh_command_run"
    fs_list.__name__ = f"{name}_fs_list"
    fs_read_text.__name__ = f"{name}_fs_read_text"
    fs_write_text.__name__ = f"{name}_fs_write_text"
    fs_make_dir.__name__ = f"{name}_fs_make_dir"
    fs_copy.__name__ = f"{name}_fs_copy"

    mcp.tool(name=f"{name}_command_run")(command)
    mcp.tool(name=f"{name}_ssh_command_run")(ssh_command)
    mcp.tool(name=f"{name}_fs_list")(fs_list)
    mcp.tool(name=f"{name}_fs_read_text")(fs_read_text)
    mcp.tool(name=f"{name}_fs_write_text")(fs_write_text)
    mcp.tool(name=f"{name}_fs_make_dir")(fs_make_dir)
    mcp.tool(name=f"{name}_fs_copy")(fs_copy)


for _contour_name in ("youtube", "telegram", "auto_edit"):
    _register_contour(_contour_name)


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
