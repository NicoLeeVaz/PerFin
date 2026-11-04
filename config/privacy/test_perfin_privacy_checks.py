"""Linux unit tests for config/privacy (synthetic data only).

Run from this directory:  python3 -m unittest -v
"""

import copy
import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import perfin_privacy_checks as pc

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def make_luhn(prefix, length):
    """Build a Luhn-valid number at runtime so none sits in this source file."""
    body = prefix + "7" * (length - len(prefix) - 1)
    for check in "0123456789":
        if pc.luhn_valid(body + check):
            return body + check
    raise AssertionError("unreachable")


class DefaultsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = pc.load_defaults()

    def test_defaults_valid(self):
        self.assertEqual(pc.validate_defaults(self.cfg), [])

    def test_every_outbound_path_disabled(self):
        self.assertEqual(len(self.cfg["outbound"]), 16)
        for key, path in self.cfg["outbound"].items():
            self.assertIs(path["default_enabled"], False, key)

    def test_enabling_any_path_is_rejected(self):
        for key in self.cfg["outbound"]:
            cfg = copy.deepcopy(self.cfg)
            cfg["outbound"][key]["default_enabled"] = True
            self.assertTrue(pc.validate_defaults(cfg), key)

    def test_raw_fallback_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["nopii"]["raw_fallback_allowed"] = True
        self.assertIn("raw fallback must be false", pc.validate_defaults(cfg))

    def test_nopii_optional_for_core(self):
        self.assertIs(self.cfg["nopii"]["required_for_core_local_use"], False)

    def test_all_json_files_parse(self):
        for path in HERE.rglob("*.json"):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))


class FormulaInjectionTests(unittest.TestCase):
    def test_required_triggers_escaped(self):
        for value in ["=1+1", "+1", "-1", "@SUM(A1)", "\t=1", "\r=1",
                      "=cmd|' /C calc'!A0", '=HYPERLINK("http://example.invalid")']:
            with self.subTest(value=value):
                self.assertTrue(pc.needs_formula_escape(value))
                self.assertEqual(pc.escape_spreadsheet_text(value), "'" + value)

    def test_conservative_extras(self):
        for value in ["\n=1", "\uff1d1", "  =1", " @x"]:
            with self.subTest(value=value):
                self.assertEqual(pc.escape_spreadsheet_text(value), "'" + value)

    def test_plain_text_untouched(self):
        for value in ["", "SYNTHETIC GROCER", "Coffee = good", "a-b", "'already"]:
            with self.subTest(value=value):
                self.assertEqual(pc.escape_spreadsheet_text(value), value)

    def test_outbox_csv_escapes_text_not_numbers(self):
        records = pc.load_json(HERE / "examples" / "export-response.synthetic.json")["records"]
        rows = list(csv.DictReader(io.StringIO(pc.records_to_outbox_csv(records))))
        self.assertEqual(rows[2]["description"][0], "'")
        self.assertEqual(rows[0]["amount_minor"], "-10000")
        for row in rows:
            for field in ("description", "memo", "category", "account_alias"):
                self.assertFalse(pc.needs_formula_escape(row[field]), (field, row[field]))


class DataDirTests(unittest.TestCase):
    ENV = {"OneDrive": r"C:\Users\alex\OneDrive"}

    def check(self, path, env=None):
        return pc.evaluate_data_dir(path, env=env or {}, check_filesystem=False)

    def test_local_appdata_ok(self):
        self.assertEqual(self.check(r"C:\Users\alex\AppData\Local\PerFin")["decision"], "ok")

    def test_sync_folders_warn(self):
        for path in [r"C:\Users\alex\OneDrive\PerFin",
                     r"C:\Users\alex\OneDrive - Contoso\PerFin",
                     r"C:\Users\alex\Dropbox\PerFin",
                     r"G:\My Drive\PerFin",
                     r"C:\Users\alex\iCloudDrive\PerFin",
                     "/Users/alex/Library/Mobile Documents/com~apple~CloudDocs/PerFin",
                     "/home/alex/Dropbox/perfin"]:
            with self.subTest(path=path):
                self.assertEqual(self.check(path)["decision"], "warn")

    def test_onedrive_env_var(self):
        result = self.check(r"c:\users\alex\onedrive\x", env=self.ENV)
        self.assertEqual(result["decision"], "warn")
        self.assertTrue(any("%OneDrive%" in r for r in result["reasons"]))

    def test_documents_and_unc_warn(self):
        self.assertEqual(self.check(r"C:\Users\alex\Documents\PerFin")["decision"], "warn")
        self.assertEqual(self.check(r"\\nas\share\PerFin")["decision"], "warn")

    def test_inside_git_checkout_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, ".git"))
            data = os.path.join(tmp, "data")
            result = pc.evaluate_data_dir(data, env={})
            self.assertEqual(result["decision"], "refuse")

    def test_symlink_alias_into_checkout_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "repo", ".git"))
            os.makedirs(os.path.join(tmp, "repo", "sub"))
            outside = os.path.join(tmp, "outside")
            os.mkdir(outside)
            alias = os.path.join(outside, "alias")
            os.symlink(os.path.join(tmp, "repo", "sub"), alias)
            result = pc.evaluate_data_dir(os.path.join(alias, "data"), env={})
            self.assertEqual(result["decision"], "refuse")

    def test_this_checkout_refused(self):
        self.assertEqual(pc.evaluate_data_dir(REPO_ROOT / "data", env={})["decision"], "refuse")

    def test_temp_dir_outside_checkout_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            if pc.find_git_checkout(tmp) is None:
                self.assertEqual(pc.evaluate_data_dir(tmp, env={})["decision"], "ok")


class RedactionTests(unittest.TestCase):
    def test_backstop_rules(self):
        line = ("import failed row 12 card 4111 1111 1111 1111 acct 123456789 "
                "ssn 123-45-6789 mail alex@example.invalid iban GB82WEST12345698765432 "
                r"path C:\Users\alex\AppData\Local\PerFin\staging\b.csv")
        out = pc.redact_log_text(line)
        for leaked in ["4111", "123456789", "123-45-6789", "alex@", "GB82", r"Users\alex"]:
            self.assertNotIn(leaked, out)
        for tag in ["[REDACTED-PAN]", "[REDACTED-DIGITS]", "[REDACTED-SSN]",
                    "[REDACTED-EMAIL]", "[REDACTED-IBAN]", "%USERPROFILE%"]:
            self.assertIn(tag, out)
        self.assertIn("row 12", out)

    def test_posix_home_and_dates_kept(self):
        out = pc.redact_log_text("batch 2026-10-03 at /home/alex/.local/share/perfin")
        self.assertEqual(out, "batch 2026-10-03 at %USERPROFILE%/.local/share/perfin")

    def test_non_luhn_grouped_digits_still_redacted(self):
        self.assertEqual(pc.redact_log_text("1234 5678 9012 3456"), "[REDACTED-DIGITS]")


class ExportGateTests(unittest.TestCase):
    def setUp(self):
        self.cfg = pc.load_defaults()
        ex = HERE / "examples"
        self.desc = pc.load_json(ex / "adapter-description.synthetic.json")
        self.req = pc.load_json(ex / "export-request.synthetic.json")
        self.resp = pc.load_json(ex / "export-response.synthetic.json")

    def gate(self, **kw):
        args = dict(defaults=self.cfg, feature_flag=True, description=self.desc,
                    request=self.req, response=self.resp, user_confirmed=True)
        args.update(kw)
        return pc.decide_export(**args)

    def test_examples_match_schema(self):
        for doc in (self.desc, self.req, self.resp):
            self.assertEqual(pc.validate_envelope(doc), [])

    def test_happy_path_requires_confirmation(self):
        self.assertEqual(self.gate(), (True, []))
        allowed, reasons = self.gate(user_confirmed=False)
        self.assertFalse(allowed)
        self.assertIn("confirmation", reasons[0])

    def test_feature_flag_off_by_default(self):
        self.assertFalse(self.gate(feature_flag=False)[0])

    def test_missing_adapter_disables_export(self):
        allowed, reasons = self.gate(description=None, response=None)
        self.assertFalse(allowed)
        self.assertIn("export disabled", reasons[0])

    def test_unsupported_adapter_disables_export(self):
        for change in [lambda d: d.update(contract_version="0.1.0") or d["adapter"].update(offline=False),
                       lambda d: d.update(payload_kinds=["text"])]:
            desc = copy.deepcopy(self.desc)
            change(desc)
            self.assertFalse(self.gate(description=desc)[0])
        bad_version = copy.deepcopy(self.desc)
        bad_version["contract_version"] = "1.0.0"
        self.assertFalse(self.gate(description=bad_version)[0])

    def test_non_ok_status_cancels(self):
        for status in ("refused", "unsupported", "error"):
            resp = copy.deepcopy(self.resp)
            resp["status"] = status
            self.assertFalse(self.gate(response=resp)[0], status)

    def test_raw_echo_rejected(self):
        raw = copy.deepcopy(self.resp)
        raw["records"] = copy.deepcopy(self.req["records"])
        allowed, reasons = self.gate(response=raw)
        self.assertFalse(allowed)
        self.assertIn("residual card number", reasons)
        self.assertIn("residual sensitive value", reasons)

    def test_amount_and_date_changes_rejected(self):
        for field, value in (("amount_minor", -10001), ("date", "2026-10-04"), ("currency", "EUR")):
            resp = copy.deepcopy(self.resp)
            resp["records"][0][field] = value
            allowed, reasons = self.gate(response=resp)
            self.assertFalse(allowed, field)
            self.assertIn("r1: %s changed" % field, reasons)

    def test_money_in_text_must_survive(self):
        req = copy.deepcopy(self.req)
        resp = copy.deepcopy(self.resp)
        req["records"][0]["memo"] = "split $1,234.56 on 2026-10-01"
        resp["records"][0]["memo"] = "split [AMOUNT] on 2026-10-01"
        self.assertIn("r1: money in memo changed", pc.check_fidelity(req, resp))
        resp["records"][0]["memo"] = "split $1,234.56 on [DATE]"
        self.assertIn("r1: dates in memo changed", pc.check_fidelity(req, resp))

    def test_deleted_unscrubbed_field_rejected(self):
        resp = copy.deepcopy(self.resp)
        resp["records"][0].pop("category")
        allowed, reasons = self.gate(response=resp)
        self.assertFalse(allowed)
        self.assertIn("r1: unscrubbed field category changed", reasons)
        resp = copy.deepcopy(self.resp)
        resp["records"][0].pop("memo")
        self.assertIn("r1: scrubbed field memo missing", pc.check_fidelity(self.req, resp))

    def test_whole_dollar_amounts_must_survive(self):
        req = copy.deepcopy(self.req)
        resp = copy.deepcopy(self.resp)
        req["records"][0]["memo"] = "I paid $100 for groceries, $1,250 rent"
        resp["records"][0]["memo"] = "I paid $900 for groceries, $1,250 rent"
        self.assertIn("r1: money in memo changed", pc.check_fidelity(req, resp))
        resp["records"][0]["memo"] = "I paid $100.00 for groceries, $1,250 rent"
        self.assertNotIn("r1: money in memo changed", pc.check_fidelity(req, resp))

    def test_record_count_change_rejected(self):
        resp = copy.deepcopy(self.resp)
        resp["records"].pop()
        self.assertIn("record count changed", pc.check_fidelity(self.req, resp))

    def test_unknown_field_rejected_by_schema(self):
        resp = copy.deepcopy(self.resp)
        resp["records"][0]["account_number"] = "x"
        self.assertFalse(self.gate(response=resp)[0])

    def test_text_payload(self):
        desc = copy.deepcopy(self.desc)
        desc["payload_kinds"] = ["text"]
        req = {k: v for k, v in self.req.items() if k != "records"}
        req.update(payload_kind="text", scrub_fields=["text"],
                   text="Alex Example paid 250.00 on 2026-10-15")
        resp = {k: v for k, v in self.resp.items() if k != "records"}
        resp["text"] = "[PERSON_1] paid 250.00 on 2026-10-15"
        self.assertEqual(self.gate(description=desc, request=req, response=resp), (True, []))
        resp["text"] = "Alex Example paid 250.00 on 2026-10-15"
        self.assertFalse(self.gate(description=desc, request=req, response=resp)[0])


    def test_non_selected_payload_rejected_and_scanned(self):
        resp = copy.deepcopy(self.resp)
        resp["text"] = "Alex Example " + make_luhn("4", 16) + " alex@example.invalid"
        allowed, reasons = self.gate(response=resp)
        self.assertFalse(allowed)
        self.assertIn("unexpected text payload in response", reasons)
        self.assertIn("residual card number", reasons)
        self.assertIn("residual email", reasons)


class RepoGuardTests(unittest.TestCase):
    def test_detects_forbidden_files_and_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fixtures").mkdir()
            (root / "fixtures" / "ok.csv").write_text("synthetic,4111111111111111\n")
            (root / "statement.pdf").write_bytes(b"%PDF-1.7")
            (root / "run.log").write_text("x")
            (root / "~$book.xlsx").write_text("x")
            (root / "notes.txt").write_text("card " + make_luhn("4000", 16))
            findings = pc.scan_repo_for_forbidden(root)
        joined = "\n".join(findings)
        self.assertIn("statement.pdf", joined)
        self.assertIn("run.log", joined)
        self.assertIn("~$book.xlsx", joined)
        self.assertIn("notes.txt", joined)
        self.assertNotIn("ok.csv", joined)

    def test_this_repository_is_clean(self):
        self.assertEqual(pc.scan_repo_for_forbidden(REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
