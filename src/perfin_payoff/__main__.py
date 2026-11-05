"""Local JSON forecast command; file output is the caller's privacy responsibility."""
import argparse
import json
import sys
from . import ScenarioError, simulate, sensitivity


def main(argv=None):
    p = argparse.ArgumentParser(description="Approximate monthly payoff forecast; JSON on stdout")
    p.add_argument("scenario")
    p.add_argument("--extra-monthly-minor", type=int)
    args = p.parse_args(argv)
    try:
        with open(args.scenario, encoding="utf-8") as f:
            doc = json.load(f)
        result = simulate(doc) if args.extra_monthly_minor is None else sensitivity(doc, args.extra_monthly_minor)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, ScenarioError):
        print("Invalid/unreadable payoff scenario; check the local input and contract.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
