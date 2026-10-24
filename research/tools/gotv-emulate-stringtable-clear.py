from pathlib import Path
src=Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0].replace('networksystem.dll','engine2.dll').replace('be7e13ad771b21c986e25d9469993a1225be5649473f3d722ca5eefe375d1bec','6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21');exec(src)
from unicorn.x86_const import UC_X86_REG_RAX
rows=[]
for old_size in [0,1,16,128]:
 u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 item=scratch;request=scratch+0x200;name=scratch+0x400
 u.mem_write(item+0x10,struct.pack('<I',old_size));u.mem_write(item+0x18,struct.pack('<Q',scratch+0x1000));u.mem_write(item+0x24,struct.pack('<I',0xc0000000));u.mem_write(request,struct.pack('<QI',0,0));u.mem_write(name,b'fixture\0')
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,b'\0')
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,item),(UC_X86_REG_RDX,name),(UC_X86_REG_R8,123),(UC_X86_REG_R9,request),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'prior_size':old_size}
 try:
  u.emu_start(0x180110450,stop,timeout=100000,count=100000)
  size=struct.unpack('<I',u.mem_read(item+16,4))[0];changed=u.reg_read(UC_X86_REG_RAX)&255;tick=struct.unpack('<I',u.mem_read(item+8,4))[0]
  row.update(size=size,changed=changed,tick=tick,passed=size==0 and changed==int(old_size>0) and tick==(123 if old_size else 0) and u.reg_read(UC_X86_REG_RIP)==stop)
 except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
 rows.append(row)
s={'manifest':'8766757721818354077','method':'isolated engine2 SetUserData empty-request cases; external-backed storage flags suppress allocator release; no imports stubbed/no OS execution','cases':len(rows),'passed':sum(r['passed']for r in rows)}
Path('.agent-tmp/gotv-research-plan/stringtable-clear-emulation.json').write_text(json.dumps({'summary':s,'cases':rows},indent=2)+'\n');print(json.dumps(s));print(json.dumps(rows))
