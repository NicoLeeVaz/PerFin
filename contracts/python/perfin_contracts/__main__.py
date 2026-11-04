"""python3 -m perfin_contracts FILE...   (PYTHONPATH=contracts/python)"""
import json
import sys

from .semantic import validate_document


def main(argv):
    bad = 0
    for path in argv:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        errs = validate_document(doc)
        print(f"{'OK ' if not errs else 'ERR'} {path}")
        for code, p, msg in errs:
            print(f"    {code} {p}: {msg}")
        bad += bool(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
