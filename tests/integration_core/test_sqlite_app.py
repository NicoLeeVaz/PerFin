"""Real SQLite CLI workflows; these checks require no Office or fake adapter."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from scenario import ROOT, two_cycles
from perfin_app.__main__ import main
from perfin_app.backends import select_backend
from perfin_app.paths import initialize_layout
from perfin_app.service import WorkflowError


@unittest.skipUnless(os.name == 'posix', 'POSIX permission checks')
class PrivateDataRoot(unittest.TestCase):
    def test_new_root_is_private_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory(prefix='perfin-private-root-') as temp:
            previous = os.umask(0o022)
            try:
                root = initialize_layout(Path(temp) / 'new-data', synthetic=True)
            finally:
                os.umask(previous)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertTrue((root / 'perfin-data-dir.json').is_file())

    def test_existing_user_folder_permissions_are_preserved(self):
        with tempfile.TemporaryDirectory(prefix='perfin-existing-root-') as temp:
            root = Path(temp) / 'existing'
            root.mkdir()
            root.chmod(0o750)
            initialize_layout(root, synthetic=True)
            self.assertEqual(root.stat().st_mode & 0o777, 0o750)


class BackendSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='perfin-backend-selection-')
        self.addCleanup(self.temp.cleanup)
        self.root = initialize_layout(self.temp.name, synthetic=True)

    def test_new_root_defaults_to_sqlite_without_creating_database(self):
        selected = select_backend(self.root)
        self.assertEqual(selected.backend, 'sqlite')
        self.assertEqual(selected.path, self.root / 'db/perfin.sqlite')
        self.assertFalse(selected.path.exists())

    def test_legacy_access_root_remains_access(self):
        (self.root / 'db/perfin.accdb').write_text('SYNTHETIC placeholder, never opened')
        self.assertEqual(select_backend(self.root).backend, 'access')
        with self.assertRaisesRegex(WorkflowError, 'already uses access'):
            select_backend(self.root, 'sqlite')
        self.assertFalse((self.root / 'db/perfin.sqlite').exists())

    def test_two_backend_files_are_refused_even_with_explicit_selection(self):
        for name in ('perfin.accdb', 'perfin.sqlite'):
            (self.root / 'db' / name).write_text('SYNTHETIC placeholder, never opened')
        with self.assertRaisesRegex(WorkflowError, 'Both SQLite and Access'):
            select_backend(self.root, 'sqlite')

    def test_marker_mismatch_and_unknown_backend_refused(self):
        marker = self.root / 'perfin-data-dir.json'
        for body in ({'app': 'PerFin', 'backend': 'other'},
                     {'app': 'PerFin', 'backend': 'sqlite', 'database': '../outside.sqlite3'},
                     [], {'app': 'another-app'}):
            with self.subTest(body=body):
                marker.write_text(json.dumps(body))
                with self.assertRaises(WorkflowError):
                    select_backend(self.root)


class SQLiteCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='perfin-sqlite-cli-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'

    def cli(self, *arguments, expected=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--data-root', str(self.root), *arguments])
        self.assertEqual(code, expected, err.getvalue() or out.getvalue())
        return json.loads(out.getvalue()) if code == 0 else err.getvalue()

    def test_init_persists_sqlite_and_does_not_switch_to_access(self):
        self.cli('init', '--demo')
        marker = json.loads((self.root / 'perfin-data-dir.json').read_text())
        self.assertEqual((marker['backend'], marker['database']), ('sqlite', 'db/perfin.sqlite'))
        self.assertEqual(self.cli('status')['account_balances_minor']['chk:main'], 250000)
        self.assertFalse((self.root / 'db/perfin.accdb').exists())
        before = (self.root / 'db/perfin.sqlite').read_bytes()
        self.assertIn('already uses sqlite', self.cli('--backend', 'access', 'status', expected=2))
        self.cli('init', '--demo', expected=2)
        self.assertEqual((self.root / 'db/perfin.sqlite').read_bytes(), before)

    def test_cli_import_review_commit_replay_refresh_and_statements(self):
        self.cli('init', '--demo')
        source = Path(self.temp.name) / 'synthetic.csv'
        source.write_text('Date,Description,Amount,Balance,Transaction ID\n'
                          '02/01/2026,SYNTHETIC SHOP,-50.00,,syn-a\n'
                          '02/02/2026,SYNTHETIC REFUND,20.00,,syn-b\n')
        first = self.cli('import', str(source), '--account', 'chk:main', '--profile', 'synthetic_checking_signed')
        batch = first['document']['batch']['batch_id']
        self.assertEqual(self.cli('status')['account_balances_minor']['chk:main'], 250000)
        self.cli('review', batch, '--approve', '1,2')
        self.cli('commit', batch)
        summary = self.cli('status')
        self.assertEqual(summary['account_balances_minor']['chk:main'], 247000)
        replay = self.cli('import', str(source), '--account', 'chk:main', '--profile', 'synthetic_checking_signed')
        self.assertEqual(replay['result_status'], 'replayed')
        self.assertEqual(self.cli('status'), summary)
        refreshed = self.cli('refresh', '--as-of', '2026-02-28')
        self.assertTrue(Path(refreshed['workbook']).is_file())
        self.cli('statements', '--as-of', '2026-02-28', '--period-start', '2026-02-01')
        self.assertTrue((self.root / 'workbooks/excel_statements/PerFin-Statements.xlsx').is_file())
        self.cli('snapshot')
        bundle = json.loads((self.root / 'exports/ledger.json').read_text())
        self.assertEqual(len(bundle['transactions']), 2)

    def test_sqlite_backup_restore_and_reopen_preserves_summary(self):
        from perfin_store.sqlite_backend import open_database
        self.cli('init', '--demo')
        summary = self.cli('status')
        backup_set = self.cli('backup')['backup_set']
        self.cli('restore', backup_set, '--target', 'db/restored.accdb', expected=2)
        self.assertFalse((self.root / 'db/restored.accdb').exists())
        self.cli('restore', backup_set, '--target', 'db/restored.sqlite3')
        restored = open_database(self.root / 'db/restored.sqlite3')
        try:
            self.assertEqual(restored.summary(), summary)
        finally:
            restored.adapter.close()
        self.assertEqual(self.cli('status'), summary)

    def test_payoff_parameters_persist_without_changing_ledger(self):
        from perfin_store.sqlite_backend import open_database
        self.cli('init', '--demo')
        before = self.cli('status')
        scenario_path = ROOT / 'fixtures/payoff/scenario.synthetic.json'
        scenario = json.loads(scenario_path.read_text())['scenario']
        result = self.cli('payoff', str(scenario_path))
        self.assertTrue(Path(result['workbook']).is_file())
        repo = open_database(self.root / 'db/perfin.sqlite')
        try:
            self.assertEqual(repo.payoff_scenario(scenario['scenario_id'])['scenario'], scenario)
        finally:
            repo.adapter.close()
        self.assertEqual(self.cli('status'), before)

    def test_corrupt_sqlite_file_is_refused_without_traceback_or_fallback(self):
        root = initialize_layout(self.root, synthetic=True)
        (root / 'db/perfin.sqlite').write_text('SYNTHETIC invalid database')
        error = self.cli('status', expected=2)
        self.assertIn('SQLite database operation failed', error)
        self.assertNotIn('Traceback', error)
        self.assertFalse((root / 'db/perfin.accdb').exists())

    def test_two_cycles_run_on_real_sqlite(self):
        from perfin_store.sqlite_backend import create_database, open_database
        root = initialize_layout(self.root, synthetic=True)
        create_database(root / 'db/perfin.sqlite')
        repo = open_database(root / 'db/perfin.sqlite')
        try:
            app, expected = two_cycles(repo, root)
            self.assertEqual(repo.summary()['account_balances_minor'], expected)
            self.assertEqual(len(repo.summary()['reconciliations']), 6)
            self.assertTrue(Path(app.refresh('2026-03-28')['workbook']).is_file())
        finally:
            repo.adapter.close()

    def test_sqlite_envcheck_has_no_ace_requirement(self):
        result = self.cli('envcheck')
        self.assertEqual(result['backend'], 'sqlite')
        self.assertEqual(result['native_access_excel'], 'not checked')
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
