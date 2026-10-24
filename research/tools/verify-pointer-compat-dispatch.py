from pathlib import Path
import struct,json,hashlib
checks=[]
for module,path,sha,words,bytesites in [
 ('client','.agent-tmp/gotv-tools/cs2/game/csgo/bin/win64/client.dll','659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0',[(0x181c638a8,0x180b6c860)],[(0x180b6c881,'498be9')]),
 ('networksystem','.agent-tmp/gotv-tools/cs2/game/bin/win64/networksystem.dll','be7e13ad771b21c986e25d9469993a1225be5649473f3d722ca5eefe375d1bec',[],[(0x180077292,'488bb510020000'),(0x1800773bc,'4c8bce'),(0x1800773bf,'4c8b5010'),(0x1800773cf,'41ffd2')])]:
 b=Path(path).read_bytes();assert hashlib.sha256(b).hexdigest()==sha
 pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;ss=[]
 for i in range(struct.unpack_from('<H',b,pe+6)[0]):
  p=opt+struct.unpack_from('<H',b,pe+20)[0]+40*i;_,va,size,raw=struct.unpack_from('<IIII',b,p+8);ss.append((0x180000000+va,size,raw))
 def off(a):
  for va,size,raw in ss:
   if va<=a<va+size:return raw+a-va
  raise ValueError(hex(a))
 for a,v in words:assert struct.unpack_from('<Q',b,off(a))[0]==v
 for a,h in bytesites:assert b[off(a):off(a)+len(h)//2].hex()==h,(hex(a),b[off(a):off(a)+len(h)//2].hex())
 checks.append({'module':module,'sha256':sha,'words':[{'address':hex(a),'value':hex(v)}for a,v in words],'instructions':[{'address':hex(a),'bytes':h}for a,h in bytesites]})
result={'manifest':'8766757721818354077','checks':checks,'observation':'network077240 passes its fifth argument (field name) as callback R9; clientb6c860 reads R9 and searches helper+0x80. It ignores the owner/type arguments for this fixed implementation. Explicit trailing* is tested before the callback.','configuration':'b77390 populates helper+0x80 from the configured PointerFieldTypes name list; despite the section name, use the observed callback lookup argument','scope':'fixed-build metadata compatibility path; does not infer pointer semantics for unknown builds'}
Path('.agent-tmp/gotv-research-plan/pointer-compat-dispatch.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
