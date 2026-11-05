"""Exceptions raised by the importer.

Row-level problems never raise: they become staged rows carrying contract error
codes. Exceptions are reserved for problems that stop a whole file from being
staged (invalid profile, unknown account, unrecognised header layout).

Messages never contain field values (descriptions, amounts, balances), so they
are safe to show or to pass to a privacy-redacted diagnostic log.
"""


class ImportProblem(Exception):
    """Base class. ``code`` is a contract error code (common.schema.json)."""

    def __init__(self, code, message, errors=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors = list(errors or [])  # [(code, path, message)]


class ProfileError(ImportProblem):
    """The import profile is not a valid contract 1.0.x import_profile."""

    def __init__(self, message, errors=None):
        super().__init__("E_SCHEMA", message, errors)


class ImportRefused(ImportProblem):
    """The file cannot be staged with this profile/account (nothing is produced)."""


class UnknownFormat(ImportRefused):
    """The file's header does not match the profile. A human must choose or map.

    ``found_headers`` lists the header cells read from the file so a UI can offer a
    user column mapping (see ``profiles.profile_from_mapping``). Header names are
    column labels, not transaction values.
    """

    def __init__(self, message, found_headers=None, missing=None, code="E_SCHEMA"):
        super().__init__(code, message)
        self.found_headers = list(found_headers or [])
        self.missing = list(missing or [])


class ValueParseError(ValueError):
    """A single field failed strict parsing. ``code`` is E_PARSE_DATE or E_PARSE_AMOUNT."""

    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason
