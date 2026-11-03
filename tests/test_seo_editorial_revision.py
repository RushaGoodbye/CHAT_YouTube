import json
from rg_youtube_control.seo_editorial_revision import propose_editorial_revision

def card():
    return {"verbatim_quote":"В городе закрыли несколько магазинов одежды.",
            "source_context":"В городе закрыли несколько магазинов одежды. Некоторые кафе открылись.",
            "proposed_topic":"Всі бізнеси закрилися",
            "proposed_summary":"Всі підприємства закрилися через кризу.",
            "critic_issues_unverified":["Overgeneralized closures"]}

def test_good_review_only():
    result=propose_editorial_revision(card=card(),model="local",chat=lambda *a,**k:
        json.dumps({"topic":"Закриття деяких магазинів",
        "summary_uk":"Співрозмовник говорить, що частина магазинів одягу закрилася, але деякі кафе відкрилися."}))
    assert result["status"]=="REVIEW_REQUIRED"
    assert result["proposal"]["topic"]=="Закриття деяких магазинів"
    assert result["verbatim_quote_unchanged"]==card()["verbatim_quote"]
    assert result["editorial_approved"] is False

def test_unverified_number_rejected():
    result=propose_editorial_revision(card=card(),model="local",chat=lambda *a,**k:
        json.dumps({"topic":"Закриття 999 магазинів",
        "summary_uk":"У місті начебто закрили 999 магазинів."}))
    assert result["status"]=="BLOCKED_UNSUPPORTED_NUMBER"

def test_missing_quote_in_context_blocks():
    d=card()
    d["source_context"]="A different dialogue unrelated to the quotation"
    result=propose_editorial_revision(card=d,model="local",chat=lambda *a,**k:1/0)
    assert result["status"]=="BLOCKED_SOURCE_CONTEXT"

def test_bad_model_response_remains_blocked():
    result=propose_editorial_revision(card=card(),model="local",chat=lambda *a,**k:"not json")
    assert result["status"]=="BLOCKED_REPAIR_FAILURE"

def test_critic_objections_never_override_source():
    def model(messages,**kwargs):
        req=json.loads(messages[-1]["content"])
        assert "Overgeneralized closures" in req["unverified_critic_objections"]
        assert "Некоторые кафе открылись" in req["surrounding_transcript"]
        return json.dumps({"topic":"Розмова про магазини",
                           "summary_uk":"Учасник розповідає про закриті магазини одягу і відкриті кафе."})
    result=propose_editorial_revision(card=card(),model="local",chat=model)
    assert result["status"]=="REVIEW_REQUIRED"
    assert result["publication_allowed"] is False
