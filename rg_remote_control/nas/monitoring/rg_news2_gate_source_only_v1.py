#!/usr/bin/env python3
"""Read-only AST inspection of installed RG NEWS2 private sender."""
import ast
import copy
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
OUT = ROOT / "operator" / "rg_news2_outbound_queue_v2.py"
EXPECTED = "e94253084ea2"
ALLOW = {"status", "photo", "private", "enabled", "disabled", "on", "off"}

class Redact(ast.NodeTransformer):
    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value not in ALLOW:
            return ast.copy_location(ast.Constant(value="[redacted]"), node)
        if isinstance(node.value, (float, int)) and not isinstance(node.value, bool) and abs(node.value) > 99:
            return ast.copy_location(ast.Constant(value=0), node)
        return node

def safe_expr(node):
    # ast.unparse is not available on the NAS /usr/bin/python3.
    # ast.dump works on old Python versions; all literal text is redacted.
    try:
        t = Redact().visit(copy.deepcopy(node))
        return ast.dump(t, annotate_fields=False, include_attributes=False)[:700]
    except (ValueError, TypeError, AttributeError):
        return "[unparsable]"

def inspect(path=OUT, expected=EXPECTED):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("SOURCE_NOT_REGULAR")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest()[:12] != expected:
        raise RuntimeError("SOURCE_SHA_CHANGED")
    root = ast.parse(data.decode("utf-8"))
    selected = ("gates", "photo_auto_gate_open", "run", "private_send_only")
    result = {}
    for node in root.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in selected:
            continue
        guards = []
        for item in ast.walk(node):
            if not isinstance(item, ast.If):
                continue
            raises = sum(isinstance(y, ast.Raise) for st in item.body for y in ast.walk(st))
            guards.append({"line": item.lineno, "test": safe_expr(item.test), "raises": raises})
        result[node.name] = guards[:60]
    return {"status": "SOURCE_ONLY", "hash_verified": True, "telegram_calls": 0,
            "no_database_writes": True, "no_runner_started": True, "guards": result}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        p = pathlib.Path(temp) / "test.py"
        p.write_text("def gates():\n  if Path('/some/path').exists(): raise RuntimeError('private-error')\n")
        expected = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        serialized = json.dumps(inspect(p, expected))
        assert "/some/path" not in serialized
        assert "private-error" not in serialized
        assert "exists" in serialized
        assert "Constant" in serialized
    print("RG_NEWS2_GATE_SOURCE_INSPECT_OLD_PYTHON_SELFTEST_PASS")

if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        selftest()
    elif sys.argv[1:] == ["inspect"]:
        print(json.dumps(inspect(), ensure_ascii=False, indent=2))
    else:
        sys.exit("Only selftest and inspect are supported")
