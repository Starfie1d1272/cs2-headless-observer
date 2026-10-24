"""Run the supplied synthetic channel example without Steam or a network connection."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    default_fixture=ROOT/'examples/synthetic-channel.json'
    if not default_fixture.is_file(): default_fixture=ROOT/'tests/fixtures/synthetic-channel.json'
    ap.add_argument('--fixture',type=Path,default=default_fixture)
    ap.add_argument('--worker',type=Path,default=ROOT/'client/parser_worker.mjs')
    ap.add_argument('--node',default=str(ROOT/'runtime/node.exe') if (ROOT/'runtime/node.exe').is_file() else 'node')
    ap.add_argument('--output',type=Path,default=ROOT/'runs'/('synthetic-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')))
    args=ap.parse_args()
    fixture=json.loads(args.fixture.read_text(encoding='utf-8'))
    if fixture.get('schema')!='cs2-observer-synthetic-channel/1' or fixture.get('provenance')!='WHOLLY_SYNTHETIC_NO_MATCH_NO_PLAYER_DATA':
        ap.error('Expected the synthetic example fixture')
    args.output.mkdir(parents=True,exist_ok=False)
    sample=args.output/'synthetic.frames'
    with sample.open('xb') as out:
        out.write(b'MZRCS2\x01\0')
        for frame in fixture['frames']:
            body=base64.b64decode(frame['bodyBase64'],validate=True)
            out.write(struct.pack('<IQB',len(body),frame['elapsedMs'],int(frame['reliable']))+body)
    subprocess.run([sys.executable,'-B',str(ROOT/'client/replay_ordered.py'),'--input',str(sample),
        '--worker',str(args.worker.resolve()),'--node',args.node,'--host-version',str(fixture['hostVersion']),
        '--output',str(args.output/'replay')],check=True)
    rows=[json.loads(line) for line in (args.output/'replay/events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(row.get('kind')=='cursor' and row.get('tick')==100 for row in rows), 'Missing synthetic cursor'
    assert sum(row.get('kind')==fixture['expectedEvent'] for row in rows)==1, 'Missing synthetic lifecycle event'
    print(json.dumps({'synthetic':True,'frames':len(fixture['frames']),'events':len(rows),'passed':True}))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
