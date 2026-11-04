"""Document validation: header/version, schema subset, then cross-record rules."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List

from . import SUPPORTED_MAJOR, SUPPORTED_MINOR
from .schema_subset import Error, load_schema, validate

DOC_SCHEMAS = {
    "ledger_bundle": "ledger_bundle.schema.json", "staging_batch": "staging_batch.schema.json",
    "import_profile": "import_profile.schema.json", "command": "command.schema.json",
    "command_result": "command_result.schema.json", "payoff_scenario": "payoff_scenario.schema.json",
    "payoff_result": "payoff_result.schema.json", "net_worth_report": "net_worth_report.schema.json",
    "module_manifest": "module_manifest.schema.json",
}
LIABILITY_CLASSES = {"credit_card", "loan", "mortgage", "other_liability"}


def check_version(v: Any) -> List[Error]:
    m = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", v) if isinstance(v, str) else None
    if not m:
        return [("E_VERSION_UNSUPPORTED", "$.contract_version", f"invalid version {v!r}")]
    major, minor = int(m.group(1)), int(m.group(2))
    if major != SUPPORTED_MAJOR or minor > SUPPORTED_MINOR:
        return [("E_VERSION_UNSUPPORTED", "$.contract_version",
                 f"{v} not readable by {SUPPORTED_MAJOR}.{SUPPORTED_MINOR}.x (fail closed)")]
    return []


def validate_document(doc: Any) -> List[Error]:
    if not isinstance(doc, dict):
        return [("E_TYPE", "$", "document must be a JSON object")]
    if doc.get("contract") != "perfin":
        return [("E_SCHEMA", "$.contract", "not a perfin document")]
    errs = check_version(doc.get("contract_version"))
    if errs:
        return errs
    dt = doc.get("document_type")
    if dt not in DOC_SCHEMAS:
        return [("E_DOCUMENT_TYPE", "$.document_type", f"unknown document_type {dt!r}")]
    name = DOC_SCHEMAS[dt]
    if dt == "module_manifest" and doc.get("writes_ledger") is not False:
        return [("E_MODULE_WRITES_LEDGER", "$.writes_ledger", "modules must emit commands, never write the ledger")]
    errs = validate(doc, load_schema(name), name)
    if errs:
        return errs  # structural errors first; semantic rules assume a well-formed document
    return {"ledger_bundle": ledger_rules, "staging_batch": staging_rules, "command": command_rules,
            "import_profile": profile_rules, "payoff_scenario": payoff_rules,
            "module_manifest": manifest_rules}.get(dt, lambda d: [])(doc)


def _dupes(items, key, path) -> List[Error]:
    c = Counter(i[key] for i in items)
    return [("E_DUPLICATE_ID", path, f"duplicate {key} {k!r}") for k, n in c.items() if n > 1]


def _min_rule(rule, path) -> List[Error]:
    need = {"fixed": ["amount_minor"], "pct": ["pct"], "pct_plus_interest": ["pct"]}[rule["rule_type"]]
    return [("E_REQUIRED", f"{path}.{k}", f"{rule['rule_type']} rule needs {k}") for k in need if k not in rule]


def ledger_rules(b: Dict) -> List[Error]:
    e: List[Error] = []
    accts = {a["account_id"]: a for a in b["accounts"]}
    cats = {c["category_id"]: c for c in b["categories"]}
    txns = {t["transaction_id"]: t for t in b["transactions"]}
    links = {l["transfer_link_id"]: l for l in b.get("transfer_links", [])}
    stmts = {s["statement_id"]: s for s in b.get("statements", [])}
    e += _dupes(b["accounts"], "account_id", "$.accounts")
    e += _dupes(b["categories"], "category_id", "$.categories")
    e += _dupes(b["transactions"], "transaction_id", "$.transactions")
    e += _dupes(b.get("transfer_links", []), "transfer_link_id", "$.transfer_links")
    e += _dupes(b.get("statements", []), "statement_id", "$.statements")
    e += _dupes([s for t in b["transactions"] for s in t["splits"]], "split_id", "$.transactions[*].splits")

    for i, a in enumerate(b["accounts"]):
        p = f"$.accounts[{i}]"
        if a["currency"] != b["base_currency"]:
            e.append(("E_CURRENCY_MISMATCH", f"{p}.currency",
                      f"{a['currency']} account in a {b['base_currency']} ledger; multi-currency is unsupported in 1.0"))
        if (a["account_class"] in LIABILITY_CLASSES) != (a["kind"] == "liability"):
            e.append(("E_ACCOUNT_KIND", p, f"class {a['account_class']} inconsistent with kind {a['kind']}"))
        if a.get("closed_date") and a["closed_date"] < a["opening_balance_date"]:
            e.append(("E_DATE_ORDER", p, "closed before opening"))
    for i, c in enumerate(b["categories"]):
        if c.get("parent_category_id") and c["parent_category_id"] not in cats:
            e.append(("E_CATEGORY_UNKNOWN", f"$.categories[{i}]", "unknown parent category"))

    reversed_by = Counter(t["reverses_transaction_id"] for t in b["transactions"] if t.get("reverses_transaction_id"))
    for tid, n in reversed_by.items():
        if n > 1:
            e.append(("E_DUPLICATE_ID", "$.transactions", f"transaction {tid!r} is reversed {n} times; reverse at most once"))
    link_splits = defaultdict(list)  # link id -> [(txn, split)]
    for i, t in enumerate(b["transactions"]):
        p = f"$.transactions[{i}]"
        a = accts.get(t["account_id"])
        if a is None:
            e.append(("E_ACCOUNT_UNKNOWN", f"{p}.account_id", f"unknown account {t['account_id']!r}"))
        else:
            if t["currency"] != a["currency"]:
                e.append(("E_CURRENCY_MISMATCH", p, "transaction currency differs from account"))
            if t["posted_date"] <= a["opening_balance_date"]:
                e.append(("E_DATE_ORDER", f"{p}.posted_date", "must be after the account's opening_balance_date"))
        if t.get("transaction_date") and t["transaction_date"] > t["posted_date"]:
            e.append(("E_DATE_ORDER", f"{p}.transaction_date", "transaction_date after posted_date"))
        if sum(s["amount_minor"] for s in t["splits"]) != t["amount_minor"]:
            e.append(("E_SPLITS_UNBALANCED", f"{p}.splits", "split amounts must sum to the transaction amount"))
        if (t["entry_method"] == "import") != bool(t.get("source")):
            e.append(("E_REQUIRED", f"{p}.source", "imported transactions need source provenance; others must not claim it"))
        if t["entry_method"] == "reversal" or t.get("reverses_transaction_id"):
            o = txns.get(t.get("reverses_transaction_id") or "")
            if o is None or t["entry_method"] != "reversal":
                e.append(("E_REF_UNKNOWN", f"{p}.reverses_transaction_id", "reversal must reference an existing transaction"))
            elif o["amount_minor"] != -t["amount_minor"] or o["account_id"] != t["account_id"]:
                e.append(("E_TRANSFER_AMOUNT", p, "reversal must negate the original on the same account"))
            else:
                key = lambda x, sign: (x["split_kind"], x.get("category_id"), x.get("transfer_link_id"), sign * x["amount_minor"])
                if Counter(key(x, 1) for x in t["splits"]) != Counter(key(x, -1) for x in o["splits"]):
                    e.append(("E_SPLIT_KIND", f"{p}.splits", "reversal splits must negate the original's splits (same kinds and categories)"))
        for j, s in enumerate(t["splits"]):
            sp = f"{p}.splits[{j}]"
            k = s["split_kind"]
            if k == "category":
                if not s.get("category_id") or s.get("transfer_link_id"):
                    e.append(("E_SPLIT_KIND", sp, "category split needs category_id and no transfer_link_id"))
                elif s["category_id"] not in cats:
                    e.append(("E_CATEGORY_UNKNOWN", sp, f"unknown category {s['category_id']!r}"))
            elif k == "transfer":
                if not s.get("transfer_link_id") or s.get("category_id"):
                    e.append(("E_SPLIT_KIND", sp, "transfer split needs transfer_link_id and no category (no expense)"))
                elif s["transfer_link_id"] not in links:
                    e.append(("E_TRANSFER_UNPAIRED", sp, "transfer split references unknown link"))
                else:
                    link_splits[s["transfer_link_id"]].append((t, s))
            elif k == "adjustment":
                orig = txns.get(t.get("reverses_transaction_id") or "")
                reverses_adjustment = (t["entry_method"] == "reversal" and orig is not None and orig["entry_method"] == "manual"
                                       and any(x["split_kind"] == "adjustment" for x in orig["splits"]))
                if s.get("category_id") or s.get("transfer_link_id") or not (t["entry_method"] == "manual" or reverses_adjustment):
                    e.append(("E_SPLIT_KIND", sp, "adjustment splits are uncategorized, unlinked, and manual or a reversal of a manual adjustment"))

    for i, l in enumerate(b.get("transfer_links", [])):
        p = f"$.transfer_links[{i}]"
        f, to = txns.get(l["from_transaction_id"]), txns.get(l["to_transaction_id"])
        if f is None or to is None:
            e.append(("E_REF_UNKNOWN", p, "link references unknown transaction"))
            continue
        if f["account_id"] == to["account_id"]:
            e.append(("E_TRANSFER_SAME_ACCOUNT", p, "transfer legs must be different accounts"))
        if f["currency"] != to["currency"]:
            e.append(("E_CURRENCY_MISMATCH", p, "cross-currency transfers are unsupported in 1.0"))
        legs = link_splits.get(l["transfer_link_id"], [])
        fs = [s["amount_minor"] for t, s in legs if t is f]
        ts = [s["amount_minor"] for t, s in legs if t is to]
        if not fs or not ts or len(legs) != len(fs) + len(ts):
            e.append(("E_TRANSFER_UNPAIRED", p, "both legs (and only those) need a transfer split for this link"))
        elif sum(fs) >= 0 or sum(fs) != -sum(ts):
            e.append(("E_TRANSFER_AMOUNT", p, "from leg must be negative and equal to minus the to leg"))

    for i, s in enumerate(b.get("statements", [])):
        p = f"$.statements[{i}]"
        if s["account_id"] not in accts:
            e.append(("E_ACCOUNT_UNKNOWN", p, "unknown account"))
        if s["period_start"] > s["period_end"] or (s.get("due_date") and s["due_date"] < s["period_end"]):
            e.append(("E_DATE_ORDER", p, "need period_start <= period_end <= due_date"))
        if s.get("bucket_balances") and sum(x["balance_minor"] for x in s["bucket_balances"]) != s["closing_balance_minor"]:
            e.append(("E_BUCKET_SUM", p, "bucket balances must sum to closing_balance_minor"))

    alloc = Counter()
    for i, sp in enumerate(b.get("statement_payments", [])):
        p = f"$.statement_payments[{i}]"
        s, t = stmts.get(sp["statement_id"]), txns.get(sp["transaction_id"])
        if s is None or t is None:
            e.append(("E_REF_UNKNOWN", p, "unknown statement or transaction"))
            continue
        # The payment portion is the inbound transfer splits (a linked payment from another
        # account); refunds, credits and reversals on the card are not payments.
        paid = sum(x["amount_minor"] for x in t["splits"] if x["split_kind"] == "transfer" and x["amount_minor"] > 0)
        if t["account_id"] != s["account_id"] or paid <= 0:
            e.append(("E_ACCOUNT_KIND", p, "allocation needs a payment: an inbound transfer on the statement's account"))
            continue
        alloc[t["transaction_id"]] += sp["amount_minor"]
        if alloc[t["transaction_id"]] > paid:
            e.append(("E_ALLOCATION_EXCEEDS", p, "allocations exceed the payment portion of the transaction"))

    for i, r in enumerate(b.get("reconciliations", [])):
        p = f"$.reconciliations[{i}]"
        s = stmts.get(r["statement_id"])
        if s is None:
            e.append(("E_REF_UNKNOWN", p, "unknown statement"))
            continue
        total = 0
        for tid in r["included_transaction_ids"]:
            t = txns.get(tid)
            if t is None or t["account_id"] != s["account_id"] or not (s["period_start"] <= t["posted_date"] <= s["period_end"]):
                e.append(("E_REF_UNKNOWN", p, f"{tid!r} is not a posted transaction of this account in the period"))
            else:
                total += t["amount_minor"]
        diff = s["closing_balance_minor"] - (s["opening_balance_minor"] + total)
        if diff != r["difference_minor"] or (r["recon_status"] == "balanced" and diff != 0):
            e.append(("E_RECON_MISMATCH", p, f"recomputed difference {diff}"))

    for i, ct in enumerate(b.get("card_terms", [])):
        p = f"$.card_terms[{i}]"
        a = accts.get(ct["account_id"])
        if a is None:
            e.append(("E_ACCOUNT_UNKNOWN", p, "unknown account"))
        elif a["account_class"] != "credit_card":
            e.append(("E_ACCOUNT_KIND", p, "card terms need a credit_card account"))
        e += card_terms_local_rules(ct, p)

    for i, v in enumerate(b.get("asset_valuations", [])):
        p = f"$.asset_valuations[{i}]"
        a = accts.get(v["account_id"])
        if a is None:
            e.append(("E_ACCOUNT_UNKNOWN", p, "unknown account"))
        elif a["kind"] != "asset":
            e.append(("E_ACCOUNT_KIND", p, "valuations apply to asset accounts"))
        elif v["currency"] != a["currency"]:
            e.append(("E_CURRENCY_MISMATCH", p, "valuation currency differs from account"))
    return e


def card_terms_local_rules(ct: Dict, p: str) -> List[Error]:
    """Rules checkable from one card_terms record alone (shared with set_card_terms commands)."""
    e: List[Error] = []
    if ct.get("effective_to") and ct["effective_to"] < ct["effective_from"]:
        e.append(("E_DATE_ORDER", p, "effective_to before effective_from"))
    e += _min_rule(ct["min_payment_rule"], f"{p}.min_payment_rule")
    e += _dupes(ct["apr_buckets"], "bucket_id", f"{p}.apr_buckets")
    for j, bk in enumerate(ct["apr_buckets"]):
        if bk["deferred_interest"] and not bk.get("promo_end_date"):
            e.append(("E_REQUIRED", f"{p}.apr_buckets[{j}].promo_end_date", "deferred interest needs a deadline"))
        if bk.get("promo_end_date") and not bk.get("post_promo_apr"):
            e.append(("E_REQUIRED", f"{p}.apr_buckets[{j}].post_promo_apr", "promotion needs its post-promotion APR"))
    return e


def staging_rules(d: Dict) -> List[Error]:
    e = _dupes(d["rows"], "row_number", "$.rows")
    for i, r in enumerate(d["rows"]):
        p = f"$.rows[{i}]"
        if r["review_state"] == "approved":
            if r["errors"] or r.get("parsed") is None:
                e.append(("E_ROW_UNRESOLVED", p, "a row with parse errors cannot be approved"))
            if r["duplicate"]["status"] in ("exact_reimport", "possible", "confirmed_duplicate"):
                e.append(("E_DUPLICATE_UNRESOLVED", p, "duplicate status must be none or confirmed_distinct to approve"))
            ps = r.get("proposed_splits") or []
            if r.get("parsed") and ps and sum(s["amount_minor"] for s in ps) != r["parsed"]["amount_minor"]:
                e.append(("E_SPLITS_UNBALANCED", p, "proposed splits must sum to the parsed amount"))
        if r.get("parsed") is None and not r["errors"]:
            e.append(("E_ROW_UNRESOLVED", p, "unparsed row must carry its error codes"))
    if d["batch"]["batch_status"] in ("approved", "committed"):
        if any(r["review_state"] in ("pending", "needs_review") for r in d["rows"]):
            e.append(("E_BATCH_STATE", "$.batch", "every row must be approved or rejected first"))
    return e


def command_rules(c: Dict) -> List[Error]:
    name = "command.schema.json"
    sub = load_schema(name)["$defs"][f"payload_{c['command_type']}"]
    errs = validate(c["payload"], sub, name, "$.payload")
    if not errs:  # payload-local semantic rules, identical to the standalone documents
        if c["command_type"] == "save_payoff_scenario":
            errs = scenario_rules(c["payload"], "$.payload")
        elif c["command_type"] == "set_card_terms":
            errs = card_terms_local_rules(c["payload"], "$.payload")
        elif c["command_type"] == "set_splits":
            errs = _dupes(c["payload"]["splits"], "split_id", "$.payload.splits")
    return [("E_COMMAND_PAYLOAD", p, f"{code}: {m}") for code, p, m in errs]


def profile_rules(d: Dict) -> List[Error]:
    cols, rule = d["columns"], d["amount"]["sign_rule"]
    if rule == "debit_credit_columns":
        if not (cols.get("debit") and cols.get("credit")) or cols.get("amount"):
            return [("E_REQUIRED", "$.columns", "debit_credit_columns needs debit and credit and no amount")]
    elif not cols.get("amount"):
        return [("E_REQUIRED", "$.columns.amount", "amount column required")]
    if d["amount"]["decimal_separator"] == d["amount"].get("thousands_separator"):
        return [("E_ENUM", "$.amount", "decimal and thousands separators must differ")]
    return []


def payoff_rules(d: Dict) -> List[Error]:
    return scenario_rules(d["scenario"], "$.scenario")


def scenario_rules(s: Dict, root: str) -> List[Error]:
    e = _dupes(s["cards"], "account_id", f"{root}.cards")
    for i, c in enumerate(s["cards"]):
        e += _min_rule(c["min_payment_rule"], f"{root}.cards[{i}].min_payment_rule")
        for j, bk in enumerate(c["buckets"]):
            if (bk.get("promo_end_month") is None) != (bk.get("post_promo_apr") is None) or (bk["deferred_interest"] and bk.get("promo_end_month") is None):
                e.append(("E_REQUIRED", f"{root}.cards[{i}].buckets[{j}]", "promotion needs end month and post-promo APR"))
    for i, st in enumerate(s["strategies"]):
        if st["kind"] == "near_apr_hybrid" and ("gap_pp" not in st or "prefer" not in st):
            e.append(("E_REQUIRED", f"{root}.strategies[{i}]", "hybrid needs gap_pp and prefer"))
        if st["kind"] != "near_apr_hybrid" and ("gap_pp" in st or "prefer" in st):
            e.append(("E_UNKNOWN_FIELD", f"{root}.strategies[{i}]", "gap_pp/prefer apply to the hybrid only"))
    return e


def manifest_rules(d: Dict) -> List[Error]:
    e = []
    if d["module_kind"] == "excel_workbook" and not d.get("workbook_file"):
        e.append(("E_REQUIRED", "$.workbook_file", "excel modules ship their own workbook file"))
    lo = tuple(map(int, d["contract_versions"]["min"].split(".")))
    hi = tuple(map(int, d["contract_versions"]["max_exclusive"].split(".")))
    if not lo <= (SUPPORTED_MAJOR, SUPPORTED_MINOR, 0) < hi:
        e.append(("E_VERSION_UNSUPPORTED", "$.contract_versions", "module does not support this contract version"))
    return e
