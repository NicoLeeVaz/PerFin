"""Fixtures follow the contract exactly; the CSV reader enforces the dialect."""
import datetime as dt
import os
import unittest

import _support
import fixture_gen
from perfin_contracts.semantic import validate_document
from perfin_excel_core import reports, spec


class Fixtures(unittest.TestCase):
    def test_synthetic_documents_validate(self):
        for name in ("ledger_bundle.synthetic.json", "staging_batch.synthetic.json"):
            self.assertEqual(validate_document(_support.load_json(_support.FIXTURES / name)), [], name)
        for mf in sorted(_support.MODULES.glob("*/module_manifest.json")):
            self.assertEqual(validate_document(_support.load_json(mf)), [], mf)

    def test_committed_csvs_match_generator(self):
        with _support.temp_dir() as d:
            fixture_gen.generate(d)
            for table in spec.CORE_SOURCES:
                with open(d / (table + ".csv"), "rb") as a, open(_support.REPORTS / (table + ".csv"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), table)

    def test_headers_and_dialect_exact(self):
        tables = spec.report_tables()
        dialect = spec.csv_dialect()
        self.assertEqual((dialect["encoding"], dialect["bom"], dialect["line_terminator"]), ("utf-8", False, "\r\n"))
        for table in spec.CORE_SOURCES:
            raw = (_support.REPORTS / (table + ".csv")).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            header = raw.split(b"\r\n", 1)[0].decode("ascii")
            self.assertEqual(header.split(","), [c[0] for c in tables[table]])
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b"").replace(b'\r', b''), "bare LF in " + table)
            rows = reports.read_report_csv(_support.REPORTS / (table + ".csv"), table)
            self.assertTrue(rows, table)

    def test_trigger_texts_present(self):
        q = reports.read_report_csv(_support.REPORTS / "rpt_review_queue.csv", "rpt_review_queue")
        firsts = {r["description"][0] for r in q if r["description"]}
        self.assertTrue({"+", "-", "@", "\t", "\r"} <= firsts)
        t = reports.read_report_csv(_support.REPORTS / "rpt_transactions.csv", "rpt_transactions")
        self.assertTrue(any(r["description"].startswith("=") for r in t))


class Reader(unittest.TestCase):
    def write(self, d, text, table="rpt_reconciliation", raw=None):
        p = d / (table + ".csv")
        p.write_bytes(raw if raw is not None else text.encode("utf-8"))
        return p

    H = "reconciliation_id,statement_id,included_count,difference_minor,recon_status\r\n"

    def status_of(self, d, **kw):
        p = self.write(d, **kw)
        with self.assertRaises(reports.ReportError) as cm:
            reports.read_report_csv(p, "rpt_reconciliation")
        return cm.exception.status

    def test_rejections(self):
        with _support.temp_dir() as d:
            ok = self.H + "r1,s1,2,0,balanced\r\n"
            self.assertEqual(reports.read_report_csv(self.write(d, ok), "rpt_reconciliation")[0]["included_count"], 2)
            cases = {
                "bom": (dict(text="", raw=b"\xef\xbb\xbf" + ok.encode()), spec.STATUS_INVALID),
                "lf": (dict(text=ok.replace("\r\n", "\n")), spec.STATUS_INVALID),
                "header": (dict(text=ok.replace("recon_status", "status")), spec.STATUS_BAD_HEADER),
                "order": (dict(text="statement_id,reconciliation_id,included_count,difference_minor,recon_status\r\n"),
                          spec.STATUS_BAD_HEADER),
                "empty": (dict(text=""), spec.STATUS_BAD_HEADER),
                "float": (dict(text=self.H + "r1,s1,2,12.34,balanced\r\n"), spec.STATUS_INVALID),
                "null": (dict(text=self.H + "r1,s1,2,,balanced\r\n"), spec.STATUS_INVALID),
                "fields": (dict(text=self.H + "r1,s1,2,0,balanced,x\r\n"), spec.STATUS_INVALID),
                "quoting": (dict(text=self.H + '"r1",s1,2,0,balanced\r\n'), spec.STATUS_INVALID),
                "latin1": (dict(text="", raw=(self.H + "r1,s1,2,0,b\xe9\r\n").encode("latin-1")), spec.STATUS_INVALID),
                "bound": (dict(text=self.H + "r1,s1,2,922337203685478,balanced\r\n"), spec.STATUS_INVALID),
                "id": (dict(text=self.H + "-r1,s1,2,0,balanced\r\n"), spec.STATUS_INVALID),
            }
            for name, (kw, want) in cases.items():
                self.assertEqual(self.status_of(d, **kw), want, name)
            with self.assertRaises(reports.ReportError) as cm:
                reports.read_report_csv(d / "nope.csv", "rpt_reconciliation")
            self.assertEqual(cm.exception.status, spec.STATUS_MISSING)

    def test_typed_values(self):
        self.assertIsNone(reports.parse_value("", "date", True))
        self.assertEqual(reports.parse_value("2028-02-29", "date", False), dt.date(2028, 2, 29))
        for bad, t in [("2026-02-30", "date"), ("1/2/2026", "date"), ("true", "boolean"), ("1e3", "money_minor"),
                       (" 5", "integer"), ("0.24.1", "decimal_string"), ("usd", "currency")]:
            with self.assertRaises(ValueError, msg=bad):
                reports.parse_value(bad, t, False)
        self.assertEqual(reports.parse_value("0.2499", "decimal_string", False), "0.2499")
        self.assertEqual(reports.parse_value("=1+1", "text", False), "=1+1")

    def test_accounts_sign_rule(self):
        with _support.temp_dir() as d:
            src = (_support.REPORTS / "rpt_accounts.csv").read_text(encoding="utf-8")
            (d / "rpt_accounts.csv").write_bytes(src.replace(",-55000,55000,", ",-55000,-55000,").encode())
            with self.assertRaises(reports.ReportError) as cm:
                reports.read_report_csv(d / "rpt_accounts.csv", "rpt_accounts")
            self.assertEqual(cm.exception.status, spec.STATUS_INVALID)
            self.assertNotIn("55000", cm.exception.message)  # messages never echo values


class Status(unittest.TestCase):
    def test_all_ok_and_derived(self):
        with _support.temp_dir() as d:
            _support.copy_reports(d)
            tables, status = reports.load_reports(d, _support.CHECKED_AT)
            self.assertEqual({s["status"] for s in status}, {spec.STATUS_OK})
            self.assertEqual([s["source"] for s in status], list(spec.CORE_SOURCES))
            recon = {r["statement_id"]: r for r in tables["perfin_statement_recon"]}
            self.assertEqual(recon["st_alpha_2026_06"]["recon_status"], "balanced")
            self.assertEqual(recon["st_alpha_2026_06"]["opening_display_minor"], 45000)
            self.assertEqual(recon["st_beta_2026_06"]["recon_status"], "in_progress")
            self.assertEqual(recon["st_beta_2026_06"]["difference_minor"], 2500)
            self.assertEqual(sorted(i["transaction_id"] for i in tables["perfin_unreconciled_items"]), ["t005", "t006"])

    def test_timezone_aware_checked_at_accepted(self):
        # contract timestamps are UTC "...Z"; an aware value must not crash the
        # comparison with naive local file times and must give the same result
        aware = _support.CHECKED_AT.astimezone(dt.timezone.utc)
        with _support.temp_dir() as d:
            _support.copy_reports(d)
            _, naive_status = reports.load_reports(d, _support.CHECKED_AT)
            _, aware_status = reports.load_reports(d, aware)
            self.assertEqual([s["status"] for s in aware_status], [s["status"] for s in naive_status])

    def test_missing_invalid_stale(self):
        with _support.temp_dir() as d:
            _support.copy_reports(d)
            os.remove(d / "rpt_card_status.csv")
            (d / "rpt_review_queue.csv").write_bytes(b"wrong,header\r\n")
            old = dt.datetime(2026, 5, 1).timestamp()
            os.utime(d / "rpt_transactions.csv", (old, old))
            tables, status = reports.load_reports(d, _support.CHECKED_AT, stale_days=7)
            by = {s["source"]: s for s in status}
            self.assertEqual(by["rpt_card_status"]["status"], spec.STATUS_MISSING)
            self.assertEqual(by["rpt_review_queue"]["status"], spec.STATUS_BAD_HEADER)
            self.assertEqual(by["rpt_transactions"]["status"], spec.STATUS_STALE)
            self.assertEqual(tables["rpt_card_status"], [])          # no old data
            self.assertEqual(tables["rpt_review_queue"], [])
            self.assertTrue(tables["rpt_transactions"])              # stale rows shown, but flagged
            late = _support.CHECKED_AT + dt.timedelta(days=30)
            _, status = reports.load_reports(d, late, stale_days=7)
            self.assertEqual({s["source"]: s["status"] for s in status}["rpt_accounts"], spec.STATUS_STALE)

    def test_derived_views_need_their_sources(self):
        with _support.temp_dir() as d:
            _support.copy_reports(d)
            os.remove(d / "rpt_statements.csv")
            tables, _ = reports.load_reports(d, _support.CHECKED_AT)
            self.assertEqual(tables["perfin_statement_recon"], [])
            self.assertEqual(tables["perfin_unreconciled_items"], [])


if __name__ == "__main__":
    unittest.main()
