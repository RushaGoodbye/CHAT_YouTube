import json
from rg_youtube_control.seo_content_editor import grounded_description_issue, recover_source_description

REPORT={"blocks":[
 {"verified":True,"start_stamp":"00:00:12","topics":[{"topic":"ціни на бензин","evidence":"Цены на бензин подорожали, люди на заправках об этом говорят"}]},
 {"verified":True,"start_stamp":"00:05:15","topics":[{"topic":"пенсії та виплати","evidence":"Люди обсуждают пенсии и социальные выплаты в регионе"}]},
]}

def test_generic_description_blocked():
 d=("У цьому випуску «РАША ГУДБАЙ» ведучий та співрозмовники обговорюють такі теми: "
     "ціни на бензин; пенсії. Учасники чат-рулетки висловлюють власні думки та припущення "
     "щодо причин подій. Дивіться повну розмову, щоб почути аргументи співрозмовників "
     "і оцінити їх у контексті.")
 assert grounded_description_issue(d,REPORT)=="GENERIC_TEMPLATE_DESCRIPTION"

def test_unsupported_number_is_blocked():
 d=("Співрозмовник говорить про ціни на бензин і пояснює, чому, на його думку, "
     "подорожчали товари на заправках. У розмові згадують пенсії та соціальні "
     "виплати, які, за словами учасників, стали темою суперечки. "
     "Ведучий уточнює позицію гостя, а той вважає, що зміни зачіпають людей "
     "у регіоні. Під час обговорення згадується підвищення на 47 відсотків.")
 assert grounded_description_issue(d,REPORT)=="UNSUPPORTED_NUMERIC_CLAIM"

def test_source_grounded_repair_accepts_specific_ukrainian_prose():
 d=("Співрозмовник говорить про ціни на бензин і пояснює, чому, на його думку, "
     "подорожчали товари на заправках. У розмові згадують пенсії та соціальні "
     "виплати, які, за словами учасників, стали темою суперечки. "
     "Ведучий уточнює позицію гостя, а той вважає, що зміни зачіпають людей "
     "у регіоні. Дискусія зосереджена на тому, як громадяни оцінюють власні "
     "витрати та забезпечення.")
 assert grounded_description_issue(d,REPORT)==""

def test_unsupported_name_from_model_is_rejected():
 d=("Співрозмовник говорить про ціни на бензин і пояснює позицію щодо "
    "подорожчання пального на заправках. У розмові згадують пенсії та "
    "соціальні виплати, які, за словами учасників, стали предметом суперечки. "
    "Ведучий запитує про політику Зеленського, а співрозмовник вважає, "
    "що це вплинуло на витрати звичайних людей у регіоні.")
 assert grounded_description_issue(d,REPORT)=="UNSUPPORTED_NAMED_ENTITY"

def test_one_repair_only_and_unreviewed():
 calls=[]
 valid=("Співрозмовник говорить про ціни на бензин і пояснює, чому, на його думку, "
     "подорожчали товари на заправках. У розмові згадують пенсії та соціальні "
     "виплати, які, за словами учасників, стали темою суперечки. "
     "Ведучий уточнює позицію гостя, а той вважає, що зміни зачіпають людей "
     "у регіоні. Дискусія зосереджена на тому, як громадяни оцінюють власні "
     "витрати та забезпечення.")
 def fake(messages,**kwargs):
    calls.append(messages)
    assert "Цены на бензин подорожали" in messages[1]["content"]
    return json.dumps({"description":valid},ensure_ascii=False)
 result,issue=recover_source_description(report=REPORT,current_title="Тема",model="dummy",chat=fake)
 assert result==valid and issue==""
 assert len(calls)==1


def test_source_quote_preview_three_distinct_spoken_passages():
 from rg_youtube_control.seo_content_editor import literal_quote_description_preview
 report={"blocks":[
   {"verified":True,"start_stamp":"00:00:03","topics":[
     {"evidence":"Цены на бензин выросли, и люди на заправках об этом говорят постоянно"}]},
   {"verified":True,"start_stamp":"00:05:22","topics":[
     {"evidence":"Пенсии и социальные выплаты отличаются, об этом спорят в регионе каждый день"}]},
   {"verified":True,"start_stamp":"00:10:04","topics":[
     {"evidence":"На работе говорят, что зарплата стала меньше, а расходы каждый месяц растут"}]}
 ]}
 desc=literal_quote_description_preview(report)
 assert "Цены на бензин выросли" in desc
 assert "Пенсии и социальные выплаты" in desc
 assert "зарплата стала меньше" in desc
 assert "обговорюють такі теми" not in desc
 assert 290<=len(desc)<=920
 assert grounded_description_issue(desc,report)=="SOURCE_QUOTES_ARE_NOT_UKRAINIAN_DESCRIPTION"


def test_quote_preview_must_not_be_considered_finished_seo():
 from rg_youtube_control.seo_quality_gate import inspect_package
 package={"title":"Питання росіянам про бензин та пенсії",
          "title_variants":["Чому подорожчав бензин у Росії?",
                            "Які пенсії обговорюють росіяни?",
                            "Як змінилися витрати у регіоні?"],
          "description":literal_quote_description_preview_source(),
          "tags":["бензин","ціни","пенсії","соціальні виплати","росіяни","РАША ГУДБАЙ","чат рулетка","Україна"],
          "description_source_quote_preview_only":True}
 verdict=inspect_package(package)
 assert not verdict["format_pass"]
 assert "SOURCE_QUOTES_PREVIEW_NOT_FINISHED_SEO" in verdict["problems"]["description"]

def literal_quote_description_preview_source():
 from rg_youtube_control.seo_content_editor import literal_quote_description_preview
 report={"blocks":[
 {"verified":True,"start_stamp":"00:00:03","topics":[{"evidence":"Цены на бензин выросли, и люди на заправках об этом говорят постоянно"}]},
 {"verified":True,"start_stamp":"00:05:22","topics":[{"evidence":"Пенсии и социальные выплаты отличаются, об этом спорят в регионе каждый день"}]},
 {"verified":True,"start_stamp":"00:10:04","topics":[{"evidence":"На работе говорят, что зарплата стала меньше, а расходы каждый месяц растут"}]}
 ]}
 return literal_quote_description_preview(report)