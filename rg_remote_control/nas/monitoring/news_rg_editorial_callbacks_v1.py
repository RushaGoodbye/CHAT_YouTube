#!/usr/bin/env python3
"""NEWS RG editorial decisions on the EXISTING Telegram callback stream.

No getUpdates, sendPhoto, sendMessage, channel publication, or production DB edits.
An editorial approval is NOT a publication approval.
"""
import os,json,re,pathlib,time
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2")
O=B/"operator"
ST=O/"news_rg_private_review_staging"
RECEIPTS=O/"news_rg_private_multipart_receipts_v1"
DECISIONS=O/"news_rg_editorial_decisions_v1"
PAT=re.compile(r"^ne1:(accept|reject):([a-f0-9]{24})$")
def _read_safe(p):
    if not p.is_file() or p.is_symlink() or p.stat().st_size>20000:
        raise ValueError("UNSAFE_OR_MISSING_FILE")
    return json.loads(p.read_text(encoding="utf-8"))
def _watermark_after_video_accept(draft_id):
    """Local durable handoff; NEVER claim Cloudflare watermark is done."""
    try:
        import news_rg_video_watermark_handoff_v1 as handoff
        outcome=handoff.ensure_approved(draft_id)
        return {"status":"VIDEO_APPROVED_WATERMARK_HANDOFF_QUEUED_LOCAL",
                "watermark_handoff":outcome.get("status"),
                "cloudflare_delivery":"NOT_VERIFIED","public_publication":"OFF"}
    except (OSError,ValueError,ImportError,RuntimeError):
        return {"status":"VIDEO_APPROVED_WATERMARK_HANDOFF_NEEDS_RECOVERY",
                "cloudflare_delivery":"NOT_ATTEMPTED","public_publication":"OFF"}
def process_callback(update,cfg):
    """Return None for non-NEWS-RG callbacks; status dict for NEWS-RG callbacks."""
    q=update.get("callback_query") or {}
    m=PAT.fullmatch(str(q.get("data","")))
    if not m:
        return None
    action,draft_id=m.groups()
    user=q.get("from") or {}
    chat=(q.get("message") or {}).get("chat") or {}
    msg=(q.get("message") or {})
    try:
        allowed=cfg.get("moderators") or []
        allowed={int(x) for x in allowed}
        moderator=int(user.get("id",0))
        expected=int(cfg.get("moderation_chat_id",0))
        if moderator<=0 or moderator not in allowed or expected<=0:
            return {"status":"EDITORIAL_USER_NOT_ALLOWED"}
        if int(chat.get("id",0))!=expected or str(chat.get("type",""))!="private":
            return {"status":"EDITORIAL_PRIVATE_CHAT_REQUIRED"}
        staged=_read_safe(ST/(draft_id+".json"))
        receipt=_read_safe(RECEIPTS/(draft_id+".json"))
        if staged.get("draft_id")!=draft_id or staged.get("public_publication")!="OFF":
            return {"status":"EDITORIAL_STAGING_NOT_SAFE"}
        if staged.get("editorial_status") not in ("HUMAN_FACT_AND_PHOTO_REVIEW_REQUIRED","HUMAN_FACT_AND_VIDEO_REVIEW_REQUIRED"):
            return {"status":"EDITORIAL_STAGING_NOT_READY"}
        if receipt.get("status")!="PRIVATE_SENT_CONFIRMED" or receipt.get("draft_id")!=draft_id:
            return {"status":"EDITORIAL_DELIVERY_NOT_CONFIRMED"}
        if receipt.get("message_id")!=msg.get("message_id"):
            return {"status":"EDITORIAL_MESSAGE_MISMATCH"}
        if DECISIONS.is_symlink():
            return {"status":"EDITORIAL_LEDGER_UNSAFE"}
        DECISIONS.mkdir(mode=0o700,parents=False,exist_ok=True)
        os.chmod(DECISIONS,0o700)
        dest=DECISIONS/(draft_id+".json")
        if dest.is_symlink():return {"status":"EDITORIAL_LEDGER_UNSAFE"}
        if dest.exists():
            existing=_read_safe(dest)
            if (staged.get("media_type")=="video" and
                existing.get("decision")=="editorially_accepted_not_published"):
                return _watermark_after_video_accept(draft_id)
            return {"status":"EDITORIAL_ALREADY_DECIDED","decision":existing.get("decision")}
        fd=os.open(str(dest),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump({"schema":"NEWS_RG_HUMAN_EDITORIAL_DECISION_V1",
               "draft_id":draft_id,
               "decision":"editorially_accepted_not_published" if action=="accept" else "editorially_rejected",
               "moderator_id":moderator,"telegram_message_id":msg["message_id"],
               "timestamp":int(time.time()),"public_publication":"OFF"},out,ensure_ascii=False)
            out.flush();os.fsync(out.fileno())
        if action=="accept" and staged.get("media_type")=="video":
            return _watermark_after_video_accept(draft_id)
        return {"status":"EDITORIAL_ACCEPTED_NO_PUBLICATION" if action=="accept" else "EDITORIAL_REJECTED",
                "public_publication":"OFF"}
    except FileExistsError:
        return {"status":"EDITORIAL_ALREADY_DECIDED"}
    except (OSError,ValueError,TypeError,KeyError):
        return {"status":"EDITORIAL_SAFE_STOP"}
def selftest():
    assert PAT.fullmatch("ne1:accept:"+"a"*24)
    assert "watermark" in _watermark_after_video_accept.__doc__.lower()
    assert _watermark_after_video_accept("invalid")["status"]=="VIDEO_APPROVED_WATERMARK_HANDOFF_NEEDS_RECOVERY"
    assert PAT.fullmatch("ne1:reject:"+"f"*24)
    assert not PAT.fullmatch("rg3:approve:"+"a"*24)
    assert not PAT.fullmatch("ne1:accept:"+"x"*24)
    assert process_callback({"callback_query":{"data":"rg3:approve:"+"a"*24}}, {}) is None
    print("NEWS_RG_EDITORIAL_CALLBACK_SELFTEST_PASS")
if __name__=="__main__":
    selftest()
