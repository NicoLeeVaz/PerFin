"""Synthetic integration with the real SQLite engine and existing XLSX generators."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("portable_demo", ROOT / "scripts/core/portable_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class PortableDemo(unittest.TestCase):
    def test_real_sqlite_two_cycles_and_three_workbooks_without_network(self):
        with tempfile.TemporaryDirectory(prefix="perfin-portable-") as directory:
            root = Path(directory) / "demo"
            with patch("socket.create_connection", side_effect=AssertionError("network prohibited")):
                evidence = demo.run_demo(root)
            self.assertEqual(evidence["result"], "PASS", evidence.get("error"))
            self.assertEqual(evidence["native_excel"], "PENDING")
            self.assertEqual(evidence["native_access"], "PENDING")
            self.assertTrue(all(c["status"] == "PASS" for c in evidence["checks"]))
            self.assertEqual(evidence["summary"], {
                "account_balances_minor": {"chk:main": 234000, "card:a": -17600, "card:b": -6200},
                "net_worth_minor": 210200, "reconciliations": 6, "transaction_count": 16})
            self.assertEqual(len(evidence["artifacts"]), 3)
            for artifact in evidence["artifacts"]:
                self.assertEqual(hashlib.sha256((root / artifact["path"]).read_bytes()).hexdigest(), artifact["sha256"])
            self.assertEqual(json.loads((root / "portable-demo-evidence.json").read_text()), evidence)
            self.assertIn("Desktop Excel recalculation", (root / "index.html").read_text())
            with sqlite3.connect(root / "db/perfin.sqlite") as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM reconciliation").fetchone(), (6,))
                self.assertGreater(connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 0)
            # A second run must not silently reset the database or replace artifacts.
            before = (root / "db/perfin.sqlite").read_bytes()
            with self.assertRaises(FileExistsError):
                demo.run_demo(root)
            self.assertEqual((root / "db/perfin.sqlite").read_bytes(), before)

    def test_refuses_repo_and_existing_content_before_writing(self):
        with self.assertRaises(ValueError):
            demo.run_demo(ROOT / "forbidden-demo-output")
        self.assertFalse((ROOT / "forbidden-demo-output").exists())
        with tempfile.TemporaryDirectory(prefix="perfin-portable-refusal-") as directory:
            root = Path(directory)
            sentinel = root / "private.txt"
            sentinel.write_text("leave existing user content alone")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(demo.main(["--out", str(root)]), 2)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["private.txt"])
            self.assertEqual(sentinel.read_text(), "leave existing user content alone")

    def test_failed_workbook_step_records_failure_and_never_claims_pass(self):
        with tempfile.TemporaryDirectory(prefix="perfin-portable-failure-") as directory:
            root = Path(directory) / "demo"
            with patch.object(demo.FinanceApp, "refresh", side_effect=RuntimeError("synthetic refresh failure")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(demo.main(["--out", str(root)]), 1)
            evidence = json.loads((root / "portable-demo-evidence.json").read_text())
            self.assertEqual(evidence["result"], "FAIL")
            self.assertEqual(evidence["error"]["message"], "synthetic refresh failure")
            self.assertFalse((root / "index.html").exists())
            self.assertEqual(evidence["native_excel"], "PENDING")


if __name__ == "__main__":
    unittest.main()
