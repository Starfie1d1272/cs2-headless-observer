from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
import math

def pack(parts):
 bits=sum(n for v,n in parts); value=0; offset=0
 for v,n in parts: value|=v<<offset;offset+=n
 return value.to_bytes((bits+7)//8,'little'),bits

def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
rows=[];cases=[]
for dim in [6,8]:
 for ib,fb,mp in [(10,4,8),(14,5,11)]:
  for compact in [0,1]:
   for integral_present in [0,1]:
    for present in range(8):
     for mask in range(4):
      for sign in range(2):
       parts=[];expected=[]
       for axis in range(3):
        parts += [(compact,1),(integral_present,1)]
        width=mp if compact else ib
        value=(1<<width)-axis if integral_present else 0
        if integral_present:parts += [(sign,1),(value-1,width)]
        expected.append(-value if sign else value)
       parts.append((present,3))
       for axis in range(3):
        if not(present>>axis&1):expected.append(0);continue
        parts += [(mask&1,1),(mask>>1,1)]
        value=0
        if mask:
         parts.append((sign,1))
         if mask&1:parts.append((axis,ib));value=axis+1
         if mask&2:parts.append(((1<<fb)-1,fb));value+=((1<<fb)-1)/(1<<fb)
        expected.append(-value if sign and mask else value)
       cases.append(('integral_coordinate_aggregate',ib,parts,expected,fb,mp,dim))
for kind,width,parts,expected,configbits,mp,dim in cases:
 u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;profile=scratch+0x600;data=scratch+0x1000
 payload,bits=pack(parts);u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0))
 u.mem_write(desc+0x26,struct.pack('<H',dim<<12|3<<7));u.mem_write(profile,struct.pack('<II',width,configbits));u.mem_write(profile+0xc,struct.pack('<f',1/(1<<configbits)));u.mem_write(profile+0x10,struct.pack('<I',mp));u.mem_write(profile+0x20,struct.pack('<I',width));u.mem_write(profile+0x28,struct.pack('<f',1/((1<<width)-1)));u.mem_write(profile+0x2c,struct.pack('<I',width));u.mem_write(profile+0x40,struct.pack('<d',360/(1<<width)))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,profile),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'kind':kind,'width':width,'fraction_bits':configbits,'compact_bits':mp,'dimension':dim,'input_hex':payload.hex(),'expected':expected,'expected_bits':bits}
 try:
  endpoint=stop if dim==6 else 0x1801b65e0
  u.emu_start(0x1800da4f0,endpoint,timeout=100000,count=100000)
  actual=list(struct.unpack('<6f',u.mem_read(out,24))) if dim==6 else list(struct.unpack('<fff',u.mem_read(u.reg_read(UC_X86_REG_RDX),12)))+list(struct.unpack('<fff',u.mem_read(u.reg_read(UC_X86_REG_RCX),12)));read=struct.unpack('<i',u.mem_read(reader+0x10,4))[0];overflow=u.mem_read(reader+0x20,1)[0]
  row.update(actual=actual,actual_bits=read,overflow=overflow,passed=actual==expected and read==bits and not overflow and u.reg_read(UC_X86_REG_RIP)==endpoint)
 except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
 rows.append(row)
summary={'manifest':'8766757721818354077','method':'isolated fixed-build integral coord dimensions6/8: first triple integral, second triple presence-conditioned fractional coord; dimension8 stops before matrix conversion','cases':len(rows),'passed':sum(x['passed']for x in rows)}
Path('.agent-tmp/gotv-research-plan/integral-coordinate-aggregate-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([x for x in rows if not x['passed']][:5]))
