# Static generated-constructor evidence only. Never executes game code.
import sys,struct,bisect,json,re,hashlib
from pathlib import Path
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from capstone.x86_const import X86_OP_IMM,X86_OP_MEM,X86_OP_REG,X86_REG_RIP
path=Path(sys.argv[1]);b=path.read_bytes()
expected={'client.dll':'659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0','server.dll':'09e8c04c5f44040155d04fa79a3f43491d542a386f45807ed77785729e5925a9'}
assert hashlib.sha256(b).hexdigest()==expected[path.name], 'fixed-module-sha-mismatch'
pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;base=struct.unpack_from('<Q',b,opt+24)[0];secs=[]
for j in range(struct.unpack_from('<H',b,pe+6)[0]):
 k=opt+struct.unpack_from('<H',b,pe+20)[0]+40*j;vs,va,sz,raw=struct.unpack_from('<IIII',b,k+8);secs.append((b[k:k+8].rstrip(b'\0'),base+va,sz,raw))
def off(a):
 for _,va,sz,raw in secs:
  if va<=a<va+sz:return raw+a-va
 raise ValueError(hex(a))
def string(a):
 try:
  q=off(a);e=b.index(0,q,q+180);s=b[q:e].decode('ascii')
  return s if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_:<> ,*\[\]\-]*',s) else None
 except:return None
rva,size=struct.unpack_from('<II',b,opt+112+24);q=off(base+rva);ranges=[];ends={}
for p in range(q,q+size,12):
 a,z,u=struct.unpack_from('<III',b,p);root=a
 for _ in range(20):
  x=off(base+u);flags=b[x]>>3;count=b[x+2]
  if not flags&4:break
  root,_,u=struct.unpack_from('<III',b,x+((4+count*2+3)//4)*4)
 ranges.append((base+a,base+z,base+root));ends[base+root]=max(ends.get(base+root,0),base+z)
ranges.sort();starts=[x[0]for x in ranges]
def owner(a):
 k=bisect.bisect_right(starts,a)-1
 return ranges[k][2] if k>=0 and a<ranges[k][1] else None
cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True
text=next(s for s in secs if s[0]==b'.text');_,va,sz,raw=text
candidates=set()
for signature in [b'\x4b\x01\x00\x00\x01',b'\x4c\x01\x00\x00\x01']:
 p=raw
 while(p:=b.find(signature,p,raw+sz))>=0:
  root=owner(va+p-raw);p+=1
  if root:candidates.add(root)
constructors={}
for root in sorted(candidates):
 writes=[];underlying=[];stores=[];atomic_bases=set();pending_destination=None;pending_name=None;q=off(root)
 for ins in cs.disasm(b[q:q+min(ends[root]-root,10000)],root):
  if ins.mnemonic.startswith('ret'):break
  _,written=ins.regs_access()
  if any(cs.reg_name(r) in ('rcx','ecx','cx','cl','ch') for r in written):pending_destination=None
  if any(cs.reg_name(r) in ('rdx','edx','dx','dl','dh') for r in written):pending_name=None
  if ins.mnemonic=='mov'and len(ins.operands)==2:
   d,v=ins.operands
   if d.type==X86_OP_MEM and v.type==X86_OP_IMM and d.size==1 and d.mem.disp==0x144 and v.imm==1:atomic_bases.add(cs.reg_name(d.mem.base))
   if d.type==X86_OP_MEM and v.type==X86_OP_IMM and d.size==1 and d.mem.disp in(0x14b,0x14c) and v.imm==1:
    writes.append({'flag':hex(d.mem.disp),'address':hex(ins.address),'base':cs.reg_name(d.mem.base)})
  if ins.mnemonic=='lea'and len(ins.operands)==2:
   d,v=ins.operands
   if d.type==X86_OP_REG and cs.reg_name(d.reg)=='rcx':
    pending_destination=cs.reg_name(v.mem.base) if v.type==X86_OP_MEM and v.mem.disp==0x130 else None
   if d.type==X86_OP_REG and cs.reg_name(d.reg)=='rdx':
    pending_name=string(ins.address+ins.size+v.mem.disp) if v.type==X86_OP_MEM and v.mem.base==X86_REG_RIP else None
   v=ins.operands[1]
   if v.type==X86_OP_MEM and v.mem.base==X86_REG_RIP:
    name=string(ins.address+ins.size+v.mem.disp)
    if name in ['float32','float64','int8','int16','int32','int64','uint8','uint16','uint32','uint64']:
     underlying.append({'name':name,'address':hex(ins.address)})
  if ins.mnemonic=='call':
   if pending_destination and pending_name and ins.operands[0].type==X86_OP_MEM and ins.operands[0].mem.base==X86_REG_RIP:
    stores.append({'name':pending_name,'base':pending_destination,'call':hex(ins.address),'offset':'0x130','assignment_iat':hex(ins.address+ins.size+ins.operands[0].mem.disp)})
   pending_destination=None;pending_name=None
 writes=[w for w in writes if w['base'] in atomic_bases]
 if writes and underlying:constructors[root]={'boxed_flags':writes,'underlying_candidates':underlying,'underlying_stores':stores}
callers={};p=raw
while(p:=b.find(b'\xe8',p,raw+sz-5))>=0:
 a=va+p-raw;target=a+5+struct.unpack_from('<i',b,p+1)[0];p+=1
 if target in constructors:
  root=owner(a)
  if root:callers.setdefault(root,set()).add(a)
def regname(reg):
 s=cs.reg_name(reg)
 if s in ('eax','ax','al','ah'):return 'rax'
 if s in ('ebx','bx','bl','bh'):return 'rbx'
 if s in ('ecx','cx','cl','ch'):return 'rcx'
 if s in ('edx','dx','dl','dh'):return 'rdx'
 if s in ('edi','di','dil'):return 'rdi'
 if s in ('esi','si','sil'):return 'rsi'
 if s.startswith('r')and s[-1:]in ('d','w','b')and s[1:-1].isdigit():return s[:-1]
 return s
result=[];unresolved=[]
for root,sites in sorted(callers.items()):
 q=off(root);regs={};stack={}
 for ins in cs.disasm(b[q:q+max(sites)-root+5],root):
  ops=ins.operands;value=None;dest=None
  if ins.mnemonic=='lea'and len(ops)==2 and ops[0].type==X86_OP_REG and ops[1].type==X86_OP_MEM and ops[1].mem.base==X86_REG_RIP:
   value=string(ins.address+ins.size+ops[1].mem.disp);dest=regname(ops[0].reg)
  elif ins.mnemonic=='mov'and len(ops)==2:
   d,s=ops
   value=s.imm if s.type==X86_OP_IMM else regs.get(regname(s.reg)) if s.type==X86_OP_REG else None
   if d.type==X86_OP_REG:dest=regname(d.reg)
   elif d.type==X86_OP_MEM and cs.reg_name(d.mem.base)=='rsp':stack[d.mem.disp]=value
  elif ins.mnemonic=='xor'and len(ops)==2 and all(x.type==X86_OP_REG for x in ops)and ops[0].reg==ops[1].reg:
   value=0;dest=regname(ops[0].reg)
  _,written=ins.regs_access()
  for r in written:regs.pop(regname(r),None)
  if dest and value is not None:regs[dest]=value
  if ins.mnemonic=='call':
   target=ops[0].imm if len(ops)==1 and ops[0].type==X86_OP_IMM else None
   if ins.address in sites and target in constructors:
    row={'type':regs.get('r9'),'field':regs.get('rdx'),'width_argument':stack.get(0x20),'call':hex(ins.address),'constructor':hex(target),**constructors[target]}
    (result if isinstance(row['type'],str) else unresolved).append(row)
   for reg in ['rax','rcx','rdx','r8','r9','r10','r11']:regs.pop(reg,None)
summary={'module':str(path),'constructor_count':len(constructors),'identified_calls':len(result),'unresolved_calls':len(unresolved),'unique_types':len(set(x['type']for x in result)),'method':'Static boxed flag writes and direct constructor calls; underlying names are candidates until store linkage is checked; no game execution'}
out={'summary':summary,'calls':result,'unresolved':unresolved};Path(sys.argv[2]).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(summary))
