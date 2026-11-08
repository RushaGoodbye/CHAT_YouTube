from rg_youtube_control.seo_g2_numeric_risk import screen_numeric_claims

def packet(source,summary,topic="Паливо"):
    return {"video_id":"AbCdEfGh123","records":[
        {"id":1,"source_context":source,"source_quote":source,
         "proposed_topic":topic,"proposed_summary":summary}]}

def test_spoken_ninety_fifth_supports_digit_95():
    result=screen_numeric_claims(packet("девяносто пятый сорт бензина",
                                     "Учасник згадує бензин марки 95."))
    assert result["flagged"]==0
    assert result["publication_allowed"] is False

def test_compound_number_does_not_support_90_alone():
    result=screen_numeric_claims(packet("девяносто пятый",
                                     "В ефірі згадали бензин марки 90."))
    assert result["flagged"]==1
    assert result["findings"][0]["numbers_not_in_local_source"]==["90"]

def test_unspoken_number_is_flagged():
    result=screen_numeric_claims(packet("В місті обговорюють бензин",
                                     "Співрозмовник повідомляє про 999 автомобілів."))
    assert result["flagged"]==1
    assert result["findings"][0]["risk_type"]=="UNSUPPORTED_NUMERIC_DETAIL_NEEDS_REVIEW"
    assert result["publication_allowed"] is False

def test_source_grounded_is_not_claim_of_truth():
    result=screen_numeric_claims(packet("Він каже, що втрати 2000",
                                     "Учасник стверджує, що втрати 2000."))
    assert result["flagged"]==0
    assert result["publication_allowed"] is False
