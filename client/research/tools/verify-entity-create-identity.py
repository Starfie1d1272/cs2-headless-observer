from pathlib import Path
import struct,json,hashlib
path=Path('.agent-tmp/gotv-tools/cs2/game/csgo/bin/win64/client.dll');b=path.read_bytes()
assert hashlib.sha256(b).hexdigest()=='659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0'
pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;ss=[]
for i in range(struct.unpack_from('<H',b,pe+6)[0]):
 p=opt+struct.unpack_from('<H',b,pe+20)[0]+i*40;vs,va,sz,raw=struct.unpack_from('<IIII',b,p+8);ss.append((0x180000000+va,sz,raw))
def off(a):
 for va,sz,raw in ss:
  if va<=a<va+sz:return raw+a-va
 raise ValueError(hex(a))
slots=[(0x181c630f0,0xe8,0x180b6f120),(0x181c630f0,0xf0,0x180b65dc0),(0x181c30e48,8,0x1809e6500),(0x181c30e48,0x18,0x1809d41f0)]
for v,s,t in slots:assert struct.unpack_from('<Q',b,off(v+s))[0]==t
stores=[(0x1815afa0e,'41c1e50f'),(0x1815afa15,'894710'),(0x1815afadd,'41c1e50f'),(0x1815afae4,'895f10')]
for a,h in stores:assert b[off(a):off(a)+len(h)//2].hex()==h
v=0x181c30e48;col=struct.unpack_from('<Q',b,off(v-8))[0];typ=0x180000000+struct.unpack_from('<I',b,off(col)+12)[0];p=off(typ)+16
assert b[p:b.index(0,p)]==b'.?AVCEntity2NetworkClasses@@'
result={'manifest':'8766757721818354077','source_module_sha256':hashlib.sha256(b).hexdigest(),'verified_slots':[{'vtable':hex(v),'slot':hex(s),'target':hex(t)}for v,s,t in slots],'verified_serial_shift_stores':[{'address':hex(a),'bytes':h}for a,h in stores],'call_path':['engine0464f0 receives entity-create index and17-bit serial','Source2Client slotf0 -> clientb65dc0','CEntity2NetworkClasses slot18 -> client9d41f0','client15b1af0 ->15aff20 ->15af680'],'observations':['15aff20 validates explicit network index<0x4000 and serial<=0x1ffff (with separate-1 sentinel)','15af680 stores index in low15 bits and the supplied serial shifted15 in identity+10','event type8 carries native handle; full serial comparison is valid within the matching world/receive identity','SDK GetRefEHandle subtracts EF_IS_INVALID_EHANDLE during invalidated identity lifetime; this is not permission to subtract1 from every received serial'],'scope':'static cross-module create ownership and exact instruction checks; no live or complete entity-factory execution'}
Path('.agent-tmp/gotv-research-plan/entity-create-identity.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
