"""Build, validate and queue contract `command` documents from the core workbook.

The workbook never writes the ledger. Review actions become `command` JSON files:

    <data root>/commands/drafts/   VBA drafts (PerFinCommands.bas), not yet validated
    <data root>/commands/outbox/   validated with perfin_contracts; the repository (2b/3a)
                                   picks them up, re-validates and executes them
    <data root>/commands/rejected/ drafts that failed validation, with an .errors.json

The data root must pass the 1c location check (never inside a Git checkout, never an
unacknowledged sync or network folder). This module does not execute commands.
"""
import datetime as dt
import json
import os
import re
import uuid
from pathlib import Path

from . import _deps

ISSUED_BY = "excel_core:review_sheet"
REVIEW_COMMANDS = ("approve_rows", "reject_rows")


class CommandError(Exception):
    def __init__(self, message, errors=()):
        super().__init__(message)
        self.errors = list(errors)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def build_review_command(command_type, batch_id, row_numbers, reason=None, batch_row_version=None,
                         issued_at=None, command_id=None, issued_by=ISSUED_BY):
    """Return a validated approve_rows/reject_rows command document."""
    if command_type not in REVIEW_COMMANDS:
        raise CommandError("the review sheet only issues %s" % ", ".join(REVIEW_COMMANDS))
    rows = sorted(set(row_numbers))
    payload = {"batch_id": batch_id, "row_numbers": rows}
    if command_type == "reject_rows":
        payload["reason"] = reason
    issued_at = issued_at or utc_now()
    doc = {
        "contract": "perfin",
        "contract_version": _deps.perfin_contracts.CONTRACT_VERSION,
        "document_type": "command",
        "command_id": command_id or str(uuid.uuid4()),
        "command_type": command_type,
        "issued_at": issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issued_by": issued_by,
        "payload": payload,
        # rpt_review_queue carries no batch row_version (tracker item); pass it when known.
        "expected_versions": ([] if batch_row_version is None else
                              [{"entity": "batch", "entity_id": batch_id, "row_version": batch_row_version}]),
    }
    validate(doc)
    return doc


def validate(doc):
    if not isinstance(doc, dict):
        raise CommandError("a command must be a JSON object", [("E_TYPE", "$", "not a JSON object")])
    errs = _deps.validate_document(doc)
    if not errs and doc.get("document_type") != "command":
        errs = [("E_DOCUMENT_TYPE", "$.document_type", "only command documents go to the outbox")]
    if errs:
        raise CommandError("command failed contract validation", errs)
    return doc


def precheck_review_rows(command_type, batch_id, row_numbers, review_rows):
    """UX pre-check against rpt_review_queue rows (the repository stays authoritative).

    Returns a list of problems; approving a row with errors or an unresolved possible
    duplicate would be refused by the repository (E_ROW_UNRESOLVED / E_DUPLICATE_UNRESOLVED).
    """
    by_row = {r["row_number"]: r for r in review_rows if r["batch_id"] == batch_id}
    problems = []
    for n in sorted(set(row_numbers)):
        r = by_row.get(n)
        if r is None:
            problems.append("row %d is not in the review queue for batch %s" % (n, batch_id))
        elif command_type == "approve_rows":
            if r["error_codes"]:
                problems.append("row %d has errors" % n)
            if r["duplicate_status"] == "possible":
                problems.append("row %d is a possible duplicate; resolve it first" % n)
    return problems


def check_data_root(data_root, acknowledged=False):
    result = _deps.evaluate_data_dir(str(data_root))
    if result["decision"] == "refuse" or (result["decision"] == "warn" and not acknowledged):
        raise CommandError("data root rejected by the privacy location check: %s"
                           % "; ".join(result["reasons"]))
    return result


def _checked_path(path, data_root, acknowledged=False):
    """Refuse child symlinks/junctions that escape the approved local root."""
    root = Path(data_root).resolve()
    resolved = Path(path).resolve()
    if resolved != root and root not in resolved.parents:
        raise CommandError("command path escapes the approved data root")
    check_data_root(resolved, acknowledged)
    return Path(path)


def _folder(data_root, name, acknowledged=False):
    p = _checked_path(Path(data_root) / "commands" / name, data_root, acknowledged)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_new(path, text):
    """Create `path` atomically; never overwrite an existing command."""
    tmp = path.with_name(path.name + ".partial")
    with open(tmp, "x", encoding="utf-8", newline="\n") as f:
        f.write(text)
    try:
        os.link(tmp, path)  # fails if the target exists
    finally:
        os.unlink(tmp)


def write_to_outbox(doc, data_root, acknowledged=False):
    """Validate `doc` and write it to <data root>/commands/outbox/<command_id>.json."""
    check_data_root(data_root, acknowledged)
    validate(doc)
    path = _folder(data_root, "outbox", acknowledged) / ("%s.json" % doc["command_id"])
    _write_new(path, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True) + "\n")
    return path


_DRAFT_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$")


def _draft_errors(path):
    """Contract errors for one draft file; [] only for a valid command named <command_id>.json.

    Every parsed value is validated: JSON null, arrays, numbers and strings are not
    command documents and are rejected (never promoted).
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [("E_SCHEMA", "$", "not valid JSON (%s)" % type(exc).__name__)]
    if not isinstance(doc, dict):
        return [("E_TYPE", "$", "draft must be a JSON object, found %s" % type(doc).__name__)]
    errors = list(_deps.validate_document(doc))
    if not errors and doc.get("document_type") != "command":
        errors = [("E_DOCUMENT_TYPE", "$.document_type", "only command documents are accepted")]
    if not errors and (not _DRAFT_NAME.match(path.name) or path.stem != doc["command_id"]):
        errors = [("E_SCHEMA", "$.command_id", "draft file name must be <command_id>.json")]
    return errors


def promote_drafts(data_root, acknowledged=False):
    """Validate VBA drafts; move valid ones to the outbox and invalid ones to rejected/."""
    check_data_root(data_root, acknowledged)
    drafts = _folder(data_root, "drafts", acknowledged)
    report = {"promoted": [], "rejected": []}
    for path in sorted(drafts.iterdir()):
        if not path.is_file() or not path.name.endswith(".json"):
            continue
        _checked_path(path, data_root, acknowledged)
        errors = _draft_errors(path)
        if errors:
            dest = _folder(data_root, "rejected", acknowledged) / path.name
            os.replace(path, dest)
            _write_new(dest.with_name(dest.name + ".errors.json"),
                       json.dumps([list(e) for e in errors], indent=1) + "\n")
            report["rejected"].append((path.name, errors))
        else:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            validate(doc)  # defence in depth: only a validated object reaches the outbox
            dest = _folder(data_root, "outbox", acknowledged) / path.name
            if dest.exists():
                raise CommandError("outbox already holds %s" % path.name)
            _write_new(dest, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True) + "\n")
            path.unlink()
            report["promoted"].append(path.name)
    return report
