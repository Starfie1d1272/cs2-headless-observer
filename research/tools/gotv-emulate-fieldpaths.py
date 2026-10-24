from pathlib import Path
import struct,json,collections,time
from unicorn import Uc,UC_ARCH_X86,UC_MODE_64,UcError
from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_RSP,UC_X86_REG_RIP,UC_X86_REG_EFLAGS
b=Path('.agent-tmp/gotv-tools/cs2/game/bin/win64/networksystem.dll').read_bytes();pe=struct.unpack_from('<I',b,60)[0];opt=pe+24;base=struct.unpack_from('<Q',b,opt+24)[0];size=struct.unpack_from('<I',b,opt+56)[0];sec=opt+struct.unpack_from('<H',b,pe+20)[0]
u=Uc(UC_ARCH_X86,UC_MODE_64);u.mem_map(base,(size+4095)&~4095);u.mem_write(base,b[:struct.unpack_from('<I',b,opt+60)[0]])
for i in range(struct.unpack_from('<H',b,pe+6)[0]):
 vs,va,sz,raw=struct.unpack_from('<IIII',b,sec+40*i+8)
 if sz:u.mem_write(base+va,b[raw:raw+sz])
scratch=0x10000000;stack=0x20000000;stop=0x30000000;u.mem_map(scratch,0x10000);u.mem_map(stack,0x10000);u.mem_map(stop,0x1000)
ops=json.load(open('.agent-tmp/gotv-research-plan/field-path-opcodes.json'));cases=json.load(open('.agent-tmp/gotv-research-plan/field-path-model-cases.json'));results=[];started=time.monotonic()
for c in cases:
 u.mem_write(scratch,b'\0'*0x2000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 p=scratch;r=scratch+0x100;data=scratch+0x1000
 path=c['initial'];u.mem_write(p,struct.pack('<'+'h'*len(path),*path));u.mem_write(p+0x18,struct.pack('<h',len(path)))
 payload=bytes([c['first']])+b'\0'*63;u.mem_write(data,payload);u.mem_write(r,struct.pack('<Qiii',data,64,512,0))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.reg_write(UC_X86_REG_RSP,rsp);u.reg_write(UC_X86_REG_RCX,p);u.reg_write(UC_X86_REG_RDX,r);u.reg_write(UC_X86_REG_EFLAGS,2)
 result=dict(c)
 try:
  u.emu_start(int(ops[c['op']]['decode'],16),stop,timeout=100000,count=100000)
  if u.reg_read(UC_X86_REG_RIP)!=stop:raise RuntimeError('instruction/time budget exceeded')
  n=struct.unpack('<h',u.mem_read(p+0x18,2))[0];bits=struct.unpack('<i',u.mem_read(r+0x10,4))[0]
  actual=list(struct.unpack('<'+'h'*n,u.mem_read(p,n*2)))if 0<=n<=12 else None
  overflow=u.mem_read(r+0x20,1)[0];result.update(actual=actual,native_bits=bits,native_overflow=overflow)
  result['pass']=not overflow and bits==c['bits'] and (actual==c['expected'] if c['op']!=39 else actual==[32767])
 except (UcError,RuntimeError)as e:result.update(pass_=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
 results.append(result)
summary={'module':'networksystem.dll','manifest':'8766757721818354077','method':'Unicorn2.1.4 isolated x86-64 function emulation; no DLL loading, Steam, sockets or OS imports','cases':len(results),'passed':sum(x.get('pass',False)for x in results),'errors':sum('error'in x for x in results),'mismatches':sum('error'not in x and not x.get('pass',False)for x in results),'seconds':round(time.monotonic()-started,3),'opcode_counts':dict(collections.Counter(x['op']for x in results))}
Path('.agent-tmp/gotv-research-plan/field-path-emulation.json').write_text(json.dumps({'summary':summary,'nonpassing':[x for x in results if not x.get('pass',False)]},indent=2)+'\n');print(json.dumps(summary))
