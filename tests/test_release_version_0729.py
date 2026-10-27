from pathlib import Path
import tomllib


def test_release_version_is_bumped_and_consistent():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    assert tuple(map(int, version.split("."))) >= (0, 7, 30)
    package_source = Path("src/rg_youtube_control/__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{version}"' in package_source


def test_installer_manifest_and_zip_all_use_project_version():
    workflow = Path(".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    installer = Path("packaging/installer.iss").read_text(encoding="utf-8")
    assert "Select-String -Path pyproject.toml" in workflow
    assert '"/DMyAppVersion=$version"' in workflow
    assert 'RG_YouTube_Control_Update_$version.zip' in workflow
    assert 'version = $version' in workflow
    assert 'if ($manifest.version -ne $version)' in workflow
    assert 'if ($hash -ne $expected)' in workflow
    assert 'AppVersion={#MyAppVersion}' in installer
    assert 'OutputBaseFilename=RG_YouTube_Control_Setup_{#MyAppVersion}' in installer
