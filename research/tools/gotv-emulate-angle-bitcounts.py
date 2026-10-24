from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
rows=[]
for name,address,dim in [('qangle',0x1800d2950,3),('qangle_precise',0x1800d3d90,3),('qangle_pitch_yaw',0x1800d4640,2)]:
 for width in [1,8,16,20,31,32]:
  for raw in [0,1,(1<<width)//2,(1<<width)-2,(1<<width)-1]:
   u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
   reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;profile=scratch+0x600;data=scratch+0x1000
   bits=width*dim;packed=sum(raw<<(width*i)for i in range(dim));payload=packed.to_bytes((bits+7)//8,'little')
   u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0));u.mem_write(config,struct.pack('<I',width))
   if width==32 and name!='qangle_precise':value=struct.unpack('<f',struct.pack('<I',raw))[0]
   else:value=f32((raw if raw<0x80000000 else raw-(1<<32))*(360.0/(1<<(width&31))))
   expected=[value]*dim+([0.0]if dim==2 else [])
   rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
   for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,profile),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
   row={'encoder':name,'bitcount':width,'raw':raw,'expected_bits':bits}
   try:
    u.emu_start(address,stop,timeout=100000,count=100000)
    actual=bytes(u.mem_read(out,12));exp=struct.pack('<fff',*expected);read=struct.unpack('<i',u.mem_read(reader+16,4))[0];overflow=u.mem_read(reader+32,1)[0]
    row.update(expected_hex=exp.hex(),actual_hex=actual.hex(),actual_bits=read,overflow=overflow,passed=actual==exp and read==bits and not overflow and u.reg_read(UC_X86_REG_RIP)==stop)
   except UcError as e:row.update(passed=False,error=str(e))
   rows.append(row)
summary={'manifest':'8766757721818354077','method':'isolated fixed-build angle decoder dispatch; exact output bits and consumption; no OS/network execution','cases':len(rows),'passed':sum(x['passed']for x in rows),'scope':'config bitcounts 1,8,16,20,31,32; config32 precise records native shift-masked behavior, not a universal stream compatibility assumption'}
Path('.agent-tmp/gotv-research-plan/angle-bitcount-emulation.json').write_text(json.dumps({'summary':summary,'cases':rows},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([x for x in rows if not x['passed']][:12]))
