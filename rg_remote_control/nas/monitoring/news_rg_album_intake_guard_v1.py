#!/usr/bin/env python3
"""Safe, offline-first Telegram public-post album inspection.

No Telegram Bot API or MTProto. No downloads, writes, posting or polling.
This does not turn public previews into source-quality video files.
"""
import argparse
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

CHANNEL = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
POST_ID = re.compile(r"[1-9][0-9]{0,14}")
FOOTER_LABEL = 'УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ "РАША ГУДБАЙ"'
FOOTER_URL = "https://links.rginfoua.pp.ua/"

def canonical_post(url):
    if not isinstance(url, str) or len(url) > 300:
        raise ValueError("INVALID_URL")
    p = urlsplit(url.strip())
    if p.scheme != "https" or p.hostname not in ("t.me", "telegram.me"):
        raise ValueError("INVALID_SOURCE_HOST")
    if p.username or p.password or p.port is not None or p.fragment:
        raise ValueError("INVALID_SOURCE_AUTH")
    parts = p.path.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "s":
        parts = parts[1:]
    if len(parts) != 2 or not CHANNEL.fullmatch(parts[0]) or not POST_ID.fullmatch(parts[1]):
        raise ValueError("INVALID_SOURCE_PATH")
    return "https://t.me/" + parts[0] + "/" + parts[1]

def source_key(url):
    return hashlib.sha256(("RG_NEWS_SOURCE_V1\0" + canonical_post(url)).encode()).hexdigest()[:24]

class Album(HTMLParser):
    def __init__(self, expected):
        super().__init__(convert_charrefs=True)
        self.expected = expected
        self.active = False
        self.depth = 0
        self.video = 0
        self.photo = 0
        self.text = []
        self.text_depth = 0
        self.found = 0
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if not self.active:
            if d.get("data-post") == self.expected and "tgme_widget_message" in d.get("class", "").split():
                self.active, self.depth = True, 1
                self.found += 1
            return
        if tag in ("br", "img", "source", "meta", "input", "link", "hr"):
            if tag == "br" and self.text_depth:
                self.text.append(" ")
            return
        self.depth += 1
        classes = d.get("class", "").split()
        if "tgme_widget_message_video_player" in classes and tag == "a":
            self.video += 1
        if "tgme_widget_message_photo_wrap" in classes:
            self.photo += 1
        if "tgme_widget_message_text" in classes:
            self.text_depth = self.depth
    def handle_data(self, data):
        if self.active and self.text_depth:
            self.text.append(data)
    def handle_endtag(self, tag):
        if not self.active or tag in ("br", "img", "source", "meta", "input", "link", "hr"):
            return
        if self.text_depth == self.depth:
            self.text_depth = 0
        self.depth -= 1
        if self.depth <= 0:
            self.active, self.depth = False, 0

def inspect(source_url, document):
    canonical = canonical_post(source_url)
    path = urlsplit(canonical).path.strip("/")
    if not isinstance(document, str) or len(document) > 2_000_000:
        raise ValueError("INVALID_HTML")
    parser = Album(path)
    parser.feed(document)
    if parser.found != 1:
        raise ValueError("POST_NOT_EXACTLY_ONCE")
    return {
        "source": canonical,
        "source_key": source_key(canonical),
        "media_kind": ("video_album" if parser.video > 1 else "video" if parser.video == 1
                       else "photo" if parser.photo else "unknown"),
        "video_count": parser.video,
        "photo_count": parser.photo,
        "text_excerpt": " ".join(html.unescape(" ".join(parser.text)).split())[:300],
        "original_files_verified": False,
        "publication_allowed": False,
    }

def required_footer(text):
    if not isinstance(text, str):
        raise ValueError("INVALID_POST_TEXT")
    # Telegram HTML formatting; the URL must be explicitly embedded.
    label = html.escape(FOOTER_LABEL)
    return text.rstrip() + '\n\n<b><a href="' + FOOTER_URL + '">' + label + "</a></b>"

def selftest():
    source = "https://t.me/supernova_plus/62837"
    assert canonical_post(source + "?utm_source=chatgpt.com") == source
    assert canonical_post("https://t.me/supernova_plus/62837?embed=1") == source
    assert source_key(source) == source_key(source + "?utm_source=abc")
    for evil in ("http://t.me/supernova_plus/62837", "https://t.me.evil.com/supernova_plus/62837",
                 "https://user:password@t.me/supernova_plus/62837",
                 "https://t.me/supernova_plus/not-a-number",
                 "https://t.me/supernova_plus/62837#fragment"):
        try: canonical_post(evil)
        except ValueError: pass
        else: raise AssertionError("UNSAFE_SOURCE_ACCEPTED")
    media = '<a class="tgme_widget_message_video_player" href="https://t.me/x"></a>'
    fixture = '<div class="tgme_widget_message" data-post="supernova_plus/62837">' + media*3 + '<div class="tgme_widget_message_text">Крим</div></div>'
    out = inspect(source, fixture)
    assert out["video_count"] == 3 and out["media_kind"] == "video_album"
    assert not out["publication_allowed"] and not out["original_files_verified"]
    for wrong in (fixture.replace("62837", "62838"), fixture + fixture):
        try: inspect(source, wrong)
        except ValueError: pass
        else: raise AssertionError("POST_ID_GUARD_FAILED")
    footer = required_footer("Тест")
    assert footer.count(FOOTER_URL) == 1 and footer.count(FOOTER_LABEL) == 1
    print("RG_ALBUM_INTAKE_GUARD_SELFTEST_PASS")
    print("VIDEO_ALBUM_3_FIXTURE_PASS")
    print("URL_NORMALIZATION_AND_DEDUP_PASS")
    print("PUBLICATION_HARD_OFF_PASS")
    print("FOOTER_FORMAT_PASS")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["selftest", "inspect"])
    ap.add_argument("--source", default="https://t.me/supernova_plus/62837")
    ap.add_argument("--file", help="Local saved public embed HTML; no network requests")
    args = ap.parse_args()
    if args.action == "selftest":
        selftest()
    else:
        if not args.file: ap.error("--file required")
        with open(args.file, encoding="utf-8") as f: document = f.read(2_000_001)
        print(json.dumps(inspect(args.source, document), ensure_ascii=False, sort_keys=True))
