from __future__ import annotations

import json

from rg_youtube_control.free_tools import (
    _extract_json_object,
    _video_id,
    parse_google_trends_csv_text,
    summarize_google_trends,
    transcript_text,
)


def test_video_id_from_common_urls() -> None:
    assert _video_id("abcDEF123_-") == "abcDEF123_-"
    assert _video_id("https://www.youtube.com/watch?v=abcDEF123_-") == "abcDEF123_-"
    assert _video_id("https://youtu.be/abcDEF123_-") == "abcDEF123_-"
    assert _video_id("https://www.youtube.com/shorts/abcDEF123_-") == "abcDEF123_-"


def test_extract_json_from_fenced_model_response() -> None:
    result = _extract_json_object(
        """```json
        {"title":"Тест","description":"Опис","tags":["a"]}
        ```"""
    )
    assert result["title"] == "Тест"


def test_transcript_text_has_timestamps_and_limit() -> None:
    rows = [
        {"text": "Перша репліка", "start": 0, "duration": 1.5},
        {"text": "Друга репліка", "start": 65, "duration": 2},
    ]
    value = transcript_text(rows)
    assert "[00:00] Перша репліка" in value
    assert "[01:05] Друга репліка" in value


def test_parse_google_trends_csv() -> None:
    rows = parse_google_trends_csv_text(
        "Категорія: Усі категорії\n\nДата,бензин,Путін\n2026-10-01,65,40\n"
    )
    assert rows == [{"Дата": "2026-10-01", "бензин": "65", "Путін": "40"}]


def test_summarize_google_trends_orders_by_latest_interest() -> None:
    rows = [
        {"Дата": "2026-10-01", "бензин": "40", "Путін": "60"},
        {"Дата": "2026-10-02", "бензин": "90", "Путін": "50"},
    ]
    summary = summarize_google_trends(rows)
    assert summary[0]["term"] == "бензин"
    assert summary[0]["latest"] == 90.0
    assert summary[0]["average"] == 65.0


def test_transcript_sample_text_covers_full_video():
    from rg_youtube_control.free_tools import transcript_sample_text

    rows = [
        {"text": f"line {index}", "start": index * 60, "duration": 5}
        for index in range(60)
    ]
    sampled = transcript_sample_text(rows, max_chars=300, segments=6)

    assert "[00:00]" in sampled
    assert "[59:00]" in sampled
    assert "[...]" in sampled
    assert len(sampled) <= 300


def test_recover_missing_description_uses_plain_text_fallback(monkeypatch) -> None:
    import rg_youtube_control.free_tools as ft

    long_text = (
        "У відео співрозмовник відповідає на запитання про зміни у своєму житті "
        "та оцінює події через власний досвід. Він пояснює, які проблеми помічає "
        "у повсякденності, що вважає важливим і з чим не погоджується. "
        "Розмова переходить до конкретних прикладів, реакцій на запитання ведучого "
        "та аргументів самого співрозмовника. Окремо звучать оцінки ситуації в Росії "
        "і ставлення до подій, які обговорюються під час діалогу."
    )
    replies = iter([
        '{"description":"Коротко."}',
        '{"description":"Ще надто коротко."}',
        long_text,
    ])

    def fake_chat(*_args, **_kwargs):
        return next(replies)

    monkeypatch.setattr(ft, "ollama_chat", fake_chat)
    result = ft._recover_missing_description(
        current_title="Тестова назва",
        transcript="[00:00] тест " * 200,
        public_context={},
        model="qwen3:8b",
    )

    assert len(result) >= 320
    assert result.startswith("У відео")


def test_description_quality_rejects_raw_transcript_dump() -> None:
    from rg_youtube_control.free_tools import _description_quality_error

    transcript = (
        "Тяжелее стало цены поднялись в принципе всё что было так есть просто "
        "цены поднялись немножко ну ясно что кто-то должен это оплачивать "
        "вот оплачиваем ценами конечно вы довольны ну да у всего своя цена "
        "поверьте это ещё не всё вам долго расплачиваться "
    ) * 12
    description = transcript[:1800]

    assert _description_quality_error(description, transcript) in {
        "too_long",
        "not_summary_prose",
        "wrong_language",
        "transcript_copy",
    }


def test_description_quality_accepts_ukrainian_summary() -> None:
    from rg_youtube_control.free_tools import _description_quality_error

    transcript = (
        "Тяжелее стало цены поднялись зарплата изменилась люди отвечают "
        "как изменилась жизнь за год и оценивают ситуацию в России "
    ) * 40
    description = (
        "У цьому випуску росіяни відповідають, як змінилося їхнє життя за 2023 рік. "
        "Співрозмовники говорять про зростання цін, зарплати, пенсії та власний добробут. "
        "Частина учасників стверджує, що живе краще, інші прямо кажуть про погіршення. "
        "Окремо звучать оцінки економіки Росії та ставлення до політики влади. "
        "Розмова показує різні, часто суперечливі відповіді на одне просте запитання."
    )

    assert _description_quality_error(description, transcript) == ""


def test_grounded_description_uses_detected_topics_without_transcript_dump() -> None:
    from rg_youtube_control.free_tools import (
        _description_quality_error,
        _grounded_description_from_transcript,
    )

    transcript = (
        "[00:00] цены поднялись и стало дороже жить\n"
        "[01:00] зарплата поднялась\n"
        "[02:00] мне добавили пенсию\n"
        "[03:00] экономика улучшается\n"
        "[04:00] 90 процентов будут голосовать за Путина\n"
    ) * 12
    description = _grounded_description_from_transcript(
        "Как улучшилась жизнь россиян за прошедший 2023 год? | РАША ГУДБАЙ",
        transcript,
    )

    assert "ціни та вартість життя" in description
    assert "зарплати та доходи" in description
    assert "пенсії та соціальні виплати" in description
    assert "економіка Росії" in description
    assert "цены поднялись" not in description
    assert "Опис побудовано" not in description
    assert "Дивіться повну розмову" in description
    assert _description_quality_error(description, transcript) == ""


def test_grounded_tags_fill_local_seo_package() -> None:
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript

    tags = _grounded_tags_from_transcript(
        "Как улучшилась жизнь россиян за прошедший 2023 год? | РАША ГУДБАЙ",
        (
            "Цены выросли. Зарплата изменилась. Мне добавили пенсию. "
            "Экономика улучшается. 90 процентов будут голосовать за Путина. "
        ) * 20,
    )

    assert 8 <= len(tags) <= 15
    assert "РАША ГУДБАЙ" in tags
    assert "чат рулетка" in tags
    assert "цены в России" in tags
    assert "зарплаты в России" in tags
    assert "пенсии в России" in tags
    assert "экономика России" in tags


def test_preserve_current_title_when_candidate_only_strips_brand() -> None:
    from rg_youtube_control.free_tools import (
        _preserve_current_title_when_candidate_is_not_stronger,
    )

    current = "Как улучшилась жизнь россиян за прошедший 2023 год? | РАША ГУДБАЙ"
    candidate = "Как улучшилась жизнь россиян за прошедший 2023 год"

    assert (
        _preserve_current_title_when_candidate_is_not_stronger(
            current,
            candidate,
        )
        == current
    )


def test_accept_stronger_candidate_title_with_new_meaningful_words() -> None:
    from rg_youtube_control.free_tools import (
        _preserve_current_title_when_candidate_is_not_stronger,
    )

    current = "Как улучшилась жизнь россиян за прошедший 2023 год? | РАША ГУДБАЙ"
    candidate = "Россияне о ценах и зарплатах: как изменилась жизнь за 2023 год?"

    assert (
        _preserve_current_title_when_candidate_is_not_stronger(
            current,
            candidate,
        )
        == candidate
    )


def test_specific_shoigu_tags_beat_generic_model_words() -> None:
    from rg_youtube_control.free_tools import (
        _grounded_tags_from_transcript,
        _tag_is_grounded,
    )

    title = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
    transcript = (
        "Обсуждаем Шойгу, увольнение, Министерство обороны России и коррупцию. "
        "Собеседники спорят о причинах кадровых решений. "
    ) * 12

    tags = _grounded_tags_from_transcript(title, transcript)

    assert "Шойгу" in tags
    assert "увольнение Шойгу" in tags
    assert "Министерство обороны России" in tags
    assert "коррупция в России" in tags
    assert _tag_is_grounded("план", title, transcript) is False
    assert _tag_is_grounded("стратегия", title, transcript) is False
    assert _tag_is_grounded("Шойгу", title, transcript) is True


def test_fast_mode_reuses_current_title_when_model_omits_title(monkeypatch):
    from rg_youtube_control import free_tools

    monkeypatch.setattr(
        free_tools,
        "ollama_chat",
        lambda *args, **kwargs: (
            '{"title":"","title_variants":["Вариант 1","Вариант 2","Вариант 3"],'
            '"description":"У цьому випуску чат-рулетки росіяни обговорюють бензин у Росії. '
            'Співрозмовники говорять про ціни на пальне, ситуацію на АЗС та власний досвід. '
            'У розмові звучать різні оцінки причин дефіциту й вартості пального. '
            'Позиції учасників відрізняються, тому відео показує кілька поглядів на тему.",'
            '"tags":["РАША ГУДБАЙ","чат рулетка","Россия","россияне","мнение россиян",'
            '"вопросы россиянам","бензин в России","цены в России"],"chapters":""}'
        ),
    )

    result = free_tools.generate_seo_package_local(
        current_title="Хотел доказать, что бензин есть - и передумал",
        transcript="[00:00] бензин в России и цены на АЗС",
        public_context={},
        fast_mode=True,
        timeout=1,
    )

    assert result["title"] == "Хотел доказать, что бензин есть - и передумал"


def test_fast_mode_strips_legacy_stream_branding(monkeypatch):
    from rg_youtube_control import free_tools

    monkeypatch.setattr(
        free_tools,
        "ollama_chat",
        lambda *args, **kwargs: (
            '{"title":"ЧАТ РУЛЕТКА. Беларусь и Украина | РАША ГУДБАЙ СТРИМ👍 @RUSSIAGOODBYE_LIVE",'
            '"title_variants":["Беларусь и Украина","Лукашенко и Беларусь","Беларусь о войне"],'
            '"description":"У цьому випуску чат-рулетки співрозмовники обговорюють Білорусь, Лукашенка та Україну. '
            'Розмова стосується позиції Білорусі, оцінок війни та відповідальності за рішення. '
            'Учасники висловлюють різні погляди й сперечаються про роль держави у подіях. '
            'Формулювання передають позиції співрозмовників без додавання непідтверджених фактів.",'
            '"tags":["РАША ГУДБАЙ","чат рулетка","Беларусь","Лукашенко","Украина",'
            '"Беларусь и Украина","Россия","мнение россиян"],"chapters":""}'
        ),
    )

    result = free_tools.generate_seo_package_local(
        current_title="ЧАТ РУЛЕТКА. Беларусь и Украина | РАША ГУДБАЙ СТРИМ👍 @RUSSIAGOODBYE_LIVE",
        transcript=(
            "[00:00] Беларусь Лукашенко Украина война. "
            "Собеседники спорят о роли Беларуси и ответственности."
        ) * 20,
        public_context={},
        fast_mode=True,
        timeout=1,
    )

    assert "@RUSSIAGOODBYE_LIVE" not in result["title"]
    assert "РАША ГУДБАЙ СТРИМ" not in result["title"]


def test_belarus_grounded_tags_are_specific() -> None:
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript

    tags = _grounded_tags_from_transcript(
        "ЧАТ РУЛЕТКА. Беларусь и Украина",
        ("Лукашенко Беларусь Украина. " * 20),
    )

    assert "Лукашенко" in tags
    assert "Беларусь" in tags
    assert "Украина" in tags
    assert "Беларусь и Украина" in tags


def test_generic_fast_chapters_are_removed(monkeypatch):
    from rg_youtube_control import free_tools

    monkeypatch.setattr(
        free_tools,
        "ollama_chat",
        lambda *args, **kwargs: (
            '{"title":"Беларусь и Украина",'
            '"title_variants":["Беларусь и Украина: разговор","Лукашенко и Беларусь","Беларусь о войне"],'
            '"description":"У цьому випуску чат-рулетки співрозмовники обговорюють Білорусь, Лукашенка та Україну. '
            'Розмова стосується позиції Білорусі, оцінок війни та відповідальності за рішення. '
            'Учасники висловлюють різні погляди й сперечаються про роль держави у подіях. '
            'Формулювання передають позиції співрозмовників без додавання непідтверджених фактів.",'
            '"tags":["РАША ГУДБАЙ","чат рулетка","Беларусь","Лукашенко","Украина",'
            '"Беларусь и Украина","Россия","мнение россиян"],'
            '"chapters":"00:00 Вступ\\n05:20 Наступний блок\\n12:40 Фінальна частина"}'
        ),
    )

    transcript = (
        "[00:00] Беларусь Лукашенко Украина. "
        "[05:20] разговор продолжается. "
        "[12:40] финальная реплика. "
    ) * 20
    result = free_tools.generate_seo_package_local(
        current_title="Беларусь и Украина",
        transcript=transcript,
        public_context={},
        fast_mode=True,
        timeout=1,
    )

    assert result["chapters"] == ""


def test_parse_srt_transcript_rows() -> None:
    from rg_youtube_control.free_tools import parse_srt_transcript

    rows = parse_srt_transcript(
        "1\n00:00:01,000 --> 00:00:03,500\nПривіт світ\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\nДруга репліка\n"
    )

    assert len(rows) == 2
    assert rows[0]["text"] == "Привіт світ"
    assert rows[0]["start"] == 1.0
    assert rows[0]["duration"] == 2.5


def test_fetch_transcript_from_public_metadata_uses_json3(monkeypatch) -> None:
    import json as _json
    from rg_youtube_control import free_tools

    payload = {
        "events": [
            {
                "tStartMs": 1000,
                "dDurationMs": 1500,
                "segs": [{"utf8": "Привіт "}, {"utf8": "світ"}],
            }
        ]
    }

    class _Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return _json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        free_tools.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response(),
    )

    rows = free_tools.fetch_transcript_from_public_metadata(
        {
            "_caption_tracks": {
                "manual": {},
                "automatic": {
                    "ru": [
                        {
                            "ext": "json3",
                            "url": "https://example.invalid/captions",
                        }
                    ]
                },
            }
        }
    )

    assert rows == [
        {"text": "Привіт світ", "start": 1.0, "duration": 1.5}
    ]


def test_fetch_transcript_accepts_unexpected_available_language(monkeypatch) -> None:
    from rg_youtube_control import free_tools

    class _Fetched:
        def to_raw_data(self):
            return [{"text": "текст", "start": 1.0, "duration": 2.0}]

    class _Transcript:
        language_code = "be"
        is_generated = True
        is_translatable = False
        def fetch(self):
            return _Fetched()

    class _List:
        def find_transcript(self, _languages):
            raise RuntimeError("no preferred language")
        def __iter__(self):
            return iter([_Transcript()])

    class _Api:
        def list(self, _video_id):
            return _List()

    import youtube_transcript_api
    monkeypatch.setattr(
        youtube_transcript_api,
        "YouTubeTranscriptApi",
        lambda: _Api(),
    )

    rows = free_tools.fetch_transcript("abc123XYZ")

    assert rows == [{"text": "текст", "start": 1.0, "duration": 2.0}]


def test_parse_webvtt_transcript_rows() -> None:
    from rg_youtube_control.free_tools import parse_webvtt_transcript

    rows = parse_webvtt_transcript(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Перша репліка\n\n"
        "00:00:04.500 --> 00:00:06.000\n"
        "<c>Друга репліка</c>\n"
    )

    assert len(rows) == 2
    assert rows[0]["text"] == "Перша репліка"
    assert rows[1]["text"] == "Друга репліка"
