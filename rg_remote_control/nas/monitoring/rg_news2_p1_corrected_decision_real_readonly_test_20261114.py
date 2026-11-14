#!/usr/bin/env python3
"""NEWS2 P1 read-only integration of corrected decision diagnostics on real data.

Loads GH staged source, binds only pre-existing authorized NAS SMB folders.
Does not write, send Telegram requests, or change production.
"""
from pathlib import Path
import importlib.util,urllib.request,tempfile,json,os,types,hashlib
repo='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/'
sources={
 'gateway':('a99615b2172bb11a5531dadd6a5a26d82b767f7f','rg_news2_privileged_readonly_gateway_v1.py'),
 'reconciler':('43bbcb9eccc9e4a0568bf2602f7192b20de67794','rg_news2_decisions_reconcile_readonly_v1.py')
}
base=Path(r'\\192.168.50.32\docker\RG_TELEGRAM_NEWS_2\operator')
with tempfile.TemporaryDirectory(prefix='news2_p1_real_reconcile_') as td:
 objects={}
 for k,(sha,name) in sources.items():
  path=Path(td)/name
  path.write_bytes(urllib.request.urlopen(repo+sha+'/rg_remote_control/nas/monitoring/'+name,timeout=15).read())
  spec=importlib.util.spec_from_file_location(k,str(path))
  m=importlib.util.module_from_spec(spec)
  spec.loader.exec_module(m)
  m.selftest()
  objects[k]=m
 g=objects['gateway'];r=objects['reconciler']
 g.ROOT=base
 g.DECISIONS=base/'news_rg_editorial_decisions_v1'
 g.ST=base/'news_rg_private_review_staging'
 g.PRIVATE=base/'news_rg_private_multipart_receipts_v1'
 g.PUBLIC=base/'news_rg_publication_receipts_v1'
 result=g.decision_summary(g.DECISIONS)
 assert result['parse_errors']==0,result
 assert result['automatically_rejected_expired_v2']==26,result
 assert result['counts']=={'editorially_accepted_not_published':48,
                            'editorially_rejected':198,
                            'editorially_expired':1},result
 r.O=base
 r.DIRS={
   'decisions':base/'news_rg_editorial_decisions_v1',
   'private':base/'news_rg_private_multipart_receipts_v1',
   'public':base/'news_rg_publication_receipts_v1',
   'staged':base/'news_rg_private_review_staging',
   'activation':base/'news_rg_publication_activation_v1.json'
 }
 re=r.reconcile()
 assert re['decision_parse_issues']=={},re
 assert re['automatically_rejected_expired_v2']==26,re
 assert re['accepted_publication_reconciliation'].get('accepted_with_public_receipt_PUBLIC_PUBLISHED_CONFIRMED')==47,re
 assert re['accepted_publication_reconciliation'].get('accepted_without_public_receipt_before_activation_not_publishable')==1,re
 # Isolated corrupted decision does not silently count as normal.
 folder=Path(td)/'bad';folder.mkdir()
 sample={'draft_id':'a'*24,'schema':'WRONG_SCHEMA','decision':'editorially_expired'}
 (folder/('a'*24+'.json')).write_text(json.dumps(sample))
 broken=g.decision_summary(folder)
 assert broken['parse_errors']==1 and broken['issues'].get('unexpected_decision_or_schema')==1,broken
 print(json.dumps({'status':'NEWS2_P1_REAL_DECISION_SCHEMA_RECONCILIATION_PASS',
   'valid_decisions':sum(result['counts'].values()),
   'counts':result['counts'],'parse_errors':result['parse_errors'],
   'historical_pre_activation_approvals':1,
   'confirmed_publications':47,
   'corrupted_schema_rejected':True,
   'real_telegram_calls':0,'nas_writes':0},ensure_ascii=False))
