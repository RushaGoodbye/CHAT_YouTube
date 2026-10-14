from rg_remote_mcp.news2_moderation_static_audit import extract

def test_moderation_static_audit_never_reports_source_literals():
    source = '''SECRET = "sensitive"\ndef send_one():\n    try:\n        api("sendPhoto", SECRET)\n    except Exception:\n        rollback()\n'''
    report = extract(source, "rg_moderation.py")
    assert report["functions"]["send_one"]["has_try"]
    assert "api" in report["functions"]["send_one"]["calls"]
    assert "sensitive" not in str(report)
    assert "Do not enable" in report["risk_notes"][1]
