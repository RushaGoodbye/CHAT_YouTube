"""One research query fans out to FACTAGE/NEWS, Telegram Web and ChatGPT.

Never invent statistics, send private local files, or scrape user cookies. This
module prepares transparent research prompts; browser login and search results
remain under user control.
"""
from __future__ import annotations

import re
from urllib.parse import quote

TELEGRAM_URL = "https://web.telegram.org/k/"
CHATGPT_URL = "https://chatgpt.com/"


def normalize_query(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\s+", " ", text.strip())
    return text[:180]


def research_prompt(text: str) -> str:
    term = normalize_query(text)
    if not term:
        return ""
    return (
        f'Подготовь оперативную фактологическую справку для прямого эфира по теме «{term}».\n'
        'Используй проверяемые, свежие источники и обязательно укажи дату каждого '
        'события и прямые ссылки. Не выдумывай факты, числа и цитаты. '
        'Отделяй проверенную информацию от неподтверждённых сообщений.\n'
        f'1. Последние значимые новости и актуальные социальные, экономические, '
        f'инфраструктурные проблемы «{term}» (предпочтительно за последние 30 дней).\n'
        '2. Если тема относится к городу или региону России: число поимённо '
        'подтверждённых погибших на войне против Украины, географический охват, '
        'метод подсчёта, дата обновления и почему это НЕ равно точному числу '
        'всех погибших. Если достоверного числа нет — так и напиши.\n'
        '3. Школы, детские сады и больницы: сколько объектов реально закрыто '
        'за последние 10 лет, желательно по годам, со ссылками на '
        'официальные реестры/статистику. Отличай закрытие от слияния, '
        'переименования, ремонта и временной остановки. Если полная '
        'статистика отсутствует — не придумывай итоговую цифру.\n'
        '4. Краткие проверяемые вопросы для собеседника в чат-рулетке.\n'
        'Ответ на русском, лаконично, с таблицей «факт — дата — источник — '
        'уровень уверенности». Сомнительные цифры пометь явно.'
    )


def telegram_search_hint(text: str) -> str:
    term = normalize_query(text)
    if not term:
        return "Введите общий запрос для поиска по Telegram."
    return (
        f'Поиск Telegram: «{term}». После входа в Telegram Web нажмите '
        'строку поиска (слева), введите запрос и выберите результаты '
        '«Сообщения». Показаны только доступные вашему аккаунту публикации; '
        'это не весь Telegram.'
    )


def external_site_url(service: str) -> str:
    if service == "telegram":
        return TELEGRAM_URL
    if service == "chatgpt":
        return CHATGPT_URL
    raise ValueError("Unknown external service")
