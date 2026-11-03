from rg_youtube_control.seo_source_integrity import audit_source


def make_srt(texts):
    blocks = []
    for i, text in enumerate(texts):
        start, end = i * 5, i * 5 + 4
        blocks.append(
            f"{i+1}\n00:{start//60:02d}:{start%60:02d},000 --> "
            f"00:{end//60:02d}:{end%60:02d},000\n{text}"
        )
    return "\n\n".join(blocks)


def check(texts):
    return audit_source(
        requested_video_id="AbCdEfGh123",
        transcript_video_id="AbCdEfGh123",
        transcript_provenance="youtube_direct",
        srt_content=make_srt(texts),
        video_duration_s=len(texts)*5+2,
    )


def test_repeated_placeholder_content_warns_without_automatic_approval():
    result = check(["[music]"] * 25)
    assert "REPEATED_CAPTION_CONTENT" in result["review_signals"]
    assert result["status"] == "NEEDS_REVIEW"
    assert result["publication_allowed"] is False


def test_cyrillic_mixed_language_is_not_blocked():
    result = check([f"Ми говоримо про питання майбутнього {i}. И разговор на русском." for i in range(25)])
    assert "LANGUAGE_SCRIPT_UNCLEAR" not in result["review_signals"]
    assert result["status"] == "NEEDS_REVIEW"


def test_english_dialogue_is_not_wrongly_rejected():
    result = check([f"Today we discuss public transport in another city {i}" for i in range(25)])
    assert "LANGUAGE_SCRIPT_UNCLEAR" not in result["review_signals"]
    assert result["status"] == "NEEDS_REVIEW"


def test_sparse_content_yields_review_signal():
    result = check(["x"] * 6)
    assert "SPARSE_SPEECH_CONTENT" in result["review_signals"]


def test_non_alphabetic_caption_warns():
    result = check(["111 !!!"] * 12)
    assert "NO_SPEECH_LETTERS" in result["review_signals"]


def test_normal_varied_captions_do_not_trigger_repetition():
    result = check([f"different topic number {i}: transport and local economy" for i in range(25)])
    assert "REPEATED_CAPTION_CONTENT" not in result["review_signals"]
