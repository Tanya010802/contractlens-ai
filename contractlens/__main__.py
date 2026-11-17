import argparse
import json
import sys
from pathlib import Path

from .compare import SpecError, compare


def main():
    parser = argparse.ArgumentParser(description="Compare supported OpenAPI JSON contract changes")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--fail-on-high", action="store_true", help="Exit 1 if the report finds high-priority changes")
    args = parser.parse_args()
    try:
        report = compare(json.loads(args.before.read_text(encoding="utf-8")),
                         json.loads(args.after.read_text(encoding="utf-8")))
    except (OSError, ValueError, SpecError, RecursionError) as exc:
        print(f"ContractLens: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return int(args.fail_on_high and report["summary"]["high"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
