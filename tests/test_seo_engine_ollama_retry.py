"""Automatic bounded retries must not hide invalid source or cause repeat loops."""
import json
import pytest

from rg_youtube_control import seo_engine_ollama as module
from rg_youtube_control.seo_engine_v1 import generate_draft


VID = "UC-zGLdheCE"
TITLE = "Могут ли ОСУЖДЕННЫЕ преподавать в ШКОЛАХ РФ?"
SOURCE = (
    "Осужденные за тяжкие преступления и безопасность детей в школах РФ. "
    "Родители обсуждают учителей с судимостью и преподавание. " * 9
)


def candidate(tags):
    return json.dumps({
        "title": "СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ РФ? РОССИЯНЕ СПОРЯТ",
        "ab_titles": ["Судимые учителя: реакция родителей",
                      "Педагоги с судимостью: что говорят россияне",
                      "Осужденные и школы: можно ли доверять детей?"],
        "description": ("Росіяни обговорюють, чи можуть засуджені люди "
                        "працювати в школах і як захистити дітей. " * 6),
        "tags": tags,
        "chapters": "",
    }, ensure_ascii=False)


TAGS = ["раша гудбай", "чат рулетка", "судимость", "школы россии",
        "осужденные", "педагоги", "учителя", "россияне"]


def test_one_repair_recovers_bad_tag_count(monkeypatch):
    prompts = []
    def fake_llm(prompt, *, model):
        prompts.append(prompt)
        return candidate(TAGS[:3] if len(prompts) == 1 else TAGS)
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    draft = module.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert len(draft.tags) == 8
    assert len(prompts) == 2
    assert "ПРЕДЫДУЩИЙ ОТВЕТ" in prompts[1]


def test_never_retries_source_title_mismatch(monkeypatch):
    count = 0
    def fake_llm(prompt, *, model):
        nonlocal count
        count += 1
        return candidate(TAGS)
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    with pytest.raises(ValueError, match="SOURCE_VIDEO_MISMATCH"):
        module.generate_with_ollama(
            video_id=VID, current_title=TITLE,
            transcript="Разговор о погоде и ремонте автомобилей. " * 10,
        )
    assert count == 0  # source/title checks run before any paid inference


def test_no_infinite_retry_on_repeated_malformed_model(monkeypatch):
    count = 0
    def fake_llm(prompt, *, model):
        nonlocal count
        count += 1
        return candidate(TAGS[:3])
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    with pytest.raises(ValueError, match="Tags invalid"):
        module.generate_with_ollama(
            video_id=VID, current_title=TITLE, transcript=SOURCE
        )
    assert count == 2


def test_one_repair_corrects_russian_description(monkeypatch):
    count = 0
    def fake_llm(prompt, *, model):
        nonlocal count
        count += 1
        data = json.loads(candidate(TAGS))
        if count == 1:
            data["description"] = (
                "Обсуждение событий войны, действий России и мнений людей. " * 8
            )
        return json.dumps(data, ensure_ascii=False)
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    result = module.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert count == 2
    assert "У цьому" in result.description or "Росіяни" in result.description


def test_one_repair_corrects_ukrainian_headline(monkeypatch):
    count = 0
    def fake_llm(prompt, *, model):
        nonlocal count
        count += 1
        data = json.loads(candidate(TAGS))
        if count == 1:
            data["title"] = "Політична активність та історичні корені"
        return json.dumps(data, ensure_ascii=False)
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    result = module.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert count == 2
    assert "СУДИМЫЕ" in result.title


def test_targeted_russian_headline_repair_after_two_bad_full_answers(monkeypatch):
    from rg_youtube_control import seo_engine_ollama as adapter
    calls = []
    def bad_llm(prompt, *, model):
        calls.append("full")
        data = json.loads(candidate(TAGS))
        data["title"] = "Політична активність та історичні корені"
        return json.dumps(data, ensure_ascii=False)
    def fixed_titles(**kwargs):
        calls.append("titles")
        return {
            "title": "СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ РФ? РОССИЯНЕ СПОРЯТ",
            "ab_titles": [
                "Судимые педагоги: реакция родителей",
                "Школы России и осужденные учителя",
                "Преподавание после тяжкого преступления?",
            ],
        }
    monkeypatch.setattr(adapter, "ollama_json", bad_llm)
    monkeypatch.setattr(adapter, "ollama_titles_json", fixed_titles)
    result = adapter.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert "СУДИМЫЕ" in result.title
    assert calls == ["full", "full", "titles"]



def test_targeted_ukrainian_description_repair_after_two_bad_full_answers(monkeypatch):
    calls = []
    def bad_full(prompt, *, model):
        calls.append("full")
        data = json.loads(candidate(TAGS))
        data["description"] = (
            "Обсуждение событий войны и действий России и участников. " * 12
        )
        return json.dumps(data, ensure_ascii=False)
    def fixed_ukrainian(**kwargs):
        calls.append("description")
        return {"description": json.loads(candidate(TAGS))["description"]}
    monkeypatch.setattr(module, "ollama_json", bad_full)
    monkeypatch.setattr(module, "ollama_description_json", fixed_ukrainian)
    result = module.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert calls == ["full", "full", "description"]
    assert "Росіяни" in result.description


def test_targeted_two_field_repair_is_bounded_and_validated(monkeypatch):
    calls = []
    def bad_full(prompt, *, model):
        calls.append("full")
        data = json.loads(candidate(TAGS))
        data["title"] = "Політична активність та історичні корені"
        data["description"] = (
            "События и обсуждение политики, военных действий в стране. " * 12
        )
        return json.dumps(data, ensure_ascii=False)
    def titles(**kwargs):
        calls.append("titles")
        d = json.loads(candidate(TAGS))
        return {"title": d["title"], "ab_titles": d["ab_titles"]}
    def description(**kwargs):
        calls.append("description")
        return {"description": json.loads(candidate(TAGS))["description"]}
    monkeypatch.setattr(module, "ollama_json", bad_full)
    monkeypatch.setattr(module, "ollama_titles_json", titles)
    monkeypatch.setattr(module, "ollama_description_json", description)
    draft = module.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert draft.needs_review
    assert calls == ["full", "full", "titles", "description"]


def test_ai_summer_headline_rejected_for_school_video():
    from rg_youtube_control.seo_engine_v1 import generate_draft
    d = json.loads(candidate(TAGS))
    d["title"] = "Летние приключения и забавные случаи с друзьями"
    with pytest.raises(ValueError, match="SEO_TOPIC_MISMATCH"):
        generate_draft(video_id=VID, current_title=TITLE, transcript=SOURCE,
                       generate_json=lambda _: json.dumps(d, ensure_ascii=False))


def test_russian_words_with_ukrainian_token_doping_are_rejected():
    from rg_youtube_control.seo_engine_v1 import generate_draft
    d = json.loads(candidate(TAGS))
    d["description"] = (
        "У цьому описании обсуждаются события в России и действия "
        "военных, которые также представлены в тексте. " * 9
    )
    with pytest.raises(ValueError, match="Description must be Ukrainian"):
        generate_draft(video_id=VID, current_title=TITLE, transcript=SOURCE,
                       generate_json=lambda _: json.dumps(d, ensure_ascii=False))



def test_fishing_title_with_military_description_is_blocked():
    from rg_youtube_control.seo_engine_v1 import generate_draft
    title = "Рыбалка в России: разговор о летних приключениях"
    source = (
        "Мы рыбачили на реке летом, рассказываем про рыбалку и приключения. "
        "По пути еще вспоминали военные технологии и лазерное оружие. " * 8
    )
    d = json.loads(candidate(TAGS))
    d["title"] = "Рыбалка летом: приключения на реке"
    d["ab_titles"] = [
        "Летняя рыбалка: истории из походов",
        "Путешествие к реке и необычная рыбалка",
        "Рыбаки рассказывают о своих летних приключениях",
    ]
    d["description"] = (
        "У відео говорять про лазерне озброєння, військові технології, "
        "нові системи боротьби проти дронів та мобілізацію. " * 6
    )
    with pytest.raises(ValueError, match="title and description"):
        generate_draft(
            video_id=VID, current_title=title, transcript=source,
            generate_json=lambda _: json.dumps(d, ensure_ascii=False),
        )


def test_ukrainian_tax_description_matches_russian_tax_title():
    from rg_youtube_control.seo_engine_v1 import generate_draft
    title = "НАЛОГИ И ВОЙНА: КТО ОПЛАЧИВАЕТ БОЕВЫЕ ДЕЙСТВИЯ?"
    source = (
        "Налоги уходят на войну, деньги налогоплательщиков платят "
        "за боевые действия. Жители обсуждают налоговые выплаты. " * 9
    )
    d = json.loads(candidate(TAGS))
    d["title"] = "НАЛОГИ НА ВОЙНУ: КТО ПЛАТИТ И ЗАЧЕМ?"
    d["ab_titles"] = [
        "Куда идут налоги россиян во время войны?",
        "Налогоплательщики и война: кто платит?",
        "На что тратятся деньги и налоги во время войны?",
    ]
    d["description"] = (
        "У відео обговорюють, як податки фінансують війну. "
        "Співрозмовники згадують гроші платників податків, "
        "державні витрати та суспільну відповідальність. " * 5
    )
    assert generate_draft(
        video_id=VID, current_title=title, transcript=source,
        generate_json=lambda _: json.dumps(d, ensure_ascii=False),
    ).needs_review


def test_model_repairs_description_when_title_and_description_diverge(monkeypatch):
    from rg_youtube_control.seo_engine_v1 import generate_draft
    calls = []
    def bad_full(prompt, *, model):
        calls.append("full")
        d = json.loads(candidate(TAGS))
        d["description"] = (
            "У відео згадуються виключно лазерні технології, "
            "ракетне озброєння та військові дрони. " * 7
        )
        return json.dumps(d, ensure_ascii=False)
    def repair_description(**kwargs):
        calls.append("description")
        assert "СУДИМЫЕ УЧИТЕЛЯ" in kwargs["selected_title"]
        return {"description": json.loads(candidate(TAGS))["description"]}
    monkeypatch.setattr(module, "ollama_json", bad_full)
    monkeypatch.setattr(module, "ollama_description_json", repair_description)
    draft = module.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert draft.needs_review
    assert calls == ["full", "full", "description"]
