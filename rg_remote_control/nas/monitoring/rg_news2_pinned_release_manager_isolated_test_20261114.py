#!/usr/bin/env python3
"""Isolated test for root release manager. Production files never accessed."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import tempfile

M=Path('/tmp/rg_news2_pinned_release_manager_20261114.py')
BEFORE=Path('/tmp/rg_news2_gateway_before_fixture.py')
AFTER=Path('/tmp/rg_news2_privileged_readonly_gateway_v1.py')

def test():
    spec=importlib.util.spec_from_file_location('release_manager_tested',str(M))
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    old=BEFORE.read_bytes()
    new=AFTER.read_bytes()
    assert m.blob(old)==m.PREV,(m.blob(old),m.PREV)
    assert m.blob(new)==m.NEW,(m.blob(new),m.NEW)
    with tempfile.TemporaryDirectory(prefix='rg_news2_release_isolated_') as tmp:
        root=Path(tmp)
        m.OP=root
        m.DST=root/'gateway.py'
        m.BK=root/'backups'
        m.REL=m.BK/'decision_gateway_20261114_v1'
        m.OLD=m.REL/'gateway_before.py'
        m.RECEIPT=m.REL/'release_receipt.json'
        m.LOCK=root/'release.lock'
        m.DST.write_bytes(old)
        original_preflight=m.preflight
        original_evidence=m.evidence
        original_rootdir=m.rootdir
        original_geteuid=m.os.geteuid
        m.preflight=lambda:(m.DST.read_bytes(),new)
        m.rootdir=lambda p,create=False:p.mkdir(mode=0o700,exist_ok=True) if create else None
        m.os.geteuid=lambda:0
        m.evidence=lambda:{'decision_counts':{'editorially_rejected':198,'editorially_accepted_not_published':48},
                           'parse_errors':1}
        try:
            result=m.apply()
            assert result['status']=='APPLIED_QA_PASS',result
            assert m.DST.read_bytes()==new
            assert m.OLD.read_bytes()==old
            assert m.RECEIPT.is_file()
            rollback=m.rollback()
            assert rollback['status']=='ROLLBACK_VERIFIED'
            assert m.DST.read_bytes()==old
        finally:
            m.preflight=original_preflight
            m.evidence=original_evidence
            m.rootdir=original_rootdir
            m.os.geteuid=original_geteuid
    with tempfile.TemporaryDirectory(prefix='rg_news2_release_failqa_') as tmp:
        root=Path(tmp)
        m.OP=root;m.DST=root/'gateway.py';m.DST.write_bytes(old)
        m.BK=root/'backups';m.REL=m.BK/'decision_gateway_20261114_v1'
        m.OLD=m.REL/'gateway_before.py';m.RECEIPT=m.REL/'release_receipt.json';m.LOCK=root/'release.lock'
        m.preflight=lambda:(m.DST.read_bytes(),new)
        m.rootdir=lambda p,create=False:p.mkdir(mode=0o700,exist_ok=True) if create else None
        m.evidence=lambda:(_ for _ in ()).throw(RuntimeError('SIMULATED_POST_INSTALL_QA_FAILURE'))
        try:
            try:m.apply()
            except RuntimeError as ex:assert 'SIMULATED_POST_INSTALL_QA_FAILURE' in str(ex)
            else:raise AssertionError('EXPECTED_QA_FAIL')
            assert m.DST.read_bytes()==old
            assert m.OLD.read_bytes()==old
            assert not m.RECEIPT.exists()
        finally:
            m.preflight=original_preflight
            m.evidence=original_evidence
            m.rootdir=original_rootdir
    print('NEWS2_ATOMIC_RELEASE_INSTALL_ROLLBACK_PASS')
    print('NEWS2_POSTINSTALL_FAILURE_AUTOMATIC_ROLLBACK_PASS')
    print('NEWS2_BACKUP_SHA_MATCH_PASS')

if __name__=='__main__':test()
