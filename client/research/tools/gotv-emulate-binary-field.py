"""Native category6 decoding with preallocated output; no allocator hooks."""
from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-scalars.py').read_text().split('rows=[]')[0])
rows=[]
for length in (0,1,2,7,31,127,128,257,1024):
 for alignment in range(8):
  payload=bytes((i*37+11)&255 for i in range(length));wire=varuint(length)+payload
  raw=bytearray((alignment+len(wire)*8+7)//8)
  for i,v in enumerate(wire):
   for bit in range(8):raw[(alignment+i*8+bit)//8]|=((v>>bit)&1)<<((alignment+i*8+bit)%8)
  u.mem_write(scratch,b'\0'*0x9000);u.mem_write(stack+0xf000,b'\0'*0x1000)
  reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;vector=scratch+0x500;buffer=scratch+0x2000;data=scratch+0x5000
  u.mem_write(data,bytes(raw)+b'\0'*32);u.mem_write(reader,struct.pack('<Qiii',data,len(raw),alignment+len(wire)*8,alignment))
  u.mem_write(desc+0x26,struct.pack('<H',6<<7))
  u.mem_write(vector,struct.pack('<IIQ',2048,2048,buffer));u.mem_write(out+32,struct.pack('<Q',vector))
  rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
  for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
  row={'length':length,'alignment':alignment,'dimensions':0,'input_sha256':hashlib.sha256(wire).hexdigest(),'expected_bits':len(wire)*8}
  try:
   u.emu_start(base+0xdcd80,stop,timeout=1000000,count=100000)
   ptr=struct.unpack('<Q',u.mem_read(out,8))[0];actual=bytes(u.mem_read(ptr,length));n,category=struct.unpack('<II',u.mem_read(out+40,8));read=struct.unpack('<i',u.mem_read(reader+16,4))[0]-alignment;overflow=u.mem_read(reader+32,1)[0]
   row.update(actual_sha256=hashlib.sha256(actual).hexdigest(),actual_length=n,category=category,bits=read,overflow=overflow,passed=u.reg_read(UC_X86_REG_RIP)==stop and actual==payload and n==length and category==6 and read==len(wire)*8 and not overflow)
  except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
  rows.append(row)
result={'manifest':'8766757721818354077','module_sha256':hashlib.sha256(b).hexdigest(),'method':'Fixed native0dcd80 with native varint/bit-copy callees, dimension0, preallocated scratch output; no imports or allocation hooks','summary':{'cases':len(rows),'passed':sum(r['passed']for r in rows)},'cases':rows}
Path('.agent-tmp/gotv-research-plan/binary-field-emulation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary']));print(json.dumps([r for r in rows if not r['passed']]))
assert all(r['passed']for r in rows)
