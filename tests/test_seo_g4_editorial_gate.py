"""Regression checks from real G4 SEO batch: source fidelity and language."""
import json
from pathlib import Path
from rg_youtube_control.seo_editorial_gate import editorial_risk_flags


def test_mixed_language_title_is_flagged_even_without_russian_letters():
    package={"title":"Увольнення Шойгу: корупція чи плановий розворот?","title_variants":[],"description":""}
    assert "MIXED_LANGUAGE:title" in editorial_risk_flags(package, "причина звільнення Шойгу")


def test_house_apartment_substitution_is_flagged():
    package={"title":"Жителька Донбасу", "title_variants":["Донеччанка купила квартиру за гривні"],"description":"Купила квартиру за гривні"}
    transcript="Это были гривны. То есть получается, ты за гривны украинские купила дом в Украине."
    flags=editorial_risk_flags(package,transcript)
    assert "UNSUPPORTED_APARTMENT:VERIFY_SOURCE" in flags


def test_apartment_not_flagged_if_source_contains_apartment():
    p={"title":"Вона купила квартиру","title_variants":[],"description":""}
    assert not any(x.startswith("UNSUPPORTED_APARTMENT") for x in editorial_risk_flags(p,"Я купила квартиру в місті."))


def test_repeated_angle_flagged_without_claiming_automatic_approval():
    package={"title":"Дискусія","title_variants":[
        "Путін для росіянина: цар і батько?",
        "Путін для росіянина: цар та батько",
        "Як росіяни ставляться до війни?",
    ],"description":""}
    assert "REPEATED_AB_ANGLE:1:2" in editorial_risk_flags(package, "обговорюють Путіна і війну")


def test_ukrainian_sanctions_word_not_false_positive():
    p={"title":"Санкції проти Росії: що думають росіяни?","title_variants":[],"description":"Чат-рулетка про санкції."}
    assert not any(x.startswith("MIXED_LANGUAGE") for x in editorial_risk_flags(p, "санкції"))


def test_existing_real_batch_flags_read_only():
    folder=Path(r"C:\RG_YT_AGENT_RUNNER\SEO_G1_CHECK\g2_cohort_20261104")
    candidates=folder/"g4_installed_generator_real_srt_QA_20261105"
    if not candidates.exists():
        return
    from rg_youtube_control.free_tools import load_srt_transcript, transcript_sample_text
    for vid in ("MEitKm687xo","9T9uL6huCZw","9WOFamNB90k","gJlsdbxzi2k","NAXPGr6hY_g"):
        p=candidates/(vid+".json")
        if not p.is_file():
            continue
        data=json.loads(p.read_text(encoding="utf-8"))
        source=transcript_sample_text(load_srt_transcript(folder/"source_captions"/(vid+".srt")),max_chars=12000,segments=6)
        flags=editorial_risk_flags(data["model_output"],source)
        if vid=="MEitKm687xo":
            assert "MIXED_LANGUAGE:title" in flags
        if vid=="9WOFamNB90k":
            assert "PROPERTY_TYPE_AMBIGUITY:VERIFY_CONTEXT" in flags


def test_two_property_types_are_ambiguity_not_hallucination():
    p={"title":"Розмова про будинок","title_variants":["Купила квартиру за гривні"],"description":""}
    src="Питання про купівлю: вона купила квартиру. А далі питають: за гривні українські купила дом?"
    flags=editorial_risk_flags(p,src)
    assert "PROPERTY_TYPE_AMBIGUITY:VERIFY_CONTEXT" in flags
    assert not any(x.startswith("UNSUPPORTED_APARTMENT:") for x in flags)


def test_real_mixed_ukrainian_russian_word_is_blocked_by_format_gate():
    from rg_youtube_control.seo_quality_gate import inspect_package
    source = {"title": "Увольнення Шойгу: корупція чи план?",
              "title_variants": ["Звільнення Шойгу","Причини змін у владі","Питання співрозмовників"],
              "description": "У розмові обговорюють звільнення Шойгу та можливі причини кадрових рішень. "*5,
              "tags": ["Шойгу","Раша Гудбай","чат рулетка","кадрові зміни","Росія","дискусія","політика","корупція"]}
    report = inspect_package(source)
    assert report["format_pass"] is False
    assert "NON_UKRAINIAN" in report["problems"]["title"]