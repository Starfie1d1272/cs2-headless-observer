from pathlib import Path
src=Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0];exec(src)
from unicorn.x86_const import UC_X86_REG_RAX
rows=[]
for transient,persistent,key,expected in [([],[(11,2,1)],11,(2,1)), ([(11,3,1)],[(11,2,1)],11,(3,1)), ([(12,7,0)],[(11,2,1)],11,(2,1)), ([(11,0,0)],[(11,2,1)],11,(0,0)), ([],[],11,None)]:
 u.mem_write(scratch,b'\0'*0x6000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 helper=scratch;entity=scratch+0x100;old=scratch+0x200;vec=scratch+0x400;data=scratch+0x500
 u.mem_write(helper,struct.pack('<QQQ',entity,vec,0));u.mem_write(entity+16,struct.pack('<Q',old));u.mem_write(old,struct.pack('<II',2,len(persistent)))
 for i,r in enumerate(persistent):u.mem_write(old+8+i*12,struct.pack('<III',*r))
 u.mem_write(vec,struct.pack('<IIQ',len(transient),0,data))
 for i,r in enumerate(transient):u.mem_write(data+i*12,struct.pack('<III',*r))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,helper),(UC_X86_REG_RDX,key),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'transient':transient,'persistent':persistent,'key':key,'expected':expected}
 try:
  u.emu_start(0x180059190,stop,timeout=100000,count=100000)
  ptr=u.reg_read(UC_X86_REG_RAX);actual=tuple(struct.unpack('<III',u.mem_read(ptr,12))[1:]) if ptr else None
  row.update(actual=actual,passed=actual==expected and u.reg_read(UC_X86_REG_RIP)==stop)
 except UcError as e:row.update(passed=False,error=str(e))
 rows.append(row)
s={'manifest':'8766757721818354077','method':'isolated fixed networksystem metadata lookup; null optional external helper; no stubbed imports or OS execution','cases':len(rows),'passed':sum(r['passed'] for r in rows)}
Path('.agent-tmp/gotv-research-plan/metadata-lookup-emulation.json').write_text(json.dumps({'summary':s,'cases':rows},indent=2)+'\n');print(json.dumps(s));print(json.dumps(rows))
