from rg_youtube_control.seo_caption_corroboration import compare_caption_rows


def make_rows(topic="transport", count=160, offset=0):
    words = ("An interview about " + topic + " and its detailed public response ")
    return [{"text": f"{words}{i+offset}", "start": i*4.0, "duration": 3.5}
            for i in range(count)]


def test_matching_same_topic_passes_review_only():
    v = compare_caption_rows(make_rows(), make_rows())
    assert v["reason"] == "CAPTION_TRANSPORTS_CORROBORATE"
    assert v["status"] == "NEEDS_REVIEW"


def test_different_content_blocks():
    a = make_rows("rural health system science report")
    b = make_rows("astronomy spacecraft asteroid discovery")
    v = compare_caption_rows(a,b)
    assert v["status"] == "BLOCKED_SOURCE"
    assert v["reason"] == "CAPTION_CONTENT_CONFLICT"


def test_different_subtitle_casing_is_allowed():
    a = make_rows()
    b = [dict(r, text=r["text"].upper()) for r in a]
    assert compare_caption_rows(a,b)["reason"] == "CAPTION_TRANSPORTS_CORROBORATE"


def test_unavailable_second_track_stays_review_only():
    v = compare_caption_rows(make_rows(),[])
    assert v["reason"] == "INDEPENDENT_CAPTIONS_UNAVAILABLE"


def test_short_captions_require_review():
    v = compare_caption_rows(make_rows(count=4),make_rows(count=4))
    assert v["reason"] == "INSUFFICIENT_COMPARISON_EVIDENCE"


def test_timeline_shift_fails_when_content_falls_into_different_windows():
    a = make_rows()
    b = [dict(r, start=r["start"]+320) for r in make_rows()]
    assert compare_caption_rows(a,b)["status"] == "BLOCKED_SOURCE"


def test_multilingual_matching_captions_do_not_require_english():
    a = make_rows("Український діалог про бюджет і пенсії")
    b = make_rows("Український діалог про бюджет і пенсії")
    assert compare_caption_rows(a,b)["reason"] == "CAPTION_TRANSPORTS_CORROBORATE"


def test_malformed_metadata_blocks():
    b = make_rows()
    b[0] = {"text":"hi"}
    assert compare_caption_rows(make_rows(),b)["status"] == "BLOCKED_SOURCE"


def test_translated_subtitles_are_review_not_false_conflict():
    a = make_rows("міський транспорт і його тарифи")
    b = make_rows("municipal fares and bus tickets for residents")
    outcome = compare_caption_rows(a, b)
    assert outcome["status"] == "NEEDS_REVIEW"
    assert outcome["reason"] == "CAPTION_LANGUAGE_MISMATCH"
