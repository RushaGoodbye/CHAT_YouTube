from rg_remote_mcp.news2_activation_audit import describe, unpack

def test_readonly_audit_extracts_cli_without_executing():
    code = 'import argparse\np = argparse.ArgumentParser()\np.add_argument("--status")\ndef probe():\n    return "getUpdates"\n'
    report = describe("example.py", code)
    assert report["cli_keywords"] == ["--status"]
    assert "probe" in report["defined_functions"]
    assert report["telegram_api_symbols"] == ["getUpdates"]

def test_mcp_error_never_exposes_content():
    class Fake:
        is_error = True
        content = ["secret token"]
    assert unpack(Fake()) == {"error": "MCP_READ_FAILED"}
