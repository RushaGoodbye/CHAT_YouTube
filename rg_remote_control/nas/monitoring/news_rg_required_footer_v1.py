#!/usr/bin/env python3
"""Telegram NEWS2 mandatory project footer, offline formatting only.

Do not send Telegram API calls here. Format captions/text after editorial approval.
"""
from html import escape

URL = "https://links.rginfoua.pp.ua/"
LABEL = 'УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ "РАША ГУДБАЙ"'
HTML_FOOTER = '<b><a href="' + URL + '">' + escape(LABEL) + '</a></b>'
MAX_CAPTION = 1024
MAX_TEXT = 4096


class FooterError(ValueError):
    pass


def format_post(text, kind="caption"):
    """Return safely escaped Telegram HTML with a single mandatory bold link.

    Telegram caption/message lengths are checked in visible characters, not
    the markup bytes. Preserve source text without truncation or duplication.
    """
    if kind not in ("caption", "text"):
        raise FooterError("UNSUPPORTED_POST_KIND")
    if not isinstance(text, str):
        raise FooterError("INVALID_POST_TEXT")
    text = text.strip()
    if not text:
        raise FooterError("EMPTY_POST_TEXT")
    if LABEL in text or URL in text:
        raise FooterError("FOOTER_ALREADY_IN_SOURCE")
    limit = MAX_CAPTION if kind == "caption" else MAX_TEXT
    visible = text + "\n\n" + LABEL
    if len(visible) > limit:
        raise FooterError("POST_EXCEEDS_TELEGRAM_LIMIT")
    return escape(text, quote=False) + "\n\n" + HTML_FOOTER


def selftest():
    assert format_post("Тест & <новина>") == (
        "Тест &amp; &lt;новина&gt;\n\n" + HTML_FOOTER)
    assert format_post("Тест", "text").count(URL) == 1
    assert "<b><a href=" in HTML_FOOTER
    assert format_post("x" * (MAX_CAPTION - len(LABEL) - 2)).endswith(HTML_FOOTER)
    for source, kind in [
        (LABEL, "caption"), (URL, "caption"),
        ("", "caption"), ("x" * 1000, "caption"),
        ("x", "untrusted"), (None, "caption")]:
        try:
            format_post(source, kind)
        except FooterError:
            pass
        else:
            raise AssertionError("UNSAFE_POST_ACCEPTED")
    print("RG_NEWS_REQUIRED_FOOTER_FORMATTING_SELFTEST_PASS")
    print("RG_NEWS_REQUIRED_FOOTER_NO_DUPLICATION_PASS")
    print("RG_NEWS_REQUIRED_FOOTER_TELEGRAM_LENGTH_PASS")


if __name__ == "__main__":
    selftest()
