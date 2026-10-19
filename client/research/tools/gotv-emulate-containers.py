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
cases=[('pointer',False,False,0,b'\0',1),('pointer',False,True,0,b'\1',1),('pointer',True,False,0,b'\0',1)]
for n in [1,2,3]:cases.append(('pointer',True,True,n,bytes([1|(n<<1)]),7))
for n in [0,1,127,128,16384,16385]:
 p=varuint(n);cases.append(('array',False,False,n,p,len(p)*8))
for kind,poly,present,value,payload,bits in cases:
 u.mem_write(scratch,b'\0'*0x3000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 ctx=scratch;state=scratch+0x100;reader=scratch+0x200;info=scratch+0x300;desc=scratch+0x400;types=scratch+0x600;table=scratch+0x700;current=scratch+0x900;out=scratch+0xa00;data=scratch+0x1000
 for off,val in [(0x10,info),(0x18,ctx),(0x20,reader),(0x38,types),(0x40,desc)]:u.mem_write(state+off,struct.pack('<Q',val))
 u.mem_write(types+0x18,struct.pack('<Q',table));u.mem_write(desc+0xd0,bytes([4|(64 if poly else 0)]))
 for i in range(3):u.mem_write(table+i*16,struct.pack('<Q',scratch+0x2000+i*64))
 u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',0))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,ctx),(UC_X86_REG_RDX,state),(UC_X86_REG_R8,current),(UC_X86_REG_R9,out),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'kind':kind,'polymorphic':poly,'present':present,'selector_or_length':value,'input_hex':payload.hex(),'expected_bits':bits}
 try:
  u.emu_start(0x18006cc90 if kind=='pointer' else 0x18006d9f0,stop,timeout=100000,count=100000)
  read=struct.unpack('<i',u.mem_read(reader+0x10,4))[0];overflow=u.mem_read(reader+0x20,1)[0];selected=struct.unpack('<Q',u.mem_read(out,8))[0]
  expected=scratch+0x2000+(value-1)*64 if kind=='pointer' and poly and present else 0
  row.update(actual_bits=read,overflow=overflow,selected_expected=selected==expected,passed=read==bits and not overflow and selected==expected and u.reg_read(UC_X86_REG_RIP)==stop)
 except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
 rows.append(row)
summary={'manifest':'8766757721818354077','method':'isolated fake-field native container readers, debug disabled; no allocation or OS callbacks','cases':len(rows),'passed':sum(x['passed']for x in rows)}
Path('.agent-tmp/gotv-research-plan/container-codec-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([x for x in rows if not x['passed']]))
