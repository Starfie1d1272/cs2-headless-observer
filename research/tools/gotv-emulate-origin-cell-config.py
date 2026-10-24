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
rows=[]
for bits,flags,low,high in [(15, flag, 0, float(1 << width)) for flag in [0,1,2] for width in [7,8,9,10,11,12]]:
 u.mem_write(scratch,b'\0'*0x3000);u.mem_write(stack+0xe000,b'\0'*0x2000)
 meta=scratch;config=scratch+0x400;name=scratch+0x800;u.mem_write(name,b'probe\0');u.mem_write(meta+8,struct.pack('<Q',name));u.mem_write(meta+0xf0,struct.pack('<II',bits,flags));u.mem_write(meta+0xfc,struct.pack('<ff',low,high))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,meta),(UC_X86_REG_RDX,0),(UC_X86_REG_R8,config),(UC_X86_REG_R9,0),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'bits':bits,'flags':flags,'low':low,'high':high}
 try:
  u.emu_start(0x1800d1250,stop,timeout=100000,count=100000)
  data=bytes(u.mem_read(config,48));row.update(config_hex=data.hex(),configured_low=struct.unpack_from('<f',data)[0],configured_high=struct.unpack_from('<f',data,4)[0],dec_mul=struct.unpack_from('<d',data,16)[0],effective_bits=data[28],effective_flags=data[29]>>4,raw=bool(data[30]&1),completed=u.reg_read(UC_X86_REG_RIP)==stop)
 except UcError as e:
  rip=u.reg_read(UC_X86_REG_RIP)
  row.update(error=str(e),rip=hex(rip),expected_native_fatal=(rip==0x26d8b0 and 1<=bits<=31 and high<=low),fatal_import='tier0.dll!Plat_FatalError' if rip==0x26d8b0 else None)
 rows.append(row)
Path('.agent-tmp/gotv-research-plan/origin-cell-native-configurations.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps({'cases':len(rows),'completed':sum(r.get('completed',False)for r in rows),'errors':sum('error'in r for r in rows)}))
