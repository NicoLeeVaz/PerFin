"""Staging scenarios from research/credit-card-mvp.md and issue #5 acceptance."""
import ast
import copy
import glob
import hashlib
import json
import os
import unittest

from import_support import (ROOT, STAGED_AT, FakeRepository, csv_bytes, fixture_bytes, profile, stage)
from perfin_contracts.semantic import validate_document
from perfin_import import IMPORTER_VERSION, ImportRefused, ProfileError, stage_file, summarize_batch

CARD = "synthetic_card_inverted"
CHK = "synthetic_checking_signed"
CARD_HEADER = "Trans Date,Post Date,Description,Amount,Reference\n"
CHK_HEADER = "Date,Description,Amount,Balance,Transaction ID\n"
RULES = [
    {"category_id": "int.card", "contains": ["interest charge"], "direction": "outflow"},
    {"category_id": "exp.shopping", "contains": ["synthetic shop"]},
    {"category_id": "exp.coffee", "contains": ["coffee"], "direction": "outflow"},
    {"category_id": "inc.salary", "contains": ["payroll"], "direction": "inflow"},
]


def card_bytes(*lines):
    return b"\xef\xbb\xbf" + csv_bytes(CARD_HEADER + "".join(l + "\n" for l in lines))


def chk_bytes(*lines):
    return csv_bytes(CHK_HEADER + "".join(l + "\n" for l in lines))


class SignTests(unittest.TestCase):
    def test_card_sign_inversion_refund_payment_interest(self):
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "card.csv", profile(CARD), "card:alpha",
                    category_rules=RULES)
        amounts = {r["parsed"]["description"]: r["parsed"]["amount_minor"] for r in res.rows}
        self.assertEqual(amounts["SYNTHETIC COFFEE"], -2000, "charge positive in file -> more owed (negative)")
        self.assertEqual(amounts["PAYMENT RECEIVED - THANK YOU"], 10000, "payment -> less owed (positive)")
        self.assertEqual(amounts["SYNTHETIC SHOP REFUND"], 2500, "refund -> less owed (positive)")
        self.assertEqual(amounts["INTEREST CHARGE"], -500)
        self.assertEqual(amounts["SYNTHETIC SHOP"], -125000)
        by_desc = {r["parsed"]["description"]: r for r in res.rows}
        refund = by_desc["SYNTHETIC SHOP REFUND"]["proposed_splits"]
        self.assertEqual(refund, [{"split_id": "p1", "split_kind": "category", "amount_minor": 2500,
                                   "category_id": "exp.shopping"}], "refund is a positive split that reduces spending")
        self.assertEqual(by_desc["INTEREST CHARGE"]["proposed_splits"][0]["category_id"], "int.card")
        self.assertNotIn("proposed_splits", by_desc["PAYMENT RECEIVED - THANK YOU"])
        self.assertEqual(res.rows[0]["parsed"]["transaction_date"], "2026-06-30")
        self.assertEqual(res.rows[0]["parsed"]["posted_date"], "2026-07-01")

    def test_checking_as_is_and_parentheses(self):
        res = stage(self, fixture_bytes("synthetic_checking_signed.csv"), "chk.csv", profile(CHK), "chk:main",
                    category_rules=RULES)
        got = [r["parsed"]["amount_minor"] for r in res.rows]
        self.assertEqual(got, [-4510, -500, -10000, -100, -250, 123456, 0, 200000])
        self.assertEqual(res.rows[0]["parsed"]["running_balance_minor"], 195490)
        self.assertEqual(res.rows[7]["proposed_splits"][0]["category_id"], "inc.salary")

    def test_debit_credit_canonical_sign(self):
        res = stage(self, fixture_bytes("synthetic_checking_debit_credit.cp1252.csv"), "dc.csv",
                    profile("synthetic_checking_debit_credit"), "chk:main")
        self.assertEqual([r["parsed"]["amount_minor"] for r in res.rows], [-450, 25000, -1200])

    def test_debit_credit_ambiguities_rejected(self):
        prof = profile("synthetic_checking_debit_credit")
        hdr = "Posting Date,Transaction Date,Details,Debit,Credit\n"
        lines = ["7/1/2026,,SYNTHETIC BOTH,1.00,2.00", "7/1/2026,,SYNTHETIC NEITHER,,",
                 "7/1/2026,,SYNTHETIC SIGNED,-1.00,", "7/1/2026,,SYNTHETIC ZERO OTHER,0.00,3.00",
                 "7/1/2026,7/2/2026,SYNTHETIC LATE TXN DATE,1.00,"]
        res = stage(self, csv_bytes(hdr + "\n".join(lines) + "\n", "cp1252"), "dc.csv", prof, "chk:main")
        codes = [[e["code"] for e in r["errors"]] for r in res.rows]
        self.assertEqual(codes, [["E_PARSE_AMOUNT"], ["E_PARSE_AMOUNT"], ["E_PARSE_AMOUNT"], [], ["E_DATE_ORDER"]])
        self.assertEqual(res.rows[3]["parsed"]["amount_minor"], 300)
        self.assertIsNone(res.rows[3]["parsed"]["transaction_date"], "empty optional date stays null, never today")


class DuplicateTests(unittest.TestCase):
    def test_two_genuine_identical_purchases_kept_with_distinct_fingerprints(self):
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "card.csv", profile(CARD), "card:alpha")
        a, b = res.rows[0], res.rows[1]
        self.assertEqual(a["raw_fields"], b["raw_fields"])
        self.assertNotEqual(a["fingerprint"], b["fingerprint"])
        self.assertEqual(a["duplicate"]["status"], "none")
        self.assertEqual(b["duplicate"]["status"], "possible", "a human confirms the repeat; nothing is dropped")
        self.assertEqual(b["duplicate"]["matched_row_number"], 1)
        self.assertEqual(b["review_state"], "needs_review")
        self.assertEqual(len(res.rows), 6)

    def test_identical_rows_with_distinct_source_ids_are_not_flagged(self):
        res = stage(self, card_bytes("07/01/2026,07/01/2026,SYNTHETIC COFFEE,20.00,R-1",
                                     "07/01/2026,07/01/2026,SYNTHETIC COFFEE,20.00,R-2"),
                    "c.csv", profile(CARD), "card:alpha")
        self.assertEqual([r["duplicate"]["status"] for r in res.rows], ["none", "none"])

    def test_fingerprints_deterministic(self):
        data = fixture_bytes("synthetic_card_inverted.csv")
        a = stage(self, data, "card.csv", profile(CARD), "card:alpha").document
        b = stage(self, data, "card.csv", profile(CARD), "card:alpha").document
        self.assertEqual(a, b)
        c = stage(self, data, "card.csv", profile(CARD), "card:beta").document
        self.assertNotEqual([r["fingerprint"] for r in a["rows"]], [r["fingerprint"] for r in c["rows"]],
                            "fingerprints are scoped to the account")
        for r in a["rows"]:
            self.assertRegex(r["fingerprint"], "^[0-9a-f]{64}$")

    def test_replay_of_same_file_is_exact_reimport(self):
        repo = FakeRepository()
        data = fixture_bytes("synthetic_card_inverted.csv")
        first = stage(self, data, "card.csv", profile(CARD), "card:alpha", repo)
        for status in ("staged", "committed"):
            repo.batches = []
            repo.remember_batch(first.document, status)
            again = stage(self, data, "card_copy.csv", profile(CARD), "card:alpha", repo,
                          staged_at="2026-07-11T08:00:00Z")
            self.assertTrue(all(r["duplicate"]["status"] == "exact_reimport" for r in again.rows))
            self.assertTrue(all(r["review_state"] == "rejected" for r in again.rows))
            self.assertIn(first.document["batch"]["batch_id"], again.rows[0]["duplicate"]["evidence"])
            self.assertEqual(again.summary["file_replay_of_batch"], first.document["batch"]["batch_id"])
            self.assertEqual(again.summary["duplicate"]["exact_reimport"], 6)
            self.assertEqual(repo.writes, [])

    def test_replay_is_scoped_to_account_and_live_batches(self):
        data = fixture_bytes("synthetic_card_inverted.csv")
        repo = FakeRepository()
        first = stage(self, data, "card.csv", profile(CARD), "card:alpha", repo)
        repo.remember_batch(first.document, "committed")
        other = stage(self, data, "card.csv", profile(CARD), "card:beta", repo)
        self.assertEqual(other.summary["duplicate"]["exact_reimport"], 0)
        for status in ("rolled_back", "rejected"):
            repo.batches = []
            repo.remember_batch(first.document, status)
            res = stage(self, data, "card.csv", profile(CARD), "card:alpha", repo)
            self.assertIsNone(res.summary["file_replay_of_batch"], status)

    def test_overlapping_export_rows_become_possible(self):
        repo = FakeRepository()
        first = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "card.csv", profile(CARD), "card:alpha", repo)
        for i, r in enumerate(first.rows, start=1):  # pretend 2b committed them
            p = r["parsed"]
            repo.transactions.append({"transaction_id": "t%03d" % i, "account_id": "card:alpha",
                                      "posted_date": p["posted_date"], "amount_minor": p["amount_minor"],
                                      "description": p["description"], "source_txn_id": p["source_txn_id"],
                                      "fingerprint": r["fingerprint"]})
        overlap = card_bytes("06/30/2026,07/01/2026,SYNTHETIC COFFEE,20.00,",
                             "06/30/2026,07/01/2026,SYNTHETIC COFFEE,20.00,",
                             "07/05/2026,07/05/2026,INTEREST CHARGE,5.00,CARD-0005",
                             "07/20/2026,07/20/2026,SYNTHETIC NEW,3.00,CARD-0099")
        res = stage(self, overlap, "card_overlap.csv", profile(CARD), "card:alpha", repo)
        s = [(r["duplicate"]["status"], r["duplicate"].get("matched_transaction_id")) for r in res.rows]
        self.assertEqual(s[0], ("possible", "t001"))
        self.assertEqual(s[1][0], "possible")
        self.assertEqual(s[2], ("exact_reimport", "t005"), "same account + source id + fingerprint")
        self.assertEqual(s[3], ("none", None))
        self.assertEqual(res.rows[2]["review_state"], "rejected")

    def test_same_source_id_on_two_accounts_is_not_a_duplicate(self):
        repo = FakeRepository(transactions=[
            {"transaction_id": "tb1", "account_id": "card:beta", "posted_date": "2026-07-03",
             "amount_minor": 10000, "description": "PAYMENT RECEIVED - THANK YOU", "source_txn_id": "CARD-0003"}])
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "card.csv", profile(CARD), "card:alpha", repo)
        row = res.rows[2]
        self.assertEqual(row["parsed"]["source_txn_id"], "CARD-0003")
        self.assertEqual(row["duplicate"]["status"], "none")

    def test_same_source_id_same_account_different_details_is_possible(self):
        repo = FakeRepository(transactions=[
            {"transaction_id": "ta1", "account_id": "card:alpha", "posted_date": "2026-06-01",
             "amount_minor": -77, "description": "SYNTHETIC OTHER", "source_txn_id": "CARD-0003"}])
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "card.csv", profile(CARD), "card:alpha", repo)
        self.assertEqual(res.rows[2]["duplicate"]["status"], "possible")
        self.assertEqual(res.rows[2]["duplicate"]["matched_transaction_id"], "ta1")

    def test_repeated_source_id_within_file(self):
        res = stage(self, card_bytes("07/01/2026,07/01/2026,SYNTHETIC A,1.00,DUP-1",
                                     "07/02/2026,07/02/2026,SYNTHETIC B,2.00,DUP-1"),
                    "c.csv", profile(CARD), "card:alpha")
        self.assertEqual(res.rows[1]["duplicate"], {"status": "possible", "matched_row_number": 1,
                                                    "evidence": "same source transaction id earlier in this file"})

    def test_possible_duplicates_against_ledger(self):
        repo = FakeRepository(transactions=[
            {"transaction_id": "t1", "account_id": "chk:main", "posted_date": "2026-07-01", "amount_minor": -4510,
             "description": "SYNTHETIC OTHER NAME"},
            {"transaction_id": "t2", "account_id": "chk:main", "posted_date": "2026-07-06", "amount_minor": 200000,
             "description": "synthetic   payroll"},
            {"transaction_id": "t3", "account_id": "chk:main", "posted_date": "2026-07-02", "amount_minor": -500,
             "description": "SYNTHETIC ELSEWHERE", "source_txn_id": "CHK-OTHER"},
            {"transaction_id": "t4", "account_id": "sav:main", "posted_date": "2026-07-04", "amount_minor": -100,
             "description": "=SUM(A1:A9)"},
        ])
        res = stage(self, fixture_bytes("synthetic_checking_signed.csv"), "chk.csv", profile(CHK), "chk:main", repo)
        d = {r["row_number"]: r["duplicate"] for r in res.rows}
        self.assertEqual((d[1]["status"], d[1]["matched_transaction_id"]), ("possible", "t1"))  # same date+amount
        self.assertEqual((d[8]["status"], d[8]["matched_transaction_id"]), ("possible", "t2"))  # desc within window
        self.assertEqual(d[2]["status"], "none", "different issuer ids on the same account are distinct")
        self.assertEqual(d[4]["status"], "none", "other accounts are never duplicate candidates")
        self.assertEqual(res.summary["review_state"]["needs_review"], 2)


class TransferTests(unittest.TestCase):
    def test_transfer_candidate_on_other_account(self):
        repo = FakeRepository(transactions=[
            {"transaction_id": "tc1", "account_id": "card:alpha", "posted_date": "2026-07-05",
             "amount_minor": 10000, "description": "PAYMENT RECEIVED"},
            {"transaction_id": "tc2", "account_id": "chk:main", "posted_date": "2026-07-03",
             "amount_minor": 10000, "description": "SAME ACCOUNT, IGNORED"},
        ])
        res = stage(self, fixture_bytes("synthetic_checking_signed.csv"), "chk.csv", profile(CHK), "chk:main", repo,
                    category_rules=[{"category_id": "exp.misc", "contains": ["payment"]}])
        row = res.rows[2]
        self.assertEqual(row["transfer_candidate_transaction_id"], "tc1")
        self.assertNotIn("proposed_splits", row, "a transfer candidate is never proposed as an expense")
        self.assertEqual(row["review_state"], "pending")
        self.assertEqual(res.summary["transfer_candidates"], 1)

    def test_ambiguous_transfer_needs_review(self):
        legs = [{"transaction_id": tid, "account_id": acct, "posted_date": "2026-07-03", "amount_minor": 10000,
                 "description": "PAYMENT"} for tid, acct in (("x1", "card:alpha"), ("x2", "card:beta"))]
        res = stage(self, fixture_bytes("synthetic_checking_signed.csv"), "chk.csv", profile(CHK), "chk:main",
                    FakeRepository(transactions=legs))
        row = res.rows[2]
        self.assertNotIn("transfer_candidate_transaction_id", row)
        self.assertEqual(row["review_state"], "needs_review")
        self.assertEqual(res.summary["transfer_ambiguous_rows"], [3])

    def test_transfer_outside_window_or_linked_ignored(self):
        repo = FakeRepository(transactions=[
            {"transaction_id": "far", "account_id": "card:alpha", "posted_date": "2026-07-20", "amount_minor": 10000,
             "description": "P"},
            {"transaction_id": "lnk", "account_id": "card:beta", "posted_date": "2026-07-03", "amount_minor": 10000,
             "description": "P", "linked": True}])
        res = stage(self, fixture_bytes("synthetic_checking_signed.csv"), "chk.csv", profile(CHK), "chk:main", repo)
        self.assertNotIn("transfer_candidate_transaction_id", res.rows[2])


class MalformedAndSummaryTests(unittest.TestCase):
    def test_partial_invalid_import_stays_staged_with_summary(self):
        res = stage(self, fixture_bytes("synthetic_checking_malformed.csv"), "bad.csv", profile(CHK), "chk:main")
        codes = {r["row_number"]: [e["code"] for e in r["errors"]] for r in res.rows}
        self.assertEqual(codes, {1: [], 2: ["E_PARSE_DATE"], 3: ["E_PARSE_AMOUNT"], 4: ["E_PARSE_FIELD_COUNT"],
                                 5: ["E_PARSE_FIELD_COUNT"], 6: ["E_PARSE_AMOUNT"], 7: ["E_PARSE_DATE"],
                                 8: ["E_PARSE_DATE"]})
        for r in res.rows[1:]:
            self.assertIsNone(r["parsed"], "never coerced to 0 or today")
            self.assertEqual(r["review_state"], "needs_review")
        self.assertEqual(res.rows[3]["raw_fields"], ["07/03/2026", "SYNTHETIC TOO FEW", "-1.00"])
        self.assertEqual(res.document["batch"]["batch_status"], "staged")
        self.assertEqual(res.summary["review_state"], {"pending": 1, "needs_review": 7, "approved": 0, "rejected": 0})
        self.assertEqual(res.summary["error_codes"], {"E_PARSE_AMOUNT": 2, "E_PARSE_DATE": 3, "E_PARSE_FIELD_COUNT": 2})
        self.assertEqual(res.summary["rows"], 8)
        self.assertEqual(res.summary["parsed"], 1)
        self.assertEqual(summarize_batch(res.document)["rows_with_errors"], 7)

    def test_all_errors_on_a_row_are_reported(self):
        res = stage(self, chk_bytes("13/45/2026,SYNTHETIC,1.2.3,x,E-1"), "e.csv", profile(CHK), "chk:main")
        self.assertEqual(sorted(e["code"] for e in res.rows[0]["errors"]),
                         ["E_PARSE_AMOUNT", "E_PARSE_AMOUNT", "E_PARSE_DATE"])

    def test_error_messages_never_contain_values(self):
        res = stage(self, fixture_bytes("synthetic_checking_malformed.csv"), "bad.csv", profile(CHK), "chk:main")
        for r in res.rows:
            for e in r["errors"]:
                for f in r["raw_fields"]:
                    if len(f) > 2:
                        self.assertNotIn(f, e["message"])
        self.assertNotIn("SYNTHETIC", json.dumps(res.summary))

    def test_overlong_fields(self):
        long_desc = "SYNTHETIC " + "X" * 1200
        res = stage(self, chk_bytes("07/01/2026,%s,-1.00,1.00,L-1" % long_desc,
                                    "07/01/2026,%s,-1.00,1.00,L-2" % ("Y" * 4500)),
                    "l.csv", profile(CHK), "chk:main")
        self.assertEqual(res.rows[0]["errors"][0]["code"], "E_LENGTH")
        self.assertEqual(res.rows[0]["raw_fields"][1], long_desc, "raw text kept exactly")
        self.assertEqual(res.rows[1]["raw_fields"], [])
        self.assertEqual(res.rows[1]["errors"][0]["code"], "E_LENGTH")


class ProvenanceAndSafetyTests(unittest.TestCase):
    def test_provenance(self):
        data = fixture_bytes("synthetic_checking_signed.csv")
        for name in ("C:\\Users\\someone\\Downloads\\chk_2026-07.csv", "/home/someone/chk_2026-07.csv",
                     "chk_2026-07.csv"):
            res = stage(self, data, name, profile(CHK), "chk:main")
            b = res.document["batch"]
            self.assertEqual(b["source_file_name"], "chk_2026-07.csv")
            self.assertEqual(b["source_file_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual((b["account_id"], b["profile_id"], b["profile_version"], b["importer_version"]),
                             ("chk:main", CHK, "1.0.0", IMPORTER_VERSION))
            self.assertEqual(b["staged_at"], STAGED_AT)
            self.assertEqual([r["row_number"] for r in res.rows], list(range(1, 9)))
            self.assertNotIn("committed_at", b)

    def test_formula_like_descriptions_stay_exact(self):
        res = stage(self, fixture_bytes("synthetic_checking_signed.csv"), "chk.csv", profile(CHK), "chk:main")
        descs = [r["parsed"]["description"] for r in res.rows[3:7]]
        self.assertEqual(descs, ["=SUM(A1:A9)", "+SYNTHETIC PLUS", "@SYNTHETIC AT", "-SYNTHETIC DASH"])
        self.assertEqual(res.rows[3]["raw_fields"][1], "=SUM(A1:A9)")

    def test_refusals(self):
        data = fixture_bytes("synthetic_card_inverted.csv")
        cases = [("E_ACCOUNT_UNKNOWN", "card:nope", "card.csv", {}),
                 ("E_ACCOUNT_KIND", "chk:main", "card.csv", {}),
                 ("E_PATTERN", "card:alpha", "C:\\dir\\", {}),
                 ("E_PATTERN", "card:alpha", "x" * 201, {}),
                 ("E_PATTERN", "card:alpha", "card.csv", {"staged_at": "2026-07-10 12:00"}),
                 ("E_DATE_INVALID", "card:alpha", "card.csv", {"staged_at": "2026-02-30T00:00:00Z"})]
        for code, acct, name, kw in cases:
            repo = FakeRepository()
            with self.assertRaises(ImportRefused, msg=code) as cm:
                stage_file(data, name, profile(CARD), acct, repo, validator=validate_document,
                           **dict({"staged_at": STAGED_AT}, **kw))
            self.assertEqual(cm.exception.code, code)
            self.assertEqual(repo.writes, [])
        repo = FakeRepository(accounts=[{"account_id": "card:alpha", "account_class": "credit_card", "currency": "EUR"}])
        with self.assertRaises(ImportRefused) as cm:
            stage_file(data, "card.csv", profile(CARD), "card:alpha", repo, staged_at=STAGED_AT)
        self.assertEqual(cm.exception.code, "E_CURRENCY_MISMATCH")
        with self.assertRaises(ImportRefused):
            stage_file(data.decode("utf-8-sig"), "card.csv", profile(CARD), "card:alpha", FakeRepository())

    def test_invalid_category_rules_refused(self):
        for rules in ([{"category_id": "bad id", "contains": ["x"]}], [{"category_id": "c", "contains": []}],
                      [{"category_id": "c", "contains": ["x"], "direction": "sideways"}],
                      [{"category_id": "c", "contains": ["x"], "regex": ".*"}]):
            with self.assertRaises(ProfileError):
                stage(self, fixture_bytes("synthetic_card_inverted.csv"), "c.csv", profile(CARD), "card:alpha",
                      category_rules=rules)

    def test_category_rules_first_match_wins(self):
        rules = [{"category_id": "exp.first", "contains": ["synthetic"]}, {"category_id": "exp.second",
                                                                           "contains": ["coffee"]}]
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "c.csv", profile(CARD), "card:alpha",
                    category_rules=rules)
        self.assertEqual(res.rows[0]["proposed_splits"][0]["category_id"], "exp.first")
        self.assertNotIn("proposed_splits", res.rows[2], "no rule, no guess")

    def test_no_ledger_writes_before_approval(self):
        repo = FakeRepository()
        for name, pid, acct in (("synthetic_checking_signed.csv", CHK, "chk:main"),
                                ("synthetic_card_inverted.csv", CARD, "card:alpha"),
                                ("synthetic_checking_malformed.csv", CHK, "chk:main")):
            res = stage(self, fixture_bytes(name), name, profile(pid), acct, repo, category_rules=RULES)
            self.assertFalse(any(r["review_state"] == "approved" for r in res.rows), "approval is a human command")
        self.assertEqual(repo.writes, [])
        self.assertTrue(repo.calls)
        self.assertTrue(set(repo.calls) <= {"get_account", "prior_batches", "find_candidates",
                                            "find_by_source_txn_id", "find_transfer_candidates"})

    def test_static_no_logging_network_or_2b_imports(self):
        banned = {"logging", "socket", "urllib", "http", "requests", "ssl", "ftplib", "smtplib", "perfin_store",
                  "pyodbc", "subprocess"}
        for path in glob.glob(os.path.join(ROOT, "src", "perfin_import", "*.py")):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module]
                for n in names:
                    self.assertNotIn(n.split(".")[0], banned, path)
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                    self.fail("print() in %s" % path)

    def test_every_generated_batch_passes_contract_and_tamper_is_caught(self):
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "c.csv", profile(CARD), "card:alpha",
                    category_rules=RULES)
        bad = copy.deepcopy(res.document)
        bad["rows"][1]["review_state"] = "approved"  # unresolved possible duplicate
        self.assertIn("E_DUPLICATE_UNRESOLVED", {c for c, _, _ in validate_document(bad)})
        bad = copy.deepcopy(res.document)
        bad["batch"]["batch_status"] = "approved"
        self.assertIn("E_BATCH_STATE", {c for c, _, _ in validate_document(bad)})


if __name__ == "__main__":
    unittest.main()
