"""Schema scripts, setup against the test-only fake, and version policy."""
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from fake_access import FakeAccessAdapter, FakeAccessDatabase, new_fake_store  # noqa: E402
from perfin_store import SCHEMA_VERSION, ddl, migrations, sqlbuild  # noqa: E402
from perfin_store.repository import Repository  # noqa: E402
from perfin_store.setup import create_schema  # noqa: E402

REFERENCE = ROOT / "contracts" / "access" / "perfin_v1_reference.sql"
REPORT_TABLES = json.loads((ROOT / "contracts" / "schemas" / "report_tables.json").read_text(encoding="utf-8"))


def reference_tables():
    out = {}
    for stmt in ddl.split_statements(REFERENCE.read_text(encoding="utf-8")):
        t = ddl.parse_create_table(stmt)
        out[t.name] = t
    return out


class DerivedDDL(unittest.TestCase):
    def test_tables_match_reference_exactly(self):
        ref, ours = reference_tables(), ddl.registry()
        self.assertEqual(list(ref), list(ours))
        for name, rt in ref.items():
            ot = ours[name]
            self.assertEqual([(c.name, c.type, c.length, c.not_null) for c in rt.columns.values()],
                             [(c.name, c.type, c.length, c.not_null) for c in ot.columns.values()], name)
            self.assertEqual(rt.primary_key, ot.primary_key, name)
            self.assertEqual(rt.uniques, ot.uniques, name)
            self.assertEqual(rt.foreign_keys, ot.foreign_keys, name)

    def test_reference_checks_kept_and_every_currency_column_checked(self):
        ref, ours = reference_tables(), ddl.registry()
        for name, rt in ref.items():
            for ck_name, expr in rt.checks:
                self.assertIn((ck_name, expr), ours[name].checks, name)
        for t in ours.values():
            exprs = " ".join(e for _, e in t.checks)
            for c in t.columns.values():
                if c.type == "CURRENCY":
                    self.assertIn("%s = Int(%s)" % (c.name, c.name), exprs, (t.name, c.name))

    def test_010_has_no_check_constraints(self):
        self.assertNotIn("CHECK", ddl.strip_comments(ddl.read_script("010_tables.sql")))

    def test_indexes_reference_real_columns(self):
        reg = ddl.registry()
        for ix in ddl.indexes():
            for c in ix.columns:
                self.assertIn(c, reg[ix.table].columns, ix.name)
        self.assertTrue(any(ix.unique and ix.ignore_null and ix.columns == ("reverses_transaction_id",)
                            for ix in ddl.indexes()))

    def test_report_views_columns_match_report_tables_json(self):
        views = dict(ddl.views())
        for name in ("rpt_accounts", "rpt_transactions", "rpt_splits", "rpt_card_status", "rpt_statements",
                     "rpt_reconciliation", "rpt_review_queue", "rpt_card_terms", "rpt_valuations", "rpt_statement_buckets"):
            self.assertIn(name, views)
            cols = re.findall(r"AS \[(\w+)\]", views[name])
            self.assertEqual(cols, [c["name"] for c in REPORT_TABLES["tables"][name]], name)

    def test_views_are_read_only_selects(self):
        for name, sql in ddl.views():
            self.assertTrue(sql.startswith("SELECT"))
            self.assertNotRegex(sql.upper(), r"\b(INSERT|UPDATE|DELETE|DROP|ALTER)\b")


class SqlBuilder(unittest.TestCase):
    def test_all_values_are_parameters(self):
        sql, params = sqlbuild.insert("category", {"category_id": "x'); DROP TABLE account; --", "name": "n",
                                                   "category_kind": "expense"})
        self.assertEqual(sql, "INSERT INTO [category] ([category_id], [name], [category_kind]) VALUES (?, ?, ?)")
        self.assertEqual(params[0], "x'); DROP TABLE account; --")
        sql, params = sqlbuild.update("ledger_txn", {"description": "d"}, {"transaction_id": "t", "currency": None})
        self.assertEqual(sql, "UPDATE [ledger_txn] SET [description] = ? WHERE [transaction_id] = ? AND [currency] IS NULL")
        self.assertEqual(params, ("d", "t"))

    def test_unknown_identifiers_refused(self):
        with self.assertRaises(KeyError):
            sqlbuild.select("account", ["account_id; DROP"])
        with self.assertRaises(KeyError):
            sqlbuild.insert("nope", {"a": 1})
        with self.assertRaises(ValueError):
            sqlbuild.delete("account", {})


class SetupOnFake(unittest.TestCase):
    def test_ansi92_creates_everything(self):
        repo, ad, report = new_fake_store()
        self.assertEqual(report["tables"], 18)
        self.assertFalse(report["checks_failed"])
        self.assertFalse(report["views_failed"])
        meta = migrations.read_meta(ad)
        self.assertEqual(meta["schema_version"], SCHEMA_VERSION)
        self.assertEqual(meta["contract_version"], "1.0.0")
        self.assertEqual(meta["check_constraints"], "present")
        self.assertEqual(repo.blocked_errors, [])

    def test_ansi89_records_fallback(self):
        repo, ad, report = new_fake_store(ansi92=False)
        self.assertFalse(report["checks_ok"])
        self.assertEqual(len(report["checks_failed"]), len(ddl.script_statements("020_checks.sql")))
        meta = migrations.read_meta(ad)
        self.assertEqual(meta["check_constraints"], "absent")
        self.assertEqual(meta["report_views"], "absent")
        self.assertIn("repository validation", meta["check_fallback"])

    def test_bad_currency_code(self):
        ad = FakeAccessAdapter(FakeAccessDatabase())
        with self.assertRaises(Exception):
            create_schema(ad, base_currency="usd", now="2026-11-04T00:00:00Z")


class VersionPolicy(unittest.TestCase):
    def _store_with(self, version):
        repo, ad, _ = new_fake_store()
        ad.begin()
        ad.execute(*sqlbuild.update("contract_meta", {"meta_value": version}, {"meta_key": "schema_version"}))
        ad.commit()
        return ad

    def test_current_opens(self):
        self.assertEqual(migrations.check_version("1.0.0"), "current")
        self.assertEqual(migrations.check_version("1.0.7"), "current")

    def test_newer_major_refused(self):
        ad = self._store_with("2.0.0")
        with self.assertRaisesRegex(migrations.SchemaVersionError, "newer major"):
            Repository(ad)

    def test_newer_minor_refused_fail_closed(self):
        with self.assertRaisesRegex(migrations.SchemaVersionError, "fail closed"):
            Repository(self._store_with("1.1.0"))

    def test_older_major_and_garbage_refused(self):
        for v in ("0.9.0", "abc", ""):
            with self.assertRaises(migrations.SchemaVersionError):
                migrations.check_version(v)

    def test_older_minor_needs_a_migration_path(self):
        self.assertEqual(migrations.check_version("1.0.0", supported=(1, 1, 0)), "older")
        ad = self._store_with("1.0.0")
        meta = migrations.read_meta(ad)
        meta["schema_version"] = "0.5.0"
        with self.assertRaisesRegex(migrations.SchemaVersionError, "no migration"):
            migrations.migrate_to_current(ad, meta)


if __name__ == "__main__":
    unittest.main()
