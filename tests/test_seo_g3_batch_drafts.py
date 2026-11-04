import json
import pytest
from rg_youtube_control.seo_g3_batch_drafts import (
    prepare_source_packet, draft_seo_package, evaluate_independent_draft,
)

VID="7AB5scCmIIU"
def cards(provisional=False):
    return [
        {"video_id":VID,"record_id":1,"start_s":0,"status":
         "PROVISIONAL_SOURCE_REVIEW" if provisional else "SOURCE_QUOTED_AI_RISK",
         "source_quote":"Співрозмовник питає про ставлення до Росії.",
         "source_context":"Співрозмовник питає про ставлення до Росії. Гість пояснює свою позицію щодо суспільства.",
         "candidate_topic":"Розмова про ставлення до російського суспільства",
         "publication_allowed":False}
    ]
def good_package():
    return {
        "title":"Співрозмовник пояснює своє ставлення до Росії",
        "title_variants":[
            "Як у розмові пояснюють ставлення до Росії?",
            "Позиція гостя щодо російського суспільства",
            "Що каже співрозмовник про суспільство Росії?"
        ],
        "description":("У цьому діалозі співрозмовники обговорюють ставлення до Росії та її суспільства. "
          "Гість пояснює власну позицію, а ведучий ставить запитання й уточнює думку. "
          "У відео представлені саме висловлювання учасників, а не перевірені незалежні висновки. "
          "Перегляньте розмову, щоб зрозуміти аргументи кожного та контекст сказаного."),
        "tags":["Раша Гудбай","чат рулетка","розмова","Росія","суспільство",
                "українська мова","діалог","думки співрозмовників"],
    }
def test_source_packet_fail_closed_on_mismatch():
    p=cards()
    p[0]["source_quote"]="Not really present in context"
    with pytest.raises(ValueError,match="SOURCE_QUOTE"):
        prepare_source_packet(video_id=VID,cards=p)
def test_generated_complete_draft_is_always_unpublished():
    p=prepare_source_packet(video_id=VID,cards=cards())
    result=draft_seo_package(source=p,chat=lambda m:json.dumps(good_package(),ensure_ascii=False))
    assert result["status"]=="READY_FOR_INDEPENDENT_AI_REVIEW"
    assert result["quality_checks"]["format_pass"] is True
    assert not result["g3_accepted"] and not result["publication_allowed"]
def test_numeric_hallucination_hard_stop():
    p=prepare_source_packet(video_id=VID,cards=cards())
    obj=good_package();obj["title"]+=": 1941"
    result=draft_seo_package(source=p,chat=lambda m:json.dumps(obj,ensure_ascii=False))
    assert "UNSUPPORTED_NUMBERS" in result["blockers"]
    assert "1941" in result["quality_checks"]["unsupported_numbers"]
def test_provisional_source_never_auto_clears():
    p=prepare_source_packet(video_id=VID,cards=cards(provisional=True))
    result=draft_seo_package(source=p,chat=lambda m:json.dumps(good_package(),ensure_ascii=False))
    assert "PROVISIONAL_SOURCE_REVIEW" in result["blockers"]
def test_independent_critic_ai_low_does_not_approve():
    p=prepare_source_packet(video_id=VID,cards=cards())
    result=draft_seo_package(source=p,chat=lambda m:json.dumps(good_package(),ensure_ascii=False))
    reviewed=evaluate_independent_draft(draft=result,source=p,
        chat=lambda m:json.dumps({"risk":"low","issues":[]}))
    assert reviewed["status"]=="AI_SCREENED_DRAFT"
    assert reviewed["editorial_review_required"]
    assert not reviewed["human_approved"] and not reviewed["publication_allowed"]
def test_source_mismatch_blocks_independent_review():
    p=prepare_source_packet(video_id=VID,cards=cards())
    result=draft_seo_package(source=p,chat=lambda m:json.dumps(good_package(),ensure_ascii=False))
    result["source_packet_sha256"]="bad"
    with pytest.raises(ValueError,match="SOURCE_DRAFT_MISMATCH"):
        evaluate_independent_draft(draft=result,source=p,chat=lambda _: "{}")
def test_model_failure_does_not_fabricate_output():
    p=prepare_source_packet(video_id=VID,cards=cards())
    with pytest.raises(ValueError,match="MODEL_DID_NOT_RETURN_JSON"):
        draft_seo_package(source=p,chat=lambda _: "")


def test_bounded_repair_inherits_source_and_requires_new_independent_critic():
    from rg_youtube_control.seo_g3_batch_drafts import repair_seo_package
    source=prepare_source_packet(video_id=VID,cards=cards())
    broken=good_package()
    broken["title_variants"]=["Дубль","Дубль","Дубль"]
    prior=draft_seo_package(source=source,chat=lambda _:json.dumps(broken,ensure_ascii=False))
    critique=evaluate_independent_draft(draft=prior,source=source,
        chat=lambda _:json.dumps({"risk":"medium","issues":["Duplicated alternatives"]}))
    repaired=repair_seo_package(source=source,previous=prior,critique=critique,
        chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    assert repaired["status"]=="READY_FOR_INDEPENDENT_AI_REVIEW"
    assert repaired["repair_attempt"]==1
    assert repaired["independent_recheck_required"]
    assert repaired["source_packet_sha256"]==source["source_packet_sha256"]
    assert not repaired["publication_allowed"] and not repaired["g3_accepted"]

def test_repair_refuses_source_swap():
    from rg_youtube_control.seo_g3_batch_drafts import repair_seo_package
    source=prepare_source_packet(video_id=VID,cards=cards())
    broken=good_package()
    broken["title_variants"]=["Дубль","Дубль","Дубль"]
    prior=draft_seo_package(source=source,chat=lambda _:json.dumps(broken,ensure_ascii=False))
    critique=evaluate_independent_draft(draft=prior,source=source,
        chat=lambda _:json.dumps({"risk":"high","issues":["Unsupported"]}))
    critique["source_packet_sha256"]="forged"
    with pytest.raises(ValueError,match="SOURCE_CRITIQUE_MISMATCH"):
        repair_seo_package(source=source,previous=prior,critique=critique,chat=lambda _: "{}")


def test_complete_missing_third_ab_only_from_source():
    from rg_youtube_control.seo_g3_batch_drafts import complete_missing_source_variants
    source=prepare_source_packet(video_id=VID,cards=cards())
    source["records"][0]["topic_candidate_not_fact"]="Розмова про суспільство та громадянську позицію"
    pkg=good_package()
    pkg["title_variants"]=pkg["title_variants"][:2]
    broken=draft_seo_package(source=source,chat=lambda _:json.dumps(pkg,ensure_ascii=False))
    assert broken["blockers"]==["title_variants"]
    repaired=complete_missing_source_variants(source=source,draft=broken)
    assert len(repaired["seo"]["title_variants"])==3
    assert repaired["seo"]["title_variants"][-1] == source["records"][0]["topic_candidate_not_fact"]
    assert repaired["seo"]["description"] == pkg["description"]
    assert repaired["independent_recheck_required"] is True
    assert not repaired["publication_allowed"] and not repaired["human_approved"]


def test_no_ungrounded_source_ab_fallback():
    from rg_youtube_control.seo_g3_batch_drafts import complete_missing_source_variants
    source=prepare_source_packet(video_id=VID,cards=cards())
    source["records"][0]["topic_candidate_not_fact"] = "Я это русский заголовок"
    pkg=good_package();pkg["title_variants"]=pkg["title_variants"][:2]
    draft=draft_seo_package(source=source,chat=lambda _:json.dumps(pkg,ensure_ascii=False))
    with pytest.raises(ValueError,match="NO_GROUNDED_THIRD_AB_TITLE"):
        complete_missing_source_variants(source=source,draft=draft)


def test_source_variant_repair_never_rewrites_other_bad_fields():
    from rg_youtube_control.seo_g3_batch_drafts import complete_missing_source_variants
    source=prepare_source_packet(video_id=VID,cards=cards())
    pkg=good_package();pkg["title_variants"]=pkg["title_variants"][:2];pkg["description"]="Коротко"
    draft=draft_seo_package(source=source,chat=lambda _:json.dumps(pkg,ensure_ascii=False))
    with pytest.raises(ValueError,match="NOT_SOLELY_MISSING_ONE_TITLE_VARIANT"):
        complete_missing_source_variants(source=source,draft=draft)
