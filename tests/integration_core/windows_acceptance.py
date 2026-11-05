"""Run the same two-cycle integration scenario on actual ACE. Exit 2 means BLOCKED."""
import argparse
import json
import os
import sys
from pathlib import Path
from scenario import ROOT, two_cycles
from perfin_app.paths import initialize_layout, child
from perfin_store.setup import create_database
from perfin_store.__main__ import open_access
from perfin_store import backup


def main():
    p=argparse.ArgumentParser();p.add_argument('--workdir',required=True);a=p.parse_args()
    if sys.platform!='win32':
        print('BLOCKED: Windows/ACE required');return 2
    root=initialize_layout(a.workdir,synthetic=True);db=child(root,'db/perfin.accdb')
    evidence={'environment':'Windows/ACE','checks':[],'desktop_excel':'pending separate release COM check'}
    repo=None
    try:
        create_database(db);repo=open_access(str(db));app,expected=two_cycles(repo,root)
        out=app.refresh('2026-03-28');summary=repo.summary();repo.adapter.close();repo=None
        saved=backup.create_backup(db,child(root,'backups'),summary=summary)
        def read_summary(path):
            r=open_access(str(path))
            try:return r.summary()
            finally:r.adapter.close()
        restored=child(root,'db/restored.accdb');backup.restore_backup(saved,restored,open_summary=read_summary)
        assert read_summary(restored)==summary
        evidence.update(status='PASS',checks=['two cycles','six reconciliations','replay no-op','report/workbook generation','verified restore'],balances=expected,workbook=out['workbook'])
        code=0
    except Exception as exc:
        evidence.update(status='FAIL',error_type=type(exc).__name__);code=1
    finally:
        if repo is not None:repo.adapter.close()
    child(root,'integration-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
