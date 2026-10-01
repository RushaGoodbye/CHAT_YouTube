from rg_youtube_control.comment_rules import classify
from rg_youtube_control.metadata_audit import audit, normalize_links

def test_simple_thanks_is_safe():
    result = classify("Дякую за стрім!")
    assert result.category == "thanks"
    assert result.auto_allowed is True

def test_donate_request_is_safe():
    result = classify("Де реквізити для донату?")
    assert result.category == "donate"
    assert result.auto_allowed is True

def test_political_text_requires_review():
    result = classify("Спасибо, но что вы думаете о войне?")
    assert result.category == "review"
    assert result.auto_allowed is False

def test_unknown_text_requires_review():
    result = classify("Интересный выпуск")
    assert result.category == "review"

def test_old_links_are_replaced():
    source = "https://rg-links-d9e.pages.dev/ https://rg-donates.pages.dev/"
    value = normalize_links(source)
    assert "links.rginfoua.pp.ua" in value
    assert "donate.rginfoua.pp.ua" in value

def test_empty_metadata_needs_work():
    result = audit("", [])
    assert result.needs_update is True
    assert "thin_description" in result.issues
    assert "no_tags" in result.issues

def test_comments_disabled_reason_is_detected():
    import json
    import httplib2
    from googleapiclient.errors import HttpError
    from rg_youtube_control.service import _http_error_reason

    response = httplib2.Response({"status": "403"})
    payload = {
        "error": {
            "code": 403,
            "message": "The video has disabled comments.",
            "errors": [
                {
                    "domain": "youtube.commentThread",
                    "reason": "commentsDisabled",
                    "message": "The video has disabled comments.",
                }
            ],
        }
    }
    exc = HttpError(response, json.dumps(payload).encode("utf-8"))
    assert _http_error_reason(exc) == "commentsDisabled"