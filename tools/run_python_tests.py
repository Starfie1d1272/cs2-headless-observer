"""Run current Python tests and propagate import paths to fixture children."""

import argparse
import json
import os
from pathlib import Path
import sys
import unittest

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument(
    "--fast",
    action="store_true",
    help="Allow skipping worker-gated tests when GOTV_ORDERED_WORKER is unset.",
)
args = ap.parse_args()

ROOT = Path(__file__).resolve().parents[1]
paths = [
    str(ROOT / p) for p in ("client", "tests", "tests/python", "tools/diagnostics")
]
sys.path[:0] = paths
os.environ["PYTHONPATH"] = os.pathsep.join(paths + [os.environ.get("PYTHONPATH", "")])
suite = unittest.defaultTestLoader.discover(
    str(ROOT / "tests/python"), pattern="test_*.py"
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(
    json.dumps(
        {
            "mode": "fast-unit-only" if args.fast else "full",
            "tests": result.testsRun,
            "skipped": len(result.skipped),
            "failures": len(result.failures),
            "errors": len(result.errors),
        }
    )
)
if result.skipped and not args.fast:
    print(
        "Required tests were skipped. Build the worker and use tools/verify_all.py for native fixtures.",
        file=sys.stderr,
    )
raise SystemExit(
    0 if result.wasSuccessful() and (args.fast or not result.skipped) else 1
)
