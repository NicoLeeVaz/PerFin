"""Turn one CSV file into a contract ``staging_batch`` document. No ledger writes.

Pipeline: validate profile -> check account -> hash file -> strict decode + csv
-> exact header match -> per-row strict parsing -> fingerprints -> duplicate,
transfer and category proposals -> review states -> contract validation of the
output. The only side effect is calling the repository's read methods.

No logging is performed. Nothing in this module writes files.
"""
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath

from . import IMPORTER_VERSION
from .errors import ImportRefused, ProfileError, UnknownFormat, ValueParseError
from .profiles import DEFAULT_DEDUPE_KEY, default_validator, header_of, load_profile, resolve_columns
from .reader import read_records
from .repository import REPLAY_BATCH_STATES
from .values import parse_amount, parse_date

CONTRACT_VERSION = "1.0.0"
FINGERPRINT_SCHEME = "perfin-import-fingerprint/1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_FILE_NAME = re.compile(r"[^/\\:]{1,200}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
MAX_RAW_FIELD = 4000
MAX_DESCRIPTION = 1000
MAX_SOURCE_ID = 128
DIRECTIONS = ("outflow", "inflow", "any")


class StageResult:
    """``document`` is the staging_batch; ``summary`` holds counts only (log-safe)."""

    def __init__(self, document, summary):
        self.document = document
        self.summary = summary

    @property
    def rows(self):
        return self.document["rows"]


# ----------------------------------------------------------------- helpers

def base_file_name(name):
    """Base name only, for Windows and POSIX paths alike; never a local path."""
    if not isinstance(name, str):
        raise ImportRefused("E_TYPE", "source file name must be text")
    base = PurePosixPath(PureWindowsPath(name).name).name
    if name.endswith(("/", "\\")) or not _FILE_NAME.fullmatch(base or ""):
        raise ImportRefused("E_PATTERN", "source file name must be a base name of 1-200 characters "
                            "without / \\ or :")
    return base


def _timestamp(staged_at):
    if staged_at is None:
        staged_at = datetime.now(timezone.utc)
    if isinstance(staged_at, datetime):
        if staged_at.tzinfo is None:
            raise ImportRefused("E_TYPE", "staged_at must be timezone-aware UTC")
        return staged_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(staged_at, str) and _TIMESTAMP.fullmatch(staged_at):
        try:
            datetime.strptime(staged_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise ImportRefused("E_DATE_INVALID", "staged_at is not a real UTC time") from None
        return staged_at
    raise ImportRefused("E_PATTERN", "staged_at must be YYYY-MM-DDTHH:MM:SSZ")


def _sha(*parts):
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()


def _norm_text(text):
    return " ".join((text or "").casefold().split())


def _days_apart(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def validate_category_rules(rules):
    """Rules: ordered list of {"category_id", "contains": [text...], "direction"}."""
    out = []
    for i, rule in enumerate(rules or []):
        if not isinstance(rule, dict) or set(rule) - {"category_id", "contains", "direction"}:
            raise ProfileError("category rule %d has unknown keys" % i)
        cid, contains = rule.get("category_id"), rule.get("contains")
        direction = rule.get("direction", "any")
        if not isinstance(cid, str) or not _ID.fullmatch(cid):
            raise ProfileError("category rule %d needs a valid category_id" % i)
        if (not isinstance(contains, list) or not contains
                or not all(isinstance(c, str) and c.strip() for c in contains)):
            raise ProfileError("category rule %d needs a non-empty list of 'contains' texts" % i)
        if direction not in DIRECTIONS:
            raise ProfileError("category rule %d direction must be one of %s" % (i, DIRECTIONS))
        out.append((cid, [_norm_text(c) for c in contains], direction))
    return out


def _match_category(rules, description, amount):
    text = _norm_text(description)
    for cid, needles, direction in rules:
        if direction == "outflow" and amount >= 0:
            continue
        if direction == "inflow" and amount <= 0:
            continue
        if any(n in text for n in needles):
            return cid
    return None


# ---------------------------------------------------------- row parsing

def _parse_row(fields, index, profile, expected):
    """Return (parsed or None, errors). Never coerces; collects every error."""
    errors = []
    n = len(fields)
    if expected is not None and n != expected:
        return None, [("E_PARSE_FIELD_COUNT", "raw_fields", "row has %d fields; expected %d" % (n, expected))]
    if index and max(index.values()) >= n:
        return None, [("E_PARSE_FIELD_COUNT", "raw_fields",
                       "row has %d fields; mapped columns need %d" % (n, max(index.values()) + 1))]

    def col(field):
        i = index.get(field)
        return (None, None) if i is None else (fields[i], "raw_fields[%d]" % i)

    fmt = profile["date_format"]
    amt = profile["amount"]
    dec, ts = amt["decimal_separator"], amt.get("thousands_separator", "")
    paren = bool(amt.get("parentheses_negative", False))
    rule = amt["sign_rule"]

    posted = txn_date = amount = balance = None
    raw, path = col("posted_date")
    try:
        posted = parse_date(raw, fmt)
    except ValueParseError as e:
        errors.append((e.code, path, e.reason))
    raw, path = col("transaction_date")
    if raw is not None and raw.strip(" \t") != "":
        try:
            txn_date = parse_date(raw, fmt)
        except ValueParseError as e:
            errors.append((e.code, path, e.reason))

    if rule == "debit_credit_columns":
        values = {}
        for side in ("debit", "credit"):
            raw, path = col(side)
            try:
                values[side] = parse_amount(raw, dec, ts, False, allow_sign=False)
            except ValueParseError as e:
                errors.append((e.code, path, e.reason))
                values[side] = "error"
        if "error" not in values.values():
            debit, credit = values["debit"], values["credit"]
            if debit is None and credit is None:
                errors.append(("E_PARSE_AMOUNT", col("debit")[1], "both debit and credit are empty; never coerced to 0"))
            elif debit is not None and credit is not None and debit != 0 and credit != 0:
                errors.append(("E_PARSE_AMOUNT", col("debit")[1], "both debit and credit hold a non-zero amount; ambiguous"))
            else:
                # Debit = money out / more owed (negative); credit = money in / less owed.
                amount = (credit or 0) - (debit or 0)
    else:
        raw, path = col("amount")
        try:
            value = parse_amount(raw, dec, ts, paren)
            if value is None:
                errors.append(("E_PARSE_AMOUNT", path, "amount is empty; never coerced to 0"))
            else:
                amount = -value if rule == "invert" else value
        except ValueParseError as e:
            errors.append((e.code, path, e.reason))

    raw, path = col("running_balance")
    if raw is not None:
        try:
            value = parse_amount(raw, dec, ts, paren)
            if value is not None:
                balance = -value if rule == "invert" else value
        except ValueParseError as e:
            errors.append((e.code, path, e.reason))

    description, dpath = col("description")
    if len(description) > MAX_DESCRIPTION:
        errors.append(("E_LENGTH", dpath, "description longer than %d characters" % MAX_DESCRIPTION))
    source_id, spath = col("source_txn_id")
    if source_id is not None and source_id.strip(" \t") == "":
        source_id = None
    if source_id is not None and len(source_id) > MAX_SOURCE_ID:
        errors.append(("E_LENGTH", spath, "source transaction id longer than %d characters" % MAX_SOURCE_ID))
    if posted and txn_date and txn_date > posted:
        errors.append(("E_DATE_ORDER", col("transaction_date")[1], "transaction date is after posted date"))
    if errors:
        return None, errors
    parsed = {"posted_date": posted, "amount_minor": amount, "description": description}
    if "transaction_date" in index:
        parsed["transaction_date"] = txn_date
    if "source_txn_id" in index:
        parsed["source_txn_id"] = source_id
    if "running_balance" in index:
        parsed["running_balance_minor"] = balance
    return parsed, []


def _err(code, path, message):
    e = {"code": code, "message": message}
    if path:
        e["path"] = path
    return e


# ------------------------------------------------------------- staging

def stage_file(data, source_file_name, profile, account_id, repository, *, staged_at=None,
               batch_id=None, category_rules=None, validator=None, duplicate_window_days=3,
               transfer_window_days=5):
    """Stage ``data`` (the file's bytes) for ``account_id`` using ``profile``.

    Returns a StageResult. Raises ProfileError / ImportRefused / UnknownFormat when
    the whole file cannot be staged. Row-level problems never raise.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise ImportRefused("E_TYPE", "file content must be bytes; the importer decodes it itself")
    data = bytes(data)
    validator = validator or default_validator()
    profile = load_profile(profile, validator)
    rules = validate_category_rules(category_rules)
    file_name = base_file_name(source_file_name)
    staged = _timestamp(staged_at)

    account = repository.get_account(account_id)
    if account is None:
        raise ImportRefused("E_ACCOUNT_UNKNOWN", "account is not known to the repository")
    if account.get("account_class") != profile["account_class"]:
        raise ImportRefused("E_ACCOUNT_KIND", "profile is for %s accounts; target account is %s"
                            % (profile["account_class"], account.get("account_class")))
    currency = profile["amount"].get("currency")
    if currency and account.get("currency") and currency != account["currency"]:
        raise ImportRefused("E_CURRENCY_MISMATCH", "profile currency differs from the account currency")

    file_sha = hashlib.sha256(data).hexdigest()
    read = read_records(data, profile["file"])
    try:
        header = header_of(read, profile)
        index = resolve_columns(profile, header)
    except UnknownFormat as e:
        if read.bom_mismatch:
            e.message += " The file starts with a UTF-8 byte-order mark; a utf-8-sig profile may fit."
            e.args = (e.message,)
        raise
    expected = profile["file"].get("expected_field_count")
    if expected is None and header is not None:
        expected = len(header)

    hr = profile["file"]["header_rows"]
    body = read.records[hr:]
    footer = profile["file"].get("skip_footer_rows", 0) or 0
    footer_skipped = 0
    if footer and read.structural_error_line is None:
        footer_skipped = min(footer, len(body))
        body = body[:len(body) - footer_skipped]

    batch_id = batch_id or "imp-" + _sha("batch", account_id, file_sha, staged)[:24]
    if not _ID.fullmatch(batch_id):
        raise ImportRefused("E_PATTERN", "batch_id is not a valid contract id")

    replay = sorted((b for b in repository.prior_batches(account_id)
                     if b.get("source_file_sha256") == file_sha and b.get("batch_status") in REPLAY_BATCH_STATES),
                    key=lambda b: b["batch_id"])
    dedupe_key = list(profile.get("dedupe_key") or DEFAULT_DEDUPE_KEY)
    key_fields = [k for k in dedupe_key if k != "row_occurrence"]

    rows, seen_keys, natural_first, source_first = [], Counter(), {}, {}
    for n, record in enumerate(body, start=1):
        row = {"row_number": n}
        if record.bad_fields:
            row["raw_fields"] = []
            row["parsed"] = None
            row["errors"] = [_err("E_PARSE_ENCODING", "raw_fields[%d]" % i,
                                  "bytes not valid in %s; field not stored, never replaced"
                                  % profile["file"]["encoding"]) for i in record.bad_fields]
        elif any(len(f) > MAX_RAW_FIELD for f in record.fields):
            row["raw_fields"] = []
            row["parsed"] = None
            row["errors"] = [_err("E_LENGTH", "raw_fields[%d]" % i, "field longer than %d characters; not stored"
                                  % MAX_RAW_FIELD) for i, f in enumerate(record.fields) if len(f) > MAX_RAW_FIELD]
        else:
            row["raw_fields"] = list(record.fields)
            parsed, errs = _parse_row(record.fields, index, profile, expected)
            row["parsed"] = parsed
            row["errors"] = [_err(*e) for e in errs]

        parsed = row["parsed"]
        if parsed is not None:
            values = {"source_txn_id": parsed.get("source_txn_id"), "posted_date": parsed["posted_date"],
                      "transaction_date": parsed.get("transaction_date"), "amount_minor": parsed["amount_minor"],
                      "description": parsed["description"], "running_balance": parsed.get("running_balance_minor")}
            natural = [[k, values[k]] for k in key_fields]
        else:
            natural = [["unparsed_raw_fields", record.fields]]
        natural_key = _sha(natural)
        seen_keys[natural_key] += 1
        occurrence = seen_keys[natural_key]
        row["fingerprint"] = _sha(FINGERPRINT_SCHEME, account_id, natural, ["row_occurrence", occurrence])
        row["duplicate"] = {"status": "none"}
        row["_natural"] = natural_key
        rows.append(row)

        if replay:
            prior = replay[0]
            row["duplicate"] = {"status": "exact_reimport", "matched_transaction_id": None,
                                "matched_row_number": None,
                                "evidence": "same account and source file SHA-256 as batch %s (%s)"
                                            % (prior["batch_id"], prior["batch_status"])}
            continue
        if parsed is None:
            continue
        row["duplicate"] = _classify_duplicate(row, parsed, account_id, repository, duplicate_window_days,
                                               natural_first, source_first)

    if read.structural_error_line is not None:
        n = len(rows) + 1
        rows.append({"row_number": n, "raw_fields": [], "parsed": None,
                     "errors": [_err("E_PARSE_FIELD_COUNT", "$",
                                     "CSV quoting is malformed in the record starting at physical line %d; "
                                     "the rest of the file was not read" % read.structural_error_line)],
                     "fingerprint": _sha(FINGERPRINT_SCHEME, account_id, "structural_error", file_sha,
                                         read.structural_error_line),
                     "duplicate": {"status": "exact_reimport" if replay else "none"}, "_natural": None})
        if replay:
            rows[-1]["duplicate"]["evidence"] = "same account and source file SHA-256 as batch %s" % replay[0]["batch_id"]

    ambiguous_transfers = []
    for row in rows:
        row.pop("_natural")
        parsed, status = row["parsed"], row["duplicate"]["status"]
        transfer_ambiguous = False
        if parsed is not None and status != "exact_reimport" and parsed["amount_minor"] != 0:
            cands = [c for c in repository.find_transfer_candidates(
                account_id, -parsed["amount_minor"], parsed["posted_date"], transfer_window_days)
                if c.get("account_id") != account_id and c.get("amount_minor") == -parsed["amount_minor"]]
            if len(cands) == 1:
                row["transfer_candidate_transaction_id"] = cands[0]["transaction_id"]
            elif len(cands) > 1:
                transfer_ambiguous = True
                ambiguous_transfers.append(row["row_number"])
        if (parsed is not None and rules and status != "exact_reimport"
                and not row.get("transfer_candidate_transaction_id") and not transfer_ambiguous):
            cid = _match_category(rules, parsed["description"], parsed["amount_minor"])
            if cid:
                row["proposed_splits"] = [{"split_id": "p1", "split_kind": "category",
                                           "amount_minor": parsed["amount_minor"], "category_id": cid}]
        if status == "exact_reimport":
            row["review_state"] = "rejected"  # can never be approved; commit would change nothing
        elif row["errors"] or status == "possible" or transfer_ambiguous:
            row["review_state"] = "needs_review"
        else:
            row["review_state"] = "pending"

    document = {
        "contract": "perfin",
        "contract_version": CONTRACT_VERSION,
        "document_type": "staging_batch",
        "batch": {
            "batch_id": batch_id,
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "account_id": account_id,
            "source_file_sha256": file_sha,
            "source_file_name": file_name,
            "staged_at": staged,
            "importer_version": IMPORTER_VERSION,
            "batch_status": "staged",
        },
        "rows": rows,
    }
    errs = validator(document)
    if errs:
        raise RuntimeError("internal defect: generated staging_batch failed contract validation: %s"
                           % "; ".join("%s %s" % (c, p) for c, p, _ in errs))
    summary = summarize_batch(document)
    summary.update({
        "blank_records_skipped": read.blank_records,
        "footer_records_skipped": footer_skipped,
        "file_complete": read.structural_error_line is None,
        "file_replay_of_batch": replay[0]["batch_id"] if replay else None,
        "transfer_ambiguous_rows": ambiguous_transfers,
    })
    return StageResult(document, summary)


def _classify_duplicate(row, parsed, account_id, repo, window, natural_first, source_first):
    """Return the row's duplicate object. Source ids are scoped to ``account_id``."""
    sid = parsed.get("source_txn_id")
    fp = row["fingerprint"]
    if sid is not None:
        for t in sorted(repo.find_by_source_txn_id(account_id, sid), key=lambda t: t["transaction_id"]):
            if t.get("account_id") != account_id:
                continue  # defensive: never match another account's source id
            if t.get("fingerprint") == fp:
                return {"status": "exact_reimport", "matched_transaction_id": t["transaction_id"],
                        "evidence": "same account, source transaction id and fingerprint as a ledger transaction"}
            return {"status": "possible", "matched_transaction_id": t["transaction_id"],
                    "evidence": "same account and source transaction id, but different details"}
        if sid in source_first:
            return {"status": "possible", "matched_row_number": source_first[sid],
                    "evidence": "same source transaction id earlier in this file"}
        source_first[sid] = row["row_number"]

    # Within the file: identical natural key (row_occurrence keeps fingerprints distinct).
    nk = row["_natural"]
    if nk in natural_first:
        first_row, first_sid = natural_first[nk]
        if not (sid and first_sid and sid != first_sid):
            return {"status": "possible", "matched_row_number": first_row,
                    "evidence": "same date, amount and description earlier in this file; "
                                "legitimate repeated purchases are possible"}
    else:
        natural_first[nk] = (row["row_number"], sid)

    best = None
    for t in repo.find_candidates(account_id, parsed["posted_date"], parsed["amount_minor"], window):
        if t.get("account_id") != account_id or t.get("amount_minor") != parsed["amount_minor"]:
            continue
        if sid and t.get("source_txn_id") and t["source_txn_id"] != sid:
            continue  # different issuer ids on the same account: reliable evidence of distinct rows
        apart = _days_apart(parsed["posted_date"], t["posted_date"])
        if apart > window:
            continue
        same_fp = t.get("fingerprint") == fp
        same_desc = _norm_text(t.get("description")) == _norm_text(parsed["description"])
        if not (same_fp or same_desc or apart == 0):
            continue
        rank = (0 if same_fp else 1, 0 if same_desc else 1, apart, t["transaction_id"])
        if best is None or rank < best[0]:
            best = (rank, t)
    if best:
        rank, t = best
        why = ("same fingerprint as" if rank[0] == 0 else
               "same amount and description within %d day(s) of" % rank[2] if rank[1] == 0 else
               "same amount and posted date as")
        return {"status": "possible", "matched_transaction_id": t["transaction_id"],
                "evidence": why + " an existing transaction on this account"}
    return {"status": "none"}


def summarize_batch(document):
    """Counts per review state, duplicate status and error code. No values."""
    rows = document["rows"]
    review = Counter({k: 0 for k in ("pending", "needs_review", "approved", "rejected")})
    dup = Counter({k: 0 for k in ("none", "exact_reimport", "possible", "confirmed_duplicate",
                                  "confirmed_distinct")})
    codes = Counter()
    for r in rows:
        review[r["review_state"]] += 1
        dup[r["duplicate"]["status"]] += 1
        for e in r["errors"]:
            codes[e["code"]] += 1
    return {
        "batch_id": document["batch"]["batch_id"],
        "batch_status": document["batch"]["batch_status"],
        "rows": len(rows),
        "parsed": sum(1 for r in rows if r.get("parsed") is not None),
        "rows_with_errors": sum(1 for r in rows if r["errors"]),
        "review_state": dict(review),
        "duplicate": dict(dup),
        "error_codes": dict(sorted(codes.items())),
        "transfer_candidates": sum(1 for r in rows if r.get("transfer_candidate_transaction_id")),
        "categorized": sum(1 for r in rows if r.get("proposed_splits")),
    }
