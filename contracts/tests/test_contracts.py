"""Contract 1.0.0 conformance tests. Linux/stdlib only; no Office needed.

    python3 -m unittest discover -s contracts/tests -v
"""
import copy
import glob
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

from perfin_contracts import CONTRACT_VERSION  # noqa: E402
from perfin_contracts.derive import account_balance, display_balance, period_totals  # noqa: E402
from perfin_contracts.schema_subset import check_schema_keywords, load_schema, validate, _resolve  # noqa: E402
from perfin_contracts.semantic import DOC_SCHEMAS, validate_document  # noqa: E402


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


VALID = sorted(glob.glob(os.path.join(ROOT, "examples", "valid", "*.json")))
EXPECTED = load(os.path.join(ROOT, "examples", "invalid", "expected.json"))
LEDGER = load(os.path.join(ROOT, "examples", "valid", "ledger_household.json"))


def codes(doc):
    return sorted({c for c, _, _ in validate_document(doc)})


class Schemas(unittest.TestCase):
    def test_version_file(self):
        self.assertEqual(read(os.path.join(ROOT, "VERSION")).strip(), CONTRACT_VERSION)

    def test_keyword_subset_and_refs(self):
        for f in glob.glob(os.path.join(ROOT, "schemas", "*.schema.json")):
            s = load(f)
            check_schema_keywords(s, os.path.basename(f))
            for ref in re.findall(r'"\$ref":\s*"([^"]+)"', read(f)):
                _resolve(ref, os.path.basename(f))  # raises if dangling

    def test_no_number_type(self):
        for f in glob.glob(os.path.join(ROOT, "schemas", "*.json")):
            self.assertNotIn('"number"', read(f), f)

    def test_error_codes_declared(self):
        declared = set(load_schema("common.schema.json")["$defs"]["error_code"]["enum"])
        src = "".join(read(p) for p in glob.glob(os.path.join(ROOT, "python", "perfin_contracts", "*.py")))
        used = set(re.findall(r'"(E_[A-Z_]+)"', src)) | {c for v in EXPECTED.values() for c in v}
        self.assertEqual(used - declared, set())


class MoneyStorageRange(unittest.TestCase):
    def test_currency_integer_boundaries(self):
        # Access Currency stores cents as whole Currency values; Excel's larger
        # exact-integer range cannot all fit the chosen database representation.
        for amount in (-922337203685477, 922337203685477):
            b = copy.deepcopy(LEDGER)
            b["accounts"][0]["opening_balance_minor"] = amount
            self.assertEqual(validate_document(b), [])
        for amount in (-922337203685478, 922337203685478, 9007199254740991):
            b = copy.deepcopy(LEDGER)
            b["accounts"][0]["opening_balance_minor"] = amount
            self.assertIn("E_RANGE", codes(b))


class Examples(unittest.TestCase):
    def test_valid_examples_pass(self):
        self.assertGreaterEqual(len(VALID), 10)
        for f in VALID:
            self.assertEqual(validate_document(load(f)), [], f)

    def test_invalid_examples_fail_with_expected_codes(self):
        self.assertGreaterEqual(len(EXPECTED), 30)
        for name, exp in EXPECTED.items():
            self.assertEqual(codes(load(os.path.join(ROOT, "examples", "invalid", name))), exp, name)

    def test_every_invalid_file_has_expectation(self):
        files = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "examples", "invalid", "*.json"))} - {"expected.json"}
        self.assertEqual(files, set(EXPECTED))

    def test_every_document_type_has_valid_example(self):
        types = {load(f)["document_type"] for f in VALID}
        self.assertEqual(types, set(DOC_SCHEMAS))

    def test_valid_examples_contain_no_floats(self):
        def walk(x):
            if isinstance(x, float):
                raise AssertionError("float in example")
            if isinstance(x, dict):
                [walk(v) for v in x.values()]
            if isinstance(x, list):
                [walk(v) for v in x]
        for f in VALID:
            walk(load(f))


class Rules(unittest.TestCase):
    def mutate(self, fn):
        d = copy.deepcopy(LEDGER)
        fn(d)
        return codes(d)

    def test_leap_day(self):
        s = {"$ref": "common.schema.json#/$defs/date"}
        self.assertEqual(validate("2028-02-29", s, "common.schema.json"), [])
        self.assertEqual(validate("2027-02-29", s, "common.schema.json")[0][0], "E_DATE_INVALID")

    def test_version_policy(self):
        for v, ok in (("1.0.0", True), ("1.0.7", True), ("1.1.0", False), ("2.0.0", False), ("0.9.0", False), ("1.0", False)):
            d = dict(LEDGER, contract_version=v)
            self.assertEqual(validate_document(d) == [], ok, v)

    def test_manifest_range_uses_full_contract_version(self):
        base = load(os.path.join(ROOT, "examples", "valid", "module_manifest_payoff.json"))
        major, minor, patch = map(int, CONTRACT_VERSION.split("."))
        cur = f"{major}.{minor}.{patch}"
        nxt = f"{major}.{minor}.{patch + 1}"
        for lo, hi, ok in ((cur, f"{major}.{minor + 1}.0", True), (f"{major}.0.0", f"{major + 1}.0.0", True),
                           (f"{major}.0.0", cur, False), (nxt, f"{major + 1}.0.0", False)):
            d = dict(base, contract_versions={"min": lo, "max_exclusive": hi})
            self.assertEqual(validate_document(d) == [], ok, (lo, hi))

    def test_unknown_document_type(self):
        self.assertEqual(codes(dict(LEDGER, document_type="ledger_dump")), ["E_DOCUMENT_TYPE"])

    def test_transfer_split_cannot_carry_category(self):
        self.assertIn("E_SPLIT_KIND", self.mutate(lambda d: d["transactions"][3]["splits"][0].update(category_id="exp.groceries")))

    def test_adjustment_must_be_manual(self):
        def f(d):
            d["transactions"][1]["splits"] = [{"split_id": "s002", "split_kind": "adjustment", "amount_minor": -10000}]
        self.assertIn("E_SPLIT_KIND", self.mutate(f))

    def test_reversal_must_negate(self):
        def f(d):
            d["transactions"].append({"transaction_id": "t099", "account_id": "card:beta", "posted_date": "2026-06-30",
                                      "amount_minor": 7000, "currency": "USD", "description": "REVERSAL", "entry_method": "reversal",
                                      "reverses_transaction_id": "t005", "splits": [{"split_id": "s099", "split_kind": "category",
                                      "amount_minor": 7000, "category_id": "exp.groceries"}], "row_version": 1})
        self.assertIn("E_TRANSFER_AMOUNT", self.mutate(f))

    def _adjustment(self, d):
        d["transactions"].append({"transaction_id": "t020", "account_id": "chk:main", "posted_date": "2026-06-29",
                                  "amount_minor": -100, "currency": "USD", "description": "RECON ADJUSTMENT",
                                  "entry_method": "manual", "splits": [{"split_id": "s020", "split_kind": "adjustment",
                                  "amount_minor": -100}], "row_version": 1})

    def _reversal_of(self, d, orig, amount):
        d["transactions"].append({"transaction_id": "t021", "account_id": "chk:main", "posted_date": "2026-06-30",
                                  "amount_minor": amount, "currency": "USD", "description": "REVERSAL",
                                  "entry_method": "reversal", "reverses_transaction_id": orig,
                                  "splits": [{"split_id": "s021", "split_kind": "adjustment", "amount_minor": amount}],
                                  "row_version": 1})

    def test_reversal_of_manual_adjustment_is_valid(self):
        def f(d):
            self._adjustment(d)
            self._reversal_of(d, "t020", 100)
        self.assertEqual(self.mutate(f), [])

    def test_reversal_cannot_turn_category_into_adjustment(self):
        def f(d):
            self._reversal_of(d, "t001", -300000)
        self.assertIn("E_SPLIT_KIND", self.mutate(f))

    def _reverse_purchase(self, d, split):
        d["transactions"].append({"transaction_id": "t030", "account_id": "card:alpha", "posted_date": "2026-06-29",
                                  "amount_minor": 10000, "currency": "USD", "description": "REVERSAL OF t002",
                                  "entry_method": "reversal", "reverses_transaction_id": "t002",
                                  "splits": [split], "row_version": 1})

    def test_reversal_negating_splits_is_valid(self):
        self.assertEqual(self.mutate(lambda d: self._reverse_purchase(
            d, {"split_id": "s030", "split_kind": "category", "amount_minor": 10000, "category_id": "exp.groceries"})), [])

    def test_reversal_cannot_recategorize(self):
        # negates the total but books income instead of reversing the grocery expense
        self.assertIn("E_SPLIT_KIND", self.mutate(lambda d: self._reverse_purchase(
            d, {"split_id": "s030", "split_kind": "category", "amount_minor": 10000, "category_id": "inc.salary"})))

    def test_transaction_reversed_at_most_once(self):
        def f(d):
            for tid in ("t050", "t051"):
                d["transactions"].append({"transaction_id": tid, "account_id": "card:alpha", "posted_date": "2026-06-29",
                                          "amount_minor": 10000, "currency": "USD", "description": "REVERSAL OF t002",
                                          "entry_method": "reversal", "reverses_transaction_id": "t002",
                                          "splits": [{"split_id": "s" + tid, "split_kind": "category", "amount_minor": 10000,
                                                      "category_id": "exp.groceries"}], "row_version": 1})
        self.assertIn("E_DUPLICATE_ID", self.mutate(f))

    def test_refund_is_not_a_payment_allocation(self):
        def f(d):
            d["transactions"].append({"transaction_id": "t040", "account_id": "card:alpha", "posted_date": "2026-07-02",
                                      "amount_minor": 2500, "currency": "USD", "description": "MERCHANT REFUND",
                                      "entry_method": "manual", "splits": [{"split_id": "s040", "split_kind": "category",
                                      "amount_minor": 2500, "category_id": "exp.groceries"}], "row_version": 1})
            d["statement_payments"].append({"allocation_id": "a040", "statement_id": "st_alpha_2026_06",
                                            "transaction_id": "t040", "amount_minor": 2500})
        self.assertIn("E_ACCOUNT_KIND", self.mutate(f))

    def test_offsetting_transfer_splits_cannot_inflate_payment(self):
        def f(d):
            d["transactions"][3]["splits"] = [
                {"split_id": "s004", "split_kind": "transfer", "amount_minor": 20000, "transfer_link_id": "L001"},
                {"split_id": "s004b", "split_kind": "transfer", "amount_minor": -10000, "transfer_link_id": "L001"}]
            d["statement_payments"][0]["amount_minor"] = 20000
        got = self.mutate(f)
        self.assertIn("E_TRANSFER_AMOUNT", got)
        self.assertIn("E_ALLOCATION_EXCEEDS", got)

    def test_all_entity_ids_unique(self):
        for coll in ("statement_payments", "reconciliations", "card_terms", "asset_valuations"):
            self.assertIn("E_DUPLICATE_ID", self.mutate(lambda d: d[coll].append(copy.deepcopy(d[coll][0]))), coll)

    def test_statement_bucket_ids_unique(self):
        # contract 1.0.1: Access primary key statement_bucket_balance(statement_id, bucket_id)
        def f(d):
            d["statements"][0]["bucket_balances"] = [{"bucket_id": "purchase", "balance_minor": -27500},
                                                     {"bucket_id": "purchase", "balance_minor": -27500}]
        self.assertEqual(self.mutate(f), ["E_DUPLICATE_ID"])

    def test_deferred_promo_needs_deadline(self):
        self.assertIn("E_REQUIRED", self.mutate(lambda d: d["card_terms"][1]["apr_buckets"][1].pop("promo_end_date")))

    def test_non_base_currency_account_rejected(self):
        def f(d):
            d["accounts"].append({"account_id": "cash:eur", "kind": "asset", "account_class": "cash",
                                  "display_name": "EUR cash", "currency": "EUR", "opening_balance_minor": 0,
                                  "opening_balance_date": "2026-05-31", "row_version": 1})
        self.assertEqual(self.mutate(f), ["E_CURRENCY_MISMATCH"])

    def test_currency_mismatch(self):
        self.assertIn("E_CURRENCY_MISMATCH", self.mutate(lambda d: d["transactions"][0].update(currency="EUR")))


class CommandPayloadRules(unittest.TestCase):
    """Commands apply the same payload-local rules as the standalone documents."""

    def command(self, ctype, payload):
        return {"contract": "perfin", "contract_version": "1.0.0", "document_type": "command",
                "command_id": "1a2b3c4d-0000-4000-8000-000000000009", "command_type": ctype,
                "issued_at": "2026-07-02T15:11:00Z", "issued_by": "excel_payoff:planner",
                "payload": payload, "expected_versions": []}

    def test_save_payoff_scenario_applies_scenario_rules(self):
        sc = copy.deepcopy(load(os.path.join(ROOT, "examples", "valid", "payoff_scenario.json"))["scenario"])
        self.assertEqual(validate_document(self.command("save_payoff_scenario", sc)), [])
        sc["strategies"][3].pop("gap_pp")
        self.assertEqual(codes(self.command("save_payoff_scenario", sc)), ["E_COMMAND_PAYLOAD"])

    def test_statement_payment_allocation_commands(self):
        alloc = copy.deepcopy(LEDGER["statement_payments"][0])
        self.assertEqual(validate_document(self.command("allocate_statement_payment", alloc)), [])
        alloc["amount_minor"] = 0
        self.assertEqual(codes(self.command("allocate_statement_payment", alloc)), ["E_COMMAND_PAYLOAD"])
        self.assertEqual(validate_document(self.command("remove_statement_payment",
                                                        {"allocation_id": "a001", "reason": "allocated to wrong cycle"})), [])

    def test_set_card_terms_applies_terms_rules(self):
        ct = copy.deepcopy(LEDGER["card_terms"][1])
        self.assertEqual(validate_document(self.command("set_card_terms", ct)), [])
        ct["apr_buckets"][1].pop("promo_end_date")
        self.assertEqual(codes(self.command("set_card_terms", ct)), ["E_COMMAND_PAYLOAD"])
        ct = copy.deepcopy(LEDGER["card_terms"][1])
        ct["min_payment_rule"] = {"rule_type": "pct_plus_interest", "floor_minor": 2500}
        self.assertEqual(codes(self.command("set_card_terms", ct)), ["E_COMMAND_PAYLOAD"])


class Semantics(unittest.TestCase):
    """Accounting meaning of the canonical sign convention (credit-card MVP scenarios)."""

    def test_purchase_then_payment_no_double_expense(self):
        # $100 purchase (t002) then $100 checking-to-card payment (t003/t004)
        self.assertEqual(display_balance(LEDGER, "card:alpha", "2026-06-02"), 45000)
        self.assertEqual(display_balance(LEDGER, "card:alpha", "2026-06-03"), 55000)
        self.assertEqual(display_balance(LEDGER, "card:alpha", "2026-06-12"), 45000)  # debt back to prior level
        before = account_balance(LEDGER, "chk:main", "2026-06-09")
        self.assertEqual(account_balance(LEDGER, "chk:main", "2026-06-10"), before - 10000)
        tot = period_totals(LEDGER, "2026-06-01", "2026-06-12")
        self.assertEqual(tot["spending"], 10000 + 5000 + 3000)  # t002 + split t005 only; payment adds nothing

    def test_refund_interest_fees_and_opening(self):
        tot = period_totals(LEDGER, "2026-06-01", "2026-06-30")
        self.assertEqual(tot, {"income": 300000, "spending": 10000 + 5000 + 3000 - 2500,
                               "interest": 500 + 110000, "fees": 9500})
        # opening balances (setup) are not income
        self.assertEqual(period_totals(LEDGER, "2026-05-01", "2026-05-31"), {"income": 0, "spending": 0, "interest": 0, "fees": 0})

    def test_principal_is_transfer_interest_is_expense(self):
        self.assertEqual(display_balance(LEDGER, "mtg:home", "2026-06-30"), 30000000 - 60000)
        tot = period_totals(LEDGER, "2026-06-01", "2026-06-01")
        self.assertEqual(tot["interest"], 110000)
        self.assertEqual(tot["spending"], 0)

    def test_statement_reconciles(self):
        s = LEDGER["statements"][0]
        self.assertEqual(account_balance(LEDGER, "card:alpha", s["period_end"]), s["closing_balance_minor"])

    def test_formula_like_text_stays_text(self):
        self.assertTrue(isinstance(LEDGER["transactions"][1]["description"], str))
        self.assertTrue(LEDGER["transactions"][1]["description"].startswith("="))


class AccessAndReports(unittest.TestCase):
    DDL = read(os.path.join(ROOT, "access", "perfin_v1_reference.sql"))

    def tables(self):
        out = {}
        for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", self.DDL, re.S):
            cols = [l.strip().split()[0] for l in body.strip().splitlines() if l.strip() and not l.strip().startswith("CONSTRAINT")]
            out[name] = set(cols)
        return out

    def test_ddl_covers_entity_scalars(self):
        t = self.tables()
        ent = load_schema("ledger_bundle.schema.json")["$defs"]
        mapping = {"account": "account", "category": "category", "transaction": "ledger_txn", "split": "split",
                   "transfer_link": "transfer_link", "statement": "statement", "statement_payment": "statement_payment",
                   "reconciliation": "reconciliation", "asset_valuation": "asset_valuation", "card_terms": "card_terms"}
        nested = {"source", "splits", "bucket_balances", "included_transaction_ids", "min_payment_rule", "apr_buckets"}
        for e, table in mapping.items():
            for prop in ent[e]["properties"]:
                if prop not in nested:
                    self.assertIn(prop, t[table], f"{e}.{prop} missing from {table}")
        self.assertTrue({"source_batch_id", "source_row_number", "source_txn_id"} <= t["ledger_txn"])
        self.assertTrue({"min_rule_type", "min_amount_minor", "min_pct", "min_floor_minor"} <= t["card_terms"])
        self.assertIn("card_apr_bucket", t)
        self.assertIn("reconciliation_item", t)

    def test_ddl_money_columns_are_currency(self):
        for line in self.DDL.splitlines():
            m = re.match(r"\s+(\w+_minor) (\w+)", line)
            if m:
                self.assertEqual(m.group(2), "CURRENCY", line)

    def test_report_tables_carry_module_inputs(self):
        """Modules read only rpt_* tables, so every payoff/net-worth input must be exposed there."""
        rt = {t: {c["name"] for c in cols} for t, cols in load(os.path.join(ROOT, "schemas", "report_tables.json"))["tables"].items()}
        card = load_schema("payoff_scenario.schema.json")["$defs"]["scenario_body"]["properties"]["cards"]["items"]
        rule = set(load_schema("ledger_bundle.schema.json")["$defs"]["card_terms"]["properties"]["min_payment_rule"]["properties"])
        self.assertEqual(rule, {"rule_type", "amount_minor", "pct", "floor_minor"})
        self.assertTrue({"min_rule_type", "min_amount_minor", "min_pct", "min_floor_minor"} <= rt["rpt_card_terms"])
        bucket = card["properties"]["buckets"]["items"]["properties"]
        self.assertTrue({"apr", "post_promo_apr", "deferred_interest", "promo_end_date", "bucket_id"} <= rt["rpt_card_terms"])
        self.assertIn("promo_end_month", bucket)  # derived from promo_end_date and the scenario as_of
        self.assertTrue({"statement_id", "account_id", "bucket_id", "balance_minor"} <= rt["rpt_statement_buckets"])
        self.assertTrue({"ownership_pct", "legal_liability_pct", "liquidity", "include_in_net_worth", "kind"} <= rt["rpt_accounts"])
        self.assertIn("cost_basis_minor", rt["rpt_valuations"])

    def test_report_tables(self):
        rt = load(os.path.join(ROOT, "schemas", "report_tables.json"))
        allowed = {"id", "text", "enum", "currency", "money_minor", "date", "boolean", "integer", "decimal_string"}
        for name, cols in rt["tables"].items():
            names = [c["name"] for c in cols]
            self.assertEqual(len(names), len(set(names)), name)
            self.assertTrue(all(c["type"] in allowed for c in cols), name)
        reads = set(load_schema("module_manifest.schema.json")["properties"]["reads"]["items"]["enum"])
        self.assertEqual(reads, set(rt["tables"]))


if __name__ == "__main__":
    unittest.main()
