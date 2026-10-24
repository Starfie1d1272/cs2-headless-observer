"""Fixed client callback facts, isolated CPU memory only; no OS loader/imports."""
import hashlib,json,struct,sys
from pathlib import Path
from unicorn import Uc,UC_ARCH_X86,UC_MODE_64
from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_R8,UC_X86_REG_RSP,UC_X86_REG_RAX
path=Path(sys.argv[1]);output=Path(sys.argv[2]);data=path.read_bytes()
expected='659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0'
assert hashlib.sha256(data).hexdigest()==expected
pe=struct.unpack_from('<I',data,60)[0];n=struct.unpack_from('<H',data,pe+6)[0];opt=struct.unpack_from('<H',data,pe+20)[0];sections=[]
for i in range(n):
 p=pe+24+opt+i*40;vs,va,rs,rp=struct.unpack_from('<IIII',data,p+8);sections.append((va,max(vs,rs),rp))
def offset(va):return next(rp+va-0x180000000-start for start,size,rp in sections if start<=va-0x180000000<start+size)
uc=Uc(UC_ARCH_X86,UC_MODE_64);uc.mem_map(0x100000,0x10000)
ctx,entity,target,wire,stack,stop=0x100100,0x101000,0x105000,0x106000,0x109000,0x10f000
callbacks=[('x',0x180b9adc0,0x180b9e2c0,0x180b9f540,0x12d8),('y',0x180b9ad40,0x180b9e280,0x180b9f570,0x12dc),('z',0x180b9ad80,0x180b9e2a0,0x180b9f5a0,0x12e0)]
pages=set()
for _,*addresses,off in callbacks:
 for address in addresses:
  page=address&~4095
  if page not in pages:uc.mem_map(page,4096);uc.mem_write(page,data[offset(page):offset(page)+4096]);pages.add(page)
def f(v):return struct.pack('<f',v)
def run(address):
 uc.mem_write(stack,struct.pack('<Q',stop));uc.reg_write(UC_X86_REG_RSP,stack)
 uc.reg_write(UC_X86_REG_RCX,ctx);uc.reg_write(UC_X86_REG_RDX,0);uc.reg_write(UC_X86_REG_R8,wire)
 uc.emu_start(address,stop,count=100)
 return uc.reg_read(UC_X86_REG_RAX)&0xffffffff
rows=[]
for axis,getter,setter,checked,off in callbacks:
 for base,value in [(3.,10.),(4.,-2.),(0.,0.),(-5.,1.),(16384.,16385.)]:
  uc.mem_write(ctx,bytes(64));uc.mem_write(ctx+0x10,struct.pack('<Q',entity));uc.mem_write(ctx+0x18,struct.pack('<Q',target))
  uc.mem_write(entity+off,f(base));uc.mem_write(target,f(value));uc.mem_write(wire,bytes(48))
  result=run(getter);actual=bytes(uc.mem_read(wire,4));assert actual==f(value-base) and result==1
  assert struct.unpack('<II',uc.mem_read(wire+0x28,8))==(1,3)
  rows.append({'axis':axis,'kind':'serialize-relative','base':base,'value':value,'output':struct.unpack('<f',actual)[0]})
 for callback,kind in [(setter,'unserialize'),(checked,'checked-unserialize')]:
  for incoming in [-100.,0.,12.5,999.]:
   uc.mem_write(ctx,bytes(64));uc.mem_write(ctx+8,struct.pack('<Q',entity));uc.mem_write(ctx+0x10,struct.pack('<Q',target))
   uc.mem_write(entity+off,f(25.));uc.mem_write(target,f(-777.));uc.mem_write(wire,f(incoming)+bytes(36)+struct.pack('<II',1,3))
   result=run(callback);assert bytes(uc.mem_read(target,4))==f(25.) and result==1
   rows.append({'axis':axis,'kind':kind,'incoming':incoming,'output':25.})
 for dimension,category in [(2,3),(1,2)]:
  uc.mem_write(target,f(-777.));uc.mem_write(wire+0x28,struct.pack('<II',dimension,category))
  result=run(checked);assert result==0 and bytes(uc.mem_read(target,4))==f(-777.)
  rows.append({'axis':axis,'kind':'checked-reject','dimension':dimension,'category':category,'target_unchanged':True})
result={'profile':'14191/10924','module':'client.dll','sha256':expected,'method':'Isolated exact callbacks with preallocated CPU memory; no hooks, OS imports, game launch or networking','checks':len(rows),'passed':len(rows),'conclusions':['Serialize callback emits field minus per-axis object base and declares float/category3 dimension1.','Both registered receive callback variants copy the corresponding object base to target; changing incoming scalar does not change that result.','The checked variant rejects non-float or non-scalar input without writing target.','These callback results describe network-to-object adaptation, not a complete fish animation/rendered-position model.'],'callbacks':[{'axis':a,'serialize':hex(g),'unserialize':hex(s),'checked_unserialize':hex(c),'base_offset':hex(o)} for a,g,s,c,o in callbacks],'cases':rows}
output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'checks':len(rows),'passed':len(rows)}))
