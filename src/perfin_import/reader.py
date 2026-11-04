"""Decode bytes and split them into CSV records with the standard ``csv`` module.

* Decoding is strict per the profile's declared encoding. Undecodable bytes are
  never replaced: they are carried as surrogate escapes only long enough to mark
  the affected record E_PARSE_ENCODING, and are never written into staging.
* RFC 4180 quoting via ``csv`` with ``strict=True``: doubled quotes, quoted
  delimiters and quoted newlines are kept exactly; trailing empty fields are kept.
  Backslash is not an escape character.
* A structural CSV error (for example an unterminated quote) stops reading at
  that point; the caller stages what was read plus an error record.
"""
import csv
import io

_SURROGATE_LO, _SURROGATE_HI = 0xDC80, 0xDCFF


def has_undecodable(text):
    return any(_SURROGATE_LO <= ord(ch) <= _SURROGATE_HI for ch in text)


class Record:
    __slots__ = ("fields", "line", "bad_fields")

    def __init__(self, fields, line):
        self.fields = fields
        self.line = line  # physical line where the record starts (1-based)
        self.bad_fields = [i for i, f in enumerate(fields) if has_undecodable(f)]


class ReadResult:
    def __init__(self, records, blank_records, structural_error_line, bom_mismatch):
        self.records = records
        self.blank_records = blank_records
        self.structural_error_line = structural_error_line  # None if the whole file parsed
        self.bom_mismatch = bom_mismatch


def decode(data, encoding):
    """Decode ``data``; undecodable bytes become lone surrogates (flagged later)."""
    return data.decode(encoding, errors="surrogateescape")


def read_records(data, file_spec):
    encoding = file_spec["encoding"]
    text = decode(data, encoding)
    bom_mismatch = encoding != "utf-8-sig" and data.startswith(b"\xef\xbb\xbf")
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=file_spec["delimiter"],
        quotechar=file_spec.get("quote_char", '"'),
        doublequote=True,
        escapechar=None,
        skipinitialspace=False,
        strict=True,
        quoting=csv.QUOTE_MINIMAL,
    )
    records, blank = [], 0
    structural_error_line = None
    start_line = 1
    while True:
        try:
            fields = next(reader)
        except StopIteration:
            break
        except csv.Error:
            structural_error_line = start_line
            break
        if fields == []:
            blank += 1
        else:
            records.append(Record(fields, start_line))
        start_line = reader.line_num + 1
    return ReadResult(records, blank, structural_error_line, bom_mismatch)
