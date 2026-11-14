#!/usr/bin/env python3
"""Offline contract tests for NEWS2 decision reconciliation, no production reads."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time

SOURCE=Path(__file__).with_name('rg_news2_decisions_reconcile_readonly_v1.py')

def run():
    sp=importlib.util.spec_from_file_location('news2_reconcile',str(SOURCE))
    m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    with tempfile.TemporaryDirectory(prefix='news2_decision_fixture_') as tmp:
        root=Path(tmp)
        m.DIRS={k:root/k for k in ('decisions','private','public','staged')}
        for path in m.DIRS.values():path.mkdir()
        def write(folder,key,body):
            (m.DIRS[folder]/(key+'.json')).write_text(json.dumps(body),encoding='utf8')
        now=int(time.time())
        a='a'*24;b='b'*24;c='c'*24;d='d'*24;e='e'*24
        write('decisions',a,{'draft_id':a,'decision':'editorially_accepted_not_published','timestamp':now-100})
        write('decisions',b,{'draft_id':b,'decision':'editorially_accepted_not_published','timestamp':now-1800})
        write('decisions',c,{'draft_id':c,'decision':'editorially_accepted_not_published','timestamp':now-88000})
        write('decisions',d,{'draft_id':d,'decision':'editorially_rejected','timestamp':now-300})
        write('decisions',e,{'draft_id':e,'decision':'editorially_accepted_not_published','timestamp':now-800})
        write('public',e,{'status':'PUBLIC_PUBLISHED_CONFIRMED'})
        doc=m.reconcile()
        assert doc['decision_files']==5,doc
        assert doc['decision_counts']=={'editorially_accepted_not_published':4,'editorially_rejected':1},doc
        assert doc['decision_parse_issues']=={},doc
        p=doc['accepted_publication_reconciliation']
        assert p['accepted_without_public_receipt_under_15m']==1,p
        assert p['accepted_without_public_receipt_15_to_35m']==1,p
        assert p['accepted_without_public_receipt_over_24h']==1,p
        assert p['accepted_with_public_receipt_PUBLIC_PUBLISHED_CONFIRMED']==1,p
        assert doc['telegram_calls']==0 and doc['production_writes']==0
    print('NEWS2_DECISION_RECONCILE_5_CASES_PASS')
    print('NEWS2_DECISION_RECONCILE_NO_FALSE_PARSE_ERRORS_PASS')
    print('NEWS2_DECISION_RECONCILE_NO_API_OR_WRITES_PASS')

if __name__=='__main__':run()
