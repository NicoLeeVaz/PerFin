import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from scenario import ROOT, two_cycles, FinanceApp, accepted
from fake_access import new_fake_store, FakeAccessAdapter
from perfin_app.paths import initialize_layout, LocationError
from perfin_store.repository import Repository, StorageError
from perfin_store import backup
from perfin_import.profiles import profile_from_mapping


class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='perfin-integration-');self.addCleanup(self.temp.cleanup)
        self.root=initialize_layout(self.temp.name,synthetic=True)
        self.repo,self.adapter,_=new_fake_store(path=str(self.root/'db/perfin.accdb'))
        self.addCleanup(self.adapter.close)

    def test_two_cycles_replay_exact_reports_and_restore(self):
        with patch('socket.create_connection', side_effect=AssertionError('network prohibited')):
            app,expected=two_cycles(self.repo,self.root)
        result=app.refresh('2026-03-28')
        self.assertTrue(Path(result['workbook']).is_file())
        from perfin_excel_core.reports import read_report_csv
        rows=read_report_csv(self.root/'reports/rpt_accounts.csv','rpt_accounts')
        self.assertEqual({r['account_id']:r['ledger_balance_minor'] for r in rows},expected)
        summary=self.repo.summary();self.adapter.close()
        b=backup.create_backup(self.root/'db/perfin.accdb',self.root/'backups',summary=summary)
        def read_summary(path):
            a=FakeAccessAdapter(path=str(path));r=Repository(a)
            try:return r.summary()
            finally:a.close()
        restored=self.root/'db/restored.accdb'
        backup.restore_backup(b,restored,open_summary=read_summary)
        self.assertEqual(read_summary(restored),summary)

    def test_stage_preserves_extras_and_failed_commit_is_atomic(self):
        import synthetic as S
        accepted(self.repo.import_bundle(S.reference_bundle()));accepted(self.repo.set_default_categories('exp.uncategorized','inc.uncategorized'))
        d=S.card_batch();d['rows'][0]['parsed']['running_balance_minor']=-46234
        d['rows'][0]['transfer_candidate_transaction_id']='candidate'
        d['rows'][4]['duplicate']['matched_row_number']=1;d['rows'][4]['duplicate']['evidence']='synthetic evidence'
        accepted(self.repo.stage_batch(d));out=self.repo.export_staging_batch(d['batch']['batch_id'])
        self.assertEqual(out['rows'][0]['parsed']['running_balance_minor'],-46234)
        self.assertEqual(out['rows'][0]['transfer_candidate_transaction_id'],'candidate')
        self.assertEqual(out['rows'][4]['duplicate']['evidence'],'synthetic evidence')
        app=FinanceApp(self.repo,self.root);app.review(d['batch']['batch_id'],approve=[1],reject=[2,3,4,5,6],reason='synthetic')
        before=copy.deepcopy(self.adapter.db.rows)
        self.adapter.fail_on("INSERT INTO [split]", nth=1)
        with self.assertRaises(StorageError):app.commit(d['batch']['batch_id'])
        self.assertEqual(self.adapter.db.rows,before)

    def test_child_symlink_is_refused(self):
        outside=self.root.parent/(self.root.name+'-outside');outside.mkdir();self.addCleanup(outside.rmdir)
        (self.root/'staging').rmdir();(self.root/'staging').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(LocationError):FinanceApp(self.repo,self.root).path('staging/private.json')


class CommandsAndPackaging(unittest.TestCase):
    def test_identical_outbox_requeue_is_dequeued(self):
        from perfin_app.__main__ import demo_bundle
        from perfin_store.__main__ import make_command
        from perfin_app.service import WorkflowError
        with tempfile.TemporaryDirectory(prefix='perfin-outbox-') as d:
            root=initialize_layout(d,synthetic=True);repo,ad,_=new_fake_store();self.addCleanup(ad.close)
            accepted(repo.import_bundle(demo_bundle(repo.contract_version)));app=FinanceApp(repo,root)
            scenario=json.loads((ROOT/'contracts/examples/valid/payoff_scenario.json').read_text())
            doc=make_command(repo,'save_payoff_scenario',scenario['scenario'],[])
            p=root/'commands/outbox'/(doc['command_id']+'.json')
            p.write_text(json.dumps(doc));first=app.process_outbox();before=copy.deepcopy(ad.db.rows)
            self.assertEqual(first['results'][0]['result_status'],'accepted')
            doc['issued_at']='2026-12-31T23:59:59Z'
            p.write_text(json.dumps(doc));second=app.process_outbox()
            self.assertEqual(second['results'][0]['result_status'],'replayed');self.assertFalse(p.exists())
            self.assertEqual(ad.db.rows,before)
            doc['payload']['cash_plan']['monthly_minor']+=1;p.write_text(json.dumps(doc))
            with self.assertRaises(WorkflowError):app.process_outbox()
            self.assertEqual(ad.db.rows,before)

    def test_low_level_report_file_symlink_refused(self):
        from perfin_store.reports import export_csv, ExportLocationError
        with tempfile.TemporaryDirectory(prefix='perfin-export-') as d:
            root=Path(d);out=root/'reports';out.mkdir();dest=root/'outside.csv';dest.write_text('sentinel')
            (out/'rpt_accounts.csv').symlink_to(dest)
            repo,ad,_=new_fake_store();self.addCleanup(ad.close)
            with self.assertRaises(ExportLocationError):export_csv(repo,out)
            self.assertEqual(dest.read_text(),'sentinel')

class AdditionalFlows(unittest.TestCase):
    def test_cli_reconcile_can_update_without_json_commands(self):
        from contextlib import redirect_stdout
        import io
        from perfin_app.__main__ import main, demo_bundle
        with tempfile.TemporaryDirectory(prefix='perfin-cli-') as d:
            root=initialize_layout(d,synthetic=True);db=root/'db/perfin.accdb';repo,ad,_=new_fake_store(path=str(db))
            accepted(repo.import_bundle(demo_bundle(repo.contract_version)));ad.close()
            def open_repo(path):return Repository(FakeAccessAdapter(path=path))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--data-root',str(root),'statement-add','empty','--account','chk:main','--start','2026-01-01',
                    '--end','2026-01-31','--opening-cents','250000','--closing-cents','250000'],open_repo=open_repo),0)
                for _ in range(2):
                    self.assertEqual(main(['--data-root',str(root),'reconcile','empty','--transactions',''],open_repo=open_repo),0)
            r=open_repo(str(db))
            try:self.assertEqual(r._one('reconciliation',{'reconciliation_id':'recon.empty'})['row_version'],2)
            finally:r.adapter.close()

    def test_pdf_replay_keeps_staging_and_provenance(self):
        import importlib.util
        from perfin_app.__main__ import demo_bundle
        spec=importlib.util.spec_from_file_location('pdf_fixture',ROOT/'fixtures/pdf/synthetic.py')
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory(prefix='perfin-pdf-app-') as d:
            root=initialize_layout(d,synthetic=True);repo,ad,_=new_fake_store();self.addCleanup(ad.close)
            accepted(repo.import_bundle(demo_bundle(repo.contract_version)));app=FinanceApp(repo,root)
            data=fixture.pdf_bytes()
            first=app.import_pdf(data,'synthetic.pdf','chk:main');before=copy.deepcopy(ad.db.rows)
            second=app.import_pdf(data,'synthetic.pdf','chk:main')
            self.assertEqual(first['document']['batch']['batch_id'],second['document']['batch']['batch_id'])
            self.assertEqual(before,ad.db.rows)
            self.assertTrue(list((root/'staging').glob('*.pdf-provenance.json')))

    def test_reversed_originals_remain_duplicate_evidence(self):
        from test_repository import Transfers
        from perfin_app.service import ImportView
        case=Transfers();case.setUp();self.addCleanup(case.ad.close)
        for original,reversal in [('m1','rv1'),('rv1','rv2')]:
            case.ok(case.run_cmd('reverse_transaction',{'transaction_id':original,'reversal_transaction_id':reversal,
                    'posted_date':'2026-07-20','reason':'synthetic reversal'},[case.ev('transaction',original)]))
        candidates=ImportView(case.repo).find_candidates('chk:main','2026-07-10',-10000,3)
        self.assertEqual([t['transaction_id'] for t in candidates],['m1'])

    def test_optional_modules_read_access_snapshot_and_save_parameters(self):
        from perfin_app.__main__ import demo_bundle
        with tempfile.TemporaryDirectory(prefix='perfin-modules-') as d:
            root=initialize_layout(d,synthetic=True);repo,ad,_=new_fake_store();self.addCleanup(ad.close)
            accepted(repo.import_bundle(demo_bundle(repo.contract_version)));app=FinanceApp(repo,root)
            before=repo.export_bundle()
            scenario=json.loads((ROOT/'fixtures/payoff/scenario.synthetic.json').read_text())
            result=app.payoff(scenario)
            self.assertTrue(Path(result['workbook']).exists())
            self.assertEqual(repo.payoff_scenario(scenario['scenario']['scenario_id'])['scenario'],scenario['scenario'])
            st=app.statements('2026-03-31','2026-01-01')
            self.assertTrue(Path(st['workbook']).exists())
            self.assertEqual(before,repo.export_bundle())
            app.refresh('2026-03-31')
            from perfin_excel_core.reports import read_report_csv
            rows=read_report_csv(root/'reports/perfin_modules.csv','perfin_modules')
            self.assertEqual(len(rows),2);self.assertTrue(all(r['launchable'] for r in rows))

    def test_excel_review_versions_refresh_and_stale_tokens_reject(self):
        import synthetic as S
        from perfin_excel_core import commands, reports, spec
        from perfin_app.service import WorkflowError
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory(prefix='perfin-review-tokens-') as d:
            root=initialize_layout(d,synthetic=True);repo,ad,_=new_fake_store();self.addCleanup(ad.close)
            accepted(repo.import_bundle(S.reference_bundle()));accepted(repo.stage_batch(S.card_batch()))
            app=FinanceApp(repo,root);out=app.refresh('2026-07-02')
            rows=reports.read_report_csv(root/'reports/perfin_batch_versions.csv',spec.BATCH_VERSIONS_TABLE)
            self.assertEqual(rows,[{'batch_id':'b.alpha.07','row_version':1}])
            wb=load_workbook(out['workbook'])
            self.assertIn(spec.BATCH_VERSIONS_TABLE,wb['Settings'].tables)
            self.assertEqual(wb['Settings']['D15'].value,'b.alpha.07');self.assertEqual(wb['Settings']['E15'].value,1)
            self.assertTrue(wb['Settings'].protection.sheet)
            app.command(commands.build_review_command('approve_rows','b.alpha.07',[1],batch_row_version=1))
            with self.assertRaisesRegex(WorkflowError,'E_STALE_VERSION'):
                app.command(commands.build_review_command('approve_rows','b.alpha.07',[2],batch_row_version=1))
            app.refresh('2026-07-02')
            self.assertEqual(reports.read_report_csv(root/'reports/perfin_batch_versions.csv',spec.BATCH_VERSIONS_TABLE)[0]['row_version'],2)
            vba=(ROOT/'excel/core/vba/PerFinCommands.bas').read_text()
            self.assertIn('version = BatchVersion(batch)',vba)
            self.assertIn('If version < 1 Then',vba)
            self.assertIn('CStr(version)',vba)
            self.assertNotIn('""expected_versions"": []',vba)

if __name__=='__main__':unittest.main()
