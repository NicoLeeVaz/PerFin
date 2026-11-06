"""Real on-disk SQLite checks, independent of the fake Access adapter."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests/store"), str(ROOT / "contracts/python")]

import synthetic as S
from perfin_contracts.semantic import validate_document
from perfin_store import ddl, money
from perfin_store import reports
from perfin_store.adapter import AdapterError
from perfin_store.migrations import SchemaVersionError
from perfin_store.repository import Repository, StorageError
from perfin_store.sqlite_backend import SQLiteAdapter, create_database, open_database


class SQLiteRepository(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="perfin-sqlite-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "perfin.sqlite3"
        self.created = create_database(self.path)
        self.repo = open_database(self.path)
        self.repo.clock = lambda: "2026-11-05T12:00:00Z"
        self.addCleanup(self.repo.adapter.close)
        self.ok(self.repo.import_bundle(S.reference_bundle()))
        self.ok(self.repo.set_default_categories("exp.uncategorized", "inc.uncategorized"))

    def ok(self, result):
        self.assertEqual(validate_document(result), [])
        self.assertEqual(result["result_status"], "accepted", result)
        return result

    def rejected(self, result, code):
        self.assertEqual(result["result_status"], "rejected", result)
        self.assertIn(code, [e["code"] for e in result["errors"]], result)

    def ev(self, entity, eid):
        table, key = {"batch": ("import_batch", "batch_id"), "transaction": ("ledger_txn", "transaction_id"),
                      "transfer_link": ("transfer_link", "transfer_link_id")}[entity]
        return S.ev(entity, eid, self.repo._one(table, {key: eid})["row_version"])

    def command(self, kind, payload, expected=(), command_id=None):
        doc = S.command(kind, payload, list(expected))
        if command_id:
            doc["command_id"] = command_id
        return self.repo.execute(doc)

    def commit_batch(self, batch):
        b = batch["batch"]
        return self.command("commit_batch", {"batch_id": b["batch_id"], "source_file_sha256": b["source_file_sha256"]},
                            [self.ev("batch", b["batch_id"])])

    def state(self):
        return {t: self.repo.adapter.query_storage('SELECT * FROM "%s" ORDER BY %s' %
                (t, ", ".join('"%s"' % c for c in spec.primary_key))) for t, spec in ddl.registry().items()}

    def test_schema_preserves_all_columns_keys_relationships_and_indexes(self):
        self.assertEqual(self.created["tables"], 18)
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        tables = dict(con.execute("SELECT name, sql FROM sqlite_schema WHERE type='table'"))
        self.assertEqual(set(tables), set(ddl.registry()))
        for name, spec in ddl.registry().items():
            with self.subTest(table=name):
                cols = con.execute('PRAGMA table_info("%s")' % name).fetchall()
                self.assertEqual([r[1] for r in cols], list(spec.columns))
                self.assertEqual(tuple(r[1] for r in sorted(cols, key=lambda r: r[5]) if r[5]), spec.primary_key)
                self.assertEqual({(r[3], r[2], r[4]) for r in con.execute('PRAGMA foreign_key_list("%s")' % name)},
                                 set(spec.foreign_keys))
                self.assertTrue(tables[name].endswith("STRICT"))
        index_names = {r[0] for r in con.execute("SELECT name FROM sqlite_schema WHERE type='index'")}
        self.assertTrue({i.name for i in ddl.indexes()} <= index_names)
        self.assertEqual(self.repo.meta["backend"], "sqlite")
        self.assertEqual(self.repo.meta["report_views"], "python_export")

    def test_persistence_reopen_and_read_only(self):
        b = S.batch("persist", "chk:main", [S.row(1, "2026-07-01", -1234, "SYNTHETIC", state="approved")])
        self.ok(self.repo.stage_batch(b))
        self.ok(self.commit_batch(b))
        expected = self.repo.export_bundle()
        other = open_database(self.path, read_only=True)
        self.addCleanup(other.adapter.close)
        self.assertEqual(other.export_bundle(), expected)
        self.assertEqual(other.summary()["account_balances_minor"]["chk:main"], 248766)
        with self.assertRaises(StorageError):
            other.set_default_categories("exp.groceries", "inc.salary")
        self.assertEqual(other.export_bundle(), expected)

    def test_engine_foreign_keys_are_enabled_on_every_connection(self):
        for read_only in (False, True):
            adapter = SQLiteAdapter(self.path, read_only=read_only)
            try:
                self.assertEqual(adapter.query_storage("PRAGMA foreign_keys"), [(1,)])
            finally:
                adapter.close()
        adapter = self.repo.adapter
        adapter.begin()
        with self.assertRaises(sqlite3.IntegrityError):
            adapter.execute("DELETE FROM [category] WHERE [category_id] = ?", ("exp",))
        adapter.rollback()
        self.assertEqual(adapter.query_storage("PRAGMA foreign_key_check"), [])

    def test_engine_rejects_fractional_out_of_range_and_invalid_boolean(self):
        con = sqlite3.connect(self.path)
        self.addCleanup(con.close)
        for column, bad in (("opening_balance_minor", 0.5), ("opening_balance_minor", money.MONEY_MAX + 1),
                            ("opening_balance_minor", "not money"), ("include_in_net_worth", -1),
                            ("row_version", 2**31), ("display_name", "x" * 121)):
            with self.subTest(column=column, bad=bad):
                with self.assertRaises(sqlite3.IntegrityError):
                    con.execute('UPDATE account SET "%s" = ? WHERE account_id = ?' % column, (bad, "chk:main"))
                con.rollback()

    def test_exact_cents_at_contract_bounds(self):
        b = S.batch("bounds", "chk:main", [S.row(1, "2026-07-01", money.MONEY_MAX, "MAX", state="approved"),
                                               S.row(2, "2026-07-01", money.MONEY_MIN, "MIN", state="approved")])
        self.ok(self.repo.stage_batch(b))
        self.ok(self.commit_batch(b))
        stored = self.repo.adapter.query_storage("SELECT amount_minor, typeof(amount_minor) FROM ledger_txn ORDER BY amount_minor")
        self.assertEqual(stored, [(money.MONEY_MIN, "integer"), (money.MONEY_MAX, "integer")])
        self.assertEqual(self.repo.summary()["account_balances_minor"]["chk:main"], 250000)
        self.assertEqual(validate_document(self.repo.export_bundle()), [])

    def test_case_insensitive_ids_and_unique_null_reversal_ids(self):
        self.assertEqual(self.repo.adapter.query_storage("SELECT account_id FROM account WHERE account_id = ?",
                                                        ("CHK:MAIN",)), [("chk:main",)])
        self.repo.adapter.begin()
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.adapter.execute("INSERT INTO contract_meta (meta_key, meta_value) VALUES (?, ?)",
                                      ("BACKEND", "duplicate"))
        self.repo.adapter.rollback()
        b = S.batch("nulls", "chk:main", [S.row(1, "2026-07-01", -1, "ONE", state="approved"),
                                              S.row(2, "2026-07-01", -2, "TWO", state="approved")])
        self.ok(self.repo.stage_batch(b))
        self.ok(self.commit_batch(b))
        self.assertEqual(self.repo.adapter.query_storage("SELECT reverses_transaction_id FROM ledger_txn"), [(None,), (None,)])

    def test_commit_duplicate_refusal_explicit_review_and_retry(self):
        b = S.batch("duplicates", "chk:main", [
            S.row(1, "2026-07-01", -5000, "FIRST", state="approved", source_txn_id="bank-1"),
            S.row(2, "2026-07-02", -900, "SECOND", state="approved", source_txn_id="bank-1")])
        self.ok(self.repo.stage_batch(b))
        before = self.state()
        self.rejected(self.commit_batch(b), "E_DUPLICATE_UNRESOLVED")
        self.assertEqual(self.state(), before)
        self.ok(self.command("resolve_duplicate", {"batch_id": "duplicates", "row_number": 2,
                         "resolution": "confirmed_distinct"}, [self.ev("batch", "duplicates")]))
        self.ok(self.commit_batch(b))
        self.assertEqual(self.repo.summary()["account_balances_minor"]["chk:main"], 244100)
        resolved = [r for r in self.repo._rows("audit_log") if r["action"] == "resolve"]
        self.assertEqual(json.loads(resolved[0]["before_json"])["duplicate_status"], "none")
        before = self.state()
        self.assertEqual(self.commit_batch(b)["result_status"], "replayed")
        self.assertEqual(self.repo.stage_batch(b)["result_status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_stale_version_across_independent_connections(self):
        b = S.batch("stale", "chk:main", [S.row(1, "2026-07-01", -100, "ROW")])
        self.ok(self.repo.stage_batch(b))
        expected = [self.ev("batch", "stale")]
        other = open_database(self.path)
        self.addCleanup(other.adapter.close)
        self.ok(self.command("approve_rows", {"batch_id": "stale", "row_numbers": [1]}, expected))
        before = self.state()
        self.rejected(other.execute(S.command("reject_rows", {"batch_id": "stale", "row_numbers": [1],
                     "reason": "stale"}, expected)), "E_STALE_VERSION")
        self.assertEqual(self.state(), before)

    def test_later_ledger_collision_recovers_after_explicit_review(self):
        pending = S.batch("pending", "chk:main", [S.row(1, "2026-07-02", -900, "SECOND",
                          state="approved", source_txn_id="bank-1")])
        first = S.batch("first", "chk:main", [S.row(1, "2026-07-01", -5000, "FIRST",
                        state="approved", source_txn_id="bank-1")])
        self.ok(self.repo.stage_batch(pending))
        self.ok(self.repo.stage_batch(first))
        self.ok(self.commit_batch(first))
        before = self.state()
        self.rejected(self.commit_batch(pending), "E_DUPLICATE_UNRESOLVED")
        self.assertEqual(self.state(), before)
        self.ok(self.command("resolve_duplicate", {"batch_id": "pending", "row_number": 1,
                             "resolution": "confirmed_distinct"}, [self.ev("batch", "pending")]))
        self.ok(self.commit_batch(pending))
        self.assertEqual(self.repo.summary()["account_balances_minor"]["chk:main"], 244100)

    def test_failure_mid_commit_rolls_back_every_table_and_retry_succeeds(self):
        b = S.batch("atomic", "chk:main", [S.row(n, "2026-07-01", -n, "ROW", state="approved") for n in (1, 2, 3)])
        self.ok(self.repo.stage_batch(b))
        before = self.state()
        original = self.repo.adapter.execute
        count = 0

        def fail(sql, params=()):
            nonlocal count
            if sql.startswith("INSERT INTO [split]"):
                count += 1
                if count == 3:
                    raise RuntimeError("injected third split failure")
            return original(sql, params)

        self.repo.adapter.execute = fail
        try:
            with self.assertRaises(StorageError):
                self.commit_batch(b)
        finally:
            self.repo.adapter.execute = original
        self.assertEqual(self.state(), before)
        self.ok(self.commit_batch(b))
        self.assertEqual(self.repo.summary()["account_balances_minor"]["chk:main"], 249994)

    def test_second_writer_cannot_enter_transaction_and_rollback_releases_lock(self):
        other = SQLiteAdapter(self.path, timeout=0)
        self.addCleanup(other.close)
        self.repo.adapter.begin()
        with self.assertRaises(sqlite3.OperationalError):
            other.begin()
        self.repo.adapter.rollback()
        other.begin()
        other.rollback()

    def test_close_discards_uncommitted_changes(self):
        other = SQLiteAdapter(self.path)
        other.begin()
        other.execute("INSERT INTO contract_meta (meta_key, meta_value) VALUES (?, ?)", ("never_committed", "value"))
        other.close()
        self.assertEqual(self.repo.adapter.query_storage("SELECT meta_value FROM contract_meta WHERE meta_key = ?",
                                                        ("never_committed",)), [])

    def test_transfer_relink_same_second_restores_latest_categories(self):
        b = {"contract": "perfin", "contract_version": "1.0.1", "document_type": "ledger_bundle", "base_currency": "USD",
             "accounts": [], "categories": [], "transactions": [
                 {"transaction_id": "m1", "account_id": "chk:main", "posted_date": "2026-07-01", "amount_minor": -10000,
                  "currency": "USD", "description": "PAYMENT", "entry_method": "manual", "row_version": 1,
                  "splits": [S.cat("m1.s", -10000, "exp.uncategorized")]},
                 {"transaction_id": "m2", "account_id": "card:alpha", "posted_date": "2026-07-01", "amount_minor": 10000,
                  "currency": "USD", "description": "RECEIVED", "entry_method": "manual", "row_version": 1,
                  "splits": [S.cat("m2.s", 10000, "inc.uncategorized")]}]}
        self.ok(self.repo.import_bundle(b))
        for i, cid in enumerate(("ffffffff-ffff-4fff-8fff-ffffffffffff", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")):
            if i:
                self.ok(self.command("set_splits", {"transaction_id": "m1", "splits": [S.cat("m1.s", -10000, "exp.groceries")]},
                                     [self.ev("transaction", "m1")]))
            self.ok(self.command("link_transfer", {"transfer_link_id": "L1", "from_transaction_id": "m1",
                         "to_transaction_id": "m2", "link_status": "confirmed"},
                         [self.ev("transaction", "m1"), self.ev("transaction", "m2")], cid))
            self.ok(self.command("unlink_transfer", {"transfer_link_id": "L1", "reason": "review"},
                                 [self.ev("transfer_link", "L1")]))
        self.assertEqual(self.repo.transaction("m1")["splits"], [S.cat("m1.s", -10000, "exp.groceries")])
        self.assertEqual(self.repo.transaction("m2")["splits"], [S.cat("m2.s", 10000, "inc.uncategorized")])
        self.assertEqual(validate_document(self.repo.export_bundle()), [])

    def test_create_refuses_existing_files_and_open_never_creates(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            create_database(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        missing = self.path.parent / "missing.sqlite3"
        with self.assertRaises(AdapterError):
            open_database(missing)
        self.assertFalse(missing.exists())
        with self.assertRaises(AdapterError):
            create_database(ROOT / "inside.sqlite3")
        self.assertFalse((ROOT / "inside.sqlite3").exists())

    def test_backend_and_newer_schema_metadata_fail_closed(self):
        for key, value in (("backend", "access"), ("sqlite_schema_version", "999"), ("schema_version", "9.0.0")):
            original = self.repo.meta[key]
            self.repo.adapter.begin()
            self.repo.adapter.execute("UPDATE contract_meta SET meta_value = ? WHERE meta_key = ?", (value, key))
            self.repo.adapter.commit()
            with self.assertRaises(SchemaVersionError):
                open_database(self.path)
            self.repo.adapter.begin()
            self.repo.adapter.execute("UPDATE contract_meta SET meta_value = ? WHERE meta_key = ?", (original, key))
            self.repo.adapter.commit()

    def test_future_contract_minor_is_refused_without_changing_database(self):
        self.repo.adapter.begin()
        self.repo.adapter.execute("UPDATE contract_meta SET meta_value = ? WHERE meta_key = ?",
                                  ("1.1.0", "contract_version"))
        self.repo.adapter.commit()
        before = self.path.read_bytes()
        with self.assertRaises(SchemaVersionError):
            opened = open_database(self.path)
            opened.adapter.close()
        self.assertEqual(self.path.read_bytes(), before)

    def test_same_contract_minor_patch_versions_remain_compatible(self):
        for version in ("1.0.0", "1.0.999"):
            with self.subTest(version=version):
                self.repo.adapter.begin()
                self.repo.adapter.execute("UPDATE contract_meta SET meta_value = ? WHERE meta_key = ?",
                                          (version, "contract_version"))
                self.repo.adapter.commit()
                opened = open_database(self.path)
                opened.adapter.close()

    def test_create_preserves_orphaned_sidecars_and_refuses_target(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                target = self.path.parent / ("orphan" + suffix + ".sqlite")
                sidecar = Path(str(target) + suffix)
                sentinel = b"SYNTHETIC existing sidecar; preserve exactly"
                sidecar.write_bytes(sentinel)
                with self.assertRaises(FileExistsError):
                    create_database(target)
                self.assertFalse(target.exists())
                self.assertEqual(sidecar.read_bytes(), sentinel)

    @unittest.skipUnless(sys.platform != "win32", "symlink creation requires native Windows privileges")
    def test_create_refuses_dangling_sidecar_links(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                target = self.path.parent / ("dangling" + suffix + ".sqlite")
                sidecar = Path(str(target) + suffix)
                sidecar.symlink_to(self.path.parent / "missing-private-file")
                with self.assertRaises(FileExistsError):
                    create_database(target)
                self.assertFalse(target.exists())
                self.assertTrue(sidecar.is_symlink())

    def interleaving_pair(self):
        # WAL permits the writer to commit inside the deterministic read hook.
        # The production default rollback journal also preserves snapshots, but
        # its writer would wait for this reader instead of demonstrating interleave.
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode = WAL").fetchone(), ("wal",))
        bundle = {"contract": "perfin", "contract_version": "1.0.1", "document_type": "ledger_bundle", "base_currency": "USD",
                  "accounts": [], "categories": [], "transactions": [
                      {"transaction_id": "interleave", "account_id": "chk:main", "posted_date": "2026-07-01",
                       "amount_minor": -100, "currency": "USD", "description": "SYNTHETIC", "entry_method": "manual",
                       "row_version": 1, "splits": [S.cat("interleave.s", -100, "exp.groceries")]}]}
        self.ok(self.repo.import_bundle(bundle))
        writer = open_database(self.path)
        self.addCleanup(writer.adapter.close)
        return writer

    def edit_with(self, writer, amount):
        version = writer.transaction("interleave")["row_version"]
        self.ok(writer.execute(S.command("edit_transaction", {"transaction_id": "interleave",
                    "changes": {"amount_minor": amount}, "reason": "SYNTHETIC interleaving"},
                    [S.ev("transaction", "interleave", version)])))

    def test_multitable_reads_remain_consistent_during_another_connection_commit(self):
        writer = self.interleaving_pair()
        for operation in ("bundle", "transaction", "reports", "summary"):
            with self.subTest(operation=operation):
                old_amount = self.repo.transaction("interleave")["amount_minor"]
                new_amount = old_amount - 100
                original = self.repo.adapter.query
                fired = False

                def query(sql, params=()):
                    nonlocal fired
                    rows = original(sql, params)
                    if "FROM [ledger_txn]" in sql and not fired:
                        fired = True
                        self.edit_with(writer, new_amount)
                    return rows

                with patch.object(self.repo.adapter, "query", query):
                    if operation == "bundle":
                        result = self.repo.export_bundle()
                        self.assertEqual(validate_document(result), [])
                        self.assertEqual(result["transactions"][0]["amount_minor"], old_amount)
                    elif operation == "transaction":
                        result = self.repo.transaction("interleave")
                        self.assertEqual(result["amount_minor"], old_amount)
                        self.assertEqual(sum(s["amount_minor"] for s in result["splits"]), old_amount)
                    elif operation == "reports":
                        result = reports.build_tables(self.repo, "2026-07-02")
                        self.assertEqual(result["rpt_transactions"][0]["amount_minor"], old_amount)
                        self.assertEqual(result["rpt_splits"][0]["amount_minor"], old_amount)
                    else:
                        result = self.repo.summary()
                        self.assertEqual(result["account_balances_minor"]["chk:main"], 250000 + old_amount)
                self.assertTrue(fired)
                self.assertFalse(self.repo.adapter._conn.in_transaction)
                self.assertEqual(self.repo.transaction("interleave")["amount_minor"], new_amount)

    def test_constructor_validation_uses_one_snapshot(self):
        writer = self.interleaving_pair()
        original = SQLiteAdapter.query
        for factory, new_amount in ((open_database, -200), (lambda path: Repository(SQLiteAdapter(path)), -300)):
            fired = False

            def query(adapter, sql, params=()):
                nonlocal fired
                rows = original(adapter, sql, params)
                if adapter is not writer.adapter and "FROM [ledger_txn]" in sql and not fired:
                    fired = True
                    self.edit_with(writer, new_amount)
                return rows

            with patch.object(SQLiteAdapter, "query", query):
                reader = factory(self.path)
            self.addCleanup(reader.adapter.close)
            self.assertTrue(fired)
            self.assertEqual(reader.blocked_errors, [])
            self.assertFalse(reader.adapter._conn.in_transaction)
            self.assertEqual(reader.transaction("interleave")["amount_minor"], new_amount)

    def test_staging_export_keeps_batch_and_review_rows_in_one_snapshot(self):
        writer = self.interleaving_pair()
        b = S.batch("interleave.batch", "chk:main", [S.row(1, "2026-07-02", -100, "PENDING")])
        self.ok(self.repo.stage_batch(b))
        original = self.repo.adapter.query
        fired = False

        def query(sql, params=()):
            nonlocal fired
            rows = original(sql, params)
            if "FROM [import_batch]" in sql and not fired:
                fired = True
                self.ok(writer.execute(S.command("approve_rows", {"batch_id": "interleave.batch", "row_numbers": [1]},
                                                 [S.ev("batch", "interleave.batch", 1)])))
            return rows

        with patch.object(self.repo.adapter, "query", query):
            doc = self.repo.export_staging_batch("interleave.batch")
        self.assertTrue(fired)
        self.assertEqual(doc["batch"]["batch_status"], "staged")
        self.assertEqual(doc["rows"][0]["review_state"], "pending")
        self.assertEqual(self.repo.export_staging_batch("interleave.batch")["rows"][0]["review_state"], "approved")

    def test_snapshot_exception_releases_only_its_own_transaction(self):
        original = self.repo.adapter.query

        def fail(sql, params=()):
            if "FROM [split]" in sql:
                raise RuntimeError("injected reader failure")
            return original(sql, params)

        with patch.object(self.repo.adapter, "query", fail):
            with self.assertRaises(RuntimeError):
                self.repo.snapshot()
            self.assertFalse(self.repo.adapter._conn.in_transaction)
            self.repo.adapter.begin()
            try:
                with self.assertRaises(RuntimeError):
                    self.repo.snapshot()
                self.assertTrue(self.repo.adapter._conn.in_transaction)
            finally:
                self.repo.adapter.rollback()
        self.assertEqual(validate_document(self.repo.export_bundle()), [])


if __name__ == "__main__":
    unittest.main()
