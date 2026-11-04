"""Backup/restore logic with a fake database file (the test-only fake saved as JSON).

Proves the quiescence checks, SHA-256 manifest verification and the restore comparison logic.
The real Access copy/lock behaviour is checked only by windows_acceptance.py.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import synthetic as S  # noqa: E402
from fake_access import FakeAccessAdapter, new_fake_store  # noqa: E402
from perfin_store import backup, migrations  # noqa: E402
from perfin_store.repository import Repository  # noqa: E402


def open_summary(path):
    repo = Repository(FakeAccessAdapter(path=str(path)))
    try:
        return repo.summary()
    finally:
        repo.adapter.close()


class BackupRestore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="perfin-store-test-"))
        self.db = self.tmp / "data" / "db" / "perfin.accdb"
        self.db.parent.mkdir(parents=True)
        repo, ad, _ = new_fake_store(path=str(self.db))
        repo.import_bundle(S.reference_bundle())
        repo.set_default_categories("exp.uncategorized", "inc.uncategorized")
        b = S.batch("b.chk", "chk:main", [S.row(1, "2026-06-02", -4321, "x", state="approved")])
        repo.stage_batch(b)
        repo.execute(S.command("commit_batch", {"batch_id": "b.chk", "source_file_sha256": b["batch"]["source_file_sha256"]},
                               [S.ev("batch", "b.chk", 2)]))
        repo.execute(S.command("record_statement", {"statement_id": "st1", "account_id": "chk:main", "period_start": "2026-06-01",
                                                    "period_end": "2026-06-30", "opening_balance_minor": 250000,
                                                    "closing_balance_minor": 245679, "evidence_ref": "sha256:" + "b" * 64}))
        self.repo, self.ad = repo, ad
        self.summary = repo.summary()
        self.dest = self.tmp / "backups"

    def tearDown(self):
        if not self.ad.closed:
            self.ad.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def backup(self, **kw):
        return backup.create_backup(self.db, self.dest, summary=self.summary, **kw)

    def test_refused_while_open_then_succeeds(self):
        with self.assertRaisesRegex(backup.BackupError, "lock file"):
            self.backup()
        self.assertFalse(self.dest.exists() and any(self.dest.iterdir()))
        self.ad.close()
        with self.assertRaisesRegex(backup.BackupError, "exclusively"):
            self.backup(probe=lambda p: False)
        set_dir = self.backup()
        self.assertEqual(backup.verify_backup(set_dir), [])
        m = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["files"][0]["sha256"], backup.sha256_file(self.db))
        self.assertEqual(m["schema_version"], "1.0.0")
        self.assertEqual(m["ledger_summary"]["account_balances_minor"]["chk:main"], 245679)

    def test_manifest_verification_detects_tampering(self):
        self.ad.close()
        set_dir = self.backup()
        copy = set_dir / "db" / "perfin.accdb"
        original = copy.read_bytes()
        copy.write_bytes(original[:-1] + b"X")
        self.assertTrue(any("hash mismatch" in p for p in backup.verify_backup(set_dir)))
        copy.write_bytes(original + b" ")
        self.assertTrue(any("size mismatch" in p for p in backup.verify_backup(set_dir)))
        copy.write_bytes(original)
        (set_dir / "stray.txt").write_text("x", encoding="utf-8")
        self.assertTrue(any("unlisted" in p for p in backup.verify_backup(set_dir)))
        (set_dir / "stray.txt").unlink()
        m = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
        m["files"].append({"path": "../outside", "size": 1, "sha256": "0" * 64})
        (set_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        self.assertTrue(any("unsafe path" in p for p in backup.verify_backup(set_dir)))
        (set_dir / "manifest.json").unlink()
        self.assertTrue(backup.verify_backup(set_dir))

    def test_fake_file_manifest_round_trip(self):
        fake = self.tmp / "fake" / "x.accdb"
        fake.parent.mkdir()
        fake.write_bytes(b"not really an accdb, synthetic bytes only")
        set_dir = backup.create_backup(fake, self.dest, summary={"schema_version": "1.0.0", "contract_version": "1.0.0"})
        self.assertEqual(backup.verify_backup(set_dir), [])
        self.assertEqual(json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))["files"][0]["size"], 41)

    def test_destination_privacy_rules(self):
        self.ad.close()
        with self.assertRaisesRegex(backup.BackupError, "inside git checkout"):
            backup.create_backup(self.db, ROOT / "backups-here", summary=self.summary)
        self.assertFalse((ROOT / "backups-here").exists())
        with self.assertRaisesRegex(backup.BackupError, "acknowledgement"):
            backup.create_backup(self.db, self.tmp / "OneDrive" / "b", summary=self.summary)
        set_dir = backup.create_backup(self.db, self.tmp / "OneDrive" / "b", summary=self.summary, acknowledge_location=True)
        self.assertTrue(set_dir.exists())

    def test_restore_matches_balances_history_and_version(self):
        self.ad.close()
        set_dir = self.backup()
        target = self.tmp / "restore" / "perfin-restored.accdb"
        res = backup.restore_backup(set_dir, target, open_summary=open_summary)
        self.assertEqual(res["schema_version"], "1.0.0")
        restored = open_summary(target)
        self.assertEqual(restored["import_history"], self.summary["import_history"])
        self.assertEqual(restored["account_balances_minor"], self.summary["account_balances_minor"])
        with self.assertRaisesRegex(backup.BackupError, "new path"):
            backup.restore_backup(set_dir, target, open_summary=open_summary)

    def test_restore_stops_on_bad_hash_before_writing(self):
        self.ad.close()
        set_dir = self.backup()
        (set_dir / "db" / "perfin.accdb").write_bytes(b"corrupt")
        target = self.tmp / "restore" / "r.accdb"
        with self.assertRaisesRegex(backup.BackupError, "nothing was restored"):
            backup.restore_backup(set_dir, target, open_summary=open_summary)
        self.assertFalse(target.exists())

    def test_restore_mismatch_removes_copy(self):
        self.ad.close()
        summary = dict(self.summary, account_balances_minor={"chk:main": 1})
        set_dir = backup.create_backup(self.db, self.dest, summary=summary)
        target = self.tmp / "restore" / "r.accdb"
        with self.assertRaisesRegex(backup.BackupError, "account_balances_minor"):
            backup.restore_backup(set_dir, target, open_summary=open_summary)
        self.assertFalse(target.exists())

    def test_restore_refuses_newer_major_and_in_repo_target(self):
        self.ad.close()
        set_dir = backup.create_backup(self.db, self.dest, summary=dict(self.summary, schema_version="2.0.0"))
        with self.assertRaises(migrations.SchemaVersionError):
            backup.restore_backup(set_dir, self.tmp / "r" / "x.accdb", open_summary=open_summary)
        good = backup.create_backup(self.db, self.tmp / "b2", summary=self.summary)
        with self.assertRaisesRegex(backup.BackupError, "inside git checkout"):
            backup.restore_backup(good, ROOT / "restored.accdb", open_summary=open_summary)
        self.assertFalse((ROOT / "restored.accdb").exists())

    def test_statements_are_references_not_attachments(self):
        cols = [c for c in self.repo._rows("statement")[0]]
        self.assertIn("evidence_ref", cols)
        self.assertEqual(self.summary["statements"][0]["evidence_ref"], "sha256:" + "b" * 64)


if __name__ == "__main__":
    unittest.main()
