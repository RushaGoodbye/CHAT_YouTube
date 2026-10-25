"""Desktop and generator must reject exactly the same incidental SEO hooks."""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from rg_youtube_control.seo_editorial_signal import (
    is_incidental_seo_headline,
    off_topic_title_warnings,
)
from rg_youtube_control.ui import ContentOptimizationDialog


MAIN = "Увольнение Шойгу — коррупция или все идет по плану? | РАША ГУДБАЙ"


@settings(max_examples=65, deadline=None, derandomize=True)
@given(
    distraction=st.sampled_from([
        "рубашка", "рубаха", "сорочка", "одежда", "одяг", "футболка",
        "причёска", "зачіска", "красивый", "выглядишь",
        "как дела", "привет", "дякую за розмову",
    ]),
    prefix=st.text(alphabet=" ABCDEFG0123456789", min_size=0, max_size=15),
    suffix=st.text(alphabet=" ABCDEFG0123456789", min_size=0, max_size=15),
)
def test_incidental_titles_cannot_pass_generator_or_gui(distraction, prefix, suffix):
    candidate = f"{prefix} {distraction} {suffix}"
    assert is_incidental_seo_headline(MAIN, candidate)
    # The UI numbers the main title as variant 1 and 3 A/B titles as 2–4.
    assert off_topic_title_warnings(
        MAIN,
        ["Шойгу и коррупция: что говорили россияне?",
         "МЧС и Минобороны: о чем спорили собеседники?",
         "Путин и Шойгу: разговор о кадровой перестановке?",
         candidate],
    ) == ["Варіант 4 просуває випадкову репліку про зовнішність"]


def test_clothing_is_allowed_when_it_is_the_actual_video_subject():
    original = "Какая рубашка лучше для съёмки YouTube видео?"
    assert not is_incidental_seo_headline(original, "Почему эта рубашка удобна для съёмки?")
    assert not off_topic_title_warnings(original, ["Рубашка для записи стрима: советы"])


def test_generator_calls_same_policy_as_gui():
    import inspect
    from rg_youtube_control.free_tools import generate_seo_package_local
    source = inspect.getsource(generate_seo_package_local)
    assert "is_incidental_seo_headline(current_title, value)" in source


def test_qt_editor_rejects_same_fourth_appearance_headline(qtbot):
    dialog = ContentOptimizationDialog(
        "Шойгу и коррупция — что говорили россияне?",
        "Выпуск чат-рулетки о кадровых решениях и мнениях россиян.",
        "",
        ["Шойгу", "чат рулетка"],
        "draft",
        title_variants=[
            "Шойгу: о чём спорили россияне?",
            "Уход Шойгу: коррупция или план?",
            "Шойгу и рубашка: как выглядит ведущий?",
        ],
    )
    qtbot.addWidget(dialog)
    title, _, _, _, _, ab = dialog.values()
    assert len(ab) == 3
    assert off_topic_title_warnings(MAIN, [title, *ab]) == [
        "Варіант 4 просуває випадкову репліку про зовнішність"
    ]
