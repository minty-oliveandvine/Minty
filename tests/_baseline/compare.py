"""Diff two `pytest -rfE` outputs: which tests newly fail, which newly pass.

    python tests/_baseline/compare.py BASELINE.txt NEW.txt

Both must be FULL runs (some tests only pass in suite order). Reads the `FAILED ...` /
`ERROR ...` summary lines, so `-rfE` is required when producing the files.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

LINE = re.compile(r"^(FAILED|ERROR) (\S+?)(?: - .*)?$")


def ids(path: str) -> set[str]:
    out = set()
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line.rstrip())
        if m:
            out.add(m.group(2))
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    base, new = ids(sys.argv[1]), ids(sys.argv[2])
    newly_failing = sorted(new - base)
    newly_passing = sorted(base - new)
    print(f"baseline non-passing: {len(base)}   new non-passing: {len(new)}")
    print(f"\nNEWLY FAILING ({len(newly_failing)}):")
    for t in newly_failing:
        print("  ", t)
    print(f"\nNEWLY PASSING ({len(newly_passing)}):")
    for t in newly_passing:
        print("  ", t)
    return 1 if newly_failing else 0


if __name__ == "__main__":
    sys.exit(main())
