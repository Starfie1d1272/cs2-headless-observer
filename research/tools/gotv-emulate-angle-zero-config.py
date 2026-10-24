from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
from unicorn.x86_const import UC_X86_REG_RAX
rows=[]
for present in [0,1]:
 for width in [0,1,8,31,32,33,0xffffffff]:
  u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
  field=scratch;out=scratch+0x400;rsp=stack+0xff08
  u.mem_write(field+0xf0,struct.pack('<I',width));u.mem_write(field+0x108,bytes([present]));u.mem_write(rsp,struct.pack('<Q',stop))
  for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,field),(UC_X86_REG_RDX,0),(UC_X86_REG_R8,out),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
  u.emu_start(0x1800d1f00,stop,timeout=100000,count=100000)
  value=struct.unpack('<I',u.mem_read(out,4))[0];accepted=u.reg_read(UC_X86_REG_RAX)&255
  rows.append({'kind':'angle_config','present':present,'input_width':width,'actual_config':value,'accepted':accepted,'passed':value==(width if present and width<=32 else 0) and accepted==int(width<=32)})
for config_width in [0,32]:
 for left,right in [(0,0),(0x80000000,0x3f800000),(0xc2340000,0x43340000),(0x3f000000,0xbf800000),(0x7f7fffff,0xff7fffff)]:
  u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
  reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;data=scratch+0x1000;rsp=stack+0xff08
  payload=struct.pack('<II',left,right);u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,8,64,0));u.mem_write(config,struct.pack('<I',config_width));u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
  for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
  u.emu_start(0x1800d4640,stop,timeout=100000,count=100000)
  actual=bytes(u.mem_read(out,12));bits=struct.unpack('<i',u.mem_read(reader+16,4))[0];overflow=u.mem_read(reader+32,1)[0]
  rows.append({'kind':'pitch_yaw','config_width':config_width,'input_hex':payload.hex(),'actual_hex':actual.hex(),'actual_bits':bits,'overflow':overflow,'passed':actual==payload+b'\0'*4 and bits==64 and not overflow})
summary={'manifest':'8766757721818354077','cases':len(rows),'passed':sum(r['passed'] for r in rows),'method':'fixed-hash isolated angle config constructor and pitch/yaw native zero/32 branches, no OS imports'}
Path('.agent-tmp/gotv-research-plan/angle-zero-config-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([r for r in rows if not r['passed']]))
assert all(r['passed'] for r in rows)
