"""Run current Python tests and propagate import paths to fixture children."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
paths = [str(ROOT / p) for p in ('client', 'tests', 'tests/python', 'tools/diagnostics')]
sys.path[:0] = paths
os.environ['PYTHONPATH'] = os.pathsep.join(paths + [os.environ.get('PYTHONPATH', '')])
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests/python'), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'tests': result.testsRun, 'skipped': len(result.skipped),
                  'failures': len(result.failures), 'errors': len(result.errors)}))
if result.skipped:
    print('Required tests were skipped. Build the worker and use tools/verify_all.py for native fixtures.', file=sys.stderr)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
