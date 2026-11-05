"""Declarative, versioned import profiles (contract ``import_profile`` 1.0.x).

A profile is data only. Adding a bank format means adding a JSON file that
validates against ``contracts/schemas/import_profile.schema.json``; the parser in
``staging.py`` is never edited for a new format (see docs/import/README.md).

Every profile is validated by the frozen contract validator
(``perfin_contracts.semantic.validate_document``) plus the few extra checks the
parser relies on. The validator is injected or imported from ``perfin_contracts``;
if it is unavailable the importer fails closed instead of trusting the profile.
"""
import copy
import json
import os

from .errors import ProfileError, UnknownFormat
from .reader import has_undecodable, read_records

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin_profiles")
COLUMN_FIELDS = ("posted_date", "transaction_date", "description", "amount", "debit", "credit",
                 "source_txn_id", "running_balance")
DEFAULT_DEDUPE_KEY = ["source_txn_id", "posted_date", "amount_minor", "description", "row_occurrence"]
UNVERIFIED_NOTE = "Not verified against any real institution's export."


def default_validator():
    try:
        from perfin_contracts.semantic import validate_document
    except ImportError:
        raise ProfileError("contract validator perfin_contracts is not importable; refusing to trust "
                           "an unvalidated profile (put contracts/python on sys.path)") from None
    return validate_document


def _extra_checks(doc):
    """Rules the parser relies on that the 1.0.0 schema does not state."""
    errs = []
    cols = doc["columns"]
    mapped = {k: v for k, v in cols.items() if v not in (None, "")}
    if doc["file"]["header_rows"] == 0:
        for k, v in mapped.items():
            if not (v.isdigit() and v.isascii() and int(v) >= 1):
                errs.append(("E_PATTERN", "$.columns.%s" % k,
                             "with header_rows 0 columns must be 1-based column numbers"))
    names = list(mapped.values())
    for k, v in mapped.items():
        if names.count(v) > 1:
            errs.append(("E_DUPLICATE_ID", "$.columns.%s" % k, "two fields map to the same column"))
    expected = doc["file"].get("expected_field_count")
    if expected is not None and doc["file"]["header_rows"] == 0:
        for k, v in mapped.items():
            if v.isdigit() and int(v) > expected:
                errs.append(("E_RANGE", "$.columns.%s" % k, "column number exceeds expected_field_count"))
    for key in doc.get("dedupe_key") or []:
        if key == "running_balance" and not cols.get("running_balance"):
            errs.append(("E_REQUIRED", "$.dedupe_key", "running_balance dedupe key needs that column"))
        if key == "transaction_date" and not cols.get("transaction_date"):
            errs.append(("E_REQUIRED", "$.dedupe_key", "transaction_date dedupe key needs that column"))
    return errs


def validate_profile(doc, validator=None):
    """Return a list of (code, path, message); empty means the profile is usable."""
    validator = validator or default_validator()
    if not isinstance(doc, dict) or doc.get("document_type") != "import_profile":
        return [("E_DOCUMENT_TYPE", "$.document_type", "not an import_profile document")]
    errs = [tuple(e) for e in validator(doc)]
    if errs:
        return errs
    return _extra_checks(doc)


def load_profile(source, validator=None):
    """Load a profile from a dict or a JSON file path; raise ProfileError if invalid."""
    if isinstance(source, dict):
        doc = copy.deepcopy(source)
    else:
        with open(source, encoding="utf-8") as fh:
            doc = json.load(fh)
    errs = validate_profile(doc, validator)
    if errs:
        raise ProfileError("import profile failed contract validation", errs)
    return doc


def load_profiles_dir(directory, validator=None):
    """Load every ``*.json`` profile in a directory, keyed by (profile_id, profile_version)."""
    out = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        doc = load_profile(os.path.join(directory, name), validator)
        key = (doc["profile_id"], doc["profile_version"])
        if key in out:
            raise ProfileError("duplicate profile id/version %s %s" % key)
        out[key] = doc
    return out


def builtin_profiles(validator=None):
    return load_profiles_dir(BUILTIN_DIR, validator)


def profile_from_mapping(mapping, *, profile_id, profile_version, account_class, date_format,
                         sign_rule, decimal_separator, thousands_separator="", encoding="utf-8",
                         delimiter=",", quote_char='"', header_rows=1, skip_footer_rows=0,
                         expected_field_count=None, currency=None, parentheses_negative=False,
                         dedupe_key=None, description=None, validator=None):
    """Build a profile from a user-supplied ``{header text: field}`` mapping.

    ``field`` is one of COLUMN_FIELDS. Nothing is inferred: date format, sign rule
    and separators must be stated explicitly. The result goes through exactly the
    same validation as a shipped profile.
    """
    if not isinstance(mapping, dict) or not mapping:
        raise ProfileError("mapping must be a non-empty {header: field} object")
    columns = {}
    for header, field in mapping.items():
        if field not in COLUMN_FIELDS:
            raise ProfileError("unknown target field in mapping",
                               [("E_ENUM", "$.mapping", "target must be one of %s" % ", ".join(COLUMN_FIELDS))])
        if field in columns:
            raise ProfileError("field mapped twice", [("E_DUPLICATE_ID", "$.mapping", "field %s mapped twice" % field)])
        if not isinstance(header, str):
            raise ProfileError("header must be text", [("E_TYPE", "$.mapping", "header names must be strings")])
        columns[field] = header
    if sign_rule == "debit_credit_columns":
        columns.setdefault("amount", None)
    doc = {
        "contract": "perfin",
        "contract_version": "1.0.0",
        "document_type": "import_profile",
        "profile_id": profile_id,
        "profile_version": profile_version,
        "description": description or ("User-supplied column mapping. " + UNVERIFIED_NOTE),
        "account_class": account_class,
        "file": {
            "encoding": encoding,
            "delimiter": delimiter,
            "quote_char": quote_char,
            "header_rows": header_rows,
            "skip_footer_rows": skip_footer_rows,
            "expected_field_count": expected_field_count,
        },
        "columns": columns,
        "date_format": date_format,
        "amount": {
            "sign_rule": sign_rule,
            "decimal_separator": decimal_separator,
            "thousands_separator": thousands_separator,
            "parentheses_negative": parentheses_negative,
        },
        "dedupe_key": list(dedupe_key or DEFAULT_DEDUPE_KEY),
    }
    if currency is not None:
        doc["amount"]["currency"] = currency
    return load_profile(doc, validator)


# ------------------------------------------------------------ header matching

def resolve_columns(profile, header):
    """Map each profile field to a 0-based column index, or raise UnknownFormat.

    ``header`` is the list of header cells (None when header_rows is 0). Matching
    is exact: no case folding, trimming or fuzzy matching, so an unfamiliar layout
    goes to human review instead of being guessed.
    """
    cols = {k: v for k, v in profile["columns"].items() if v not in (None, "")}
    if header is None:
        return {k: int(v) - 1 for k, v in cols.items()}
    if any(has_undecodable(h) for h in header):
        raise UnknownFormat("header contains bytes that are not valid in the declared encoding",
                            code="E_PARSE_ENCODING")
    missing, ambiguous, index = [], [], {}
    for field, name in cols.items():
        hits = [i for i, h in enumerate(header) if h == name]
        if not hits:
            missing.append(field)
        elif len(hits) > 1:
            ambiguous.append(field)
        else:
            index[field] = hits[0]
    if missing or ambiguous:
        parts = []
        if missing:
            parts.append("header has no column for: %s" % ", ".join(missing))
        if ambiguous:
            parts.append("header repeats the column for: %s" % ", ".join(ambiguous))
        raise UnknownFormat("; ".join(parts) + ". Choose another profile or supply a column mapping.",
                            found_headers=header, missing=missing + ambiguous)
    expected = profile["file"].get("expected_field_count")
    if expected is not None and len(header) != expected:
        raise UnknownFormat("header has %d columns; profile expects %d" % (len(header), expected),
                            found_headers=header)
    return index


def header_of(read, profile):
    hr = profile["file"]["header_rows"]
    if hr == 0:
        return None
    if len(read.records) < hr:
        raise UnknownFormat("file has fewer records than the declared header rows")
    return read.records[hr - 1].fields


def match_profiles(data, profiles):
    """Return the profiles whose declared header matches ``data`` exactly.

    Use it to pick a profile: zero matches means an unknown format (ask the user
    for a mapping); more than one means the user must choose. Never guesses.
    Profiles with header_rows 0 cannot be identified from the file and are skipped.
    """
    hits = []
    for profile in (profiles.values() if isinstance(profiles, dict) else profiles):
        if profile["file"]["header_rows"] == 0:
            continue
        read = read_records(data, profile["file"])
        try:
            resolve_columns(profile, header_of(read, profile))
        except UnknownFormat:
            continue
        hits.append(profile)
    return hits
