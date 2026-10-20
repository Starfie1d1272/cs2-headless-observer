from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
from unicorn.x86_const import UC_X86_REG_RAX
rows=[]
for mode in [0,1]:
 for bank in [0,1]:
  u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
  ctx=scratch;info=scratch+0x100;field=scratch+0x400;accessors=scratch+0x600;rsp=stack+0xff08
  u.mem_write(ctx+0x28,struct.pack('<I',mode));u.mem_write(info+0x14a,b'\1');u.mem_write(field+0x30,struct.pack('<Q',accessors))
  source=0x1802910a0+(mode+bank*2)*16;u.mem_write(accessors+bank*16,bytes(u.mem_read(source,16)));u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<I',bank))
  for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,ctx),(UC_X86_REG_RDX,info),(UC_X86_REG_R8,0),(UC_X86_REG_R9,field),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
  u.emu_start(0x1800ebd90,stop,timeout=1000000,count=100000)
  result=u.reg_read(UC_X86_REG_RAX);array=struct.unpack('<Q',u.mem_read(field+0x28,8))[0]
  rows.append({'kind':'char_array_atomic_accessor','mode':mode,'bank':bank,'array_serializer':result,'field_array_callbacks':array,'passed':result==0 and array==0 and u.reg_read(UC_X86_REG_RIP)==stop})
for address in [0x1800eb0f0,0x1800eb150]:
 for count in [0,1,6,128,65535]:
  for encoded in [0,1]:
   for incoming in [count,(count+1)&65535]:
    u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
    ctx=scratch;field=scratch+0x100;reader=scratch+0x200;out=scratch+0x400;data=scratch+0x1000;rsp=stack+0xff08;payload=varuint(incoming)
    u.mem_write(ctx,struct.pack('<Q',field));u.mem_write(field+0x22,struct.pack('<H',count));u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),len(payload)*8,0));u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,bytes([encoded]))
    for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,ctx),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,out),(UC_X86_REG_R9,0),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
    u.emu_start(address,stop,timeout=1000000,count=100000)
    value=struct.unpack('<I',u.mem_read(out,4))[0];read=struct.unpack('<i',u.mem_read(reader+16,4))[0];accepted=u.reg_read(UC_X86_REG_RAX)&255;expected=incoming if encoded else count
    rows.append({'kind':'fixed_array_length','function':hex(address),'declared':count,'encoded':bool(encoded),'input':incoming,'actual':value,'bits':read,'accepted':accepted,'passed':value==expected and read==(len(payload)*8 if encoded else 0) and accepted==(int(expected==count) if address==0x1800eb150 else 1) and u.reg_read(UC_X86_REG_RIP)==stop})
summary={'manifest':'8766757721818354077','cases':len(rows),'passed':sum(x['passed']for x in rows),'method':'native ordinary fixed-array readers and char-array atomic bypass; saved callback table, no allocator or OS imports'}
Path('.agent-tmp/gotv-research-plan/fixed-array-boundary-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([r for r in rows if not r['passed']]));assert all(r['passed']for r in rows)
