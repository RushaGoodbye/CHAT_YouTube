#!/usr/bin/env python3
"""Read-only Telegram bot transport diagnostics on Synology NAS.
ONLY getMe, getChat, getChatMember. No sendPhoto, sendMessage, getUpdates,
deleteWebhook, mutation or Cloudflare access. No secrets printed.
"""
import argparse,json,os,pathlib,re,stat,sys,urllib.error,urllib.parse,urllib.request
ROOT=pathlib.Path("/volume1/docker")
ENV_FILES=(ROOT/"RG_CONTENT_DEPLOY/deploy.env",ROOT/"RG_ALERTS_DEPLOY/deploy.env",ROOT/"RG_DEPLOY/deploy.env")
TOKEN_FILES=(ROOT/"RG_SECRETS/rg_telegram_bot_token",ROOT/"RG_SECRETS/telegram_bot_token")
CHAT="@RussiaGoodbyeUA"
TOKEN_RX=re.compile(r"^[0-9]{5,13}:[A-Za-z0-9_-]{25,}$")
SAFE_API={"getMe","getChat","getChatMember"}
def read_kv(path):
 if not path.is_file() or path.is_symlink():return {}
 values={}
 with path.open("r",encoding="utf-8") as file:
  for raw in file:
   line=raw.strip()
   m=re.match(r"^(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*)$",line)
   if not m:continue
   value=m.group(2).strip()
   if len(value)>=2 and value[0]==value[-1] and value[0] in "'\"":value=value[1:-1]
   values[m.group(1)]=value
 return values
def credential():
 for path in TOKEN_FILES:
  if not path.is_symlink() and path.is_file():
   token=path.read_text("utf-8").strip()
   if TOKEN_RX.fullmatch(token):return token,path.name
 for path in ENV_FILES:
  data=read_kv(path)
  token=data.get("TELEGRAM_BOT_TOKEN","")
  if TOKEN_RX.fullmatch(token):return token,path.parent.name+"/deploy.env"
 return None,None
def get_json(token,method,params):
 if method not in SAFE_API:raise ValueError("read_only_method_violation")
 qs=urllib.parse.urlencode(params)
 url="https://api.telegram.org/bot"+token+"/"+method+("?"+qs if qs else "")
 request=urllib.request.Request(url,headers={"User-Agent":"RG-NAS-Telegram-Readiness/1.0","Accept":"application/json"})
 try:
  with urllib.request.urlopen(request,timeout=12) as response:
   if response.status!=200:raise RuntimeError("telegram_http_non200")
   raw=response.read(16001)
 except urllib.error.HTTPError as ex:
  # Exceptions and URLs may contain bot token: NEVER propagate the exception or request URI.
  raise RuntimeError("telegram_http_"+str(ex.code)) from None
 except (urllib.error.URLError,TimeoutError,OSError):
  raise RuntimeError("telegram_connectivity_error") from None
 if len(raw)>16000:raise RuntimeError("telegram_reply_too_large")
 try:body=json.loads(raw)
 except (ValueError,TypeError):raise RuntimeError("telegram_bad_json") from None
 if not isinstance(body,dict) or body.get("ok") is not True:raise RuntimeError("telegram_api_not_ok")
 result=body.get("result")
 if not isinstance(result,dict):raise RuntimeError("telegram_result_not_object")
 return result
def probe(token,source):
 me=get_json(token,"getMe",{})
 bot_id=me.get("id")
 if not isinstance(bot_id,int) or bot_id<=0 or me.get("is_bot") is not True:raise RuntimeError("bot_identity_invalid")
 info=get_json(token,"getChat",{"chat_id":CHAT})
 if info.get("type")!="channel":raise RuntimeError("target_not_channel")
 if str(info.get("username","")).casefold()!=CHAT.lstrip("@").casefold():raise RuntimeError("target_channel_mismatch")
 member=get_json(token,"getChatMember",{"chat_id":CHAT,"user_id":bot_id})
 role=member.get("status")
 can_post=role=="creator" or (role=="administrator" and member.get("can_post_messages") is True)
 return {"status":"TELEGRAM_TRANSPORT_READ_READY" if can_post else "BLOCKED_BOT_NOT_POSTING_ADMIN",
         "credential_source":source,"bot_username":me.get("username",""),
         "channel_username":"@"+str(info["username"]),"channel_type":info["type"],
         "bot_membership":role,"bot_can_post":bool(can_post),
         "operations":["getMe","getChat","getChatMember"],
         "production_post_enabled":False,"telegram_sends":0,"cloudflare_calls":0,
         "sole_writer_verified":False,"no_backfill_enforced_at_transport":False}
def selftest():
 assert not (set(("sendMessage","sendPhoto","getUpdates","deleteWebhook"))&SAFE_API)
 assert TOKEN_RX.fullmatch("12345678:"+"a"*38)
 assert not TOKEN_RX.fullmatch("not_a_token")
 assert not TOKEN_RX.fullmatch("1234:"+ "a"*38)
 with __import__("tempfile").TemporaryDirectory() as folder:
  path=pathlib.Path(folder)/"deploy.env"
  path.write_text('TELEGRAM_BOT_TOKEN="12345678:'+("a"*38)+'"\nexport TELEGRAM_CHAT_ID=@RussiaGoodbyeUA\n',encoding="utf-8")
  assert read_kv(path)["TELEGRAM_CHAT_ID"]==CHAT
  assert TOKEN_RX.fullmatch(read_kv(path)["TELEGRAM_BOT_TOKEN"])
 assert not (set(("sendMessage","sendPhoto"))&SAFE_API)
 print(json.dumps({"status":"TRANSPORT_SELFTEST_PASS","methods_read_only":True,"bot_token_logged":False,
                   "telegram_sends":0,"network_calls":0}))
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("mode",choices=("selftest","status","probe"))
 a=parser.parse_args()
 if a.mode=="selftest":selftest();return
 token,source=credential()
 if not token:
  print(json.dumps({"status":"BLOCKED_TOKEN_NOT_AVAILABLE_ON_NAS","searched_locations":["RG_SECRETS/rg_telegram_bot_token","RG_SECRETS/telegram_bot_token","RG_CONTENT_DEPLOY/deploy.env","RG_ALERTS_DEPLOY/deploy.env","RG_DEPLOY/deploy.env"],
    "send_enabled":False,"telegram_sends":0}))
  return
 if a.mode=="status":
  print(json.dumps({"status":"TRANSPORT_CREDENTIAL_AVAILABLE","source":source,"token_value_not_printed":True,
                    "telegram_sends":0}))
  return
 result=probe(token,source)
 print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
 try:main()
 except Exception as error:
  # Never emit exception text beyond a tightly controlled reason.
  reason=str(error)
  allowed={"telegram_bad_json","telegram_api_not_ok","telegram_result_not_object",
           "telegram_http_non200","telegram_reply_too_large","telegram_connectivity_error",
           "bot_identity_invalid","target_not_channel","target_channel_mismatch","read_only_method_violation"}
  safe=reason if reason in allowed or re.fullmatch(r"telegram_http_[0-9]{3}",reason) else type(error).__name__
  print(json.dumps({"status":"BLOCKED","reason":safe,"bot_token_logged":False,"telegram_sends":0}),file=sys.stderr)
  sys.exit(1)
