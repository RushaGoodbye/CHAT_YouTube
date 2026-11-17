from __future__ import annotations

import json
import pytest
from rg_youtube_control.vidiq_review import (
    SOURCE, validate_vidiq_proposals, import_proposals,
    load_inbox, set_editorial_reviewed,
)


def _sample():
    return {
        "source": SOURCE, "channel_id": "UCzaBfIZNcZcFxv4N854UIVQ",
        "publishing_enabled": False, "automatic_approval": False,
        "videos": [{"video_id": "Oh6mcqc_YZo", "applied": False,
                    "title_suggestions": [
                        {"title": "Перша назва від vidIQ", "vidiq_score": 81},
                        {"title": "Друга назва від vidIQ", "vidiq_score": 78},
                        {"title": "Третя назва від vidIQ", "vidiq_score": 75},
                    ]}],
    }


def test_accepts_only_credible_vidiq_export():
    data=validate_vidiq_proposals(
        _sample(),expected_channel_id="UCzaBfIZNcZcFxv4N854UIVQ")
    assert data["type"] == "titles_only"
    assert data["videos"][0]["stage"] == "VIDIQ_SUGGESTED"


@pytest.mark.parametrize("change", [
    lambda d: d.update(source="local generator"),
    lambda d: d.update(channel_id="UCwrong"),
    lambda d: d.update(publishing_enabled=True),
    lambda d: d["videos"][0]["title_suggestions"][0].update(vidiq_score=250),
    lambda d: d["videos"][0]["title_suggestions"][1].update(
        title="Перша назва від vidIQ"),
])
def test_rejects_invalid_or_untrusted_data(change):
    data=_sample()
    change(data)
    with pytest.raises(ValueError):
        validate_vidiq_proposals(data,
                                 expected_channel_id="UCzaBfIZNcZcFxv4N854UIVQ")


def test_persistent_manual_review_and_import_idempotence(tmp_path):
    source=tmp_path/"source.json"
    inbox=tmp_path/"vidiq_inbox.json"
    source.write_text(json.dumps(_sample(),ensure_ascii=False),encoding="utf-8")
    args={"expected_channel_id":"UCzaBfIZNcZcFxv4N854UIVQ",
          "allowed_video_ids":{"Oh6mcqc_YZo"}}
    first=import_proposals(source,inbox,**args)
    assert first["imported"]==1
    assert first["newly_supplied"]==1
    with pytest.raises(ValueError):
        set_editorial_reviewed(inbox,"Oh6mcqc_YZo",confirmed_content=False)
    with pytest.raises(ValueError):
        set_editorial_reviewed(inbox,"Oh6mcqc_YZo",confirmed_content=True)
    with pytest.raises(ValueError):
        set_editorial_reviewed(inbox,"Oh6mcqc_YZo",confirmed_content=True,
                               selected_title="Not a vidIQ candidate")
    selected="Друга назва від vidIQ"
    assert set_editorial_reviewed(inbox,"Oh6mcqc_YZo",confirmed_content=True,
                                  selected_title=selected)
    assert load_inbox(inbox)["videos"][0]["stage"]=="CONTENT_REVIEWED"
    assert load_inbox(inbox)["videos"][0]["selected_title"]==selected
    again=import_proposals(source,inbox,**args)
    assert again["newly_supplied"]==0
    assert load_inbox(inbox)["videos"][0]["stage"]=="CONTENT_REVIEWED"


def test_reject_unknown_ids_without_file(tmp_path):
    src=tmp_path/"source.json"
    src.write_text(json.dumps(_sample()),encoding="utf-8")
    dest=tmp_path/"out.json"
    with pytest.raises(ValueError):
        import_proposals(src,dest,expected_channel_id=_sample()["channel_id"],
                         allowed_video_ids=set())
    assert not dest.exists()


def test_import_never_loses_selected_title_and_approval(tmp_path):
    src=tmp_path/"vidiq_source.json"
    inbox=tmp_path/"vidiq_inbox.json"
    src.write_text(json.dumps(_sample(),ensure_ascii=False),encoding="utf-8")
    kwargs={"expected_channel_id":_sample()["channel_id"],
            "allowed_video_ids":{"Oh6mcqc_YZo"}}
    import_proposals(src,inbox,**kwargs)
    set_editorial_reviewed(inbox,"Oh6mcqc_YZo",confirmed_content=True,
                           selected_title="Третя назва від vidIQ")
    import_proposals(src,inbox,**kwargs)
    actual=load_inbox(inbox)["videos"][0]
    assert actual["stage"]=="CONTENT_REVIEWED"
    assert actual["selected_title"]=="Третя назва від vidIQ"
