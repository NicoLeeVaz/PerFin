"""Reference privacy checks for PerFin (task 1c). Standard library only.

These functions express rules from docs/privacy/*.md so that later tasks can
reuse or port them. Passing their unit tests on Linux is not evidence that any
Windows, Office or Access behaviour has been verified.

Command line:
    python3 perfin_privacy_checks.py validate-defaults [defaults.json]
    python3 perfin_privacy_checks.py validate-examples
    python3 perfin_privacy_checks.py check-data-dir PATH
    python3 perfin_privacy_checks.py scan-repo ROOT
"""

import csv
import fnmatch
import io
import json
import os
import re
from decimal import Decimal
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath

HERE = Path(__file__).resolve().parent
DEFAULTS_PATH = HERE / "defaults.json"
SCHEMA_PATH = HERE / "nopii-export-envelope.schema.json"
EXAMPLES_DIR = HERE / "examples"


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_defaults(path=DEFAULTS_PATH):
    return load_json(path)


# ---------------------------------------------------------------- formulas

def needs_formula_escape(value, defaults=None):
    """True if a text value could be evaluated as a spreadsheet formula."""
    if not isinstance(value, str) or value == "":
        return False
    cfg = (defaults or load_defaults())["formula_injection"]
    triggers = tuple(cfg["triggers"]) + tuple(cfg.get("conservative_extra_triggers", []))
    if value.startswith(triggers):
        return True
    if cfg.get("check_after_leading_spaces"):
        stripped = value.lstrip(" ")
        return stripped != value and stripped.startswith(triggers)
    return False


def escape_spreadsheet_text(value, defaults=None):
    """Prefix a text value with an apostrophe when it could become a formula.

    Apply only to text fields at the Excel/CSV output boundary; never to
    numeric columns and never when storing to Access.
    """
    cfg = (defaults or load_defaults())["formula_injection"]
    if needs_formula_escape(value, defaults):
        return cfg["escape_prefix"] + value
    return value


def records_to_outbox_csv(records, defaults=None):
    """Serialise export records to CSV with every text field escaped."""
    defaults = defaults or load_defaults()
    fields = defaults["nopii"]["allowed_record_fields"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="raise", lineterminator="\r\n")
    writer.writeheader()
    for record in records:
        row = {}
        for name in fields:
            value = record.get(name, "")
            if isinstance(value, bool):
                raise ValueError("boolean not allowed in export record")
            row[name] = value if isinstance(value, int) else escape_spreadsheet_text(str(value), defaults)
        writer.writerow(row)
    return out.getvalue()


# ------------------------------------------------------------- data dir

def _pure_path(path):
    text = str(path)
    if "\\" in text or re.match(r"^[A-Za-z]:", text):
        return PureWindowsPath(text)
    return PurePosixPath(text)


def _is_under(child, parent):
    child_p, parent_p = _pure_path(child), _pure_path(parent)
    if type(child_p) is not type(parent_p):
        return False
    c = [p.casefold() for p in child_p.parts]
    p = [x.casefold() for x in parent_p.parts]
    return len(p) > 0 and c[: len(p)] == p


def detect_sync_folder(path, env=None, defaults=None):
    """Return reasons why `path` looks like a sync-client folder (heuristic)."""
    cfg = (defaults or load_defaults())["data_dir"]
    env = os.environ if env is None else env
    markers = {m.casefold() for m in cfg["sync_markers"]}
    prefixes = [p.casefold() for p in cfg["sync_marker_prefixes"]]
    reasons = []
    for part in _pure_path(path).parts:
        folded = part.casefold()
        if folded in markers or any(folded.startswith(p) for p in prefixes):
            reasons.append("sync marker segment: %s" % part)
    for var in cfg["sync_env_vars"]:
        value = env.get(var)
        if value and _is_under(path, value):
            reasons.append("under %%%s%%" % var)
    return reasons


def find_git_checkout(path):
    """Return the nearest ancestor (or self) containing `.git`, else None.

    Checks both the literal path and its symlink-resolved form (resolve() with
    strict=False also resolves an existing prefix when the leaf does not exist yet),
    so an alias into a checkout cannot bypass the guard.
    """
    literal = Path(path).expanduser().absolute()
    for start in (literal, literal.resolve(strict=False)):
        for candidate in [start, *start.parents]:
            if (candidate / ".git").exists():
                return candidate
    return None


def evaluate_data_dir(path, env=None, defaults=None, check_filesystem=True):
    """Decide whether `path` may hold real PerFin data.

    Returns {"decision": "ok" | "warn" | "refuse", "reasons": [...]}.
    "warn" means blocked until the user explicitly acknowledges.
    """
    defaults = defaults or load_defaults()
    cfg = defaults["data_dir"]
    reasons, decision = [], "ok"
    if check_filesystem and cfg["refuse_inside_git_checkout"]:
        repo = find_git_checkout(path)
        if repo is not None:
            return {"decision": "refuse", "reasons": ["inside git checkout: %s" % repo]}
    sync = detect_sync_folder(path, env, defaults)
    if sync:
        decision = "warn"
        reasons.extend(sync)
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        decision = "warn"
        reasons.append("network (UNC) path")
    redirected = {f.casefold() for f in cfg["possibly_redirected_user_folders"]}
    for part in _pure_path(path).parts:
        if part.casefold() in redirected:
            decision = "warn"
            reasons.append("possibly redirected user folder: %s" % part)
            break
    return {"decision": decision, "reasons": reasons}


# ------------------------------------------------------------- redaction

def luhn_valid(digits):
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# The profile-directory component may contain spaces ("Alex Example"); it ends at the next
# path separator, line break or quote. Without a following separator the rest of the line is
# redacted, which deliberately over-redacts rather than leaking part of a name.
_USER_PATH = re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\/\r\n\"'<>|]+|/home/[^/\r\n\"'<>|]+|/Users/[^/\r\n\"'<>|]+)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
# Any span of 13+ digits, optionally separated by single spaces or hyphens.
_GROUPED = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,}(?!\d)")


def card_number_candidates(span):
    """Digit strings of 13-19 digits inside a span that could be a card number.

    A greedy span can join a PAN to a neighbouring number ("4242 4242 4242 4242 1"),
    so candidates are runs of consecutive separator-delimited groups totalling 13-19
    digits. Arbitrary windows inside an unbroken digit run are not tried: they would flag
    substrings of harmless long numbers, and the export gate already rejects any run of
    6+ digits.
    """
    groups = re.split(r"[ -]", span)
    out = set()
    for i in range(len(groups)):
        for j in range(i + 1, len(groups) + 1):
            digits = "".join(groups[i:j])
            if 13 <= len(digits) <= 19:
                out.add(digits)
            if len(digits) > 19:
                break
    return out


def find_card_numbers(text):
    """Luhn-valid candidate card numbers found anywhere in `text`."""
    found = set()
    for match in _GROUPED.finditer(text):
        found |= {c for c in card_number_candidates(match.group(0)) if luhn_valid(c)}
    return found
_DIGITS = re.compile(r"\d{6,}")


def redact_log_text(text):
    """Regex backstop applied to every diagnostic log message."""
    text = _USER_PATH.sub("%USERPROFILE%", text)
    text = _EMAIL.sub("[REDACTED-EMAIL]", text)
    text = _IBAN.sub("[REDACTED-IBAN]", text)
    text = _SSN.sub("[REDACTED-SSN]", text)

    def grouped(match):
        cands = card_number_candidates(match.group(0))
        return "[REDACTED-PAN]" if any(luhn_valid(c) for c in cands) else "[REDACTED-DIGITS]"

    text = _GROUPED.sub(grouped, text)
    return _DIGITS.sub("[REDACTED-DIGITS]", text)


# --------------------------------------------------------- schema subset

def validate_schema(instance, schema, root=None, where="$"):
    """Validate against the JSON Schema subset used by the envelope schema."""
    root = root or schema
    errors = []
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return validate_schema(instance, root["$defs"][name], root, where)
    if "oneOf" in schema:
        matches = [s for s in schema["oneOf"] if not validate_schema(instance, s, root, where)]
        if len(matches) != 1:
            errors.append("%s: matches %d of oneOf" % (where, len(matches)))
        return errors
    for sub in schema.get("allOf", []):
        errors += validate_schema(instance, sub, root, where)
    if "const" in schema and instance != schema["const"]:
        errors.append("%s: expected %r" % (where, schema["const"]))
    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: %r not in enum" % (where, instance))
    kind = schema.get("type")
    checks = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
    }
    if kind and not checks[kind](instance):
        return errors + ["%s: expected %s" % (where, kind)]
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append("%s: does not match %s" % (where, schema["pattern"]))
        if len(instance) < schema.get("minLength", 0):
            errors.append("%s: too short" % where)
    if isinstance(instance, int) and "minimum" in schema and instance < schema["minimum"]:
        errors.append("%s: below minimum" % where)
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append("%s: missing %s" % (where, key))
        props = schema.get("properties", {})
        for key, value in instance.items():
            if key in props:
                errors += validate_schema(value, props[key], root, "%s.%s" % (where, key))
            elif schema.get("additionalProperties") is False:
                errors.append("%s: unexpected property %s" % (where, key))
    if isinstance(instance, list):
        if "items" in schema:
            for i, item in enumerate(instance):
                errors += validate_schema(item, schema["items"], root, "%s[%d]" % (where, i))
        if "contains" in schema and not any(
            not validate_schema(item, schema["contains"], root, where) for item in instance
        ):
            errors.append("%s: missing required item %r" % (where, schema["contains"]))
    return errors


def validate_envelope(instance, schema=None):
    return validate_schema(instance, schema or load_json(SCHEMA_PATH))


# ------------------------------------------------------------- fidelity

# Monetary tokens: amounts with exactly two decimals (with or without a currency symbol),
# plus whole amounts that carry a currency symbol ($100, $1,250, EUR-symbol 40).
# Bare integers without a symbol are not treated as money (they may be scrubbable ids);
# see docs/privacy/nopii-export-contract.md.
_MONEY = re.compile(
    r"(?<![\w.])[-+]?[$\u20ac\u00a3]?\s?\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)"
    r"|(?<![\w.,])[-+]?[$\u20ac\u00a3]?\s?\d+\.\d{2}(?!\d)"
    r"|[-+]?[$\u20ac\u00a3]\s?\d{1,3}(?:,\d{3})+(?![\d.,])"
    r"|[-+]?[$\u20ac\u00a3]\s?\d+(?![\d.,])"
)
_ISO_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def _money_tokens(text):
    """Multiset of (currency symbol, Decimal value) so $100 and $100.00 compare equal."""
    out = Counter()
    for token in _MONEY.findall(text):
        symbol = next((c for c in token if c in "$\u20ac\u00a3"), "")
        digits = re.sub(r"[^\d.+-]", "", token)
        out[(symbol, Decimal(digits).quantize(Decimal("0.01")))] += 1
    return out


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _strings(value)


def check_fidelity(request, response):
    """Independent PerFin checks on an adapter response. Returns error list."""
    errors = []
    if response.get("export_id") != request.get("export_id"):
        errors.append("export_id mismatch")
    other = "text" if request["payload_kind"] == "ledger_rows" else "records"
    if response.get(other) is not None:
        errors.append("unexpected %s payload in response" % other)
    if request["payload_kind"] == "ledger_rows":
        req, resp = request.get("records", []), response.get("records")
        if not isinstance(resp, list) or len(resp) != len(req):
            return errors + ["record count changed"]
        for a, b in zip(req, resp):
            if a["record_id"] != b.get("record_id"):
                errors.append("record id changed: %s" % a["record_id"])
                continue
            for field in request["preserve_fields"]:
                if a.get(field) != b.get(field):
                    errors.append("%s: %s changed" % (a["record_id"], field))
            for field in a:
                # every field not selected for scrubbing must come back unchanged; deletion is a change
                if field in request["scrub_fields"] or field in request["preserve_fields"] or field == "record_id":
                    continue
                if field not in b or a[field] != b[field]:
                    errors.append("%s: unscrubbed field %s changed" % (a["record_id"], field))
            for field in request["scrub_fields"]:
                if field in a and field not in b:
                    errors.append("%s: scrubbed field %s missing" % (a["record_id"], field))
                    continue
                before, after = a.get(field, ""), b.get(field, "")
                if _money_tokens(before) != _money_tokens(after):
                    errors.append("%s: money in %s changed" % (a["record_id"], field))
                if Counter(_ISO_DATE.findall(before)) != Counter(_ISO_DATE.findall(after)):
                    errors.append("%s: dates in %s changed" % (a["record_id"], field))
    else:
        before, after = request.get("text", ""), response.get("text")
        if not isinstance(after, str):
            return errors + ["text missing"]
        if _money_tokens(before) != _money_tokens(after):
            errors.append("money in text changed")
        if Counter(_ISO_DATE.findall(before)) != Counter(_ISO_DATE.findall(after)):
            errors.append("dates in text changed")
    errors += residual_findings(request, response)
    return errors


def residual_findings(request, response):
    """Identifiers that survived scrubbing. Values are never echoed."""
    found = []
    # Scan every payload field the response carries, not only the requested one.
    payload = [response.get("records"), response.get("text")]
    sensitive = [s.casefold() for s in request.get("sensitive_values", [])]
    sensitive_digits = [re.sub(r"\D", "", s) for s in request.get("sensitive_values", [])]
    for text in _strings(payload):
        if _EMAIL.search(text):
            found.append("residual email")
        if find_card_numbers(text):
            found.append("residual card number")
        if _DIGITS.search(text):
            found.append("residual digit run")
        folded, digits = text.casefold(), re.sub(r"\D", "", text)
        for value, value_digits in zip(sensitive, sensitive_digits):
            if value in folded or (len(value_digits) >= 6 and value_digits in digits):
                found.append("residual sensitive value")
    return sorted(set(found))


def decide_export(defaults, feature_flag, description, request, response, user_confirmed):
    """Gate for outbound path O1. Fail closed; never a raw fallback.

    Returns (allowed, reasons). `description` / `response` may be None when
    the adapter is missing or did not answer.
    """
    nopii = defaults["nopii"]
    if nopii.get("raw_fallback_allowed"):
        return False, ["configuration error: raw fallback must be false"]
    if not feature_flag:
        return False, ["export feature disabled"]
    if description is None:
        return False, ["NoPii adapter not available - export disabled"]
    if validate_envelope(description) or description.get("kind") != "perfin.nopii.adapter_description":
        return False, ["invalid adapter description - export disabled"]
    if description["contract_version"].split(".")[:2] != nopii["contract_version"].split(".")[:2]:
        return False, ["unsupported contract version - export disabled"]
    if description["adapter"]["offline"] is not True:
        return False, ["adapter not offline - export disabled"]
    if request["payload_kind"] not in description["payload_kinds"]:
        return False, ["payload kind unsupported - export disabled"]
    if validate_envelope(request):
        return False, ["invalid request"]
    if response is None or validate_envelope(response) or response.get("kind") != "perfin.nopii.export_response":
        return False, ["invalid or missing adapter response - export cancelled"]
    if response.get("adapter", {}).get("offline") is not True:
        return False, ["adapter reported not offline for this export - export cancelled"]
    if response["status"] != "ok":
        return False, ["adapter status %s - export cancelled" % response["status"]]
    errors = check_fidelity(request, response)
    if errors:
        return False, errors
    if not user_confirmed:
        return False, ["awaiting user confirmation of scrubbed preview"]
    return True, []


# --------------------------------------------------------- config checks

def validate_defaults(cfg):
    errors = []
    for key, path in cfg["outbound"].items():
        if path.get("default_enabled") is not False:
            errors.append("%s must be disabled by default" % key)
    for key in ("O2", "O3", "O8"):
        if cfg["outbound"].get(key, {}).get("prohibited") is not True:
            errors.append("%s must be prohibited" % key)
    nopii = cfg["nopii"]
    if nopii.get("raw_fallback_allowed") is not False:
        errors.append("raw fallback must be false")
    if nopii.get("required_for_core_local_use") is not False:
        errors.append("NoPii must be optional for core local use")
    if not {"date", "amount_minor", "currency"} <= set(nopii["required_preserve_fields"]):
        errors.append("money/date fields must be preserved")
    if not {"=", "+", "-", "@", "\t", "\r"} <= set(cfg["formula_injection"]["triggers"]):
        errors.append("formula triggers incomplete")
    if cfg["data_dir"].get("refuse_inside_git_checkout") is not True:
        errors.append("data dir inside git checkout must be refused")
    for sub in ("statements/originals", "db", "backups", "logs", "temp", "exports/outbox"):
        if sub not in cfg["data_dir"]["subdirs"]:
            errors.append("missing subdir %s" % sub)
    return errors


# ------------------------------------------------------------- repo scan

def _repo_files(root):
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True,
        ).stdout.decode("utf-8")
        return [p for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in names:
                files.append(os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/"))
        return files


def scan_repo_for_forbidden(root, defaults=None):
    """Flag likely real-data files and non-test card numbers in a checkout."""
    guard = (defaults or load_defaults())["repo_guard"]
    allowed_pans = set(guard["allowed_test_pans"])
    findings = []
    for rel in sorted(set(_repo_files(root))):
        name = rel.rsplit("/", 1)[-1]
        # case-insensitive on every host: RUN.LOG and backup.BAK must not bypass the guard
        if any(fnmatch.fnmatchcase(name.casefold(), g.casefold()) for g in guard["always_forbidden_globs"]):
            findings.append("%s: forbidden file type" % rel)
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in guard["restricted_extensions"]:
            if not any(rel.startswith(p) for p in guard["restricted_extensions"][ext]):
                findings.append("%s: %s outside allowed paths" % (rel, ext))
        path = Path(root) / rel
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if find_card_numbers(text) - allowed_pans:
            findings.append("%s: Luhn-valid number not in test allow-list" % rel)
    return findings


# ------------------------------------------------------------------- CLI

def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    command = argv[1]
    if command == "validate-defaults":
        errors = validate_defaults(load_defaults(argv[2] if len(argv) > 2 else DEFAULTS_PATH))
    elif command == "validate-examples":
        errors = []
        for path in sorted(EXAMPLES_DIR.glob("*.json")):
            errors += ["%s: %s" % (path.name, e) for e in validate_envelope(load_json(path))]
    elif command == "check-data-dir":
        result = evaluate_data_dir(argv[2])
        print(json.dumps(result, indent=2))
        return 0 if result["decision"] == "ok" else 1
    elif command == "scan-repo":
        errors = scan_repo_for_forbidden(argv[2])
    else:
        print(__doc__)
        return 2
    for error in errors:
        print(error)
    print("OK" if not errors else "%d problem(s)" % len(errors))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
