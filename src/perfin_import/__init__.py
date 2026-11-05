"""PerFin CSV import staging (task 2a). Standard library only.

Parses institution CSV exports with declarative ``import_profile`` documents and
produces contract 1.0.0 ``staging_batch`` documents for human review. It never
writes the ledger: Access (task 2b) commits approved rows via ``commit_batch``.
"""
IMPORTER_VERSION = "0.1.0"

from .errors import ImportProblem, ImportRefused, ProfileError, UnknownFormat, ValueParseError  # noqa: E402
from .profiles import (builtin_profiles, load_profile, load_profiles_dir, match_profiles,  # noqa: E402
                       profile_from_mapping, validate_profile)
from .staging import StageResult, stage_file, summarize_batch  # noqa: E402
from .values import parse_amount, parse_date  # noqa: E402

__all__ = [
    "IMPORTER_VERSION", "ImportProblem", "ImportRefused", "ProfileError", "UnknownFormat", "ValueParseError",
    "builtin_profiles", "load_profile", "load_profiles_dir", "match_profiles", "profile_from_mapping",
    "validate_profile", "StageResult", "stage_file", "summarize_batch", "parse_amount", "parse_date",
]
