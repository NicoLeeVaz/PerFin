"""Setup location checks, environment check, review CLI and static safety checks."""
import ast
import io
import json
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src" / "perfin_store"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import synthetic as S  # noqa: E402
import windows_acceptance  # noqa: E402
from fake_access import new_fake_store  # noqa: E402
from perfin_store import __main__ as cli  # noqa: E402
from perfin_store import envcheck, setup  # noqa: E402


def quiet(fn, *a, **kw):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fn(*a, **kw)
    return code, out.getvalue(), err.getvalue()


class SetupLocation(unittest.TestCase):
    def test_refuses_paths_inside_a_git_checkout(self):
        for p in (ROOT / "perfin.accdb", ROOT / "access" / "perfin.accdb", ROOT / "x" / "y" / "perfin.accdb"):
            code, _, err = quiet(setup.main, ["--create", str(p)])
            self.assertEqual(code, setup.EXIT_REFUSED, p)
            self.assertIn("inside git checkout", err)
            self.assertFalse(p.exists())
        self.assertFalse((ROOT / "x").exists())

    def test_refuses_alias_into_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / "alias"
            link.symlink_to(ROOT, target_is_directory=True)
            code, _, err = quiet(setup.main, ["--create", str(link / "perfin.accdb")])
            self.assertEqual(code, setup.EXIT_REFUSED)

    def test_sync_folder_needs_acknowledgement(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Dropbox" / "perfin.accdb"
            code, _, err = quiet(setup.main, ["--create", str(p)])
            self.assertEqual(code, setup.EXIT_REFUSED)
            self.assertIn("acknowledge", err)
            code, _, err = quiet(setup.main, ["--create", str(p), "--acknowledge-location"])
            self.assertNotEqual(code, setup.EXIT_REFUSED)

    def test_other_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(quiet(setup.main, ["--create", str(Path(d) / "perfin.mdb")])[0], setup.EXIT_REFUSED)
            existing = Path(d) / "perfin.accdb"
            existing.write_bytes(b"")
            self.assertEqual(quiet(setup.main, ["--create", str(existing)])[0], setup.EXIT_REFUSED)

    @unittest.skipIf(sys.platform == "win32", "Linux behaviour")
    def test_unsupported_platform_after_checks(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "db" / "perfin.accdb"
            code, _, err = quiet(setup.main, ["--create", str(p)])
            self.assertEqual(code, setup.EXIT_UNSUPPORTED)
            self.assertIn("unsupported platform", err)
            self.assertFalse(p.exists())

    def test_create_database_with_injected_fake_adapter(self):
        from fake_access import FakeAccessAdapter
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "db" / "perfin.accdb"
            report = setup.create_database(p, adapter_factory=lambda path, **kw: FakeAccessAdapter(path=path),
                                           now="2026-11-04T00:00:00Z")
            self.assertEqual(report["opened"], {"schema_version": "1.0.0", "blocked": False})
            self.assertFalse(p.with_suffix(".laccdb").exists())  # closed after setup


class EnvCheck(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "Linux behaviour")
    def test_unsupported_platform_reported_cleanly(self):
        code, out, err = quiet(envcheck.main, ["--json"])
        self.assertEqual(code, envcheck.EXIT_UNSUPPORTED)
        report = json.loads(out)
        self.assertEqual(report["status"], "unsupported platform")
        self.assertIn(report["python"]["bits"], (32, 64))
        self.assertEqual(err, "")
        code, out, _ = quiet(envcheck.main, [])
        self.assertIn("unsupported platform", out)

    def test_no_network_calls(self):
        def boom(*a, **kw):
            raise AssertionError("network call attempted")
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom):
            quiet(envcheck.main, ["--json"])


class ReviewCli(unittest.TestCase):
    def setUp(self):
        self.repo, self.ad, _ = new_fake_store()
        self.repo.import_bundle(S.reference_bundle())
        self.repo.set_default_categories("exp.uncategorized", "inc.uncategorized")
        self.repo.stage_batch(S.card_batch())
        self.open = lambda path, **kw: self.repo

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stderr(io.StringIO()):
            code = cli.main(list(args), open_repo=self.open, out=out)
        self.ad.closed = False  # the CLI closes its connection; the fake is reused across calls
        return code, out.getvalue()

    def test_queue_then_approve_reject_resolve_commit(self):
        code, out = self.cli("review", "--db", "x.accdb", "--batch", "b.alpha.07")
        self.assertEqual(code, 0)
        self.assertIn("E_PARSE_AMOUNT", out)
        self.assertIn("-12.34", out)
        code, out = self.cli("review", "--db", "x.accdb", "--batch", "b.alpha.07", "--approve", "1,2,3,6",
                             "--reject", "4", "--reason", "unparseable", "--resolve", "5=confirmed_duplicate")
        self.assertEqual(code, 0, out)
        code, out = self.cli("review", "--db", "x.accdb", "--batch", "b.alpha.07", "--reject", "5", "--reason", "dup",
                             "--commit", "--json")
        self.assertEqual(code, 0, out)
        self.assertIn('"result_status": "accepted"', out)
        self.assertEqual(len(self.repo.export_bundle()["transactions"]), 4)
        code, out = self.cli("review", "--db", "x.accdb", "--batch", "b.alpha.07", "--commit", "--json")
        self.assertEqual(code, 1)
        self.assertIn("E_IDEMPOTENT_REPLAY", out)

    def test_failed_action_stops(self):
        code, out = self.cli("review", "--db", "x.accdb", "--batch", "b.alpha.07", "--approve", "4")
        self.assertEqual(code, 1)
        self.assertIn("E_ROW_UNRESOLVED", out)

    def test_export_bundle(self):
        code, out = self.cli("export-bundle", "--db", "x.accdb")
        self.assertEqual(json.loads(out)["document_type"], "ledger_bundle")


class StaticSafety(unittest.TestCase):
    def modules(self):
        return {p.name: ast.parse(p.read_text(encoding="utf-8")) for p in SRC.glob("*.py")}

    def imports(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                yield from (a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                yield node.module.split(".")[0]

    def test_no_network_or_alternate_database_modules(self):
        banned = {"socket", "http", "urllib", "requests", "ftplib", "smtplib", "sqlite3", "dbm", "shelve"}
        for name, tree in self.modules().items():
            self.assertFalse(banned & set(self.imports(tree)), name)

    def test_vba_and_powershell_have_no_network_calls(self):  # privacy checklist N1
        for p in (ROOT / "access" / "setup").iterdir():
            text = p.read_text(encoding="utf-8").lower()
            for token in ("xmlhttp", "winhttp", "urldownloadtofile", "internetopen", "followhyperlink", "outlook.application",
                          "invoke-webrequest", "invoke-restmethod", "net.webclient", "start-bitstransfer"):
                self.assertNotIn(token, text, (p.name, token))

    def test_pyodbc_only_lazily_in_adapter_and_envcheck(self):
        for name, tree in self.modules().items():
            top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
            self.assertFalse(any("pyodbc" in ast.dump(n) for n in top), name)
            if name not in ("adapter.py", "envcheck.py"):
                self.assertNotIn("pyodbc", set(self.imports(tree)), name)

    def test_no_floats_for_money(self):
        for name, tree in self.modules().items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float":
                    self.fail("float() call in %s" % name)

    def test_no_committed_databases_or_csv(self):
        for pattern in ("*.accdb", "*.mdb", "*.laccdb", "*.csv", "*.bak"):
            for base in (ROOT / "access", ROOT / "tests" / "store", ROOT / "src" / "perfin_store", ROOT / "docs" / "access"):
                self.assertEqual(list(base.rglob(pattern)), [], (base, pattern))

    @unittest.skipIf(sys.platform == "win32", "Linux behaviour")
    def test_windows_acceptance_reports_blocked_here(self):
        code, out, _ = quiet(windows_acceptance.main, [])
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", out)


if __name__ == "__main__":
    unittest.main()
