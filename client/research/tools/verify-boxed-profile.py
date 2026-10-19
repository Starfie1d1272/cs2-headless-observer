from pathlib import Path
import json,re
root=Path('.agent-tmp/gotv-research-plan')
profiles={};evidence={}
for module,iat in [('client','0x181aad7f0'),('server','0x1817643c8')]:
 data=json.loads((root/f'{module}-boxed-registration-evidence.json').read_text())
 assert not data['unresolved']
 profile={};rows=[]
 for row in data['calls']:
  bases={v['base'] for v in row['boxed_flags']}
  stores=[v for v in row['underlying_stores'] if v['base'] in bases and v['assignment_iat']==iat]
  names={v['name'] for v in stores};assert len(names)==1,(module,row)
  underlying=next(iter(names));shape=row['type'];name=re.sub(r'\[\d+\]$','',shape)
  if name.startswith('CNetworkUtlVectorBase<'):name=name.split('<',1)[1].split(',',1)[0].strip()
  assert name not in profile or profile[name]==underlying,(name,profile.get(name),underlying)
  profile[name]=underlying
  rows.append({'name':name,'shape':shape,'underlying':underlying,'constructor':row['constructor'],'call':row['call'],'stores':stores})
 profiles[module]=profile;evidence[module]=rows
assert profiles['client']==profiles['server']
result={'manifest':'8766757721818354077','profile':dict(sorted(profiles['client'].items())),'summary':{'client_calls':len(evidence['client']),'server_calls':len(evidence['server']),'base_types':len(profiles['client']),'mismatches':0,'scope':'signature-matched generated boxed constructors with IsAtomic, IsTypeSafe and CUtlString::Set to the same object +0x130; whole-game unrelated objects excluded'},'assignment_imports':{'client':'tier0!CUtlString::Set at181aad7f0','server':'tier0!CUtlString::Set at1817643c8'},'evidence':evidence}
(root/'native-boxed-type-profile.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['profile']));print(json.dumps(result['summary']))
