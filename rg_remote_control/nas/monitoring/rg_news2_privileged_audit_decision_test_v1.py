#!/usr/bin/env python3
"""Offline isolated regression for NEWS2 privileged gateway decision ledger."""
import importlib.util
import json
from pathlib import Path
import tempfile
s=Path(__file__).with_name('rg_news2_privileged_readonly_gateway_v1.py')
spec=importlib.util.spec_from_file_location('news2_audit_test',str(s))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='rg_news2_decision_regression_') as tmp:
    d=Path(tmp)
    keys=['a'*24,'b'*24,'c'*24]
    entries=[
      {'draft_id':keys[0],'decision':'editorially_accepted_not_published'},
      {'draft_id':keys[1],'decision':'editorially_rejected'},
      {'draft_id':keys[2],'decision':'UNKNOWN_LEGACY_STATUS'}
    ]
    for key,record in zip(keys,entries):
        (d/(key+'.json')).write_text(json.dumps(record),encoding='utf8')
    result=m.decision_summary(d)
    assert result['counts']=={'editorially_accepted_not_published':1,'editorially_rejected':1},result
    assert result['parse_errors']==1,result
    assert result['issues']=={'unexpected_decision':1},result
    assert 'draft_id' not in json.dumps(result)
print('NEWS2_DECISION_GATEWAY_ISOLATED_REGRESSION_PASS')
print('NEWS2_DECISION_STATUS_FALSE_POSITIVES_ELIMINATED_PASS')
