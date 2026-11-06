import importlib.util
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
import zipfile
from unittest.mock import patch
from openpyxl import Workbook
ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT / "src", ROOT / "excel/core", ROOT / "contracts/python"):
    sys.path.insert(0, str(source))
from perfin_excel_core.registry import scan

spec = importlib.util.spec_from_file_location('extra_register', ROOT / 'extras/register.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Registration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='perfin-extra-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / 'source.xlsx'
        self.save('=PMT(0.06/12,360,-100000)')

    def save(self, value):
        wb = Workbook(); wb.active['A1'] = value; wb.save(self.file); wb.close()

    def evidence(self):
        return dict(sha256=module.inspect_bytes(self.file.read_bytes())['sha256'],
                    source_url='https://example.com/template', license='Synthetic test',
                    license_reviewed=True, synthetic_math_checked=True,
                    desktop_offline_checked=True, tested_environment='TEST ONLY',
                    reviewed_by='fixture', notes='Synthetic evidence, not a real native pass')

    def test_registers_exact_bytes_with_no_ledger_access_and_registry_compatibility(self):
        before = self.file.read_bytes()
        with patch('socket.create_connection', side_effect=AssertionError('no network')):
            dest = Path(module.register(self.file, self.root/'data', 'extra_loan', self.evidence()))
        self.assertEqual((dest/'Workbook.xlsx').read_bytes(), before)
        entry = scan(dest.parent)[0]
        self.assertTrue(entry['launchable'])
        manifest = json.loads((dest/'module_manifest.json').read_text())
        self.assertFalse(manifest['writes_ledger'])
        self.assertEqual(manifest['reads'], [])
        self.assertFalse((self.root/'data/db').exists())

    def test_hash_change_blocks_registration(self):
        evidence = self.evidence(); self.save(12)
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            module.register(self.file, self.root/'data', 'extra_loan', evidence)

    def test_all_operator_checks_required_as_booleans(self):
        for field in ['license_reviewed','synthetic_math_checked','desktop_offline_checked']:
            evidence = self.evidence(); evidence[field] = 'true'
            with self.assertRaises(ValueError):
                module.register(self.file, self.root/'data', 'extra_loan', evidence)

    def test_cannot_overwrite_existing_module(self):
        module.register(self.file, self.root/'data', 'extra_loan', self.evidence())
        with self.assertRaises(ValueError):
            module.register(self.file, self.root/'data', 'extra_loan', self.evidence())

    def test_cannot_duplicate_module_identity_in_another_folder(self):
        dest=Path(module.register(self.file,self.root/'data','extra_loan',self.evidence()))
        dest.rename(dest.parent/'renamed')
        with self.assertRaisesRegex(ValueError,'another folder'):
            module.register(self.file,self.root/'data','extra_loan',self.evidence())

    def test_rejects_remote_formulas_and_hyperlinks(self):
        self.save('=WEBSERVICE("https://example.com")')
        self.assertFalse(module.inspect_bytes(self.file.read_bytes())['static_clean'])
        wb=Workbook(); wb.active['A1']='Publisher'; wb.active['A1'].hyperlink='https://example.com'
        wb.save(self.file);wb.close()
        self.assertFalse(module.inspect_bytes(self.file.read_bytes())['static_clean'])

    def test_rejects_macro_and_connection_packages(self):
        raw=self.file.read_bytes()
        for name in ['xl/vbaProject.bin','xl/connections.xml','xl/macrosheets/sheet1.xml','customXml/item1.xml']:
            data=io.BytesIO(raw)
            with zipfile.ZipFile(data,'a') as z:z.writestr(name,b'fake')
            with self.assertRaises(ValueError):module.inspect_bytes(data.getvalue())

    def test_refuses_paths_and_symlink_escape(self):
        for name in ['../escape','excel_payoff','extra_../bad']:
            with self.assertRaises(ValueError):
                module.register(self.file,self.root/'data',name,self.evidence())
        (self.root/'data').mkdir(); (self.root/'outside').mkdir()
        (self.root/'data/workbooks').symlink_to(self.root/'outside',target_is_directory=True)
        with self.assertRaises(ValueError):
            module.register(self.file,self.root/'data','extra_loan',self.evidence())
        self.assertEqual(list((self.root/'outside').iterdir()),[])

    def test_refuses_non_xlsx_and_oversized_bytes(self):
        with self.assertRaises(ValueError):module.read_workbook(self.root/'source.xlsm')
        with patch.object(module,'MAX_BYTES',10):
            with self.assertRaises(ValueError):module.read_workbook(self.file)

    def test_catalog_is_link_only_and_default_off(self):
        catalog=json.loads((ROOT/'extras/catalog.json').read_text())
        ids=[x['id'] for x in catalog['tools']]
        self.assertEqual(len(ids),len(set(ids)))
        for tool in catalog['tools']:
            self.assertFalse(tool['enabled_by_default'])
            self.assertFalse(tool['binary_verified'])
            self.assertTrue(tool['url'].startswith('https://'))
            self.assertTrue(tool['license'])


if __name__ == '__main__':unittest.main()
