"""Select evidence from the full video, not just the first dialogue."""
from rg_youtube_control.seo_source_excerpt import select_source_excerpt


def test_late_source_subject_gets_into_ollama_context():
    opening = ("Случайная беседа о рыбалке, погоде и соседях. " * 1300)
    middle = ("Проехали мимо вокзала и говорили о машинах. " * 1000)
    ending = ("В КРАСНОДАРЕ ВОЗНИК ДЕФИЦИТ БЕНЗИНА, на заправках очередь. " * 160)
    transcript = opening + middle + ending
    assert "ДЕФИЦИТ БЕНЗИНА" not in transcript[:23000]
    excerpt = select_source_excerpt(
        "ДЕФИЦИТ БЕНЗИНА В КРАСНОДАРЕ", transcript, char_budget=10000
    )
    assert "ДЕФИЦИТ БЕНЗИНА" in excerpt
    assert len(excerpt) <= 10000
    assert excerpt.find("рыбалке") < excerpt.find("БЕНЗИНА")


def test_middle_subject_is_visible_for_targeted_description_repair():
    first = "Беседа о музыке и семьях. " * 1800
    subject = "НАЛОГИ ПЛАТЯТ НА ВОЙНУ, налогоплательщики спорят о налогах. " * 120
    last = "Рыбалка и погода. " * 1500
    transcript = first + subject + last
    excerpt = select_source_excerpt("НАЛОГИ И ВОЙНА", transcript, char_budget=6000)
    assert "НАЛОГИ" in excerpt
    assert len(excerpt) <= 6000


def test_short_transcript_is_not_modified():
    text = "Настоящая исходная расшифровка." * 4
    assert select_source_excerpt("Тема", text, char_budget=4000) == text


def test_long_transcript_has_start_middle_end_without_subject_overlap():
    text = (
        "Начало. " * 800 +
        "Середина. " * 800 +
        "Концовка. " * 800
    )
    excerpt = select_source_excerpt("Бесполезный заголовок", text,
                                    char_budget=9000)
    assert "Начало" in excerpt
    assert "Середина" in excerpt
    assert "Концовка" in excerpt


def test_excerpt_has_no_paraphrased_source_claims():
    transcript = ("раз-два-три " * 14000).strip()
    excerpt = select_source_excerpt("Контекст", transcript, char_budget=8000)
    # Extractor never inserts generated factual sentences.
    for fragment in excerpt.split("\n[…]\n"):
        assert fragment.replace(" ", "") in transcript.replace(" ", "")
