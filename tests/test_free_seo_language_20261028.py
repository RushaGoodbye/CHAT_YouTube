"""Language classifier is optional and may never silently alter metadata."""
import sys
from types import SimpleNamespace

from rg_youtube_control import seo_free_quality as quality
from rg_youtube_control.dialogue_seo import ab_title_issues


class Lang:
    RUSSIAN = "Russian"
    UKRAINIAN = "Ukrainian"


class Detector:
    def compute_language_confidence_values(self, text):
        is_russian = "Кадровые решения" in text
        return [
            SimpleNamespace(language=Lang.RUSSIAN, value=0.98 if is_russian else 0.04),
            SimpleNamespace(language=Lang.UKRAINIAN, value=0.02 if is_russian else 0.96),
        ]


class Builder:
    @classmethod
    def from_languages(cls, *languages):
        assert set(languages) == {Lang.RUSSIAN, Lang.UKRAINIAN}
        return cls()

    def build(self):
        return Detector()


def test_optional_lingua_catches_long_russian_headline(monkeypatch):
    monkeypatch.setitem(sys.modules, "lingua", SimpleNamespace(
        Language=Lang, LanguageDetectorBuilder=Builder,
    ))
    quality._detector_cache.clear()
    title = "Кадровые решения в оборонной сфере: разные позиции собеседников"
    assert quality.russian_language_signal(title)
    assert any("не українською" in reason for reason in ab_title_issues([
        title,
        "Бензин та ціни: що кажуть учасники розмови?",
        "Мобілізація: які наслідки обговорюють співрозмовники?",
    ]))


def test_ukrainian_letters_and_uncertain_language_are_not_false_rejections(monkeypatch):
    monkeypatch.setitem(sys.modules, "lingua", SimpleNamespace(
        Language=Lang, LanguageDetectorBuilder=Builder,
    ))
    quality._detector_cache.clear()
    assert not quality.russian_language_signal(
        "Ціни та корупція: що кажуть співрозмовники про ситуацію?"
    )
    assert not quality.russian_language_signal("Шойгу")


def test_detector_missing_or_model_error_keeps_deterministic_gate(monkeypatch):
    class BrokenBuilder:
        @classmethod
        def from_languages(cls, *languages):
            raise RuntimeError("model unavailable")
    quality._detector_cache.clear()
    monkeypatch.setitem(sys.modules, "lingua", SimpleNamespace(
        Language=Lang, LanguageDetectorBuilder=BrokenBuilder,
    ))
    assert quality.russian_language_signal(
        "Кадровые решения в оборонной сфере: разные позиции собеседников"
    ) is False
    issues = ab_title_issues([
        "Почему коррупция и увольнение: что говорят россияне?",
        "Пальне та ціни: що думають учасники розмови?",
        "Мобілізація: що обговорюють співрозмовники?",
    ])
    assert any("не українською" in issue for issue in issues)


def test_language_signal_is_review_gate_not_evidence_generator():
    from rg_youtube_control.free_tools import _verified_source_ab_titles
    assert _verified_source_ab_titles({"blocks": []}, "Назва") == []
