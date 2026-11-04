"""Repository command flow against the TEST-ONLY fake adapter (repository logic, not ACE behaviour)."""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import synthetic as S  # noqa: E402
from fake_access import FakeEngineError, new_fake_store  # noqa: E402
from perfin_store.repository import NIL_UUID, StorageError, derive_id  # noqa: E402

sys.path.insert(0, str(ROOT / "contracts" / "python"))
from perfin_contracts.semantic import validate_document  # noqa: E402

B = "b.alpha.07"
SHA = S.card_batch()["batch"]["source_file_sha256"]


class Base(unittest.TestCase):
    def setUp(self):
        self.repo, self.ad, _ = new_fake_store()
        self.ok(self.repo.import_bundle(S.reference_bundle()))
        self.ok(self.repo.set_default_categories("exp.uncategorized", "inc.uncategorized"))

    # helpers -------------------------------------------------------------
    def ok(self, result):
        self.assertEqual(validate_document(result), [])
        self.assertEqual(result["result_status"], "accepted", result["errors"])
        return result

    def rejected(self, result, code):
        self.assertEqual(validate_document(result), [])
        self.assertEqual(result["result_status"], "rejected", result)
        self.assertIn(code, [e["code"] for e in result["errors"]], result["errors"])
        return result

    def run_cmd(self, ctype, payload, expected=()):
        return self.repo.execute(S.command(ctype, payload, list(expected)))

    def version(self, entity, eid):
        table, key = {"batch": ("import_batch", "batch_id"), "transaction": ("ledger_txn", "transaction_id"),
                      "transfer_link": ("transfer_link", "transfer_link_id"), "statement": ("statement", "statement_id"),
                      "reconciliation": ("reconciliation", "reconciliation_id"), "card_terms": ("card_terms", "terms_id"),
                      "asset_valuation": ("asset_valuation", "valuation_id")}[entity]
        return self.repo._one(table, {key: eid})["row_version"]

    def ev(self, entity, eid):
        return S.ev(entity, eid, self.version(entity, eid))

    def state(self):
        return copy.deepcopy(self.ad.db.rows)

    def stage_and_review(self):
        self.ok(self.repo.stage_batch(S.card_batch()))
        self.ok(self.run_cmd("approve_rows", {"batch_id": B, "row_numbers": [1, 2, 3, 6]}, [self.ev("batch", B)]))
        self.ok(self.run_cmd("reject_rows", {"batch_id": B, "row_numbers": [4], "reason": "bad"}, [self.ev("batch", B)]))
        self.ok(self.run_cmd("resolve_duplicate", {"batch_id": B, "row_number": 5, "resolution": "confirmed_duplicate"},
                             [self.ev("batch", B)]))
        self.ok(self.run_cmd("reject_rows", {"batch_id": B, "row_numbers": [5], "reason": "dup"}, [self.ev("batch", B)]))

    def commit(self):
        return self.run_cmd("commit_batch", {"batch_id": B, "source_file_sha256": SHA}, [self.ev("batch", B)])

    def manual_pair(self):
        """Checking -10000 and card +10000 posted as manual history (a card payment to be linked)."""
        bundle = {"contract": "perfin", "contract_version": "1.0.0", "document_type": "ledger_bundle", "base_currency": "USD",
                  "accounts": [], "categories": [], "transactions": [
                      {"transaction_id": "m1", "account_id": "chk:main", "posted_date": "2026-07-10", "amount_minor": -10000,
                       "currency": "USD", "description": "PAYMENT TO CARD", "entry_method": "manual", "row_version": 1,
                       "splits": [S.cat("m1.s1", -10000, "exp.uncategorized")]},
                      {"transaction_id": "m2", "account_id": "card:alpha", "posted_date": "2026-07-12", "amount_minor": 10000,
                       "currency": "USD", "description": "PAYMENT RECEIVED", "entry_method": "manual", "row_version": 1,
                       "splits": [S.cat("m2.s1", 10000, "inc.uncategorized")]}]}
        self.ok(self.repo.import_bundle(bundle))


class StagingAndReview(Base):
    def test_stage_never_touches_ledger(self):
        before = self.state()
        self.ok(self.repo.stage_batch(S.card_batch()))
        after = self.state()
        for t in ("ledger_txn", "split", "transfer_link"):
            self.assertEqual(before[t], after[t])
        self.assertEqual(len(after["staging_row"]), 6)
        doc = self.repo.export_staging_batch(B)
        self.assertEqual(validate_document(doc), [])
        self.assertEqual(doc["rows"][0]["raw_fields"], S.card_batch()["rows"][0]["raw_fields"])

    def test_restage_same_file_is_replay(self):
        self.ok(self.repo.stage_batch(S.card_batch()))
        again = S.card_batch("b.other.name")
        r = self.repo.stage_batch(again)
        self.assertEqual(r["result_status"], "replayed")
        self.assertEqual(r["errors"][0]["code"], "E_IDEMPOTENT_REPLAY")
        self.assertEqual(len(self.ad.db.rows["import_batch"]), 1)

    def test_unknown_account_rejected(self):
        self.rejected(self.repo.stage_batch(S.batch("b.x", "chk:nope", [S.row(1, "2026-07-01", -1, "x")])),
                      "E_ACCOUNT_UNKNOWN")

    def test_cannot_approve_error_or_duplicate_rows(self):
        self.ok(self.repo.stage_batch(S.card_batch()))
        before = self.state()
        r = self.rejected(self.run_cmd("approve_rows", {"batch_id": B, "row_numbers": [4, 5, 99]}, [self.ev("batch", B)]),
                          "E_ROW_UNRESOLVED")
        codes = [e["code"] for e in r["errors"]]
        self.assertEqual(codes, ["E_ROW_UNRESOLVED", "E_DUPLICATE_UNRESOLVED", "E_REF_UNKNOWN"])
        self.assertEqual(before, self.state())

    def test_resolve_only_possible(self):
        self.ok(self.repo.stage_batch(S.card_batch()))
        self.rejected(self.run_cmd("resolve_duplicate", {"batch_id": B, "row_number": 1, "resolution": "confirmed_distinct"},
                                   [self.ev("batch", B)]), "E_BATCH_STATE")
        self.ok(self.run_cmd("resolve_duplicate", {"batch_id": B, "row_number": 5, "resolution": "confirmed_distinct"},
                             [self.ev("batch", B)]))
        self.ok(self.run_cmd("approve_rows", {"batch_id": B, "row_numbers": [5]}, [self.ev("batch", B)]))

    def test_batch_status_follows_review(self):
        self.stage_and_review()
        self.assertEqual(self.repo._one("import_batch", {"batch_id": B})["batch_status"], "approved")
        self.assertEqual(self.version("batch", B), 5)


class Commit(Base):
    def test_commit_creates_validated_ledger_rows(self):
        self.stage_and_review()
        r = self.ok(self.commit())
        txns = {t["transaction_id"]: t for t in self.repo.export_bundle()["transactions"]}
        self.assertEqual(sorted(txns), ["b.alpha.07.r1", "b.alpha.07.r2", "b.alpha.07.r3", "b.alpha.07.r6"])
        t2 = txns["b.alpha.07.r2"]
        self.assertEqual([s["amount_minor"] for s in t2["splits"]], [-5000, -3000])
        self.assertEqual(t2["source"], {"batch_id": B, "row_number": 2})
        self.assertEqual(txns["b.alpha.07.r1"]["source"]["source_txn_id"], "SYN-1")
        self.assertEqual(txns["b.alpha.07.r3"]["splits"][0]["category_id"], "inc.uncategorized")  # default category
        self.assertEqual(validate_document(self.repo.export_bundle()), [])
        batch = self.repo._one("import_batch", {"batch_id": B})
        self.assertEqual((batch["batch_status"], batch["committed_at"]), ("committed", "2026-11-04T12:00:00Z"))
        self.assertIn({"entity": "batch", "entity_id": B, "row_version": 6}, r["affected"])
        log = self.repo._one("command_log", {"command_id": r["command_id"]})
        self.assertEqual(log["result_status"], "accepted")
        self.assertEqual(json.loads(log["result_json"]), r)

    def test_injected_failure_mid_commit_writes_nothing(self):
        self.stage_and_review()
        before = self.state()
        self.ad.fail_on("INSERT INTO [split]", nth=3)
        with self.assertRaises(StorageError) as cm:
            self.commit()
        self.assertIsInstance(cm.exception.__cause__, FakeEngineError)
        self.assertEqual(before, self.state())  # every table, including command_log and audit_log
        self.ok(self.commit())  # the same command flow succeeds afterwards

    def test_failure_at_commit_time_rolls_back(self):
        self.stage_and_review()
        before = self.state()
        self.ad.fail_commit = FakeEngineError("disk full")
        with self.assertRaises(StorageError):
            self.commit()
        self.assertEqual(before, self.state())

    def test_failure_in_audit_write_rolls_back(self):
        self.stage_and_review()
        before = self.state()
        self.ad.fail_on("INSERT INTO [audit_log]", nth=2)
        with self.assertRaises(StorageError):
            self.commit()
        self.assertEqual(before, self.state())

    def test_replay_same_file_changes_nothing(self):
        self.stage_and_review()
        self.ok(self.commit())
        before = self.state()
        r = self.commit()
        self.assertEqual(r["result_status"], "replayed")
        self.assertEqual(r["errors"][0]["code"], "E_IDEMPOTENT_REPLAY")
        self.assertEqual(before, self.state())
        stale = self.run_cmd("commit_batch", {"batch_id": B, "source_file_sha256": SHA}, [S.ev("batch", B, 1)])
        self.assertEqual(stale["result_status"], "replayed")  # replay wins over an old expected version

    def test_replay_same_command_id(self):
        self.stage_and_review()
        cmd = S.command("commit_batch", {"batch_id": B, "source_file_sha256": SHA}, [self.ev("batch", B)])
        self.ok(self.repo.execute(cmd))
        before = self.state()
        r = self.repo.execute(cmd)
        self.assertEqual((r["result_status"], r["errors"][0]["code"]), ("replayed", "E_IDEMPOTENT_REPLAY"))
        self.assertEqual(before, self.state())

    def test_commit_needs_all_rows_decided_and_matching_hash(self):
        self.ok(self.repo.stage_batch(S.card_batch()))
        self.rejected(self.commit(), "E_BATCH_STATE")
        self.rejected(self.run_cmd("commit_batch", {"batch_id": B, "source_file_sha256": "0" * 64}, [self.ev("batch", B)]),
                      "E_BATCH_STATE")
        self.rejected(self.run_cmd("commit_batch", {"batch_id": "nope", "source_file_sha256": SHA}), "E_REF_UNKNOWN")

    def test_row_without_splits_needs_default_category(self):
        self.ok(self.repo.set_default_categories(None, None))
        self.stage_and_review()
        before = self.state()
        r = self.rejected(self.commit(), "E_ROW_UNRESOLVED")
        self.assertIn("row_number=3", r["errors"][0]["path"])
        self.assertEqual(before, self.state())

    def test_unknown_proposed_category_rejected_before_writing(self):
        b = S.batch("b.badcat", "chk:main", [S.row(1, "2026-07-01", -100, "x", state="approved",
                                                    splits=[S.cat("p1", -100, "exp.nope")])])
        self.ok(self.repo.stage_batch(b))
        before = self.state()
        r = self.rejected(self.run_cmd("commit_batch", {"batch_id": "b.badcat", "source_file_sha256": b["batch"]["source_file_sha256"]},
                                       [self.ev("batch", "b.badcat")]), "E_CATEGORY_UNKNOWN")
        self.assertIn("proposed_splits", r["errors"][0]["path"])
        self.assertEqual(before, self.state())

    def test_source_id_already_in_ledger_is_a_duplicate(self):
        self.stage_and_review()
        self.ok(self.commit())
        b = S.batch("b.alpha.08", "card:alpha", [S.row(1, "2026-07-01", -1234, "SYNTHETIC CAFE", state="approved",
                                                        splits=[S.cat("p1", -1234, "exp.groceries")], source_txn_id="SYN-1")])
        self.ok(self.repo.stage_batch(b))
        self.rejected(self.run_cmd("commit_batch", {"batch_id": "b.alpha.08", "source_file_sha256": b["batch"]["source_file_sha256"]},
                                   [self.ev("batch", "b.alpha.08")]), "E_DUPLICATE_UNRESOLVED")


class ConcurrencyAndValidation(Base):
    def test_stale_version_rejected_and_changes_nothing(self):
        self.ok(self.repo.stage_batch(S.card_batch()))
        before = self.state()
        self.rejected(self.run_cmd("approve_rows", {"batch_id": B, "row_numbers": [1]}, [S.ev("batch", B, 7)]),
                      "E_STALE_VERSION")
        self.rejected(self.run_cmd("approve_rows", {"batch_id": B, "row_numbers": [1]}), "E_STALE_VERSION")
        self.assertEqual(before, self.state())
        self.assertEqual(self.ad.db.rows["command_log"], before["command_log"])  # rejected commands are not logged

    def test_invalid_documents_rejected(self):
        bad = S.command("approve_rows", {"batch_id": B, "row_numbers": []})
        self.rejected(self.repo.execute(bad), "E_COMMAND_PAYLOAD")
        self.rejected(self.repo.execute({"document_type": "ledger_bundle"}), "E_DOCUMENT_TYPE")
        future = S.command("approve_rows", {"batch_id": B, "row_numbers": [1]})
        future["contract_version"] = "1.1.0"
        self.rejected(self.repo.execute(future), "E_VERSION_UNSUPPORTED")
        r = self.repo.execute("not a document")
        self.assertEqual(r["command_id"], NIL_UUID)

    def test_payoff_scenarios_are_not_stored_here(self):
        cmd = json.loads((ROOT / "contracts" / "examples" / "valid" / "payoff_scenario.json").read_text(encoding="utf-8"))
        r = self.repo.execute(S.command("save_payoff_scenario", cmd["scenario"]))
        self.rejected(r, "E_COMMAND_PAYLOAD")

    def test_all_dml_is_parameterized(self):
        self.stage_and_review()
        self.ok(self.commit())
        dml = [sql for sql, _ in self.ad.statements]
        self.assertTrue(dml)
        for sql in dml:
            self.assertNotIn("'", sql)
            self.assertNotRegex(sql, r"=\s*[0-9]")


class EditsAndAudit(Base):
    def setUp(self):
        super().setUp()
        self.stage_and_review()
        self.ok(self.commit())
        self.tid = "b.alpha.07.r1"

    def audit(self, result):
        rows = {a["audit_id"]: a for a in self.ad.db.rows["audit_log"]}
        return [rows[i] for i in result["audit_ids"]]

    def test_edit_transaction_audits_before_and_after(self):
        r = self.ok(self.run_cmd("edit_transaction", {"transaction_id": self.tid, "reason": "fix amount",
                                                      "changes": {"amount_minor": -1300, "description": "CAFE"}},
                                 [self.ev("transaction", self.tid)]))
        t = self.repo.transaction(self.tid)
        self.assertEqual((t["amount_minor"], t["splits"][0]["amount_minor"], t["row_version"]), (-1300, -1300, 2))
        a = self.audit(r)[0]
        self.assertEqual((a["entity"], a["entity_id"], a["action"]), ("transaction", self.tid, "update"))
        self.assertEqual(json.loads(a["before_json"])["amount_minor"], -1234)
        self.assertEqual(json.loads(a["after_json"])["amount_minor"], -1300)
        self.assertEqual(json.loads(a["after_json"])["reason"], "fix amount")
        self.assertIn({"entity": "transaction", "entity_id": self.tid, "row_version": 2}, r["affected"])
        self.rejected(self.run_cmd("edit_transaction", {"transaction_id": self.tid, "reason": "again",
                                                        "changes": {"description": "x"}}, [S.ev("transaction", self.tid, 1)]),
                      "E_STALE_VERSION")

    def test_amount_edit_on_multi_split_needs_set_splits(self):
        tid = "b.alpha.07.r2"
        self.rejected(self.run_cmd("edit_transaction", {"transaction_id": tid, "reason": "r", "changes": {"amount_minor": -1}},
                                   [self.ev("transaction", tid)]), "E_SPLITS_UNBALANCED")

    def test_post_command_ledger_check_rejects_and_rolls_back(self):
        before = self.state()
        r = self.rejected(self.run_cmd("edit_transaction", {"transaction_id": self.tid, "reason": "r",
                                                            "changes": {"posted_date": "2026-05-01"}},
                                       [self.ev("transaction", self.tid)]), "E_DATE_ORDER")
        self.assertIn("post-command ledger check", r["errors"][0]["message"])
        self.assertEqual(before, self.state())

    def test_set_splits(self):
        tid = "b.alpha.07.r2"
        new = [S.cat("x1", -7000, "exp.household"), S.cat("x2", -1000, "exp.groceries")]
        self.ok(self.run_cmd("set_splits", {"transaction_id": tid, "splits": new}, [self.ev("transaction", tid)]))
        self.assertEqual([s["split_id"] for s in self.repo.transaction(tid)["splits"]], ["x1", "x2"])
        self.rejected(self.run_cmd("set_splits", {"transaction_id": tid, "splits": [S.cat("x3", -1, "exp.household")]},
                                   [self.ev("transaction", tid)]), "E_SPLITS_UNBALANCED")
        clash = [S.cat("b.alpha.07.r1.s1", -8000, "exp.household")]  # another transaction's split id
        self.rejected(self.run_cmd("set_splits", {"transaction_id": tid, "splits": clash}, [self.ev("transaction", tid)]),
                      "E_DUPLICATE_ID")
        adj = [{"split_id": "x9", "split_kind": "adjustment", "amount_minor": -8000}]
        self.rejected(self.run_cmd("set_splits", {"transaction_id": tid, "splits": adj}, [self.ev("transaction", tid)]),
                      "E_SPLIT_KIND")  # adjustments only on manual transactions

    def test_reverse_transaction_once(self):
        r = self.ok(self.run_cmd("reverse_transaction", {"transaction_id": self.tid, "reversal_transaction_id": "rv1",
                                                         "posted_date": "2026-07-20", "reason": "wrong card"},
                                 [self.ev("transaction", self.tid)]))
        rev = self.repo.transaction("rv1")
        self.assertEqual((rev["amount_minor"], rev["entry_method"], rev["reverses_transaction_id"]), (1234, "reversal", self.tid))
        self.assertEqual(rev["splits"][0]["category_id"], "exp.groceries")
        self.assertEqual(self.audit(r)[0]["action"], "reverse")
        self.rejected(self.run_cmd("reverse_transaction", {"transaction_id": self.tid, "reversal_transaction_id": "rv2",
                                                           "posted_date": "2026-07-21", "reason": "again"},
                                   [self.ev("transaction", self.tid)]), "E_DUPLICATE_ID")

    def test_rollback_batch_reverses_and_restores_balance(self):
        bal = lambda: self.repo.summary()["account_balances_minor"]["card:alpha"]  # noqa: E731
        self.assertEqual(bal(), -45000 - 1234 - 8000 + 10000 + 2500)
        self.ok(self.run_cmd("reverse_transaction", {"transaction_id": self.tid, "reversal_transaction_id": "rv1",
                                                     "posted_date": "2026-07-20", "reason": "single"},
                             [self.ev("transaction", self.tid)]))
        r = self.ok(self.run_cmd("rollback_batch", {"batch_id": B, "reason": "wrong file"}, [self.ev("batch", B)]))
        self.assertEqual(bal(), -45000)
        b = self.repo._one("import_batch", {"batch_id": B})
        self.assertEqual(b["batch_status"], "rolled_back")
        ids = {t["transaction_id"] for t in self.repo.export_bundle()["transactions"]}
        self.assertTrue({"b.alpha.07.r1", "b.alpha.07.r2.rev", "rv1"} <= ids)  # non-destructive
        self.assertNotIn("b.alpha.07.r1.rev", ids)  # already reversed individually
        self.assertEqual(sum(1 for a in self.audit(r) if a["action"] == "reverse"), 3)
        self.rejected(self.commit(), "E_BATCH_STATE")
        self.rejected(self.run_cmd("rollback_batch", {"batch_id": B, "reason": "again"}, [self.ev("batch", B)]), "E_BATCH_STATE")

    def test_rollback_refused_when_reconciled(self):
        self.ok(self.run_cmd("record_statement", {"statement_id": "st1", "account_id": "card:alpha", "period_start": "2026-07-01",
                                                  "period_end": "2026-07-31", "opening_balance_minor": -45000,
                                                  "closing_balance_minor": -46234}))
        self.ok(self.run_cmd("reconcile_statement", {"reconciliation_id": "rc1", "statement_id": "st1",
                                                     "included_transaction_ids": [self.tid], "difference_minor": 0,
                                                     "recon_status": "balanced"}))
        before = self.state()
        self.rejected(self.run_cmd("rollback_batch", {"batch_id": B, "reason": "x"}, [self.ev("batch", B)]), "E_BATCH_STATE")
        self.assertEqual(before, self.state())
        # editing a reconciled amount breaks the balanced reconciliation, so it is rejected
        self.rejected(self.run_cmd("edit_transaction", {"transaction_id": self.tid, "reason": "r",
                                                        "changes": {"amount_minor": -1}}, [self.ev("transaction", self.tid)]),
                      "E_RECON_MISMATCH")


class Transfers(Base):
    def setUp(self):
        super().setUp()
        self.manual_pair()

    def link(self, lid="L1", f="m1", t="m2"):
        return self.run_cmd("link_transfer", {"transfer_link_id": lid, "from_transaction_id": f, "to_transaction_id": t,
                                              "link_status": "confirmed", "match_evidence": "user confirmed"},
                            [self.ev("transaction", f), self.ev("transaction", t)])

    def test_link_makes_payment_not_spending(self):
        self.ok(self.link())
        for tid in ("m1", "m2"):
            s = self.repo.transaction(tid)["splits"]
            self.assertEqual([(x["split_kind"], x.get("category_id"), x["transfer_link_id"]) for x in s],
                             [("transfer", None, "L1")])
        self.assertEqual(validate_document(self.repo.export_bundle()), [])
        self.assertEqual(self.version("transaction", "m1"), 2)

    def test_link_rules(self):
        self.rejected(self.run_cmd("link_transfer", {"transfer_link_id": "L1", "from_transaction_id": "m2",
                                                     "to_transaction_id": "m1", "link_status": "confirmed"},
                                   [self.ev("transaction", "m1"), self.ev("transaction", "m2")]), "E_TRANSFER_AMOUNT")
        self.rejected(self.link(t="m1"), "E_TRANSFER_SAME_ACCOUNT")
        self.rejected(self.run_cmd("link_transfer", {"transfer_link_id": "L1", "from_transaction_id": "m1",
                                                     "to_transaction_id": "m2", "link_status": "confirmed"}),
                      "E_STALE_VERSION")
        self.ok(self.link())
        self.rejected(self.link(), "E_DUPLICATE_ID")
        self.rejected(self.link(lid="L2"), "E_TRANSFER_UNPAIRED")
        self.rejected(self.run_cmd("reverse_transaction", {"transaction_id": "m1", "reversal_transaction_id": "rvx",
                                                           "posted_date": "2026-07-20", "reason": "x"},
                                   [self.ev("transaction", "m1")]), "E_TRANSFER_UNPAIRED")
        self.rejected(self.run_cmd("edit_transaction", {"transaction_id": "m1", "reason": "x", "changes": {"amount_minor": -1}},
                                   [self.ev("transaction", "m1")]), "E_TRANSFER_AMOUNT")

    def test_unlink_restores_pre_link_splits(self):
        self.ok(self.link())
        r = self.ok(self.run_cmd("unlink_transfer", {"transfer_link_id": "L1", "reason": "not a payment"},
                                 [self.ev("transfer_link", "L1")]))
        self.assertEqual(self.repo.transaction("m1")["splits"], [S.cat("m1.s1", -10000, "exp.uncategorized")])
        self.assertEqual(self.repo.transaction("m2")["splits"], [S.cat("m2.s1", 10000, "inc.uncategorized")])
        self.assertEqual(self.ad.db.rows["transfer_link"], [])
        self.assertIn({"entity": "transfer_link", "entity_id": "L1", "row_version": 1}, r["affected"])

    def test_statement_payment_allocation(self):
        self.ok(self.link())
        st = {"statement_id": "st7", "account_id": "card:alpha", "period_start": "2026-07-01", "period_end": "2026-07-31",
              "due_date": "2026-08-25", "opening_balance_minor": -45000, "closing_balance_minor": -35000,
              "minimum_due_minor": 2500, "bucket_balances": [{"bucket_id": "purchase", "balance_minor": -35000}],
              "evidence_ref": "sha256:" + "a" * 64}
        self.ok(self.run_cmd("record_statement", st))
        self.rejected(self.run_cmd("allocate_statement_payment", {"allocation_id": "a1", "statement_id": "st7",
                                                                  "transaction_id": "m2", "amount_minor": 10001}),
                      "E_ALLOCATION_EXCEEDS")
        self.ok(self.run_cmd("allocate_statement_payment", {"allocation_id": "a1", "statement_id": "st7",
                                                            "transaction_id": "m2", "amount_minor": 10000}))
        self.rejected(self.run_cmd("allocate_statement_payment", {"allocation_id": "a2", "statement_id": "st7",
                                                                  "transaction_id": "m1", "amount_minor": 1}), "E_ACCOUNT_KIND")
        # unlinking would leave an allocation on a non-payment: rejected, nothing changes
        before = self.state()
        self.rejected(self.run_cmd("unlink_transfer", {"transfer_link_id": "L1", "reason": "x"}, [self.ev("transfer_link", "L1")]),
                      "E_ACCOUNT_KIND")
        self.assertEqual(before, self.state())
        self.ok(self.run_cmd("remove_statement_payment", {"allocation_id": "a1", "reason": "wrong statement"}))
        self.ok(self.run_cmd("unlink_transfer", {"transfer_link_id": "L1", "reason": "x"}, [self.ev("transfer_link", "L1")]))


class StatementsTermsValuations(Base):
    ST = {"statement_id": "st1", "account_id": "card:alpha", "period_start": "2026-06-01", "period_end": "2026-06-30",
          "opening_balance_minor": -45000, "closing_balance_minor": -45000}

    def test_statement_upsert_needs_version(self):
        self.ok(self.run_cmd("record_statement", self.ST))
        self.rejected(self.run_cmd("record_statement", dict(self.ST, due_date="2026-07-25")), "E_STALE_VERSION")
        self.ok(self.run_cmd("record_statement", dict(self.ST, due_date="2026-07-25"), [self.ev("statement", "st1")]))
        self.assertEqual(self.version("statement", "st1"), 2)

    def test_statement_rules(self):
        dup = dict(self.ST, bucket_balances=[{"bucket_id": "p", "balance_minor": -45000}, {"bucket_id": "p", "balance_minor": 0}])
        self.rejected(self.run_cmd("record_statement", dup), "E_DUPLICATE_ID")  # matches contract 1.0.1 (PR #18)
        self.rejected(self.run_cmd("record_statement", dict(self.ST, bucket_balances=[{"bucket_id": "p", "balance_minor": 1}])),
                      "E_BUCKET_SUM")
        self.rejected(self.run_cmd("record_statement", dict(self.ST, evidence_ref="C:\\Users\\me\\stmt.pdf")), "E_PATTERN")
        self.rejected(self.run_cmd("record_statement", dict(self.ST, account_id="chk:none")), "E_ACCOUNT_UNKNOWN")

    def test_reconciliation(self):
        self.ok(self.run_cmd("record_statement", self.ST))
        self.ok(self.run_cmd("reconcile_statement", {"reconciliation_id": "r1", "statement_id": "st1",
                                                     "included_transaction_ids": [], "difference_minor": 0,
                                                     "recon_status": "balanced"}))
        self.rejected(self.run_cmd("reconcile_statement", {"reconciliation_id": "r2", "statement_id": "st1",
                                                           "included_transaction_ids": [], "difference_minor": 5,
                                                           "recon_status": "in_progress"}), "E_RECON_MISMATCH")

    def test_card_terms_and_valuation(self):
        terms = {"terms_id": "ct1", "account_id": "card:alpha", "effective_from": "2026-01-01", "terms_source": "user_estimate",
                 "credit_limit_minor": 500000, "min_payment_rule": {"rule_type": "pct_plus_interest", "pct": "0.01",
                                                                    "floor_minor": 2500},
                 "apr_buckets": [{"bucket_id": "purchase", "bucket_kind": "purchase", "apr": "0.2499", "deferred_interest": False}]}
        self.ok(self.run_cmd("set_card_terms", terms))
        self.assertEqual([t for t in self.repo.export_bundle()["card_terms"]], [terms])
        self.rejected(self.run_cmd("set_card_terms", dict(terms, terms_id="ct2", account_id="chk:main")), "E_ACCOUNT_KIND")
        self.ok(self.run_cmd("set_card_terms", dict(terms, credit_limit_minor=None), [self.ev("card_terms", "ct1")]))
        val = {"valuation_id": "v1", "account_id": "re:home", "as_of": "2026-06-30", "value_minor": 45000000,
               "currency": "USD", "valuation_source": "synthetic appraisal", "valuation_method": "appraisal"}
        self.ok(self.run_cmd("record_valuation", val))
        self.rejected(self.run_cmd("record_valuation", dict(val, valuation_id="v2", account_id="card:alpha")), "E_ACCOUNT_KIND")


class BundleImport(Base):
    def test_household_example_round_trip(self):
        repo, ad, _ = new_fake_store()
        doc = json.loads((ROOT / "contracts" / "examples" / "valid" / "ledger_household.json").read_text(encoding="utf-8"))
        for t in doc["transactions"]:  # the example's imported row has no committed batch here
            if t.get("source"):
                t["entry_method"] = "manual"
                del t["source"]
        self.assertEqual(validate_document(doc), [])
        self.ok(repo.import_bundle(doc))
        out = repo.export_bundle()
        self.assertEqual(validate_document(out), [])
        norm = lambda d: json.dumps(d, sort_keys=True)  # noqa: E731
        for coll, key in (("transactions", "transaction_id"), ("transfer_links", "transfer_link_id"),
                          ("statement_payments", "allocation_id"), ("asset_valuations", "valuation_id")):
            self.assertEqual(sorted(map(norm, doc[coll])), sorted(map(norm, out[coll])), coll)
        acct = {a["account_id"]: a for a in out["accounts"]}
        self.assertTrue(acct["sav:reserve"]["include_in_net_worth"])  # absent flag stored as TRUE (Yes/No has no Null)

    def test_duplicates_and_invalid_bundles_rejected(self):
        self.rejected(self.repo.import_bundle(S.reference_bundle()), "E_DUPLICATE_ID")
        bad = S.reference_bundle()
        bad["accounts"] = [dict(bad["accounts"][0], account_id="chk:new", currency="EUR")]
        bad["categories"] = []
        self.rejected(self.repo.import_bundle(bad), "E_CURRENCY_MISMATCH")

    def test_ids_differing_only_by_case_collide_like_access(self):
        self.manual_pair()
        clash = {"contract": "perfin", "contract_version": "1.0.0", "document_type": "ledger_bundle", "base_currency": "USD",
                 "accounts": [], "categories": [], "transactions": [
                     {"transaction_id": "M1", "account_id": "chk:main", "posted_date": "2026-07-10", "amount_minor": -1,
                      "currency": "USD", "description": "x", "entry_method": "manual", "row_version": 1,
                      "splits": [S.cat("M1.s9", -1, "exp.uncategorized")]}]}
        self.rejected(self.repo.import_bundle(clash), "E_DUPLICATE_ID")

    def test_derived_ids_fit_the_contract(self):
        long_batch = "b" * 64
        tid = derive_id(long_batch, "r1", prefix="imp")
        self.assertLessEqual(len(tid), 64)
        self.assertTrue(tid.startswith("imp."))
        self.assertEqual(derive_id("b1", "r1"), "b1.r1")


if __name__ == "__main__":
    unittest.main()
