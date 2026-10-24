from pathlib import Path
import struct,json,collections,time,hashlib
from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UcError
from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_RSP,UC_X86_REG_RIP,UC_X86_REG_EFLAGS,UC_X86_REG_R8,UC_X86_REG_R9
b=Path('.agent-tmp/gotv-tools/cs2/game/bin/win64/networksystem.dll').read_bytes()
assert hashlib.sha256(b).hexdigest() == 'be7e13ad771b21c986e25d9469993a1225be5649473f3d722ca5eefe375d1bec', 'fixed-module-sha-mismatch'
pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;base=struct.unpack_from('<Q',b,opt+24)[0];size=struct.unpack_from('<I',b,opt+56)[0];sec=opt+struct.unpack_from('<H',b,pe+20)[0]
u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(base,(size+4095)&~4095);u.mem_write(base,b[:struct.unpack_from('<I',b,opt+60)[0]])
for i in range(struct.unpack_from('<H',b,pe+6)[0]):
 vs,va,sz,raw=struct.unpack_from('<IIII',b,sec+40*i+8)
 if sz:u.mem_write(base+va,b[raw:raw+sz])
scratch=0x10000000;stack=0x20000000;stop=0x30000000;u.mem_map(scratch,0x10000);u.mem_map(stack,0x10000);u.mem_map(stop,0x1000)
def varuint(n):
 out=bytearray()
 while n>=128:out.append((n&127)|128);n>>=7
 out.append(n);return bytes(out)
rows=[];cases=[]
for dim in [1,2,3,4,6,8]:
 for values in [[0.0]*dim,[float(i)-2.5 for i in range(dim)],[65536.0/(i+1)for i in range(dim)]]:
  data=struct.pack('<'+'f'*dim,*values);cases.append(('float_raw',dim,data,data,len(data)*8,0))
for value in [0,1,127,128,254,255]:
 expected=struct.pack('<f',value/255);cases.append(('float_quant8',1,bytes([value]),expected,8,0))
for value in [b'',b'a',b'hello',bytes.fromhex('e4b8ade69687')]:cases.append(('string',1,value+b'\0',value+b'\0',(len(value)+1)*8,0))
for value in [b'',b'\0',b'abc',bytes(range(128))]:
 payload=varuint(len(value))+value;cases.append(('binary',len(value),payload,value,len(payload)*8,0))
for kind,dim,payload,expected,bits,_ in cases:
 u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;buf=scratch+0x500;bufdata=scratch+0x2000;data=scratch+0x1000
 category=3 if kind.startswith('float') else 5 if kind=='string' else 6
 u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0));u.mem_write(desc+0x26,struct.pack('<H',(dim if category==3 else 1)<<12|category<<7))
 u.mem_write(out+0x20,struct.pack('<Q',buf));u.mem_write(buf,struct.pack('<IIQ',0,1024,bufdata))
 if kind=='float_raw':u.mem_write(config+0x1e,b'\1')
 if kind=='float_quant8':u.mem_write(config,struct.pack('<ff',0,1));u.mem_write(config+0x10,struct.pack('<d',1/255));u.mem_write(config+0x1c,b'\x08')
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'kind':kind,'dimensions_or_length':dim,'input_hex':payload.hex(),'expected_hex':expected.hex(),'expected_bits':bits}
 try:
  address=0x1800d1520 if category==3 else 0x1800d11f0 if category==5 else 0x1800dcd80
  u.emu_start(address,stop,timeout=100000,count=100000)
  actual=bytes(u.mem_read(out if category==3 else bufdata,len(expected)));read=struct.unpack('<i',u.mem_read(reader+0x10,4))[0];overflow=u.mem_read(reader+0x20,1)[0]
  row.update(actual_hex=actual.hex(),actual_bits=read,overflow=overflow,passed=actual==expected and read==bits and not overflow and u.reg_read(UC_X86_REG_RIP)==stop)
 except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
 rows.append(row)
summary={'manifest':'8766757721818354077','method':'isolated default float-family, configured quant8, string and binary native decoders; preallocated buffer, no OS allocator','cases':len(rows),'passed':sum(x['passed']for x in rows)}
Path('.agent-tmp/gotv-research-plan/aggregate-codec-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([x for x in rows if not x['passed']]))
