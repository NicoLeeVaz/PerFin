"""Release tools must not hide failures or accidentally package runtime data."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location('release_' + name, ROOT / 'scripts/release' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_all = load('check_all')
package = load('package')
windows = load('windows_acceptance')


class ReleaseTools(unittest.TestCase):
    def test_earlier_failure_cannot_be_hidden_by_later_pass(self):
        fake_commands = [('fails', ['first']), ('passes', ['second'])]
        outcomes = [subprocess.CompletedProcess(['first'], 1, '', 'Ran 2 tests\nFAILED\n'),
                    subprocess.CompletedProcess(['second'], 0, '', 'Ran 3 tests\nOK\n')]
        with tempfile.TemporaryDirectory() as d, patch.object(check_all, 'commands', return_value=fake_commands), \
             patch.object(check_all.subprocess, 'run', side_effect=outcomes), contextlib.redirect_stdout(io.StringIO()):
            report = Path(d) / 'evidence.json'
            self.assertEqual(check_all.main(['--report', str(report)]), 1)
            result = json.loads(report.read_text())
            self.assertEqual(result['result'], 'FAIL')
            self.assertEqual(result['tests_run'], 5)
            self.assertEqual([x['status'] for x in result['checks']], ['FAIL', 'PASS'])

    def test_offline_guard_blocks_socket_before_connection(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'sitecustomize.py').write_text(check_all.NETWORK_GUARD)
            import os
            env = dict(os.environ, PYTHONPATH=d)
            result = subprocess.run([sys.executable, '-B', '-c',
                'import socket; socket.socket().connect(("127.0.0.1", 9))'], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('PerFin acceptance: Python network access disabled', result.stderr)

    def test_required_empty_suite_blocks_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'tests/empty').mkdir(parents=True)
            with self.assertRaises(ValueError):
                check_all.commands(root, ['tests/empty'])

    def test_source_zip_is_byte_reproducible_and_rejects_private_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'a.py').write_text('print("synthetic")\n')
            (root / 'README.md').write_text('Synthetic package\n')
            first, second = root / 'one.zip', root / 'two.zip'
            package.source_zip(root, ['a.py', 'README.md'], first)
            package.source_zip(root, ['README.md', 'a.py'], second)
            self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
            for name in ['db/private.accdb', 'book.xlsx', 'statement.pdf', '../escape.py', '.env', 'backups/file.json']:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    package.check_source_path(name)

    def test_unrun_manual_checks_never_pass_release(self):
        revision = 'reviewed-revision'
        self.assertEqual(windows.check_manual(None, revision)[0], 'BLOCKED')
        doc = {'revision': revision, 'operator': 'synthetic operator', 'windows_version': 'test',
               'office_bitness': '64', 'excel_build': 'test', 'checks': {k: 'PASS' for k in windows.REQUIRED_MANUAL}}
        self.assertEqual(windows.check_manual(doc, 'another-revision')[0], 'BLOCKED')
        doc['checks']['core_offline_refresh'] = 'PENDING'
        self.assertEqual(windows.check_manual(doc, revision)[0], 'BLOCKED')
        doc['checks']['core_offline_refresh'] = 'FAIL'
        self.assertEqual(windows.check_manual(doc, revision)[0], 'FAIL')
        doc['checks']['core_offline_refresh'] = 'PASS'
        self.assertEqual(windows.check_manual(doc, revision)[0], 'PASS')

    @unittest.skipIf(sys.platform == 'win32', 'non-Windows refusal only')
    def test_windows_runner_explicitly_blocks_on_other_platforms(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(windows.main([]), 2)


if __name__ == '__main__':
    unittest.main()
