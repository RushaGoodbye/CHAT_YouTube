from pathlib import Path
import pytest
from rg_remote_mcp.config import Settings
from rg_remote_mcp.fsops import resolve_path
from rg_remote_mcp.execops import _validate_argv

def settings(tmp_path: Path) -> Settings:
    root=tmp_path/"root"; root.mkdir()
    return Settings(
        host="127.0.0.1",port=8765,roots={"data":root},
        allowed_commands=frozenset({"python","git"}),ssh_aliases={"alexpc":"host:22"},
        ssh_user="u",ssh_key=tmp_path/"key",ssh_known_hosts=tmp_path/"known",
        max_read_bytes=1000,max_write_bytes=1000,
    )

def test_path_escape_blocked(tmp_path):
    s=settings(tmp_path)
    with pytest.raises(ValueError):
        resolve_path(s,"data","../escape.txt")

def test_unknown_root_blocked(tmp_path):
    s=settings(tmp_path)
    with pytest.raises(ValueError):
        resolve_path(s,"other","x")

def test_command_allowlist(tmp_path):
    s=settings(tmp_path)
    assert _validate_argv(s,["python","-V"])[0]=="python"
    with pytest.raises(ValueError):
        _validate_argv(s,["cmd","/c","whoami"])
