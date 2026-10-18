#!/usr/bin/env python3
"""Cloud/file integration checks with an existing public real demo; NEVER live GOTV."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fixture', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--oracle-dir', type=Path)
args = parser.parse_args()
args.output.mkdir()
root = Path(__file__).resolve().parents[1]
checks = []


def start(label, source, follow=False):
    directory = args.output / label
    command = ['pnpm', 'exec', 'tsx',
               'client/decode.ts', '--input', str(source.resolve()),
               '--output', str(directory.resolve()), '--seconds', '45']
    if follow:
        command.append('--follow')
    log = (args.output / (label + '.log')).open('w')
    child = subprocess.Popen(command, cwd=root, stdout=log, stderr=log, start_new_session=True)
    log.close()
    return child, directory


def finish(child, directory, expected):
    try:
        code = child.wait(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        raise AssertionError('child-timeout')
    report = json.loads((directory / 'report.json').read_text())
    assert code == expected, (directory.name, code, report)
    assert report['ordinaryViewerHandshake'] == 'INCONCLUSIVE'
    assert report['liveContinuousReceipt'] == 'INCONCLUSIVE'
    checks.append({'case': directory.name, 'exit': code, 'report': report})
    return report


def wait_event(child, directory):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        file = directory / 'events.jsonl'
        if file.exists() and file.stat().st_size:
            return
        assert child.poll() is None, 'child-exited-before-first-event'
        time.sleep(.05)
    raise AssertionError('no-event-before-producer-finished')


def events(directory):
    return [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]


def semantic(rows):
    keys = ('kind', 'tick', 'tickInterval', 'map', 'warmup', 'round', 'weapon', 'actor', 'target')
    return [tuple(row[k] for k in keys) for row in rows]


child, baseline = start('complete', args.fixture)
finish(child, baseline, 0)
expected = events(baseline)
growing = args.output / 'growing.dem'
with args.fixture.open('rb') as src, growing.open('wb') as dst:
    dst.write(src.read(16 * 1024**2))
    dst.flush()
    child, incremental = start('growing', growing, True)
    wait_event(child, incremental)  # Evidence emitted while producer still holds >300 MB.
    checks.append({'case': 'events-before-producer-complete', 'passed': True})
    while chunk := src.read(1024**2):
        dst.write(chunk)
        dst.flush()
        time.sleep(.002)
finish(child, incremental, 0)
assert semantic(events(incremental)) == semantic(expected)
checks.append({'case': 'complete-growing-event-equivalence', 'rows': len(expected), 'passed': True})
for label in ('stop', 'truncate'):
    source = args.output / (label + '.dem')
    with args.fixture.open('rb') as handle:
        source.write_bytes(handle.read(16 * 1024**2))
    child, directory = start(label, source, True)
    wait_event(child, directory)
    if label == 'stop':
        os.killpg(child.pid, signal.SIGTERM)
    else:
        source.write_bytes(b'')
    # pnpm may itself exit on SIGTERM; require the decoder report and no complete status.
    if label == 'stop':
        child.wait(timeout=10)
        deadline = time.monotonic() + 10
        while not (directory / 'report.json').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        report = json.loads((directory / 'report.json').read_text())
        assert report['outcome'] != 'complete', report
        checks.append({'case': label, 'wrapper_exit': child.returncode, 'report': report})
    else:
        finish(child, directory, 1)
for label, content in [('empty', b''), ('invalid', b'NOTADEMO' * 128)]:
    source = args.output / (label + '.dem')
    source.write_bytes(content)
    child, directory = start(label, source)
    finish(child, directory, 1)
if args.oracle_dir:
    for name in ('weapon_fire', 'player_death', 'round_start', 'round_end'):
        oracle = json.loads((args.oracle_dir / ('oracle-' + name + '.json')).read_text())
        actual = [r for r in expected if r['kind'] == name]
        assert len(actual) == len(oracle), (name, len(actual), len(oracle))
        assert sorted(r['tick'] for r in actual) == sorted(r['tick'] for r in oracle), name
        if name in ('weapon_fire', 'player_death'):
            assert sorted((r['tick'], r['weapon']) for r in actual) == sorted((r['tick'], r['weapon']) for r in oracle), name
        checks.append({'case': 'demoparser2-' + name, 'rows': len(actual), 'ticks_and_weapons_equal': True})
result = {'scope': 'OFFLINE_REAL_RECORDING_ARTIFICIAL_FILE_DELIVERY',
          'fixture_sha256': hashlib.file_digest(args.fixture.open('rb'), 'sha256').hexdigest(),
          'checks': checks}
(args.output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
