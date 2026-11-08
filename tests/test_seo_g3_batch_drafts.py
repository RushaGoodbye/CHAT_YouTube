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



def test_low_risk_with_substantive_issues_is_not_screened():
    p=prepare_source_packet(video_id=VID,cards=cards())
    draft=draft_seo_package(source=p,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    checked=evaluate_independent_draft(draft=draft,source=p,chat=lambda _:json.dumps({"risk":"low","issues":["Unsupported statement"]}))
    assert checked["status"]=="NEEDS_ATTENTION"
    assert not checked["publication_allowed"]

def test_provisional_source_low_risk_requires_attention():
    p=prepare_source_packet(video_id=VID,cards=cards(provisional=True))
    draft=draft_seo_package(source=p,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    checked=evaluate_independent_draft(draft=draft,source=p,chat=lambda _:json.dumps({"risk":"low","issues":[]}))
    assert checked["status"]=="NEEDS_ATTENTION"

def test_empty_model_reply_retries_once_then_checks():
    p=prepare_source_packet(video_id=VID,cards=cards())
    calls=[]
    def chat(messages):
        calls.append(messages)
        return "" if len(calls)==1 else json.dumps(good_package(),ensure_ascii=False)
    draft=draft_seo_package(source=p,chat=chat)
    assert len(calls)==2 and len(calls[1])==3
    assert not draft["publication_allowed"]

def test_double_empty_model_reply_fails_closed():
    p=prepare_source_packet(video_id=VID,cards=cards())
    calls=[]
    def chat(messages):
        calls.append(1)
        return ""
    with pytest.raises(ValueError,match="MODEL_DID_NOT_RETURN_JSON"):
        draft_seo_package(source=p,chat=chat)
    assert len(calls)==2

def test_low_risk_with_issues_allows_bounded_repair():
    from rg_youtube_control.seo_g3_batch_drafts import repair_seo_package
    p=prepare_source_packet(video_id=VID,cards=cards())
    draft=draft_seo_package(source=p,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    review=evaluate_independent_draft(draft=draft,source=p,chat=lambda _:json.dumps({"risk":"low","issues":["Unsupported detail"]}))
    repaired=repair_seo_package(source=p,previous=draft,critique=review,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    assert repaired["repair_attempt"]==1 and repaired["independent_recheck_required"]
    assert not repaired["publication_allowed"]

def test_low_risk_no_issues_does_not_rewrite():
    from rg_youtube_control.seo_g3_batch_drafts import repair_seo_package
    p=prepare_source_packet(video_id=VID,cards=cards())
    draft=draft_seo_package(source=p,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    review=evaluate_independent_draft(draft=draft,source=p,chat=lambda _:json.dumps({"risk":"low","issues":[]}))
    with pytest.raises(ValueError,match="ALREADY_AI_SCREENED_DO_NOT_REWRITE"):
        repair_seo_package(source=p,previous=draft,critique=review,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))

def test_independent_critic_bounded_quote_centered_context():
    p=prepare_source_packet(video_id=VID,cards=cards())
    original=p["records"][0]["source_context"]
    p["records"][0]["source_context"]="x"*5000+original+"y"*5000
    draft=draft_seo_package(source=p,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    observed=[]
    def critic(messages):
        observed.append(json.loads(messages[-1]["content"])["source"][0])
        return json.dumps({"risk":"low","issues":[]})
    evaluate_independent_draft(draft=draft,source=p,chat=critic)
    assert p["records"][0]["literal_quote"] in observed[0]["source_context"]
    assert len(observed[0]["source_context"])<=len(p["records"][0]["literal_quote"])+640

def test_independent_critic_rejects_missing_quote():
    p=prepare_source_packet(video_id=VID,cards=cards())
    draft=draft_seo_package(source=p,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    p["records"][0]["literal_quote"]="Fake quote absent from original context"
    with pytest.raises(ValueError,match="CRITIC_SOURCE_QUOTE_MISMATCH"):
        evaluate_independent_draft(draft=draft,source=p,chat=lambda _:json.dumps({"risk":"low","issues":[]}))



def _original_rows_for_g3():
    first = "Люди обговорюють ставлення до Росії і своє суспільство."
    second = "Співрозмовники говорять про ціни на транспорт і проїзд."
    third = "Учасник розповідає про свій досвід роботи у великому місті."
    return [{"text": first, "start": 0.0, "duration": 4.0},
            {"text": second, "start": 4.0, "duration": 4.0},
            {"text": third, "start": 8.0, "duration": 4.0}]


def _expanded_source_for_g3():
    from rg_youtube_control.seo_evidence_records import build_evidence_records
    first = "Люди обговорюють ставлення до Росії і своє суспільство."
    second = "Співрозмовники говорять про ціни на транспорт і проїзд."
    third = "Учасник розповідає про свій досвід роботи у великому місті."
    block = {"index": 1, "start": 0.0, "end": 15.0, "verified": True,
             "topics": [{"topic": "Ставлення до суспільства",
                         "summary_uk": "Люди говорять про особисті оцінки ситуації.",
                         "evidence": first}]}
    rows = _original_rows_for_g3()
    return build_evidence_records(
        video_id=VID, timeline_report={"blocks": [block], "blocks_analyzed": 1,
                    "blocks_with_evidence": 1}, transcript_rows=rows)


def test_g3_can_supplement_source_cards_with_literal_srt_cues():
    evidence = _expanded_source_for_g3()
    source = prepare_source_packet(video_id=VID, cards=cards(), expanded_evidence=evidence, transcript_rows=_original_rows_for_g3())
    assert len(source["records"]) == 4
    assert source["contains_provisional_sources"]
    assert not source["publication_allowed"] and not source["editorial_approved"]
    quoted = [item["literal_quote"] for item in source["records"]]
    assert len(quoted) == len(set(quoted))
    assert all(item["quote_sha256"] for item in source["records"])
    draft = draft_seo_package(source=source, chat=lambda _m: json.dumps(good_package(), ensure_ascii=False))
    assert "PROVISIONAL_SOURCE_REVIEW" in draft["blockers"]
    reviewed = evaluate_independent_draft(
        draft=draft, source=source,
        chat=lambda _m: json.dumps({"risk": "low", "issues": []}))
    assert reviewed["status"] == "NEEDS_ATTENTION"
    assert not reviewed["publication_allowed"]


def test_g3_rejects_unverified_expanded_source():
    evidence = _expanded_source_for_g3()
    evidence["complete_evidence_coverage"] = False
    evidence["complete_literal_source_coverage"] = False
    with pytest.raises(ValueError, match="UNTRUSTED_EXPANDED_SOURCE_EVIDENCE"):
        prepare_source_packet(video_id=VID, cards=cards(), expanded_evidence=evidence, transcript_rows=_original_rows_for_g3())


def test_g3_never_exceeds_source_card_limit_with_cue_candidates():
    evidence = _expanded_source_for_g3()
    packet = prepare_source_packet(video_id=VID, cards=cards(),
                                   max_cards=2, expanded_evidence=evidence, transcript_rows=_original_rows_for_g3())
    assert len(packet["records"]) == 2
    assert packet["contains_provisional_sources"]
    assert not packet["publication_allowed"]


def test_provisional_g3_cue_context_preserves_quote_and_no_speaker_claim():
    source = prepare_source_packet(
        video_id=VID, cards=cards(), expanded_evidence=_expanded_source_for_g3(), transcript_rows=_original_rows_for_g3())
    extras = [r for r in source["records"] if r.get("context_is_not_speaker_proof")]
    assert extras
    assert all(r["literal_quote"] in r["source_context"] for r in extras)
    assert all(r["provisional"] for r in extras)
    assert any(len(r["source_context"]) > len(r["literal_quote"]) for r in extras)
    assert not source["publication_allowed"]


def test_g3_rejects_invented_original_cue_even_with_fake_verification_flags():
    evidence = _expanded_source_for_g3()
    evidence["source_cue_candidates"][0]["source_quote"] = (
        "Вигадана репліка про подію, якої не було в субтитрах.")
    with pytest.raises(ValueError, match="EXPANDED_CUE_NOT_IN_ORIGINAL_SRT"):
        prepare_source_packet(video_id=VID, cards=cards(), expanded_evidence=evidence,
                              transcript_rows=_original_rows_for_g3())


def test_g3_rejects_shifted_timestamp_for_valid_quote():
    evidence = _expanded_source_for_g3()
    evidence["source_cue_candidates"][0]["start_s"] += 0.5
    with pytest.raises(ValueError, match="EXPANDED_CUE_NOT_IN_ORIGINAL_SRT"):
        prepare_source_packet(video_id=VID, cards=cards(), expanded_evidence=evidence,
                              transcript_rows=_original_rows_for_g3())


def test_g3_requires_original_caption_rows_not_self_reported_model_claims():
    evidence = _expanded_source_for_g3()
    with pytest.raises(ValueError, match="ORIGINAL_SRT_REQUIRED_FOR_EXPANDED_EVIDENCE"):
        prepare_source_packet(video_id=VID, cards=cards(), expanded_evidence=evidence)


def test_g3_prompt_keeps_source_fragment_and_unknown_speaker_warnings():
    evidence = _expanded_source_for_g3()
    source = prepare_source_packet(
        video_id=VID, cards=cards(), expanded_evidence=evidence,
        transcript_rows=_original_rows_for_g3())
    prompts = []
    def writer(messages):
        prompts.append(json.loads(messages[-1]["content"]))
        return json.dumps(good_package(), ensure_ascii=False)
    draft_seo_package(source=source, chat=writer)
    assert any(r["speaker_unknown"] for r in prompts[0]["source"]["records"])
    assert all("may_be_incomplete" in r for r in prompts[0]["source"]["records"])
    assert "Never infer speaker identity" in " ".join(prompts[0]["instructions"])


def test_g3_rejects_incomplete_timeline_even_when_topic_coverage_claims_complete():
    evidence = _expanded_source_for_g3()
    assert evidence["complete_evidence_coverage"]
    evidence["source_cue_complete_timeline_verified"] = False
    evidence["complete_literal_source_coverage"] = False
    with pytest.raises(ValueError, match="UNTRUSTED_EXPANDED_SOURCE_EVIDENCE"):
        prepare_source_packet(video_id=VID, cards=cards(), expanded_evidence=evidence,
                              transcript_rows=_original_rows_for_g3())


def test_g3_rejects_invalid_block_count_even_when_all_topics_have_quotes():
    evidence = _expanded_source_for_g3()
    evidence["source_cue_invalid_block_count"] = 1
    with pytest.raises(ValueError, match="UNTRUSTED_EXPANDED_SOURCE_EVIDENCE"):
        prepare_source_packet(video_id=VID, cards=cards(), expanded_evidence=evidence,
                              transcript_rows=_original_rows_for_g3())


def test_literal_only_source_packet_is_permitted_as_provisional_not_approved():
    proof = _expanded_source_for_g3()
    proof["complete_evidence_coverage"] = False
    proof["source_cue_complete_timeline_verified"] = False
    proof["source_cue_candidates"][1]["model_block_verified"] = False
    packet = prepare_source_packet(video_id=VID, cards=cards(),
                                   expanded_evidence=proof,
                                   transcript_rows=_original_rows_for_g3())
    assert packet["expanded_literal_only"] is True
    assert packet["contains_provisional_sources"] is True
    assert packet["source_material_requires_editorial_review"] is True
    assert not packet["editorial_approved"] and not packet["publication_allowed"]
    assert any(r.get("model_block_verified") is False for r in packet["records"])
    draft = draft_seo_package(
        source=packet, chat=lambda _m: json.dumps(good_package(), ensure_ascii=False))
    assert "PROVISIONAL_SOURCE_REVIEW" in draft["blockers"]
    critique = evaluate_independent_draft(
        draft=draft, source=packet,
        chat=lambda _m: json.dumps({"risk": "low", "issues": []}))
    assert critique["status"] == "NEEDS_ATTENTION"
    assert not critique["human_approved"] and not critique["publication_allowed"]


def test_literal_only_proof_without_grounded_original_srt_is_rejected():
    proof = _expanded_source_for_g3()
    proof["complete_evidence_coverage"] = False
    proof["source_cue_candidates"][0]["source_quote"] = (
        "Подія з неіснуючого фрагмента, якої ніхто не вимовляв.")
    with pytest.raises(ValueError, match="EXPANDED_CUE_NOT_IN_ORIGINAL_SRT"):
        prepare_source_packet(video_id=VID, cards=cards(),
                              expanded_evidence=proof,
                              transcript_rows=_original_rows_for_g3())


def test_g3_card_limit_keeps_beginning_and_end_of_long_real_source():
    captions = [
        {"start": float(i * 60), "duration": 4.0,
         "text": f"Співрозмовники обговорили питання номер {i} та умови роботи в місті."}
        for i in range(15)
    ]
    cues = [
        {"start_s": row["start"], "source_quote": row["text"],
         "source_precision": "single_original_cue",
         "factual_truth_verified": False,
         "context_window": row["text"], "model_block_verified": True}
        for row in captions
    ]
    proof = {
        "video_id": VID,
        "source_cue_selection_schema": "RG_SOURCE_CUE_EXPANSION_V1",
        "source_cue_candidates_review_only": True,
        "complete_literal_source_coverage": True,
        "complete_evidence_coverage": True,
        "source_cue_invalid_block_count": 0,
        "source_cue_candidates": cues,
    }
    packet = prepare_source_packet(
        video_id=VID, cards=cards(), max_cards=5,
        expanded_evidence=proof, transcript_rows=captions,
    )
    used = [r["literal_quote"] for r in packet["records"]]
    assert len(used) == 5
    assert captions[0]["text"] in used
    assert captions[-1]["text"] in used
    assert packet["contains_provisional_sources"] is True
    assert packet["publication_allowed"] is False


def test_independent_critic_single_string_issue_is_a_real_veto():
    source = prepare_source_packet(video_id=VID, cards=cards())
    draft = draft_seo_package(
        source=source, chat=lambda _m: json.dumps(good_package(), ensure_ascii=False))
    checked = evaluate_independent_draft(
        draft=draft, source=source,
        chat=lambda _m: json.dumps({"risk": "low", "issues":
                                    "Додані імена, яких немає в оригіналі"},
                                   ensure_ascii=False))
    assert checked["issues"] == ["Додані імена, яких немає в оригіналі"]
    assert checked["status"] == "NEEDS_ATTENTION"
    assert not checked["publication_allowed"]


def test_independent_critic_empty_string_issues_do_not_approve_provisional_source():
    source = prepare_source_packet(video_id=VID, cards=cards(provisional=True))
    draft = draft_seo_package(
        source=source, chat=lambda _m: json.dumps(good_package(), ensure_ascii=False))
    checked = evaluate_independent_draft(
        draft=draft, source=source,
        chat=lambda _m: json.dumps({"risk": "low", "issues": ""}))
    assert checked["issues"] == []
    assert checked["status"] == "NEEDS_ATTENTION"
    assert not checked["human_approved"] and not checked["publication_allowed"]


def test_writer_prompt_enforces_three_distinct_ab_and_source_attribution():
    packet=prepare_source_packet(video_id=VID,cards=cards())
    observed=[]
    def writer(messages):
        observed.append(json.loads(messages[-1]["content"]))
        return json.dumps(good_package(),ensure_ascii=False)
    draft=draft_seo_package(source=packet,chat=writer)
    instructions=" ".join(observed[0]["instructions"])
    assert "EXACTLY THREE" in instructions
    assert "official policy" in instructions
    assert "reported statement" in instructions
    assert "early and late captions" in instructions
    assert draft["publication_allowed"] is False


def test_independent_critic_is_prompted_to_check_all_three_ab():
    packet=prepare_source_packet(video_id=VID,cards=cards())
    draft=draft_seo_package(source=packet,chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    seen=[]
    def critic(messages):
        seen.append(json.loads(messages[-1]["content"]))
        return json.dumps({"risk":"medium","issues":["Claim is a reported allegation, not verified state policy"]})
    review=evaluate_independent_draft(draft=draft,source=packet,chat=critic)
    rules=" ".join(seen[0]["rules"])
    assert "ALL THREE A/B titles" in rules
    assert "question-to-assertion swaps" in rules
    assert "other sources" in rules
    assert "Claim is a reported allegation" in review["issues"][0]
    assert not review["publication_allowed"]


def test_missing_ab_cannot_be_recovered_from_provisional_asr_topic():
    from rg_youtube_control.seo_g3_batch_drafts import complete_missing_source_variants
    source=prepare_source_packet(video_id=VID,cards=cards(provisional=True))
    pkg=good_package()
    pkg["title_variants"]=pkg["title_variants"][:2]
    draft=draft_seo_package(source=source,
        chat=lambda _:json.dumps(pkg,ensure_ascii=False))
    with pytest.raises(ValueError, match="NO_GROUNDED_THIRD_AB_TITLE"):
        complete_missing_source_variants(source=source,draft=draft)
    assert draft["publication_allowed"] is False


def test_missing_ab_does_not_use_fragment_topic_even_if_not_provisional():
    from rg_youtube_control.seo_g3_batch_drafts import complete_missing_source_variants
    source=prepare_source_packet(video_id=VID,cards=cards())
    source["records"][0]["incomplete_source_fragment"]=True
    pkg=good_package()
    pkg["title_variants"]=pkg["title_variants"][:2]
    draft=draft_seo_package(source=source,
        chat=lambda _:json.dumps(pkg,ensure_ascii=False))
    with pytest.raises(ValueError, match="NO_GROUNDED_THIRD_AB_TITLE"):
        complete_missing_source_variants(source=source,draft=draft)


def test_repair_prompt_keeps_reported_speech_and_does_not_invent_policy():
    from rg_youtube_control.seo_g3_batch_drafts import repair_seo_package
    source=prepare_source_packet(video_id=VID,cards=cards())
    broken=good_package()
    broken["title_variants"]=broken["title_variants"][:2]
    previous=draft_seo_package(source=source,
        chat=lambda _:json.dumps(broken,ensure_ascii=False))
    critique=evaluate_independent_draft(
        draft=previous, source=source,
        chat=lambda _:json.dumps({"risk":"high","issues":[
            "Allegation misrepresented as official policy",
            "Reported speech translated as a confirmed refusal",
        ]}))
    seen=[]
    def rewrite(messages):
        prompt=json.loads(messages[-1]["content"])
        seen.append(prompt)
        return json.dumps(good_package(),ensure_ascii=False)
    repaired=repair_seo_package(source=source,previous=previous,
        critique=critique,chat=rewrite)
    instructions=" ".join(seen[0]["rules"])
    assert "reporting somebody else's claim" in instructions
    assert "source speech-act" in instructions
    assert "Russian 'кидает'" in instructions
    assert "future action happened" in instructions
    assert "3 distinct Ukrainian A/B" in instructions
    assert len(repaired["seo"]["title_variants"])==3
    assert repaired["independent_recheck_required"] is True
    assert repaired["publication_allowed"] is False


def test_critic_compliments_are_not_mistaken_for_issues_or_success():
    source=prepare_source_packet(video_id=VID,cards=cards())
    draft=draft_seo_package(source=source,
        chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    critic=lambda _:json.dumps({"risk":"low","issues":[
        "Title variants are factually consistent with the source transcript.",
        "Description accurately reflects the dialogue.",
        "No unsupported dates were introduced.",
        "Tags align with the core topics discussed."
    ]})
    result=evaluate_independent_draft(draft=draft,source=source,chat=critic)
    assert result["risk_ai"]=="medium"
    assert result["issues"]==["INVALID_CRITIC_SCHEMA_POSITIVE_NOTES_IN_ISSUES"]
    assert result["publication_allowed"] is False


def test_description_outside_300_to_650_is_blocked_even_if_generic_gate_allows():
    p=prepare_source_packet(video_id=VID,cards=cards())
    too_long=good_package()
    too_long["description"]=(good_package()["description"]+" ")*3
    draft=draft_seo_package(source=p,
        chat=lambda _:json.dumps(too_long,ensure_ascii=False))
    assert "DESCRIPTION_TARGET_300_650" in draft["blockers"]
    assert draft["publication_allowed"] is False
    proper=draft_seo_package(source=p,
        chat=lambda _:json.dumps(good_package(),ensure_ascii=False))
    assert "DESCRIPTION_TARGET_300_650" not in proper["blockers"]
