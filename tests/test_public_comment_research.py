import sys
import types
from pathlib import Path

import pytest

from rg_youtube_control.public_comments import (
    csv_safe_public_comment_cell,
    fetch_public_comment_sample,
)


def test_public_comment_research_is_read_only_and_has_no_api_usage(monkeypatch):
    observed = {}

    class FakeDownloader:
        def get_comments_from_url(self, url, *, sort_by):
            observed["url"] = url
            observed["sort_by"] = sort_by
            yield {"cid": "c-1", "author": "Viewer", "text": "Тема про ціни цікава", "votes": "12", "time": "1 day"}
            yield {"cid": "c-2", "author": "Viewer2", "text": "Бензин подорожчав", "votes": "2"}
            yield {"cid": "c-3", "author": "Viewer3", "text": "extra"}

    fake = types.SimpleNamespace(
        YoutubeCommentDownloader=FakeDownloader,
        SORT_BY_RECENT=123,
    )
    monkeypatch.setitem(sys.modules, "youtube_comment_downloader", fake)
    result = fetch_public_comment_sample("dQw4w9WgXcQ", limit=2)
    assert observed == {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "sort_by": 123,
    }
    assert result["read_only"] is True
    assert result["youtube_data_api_units"] == 0
    assert len(result["comments"]) == 2
    assert result["comments"][0]["comment_id"] == "c-1"
    assert result["comments"][0]["comment"] == "Тема про ціни цікава"


@pytest.mark.parametrize("value", ["", "https://example.org/", "../test", "abcdefg", "xxxxxxxxxxxx"])
def test_public_comments_reject_invalid_ids_without_network(value):
    with pytest.raises(ValueError):
        fetch_public_comment_sample(value)


def test_public_comments_ui_exports_csv_only():
    ui = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    begin = ui.index("    def export_public_comments_zero_api")
    end = ui.index("    def export_comments_for_analysis", begin)
    block = ui[begin:end]
    assert "fetch_public_comment_sample(video_id, limit=100)" in block
    assert "csv.DictWriter" in block
    assert "YouTube не змінено" in block
    assert "reply_selected" not in block
    assert "set_comment_status" not in block
    assert "like_comment" not in block



@pytest.mark.parametrize(
    "text",
    ["=1+1", "+SUM(A1:A4)", "@XLOOKUP(A1,B1,C1)", "-2+3", " \t=HYPERLINK(\"https://bad.example\")"],
)
def test_public_comments_csv_formula_injection_is_escaped(text):
    value = csv_safe_public_comment_cell(text)
    assert value.startswith("'")
    assert value.endswith(text)


def test_public_comments_csv_safe_plain_text():
    assert csv_safe_public_comment_cell("Спасибо за видео") == "Спасибо за видео"
