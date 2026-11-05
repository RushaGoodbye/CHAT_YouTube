import json
from rg_youtube_control.seo_grounded_claims import (
 _distinct_references,_validate_claim,generate_attributed_claim_description
)

EVIDENCE={"blocks":[
 {"verified":True,"start_stamp":"00:00:01","topics":[
  {"evidence":"Цены на бензин на заправке выросли, люди обсуждают стоимость топлива"}]},
 {"verified":True,"start_stamp":"00:02:00","topics":[
  {"evidence":"Пенсии в нашем регионе маленькие, пенсионеры на это постоянно жалуются"}]},
 {"verified":True,"start_stamp":"00:06:00","topics":[
  {"evidence":"Зарплаты на предприятии задерживают, поэтому многие люди недовольны"}]}
]}

def test_real_quote_ids_are_distinct():
 refs=_distinct_references(EVIDENCE)
 assert [r["id"] for r in refs]==["q1","q2","q3"]

def test_rejects_unattributed_claim():
 issue=_validate_claim({"text":"Ціни на бензин на заправці різко зросли в регіоні."},
 {"quote":"Цены на бензин на заправке выросли, люди обсуждают стоимость топлива"})
 assert issue=="CLAIM_NOT_ATTRIBUTED"

def test_rejects_new_number():
 issue=_validate_claim({"text":"Співрозмовник говорить, що ціни на бензин зросли на 47 відсотків."},
 {"quote":"Цены на бензин на заправке выросли, люди обсуждают стоимость топлива"})
 assert issue=="UNSUPPORTED_CLAIM_NUMBER"

def test_rejects_russian_and_raw_quote():
 source={"quote":"Цены на бензин на заправке выросли, люди обсуждают стоимость топлива"}
 assert _validate_claim({"text":"Співрозмовник говорит что бензин сильно подорожал из-за кризиса."},source)=="MIXED_RUSSIAN"
 assert _validate_claim({"text":"Співрозмовник каже: «Цены на бензин на заправке выросли, люди обсуждают стоимость топлива»."},source)=="COPY_PASTED_QUOTE"

def test_fails_entire_package_without_valid_quote_ids():
 def fake(*args,**kw):
  return json.dumps({"claims":[
   {"quote_id":"q1","text":"Співрозмовник говорить про ціни на бензин на заправці."},
   {"quote_id":"q1","text":"Учасник розмови обговорює пенсії в регіоні."},
   {"quote_id":"q3","text":"Ведучий говорить про зарплати на підприємстві."}]},ensure_ascii=False)
 output,reason,proof=generate_attributed_claim_description(
  report=EVIDENCE,current_title="Тема",model="dummy",chat=fake)
 assert not output and reason=="MISSING_OR_DUPLICATED_QUOTE_ID"
 assert proof["publication_allowed"] is False

def test_no_fake_completion_when_source_is_too_short():
 output,reason,_=generate_attributed_claim_description(report={"blocks":[EVIDENCE["blocks"][0]]},
  current_title="Тема",model="dummy",chat=lambda *a,**k:None)
 assert not output and reason=="INSUFFICIENT_DISTINCT_SOURCE_QUOTES"