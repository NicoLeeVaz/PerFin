"""Read-only repository interface the importer needs.

The importer only *reads* prior state to classify rows; it never writes. Task 2b's
Access repository (or a test fake) provides these methods. Nothing here imports
or depends on 2b code.

Transactions are returned as plain mappings with at least ``transaction_id``,
``account_id``, ``posted_date`` (ISO text), ``amount_minor`` (int) and
``description``; optionally ``source_txn_id`` and ``fingerprint`` (the staging
fingerprint of the row the transaction was committed from).
"""
from typing import Iterable, Mapping, Optional, Protocol

# Prior batches in these states make the same (account, file hash) an exact replay.
# A rejected or rolled-back batch did not leave its rows in the ledger.
REPLAY_BATCH_STATES = frozenset({"staged", "approved", "committed"})


class ImportRepository(Protocol):
    def get_account(self, account_id: str) -> Optional[Mapping]:
        """Return {"account_id", "account_class", "currency"} or None if unknown."""

    def prior_batches(self, account_id: str) -> Iterable[Mapping]:
        """Batches already staged or committed for this account:
        {"batch_id", "source_file_sha256", "batch_status"}."""

    def find_candidates(self, account_id: str, posted_date: str, amount_minor: int,
                        window_days: int) -> Iterable[Mapping]:
        """Transactions on *this* account with exactly this amount whose posted date is
        within +/- window_days."""

    def find_by_source_txn_id(self, account_id: str, source_txn_id: str) -> Iterable[Mapping]:
        """Transactions on *this* account carrying this issuer transaction id.
        Source ids are scoped per account; other accounts are never searched."""

    def find_transfer_candidates(self, exclude_account_id: str, amount_minor: int, posted_date: str,
                                 window_days: int) -> Iterable[Mapping]:
        """Unlinked transactions on *other* accounts with exactly ``amount_minor`` (the
        caller passes the opposite of the staged amount) within +/- window_days.

        The importer then keeps only candidates whose account (looked up with
        ``get_account``) has the same currency as the target account: contract 1.0
        rejects cross-currency transfer links (E_CURRENCY_MISMATCH), so a 100-minor-unit
        EUR inflow is never a candidate for a 100-minor-unit USD outflow. An
        implementation may pre-filter by currency, but must return ``account_id``."""
