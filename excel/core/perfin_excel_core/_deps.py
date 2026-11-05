"""Locate the frozen contract validator and the 1c privacy helpers.

They are imported from the checkout (contracts/python and config/privacy), never
copied. Packaging for an installed release belongs to task 3a.
"""
import sys
from pathlib import Path

try:
    from perfin_resources import root as resource_root
    REPO_ROOT = resource_root()
except ImportError:
    REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_DIR = REPO_ROOT / "excel" / "core"
CONTRACTS_DIR = REPO_ROOT / "contracts"
REPORT_TABLES_JSON = CONTRACTS_DIR / "schemas" / "report_tables.json"

for _p in (CONTRACTS_DIR / "python", REPO_ROOT / "config" / "privacy"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

import perfin_contracts  # noqa: E402
from perfin_contracts.semantic import validate_document  # noqa: E402
from perfin_privacy_checks import (  # noqa: E402
    escape_spreadsheet_text,
    evaluate_data_dir,
    find_git_checkout,
    needs_formula_escape,
)

__all__ = [
    "REPO_ROOT", "CORE_DIR", "REPORT_TABLES_JSON", "perfin_contracts", "validate_document",
    "escape_spreadsheet_text", "evaluate_data_dir", "find_git_checkout", "needs_formula_escape",
]
