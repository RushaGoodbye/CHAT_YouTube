"""QA update builds must not advertise an older version than 0.7.32."""
from pathlib import Path
import re


def test_package_version_matches_project_and_new_installed_baseline():
    package = Path("src/rg_youtube_control/__init__.py").read_text(encoding="utf-8")
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    pkg = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"', package, re.M)
    meta = re.search(r'^version = "(\d+\.\d+\.\d+)"', project, re.M)
    assert pkg and meta
    assert pkg.group(1) == meta.group(1)
    assert tuple(map(int, pkg.group(1).split("."))) > (0, 7, 32)
