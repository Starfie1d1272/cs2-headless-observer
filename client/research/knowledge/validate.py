#!/usr/bin/env python3
"""Validate this catalog's structure and evidence digests, not scientific truth."""
import argparse, hashlib, json, pathlib, re
p=argparse.ArgumentParser();p.add_argument('repository',type=pathlib.Path);args=p.parse_args()
root=args.repository.resolve();here=root/'client/research/knowledge'
d=json.loads((here/'facts.json').read_text(encoding='utf-8'));manifest=json.loads((here/'sources.json').read_text(encoding='utf-8'));ids=set();sources=set()
for fact in d['facts']:
 assert re.fullmatch(r'[A-Z]+-\d{3}',fact['id']),fact['id']
 assert fact['id'] not in ids,fact['id'];ids.add(fact['id'])
 for key in ('topic','title','conclusion','classification','scope','modules','sources','use_in','reuse_rule'):assert fact[key],(fact['id'],key)
 sources.update(fact['sources'])
assert sources==set(manifest['files']), 'Evidence index differs from catalog'
for name in sources:
 file=(root/name).resolve();assert root in file.parents,name
 assert file.is_file(),name
 assert hashlib.sha256(file.read_bytes()).hexdigest()==manifest['files'][name],name
print(json.dumps({'facts':len(ids),'sources':len(sources),'structure_and_hashes':'pass','semantic_verification':'not performed by this validator'},ensure_ascii=False))
