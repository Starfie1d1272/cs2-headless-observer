"""Minimal private process consumer. Importing this module never launches an observer."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


class Consumer:
    def __init__(self, source):
        self.source, self.sequence, self.world, self.ready = source, 0, 1, False

    def accept(self, row):
        sequence = row.get('sequence')
        if row.get('source') != self.source or row.get('channel') != 1:
            raise ValueError('source-owner-mismatch')
        if type(sequence) is not int or not self.sequence < sequence <= 9007199254740991:
            raise ValueError('record-order')
        self.sequence = sequence
        if type(row.get('world')) is not int or row['world'] < self.world:
            return None
        if row.get('kind') == 'discontinuity':
            self.world, self.ready = row['world'], False
        elif row.get('kind') == 'cursor' and row['world'] == self.world:
            self.ready = (type(row.get('tick')) is int and row['tick'] > 0
                and isinstance(row.get('map'), str) and bool(row['map'])
                and type(row.get('tickInterval')) in (int, float) and 0 < row['tickInterval'] <= 1)
        elif row.get('type') == 'raw-event' and self.ready and row['world'] == self.world:
            return row
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', type=Path, required=True)
    ap.add_argument('--steam-api', type=Path, required=True)
    ap.add_argument('--host-version', type=int, required=True)
    ap.add_argument('--node', type=Path)
    args = ap.parse_args()
    root = args.package.resolve(strict=True)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    def entry(name):
        value = (root / manifest['entrypoints'][name]).resolve(strict=True)
        if not value.is_relative_to(root):
            raise ValueError('artifact-entrypoint')
        return str(value)
    node = args.node or (root / 'runtime/node.exe' if (root / 'runtime/node.exe').exists() else shutil.which('node'))
    if not node:
        ap.error('Supply --node for the external-node package')
    if os.environ.get('SteamAppId', '730') != '730':
        ap.error('Run outside another Steam application context')
    identity = uuid.uuid4().hex
    state = Consumer('ahead:' + identity)
    output = Path(tempfile.mkdtemp(prefix='observer-consumer-')) / identity
    command = [entry('python'), '-B', entry('driver'), '--managed', '--native', entry('native'),
        '--steam-api', str(args.steam_api.resolve(strict=True)), '--node', str(node),
        '--parser-worker', entry('worker'), '--source-role', 'ahead', '--source-id', identity,
        '--host-version', str(args.host_version), '--output', str(output)]
    connection = {'endpoint': getpass.getpass('Authorized GOTV IP:port: '), 'password': getpass.getpass('Password: ')}
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={**os.environ, 'SteamAppId': '730'}, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        child.stdin.write((json.dumps(connection) + '\n').encode()); child.stdin.flush()
        connection.clear()
        while line := child.stdout.readline(65537):
            if len(line) > 65536 or not line.endswith(b'\n'):
                raise ValueError('invalid-record-budget-or-ending')
            event = state.accept(json.loads(line.decode('utf-8')))
            if event:
                print(json.dumps({'kind': event['kind'], 'eventServerTick': event.get('eventServerTick')}, ensure_ascii=False))
    except KeyboardInterrupt:
        pass
    finally:
        state.ready = False
        child.stdin.close()
        try: child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=3)
        child.stdout.close()
        print('Private report:', output / 'report.json')
    return child.returncode


if __name__ == '__main__':
    raise SystemExit(main())
