import sqlite3
import zipfile

from rg_youtube_control.recovery import create_recovery_backup, read_recovery_manifest


def _database(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(data_dir / "rg_youtube_control.db")
    connection.execute("CREATE TABLE IF NOT EXISTS proof (value TEXT)")
    connection.execute("INSERT INTO proof(value) VALUES('safe')")
    connection.commit()
    return connection


def test_pre_update_backup_does_not_copy_its_own_backup_folder(tmp_path):
    data_dir = tmp_path / "RGYouTubeControl"
    backup_root = data_dir / "update-backups"
    stale = backup_root / "PRE_UPDATE_old" / "app_data"
    stale.mkdir(parents=True)
    (stale / "huge_old_file.txt").write_text("old", encoding="utf-8")
    (data_dir / "preferences.json").write_text('{"safe":true}', encoding="utf-8")
    connection = _database(data_dir)
    try:
        archive = create_recovery_backup(
            conn=connection,
            data_dir=data_dir,
            backup_root=backup_root,
            version="0.7.3",
            include_installer=False,
            label="PRE_UPDATE",
        )
    finally:
        connection.close()

    assert archive.is_file()
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert "rg_youtube_control.db" in names
        assert "recovery_manifest.json" in names
        assert "app_data/preferences.json" in names
        assert not any("update-backups" in name for name in names)
        assert not any("huge_old_file" in name for name in names)
        assert zf.testzip() is None
        with zf.open("rg_youtube_control.db") as database:
            assert len(database.read()) > 0
    manifest = read_recovery_manifest(archive)
    assert manifest["version"] == "0.7.3"


def test_backup_root_nested_inside_arbitrary_source_is_excluded(tmp_path):
    data_dir = tmp_path / "RGYouTubeControl"
    backup_root = data_dir / "archive" / "nested" / "backup"
    (data_dir / "archive" / "document.txt").parent.mkdir(parents=True)
    (data_dir / "archive" / "document.txt").write_text("old", encoding="utf-8")
    (data_dir / "config.json").write_text('{"ok":true}', encoding="utf-8")
    connection = _database(data_dir)
    try:
        archive = create_recovery_backup(
            conn=connection,
            data_dir=data_dir,
            backup_root=backup_root,
            version="0.7.4",
            include_installer=False,
        )
    finally:
        connection.close()
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert "rg_youtube_control.db" in names
        assert "app_data/config.json" in names
        assert not any(name.startswith("app_data/archive/") for name in names)
        assert zf.testzip() is None
