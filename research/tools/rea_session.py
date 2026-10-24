#!/usr/bin/env python3
"""Task-local, read-only REA/Ghidra reproduction. Raw results stay in a NEW private directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ['rea', 'ghidra', 'jdk', 'binary', 'queries', 'output']:
        ap.add_argument('--' + name, type=Path, required=True)
    args = ap.parse_args()
    recipe = json.loads(args.queries.read_text())
    with args.binary.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != recipe['binary_sha256']:
        raise SystemExit('binary hash mismatch: addresses must be re-established for another build')
    args.output.mkdir(mode=0o700)
    env = dict(os.environ, GHIDRA_INSTALL_DIR=str(args.ghidra.resolve()),
               JAVA_HOME=str(args.jdk.resolve()), REA_GHIDRA_STARTUP_TIMEOUT_MS='600000')
    log = (args.output / 'private-stderr.log').open('w')
    process = subprocess.Popen([str(args.rea.resolve()), '--mcp'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=log, text=True, env=env)
    serial = 0
    index = {'binary_sha256': digest, 'complete': False, 'queries': []}

    def request(method, params):
        nonlocal serial
        serial += 1
        process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': serial, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        while line := process.stdout.readline():
            value = json.loads(line)
            if value.get('id') == serial:
                return value
        raise RuntimeError('REA process ended before response')

    def call(name, arguments):
        return request('tools/call', {'name': name, 'arguments': arguments})

    try:
        request('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'mizar-private-static-research', 'version': '1'}})
        process.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        process.stdin.flush()
        opened = call('open_binary', {'path': str(args.binary.resolve()), 'provider_id': 'ghidra'})
        if opened.get('error') or opened.get('result', {}).get('isError'):
            raise RuntimeError('open-binary-failed')
        for query in recipe['queries']:
            if query['name'] not in {'search_strings', 'xrefs', 'resolve_containing_procedure', 'procedure_pseudo_code'}:
                raise ValueError('read-only-query-required')
            result = call(query['name'], query['arguments'])
            raw = (json.dumps(result, indent=2) + '\n').encode()
            name = f'private-query-{len(index["queries"]):03}.json'
            (args.output / name).write_bytes(raw)
            evidence = result.get('result', {}).get('structuredContent', {})
            index['queries'].append({'query': query, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                'evidence_id': evidence.get('evidence_id'), 'provider': evidence.get('provider'),
                'failed': bool(result.get('error') or result.get('result', {}).get('isError'))})
            (args.output / 'shareable-index.json').write_text(json.dumps(index, indent=2) + '\n')
        index['complete'] = not any(row['failed'] for row in index['queries'])
    finally:
        try:
            call('close_binary', {})
        except (RuntimeError, OSError):
            pass
        process.stdin.close()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
        log.close()
        (args.output / 'shareable-index.json').write_text(json.dumps(index, indent=2) + '\n')
    print('Static analysis finished. Raw pseudocode/logs are private; shareable-index.json contains metadata only.')
    return 0 if index['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
