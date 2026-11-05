"""Controlled write path into the Access ledger.

Every change goes through Repository.execute(command) (contract `command` documents) or one of
three logged administrative operations that the 1.0 contract has no command for
(stage_batch, import_bundle, set_default_categories). Each call:

1. validates the input document with perfin_contracts (imported, never copied);
2. opens ONE database transaction;
3. checks expected_versions (optimistic concurrency, E_STALE_VERSION) and business rules;
4. writes, then re-reads the whole ledger as a ledger_bundle and validates it with the contract's
   semantic rules (the post-command ledger must be valid);
5. writes command_log + audit_log (before/after JSON) in the same transaction and commits.

A rejected or replayed command rolls the transaction back and changes nothing (rejected
commands are not written to command_log either). An unexpected adapter/engine failure rolls
back and raises StorageError. Results are contract `command_result` documents, validated
before they are returned.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import _paths, codec, migrations, sqlbuild

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
NIL_UUID = str(uuid.UUID(int=0))  # built, not written out: a literal looks like a card number to the repo scan
ADMIN_NAMESPACE = uuid.UUID("6f7e1c1e-2b0d-4c41-9a53-2b5e1f1d7a00")
LEDGER_TABLES = ("account", "category", "ledger_txn", "split", "transfer_link", "statement",
                 "statement_bucket_balance", "statement_payment", "reconciliation", "reconciliation_item",
                 "card_terms", "card_apr_bucket", "asset_valuation")
VERSIONED = {  # expected_versions entity -> (table, key column)
    "account": ("account", "account_id"),
    "transaction": ("ledger_txn", "transaction_id"),
    "transfer_link": ("transfer_link", "transfer_link_id"),
    "statement": ("statement", "statement_id"),
    "statement_payment": ("statement_payment", "allocation_id"),  # no row_version column: always 1
    "reconciliation": ("reconciliation", "reconciliation_id"),
    "card_terms": ("card_terms", "terms_id"),
    "asset_valuation": ("asset_valuation", "valuation_id"),
    "batch": ("import_batch", "batch_id"),
}
APPROVABLE_DUP = ("none", "confirmed_distinct")
META_DEFAULT_OUT = "default_outflow_category_id"
META_DEFAULT_IN = "default_inflow_category_id"

Error = Tuple[str, str, str]


class Reject(Exception):
    def __init__(self, errors: List[Error]):
        super().__init__(errors)
        self.errors = errors


def reject(code: str, path: str, message: str):
    raise Reject([(code, path, message)])


class Replay(Exception):
    def __init__(self, message: str, affected=None):
        super().__init__(message)
        self.message = message
        self.affected = affected or []


class StorageError(RuntimeError):
    """The engine failed mid-command. The database transaction was rolled back."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_id(*parts: str, prefix: str = "id") -> str:
    """Deterministic ledger id: 'a.b.c' when it fits the contract id pattern, else a hash."""
    cand = ".".join(parts)
    if ID_RE.fullmatch(cand):
        return cand
    return "%s.%s" % (prefix, hashlib.sha256(cand.encode("utf-8")).hexdigest()[:40])


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _drop_none(d: Dict[str, Any], keep: Iterable[str] = ()) -> Dict[str, Any]:
    keep = set(keep)
    return {k: v for k, v in d.items() if v is not None or k in keep}


class _Ctx:
    def __init__(self, command_id: str, command_type: str, issued_at: str, issued_by: str,
                 document: Dict[str, Any], now: str):
        self.command_id, self.command_type = command_id, command_type
        self.issued_at, self.issued_by, self.document, self.now = issued_at, issued_by, document, now
        self.audit: List[Tuple[str, str, str, Any, Any]] = []
        self.affected: Dict[Tuple[str, str], int] = {}
        self.ledger_changed = False

    def log(self, entity: str, entity_id: str, action: str, before: Any, after: Any) -> None:
        self.audit.append((entity, entity_id, action, before, after))

    def touch(self, entity: str, entity_id: str, version: int) -> None:
        self.affected[(entity, entity_id)] = version


def _read_context(adapter):
    """Adapters with explicit snapshot support protect multi-query reads."""
    snapshot = getattr(adapter, "read_snapshot", None)
    return snapshot() if snapshot is not None else nullcontext()


def _consistent_read(method):
    @wraps(method)
    def read(self, *args, **kwargs):
        with _read_context(self.adapter):
            return method(self, *args, **kwargs)
    return read


class Repository:
    def __init__(self, adapter, *, clock: Callable[[], str] = utc_now, check_schema: bool = True):
        self.adapter = adapter
        self.clock = clock
        (self._validate, self.contract_schema_dir, self.contract_version,
         self.contract_major, self.contract_minor) = _paths.contracts()
        with _read_context(adapter):
            if check_schema:
                self.meta = migrations.ensure_compatible(adapter, contract_major=self.contract_major)
            else:
                self.meta = migrations.read_meta(adapter)
            self.base_currency = self.meta.get("base_currency")
            errs = self._validate(self.export_bundle())
            self.blocked_errors: List[Error] = list(errs)  # stored ledger invalid -> fail closed for writes

    # ------------------------------------------------------------------ low-level access
    def _rows(self, table: str, where: Optional[Dict[str, Any]] = None,
              order_by: Optional[List[str]] = None, columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        where = {k: (None if v is None else codec.to_db(table, k, v)) for k, v in (where or {}).items()}
        sql, params = sqlbuild.select(table, columns, where, order_by)
        cols = columns or list(_table_columns(table))
        return [{c: codec.from_db(table, c, v) for c, v in zip(cols, row)} for row in self.adapter.query(sql, params)]

    def _one(self, table: str, where: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rows = self._rows(table, where)
        return rows[0] if rows else None

    def _insert(self, table: str, row: Dict[str, Any]) -> None:
        self.adapter.execute(*sqlbuild.insert(table, codec.row_to_db(table, row)))

    def _update(self, table: str, changes: Dict[str, Any], where: Dict[str, Any]) -> None:
        self.adapter.execute(*sqlbuild.update(table, codec.row_to_db(table, changes), codec.row_to_db(table, where)))

    def _delete(self, table: str, where: Dict[str, Any]) -> None:
        self.adapter.execute(*sqlbuild.delete(table, codec.row_to_db(table, where)))

    def _meta_set(self, key: str, value: str) -> None:
        if self._one("contract_meta", {"meta_key": key}):
            self._update("contract_meta", {"meta_value": value}, {"meta_key": key})
        else:
            self._insert("contract_meta", {"meta_key": key, "meta_value": value})

    # ------------------------------------------------------------------ contract shapes
    @_consistent_read
    def snapshot(self, tables: Iterable[str] = LEDGER_TABLES) -> Dict[str, List[Dict[str, Any]]]:
        return {t: self._rows(t) for t in tables}

    def export_bundle(self, snap: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
        """The whole stored ledger as a contract ledger_bundle document (deterministic order)."""
        s = snap or self.snapshot()
        by = lambda rows, key: sorted(rows, key=lambda r: r[key])  # noqa: E731
        splits = defaultdict(list)
        for sp in by(s["split"], "split_id"):
            splits[sp["transaction_id"]].append(_split_out(sp))
        buckets = defaultdict(list)
        for b in by(s["statement_bucket_balance"], "bucket_id"):
            buckets[b["statement_id"]].append({"bucket_id": b["bucket_id"], "balance_minor": b["balance_minor"]})
        items = defaultdict(list)
        for it in by(s["reconciliation_item"], "transaction_id"):
            items[it["reconciliation_id"]].append(it["transaction_id"])
        aprs = defaultdict(list)
        for b in by(s["card_apr_bucket"], "bucket_id"):
            aprs[b["terms_id"]].append(_drop_none({
                "bucket_id": b["bucket_id"], "bucket_kind": b["bucket_kind"], "apr": b["apr"],
                "promo_end_date": b["promo_end_date"], "post_promo_apr": b["post_promo_apr"],
                "deferred_interest": b["deferred_interest"]}))
        doc = {
            "contract": "perfin", "contract_version": self.contract_version, "document_type": "ledger_bundle",
            "base_currency": self.base_currency or "",
            "accounts": [_account_out(a) for a in by(s["account"], "account_id")],
            "categories": [_drop_none(dict(c)) for c in by(s["category"], "category_id")],
            "transactions": [_txn_out(t, splits[t["transaction_id"]]) for t in by(s["ledger_txn"], "transaction_id")],
            "transfer_links": [_drop_none({k: l[k] for k in ("transfer_link_id", "from_transaction_id",
                                                              "to_transaction_id", "link_status", "match_evidence")})
                               for l in by(s["transfer_link"], "transfer_link_id")],
            "statements": [_statement_out(st, buckets[st["statement_id"]]) for st in by(s["statement"], "statement_id")],
            "statement_payments": [dict(p) for p in by(s["statement_payment"], "allocation_id")],
            "reconciliations": [{"reconciliation_id": r["reconciliation_id"], "statement_id": r["statement_id"],
                                 "included_transaction_ids": items[r["reconciliation_id"]],
                                 "difference_minor": r["difference_minor"], "recon_status": r["recon_status"]}
                                for r in by(s["reconciliation"], "reconciliation_id")],
            "card_terms": [_terms_out(ct, aprs[ct["terms_id"]]) for ct in by(s["card_terms"], "terms_id")],
            "asset_valuations": [_drop_none({k: v for k, v in val.items() if k != "row_version"})
                                 for val in by(s["asset_valuation"], "valuation_id")],
        }
        return doc

    @_consistent_read
    def transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        row = self._one("ledger_txn", {"transaction_id": transaction_id})
        if row is None:
            return None
        return _txn_out(row, [_split_out(s) for s in self._rows("split", {"transaction_id": transaction_id},
                                                               order_by=["split_id"])])

    @_consistent_read
    def export_staging_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        b = self._one("import_batch", {"batch_id": batch_id})
        if b is None:
            return None
        # The immutable stage command already stores every contract field. Use it
        # for provenance not represented by the normalized 1.0 columns; reviewed
        # state and financial values below still come from authoritative rows.
        stage_id = str(uuid.uuid5(ADMIN_NAMESPACE, "stage:%s:%s" % (batch_id, b["source_file_sha256"])))
        log = self._one("command_log", {"command_id": stage_id})
        original = json.loads(log["payload_json"]) if log else {}
        original_rows = {r["row_number"]: r for r in original.get("rows", [])}
        rows = []
        for r in self._rows("staging_row", {"batch_id": batch_id}, order_by=["row_number"]):
            parsed = None
            if r["parsed_posted_date"] is not None and r["parsed_amount_minor"] is not None:
                parsed = _drop_none({"posted_date": r["parsed_posted_date"], "transaction_date": r["parsed_transaction_date"],
                                     "amount_minor": r["parsed_amount_minor"], "description": r["parsed_description"] or "",
                                     "source_txn_id": r["source_txn_id"]})
            row = {"row_number": r["row_number"], "raw_fields": json.loads(r["raw_fields_json"]), "parsed": parsed,
                   "fingerprint": r["fingerprint"], "errors": json.loads(r["errors_json"]),
                   "duplicate": _drop_none({"status": r["duplicate_status"], "matched_transaction_id": r["matched_transaction_id"]}),
                   "review_state": r["review_state"]}
            saved = original_rows.get(r["row_number"], {})
            for key in ("transfer_candidate_transaction_id",):
                if key in saved:
                    row[key] = saved[key]
            for key in ("matched_row_number", "evidence"):
                if key in saved.get("duplicate", {}):
                    row["duplicate"][key] = saved["duplicate"][key]
            if parsed is not None and "running_balance_minor" in (saved.get("parsed") or {}):
                parsed["running_balance_minor"] = saved["parsed"]["running_balance_minor"]
            if r["proposed_splits_json"]:
                row["proposed_splits"] = json.loads(r["proposed_splits_json"])
            rows.append(row)
        batch = _drop_none({k: b[k] for k in ("batch_id", "profile_id", "profile_version", "account_id", "source_file_sha256",
                                               "source_file_name", "staged_at", "importer_version", "batch_status", "committed_at")})
        return {"contract": "perfin", "contract_version": self.contract_version, "document_type": "staging_batch",
                "batch": batch, "rows": rows}

    @_consistent_read
    def summary(self) -> Dict[str, Any]:
        """Facts a restore must reproduce: versions, balances, import history and statements."""
        s = self.snapshot(LEDGER_TABLES + ("import_batch",))
        totals = defaultdict(int)
        for t in s["ledger_txn"]:
            totals[t["account_id"]] += t["amount_minor"]
        per_batch = defaultdict(int)
        for t in s["ledger_txn"]:
            if t["source_batch_id"]:
                per_batch[t["source_batch_id"]] += 1
        return {
            "schema_version": self.meta.get("schema_version"),
            "contract_version": self.meta.get("contract_version"),
            "base_currency": self.base_currency,
            "account_balances_minor": {a["account_id"]: a["opening_balance_minor"] + totals[a["account_id"]]
                                       for a in sorted(s["account"], key=lambda a: a["account_id"])},
            "import_history": [{"batch_id": b["batch_id"], "account_id": b["account_id"],
                                "source_file_sha256": b["source_file_sha256"], "batch_status": b["batch_status"],
                                "committed_at": b["committed_at"], "transactions": per_batch[b["batch_id"]]}
                               for b in sorted(s["import_batch"], key=lambda b: b["batch_id"])],
            "statements": [{"statement_id": st["statement_id"], "account_id": st["account_id"],
                            "period_end": st["period_end"], "closing_balance_minor": st["closing_balance_minor"],
                            "evidence_ref": st["evidence_ref"]}
                           for st in sorted(s["statement"], key=lambda x: x["statement_id"])],
            "reconciliations": [{"reconciliation_id": r["reconciliation_id"], "recon_status": r["recon_status"],
                                 "difference_minor": r["difference_minor"]}
                                for r in sorted(s["reconciliation"], key=lambda x: x["reconciliation_id"])],
            "row_counts": {t: len(rows) for t, rows in sorted(s.items())},
        }

    # ------------------------------------------------------------------ results
    def _result(self, command_id: str, status: str, errors: List[Error] = (), affected=(), audit_ids=()) -> Dict[str, Any]:
        doc = {"contract": "perfin", "contract_version": self.contract_version, "document_type": "command_result",
               "command_id": command_id if UUID_RE.match(command_id or "") else NIL_UUID,
               "result_status": status,
               "errors": [_drop_none({"code": c, "path": p or None, "message": (m or "")[:1000] or None})
                          for c, p, m in errors],
               "affected": [{"entity": e, "entity_id": i, "row_version": v} for (e, i), v in affected],
               "audit_ids": list(audit_ids)}
        problems = self._validate(doc)
        if problems:  # an invalid result is an internal defect, never something to hand to Excel
            raise AssertionError("internal: invalid command_result %r" % (problems,))
        return doc

    # ------------------------------------------------------------------ transaction runner
    def _run(self, ctx: _Ctx, body: Callable[[_Ctx], None], *, log_type: Optional[str] = None) -> Dict[str, Any]:
        if self.blocked_errors:
            return self._result(ctx.command_id, "rejected", [("E_SCHEMA", "$", "the stored ledger fails contract "
                                                                  "validation; writes are blocked until it is repaired")])
        self.adapter.begin()
        try:
            if self._one("command_log", {"command_id": ctx.command_id}) is not None:
                raise Replay("command_id %s was already executed" % ctx.command_id)
            body(ctx)
            if ctx.ledger_changed:
                errs = self._validate(self.export_bundle())
                if errs:
                    raise Reject([(c, p, "post-command ledger check: " + m) for c, p, m in errs])
            audit_ids = ["%s.%04d" % (ctx.command_id, i + 1) for i in range(len(ctx.audit))]
            result = self._result(ctx.command_id, "accepted", [], list(ctx.affected.items()), audit_ids)
            self._insert("command_log", {
                "command_id": ctx.command_id, "command_type": log_type or ctx.command_type,
                "issued_at": ctx.issued_at, "issued_by": ctx.issued_by,
                "payload_json": _dumps(ctx.document), "result_status": "accepted", "result_json": _dumps(result)})
            for aid, (entity, eid, action, before, after) in zip(audit_ids, ctx.audit):
                self._insert("audit_log", {
                    "audit_id": aid, "command_id": ctx.command_id, "entity": entity, "entity_id": eid,
                    "action": action, "before_json": None if before is None else _dumps(before),
                    "after_json": None if after is None else _dumps(after), "recorded_at": ctx.now})
            self.adapter.commit()
            return result
        except Reject as r:
            self._safe_rollback()
            return self._result(ctx.command_id, "rejected", r.errors)
        except Replay as r:
            self._safe_rollback()
            return self._result(ctx.command_id, "replayed", [("E_IDEMPOTENT_REPLAY", "$", r.message)], r.affected)
        except AssertionError:
            self._safe_rollback()
            raise
        except Exception as exc:
            self._safe_rollback()
            raise StorageError("command %s failed in the database and was rolled back (%s)"
                               % (ctx.command_id, type(exc).__name__)) from exc

    def _safe_rollback(self) -> None:
        try:
            self.adapter.rollback()
        except Exception:  # the original failure is what matters to the caller
            pass

    # ------------------------------------------------------------------ public entry points
    def execute(self, command: Any) -> Dict[str, Any]:
        cid = command.get("command_id") if isinstance(command, dict) else None
        cid = cid if isinstance(cid, str) and UUID_RE.match(cid) else NIL_UUID
        if not isinstance(command, dict) or command.get("document_type") != "command":
            return self._result(cid, "rejected", [("E_DOCUMENT_TYPE", "$.document_type", "expected a command document")])
        errs = self._validate(command)
        if errs:
            return self._result(cid, "rejected", errs)
        ctype = command["command_type"]
        handler = getattr(self, "_cmd_" + ctype, None)
        if handler is None:
            return self._result(cid, "rejected", [("E_COMMAND_PAYLOAD", "$.command_type",
                                                   "%s is not stored by the 1.0 Access schema (no table in the "
                                                   "reference DDL)" % ctype)])
        ctx = _Ctx(cid, ctype, command["issued_at"], command["issued_by"], command, self.clock())
        payload = command["payload"]
        return self._run(ctx, lambda c: handler(c, payload))

    @staticmethod
    def _scenario_key(scenario_id):
        return "scenario:" + hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:48]

    @_consistent_read
    def payoff_scenario(self, scenario_id):
        pointer = self._one("contract_meta", {"meta_key": self._scenario_key(scenario_id)})
        if pointer is None:
            return None
        saved = self._one("command_log", {"command_id": pointer["meta_value"]})
        if saved is None:
            raise StorageError("saved scenario pointer has no audited command")
        command = json.loads(saved["payload_json"])
        return {"contract": "perfin", "contract_version": self.contract_version,
                "document_type": "payoff_scenario", "scenario": command["payload"]}

    @_consistent_read
    def payoff_scenarios(self):
        result = []
        for row in self._rows("contract_meta"):
            if row["meta_key"].startswith("scenario:"):
                saved = self._one("command_log", {"command_id": row["meta_value"]})
                result.append(json.loads(saved["payload_json"])["payload"])
        return sorted(result, key=lambda x: x["scenario_id"])

    def _cmd_save_payoff_scenario(self, ctx, payload):
        before = self.payoff_scenario(payload["scenario_id"])
        self._meta_set(self._scenario_key(payload["scenario_id"]), ctx.command_id)
        ctx.log("payoff_scenario", payload["scenario_id"], "save", before, payload)

    def stage_batch(self, doc: Any, *, issued_by: str = "importer:stage") -> Dict[str, Any]:
        """Store a staging_batch document (import_batch + staging_row). Never touches the ledger."""
        if not isinstance(doc, dict) or doc.get("document_type") != "staging_batch":
            return self._result(NIL_UUID, "rejected", [("E_DOCUMENT_TYPE", "$.document_type", "expected staging_batch")])
        errs = self._validate(doc)
        b = doc.get("batch") or {}
        cid = str(uuid.uuid5(ADMIN_NAMESPACE, "stage:%s:%s" % (b.get("batch_id"), b.get("source_file_sha256"))))
        if errs:
            return self._result(cid, "rejected", errs)
        now = self.clock()
        ctx = _Ctx(cid, "stage_batch", now, issued_by, doc, now)
        return self._run(ctx, lambda c: self._stage(c, doc))

    def import_bundle(self, bundle: Any, *, issued_by: str = "cli:import_bundle") -> Dict[str, Any]:
        """Insert-only merge of a ledger_bundle (accounts, categories, manual history ...).

        The 1.0 contract has no command that creates accounts or categories; this logged,
        validated, all-or-nothing operation is the setup path for them. Existing ids are never
        overwritten (E_DUPLICATE_ID).
        """
        cid = str(uuid.uuid4())
        if not isinstance(bundle, dict) or bundle.get("document_type") != "ledger_bundle":
            return self._result(cid, "rejected", [("E_DOCUMENT_TYPE", "$.document_type", "expected ledger_bundle")])
        if bundle.get("base_currency") != self.base_currency:
            return self._result(cid, "rejected", [("E_CURRENCY_MISMATCH", "$.base_currency",
                                                   "database base currency is %s" % self.base_currency)])
        existing = self.export_bundle()
        merged = dict(existing, contract_version=bundle.get("contract_version"))
        for key, value in bundle.items():
            if isinstance(value, list):
                merged[key] = existing.get(key, []) + value
            elif key not in ("contract", "contract_version", "document_type", "base_currency"):
                merged[key] = value  # unknown field: the validator rejects it
        errs = self._validate(merged)  # the bundle may refer to accounts/categories already stored
        if errs:
            return self._result(cid, "rejected", [(c, p, "merged with the stored ledger: " + m) for c, p, m in errs])
        now = self.clock()
        ctx = _Ctx(cid, "import_bundle", now, issued_by, {"document_type": "ledger_bundle", "counts": {
            k: len(v) for k, v in bundle.items() if isinstance(v, list)}}, now)
        return self._run(ctx, lambda c: self._import_bundle(c, bundle))

    def set_default_categories(self, outflow_category_id: Optional[str], inflow_category_id: Optional[str],
                               *, issued_by: str = "cli:settings") -> Dict[str, Any]:
        """Categories given to approved import rows that carry no proposed_splits (else E_ROW_UNRESOLVED)."""
        cid = str(uuid.uuid4())
        now = self.clock()
        ctx = _Ctx(cid, "set_default_categories", now, issued_by,
                   {"outflow": outflow_category_id, "inflow": inflow_category_id}, now)

        def body(c: _Ctx) -> None:
            for key, value in ((META_DEFAULT_OUT, outflow_category_id), (META_DEFAULT_IN, inflow_category_id)):
                if value is not None and self._one("category", {"category_id": value}) is None:
                    reject("E_CATEGORY_UNKNOWN", "$." + key, "unknown category")
                before = self._one("contract_meta", {"meta_key": key})
                if value is None:
                    if before:
                        self._delete("contract_meta", {"meta_key": key})
                else:
                    self._meta_set(key, value)
                c.log("contract_meta", key, "update", before and before["meta_value"], value)
        result = self._run(ctx, body)
        self.meta = migrations.read_meta(self.adapter)
        return result

    # ------------------------------------------------------------------ helpers for handlers
    def _versions(self, ctx: _Ctx, required: Iterable[Tuple[str, str]] = ()) -> None:
        expected = {(e["entity"], e["entity_id"]): e["row_version"] for e in ctx.document.get("expected_versions", [])}
        errs: List[Error] = []
        for ent, eid in required:
            if (ent, eid) not in expected:
                errs.append(("E_STALE_VERSION", "$.expected_versions",
                             "expected_versions must include the current row_version of %s %s" % (ent, eid)))
        for (ent, eid), v in expected.items():
            table, key = VERSIONED[ent]
            row = self._one(table, {key: eid})
            if row is None:
                errs.append(("E_REF_UNKNOWN", "$.expected_versions", "%s %s does not exist" % (ent, eid)))
                continue
            current = row.get("row_version", 1)
            if current != v:
                errs.append(("E_STALE_VERSION", "$.expected_versions",
                             "%s %s is at row_version %d, not %d; refresh and retry" % (ent, eid, current, v)))
        if errs:
            raise Reject(errs)

    def _batch(self, batch_id: str) -> Dict[str, Any]:
        b = self._one("import_batch", {"batch_id": batch_id})
        if b is None:
            reject("E_REF_UNKNOWN", "$.payload.batch_id", "unknown batch %s" % batch_id)
        return b

    def _txn(self, tid: str, path: str) -> Dict[str, Any]:
        t = self.transaction(tid)
        if t is None:
            reject("E_REF_UNKNOWN", path, "unknown transaction %s" % tid)
        return t

    def _bump_batch(self, ctx: _Ctx, b: Dict[str, Any], changes: Dict[str, Any], action: str, note: Any = None) -> None:
        v = b["row_version"] + 1
        changes = dict(changes, row_version=v)
        self._update("import_batch", changes, {"batch_id": b["batch_id"]})
        before = {k: b[k] for k in changes}
        after = dict(changes)
        if note is not None:
            after["note"] = note
        ctx.log("import_batch", b["batch_id"], action, before, after)
        ctx.touch("batch", b["batch_id"], v)

    def _batch_status_after_review(self, batch_id: str) -> str:
        states = [r["review_state"] for r in self._rows("staging_row", {"batch_id": batch_id}, columns=["review_state"])]
        if states and all(s in ("approved", "rejected") for s in states):
            return "approved" if "approved" in states else "rejected"
        return "staged"

    def _insert_txn(self, txn: Dict[str, Any]) -> None:
        src = txn.get("source") or {}
        self._insert("ledger_txn", {
            "transaction_id": txn["transaction_id"], "account_id": txn["account_id"],
            "posted_date": txn["posted_date"], "transaction_date": txn.get("transaction_date"),
            "amount_minor": txn["amount_minor"], "currency": txn["currency"], "description": txn["description"],
            "entry_method": txn["entry_method"], "source_batch_id": src.get("batch_id"),
            "source_row_number": src.get("row_number"), "source_txn_id": src.get("source_txn_id"),
            "reverses_transaction_id": txn.get("reverses_transaction_id"), "row_version": txn["row_version"]})

    def _insert_splits(self, tid: str, splits: List[Dict[str, Any]]) -> None:
        for s in splits:
            self._insert("split", {"split_id": s["split_id"], "transaction_id": tid, "split_kind": s["split_kind"],
                                   "amount_minor": s["amount_minor"], "category_id": s.get("category_id"),
                                   "transfer_link_id": s.get("transfer_link_id"), "memo": s.get("memo")})

    def _replace_splits(self, ctx: _Ctx, before: Dict[str, Any], splits: List[Dict[str, Any]], action: str,
                        txn_changes: Optional[Dict[str, Any]] = None, reason: Optional[str] = None) -> Dict[str, Any]:
        tid = before["transaction_id"]
        taken = {s["split_id"] for s in before["splits"]}
        for i, s in enumerate(splits):
            if s["split_id"] not in taken:
                other = self._one("split", {"split_id": s["split_id"]})
                if other is not None:
                    reject("E_DUPLICATE_ID", "$.payload.splits[%d].split_id" % i, "split_id %s is used by another "
                           "transaction" % s["split_id"])
        self._delete("split", {"transaction_id": tid})
        v = before["row_version"] + 1
        self._update("ledger_txn", dict(txn_changes or {}, row_version=v), {"transaction_id": tid})
        self._insert_splits(tid, splits)
        after = self.transaction(tid)
        ctx.log("transaction", tid, action, before, after if reason is None else dict(after, reason=reason))
        ctx.touch("transaction", tid, v)
        ctx.ledger_changed = True
        return after

    def _split_refs(self, splits: List[Dict[str, Any]], path: str) -> List[Error]:
        """Reference checks that must run before writing (the engine would refuse the relationship)."""
        errs: List[Error] = []
        for i, s in enumerate(splits):
            if s.get("category_id") and self._one("category", {"category_id": s["category_id"]}) is None:
                errs.append(("E_CATEGORY_UNKNOWN", "%s[%d]" % (path, i), "unknown category %s" % s["category_id"]))
            if s.get("transfer_link_id") and self._one("transfer_link", {"transfer_link_id": s["transfer_link_id"]}) is None:
                errs.append(("E_TRANSFER_UNPAIRED", "%s[%d]" % (path, i), "unknown transfer link %s" % s["transfer_link_id"]))
        return errs

    def _new_txn_id(self, tid: str, path: str) -> None:
        if self._one("ledger_txn", {"transaction_id": tid}) is not None:
            reject("E_DUPLICATE_ID", path, "transaction %s already exists" % tid)

    def _reversal_of(self, orig: Dict[str, Any], rid: str, posted_date: str) -> Dict[str, Any]:
        return {"transaction_id": rid, "account_id": orig["account_id"], "posted_date": posted_date,
                "transaction_date": None, "amount_minor": -orig["amount_minor"], "currency": orig["currency"],
                "description": ("REVERSAL: " + orig["description"])[:1000], "entry_method": "reversal",
                "reverses_transaction_id": orig["transaction_id"], "row_version": 1,
                "splits": [_drop_none({"split_id": derive_id(rid, "s%d" % (i + 1), prefix="sp"), "split_kind": s["split_kind"],
                                       "amount_minor": -s["amount_minor"], "category_id": s.get("category_id"),
                                       "transfer_link_id": s.get("transfer_link_id"), "memo": s.get("memo")})
                           for i, s in enumerate(orig["splits"])]}

    def _post_reversal(self, ctx: _Ctx, orig: Dict[str, Any], rid: str, posted_date: str, reason: str, path: str) -> None:
        if any(s["split_kind"] == "transfer" for s in orig["splits"]):
            reject("E_TRANSFER_UNPAIRED", path, "transaction %s is a linked transfer leg; unlink_transfer and "
                   "set_splits instead of reversing it (1.0 limit)" % orig["transaction_id"])
        if self._one("ledger_txn", {"reverses_transaction_id": orig["transaction_id"]}) is not None:
            reject("E_DUPLICATE_ID", path, "transaction %s is already reversed" % orig["transaction_id"])
        self._new_txn_id(rid, path)
        rev = self._reversal_of(orig, rid, posted_date)
        self._insert_txn(rev)
        self._insert_splits(rid, rev["splits"])
        ctx.log("transaction", rid, "reverse", None, dict(rev, reason=reason))
        ctx.touch("transaction", rid, 1)
        ctx.ledger_changed = True

    def _default_split(self, tid: str, amount: int, n: int = 1) -> Optional[Dict[str, Any]]:
        key = META_DEFAULT_OUT if amount < 0 else META_DEFAULT_IN
        cat = self.meta.get(key)
        if not cat:
            return None
        return {"split_id": derive_id(tid, "s%d" % n, prefix="sp"), "split_kind": "category",
                "amount_minor": amount, "category_id": cat}

    # ------------------------------------------------------------------ staging
    def _stage(self, ctx: _Ctx, doc: Dict[str, Any]) -> None:
        b = doc["batch"]
        if b["batch_status"] != "staged":
            reject("E_BATCH_STATE", "$.batch.batch_status", "new batches must have batch_status 'staged'")
        acct = self._one("account", {"account_id": b["account_id"]})
        if acct is None:
            reject("E_ACCOUNT_UNKNOWN", "$.batch.account_id", "unknown account %s" % b["account_id"])
        same_file = self._one("import_batch", {"account_id": b["account_id"], "source_file_sha256": b["source_file_sha256"]})
        if same_file is not None:
            raise Replay("this file was already staged for this account as batch %s" % same_file["batch_id"],
                         [(("batch", same_file["batch_id"]), same_file["row_version"])])
        if self._one("import_batch", {"batch_id": b["batch_id"]}) is not None:
            reject("E_DUPLICATE_ID", "$.batch.batch_id", "batch %s already exists for another file" % b["batch_id"])
        self._insert("import_batch", {
            "batch_id": b["batch_id"], "profile_id": b["profile_id"], "profile_version": b["profile_version"],
            "account_id": b["account_id"], "source_file_sha256": b["source_file_sha256"],
            "source_file_name": b["source_file_name"], "staged_at": b["staged_at"], "committed_at": None,
            "importer_version": b["importer_version"], "batch_status": "staged", "row_version": 1})
        for r in doc["rows"]:
            p = r.get("parsed") or {}
            self._insert("staging_row", {
                "batch_id": b["batch_id"], "row_number": r["row_number"], "raw_fields_json": _dumps(r["raw_fields"]),
                "parsed_posted_date": p.get("posted_date"), "parsed_transaction_date": p.get("transaction_date"),
                "parsed_amount_minor": p.get("amount_minor"), "parsed_description": p.get("description"),
                "source_txn_id": p.get("source_txn_id"), "fingerprint": r["fingerprint"],
                "errors_json": _dumps(r["errors"]), "duplicate_status": r["duplicate"]["status"],
                "matched_transaction_id": r["duplicate"].get("matched_transaction_id"),
                "review_state": r["review_state"],
                "proposed_splits_json": _dumps(r["proposed_splits"]) if r.get("proposed_splits") else None})
        status = self._batch_status_after_review(b["batch_id"])
        version = 1
        if status != "staged":
            version = 2
            self._update("import_batch", {"batch_status": status, "row_version": 2}, {"batch_id": b["batch_id"]})
        ctx.log("import_batch", b["batch_id"], "stage", None,
                {"batch_status": status, "rows": len(doc["rows"]), "source_file_sha256": b["source_file_sha256"]})
        ctx.touch("batch", b["batch_id"], version)

    def _review_target(self, ctx: _Ctx, batch_id: str) -> Tuple[Dict[str, Any], Dict[int, Dict[str, Any]]]:
        b = self._batch(batch_id)
        self._versions(ctx, [("batch", batch_id)])
        if b["batch_status"] not in ("staged", "approved", "rejected"):
            reject("E_BATCH_STATE", "$.payload.batch_id", "batch %s is %s; rows can no longer be reviewed"
                   % (batch_id, b["batch_status"]))
        return b, {r["row_number"]: r for r in self._rows("staging_row", {"batch_id": batch_id})}

    def _cmd_approve_rows(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        b, rows = self._review_target(ctx, p["batch_id"])
        errs: List[Error] = []
        for i, n in enumerate(p["row_numbers"]):
            path = "$.payload.row_numbers[%d]" % i
            r = rows.get(n)
            if r is None:
                errs.append(("E_REF_UNKNOWN", path, "batch has no row %d" % n))
            elif json.loads(r["errors_json"]) or r["parsed_posted_date"] is None or r["parsed_amount_minor"] is None:
                errs.append(("E_ROW_UNRESOLVED", path, "row %d has parse errors and cannot be approved" % n))
            elif r["duplicate_status"] not in APPROVABLE_DUP:
                errs.append(("E_DUPLICATE_UNRESOLVED", path, "row %d duplicate status is %s; resolve it or reject the row"
                             % (n, r["duplicate_status"])))
        if errs:
            raise Reject(errs)
        self._set_review(ctx, b, rows, p["row_numbers"], "approved", None)

    def _cmd_reject_rows(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        b, rows = self._review_target(ctx, p["batch_id"])
        missing = [("E_REF_UNKNOWN", "$.payload.row_numbers[%d]" % i, "batch has no row %d" % n)
                   for i, n in enumerate(p["row_numbers"]) if n not in rows]
        if missing:
            raise Reject(missing)
        self._set_review(ctx, b, rows, p["row_numbers"], "rejected", p["reason"])

    def _set_review(self, ctx: _Ctx, b, rows, numbers, state: str, reason: Optional[str]) -> None:
        for n in numbers:
            old = rows[n]["review_state"]
            self._update("staging_row", {"review_state": state}, {"batch_id": b["batch_id"], "row_number": n})
            after = {"review_state": state}
            if reason:
                after["reason"] = reason
            ctx.log("staging_row", derive_id(b["batch_id"], "r%d" % n, prefix="row"), state[:-1] if state.endswith("d") else state,
                    {"review_state": old}, after)
        self._bump_batch(ctx, b, {"batch_status": self._batch_status_after_review(b["batch_id"])}, "review")

    def _cmd_resolve_duplicate(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        b, rows = self._review_target(ctx, p["batch_id"])
        r = rows.get(p["row_number"])
        if r is None:
            reject("E_REF_UNKNOWN", "$.payload.row_number", "batch has no row %d" % p["row_number"])
        # A concurrent import or the in-batch guard can discover a source-ID
        # collision after staging. Permit explicit human resolution of that
        # collision, without allowing arbitrary clean rows to bypass review.
        source_id = r["source_txn_id"]
        detected = r["duplicate_status"] == "none" and source_id and (
            bool(self._rows("ledger_txn", {"account_id": b["account_id"], "source_txn_id": source_id},
                            columns=["transaction_id"]))
            or any(other["row_number"] < r["row_number"] and other["review_state"] == "approved"
                   and other["source_txn_id"] == source_id for other in rows.values()))
        if r["duplicate_status"] != "possible" and not detected:
            reject("E_BATCH_STATE", "$.payload.row_number", "row %d has duplicate status %s; only 'possible' "
                   "or source-ID collisions are resolved" % (p["row_number"], r["duplicate_status"]))
        self._update("staging_row", {"duplicate_status": p["resolution"]},
                     {"batch_id": b["batch_id"], "row_number": p["row_number"]})
        ctx.log("staging_row", derive_id(b["batch_id"], "r%d" % p["row_number"], prefix="row"), "resolve",
                {"duplicate_status": r["duplicate_status"]}, {"duplicate_status": p["resolution"]})
        self._bump_batch(ctx, b, {}, "review")

    # ------------------------------------------------------------------ commit / rollback
    def _cmd_commit_batch(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        b = self._batch(p["batch_id"])
        if b["source_file_sha256"] != p["source_file_sha256"]:
            reject("E_BATCH_STATE", "$.payload.source_file_sha256", "does not match the staged file of batch %s" % b["batch_id"])
        if b["batch_status"] == "committed":
            raise Replay("batch %s (this file) is already committed; nothing changed" % b["batch_id"],
                         [(("batch", b["batch_id"]), b["row_version"])])
        self._versions(ctx, [("batch", b["batch_id"])])
        if b["batch_status"] != "approved":
            why = {"staged": "every row must be approved or rejected first",
                   "rejected": "every row was rejected; there is nothing to commit",
                   "rolled_back": "a rolled-back batch cannot be committed again"}.get(b["batch_status"], b["batch_status"])
            reject("E_BATCH_STATE", "$.payload.batch_id", why)
        acct = self._one("account", {"account_id": b["account_id"]})
        known_source_ids = {t["source_txn_id"] for t in self._rows("ledger_txn", {"account_id": b["account_id"]},
                                                                   columns=["source_txn_id"]) if t["source_txn_id"]}
        batch_source_ids: Dict[str, int] = {}  # source_txn_id -> first approved row number in this batch
        errs: List[Error] = []
        txns = []
        for r in self._rows("staging_row", {"batch_id": b["batch_id"]}, order_by=["row_number"]):
            if r["review_state"] != "approved":
                continue
            n = r["row_number"]
            path = "$.rows[row_number=%d]" % n
            if json.loads(r["errors_json"]) or r["parsed_posted_date"] is None or r["parsed_amount_minor"] is None:
                errs.append(("E_ROW_UNRESOLVED", path, "approved row has parse errors"))
                continue
            if r["duplicate_status"] not in APPROVABLE_DUP:
                errs.append(("E_DUPLICATE_UNRESOLVED", path, "approved row has an unresolved duplicate"))
                continue
            if r["source_txn_id"] and r["duplicate_status"] != "confirmed_distinct":
                # Same account (a batch has one account), same source id: an exact re-import, whether the earlier
                # occurrence is already stored or an earlier approved row of this batch.
                if r["source_txn_id"] in known_source_ids:
                    errs.append(("E_DUPLICATE_UNRESOLVED", path, "source transaction id is already in the ledger for "
                                 "this account; resolve it as confirmed_distinct or reject the row"))
                    continue
                if r["source_txn_id"] in batch_source_ids:
                    errs.append(("E_DUPLICATE_UNRESOLVED", path, "source transaction id repeats row %d of this batch; "
                                 "resolve it as confirmed_distinct or reject the row" % batch_source_ids[r["source_txn_id"]]))
                    continue
            tid = derive_id(b["batch_id"], "r%d" % n, prefix="imp")
            if self._one("ledger_txn", {"transaction_id": tid}) is not None:
                errs.append(("E_DUPLICATE_ID", path, "transaction %s already exists" % tid))
                continue
            amount = r["parsed_amount_minor"]
            proposed = json.loads(r["proposed_splits_json"]) if r["proposed_splits_json"] else []
            if proposed:
                splits = [_drop_none({"split_id": derive_id(tid, "s%d" % (i + 1), prefix="sp"), "split_kind": s["split_kind"],
                                      "amount_minor": s["amount_minor"], "category_id": s.get("category_id"),
                                      "transfer_link_id": s.get("transfer_link_id"), "memo": s.get("memo")})
                          for i, s in enumerate(proposed)]
                if sum(s["amount_minor"] for s in splits) != amount:
                    errs.append(("E_SPLITS_UNBALANCED", path, "proposed splits must sum to the parsed amount"))
                    continue
                ref_errs = self._split_refs(splits, path + ".proposed_splits")
                if ref_errs:
                    errs.extend(ref_errs)
                    continue
            else:
                d = self._default_split(tid, amount)
                if d is None:
                    errs.append(("E_ROW_UNRESOLVED", path, "approved row has no proposed splits and no default "
                                 "category is configured; categorize it before commit"))
                    continue
                splits = [d]
            txns.append({"transaction_id": tid, "account_id": b["account_id"], "posted_date": r["parsed_posted_date"],
                         "transaction_date": r["parsed_transaction_date"], "amount_minor": amount,
                         "currency": acct["currency"], "description": r["parsed_description"] or "",
                         "entry_method": "import", "row_version": 1, "splits": splits,
                         "source": _drop_none({"batch_id": b["batch_id"], "row_number": n, "source_txn_id": r["source_txn_id"]})})
            if r["source_txn_id"]:
                batch_source_ids.setdefault(r["source_txn_id"], n)
        if errs:
            raise Reject(errs)
        for t in txns:
            self._insert_txn(t)
            self._insert_splits(t["transaction_id"], t["splits"])
            ctx.log("transaction", t["transaction_id"], "insert", None, t)
            ctx.touch("transaction", t["transaction_id"], 1)
        ctx.ledger_changed = True
        self._bump_batch(ctx, b, {"batch_status": "committed", "committed_at": ctx.now}, "commit",
                         {"transactions": len(txns)})

    def _cmd_rollback_batch(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        b = self._batch(p["batch_id"])
        self._versions(ctx, [("batch", b["batch_id"])])
        if b["batch_status"] != "committed":
            reject("E_BATCH_STATE", "$.payload.batch_id", "only a committed batch can be rolled back (it is %s)" % b["batch_status"])
        rows = self._rows("ledger_txn", {"source_batch_id": b["batch_id"]}, order_by=["transaction_id"])
        errs: List[Error] = []
        for t in rows:
            tid = t["transaction_id"]
            if self._rows("reconciliation_item", {"transaction_id": tid}):
                errs.append(("E_BATCH_STATE", "$.payload.batch_id", "%s is reconciled; rollback is refused" % tid))
            if self._rows("statement_payment", {"transaction_id": tid}):
                errs.append(("E_BATCH_STATE", "$.payload.batch_id", "%s is allocated to a statement; remove the "
                             "allocation first" % tid))
            if self._rows("split", {"transaction_id": tid, "split_kind": "transfer"}):
                errs.append(("E_BATCH_STATE", "$.payload.batch_id", "%s is a linked transfer leg; unlink it first" % tid))
        if errs:
            raise Reject(errs)
        reversed_count = 0
        for t in rows:
            if self._one("ledger_txn", {"reverses_transaction_id": t["transaction_id"]}) is not None:
                continue  # already reversed individually
            orig = self.transaction(t["transaction_id"])
            self._post_reversal(ctx, orig, derive_id(orig["transaction_id"], "rev", prefix="rev"), orig["posted_date"],
                                p["reason"], "$.payload.batch_id")
            reversed_count += 1
        ctx.ledger_changed = True
        self._bump_batch(ctx, b, {"batch_status": "rolled_back"}, "rollback",
                         {"reason": p["reason"], "reversals": reversed_count})

    # ------------------------------------------------------------------ transaction edits
    def _cmd_edit_transaction(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        before = self._txn(p["transaction_id"], "$.payload.transaction_id")
        self._versions(ctx, [("transaction", before["transaction_id"])])
        ch = p["changes"]
        txn_changes = {k: ch[k] for k in ("description", "transaction_date", "posted_date", "amount_minor") if k in ch}
        splits = [dict(s) for s in before["splits"]]
        if "amount_minor" in ch and ch["amount_minor"] != before["amount_minor"]:
            if len(splits) != 1:
                reject("E_SPLITS_UNBALANCED", "$.payload.changes.amount_minor", "this transaction has %d splits; use "
                       "set_splits to collapse them to one before changing the amount" % len(splits))
            splits[0]["amount_minor"] = ch["amount_minor"]
        self._replace_splits(ctx, before, splits, "update", txn_changes, reason=p["reason"])

    def _cmd_set_splits(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        before = self._txn(p["transaction_id"], "$.payload.transaction_id")
        self._versions(ctx, [("transaction", before["transaction_id"])])
        if sum(s["amount_minor"] for s in p["splits"]) != before["amount_minor"]:
            reject("E_SPLITS_UNBALANCED", "$.payload.splits", "splits must sum to the transaction amount")
        errs = self._split_refs(p["splits"], "$.payload.splits")
        if errs:
            raise Reject(errs)
        self._replace_splits(ctx, before, [_drop_none(dict(s)) for s in p["splits"]], "set_splits")

    def _cmd_reverse_transaction(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        orig = self._txn(p["transaction_id"], "$.payload.transaction_id")
        self._versions(ctx, [("transaction", orig["transaction_id"])])
        self._post_reversal(ctx, orig, p["reversal_transaction_id"], p["posted_date"], p["reason"],
                            "$.payload.reversal_transaction_id")

    # ------------------------------------------------------------------ transfers
    def _cmd_link_transfer(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        lid = p["transfer_link_id"]
        if self._one("transfer_link", {"transfer_link_id": lid}) is not None:
            reject("E_DUPLICATE_ID", "$.payload.transfer_link_id", "link %s already exists" % lid)
        f = self._txn(p["from_transaction_id"], "$.payload.from_transaction_id")
        t = self._txn(p["to_transaction_id"], "$.payload.to_transaction_id")
        self._versions(ctx, [("transaction", f["transaction_id"]), ("transaction", t["transaction_id"])])
        if f["transaction_id"] == t["transaction_id"] or f["account_id"] == t["account_id"]:
            reject("E_TRANSFER_SAME_ACCOUNT", "$.payload", "transfer legs must be on different accounts")
        if f["amount_minor"] >= 0 or t["amount_minor"] != -f["amount_minor"]:
            reject("E_TRANSFER_AMOUNT", "$.payload", "the from leg must be negative and equal to minus the to leg "
                   "(the 1.0 store links whole transactions)")
        for leg, name in ((f, "from_transaction_id"), (t, "to_transaction_id")):
            if any(s["split_kind"] == "transfer" for s in leg["splits"]):
                reject("E_TRANSFER_UNPAIRED", "$.payload." + name, "%s is already a transfer leg" % leg["transaction_id"])
        self._insert("transfer_link", {"transfer_link_id": lid, "from_transaction_id": f["transaction_id"],
                                       "to_transaction_id": t["transaction_id"], "link_status": p["link_status"],
                                       "match_evidence": p.get("match_evidence"), "row_version": 1})
        ctx.log("transfer_link", lid, "insert", None, _drop_none(dict(p)))
        ctx.touch("transfer_link", lid, 1)
        for leg in (f, t):
            split = {"split_id": derive_id(leg["transaction_id"], "tl", lid, prefix="sp"), "split_kind": "transfer",
                     "amount_minor": leg["amount_minor"], "transfer_link_id": lid}
            self._replace_splits(ctx, leg, [split], "link")

    def _cmd_unlink_transfer(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        lid = p["transfer_link_id"]
        link = self._one("transfer_link", {"transfer_link_id": lid})
        if link is None:
            reject("E_REF_UNKNOWN", "$.payload.transfer_link_id", "unknown link %s" % lid)
        self._versions(ctx, [("transfer_link", lid)])
        legs = [self.transaction(link["from_transaction_id"]), self.transaction(link["to_transaction_id"])]
        # Splits referencing the link must go before the link row (relationship split -> transfer_link).
        for leg in legs:
            restored = self._pre_link_splits(leg["transaction_id"], lid)
            if restored is None:
                keep = [s for s in leg["splits"] if s.get("transfer_link_id") != lid]
                amount = sum(s["amount_minor"] for s in leg["splits"] if s.get("transfer_link_id") == lid)
                d = self._default_split(leg["transaction_id"], amount, n=len(leg["splits"]) + 1)
                if d is None:
                    reject("E_TRANSFER_UNPAIRED", "$.payload.transfer_link_id", "no pre-link splits are recorded for %s "
                           "and no default category is configured; configure one first" % leg["transaction_id"])
                d["split_id"] = derive_id(leg["transaction_id"], "ul", lid, prefix="sp")
                restored = keep + [d]
            self._replace_splits(ctx, leg, restored, "unlink")
        self._delete("transfer_link", {"transfer_link_id": lid})
        ctx.log("transfer_link", lid, "delete", _drop_none({k: link[k] for k in link}), {"reason": p["reason"]})
        ctx.touch("transfer_link", lid, link["row_version"])

    def _pre_link_splits(self, tid: str, lid: str) -> Optional[List[Dict[str, Any]]]:
        """The splits a leg had before link_transfer replaced them (from the audit trail)."""
        best = None
        best_version = -1
        for row in self._rows("audit_log", {"entity": "transaction", "entity_id": tid, "action": "link"},
                              columns=["audit_id", "recorded_at", "before_json", "after_json"]):
            after = json.loads(row["after_json"] or "null") or {}
            if any(s.get("transfer_link_id") == lid for s in after.get("splits", [])):
                # Transaction versions increase on every edit, including unlink
                # and relink. Clock seconds and random command UUIDs do not.
                version = after.get("row_version", 0)
                if version > best_version:
                    best = row
                    best_version = version
        if best is None:
            return None
        splits = (json.loads(best["before_json"] or "null") or {}).get("splits") or []
        if not splits or any(s["split_kind"] == "transfer" for s in splits):
            return None
        return splits

    # ------------------------------------------------------------------ statements
    def _cmd_record_statement(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        sid = p["statement_id"]
        if self._one("account", {"account_id": p["account_id"]}) is None:
            reject("E_ACCOUNT_UNKNOWN", "$.payload.account_id", "unknown account")
        ref = p.get("evidence_ref")
        if ref and ("/" in ref or "\\" in ref):
            reject("E_PATTERN", "$.payload.evidence_ref", "evidence_ref is an opaque reference (for example a file "
                   "hash), never a path; statement PDFs stay outside the database")
        ids = [bk["bucket_id"] for bk in p.get("bucket_balances", [])]
        if len(ids) != len(set(ids)):
            reject("E_DUPLICATE_ID", "$.payload.bucket_balances", "bucket_id values must be unique per statement")
        row = {k: p.get(k) for k in ("account_id", "period_start", "period_end", "due_date", "opening_balance_minor",
                                     "closing_balance_minor", "minimum_due_minor", "interest_charged_minor",
                                     "fees_charged_minor", "evidence_ref")}
        existing = self._one("statement", {"statement_id": sid})
        before = None
        if existing is None:
            self._insert("statement", dict(row, statement_id=sid, row_version=1))
            v = 1
        else:
            self._versions(ctx, [("statement", sid)])
            before = self._statement_doc(sid)
            v = existing["row_version"] + 1
            self._update("statement", dict(row, row_version=v), {"statement_id": sid})
            self._delete("statement_bucket_balance", {"statement_id": sid})
        for bk in p.get("bucket_balances", []):
            self._insert("statement_bucket_balance", {"statement_id": sid, "bucket_id": bk["bucket_id"],
                                                      "balance_minor": bk["balance_minor"]})
        ctx.log("statement", sid, "insert" if before is None else "update", before, _drop_none(dict(p)))
        ctx.touch("statement", sid, v)
        ctx.ledger_changed = True

    def _statement_doc(self, sid: str) -> Dict[str, Any]:
        st = self._one("statement", {"statement_id": sid})
        return _statement_out(st, [{"bucket_id": b["bucket_id"], "balance_minor": b["balance_minor"]}
                                   for b in self._rows("statement_bucket_balance", {"statement_id": sid}, order_by=["bucket_id"])])

    def _cmd_allocate_statement_payment(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        if self._one("statement_payment", {"allocation_id": p["allocation_id"]}) is not None:
            reject("E_DUPLICATE_ID", "$.payload.allocation_id", "allocation already exists")
        if self._one("statement", {"statement_id": p["statement_id"]}) is None:
            reject("E_REF_UNKNOWN", "$.payload.statement_id", "unknown statement")
        self._txn(p["transaction_id"], "$.payload.transaction_id")
        self._versions(ctx)
        self._insert("statement_payment", dict(p))
        ctx.log("statement_payment", p["allocation_id"], "insert", None, dict(p))
        ctx.touch("statement_payment", p["allocation_id"], 1)
        ctx.ledger_changed = True

    def _cmd_remove_statement_payment(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        row = self._one("statement_payment", {"allocation_id": p["allocation_id"]})
        if row is None:
            reject("E_REF_UNKNOWN", "$.payload.allocation_id", "unknown allocation")
        self._versions(ctx)
        self._delete("statement_payment", {"allocation_id": p["allocation_id"]})
        ctx.log("statement_payment", p["allocation_id"], "delete", row, {"reason": p["reason"]})
        ctx.touch("statement_payment", p["allocation_id"], 1)
        ctx.ledger_changed = True

    def _cmd_reconcile_statement(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        rid = p["reconciliation_id"]
        if self._one("statement", {"statement_id": p["statement_id"]}) is None:
            reject("E_REF_UNKNOWN", "$.payload.statement_id", "unknown statement")
        for i, tid in enumerate(p["included_transaction_ids"]):
            for item in self._rows("reconciliation_item", {"transaction_id": tid}):
                if item["reconciliation_id"] != rid:
                    reject("E_DUPLICATE_ID", "$.payload.included_transaction_ids[%d]" % i,
                           "%s is already in reconciliation %s" % (tid, item["reconciliation_id"]))
            if self._one("ledger_txn", {"transaction_id": tid}) is None:
                reject("E_REF_UNKNOWN", "$.payload.included_transaction_ids[%d]" % i, "unknown transaction %s" % tid)
        existing = self._one("reconciliation", {"reconciliation_id": rid})
        row = {"statement_id": p["statement_id"], "difference_minor": p["difference_minor"], "recon_status": p["recon_status"]}
        before = None
        if existing is None:
            self._insert("reconciliation", dict(row, reconciliation_id=rid, row_version=1))
            v = 1
        else:
            self._versions(ctx, [("reconciliation", rid)])
            before = dict(existing, included_transaction_ids=sorted(
                i["transaction_id"] for i in self._rows("reconciliation_item", {"reconciliation_id": rid})))
            v = existing["row_version"] + 1
            self._update("reconciliation", dict(row, row_version=v), {"reconciliation_id": rid})
            self._delete("reconciliation_item", {"reconciliation_id": rid})
        for tid in p["included_transaction_ids"]:
            self._insert("reconciliation_item", {"reconciliation_id": rid, "transaction_id": tid})
        ctx.log("reconciliation", rid, "insert" if before is None else "update", before, dict(p))
        ctx.touch("reconciliation", rid, v)
        ctx.ledger_changed = True

    # ------------------------------------------------------------------ valuations and card terms
    def _cmd_record_valuation(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        vid = p["valuation_id"]
        if self._one("account", {"account_id": p["account_id"]}) is None:
            reject("E_ACCOUNT_UNKNOWN", "$.payload.account_id", "unknown account")
        row = {k: p.get(k) for k in ("account_id", "as_of", "value_minor", "currency", "valuation_source",
                                     "valuation_method", "cost_basis_minor")}
        existing = self._one("asset_valuation", {"valuation_id": vid})
        if existing is None:
            self._insert("asset_valuation", dict(row, valuation_id=vid, row_version=1))
            v = 1
        else:
            self._versions(ctx, [("asset_valuation", vid)])
            v = existing["row_version"] + 1
            self._update("asset_valuation", dict(row, row_version=v), {"valuation_id": vid})
        ctx.log("asset_valuation", vid, "insert" if existing is None else "update", existing, dict(p))
        ctx.touch("asset_valuation", vid, v)
        ctx.ledger_changed = True

    def _cmd_set_card_terms(self, ctx: _Ctx, p: Dict[str, Any]) -> None:
        tid = p["terms_id"]
        if self._one("account", {"account_id": p["account_id"]}) is None:
            reject("E_ACCOUNT_UNKNOWN", "$.payload.account_id", "unknown account")
        rule = p["min_payment_rule"]
        row = {"account_id": p["account_id"], "effective_from": p["effective_from"], "effective_to": p.get("effective_to"),
               "terms_source": p["terms_source"], "credit_limit_minor": p.get("credit_limit_minor"),
               "min_rule_type": rule["rule_type"], "min_amount_minor": rule.get("amount_minor"),
               "min_pct": rule.get("pct"), "min_floor_minor": rule.get("floor_minor")}
        existing = self._one("card_terms", {"terms_id": tid})
        before = None
        if existing is None:
            self._insert("card_terms", dict(row, terms_id=tid, row_version=1))
            v = 1
        else:
            self._versions(ctx, [("card_terms", tid)])
            before = _terms_out(existing, [_drop_none({k: b[k] for k in b if k != "terms_id"})
                                           for b in self._rows("card_apr_bucket", {"terms_id": tid}, order_by=["bucket_id"])])
            v = existing["row_version"] + 1
            self._update("card_terms", dict(row, row_version=v), {"terms_id": tid})
            self._delete("card_apr_bucket", {"terms_id": tid})
        for bk in p["apr_buckets"]:
            self._insert("card_apr_bucket", {"terms_id": tid, "bucket_id": bk["bucket_id"], "bucket_kind": bk["bucket_kind"],
                                             "apr": bk["apr"], "promo_end_date": bk.get("promo_end_date"),
                                             "post_promo_apr": bk.get("post_promo_apr"),
                                             "deferred_interest": bk["deferred_interest"]})
        ctx.log("card_terms", tid, "insert" if before is None else "update", before, dict(p))
        ctx.touch("card_terms", tid, v)
        ctx.ledger_changed = True

    # ------------------------------------------------------------------ bundle import (admin)
    def _import_bundle(self, ctx: _Ctx, bd: Dict[str, Any]) -> None:
        if bd["base_currency"] != self.base_currency:
            reject("E_CURRENCY_MISMATCH", "$.base_currency", "database base currency is %s" % self.base_currency)
        checks = (("accounts", "account", "account_id"), ("categories", "category", "category_id"),
                  ("transactions", "ledger_txn", "transaction_id"), ("transfer_links", "transfer_link", "transfer_link_id"),
                  ("statements", "statement", "statement_id"), ("statement_payments", "statement_payment", "allocation_id"),
                  ("reconciliations", "reconciliation", "reconciliation_id"), ("card_terms", "card_terms", "terms_id"),
                  ("asset_valuations", "asset_valuation", "valuation_id"))
        errs: List[Error] = []
        for coll, table, key in checks:
            for i, item in enumerate(bd.get(coll, [])):
                if self._one(table, {key: item[key]}) is not None:
                    errs.append(("E_DUPLICATE_ID", "$.%s[%d]" % (coll, i), "%s %s already exists" % (key, item[key])))
        for i, t in enumerate(bd["transactions"]):
            for j, s in enumerate(t["splits"]):
                if self._one("split", {"split_id": s["split_id"]}) is not None:
                    errs.append(("E_DUPLICATE_ID", "$.transactions[%d].splits[%d]" % (i, j), "split_id exists"))
            src = t.get("source")
            if src:
                b = self._one("import_batch", {"batch_id": src["batch_id"]})
                if b is None or b["batch_status"] != "committed":
                    errs.append(("E_REF_UNKNOWN", "$.transactions[%d].source" % i,
                                 "imported transactions need their committed import batch in this database"))
        if errs:
            raise Reject(errs)
        for a in bd["accounts"]:
            self._insert("account", _account_in(a))
            ctx.log("account", a["account_id"], "insert", None, a)
            ctx.touch("account", a["account_id"], a["row_version"])
        pending = list(bd["categories"])
        known = {c["category_id"] for c in self._rows("category", columns=["category_id"])}
        while pending:  # parents first
            ready = [c for c in pending if not c.get("parent_category_id") or c["parent_category_id"] in known]
            if not ready:
                reject("E_CATEGORY_UNKNOWN", "$.categories", "unknown or cyclic parent category")
            for c in ready:
                self._insert("category", {"category_id": c["category_id"], "name": c["name"],
                                          "category_kind": c["category_kind"], "parent_category_id": c.get("parent_category_id")})
                ctx.log("category", c["category_id"], "insert", None, c)
                known.add(c["category_id"])
                pending.remove(c)
        pending = list(bd["transactions"])
        known = {t["transaction_id"] for t in self._rows("ledger_txn", columns=["transaction_id"])}
        while pending:  # originals before their reversals
            ready = [t for t in pending if not t.get("reverses_transaction_id") or t["reverses_transaction_id"] in known]
            if not ready:
                reject("E_REF_UNKNOWN", "$.transactions", "reversal of an unknown transaction")
            for t in ready:
                self._insert_txn(t)
                known.add(t["transaction_id"])
                pending.remove(t)
                ctx.log("transaction", t["transaction_id"], "insert", None, t)
                ctx.touch("transaction", t["transaction_id"], t["row_version"])
        for l in bd.get("transfer_links", []):
            self._insert("transfer_link", {"transfer_link_id": l["transfer_link_id"], "from_transaction_id": l["from_transaction_id"],
                                           "to_transaction_id": l["to_transaction_id"], "link_status": l["link_status"],
                                           "match_evidence": l.get("match_evidence"), "row_version": 1})
            ctx.log("transfer_link", l["transfer_link_id"], "insert", None, l)
            ctx.touch("transfer_link", l["transfer_link_id"], 1)
        for t in bd["transactions"]:
            self._insert_splits(t["transaction_id"], t["splits"])
        sub = lambda name, payload: {"payload": payload, "expected_versions": [], "command_type": name}  # noqa: E731
        for coll, name in (("statements", "record_statement"), ("statement_payments", "allocate_statement_payment"),
                           ("reconciliations", "reconcile_statement"), ("card_terms", "set_card_terms"),
                           ("asset_valuations", "record_valuation")):
            for item in bd.get(coll, []):
                inner = _Ctx(ctx.command_id, name, ctx.issued_at, ctx.issued_by, sub(name, item), ctx.now)
                getattr(self, "_cmd_" + name)(inner, item)
                ctx.audit.extend(inner.audit)
                ctx.affected.update(inner.affected)
        ctx.ledger_changed = True


# ---------------------------------------------------------------------- row <-> contract
_COLUMNS_CACHE: Dict[str, Tuple[str, ...]] = {}


def _table_columns(table: str) -> Tuple[str, ...]:
    if table not in _COLUMNS_CACHE:
        from . import ddl
        _COLUMNS_CACHE[table] = tuple(ddl.table(table).columns)
    return _COLUMNS_CACHE[table]


def _account_in(a: Dict[str, Any]) -> Dict[str, Any]:
    row = {k: a.get(k) for k in _table_columns("account")}
    # Access Yes/No cannot hold Null [Unverified]: an absent flag is stored as included (TRUE).
    row["include_in_net_worth"] = a.get("include_in_net_worth", True)
    return row


def _account_out(r: Dict[str, Any]) -> Dict[str, Any]:
    return _drop_none(dict(r))


def _split_out(r: Dict[str, Any]) -> Dict[str, Any]:
    return _drop_none({k: r[k] for k in ("split_id", "split_kind", "amount_minor", "category_id", "transfer_link_id", "memo")})


def _txn_out(r: Dict[str, Any], splits: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {k: r[k] for k in ("transaction_id", "account_id", "posted_date", "amount_minor", "currency", "description",
                             "entry_method")}
    if r["transaction_date"] is not None:
        out["transaction_date"] = r["transaction_date"]
    if r["source_batch_id"] is not None:
        out["source"] = _drop_none({"batch_id": r["source_batch_id"], "row_number": r["source_row_number"],
                                    "source_txn_id": r["source_txn_id"]})
    if r["reverses_transaction_id"] is not None:
        out["reverses_transaction_id"] = r["reverses_transaction_id"]
    out["splits"] = splits
    out["row_version"] = r["row_version"]
    return out


def _statement_out(r: Dict[str, Any], buckets: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = _drop_none({k: r[k] for k in ("statement_id", "account_id", "period_start", "period_end", "due_date",
                                        "opening_balance_minor", "closing_balance_minor", "minimum_due_minor",
                                        "interest_charged_minor", "fees_charged_minor", "evidence_ref")})
    if buckets:
        out["bucket_balances"] = buckets
    return out


def _terms_out(r: Dict[str, Any], buckets: List[Dict[str, Any]]) -> Dict[str, Any]:
    rule = _drop_none({"rule_type": r["min_rule_type"], "amount_minor": r["min_amount_minor"], "pct": r["min_pct"],
                       "floor_minor": r["min_floor_minor"]})
    out = {"terms_id": r["terms_id"], "account_id": r["account_id"], "effective_from": r["effective_from"]}
    if r["effective_to"] is not None:
        out["effective_to"] = r["effective_to"]
    out.update({"terms_source": r["terms_source"], "credit_limit_minor": r["credit_limit_minor"],
                "min_payment_rule": rule, "apr_buckets": buckets})
    return out
