"""Declarative profiles: contract validity, user mapping, unknown formats, extension."""
import copy
import glob
import json
import os
import unittest

from import_support import FIXTURES, ROOT, csv_bytes, fixture_bytes, profile, stage
from perfin_contracts.semantic import validate_document
from perfin_import import (ProfileError, UnknownFormat, builtin_profiles, load_profile, load_profiles_dir,
                           match_profiles, profile_from_mapping)
from perfin_import.profiles import BUILTIN_DIR

SRC = os.path.join(ROOT, "src", "perfin_import")


class BuiltinProfileTests(unittest.TestCase):
    def test_every_shipped_profile_passes_contract(self):
        paths = sorted(glob.glob(os.path.join(BUILTIN_DIR, "*.json"))) + \
            sorted(glob.glob(os.path.join(FIXTURES, "profiles", "*.json")))
        self.assertGreaterEqual(len(paths), 4)
        for p in paths:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            self.assertEqual(validate_document(doc), [], p)

    def test_three_sign_conventions_present(self):
        rules = {pid: p["amount"]["sign_rule"] for (pid, _), p in builtin_profiles().items()}
        self.assertEqual(rules, {"synthetic_checking_signed": "as_is",
                                 "synthetic_checking_debit_credit": "debit_credit_columns",
                                 "synthetic_card_inverted": "invert"})

    def test_marked_synthetic_and_unverified(self):
        for (pid, _), p in builtin_profiles().items():
            self.assertTrue(pid.startswith("synthetic_"))
            self.assertIn("SYNTHETIC", p["description"])
            self.assertIn("not verified against any real institution", p["description"])

    def test_invalid_profiles_rejected(self):
        base = profile("synthetic_checking_signed")
        cases = {
            "bad enum": lambda d: d["file"].__setitem__("encoding", "utf-16"),
            "unknown field": lambda d: d.__setitem__("card_number", "4111111111111111"),
            "amount missing": lambda d: d["columns"].__setitem__("amount", None),
            "same separators": lambda d: d["amount"].__setitem__("thousands_separator", "."),
            "future minor": lambda d: d.__setitem__("contract_version", "1.1.0"),
            "duplicate column": lambda d: d["columns"].__setitem__("source_txn_id", "Amount"),
            "dedupe on unmapped column": lambda d: d.__setitem__("dedupe_key", ["transaction_date"]),
            "wrong doc type": lambda d: d.__setitem__("document_type", "staging_batch"),
        }
        for name, mutate in cases.items():
            doc = copy.deepcopy(base)
            mutate(doc)
            with self.assertRaises(ProfileError, msg=name):
                load_profile(doc)

    def test_headerless_profile_needs_column_numbers(self):
        doc = copy.deepcopy(profile("synthetic_checking_signed"))
        doc["file"]["header_rows"] = 0
        with self.assertRaises(ProfileError):
            load_profile(doc)
        doc["columns"] = {"posted_date": "1", "description": "2", "amount": "3", "running_balance": "4",
                          "source_txn_id": "5"}
        load_profile(doc)
        data = csv_bytes("07/01/2026,SYNTHETIC NO HEADER,-1.00,1.00,H-1\n")
        res = stage(self, data, "h.csv", doc, "chk:main")
        self.assertEqual(res.rows[0]["parsed"]["amount_minor"], -100)
        self.assertEqual(res.rows[0]["row_number"], 1)


class UnknownFormatTests(unittest.TestCase):
    def test_header_mismatch_requires_review(self):
        data = csv_bytes("When,What,How Much\n07/01/2026,SYNTHETIC,-1.00\n")
        with self.assertRaises(UnknownFormat) as cm:
            stage(self, data, "u.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertEqual(cm.exception.found_headers, ["When", "What", "How Much"])
        self.assertIn("posted_date", cm.exception.missing)

    def test_no_fuzzy_header_matching(self):
        for header in ("date,Description,Amount,Balance,Transaction ID",
                       "Date ,Description,Amount,Balance,Transaction ID",
                       "Date,Description,Amount,Amount,Balance"):
            with self.assertRaises(UnknownFormat, msg=header):
                stage(self, csv_bytes(header + "\n"), "u.csv", profile("synthetic_checking_signed"), "chk:main")

    def test_header_width_must_match_expected_field_count(self):
        data = csv_bytes("Date,Description,Amount,Balance,Transaction ID,Extra\n")
        with self.assertRaises(UnknownFormat):
            stage(self, data, "u.csv", profile("synthetic_checking_signed"), "chk:main")

    def test_match_profiles_never_guesses(self):
        profiles = builtin_profiles()
        for name, pid in (("synthetic_checking_signed.csv", "synthetic_checking_signed"),
                          ("synthetic_card_inverted.csv", "synthetic_card_inverted"),
                          ("synthetic_checking_debit_credit.cp1252.csv", "synthetic_checking_debit_credit")):
            hits = match_profiles(fixture_bytes(name), profiles)
            self.assertEqual([h["profile_id"] for h in hits], [pid], name)
        self.assertEqual(match_profiles(csv_bytes("When,What,How Much\n"), profiles), [])
        twin = copy.deepcopy(profile("synthetic_checking_signed"))
        twin["profile_id"] = "synthetic_checking_signed_twin"
        hits = match_profiles(fixture_bytes("synthetic_checking_signed.csv"), [profile("synthetic_checking_signed"), twin])
        self.assertEqual(len(hits), 2, "two matching profiles are both reported; the user chooses")


class UserMappingTests(unittest.TestCase):
    def test_mapping_builds_valid_profile_and_stages(self):
        data = csv_bytes("When,What,How Much,Ref\n03/04/2026,SYNTHETIC MAPPED,\"(1.234,50)\",U-1\n")
        prof = profile_from_mapping({"When": "posted_date", "What": "description", "How Much": "amount",
                                     "Ref": "source_txn_id"},
                                    profile_id="user_mapped", profile_version="1.0.0", account_class="checking",
                                    date_format="DD/MM/YYYY", sign_rule="as_is", decimal_separator=",",
                                    thousands_separator=".", parentheses_negative=True, expected_field_count=4,
                                    currency="USD")
        self.assertEqual(validate_document(prof), [])
        self.assertIn("not verified", prof["description"].lower())
        row = stage(self, data, "u.csv", prof, "chk:main").rows[0]
        self.assertEqual(row["parsed"]["posted_date"], "2026-04-03")
        self.assertEqual(row["parsed"]["amount_minor"], -123450)

    def test_mapping_debit_credit(self):
        prof = profile_from_mapping({"D": "posted_date", "T": "description", "Out": "debit", "In": "credit"},
                                    profile_id="user_dc", profile_version="1.0.0", account_class="credit_card",
                                    date_format="YYYY-MM-DD", sign_rule="debit_credit_columns",
                                    decimal_separator=".")
        self.assertIsNone(prof["columns"]["amount"])
        res = stage(self, csv_bytes("D,T,Out,In\n2026-07-01,SYNTHETIC CHARGE,9.99,\n2026-07-02,SYNTHETIC PAY,,50.00\n"),
                    "u.csv", prof, "card:alpha")
        self.assertEqual([r["parsed"]["amount_minor"] for r in res.rows], [-999, 5000])

    def test_mapping_validated_like_any_profile(self):
        kw = dict(profile_id="user_bad", profile_version="1.0.0", account_class="checking",
                  date_format="YYYY-MM-DD", sign_rule="as_is", decimal_separator=".")
        with self.assertRaises(ProfileError):
            profile_from_mapping({"A": "posted_date", "B": "description"}, **kw)  # no amount
        with self.assertRaises(ProfileError):
            profile_from_mapping({"A": "posted_date", "B": "description", "C": "amount", "D": "card_number"}, **kw)
        with self.assertRaises(ProfileError):
            profile_from_mapping({"A": "posted_date", "B": "description", "C": "amount"},
                                 **dict(kw, date_format="DD-MM-YY"))
        with self.assertRaises(ProfileError):
            profile_from_mapping({"A": "posted_date", "B": "description", "C": "amount"},
                                 **dict(kw, profile_id="bad id with spaces"))
        with self.assertRaises(ProfileError):
            profile_from_mapping({}, **kw)


class ExtensionTests(unittest.TestCase):
    """docs/import/README.md worked example: a new format added purely as data."""

    def test_extension_profile_loads_and_stages(self):
        extra = load_profiles_dir(os.path.join(FIXTURES, "profiles"))
        prof = extra[("synthetic_eu_semicolon", "1.0.0")]
        self.assertEqual([h["profile_id"] for h in match_profiles(fixture_bytes("synthetic_eu_semicolon.cp1252.csv"),
                                                                  extra)], ["synthetic_eu_semicolon"])
        res = stage(self, fixture_bytes("synthetic_eu_semicolon.cp1252.csv"), "eu.csv", prof, "sav:main")
        self.assertEqual([(r["parsed"]["posted_date"], r["parsed"]["amount_minor"]) for r in res.rows],
                         [("2026-04-03", 123456), ("2024-02-29", -1000)])
        self.assertEqual(res.rows[0]["parsed"]["description"], "SYNTHETIC ZINSEN ÜBERTRAG")
        self.assertEqual(res.summary["footer_records_skipped"], 1)
        self.assertEqual(res.document["batch"]["profile_id"], "synthetic_eu_semicolon")

    def test_core_code_does_not_know_the_extension(self):
        for path in glob.glob(os.path.join(SRC, "*.py")):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("synthetic_eu_semicolon", text, path)
            self.assertNotIn("Booking Date", text, path)

    def test_extension_profile_lives_outside_package(self):
        self.assertFalse(os.path.exists(os.path.join(BUILTIN_DIR, "synthetic_eu_semicolon.json")))


if __name__ == "__main__":
    unittest.main()
