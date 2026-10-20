from pathlib import Path
import json,struct,re
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from capstone.x86_const import X86_OP_IMM,X86_OP_REG,X86_OP_MEM,X86_REG_R9,X86_REG_R9D,X86_REG_RSP
b=Path('.agent-tmp/gotv-tools/cs2/game/csgo/bin/win64/client.dll').read_bytes();p=struct.unpack_from('<I',b,60)[0];n=struct.unpack_from('<H',b,p+6)[0];o=struct.unpack_from('<H',b,p+20)[0];ss=[]
for j in range(n):
 k=p+24+o+j*40;name=b[k:k+8].split(b'\0')[0];vs,va,rs,rp=struct.unpack_from('<IIII',b,k+8);ss.append((name,va,rs,rp))
def va(off):
 for _,v,s,r in ss:
  if r<=off<r+s:return 0x180000000+v+off-r
names=set()
for s in json.loads(Path('.agent-tmp/gotv-research-plan/fixture-type-authority.json').read_text())['unannotated_types']:
 s=re.sub(r'\[\d+\]$','',s)
 if '<' in s:s=s.split('<',1)[1].rsplit('>',1)[0].strip()
 names.add(s)
addresses={}
for name in names:
 start=0;needle=name.encode()+b'\0'
 while (q:=b.find(needle,start))>=0:
  start=q+1
  if va(q):addresses[va(q)]=name
cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True;rows=[]
for sec,v,s,r in ss:
 if sec!=b'.text':continue
 q=r
 while (q:=b.find(b'\x4c\x8d\x0d',q,r+s-7))>=0:
  a=va(q);target=a+7+struct.unpack_from('<i',b,q+3)[0];q+=1
  if target not in addresses:continue
  width=None
  for ins in cs.disasm(b[q+6:q+6+512],a+7):
   if ins.mnemonic=='call':
    if len(ins.operands)==1 and ins.operands[0].type==X86_OP_IMM:
     rows.append({'type':addresses[target],'name_load':hex(a),'call':hex(ins.address),'constructor':hex(ins.operands[0].imm),'stack_argument_5':width})
    break
   if ins.mnemonic.startswith('ret'):break
   _,writes=ins.regs_access()
   if X86_REG_R9 in writes or X86_REG_R9D in writes:break
   if ins.mnemonic=='mov' and len(ins.operands)==2:
    d,sr=ins.operands
    if d.type==X86_OP_MEM and d.mem.base==X86_REG_RSP and d.mem.disp==0x20 and sr.type==X86_OP_IMM:width=sr.imm
Path('.agent-tmp/gotv-research-plan/generated-type-constructor-calls.json').write_text(json.dumps(rows,indent=2)+'\n')
by={}
for row in rows:by.setdefault(row['constructor'],set()).add(row['type'])
print(json.dumps({k:sorted(v) for k,v in by.items()},indent=2));print('CALLS',len(rows))
