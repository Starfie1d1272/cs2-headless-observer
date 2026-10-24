"""Validate maintained links, source syntax and byte-preserved historical evidence."""
import ast
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'archive/migration.json').read_text(encoding='utf-8'))
preserved=0
for entry in manifest['files']:
    name=entry['to']
    if name.startswith(('archive/','research/data/','research/evidence/')) or name=='tests/fixtures/password-oracle.json':
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==entry['originalSha256'],name
        preserved+=1
syntax=0
for base in ('client','native','tools','tests','research'):
    for p in (ROOT/base).rglob('*.py'):
        ast.parse(p.read_text(encoding='utf-8'),filename=str(p)); syntax+=1
checked=0
for p in [ROOT/'README.md',ROOT/'CONTRIBUTING.md',ROOT/'THIRD_PARTY_NOTICES.md',*(ROOT/'docs').rglob('*.md'),*(ROOT/'research/knowledge').glob('*.md'),ROOT/'research/README.md',ROOT/'patches/README.md']:
    body=p.read_text(encoding='utf-8')
    for target in re.findall(r'\]\(([^)\s]+)\)',body):
        if '://' in target or target.startswith(('#','mailto:')): continue
        raw=unquote(target.split('#',1)[0])
        if not raw: continue
        assert (p.parent/raw).exists(),(p.relative_to(ROOT).as_posix(),target)
        checked+=1
print(json.dumps({'preservedHistoricalFiles':preserved,'pythonSyntaxFiles':syntax,'maintainedLocalLinks':checked,'passed':True}))
