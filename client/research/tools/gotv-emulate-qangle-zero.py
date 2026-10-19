from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
import math

def pack(parts):
 bits=sum(n for v,n in parts); value=0; offset=0
 for v,n in parts: value|=v<<offset;offset+=n
 return value.to_bytes((bits+7)//8,'little'),bits

def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
rows=[];cases=[]
for ib,fb in [(10,4),(14,5)]:
 for presence in range(8):
  for mask in range(4):
   for sign in range(2):
    for raw in [0,1,(1<<ib)-1]:
     parts=[(presence,3)];expected=[]
     for axis in range(3):
      if not presence>>axis&1:
       expected.append(0.0);continue
      parts += [(mask&1,1),(mask>>1,1)]
      val=0
      if mask:
       parts.append((sign,1))
       if mask&1:parts.append((raw,ib));val=raw+1
       if mask&2:parts.append(((1<<fb)-1,fb));val+=((1<<fb)-1)/(1<<fb)
      expected.append(-val if sign and mask else val)
     cases.append(('qangle_zero',ib,parts,expected,fb))
for kind,width,parts,expected,configbits in cases:
 u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;profile=scratch+0x600;data=scratch+0x1000
 payload,bits=pack(parts);u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0))
 u.mem_write(desc+0x26,struct.pack('<H',len(expected)<<12|3<<7));u.mem_write(profile,struct.pack('<II',width,configbits));u.mem_write(profile+0xc,struct.pack('<f',1/(1<<configbits)));u.mem_write(profile+0x20,struct.pack('<I',width));u.mem_write(profile+0x28,struct.pack('<f',1/((1<<width)-1)));u.mem_write(profile+0x2c,struct.pack('<I',width));u.mem_write(profile+0x40,struct.pack('<d',360/(1<<width)))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,profile),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'kind':kind,'width':width,'input_hex':payload.hex(),'expected':expected,'expected_bits':bits}
 try:
  u.emu_start(0x1800d2950,stop,timeout=100000,count=100000)
  actual=list(struct.unpack('<'+'f'*len(expected),u.mem_read(out,4*len(expected))));read=struct.unpack('<i',u.mem_read(reader+0x10,4))[0];overflow=u.mem_read(reader+0x20,1)[0]
  row.update(actual=actual,actual_bits=read,overflow=overflow,passed=actual==expected and read==bits and not overflow and u.reg_read(UC_X86_REG_RIP)==stop)
 except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
 rows.append(row)
summary={'manifest':'8766757721818354077','method':'isolated native qangle bitcount0, all presence masks and coordinate profiles; no OS imports or network','cases':len(rows),'passed':sum(x['passed']for x in rows)}
Path('.agent-tmp/gotv-research-plan/qangle-zero-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([x for x in rows if not x['passed']][:5]))
