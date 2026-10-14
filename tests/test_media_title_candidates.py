from rg_youtube_control.local_media_sources import discover_title_candidates


def test_title_candidates_only_media_and_never_auto_bind(tmp_path):
    (tmp_path / "РАША ГУДБАЙ ЧАТ РУЛЕТКА СКАЗОЧНЫЕ ЕМЕЛИ.mp4").write_bytes(b"movie")
    (tmp_path / "РАША ГУДБАЙ ЧАТ РУЛЕТКА СКАЗОЧНЫЕ ЕМЕЛИ.jpg").write_bytes(b"cover")
    matches = discover_title_candidates("РАША ГУДБАЙ ЧАТ РУЛЕТКА СКАЗОЧНЫЕ ЕМЕЛИ", [tmp_path])
    assert len(matches) == 1
    assert matches[0][1].suffix == ".mp4"


def test_missing_folder_safe(tmp_path):
    assert discover_title_candidates("example", [tmp_path / "missing"]) == []
