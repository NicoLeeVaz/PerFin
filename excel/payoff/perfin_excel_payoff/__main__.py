import argparse
import json
import sys
from . import build, read_scenario, recompute, save_command, install
from .workbook import write_to_outbox


def main(argv=None):
    p = argparse.ArgumentParser(description="Local payoff workbook; close Excel before recomputing")
    sub = p.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build")
    b.add_argument("scenario")
    b.add_argument("output")
    b.add_argument("--data-root")
    i = sub.add_parser("install")
    i.add_argument("scenario")
    i.add_argument("--data-root", required=True)
    r = sub.add_parser("recompute")
    r.add_argument("workbook")
    r.add_argument("--output")
    r.add_argument("--data-root")
    s = sub.add_parser("save-command")
    s.add_argument("workbook")
    s.add_argument("--data-root", required=True)
    args = p.parse_args(argv)
    try:
        if args.action == "build":
            with open(args.scenario, encoding="utf-8") as f: document = json.load(f)
            build(document, args.output, data_root=args.data_root)
        elif args.action == "install":
            with open(args.scenario, encoding="utf-8") as f: document = json.load(f)
            install(document, args.data_root)
        elif args.action == "recompute":
            recompute(args.workbook, args.output, data_root=args.data_root)
        else:
            write_to_outbox(save_command(read_scenario(args.workbook)), args.data_root)
        print("Payoff workbook operation completed locally.")
        return 0
    except Exception as exc:
        # Do not echo financial input values or file paths into shell logs.
        print("Payoff operation failed (%s). Check inputs, privacy location and that Excel is closed." % type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
