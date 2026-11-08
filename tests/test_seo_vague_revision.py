from rg_youtube_control.seo_editorial_revision import propose_editorial_revision
import json

def test_vague_rejected():
    c={"verbatim_quote":"The shops are closing in the neighborhood","source_context":"The shops are closing in the neighborhood."}
    def chat(*a,**kw):
        return json.dumps({"topic":"Unknown something","summary_uk":"There is an unknown event under discussion."})
    assert propose_editorial_revision(card=c,chat=chat,model="stub")["status"]=="BLOCKED_VAGUE_TOPIC"


def test_second_try_concrete_topic_can_be_reviewed():
    c={"verbatim_quote":"The shops are closing in the neighborhood",
       "source_context":"The shops are closing in the neighborhood."}
    def chat(*a,**kw):
        return json.dumps({"topic":"Зачинення магазинів",
          "summary_uk":"У розмові йдеться про зачинення магазинів у районі."})
    out=propose_editorial_revision(card=c,chat=chat,model="stub")
    assert out["status"]=="REVIEW_REQUIRED"
    assert not out["editorial_approved"]
