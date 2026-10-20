from pathlib import Path
import struct,json,bisect,hashlib
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from capstone.x86_const import X86_OP_MEM
b=Path('.agent-tmp/gotv-tools/cs2/game/bin/win64/engine2.dll').read_bytes();assert hashlib.sha256(b).hexdigest() == '6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21';p=struct.unpack_from('<I',b,60)[0];n=struct.unpack_from('<H',b,p+6)[0];o=struct.unpack_from('<H',b,p+20)[0];ss=[]
for j in range(n):
 k=p+24+o+j*40;name=b[k:k+8].split(b'\0')[0];vs,va,rs,rp=struct.unpack_from('<IIII',b,k+8);ss.append((name,va,rs,rp))
def off(rva):
 for _,v,s,r in ss:
  if v<=rva<v+s:return r+rva-v
 raise ValueError(hex(rva))
pr,sz=struct.unpack_from('<II',b,p+24+112+3*8);rs=[]
for q in range(off(pr),off(pr)+sz,12):
 a,z,u=struct.unpack_from('<III',b,q)
 if a<z:rs.append((a,z))
rs.sort();starts=[x[0]for x in rs];candidates=set()
for sec,v,s,r in ss:
 if sec!=b'.text':continue
 for disp in [0x2c1420,0x2c1428,0x2c1430,0x2c1434]:
  q=r
  while (q:=b.find(struct.pack('<I',disp),q,r+s))>=0:
   a=v+q-r;i=bisect.bisect_right(starts,a)-1;q+=1
   if i>=0 and a<rs[i][1]:candidates.add(rs[i])
cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True;out=[]
for a,z in sorted(candidates):
 for ins in cs.disasm(b[off(a):off(a)+z-a],0x180000000+a):
  if any(x.type==X86_OP_MEM and x.mem.disp in [0x2c1420,0x2c1428,0x2c1430,0x2c1434]for x in ins.operands):out.append({'function':hex(a),'address':hex(ins.address-0x180000000),'instruction':ins.mnemonic+' '+ins.op_str})
Path('.agent-tmp/gotv-research-plan/reliable-boundary-state-references.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
