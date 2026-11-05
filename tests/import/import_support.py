"""Shared helpers for the 2a import tests (synthetic data only).

Puts ``src`` and ``contracts/python`` on sys.path so the tests use the frozen
contract validator in place, without copying it.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "contracts", "python")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from perfin_contracts.semantic import validate_document  # noqa: E402
from perfin_import import builtin_profiles, stage_file  # noqa: E402

FIXTURES = os.path.join(ROOT, "fixtures", "import")
STAGED_AT = "2026-07-10T12:00:00Z"
READ_METHODS = {"get_account", "prior_batches", "find_candidates", "find_by_source_txn_id",
                "find_transfer_candidates"}


def fixture_bytes(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def profile(pid, version="1.0.0"):
    return builtin_profiles()[(pid, version)]


class FakeRepository:
    """In-memory stand-in for the 2b repository. Records every call.

    The importer may only call READ_METHODS. The write methods exist so that any
    attempted ledger/staging write is recorded in ``writes`` (and must stay empty).
    """

    def __init__(self, accounts=None, batches=None, transactions=None):
        self.accounts = {a["account_id"]: a for a in (accounts or DEFAULT_ACCOUNTS)}
        self.batches = list(batches or [])
        self.transactions = list(transactions or [])
        self.calls = []
        self.writes = []

    # ----- read interface (repository.ImportRepository)
    def get_account(self, account_id):
        self.calls.append("get_account")
        return self.accounts.get(account_id)

    def prior_batches(self, account_id):
        self.calls.append("prior_batches")
        return [dict(b) for b in self.batches if b["account_id"] == account_id]

    def find_candidates(self, account_id, posted_date, amount_minor, window_days):
        from datetime import date
        self.calls.append("find_candidates")
        d = date.fromisoformat(posted_date)
        return [dict(t) for t in self.transactions if t["account_id"] == account_id
                and t["amount_minor"] == amount_minor
                and abs((date.fromisoformat(t["posted_date"]) - d).days) <= window_days]

    def find_by_source_txn_id(self, account_id, source_txn_id):
        self.calls.append("find_by_source_txn_id")
        return [dict(t) for t in self.transactions
                if t["account_id"] == account_id and t.get("source_txn_id") == source_txn_id]

    def find_transfer_candidates(self, exclude_account_id, amount_minor, posted_date, window_days):
        from datetime import date
        self.calls.append("find_transfer_candidates")
        d = date.fromisoformat(posted_date)
        return [dict(t) for t in self.transactions if t["account_id"] != exclude_account_id
                and t["amount_minor"] == amount_minor and not t.get("linked")
                and abs((date.fromisoformat(t["posted_date"]) - d).days) <= window_days]

    # ----- write methods the importer must never call
    def save_batch(self, *a, **k):
        self.writes.append(("save_batch", a, k))

    def insert_transaction(self, *a, **k):
        self.writes.append(("insert_transaction", a, k))

    def commit_batch(self, *a, **k):
        self.writes.append(("commit_batch", a, k))

    # ----- test helper (not part of the importer interface)
    def remember_batch(self, document, status=None):
        b = document["batch"]
        self.batches.append({"account_id": b["account_id"], "batch_id": b["batch_id"],
                             "source_file_sha256": b["source_file_sha256"],
                             "batch_status": status or b["batch_status"]})


DEFAULT_ACCOUNTS = [
    {"account_id": "chk:main", "account_class": "checking", "currency": "USD"},
    {"account_id": "sav:main", "account_class": "savings", "currency": "USD"},
    {"account_id": "card:alpha", "account_class": "credit_card", "currency": "USD"},
    {"account_id": "card:beta", "account_class": "credit_card", "currency": "USD"},
]


def stage(testcase, data, name, prof, account, repo=None, **kw):
    """Stage and assert the contract validator accepts the result and nothing was written."""
    repo = repo if repo is not None else FakeRepository()
    kw.setdefault("staged_at", STAGED_AT)
    result = stage_file(data, name, prof, account, repo, validator=validate_document, **kw)
    testcase.assertEqual(validate_document(result.document), [], "staging_batch must pass contract 1.0.0")
    testcase.assertEqual(repo.writes, [], "importer must not write")
    testcase.assertTrue(set(repo.calls) <= READ_METHODS, repo.calls)
    testcase.assertEqual(result.document["batch"]["batch_status"], "staged")
    return result


def csv_bytes(text, encoding="utf-8"):
    return text.replace("\n", "\r\n").encode(encoding)
