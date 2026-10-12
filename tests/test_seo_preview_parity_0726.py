"""Regression for the installed 0.7.23 deep SEO preview, not the offline Shoigu fixture."""
from rg_youtube_control.dialogue_seo import ab_title_issues

def test_gui_preview_generic_shoigu_ab_is_editorial_failure():
    variants = [
        "Почему уволили Шойгу? Коррупция или стратегия?",
        "Шойгу уволили по плану? Внутренние причины",
        "Увольнение Шойгу: дискуссия о причинах",
    ]
    issues = ab_title_issues(variants)
    assert issues, "The bad installed-window titles must not silently pass"
    assert any("надто загальний" in issue for issue in issues)

def test_distinct_specific_angles_do_not_trigger_generic_label():
    variants = [
        "Путин и Шойгу: почему говорили о хороших отношениях?",
        "Коррупция и обвинения: что рассказали о Шойгу?",
        "МЧС и война: что россиянин сказал о стратегии?",
    ]
    assert not any("надто загальний" in issue for issue in ab_title_issues(variants))
