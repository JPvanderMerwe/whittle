#!/usr/bin/env python3
"""
Write the schemas the native client's tests are checked against.

    python3 tools/app_fixtures.py            # write them
    python3 tools/app_fixtures.py --check    # fail if they are stale

WHY THE APP'S TESTS NEED THE REAL SCHEMAS
-----------------------------------------
The phone offers one-tap changes - "make it taller", "make the roof gable",
"no gusset" - and builds them from each template's own fields, so a part with
no width is never offered "wider". A test against a made-up template would
prove the filter runs; only the real schemas prove it filters the right things.

AND THEY GO STALE SILENTLY, which is the whole reason this is a --check rather
than a note in a README. A template that gains a field, loses a choice or
renames one leaves the app's tests passing against a copy of last month, while
the app itself offers a change the engine no longer has. The same argument
tools/tokens.py makes about a hex value that exists in two places: the drift is
invisible until somebody puts the two side by side.

What is NOT duplicated here is behaviour. The fixtures are data; the sentences
built from them are checked against the parser itself in
tests/test_app_phrases.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# RUNNING A SCRIPT PUTS ITS OWN DIRECTORY ON sys.path, NOT THE WORKING ONE. So
# `python3 tools/app_fixtures.py` from the repo root cannot import `whittle`,
# while `python3 -c "import whittle"` from the same directory can. This is the
# first tool in here that imports the package; the others only read JSON.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "app" / "tests" / "fixtures"

TEMPLATES = OUT / "templates.json"
OPERATIONS = OUT / "operations.json"


def _templates() -> str:
    from whittle import api

    return json.dumps(
        {name: api.template_info(name) for name in api.templates()},
        indent=1, sort_keys=True, default=str,
    )


def _operations() -> str:
    from whittle.web import projects as P

    return json.dumps(P.catalogue(), indent=1, sort_keys=True, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--check", action="store_true",
                        help="fail if a fixture is stale; write nothing")
    args = parser.parse_args(argv)

    wanted = {TEMPLATES: _templates(), OPERATIONS: _operations()}

    if args.check:
        stale = [
            path for path, text in wanted.items()
            if not path.is_file() or path.read_text() != text
        ]
        if stale:
            print("stale app fixtures:")
            for path in stale:
                print("  %s" % path.relative_to(ROOT))
            print("\nrun: python3 tools/app_fixtures.py")
            return 1
        print("app fixtures are current")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for path, text in wanted.items():
        path.write_text(text)
        print("wrote %s" % path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
