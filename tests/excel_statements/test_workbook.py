import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'contracts/python'),str(ROOT/'excel/core'),str(ROOT/'excel/statements'),str(ROOT/'tests/statements')]
from openpyxl import load_workbook
from perfin_excel_statements import build, read_valuation_commands, queue_valuations
from perfin_excel_statements.__main__ import main
from perfin_excel_core import registry
from perfin_excel_core.offline_check import check_workbook
from perfin_statements import build_statements
from test_engine import bundle, valuation, account


class WorkbookTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='perfin-statements-');self.root=Path(self.temp.name)
        (self.root/'perfin-data-dir.json').write_text('{"kind":"synthetic"}')
        self.bundle=bundle();self.bundle['accounts'].append(account('re:synthetic','real_estate'))
        valuation(self.bundle,'re:synthetic',200000)
        self.details=build_statements(self.bundle,as_of='2026-02-28',period_start='2026-02-01')
        self.out=self.root/'workbooks/excel_statements/PerFin-Statements.xlsx'

    def tearDown(self):self.temp.cleanup()

    def form(self):
        build(self.details,self.out,data_root=self.root)
        wb=load_workbook(self.out);ws=wb['Valuations']
        values=['re:synthetic',date(2026,2,28),2200.25,'USD','SYNTHETIC estimate','owner_estimate','v.next',None,'Yes']
        for col,value in enumerate(values,1):ws.cell(4,col,value)
        wb.save(self.out);wb.close()

    def test_workbook_totals_and_sources(self):
        build(self.details,self.out,data_root=self.root)
        wb=load_workbook(self.out)
        self.assertEqual(wb.sheetnames,['Summary','Accounts','Income','Cash flow','Bridge','Valuations'])
        self.assertEqual(wb['Summary']['B11'].value,'=B9-B10')
        self.assertEqual(wb['Summary']['B8'].value,'Complete supplied data')
        rows=list(wb['Accounts'].iter_rows(min_row=4,values_only=True))
        self.assertEqual(sum(r[4] or 0 for r in rows),2600)
        self.assertTrue(any(r[8]=='SYNTHETIC statement' for r in rows))
        self.assertFalse(wb['Valuations']['A4'].protection.locked)
        self.assertTrue(wb['Accounts'].protection.sheet)
        self.assertEqual(len(wb['Summary']._charts),1)
        wb.close()

    def test_text_safe_and_offline(self):
        self.details['provenance'][0]['name']='=SUM(A1:A99)'
        build(self.details,self.out,data_root=self.root)
        wb=load_workbook(self.out);self.assertEqual(wb['Accounts']['B4'].data_type,'s');wb.close()
        result=check_workbook(self.out)
        self.assertEqual([f for f in result if f.severity!='INFO'],[])

    def test_valuation_queue_exact_cents_and_idempotent(self):
        self.form();commands=read_valuation_commands(self.out)
        self.assertEqual(commands[0]['payload']['value_minor'],220025)
        self.assertEqual(commands[0]['payload']['as_of'],'2026-02-28')
        before=self.out.read_bytes()
        paths=queue_valuations(self.out,data_root=self.root)
        self.assertEqual(queue_valuations(self.out,data_root=self.root),paths)
        self.assertEqual(len(list((self.root/'commands/outbox').glob('*.json'))),1)
        self.assertEqual(self.out.read_bytes(),before)

    def test_invalid_or_formula_request_never_queues(self):
        self.form();wb=load_workbook(self.out);wb['Valuations']['C4']='=2000+200';wb.save(self.out);wb.close()
        with self.assertRaises(ValueError):queue_valuations(self.out,data_root=self.root)
        self.assertFalse((self.root/'commands/outbox').exists())

    def test_rejects_fractional_cents(self):
        self.form();wb=load_workbook(self.out);wb['Valuations']['C4']=20.001;wb.save(self.out);wb.close()
        with self.assertRaises(ValueError):read_valuation_commands(self.out)

    def test_privacy_path_refused_before_write(self):
        with self.assertRaises(Exception):build(self.details,ROOT/'statements.xlsx',data_root=ROOT)
        self.assertFalse((ROOT/'statements.xlsx').exists())
        with self.assertRaises(Exception):build(self.details,ROOT/'statements.xlsx',data_root=self.root)

    def test_cli_build_and_registry(self):
        source=self.root/'bundle.json';source.write_text(json.dumps(self.bundle))
        self.assertEqual(main(['build','--bundle',str(source),'--data-root',str(self.root),
                              '--as-of','2026-02-28','--period-start','2026-02-01']),0)
        rows=registry.scan(self.root/'workbooks')
        self.assertEqual(rows[0]['module_id'],'excel_statements');self.assertTrue(rows[0]['launchable'])

    def test_temp_symlink_cannot_redirect_private_workbook(self):
        self.out.parent.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as outside:
            target=Path(outside)/'other.xlsx';target.write_text('untouched')
            self.out.with_suffix('.partial.xlsx').symlink_to(target)
            build(self.details,self.out,data_root=self.root)
            self.assertEqual(target.read_text(),'untouched')
            self.assertTrue(self.out.is_file())

    def test_manifest_symlink_outside_data_root_is_refused(self):
        self.out.parent.mkdir(parents=True)
        source=self.root/'bundle.json';source.write_text(json.dumps(self.bundle))
        with tempfile.TemporaryDirectory() as outside:
            target=Path(outside)/'manifest.json';target.write_text('untouched')
            (self.out.parent/'module_manifest.json').symlink_to(target)
            with self.assertRaises(Exception):
                main(['build','--bundle',str(source),'--data-root',str(self.root),
                      '--as-of','2026-02-28','--period-start','2026-02-01'])
            self.assertEqual(target.read_text(),'untouched')

    def test_blank_valuation_id_is_stable_for_account_and_date(self):
        self.form();wb=load_workbook(self.out);wb['Valuations']['G4']=None;wb.save(self.out);wb.close()
        first=read_valuation_commands(self.out)[0];second=read_valuation_commands(self.out)[0]
        self.assertEqual(first['payload']['valuation_id'],second['payload']['valuation_id'])
        self.assertTrue(first['payload']['valuation_id'].startswith('val-'))

    def test_changed_valuation_refreshes_output(self):
        build(self.details,self.out,data_root=self.root)
        valuation(self.bundle,'re:synthetic',230000,'2026-02-28')
        details=build_statements(self.bundle,as_of='2026-02-28',period_start='2026-02-01')
        build(details,self.out,data_root=self.root)
        wb=load_workbook(self.out)
        row=next(r for r in wb['Accounts'].iter_rows(min_row=4,values_only=True) if r[0]=='re:synthetic')
        self.assertEqual(row[4],2300);wb.close()
        self.assertEqual(details['net_worth']['bridge']['valuation_change_minor'],30000)


if __name__=='__main__':unittest.main()
