from pathlib import Path
import struct,json,collections,time
from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UcError
from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_RSP,UC_X86_REG_RIP,UC_X86_REG_EFLAGS,UC_X86_REG_R8,UC_X86_REG_R9
b=Path('.agent-tmp/gotv-tools/cs2/game/bin/win64/networksystem.dll').read_bytes();pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;base=struct.unpack_from('<Q',b,opt+24)[0];size=struct.unpack_from('<I',b,opt+56)[0];sec=opt+struct.unpack_from('<H',b,pe+20)[0]
u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(base,(size+4095)&~4095);u.mem_write(base,b[:struct.unpack_from('<I',b,opt+60)[0]])
for i in range(struct.unpack_from('<H',b,pe+6)[0]):
 vs,va,sz,raw=struct.unpack_from('<IIII',b,sec+40*i+8)
 if sz:u.mem_write(base+va,b[raw:raw+sz])
scratch=0x10000000;stack=0x20000000;stop=0x30000000;u.mem_map(scratch,0x10000);u.mem_map(stack,0x10000);u.mem_map(stop,0x1000)
def varuint(n):
 out=bytearray()
 while n>=128:out.append((n&127)|128);n>>=7
 out.append(n);return bytes(out)
rows=[]
for c in json.load(open('.agent-tmp/gotv-research-plan/encoder-family-catalog.json')):
 if c['category']not in [1,2,4,7]:continue
 widths={'fixed8':8,'fixed32':32,'fixed64':64}
 if c['category'] in [1,2]:
  if c['name']in widths:
   bits=widths[c['name']]
   cases=[(v.to_bytes(bits//8,'little'),((v-(1<<bits))&((1<<64)-1))if c['category']==1 and v>=(1<<(bits-1))else v,bits)for v in [0,1,(1<<(bits-1))-1,1<<(bits-1),(1<<bits)-1]]
  else:
   cases=[]
   for v in [0,1,127,128,65535,(1<<32)-1,(1<<63)-1,1<<63,(1<<64)-1]:
    logical=((v>>1)^-(v&1))&((1<<64)-1)if c['category']==1 else v
    payload=varuint(v);cases.append((payload,logical,len(payload)*8))
 elif c['category']==7:cases=[(bytes([v]),v,1)for v in [0,1]]
 else:cases=[(struct.pack('<f',v),struct.unpack('<Q',struct.pack('<d',v))[0],32)for v in [0.0,1.0,-1.0,0.5,65536.0]]
 for payload,expected,bits in cases:
  u.mem_write(scratch,b'\0'*0x2000);u.mem_write(stack+0xf000,b'\0'*0x1000)
  reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;data=scratch+0x1000
  u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0));u.mem_write(desc+0x26,struct.pack('<H',0x1000|(c['category']<<7)))
  rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
  for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
  row={'category':c['category'],'encoder':c['name'],'input_hex':payload.hex(),'expected_raw_u64':str(expected),'expected_bits':bits}
  try:
   u.emu_start(int(c['decode'],16),stop,timeout=100000,count=100000)
   actual=struct.unpack('<Q',u.mem_read(out,8))[0];read=struct.unpack('<i',u.mem_read(reader+0x10,4))[0];overflow=u.mem_read(reader+0x20,1)[0]
   row.update(actual_raw_u64=str(actual),actual_bits=read,overflow=overflow,passed=actual==expected and read==bits and not overflow and u.reg_read(UC_X86_REG_RIP)==stop)
  except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
  rows.append(row)
summary={'method':'isolated native x86-64 function emulation','manifest':'8766757721818354077','cases':len(rows),'passed':sum(r['passed']for r in rows),'failed':sum(not r['passed']for r in rows)}
Path('.agent-tmp/gotv-research-plan/scalar-codec-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([x for x in rows if not x['passed']]))
