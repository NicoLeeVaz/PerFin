"""Locate the frozen contract package, the privacy checks and the access/ sources.

PerFin is not packaged yet (packaging belongs to 3a). Until it is, these are found relative to
the checkout, or through PERFIN_CONTRACTS_DIR / PERFIN_PRIVACY_DIR / PERFIN_ACCESS_DIR. The
validator and the privacy checks are imported, never copied.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _dir(env: str, default: Path) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else default


CONTRACTS_PYTHON = _dir("PERFIN_CONTRACTS_DIR", REPO_ROOT / "contracts" / "python")
PRIVACY_DIR = _dir("PERFIN_PRIVACY_DIR", REPO_ROOT / "config" / "privacy")
ACCESS_DIR = _dir("PERFIN_ACCESS_DIR", REPO_ROOT / "access")
SCHEMA_DIR = ACCESS_DIR / "schema"


def _ensure(path: Path) -> None:
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def contracts():
    """Return (validate_document, schema_dir, contract_version, supported_major, supported_minor)."""
    _ensure(CONTRACTS_PYTHON)
    import perfin_contracts
    from perfin_contracts.schema_subset import SCHEMA_DIR as CONTRACT_SCHEMA_DIR
    from perfin_contracts.semantic import validate_document

    return (validate_document, Path(CONTRACT_SCHEMA_DIR), perfin_contracts.CONTRACT_VERSION,
            perfin_contracts.SUPPORTED_MAJOR, perfin_contracts.SUPPORTED_MINOR)


def privacy():
    """Return the config/privacy/perfin_privacy_checks module (1c reference checks)."""
    _ensure(PRIVACY_DIR)
    import perfin_privacy_checks

    return perfin_privacy_checks
