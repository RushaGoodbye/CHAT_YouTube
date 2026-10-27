#!/usr/bin/env python3
"""Read-only uncertain pilot receipt and outbound sender response contract inspection."""
import json,pathlib,ast,sys,os
B=pathlib.Path("/volume1/docker/RG_TELEGRAM_NEWS_2"); O=B/"operator"
def inspect():
 out={"schema":"NEWS_RG_UNCERTAIN_INSPECT_V1","read_only":True,"telegram_calls":0,"publications":0,"db_writes":0}
 p=O/"news_rg_private_pilot_claim_v1.json"
 if p.is_file() and not p.is_symlink():
  d=json.loads(p.read_text())
  out["receipt"]={k:d.get(k) for k in ("status","draft_id","created_at","message_id")}
 else:out["receipt"]="MISSING"
 s=(B/"rg_moderation.py").read_text()
 tree=ast.parse(s)
 for node in tree.body:
  if isinstance(node,ast.FunctionDef) and node.name == "api":
   out[node.name+"_implementation"]=[ast.dump(x,include_attributes=False)[:350] for x in node.body if isinstance(x,(ast.Return,ast.If,ast.Try,ast.Assign,ast.With))][:10]
 return out
if __name__=="__main__":
 if sys.argv[1:]==["selftest"]:print("UNCERTAIN_INSPECT_SELFTEST_PASS")
 elif sys.argv[1:]==["inspect"]:print(json.dumps(inspect(),ensure_ascii=False,indent=2))
