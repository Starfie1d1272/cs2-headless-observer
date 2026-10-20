from pathlib import Path
import json,struct
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_RAX
import sys
from pathlib import Path
import struct,json,collections,time
from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UcError
from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_RSP,UC_X86_REG_RIP,UC_X86_REG_EFLAGS,UC_X86_REG_R8,UC_X86_REG_R9
b=Path(sys.argv[1]).read_bytes();pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;base=struct.unpack_from('<Q',b,opt+24)[0];size=struct.unpack_from('<I',b,opt+56)[0];sec=opt+struct.unpack_from('<H',b,pe+20)[0]
u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(base,(size+4095)&~4095);u.mem_write(base,b[:struct.unpack_from('<I',b,opt+60)[0]])
for i in range(struct.unpack_from('<H',b,pe+6)[0]):
 vs,va,sz,raw=struct.unpack_from('<IIII',b,sec+40*i+8)
 if sz:u.mem_write(base+va,b[raw:raw+sz])
scratch=0x10000000;stack=0x20000000;stop=0x30000000;u.mem_map(scratch,0x10000);u.mem_map(stack,0x10000);u.mem_map(stop,0x1000)

cat=json.loads(Path(sys.argv[2]).read_text());names={r['name']:(i,int(r['base'],16)) for i,r in enumerate(cat)}
lookup=scratch+0x7000;entries=scratch+0x8000
u.mem_write(lookup+12,struct.pack('<I',1));u.mem_write(lookup+16,struct.pack('<Q',entries))
for name,(i,ptr) in names.items():u.mem_write(entries+i*32+24,struct.pack('<Q',ptr))
def cstr(p):
 out=bytearray()
 for j in range(200):
  x=u.mem_read(p+j,1)[0]
  if not x:return out.decode()
  out.append(x)
 raise ValueError('string budget')
def ret(value):
 rsp=u.reg_read(UC_X86_REG_RSP);target=struct.unpack('<Q',u.mem_read(rsp,8))[0]
 u.reg_write(UC_X86_REG_RAX,value&0xffffffffffffffff);u.reg_write(UC_X86_REG_RSP,rsp+8);u.reg_write(UC_X86_REG_RIP,target)
def hook(uc,address,size,data):
 if address==0x1800ead30:ret(lookup)
 elif address==0x1800922c0:
  if u.reg_read(UC_X86_REG_RCX)!=lookup:ret(-1)
  else:
   p=struct.unpack('<Q',u.mem_read(u.reg_read(UC_X86_REG_RDX),8))[0];name=cstr(p);ret(names.get(name,(-1,0))[0])
u.hook_add(UC_HOOK_CODE,hook)
rows=[]
for kind,width,signed,underlying,expected in [('boxed-float',4,False,'float32','float32'),('boxed-integer',4,True,'int32','int32')]+[('enum',w,s,'',('int'if s else'uint')+str(w*8))for w in [1,2,4,8]for s in [False,True]]:
 u.mem_write(scratch,b'\0'*0x6000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 field=scratch;out=scratch+0x300;flags=scratch+0x500;name=scratch+0x600;under=scratch+0x700
 u.mem_write(name,b'FixtureType\0');u.mem_write(under,underlying.encode()+b'\0');u.mem_write(field+0x10,struct.pack('<Q',name));u.mem_write(field+0x20,struct.pack('<Q',name));u.mem_write(field+0x130,struct.pack('<Q',under));u.mem_write(field+0x38,struct.pack('<I',width))
 u.mem_write(field+({'boxed-float':0x14c,'boxed-integer':0x14b,'enum':0x146}[kind]),b'\1');u.mem_write(field+0x150,bytes([signed]))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<QQ',out,flags))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,name),(UC_X86_REG_R8,field),(UC_X86_REG_R9,name),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 u.emu_start(0x1800eb600,stop,timeout=100000,count=100000)
 actual=u.reg_read(UC_X86_REG_RAX);row={'kind':kind,'width':width,'signed':signed,'underlying':underlying,'expected':expected,'returned_catalog_address':hex(actual),'field_flags_d0':u.mem_read(out+0xd0,1)[0],'passed':actual==names[expected][1]and u.reg_read(UC_X86_REG_RIP)==stop};rows.append(row)
s={'manifest':'8766757721818354077','function':'networksystem+0xeb600','method':'Isolated native scalar selection; only primitive-registry lookup and dictionary lookup stubbed against saved native catalog. No schema constructor, OS imports or game process executed.','cases':len(rows),'passed':sum(r['passed']for r in rows)}
Path(sys.argv[3]).write_text(json.dumps({'summary':s,'cases':rows},indent=2)+'\n');print(json.dumps(s));assert all(r['passed']for r in rows)
