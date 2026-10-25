"""Guard against breaking the AlexPC read-only SEO validation entrypoint."""

import importlib.util
from pathlib import Path


def test_real_source_seo_cli_imports_on_qa_branch():
    script = Path(__file__).resolve().parents[1] / "rg_remote_control" / "seo_readonly_acceptance_10.py"
    spec = importlib.util.spec_from_file_location("rg_real_seo_acceptance_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)
    assert callable(module._incidental_ab_quote)
