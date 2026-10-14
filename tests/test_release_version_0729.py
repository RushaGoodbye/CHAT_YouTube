from pathlib import Path
import tomllib


def test_release_version_is_bumped_and_consistent():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    assert tuple(map(int, version.split("."))) >= (0, 7, 30)
    package_source = Path("src/rg_youtube_control/__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{version}"' in package_source
