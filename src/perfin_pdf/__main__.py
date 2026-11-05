"""Extract a declared layout to stdout only; core app owns guarded persistence."""
import argparse
import json
import sys
from pathlib import Path
from .parser import LAYOUT_ID, PdfRefused, extract_pdf


def main(argv=None):
    p = argparse.ArgumentParser(description="Local PDF extraction preview (contains private financial text).")
    p.add_argument("action", choices=["extract"])
    p.add_argument("source", type=Path)
    p.add_argument("--layout", default=LAYOUT_ID)
    args = p.parse_args(argv)
    try:
        result = extract_pdf(args.source.read_bytes(), layout_id=args.layout)
    except OSError:
        print("PDF_UNREADABLE: cannot read the selected local file", file=sys.stderr)
        return 2
    except PdfRefused as exc:
        print("%s: %s" % (exc.code, exc), file=sys.stderr)
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=True, indent=2))
    return 0 if result.reconciled else 1


if __name__ == "__main__":
    raise SystemExit(main())
