"""Real SQLite persistence, backup and full-history round trips (no fake adapter)."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests/store")]
import synthetic as S
from perfin_store import ddl, portability, sqlite_backup
from perfin_store.sqlite_backend import create_database, open_database
from perfin_store.migrations import SchemaVersionError
from perfin_store.backup import BackupError


class RealStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="perfin-portability-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "finance.sqlite"
        create_database(self.path)
        self.repo = open_database(self.path)
        self.addCleanup(lambda: self.repo.adapter.close())
        self.ok(self.repo.import_bundle(S.reference_bundle()))
        self.ok(self.repo.set_default_categories("exp.uncategorized", "inc.uncategorized"))
        staged = S.batch("b.pending", "chk:main", [S.row(1, "2026-07-01", -50, "SYNTHETIC pending")])
        self.ok(self.repo.stage_batch(staged))
        committed = S.batch("b.committed", "chk:main", [S.row(1, "2026-07-02", -1234, "SYNTHETIC committed",
                                                            state="approved", source_txn_id="bank-1")])
        self.ok(self.repo.stage_batch(committed))
        version = self.repo._one("import_batch", {"batch_id": "b.committed"})["row_version"]
        self.ok(self.repo.execute(S.command("commit_batch", {"batch_id": "b.committed",
                            "source_file_sha256": committed["batch"]["source_file_sha256"]},
                            [S.ev("batch", "b.committed", version)])))

    def ok(self, response):
        self.assertEqual(response["result_status"], "accepted", response["errors"])

    def rows(self, repo=None):
        repo = repo or self.repo
        return {name: repo._rows(name, order_by=list(table.primary_key)) for name, table in ddl.registry().items()}

    def backup(self):
        return sqlite_backup.create_backup(self.path, self.root / "backups")

    def archive(self):
        target = self.root / "archive.json"
        portability.export_snapshot(self.path, target)
        return target


class Backup(RealStore):
    @unittest.skipUnless(os.name == "posix", "POSIX permission mode test")
    def test_backups_archives_and_restores_keep_owner_only_permissions(self):
        previous = os.umask(0o022)
        try:
            backup_set = self.backup()
            archive = self.archive()
            target = self.root / "private.sqlite"
            sqlite_backup.restore_backup(backup_set, target)
        finally:
            os.umask(previous)
        self.assertEqual(backup_set.stat().st_mode & 0o777, 0o700)
        for path in (archive, target, backup_set / "manifest.json", backup_set / sqlite_backup.DATABASE_NAME):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, path)

    def test_live_wal_backup_and_restore_preserve_all_tables(self):
        self.repo.adapter.query("PRAGMA journal_mode = WAL")
        self.ok(self.repo.set_default_categories("exp.groceries", "inc.salary"))
        self.assertTrue(Path(str(self.path) + "-wal").exists())
        expected = self.rows()
        backup_set = self.backup()
        self.assertEqual(sqlite_backup.verify_backup(backup_set), [])
        target = self.root / "restored.sqlite"
        sqlite_backup.restore_backup(backup_set, target)
        reopened = open_database(target)
        try:
            self.assertEqual(self.rows(reopened), expected)
            self.assertEqual(reopened.summary(), self.repo.summary())
        finally:
            reopened.adapter.close()

    def test_uncommitted_wal_changes_are_not_captured(self):
        self.repo.adapter.query("PRAGMA journal_mode = WAL")
        self.repo.adapter.begin()
        self.repo.adapter.execute("INSERT INTO [category] ([category_id], [name], [category_kind]) VALUES (?, ?, ?)",
                                  ("not.committed", "SYNTHETIC", "expense"))
        try:
            backup_set = self.backup()
        finally:
            self.repo.adapter.rollback()
        saved = open_database(backup_set / sqlite_backup.DATABASE_NAME)
        try:
            self.assertIsNone(saved._one("category", {"category_id": "not.committed"}))
        finally:
            saved.adapter.close()

    def test_hash_tamper_prevents_restore_before_target_creation(self):
        backup_set = self.backup()
        with (backup_set / sqlite_backup.DATABASE_NAME).open("ab") as stream:
            stream.write(b"tamper")
        target = self.root / "no.sqlite"
        self.assertTrue(sqlite_backup.verify_backup(backup_set))
        with self.assertRaises(BackupError):
            sqlite_backup.restore_backup(backup_set, target)
        self.assertFalse(target.exists())

    def test_manifest_summary_tamper_and_unlisted_files_are_refused(self):
        backup_set = self.backup()
        manifest_path = backup_set / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["ledger_summary"]["account_balances_minor"]["chk:main"] += 1
        manifest_path.write_text(json.dumps(manifest))
        self.assertIn("balances", "; ".join(sqlite_backup.verify_backup(backup_set)))
        (backup_set / "extra.txt").write_text("SYNTHETIC")
        self.assertIn("unlisted", "; ".join(sqlite_backup.verify_backup(backup_set)))

    def test_unsafe_manifest_path_and_existing_target_refused(self):
        backup_set = self.backup()
        target = self.root / "keep.sqlite"
        target.write_bytes(b"sentinel")
        with self.assertRaises(BackupError):
            sqlite_backup.restore_backup(backup_set, target)
        self.assertEqual(target.read_bytes(), b"sentinel")
        path = backup_set / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["database"]["path"] = "../finance.sqlite"
        path.write_text(json.dumps(manifest))
        self.assertTrue(sqlite_backup.verify_backup(backup_set))

    def test_stale_caller_summary_refuses_and_removes_backup_set(self):
        summary = self.repo.summary()
        summary["account_balances_minor"]["chk:main"] += 1
        with self.assertRaises(BackupError):
            sqlite_backup.create_backup(self.path, self.root / "backups", summary=summary)
        self.assertEqual(list((self.root / "backups").iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "POSIX symlink test")
    def test_restore_refuses_dangling_sidecar_links_without_touching_them(self):
        backup_set = self.backup()
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                target = self.root / ("dangling" + suffix + ".sqlite")
                sidecar = Path(str(target) + suffix)
                sidecar.symlink_to(self.root / "missing-private-file")
                with self.assertRaises(BackupError):
                    sqlite_backup.restore_backup(backup_set, target)
                self.assertFalse(target.exists())
                self.assertTrue(sidecar.is_symlink())

    def test_future_contract_backup_is_refused_and_partial_set_removed(self):
        self.repo.adapter.begin()
        self.repo.adapter.execute("UPDATE contract_meta SET meta_value = ? WHERE meta_key = ?",
                                  ("1.1.0", "contract_version"))
        self.repo.adapter.commit()
        with self.assertRaises(SchemaVersionError):
            self.backup()
        self.assertEqual(list((self.root / "backups").iterdir()), [])

    def test_restore_callback_mismatch_removes_target(self):
        backup_set = self.backup()
        target = self.root / "mismatch.sqlite"
        with self.assertRaises(BackupError):
            sqlite_backup.restore_backup(backup_set, target, open_summary=lambda path: {})
        self.assertFalse(target.exists())

    def test_restore_detects_audit_bytes_changed_after_verification(self):
        backup_set = self.backup()
        target = self.root / "changed.sqlite"
        real_copy = sqlite_backup.shutil.copyfile

        def corrupt_copy(source, destination):
            real_copy(source, destination)
            with sqlite3.connect(destination) as connection:
                connection.execute("UPDATE audit_log SET before_json = '{}'")

        with patch.object(sqlite_backup.shutil, "copyfile", side_effect=corrupt_copy):
            with self.assertRaisesRegex(BackupError, "SHA-256"):
                sqlite_backup.restore_backup(backup_set, target)
        self.assertFalse(target.exists())


class Archive(RealStore):
    @unittest.skipUnless(os.name == "posix", "POSIX symlink test")
    def test_import_refuses_dangling_sidecar_links_before_writing(self):
        archive = self.archive()
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                target = self.root / ("dangling" + suffix + ".sqlite")
                sidecar = Path(str(target) + suffix)
                sidecar.symlink_to(self.root / "missing-private-file")
                with self.assertRaises(portability.PortabilityError):
                    portability.import_snapshot(archive, target)
                self.assertFalse(target.exists())
                self.assertTrue(sidecar.is_symlink())

    def test_cli_exports_verifies_and_imports_using_database_alias(self):
        archive = self.root / "cli-history.json"
        target = self.root / "cli-restored.sqlite"
        commands = [
            ["export", "--db", str(self.path), "--out", str(archive)],
            ["verify", "--archive", str(archive)],
            ["import", "--archive", str(archive), "--db", str(target)],
        ]
        for arguments in commands:
            process = subprocess.run([sys.executable, "-B", "-m", "perfin_store.portability", *arguments],
                                     env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                                     capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout)
            self.assertNotIn("summary", result)
        reopened = open_database(target)
        try:
            self.assertEqual(self.rows(reopened), self.rows())
        finally:
            reopened.adapter.close()

    def test_future_sqlite_and_contract_minor_versions_refused_before_creation(self):
        for key, version in (("sqlite_schema_version", "999"), ("contract_version", "1.1.0")):
            with self.subTest(key=key):
                archive = self.archive()

                def edit(payload):
                    next(row for row in payload["tables"]["contract_meta"] if row["meta_key"] == key)["meta_value"] = version
                    if key == "contract_version":
                        payload["contract_version"] = version
                        payload["summary"]["contract_version"] = version

                self.alter(archive, edit, rehash=True)
                target = self.root / "unsupported.sqlite"
                with self.assertRaises(portability.PortabilityError):
                    portability.import_snapshot(archive, target)
                self.assertFalse(target.exists())
                archive.unlink()

    def test_failure_to_reopen_committed_import_removes_new_database(self):
        from perfin_store import sqlite_backend
        archive = self.archive()
        target = self.root / "reopen-failure.sqlite"
        calls = []

        def opening(path, **kwargs):
            calls.append(path)
            if len(calls) == 2:
                raise SchemaVersionError("SYNTHETIC final reopen failure")
            return open_database(path, **kwargs)

        with patch.object(sqlite_backend, "open_database", side_effect=opening):
            with self.assertRaises(SchemaVersionError):
                portability.import_snapshot(archive, target)
        self.assertEqual(len(calls), 2)
        self.assertFalse(target.exists())

    def test_all_history_and_forward_self_references_round_trip(self):
        # A child sorts before its parent; deferred foreign keys must preserve it.
        bundle = {"contract": "perfin", "contract_version": "1.0.1", "document_type": "ledger_bundle",
                  "base_currency": "USD", "accounts": [], "transactions": [], "categories": [
                      {"category_id": "z.parent", "name": "SYNTHETIC parent", "category_kind": "expense"},
                      {"category_id": "a.child", "name": "SYNTHETIC child", "category_kind": "expense",
                       "parent_category_id": "z.parent"}]}
        self.ok(self.repo.import_bundle(bundle))
        tid = "b.committed.r1"
        self.ok(self.repo.execute(S.command("reverse_transaction", {"transaction_id": tid,
                            "reversal_transaction_id": "a.reversal", "posted_date": "2026-07-03", "reason": "SYNTHETIC"},
                            [S.ev("transaction", tid, self.repo.transaction(tid)["row_version"])])))
        expected = self.rows()
        target = self.root / "ported.sqlite"
        archive = self.archive()
        self.assertEqual(len(portability.read_snapshot(archive)["payload"]["tables"]), 18)
        portability.import_snapshot(archive, target)
        reopened = open_database(target)
        try:
            self.assertEqual(self.rows(reopened), expected)
            self.assertGreater(len(expected["audit_log"]), 0)
            self.assertGreater(len(expected["command_log"]), 0)
            self.assertEqual(reopened.export_staging_batch("b.pending"), self.repo.export_staging_batch("b.pending"))
        finally:
            reopened.adapter.close()

    def alter(self, archive, edit, rehash=False):
        data = json.loads(archive.read_text())
        edit(data["payload"])
        if rehash:
            data["payload_sha256"] = hashlib.sha256(portability._canonical(data["payload"])).hexdigest()
        archive.write_text(json.dumps(data))

    def test_tampered_archive_hash_refused_before_writing(self):
        archive = self.archive()
        self.alter(archive, lambda p: p["tables"]["audit_log"].clear())
        target = self.root / "no.sqlite"
        with self.assertRaises(portability.PortabilityError):
            portability.import_snapshot(archive, target)
        self.assertFalse(target.exists())

    def test_rehashed_invalid_relationship_rolls_back_and_removes_database(self):
        archive = self.archive()
        self.alter(archive, lambda p: p["tables"]["category"].clear(), rehash=True)
        target = self.root / "no.sqlite"
        with self.assertRaises((portability.PortabilityError, sqlite3.IntegrityError)):
            portability.import_snapshot(archive, target)
        self.assertFalse(target.exists())

    def test_fractional_money_and_missing_table_rejected(self):
        archive = self.archive()
        self.alter(archive, lambda p: p["tables"]["account"][0].update(opening_balance_minor=1.5), rehash=True)
        with self.assertRaises(portability.PortabilityError):
            portability.read_snapshot(archive)
        archive.unlink()
        archive = self.archive()
        self.alter(archive, lambda p: p["tables"].pop("audit_log"), rehash=True)
        with self.assertRaises(portability.PortabilityError):
            portability.read_snapshot(archive)

    def test_existing_database_archive_and_git_destination_refused(self):
        archive = self.archive()
        before = self.path.read_bytes()
        with self.assertRaises(portability.PortabilityError):
            portability.import_snapshot(archive, self.path)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(portability.PortabilityError):
            portability.export_snapshot(self.path, archive)
        with self.assertRaises(BackupError):
            portability.export_snapshot(self.path, ROOT / "private.json")


if __name__ == "__main__":
    unittest.main()
