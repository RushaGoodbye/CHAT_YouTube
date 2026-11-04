from rg_youtube_control.seo_spoken_numbers import grounded_number_values

def test_russian_fuel_grades_written_as_spoken_ordinals():
    source = "сотый, девяносто пятый, девяносто второй"
    grounded = grounded_number_values(source)
    assert {"100", "95", "92"}.issubset(grounded)
    assert "90" not in grounded
    assert "999" not in grounded

def test_ukrainian_compound_cardinal_and_ordinals():
    source = "дев'яносто п'ятий, дев'яносто другий, сороковий"
    grounded = grounded_number_values(source)
    assert {"95", "92", "40"}.issubset(grounded)

def test_original_printed_numbers_and_no_invention():
    grounded = grounded_number_values("Номер 2060 і десять")
    assert {"2060","10"}.issubset(grounded)
    assert "2000" not in grounded

def test_generic_fuel_grade_revision_accepts_only_spoken_numbers():
    import json
    from rg_youtube_control.seo_editorial_revision import propose_editorial_revision
    quote = "сотый, девяносто пятый, девяносто второй"
    card = {"verbatim_quote":quote,"source_context":"В Краснодаре нет проблем с бензином, "+quote,
            "proposed_topic":"Види бензину","proposed_summary":"Співрозмовник перелічує бензин.",
            "critic_issues_unverified":[]}
    def chat(messages,**kwargs):
        return json.dumps({"topic":"Марки бензину 100, 95 і 92",
            "summary_uk":"Співрозмовник називає марки бензину 100, 95 та 92, розповідаючи про ситуацію з пальним."})
    outcome = propose_editorial_revision(card=card,chat=chat,model="local")
    assert outcome["status"] == "REVIEW_REQUIRED"
    assert outcome["editorial_approved"] is False

def test_unspoken_number_still_blocked():
    from rg_youtube_control.seo_editorial_revision import propose_editorial_revision
    import json
    quote="сотый, девяносто пятый, девяносто второй"
    card={"verbatim_quote":quote,"source_context":quote,
          "proposed_topic":"Марки","proposed_summary":"Обговорення бензину."}
    outcome=propose_editorial_revision(card=card,chat=lambda *a,**kw:json.dumps({
        "topic":"Марки бензину 999", "summary_uk":"Співрозмовник називає марку бензину 999."}),model="local")
    assert outcome["status"] == "BLOCKED_UNSUPPORTED_NUMBER"


def test_standalone_tens_still_supported():
    values = grounded_number_values("Девяносто. А потом девяносто пятый.")
    assert "90" in values and "95" in values


def test_compound_number_does_not_license_partial_grade_in_editorial_summary():
    import json
    from rg_youtube_control.seo_editorial_revision import propose_editorial_revision
    quote = "сотый, девяносто пятый, девяносто второй"
    card={"verbatim_quote":quote,"source_context":"В Краснодаре "+quote,
          "proposed_topic":"Марки бензину","proposed_summary":"Обговорення пального."}
    def chat(*args, **kwargs):
        return json.dumps({"topic":"Бензин марок 90, 95 та 92",
            "summary_uk":"Співрозмовник називає бензин 90, 95 і 92 марок."})
    result=propose_editorial_revision(card=card,chat=chat,model="local")
    assert result["status"]=="BLOCKED_UNSUPPORTED_NUMBER"
    assert "90" in result["unsupported_numbers"]
