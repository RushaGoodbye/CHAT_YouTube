from rg_youtube_control.seo_editorial_revision import propose_editorial_revision
import json

def test_vague_rejected():
    c={"verbatim_quote":"The shops are closing in the neighborhood","source_context":"The shops are closing in the neighborhood."}
    def chat(*a,**kw):
        return json.dumps({"topic":"Unknown something","summary_uk":"There is an unknown event under discussion."})
    assert propose_editorial_revision(card=c,chat=chat,model="stub")["status"]=="BLOCKED_VAGUE_TOPIC"
