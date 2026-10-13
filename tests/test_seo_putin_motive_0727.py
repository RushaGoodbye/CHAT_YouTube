from rg_youtube_control.free_tools import _strip_unverified_putin_motive


def test_installed_0724_preview_putin_private_motive_removed():
    source = (
        "Співрозмовник розглядає можливі причини звільнення Шойгу. "
        "Він вважає, що звільнення пов'язане з корупцією, "
        "але Путін утримував його поблизу, щоб контролювати цей процес. "
        "Також обговорюється стратегічна неадекватність Шойгу."
    )
    result = _strip_unverified_putin_motive(source)
    assert "щоб контролювати цей процес" not in result
    assert "Співрозмовник розглядає" in result
    assert "Також обговорюється" in result


def test_legitimate_putin_subject_without_motive_is_kept():
    source = "У випуску співрозмовники обговорюють Путіна та кадрові рішення."
    assert _strip_unverified_putin_motive(source) == source
