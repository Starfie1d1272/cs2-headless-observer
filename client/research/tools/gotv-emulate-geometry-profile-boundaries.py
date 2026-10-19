from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
import math

def pack(parts):
 bits=sum(n for v,n in parts); value=0; offset=0
 for v,n in parts: value|=v<<offset;offset+=n
 return value.to_bytes((bits+7)//8,'little'),bits

def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
rows=[];cases=[]
for width in range(1,32):
 for mask in range(4):
  for sign in range(8):
   for mag in [0,1,(1<<width)//2,(1<<width)-1]:
    parts=[(mask&1,1),(mask>>1,1)]; vals=[]
    for axis in range(2):
     if mask>>axis&1:parts += [(sign>>axis&1,1),(mag,width)];v=f32(mag*f32(1/((1<<width)-1)));vals.append(-v if sign>>axis&1 else v)
     else:vals.append(0.0)
    parts.append((sign>>2&1,1));s=f32(f32(vals[0]*vals[0])+f32(vals[1]*vals[1]));z=f32(math.sqrt(f32(1-s))) if s<1 else 0.0;vals.append(-z if sign>>2&1 else z)
    cases.append(('normal',width,parts,vals,0))
for width in range(1,32):
 for mask in range(8):
  for raw in [0,1,1<<(width-1),(1<<width)-1]:
   parts=[(mask,3)];vals=[]
   for axis in range(3):
    if mask>>axis&1:parts.append((raw,width));vals.append(f32(f32(raw*360/(1<<width))-180))
    else:vals.append(0.0)
   cases.append(('precise',width,parts,vals,0))
for kind,width,parts,expected,configbits in cases:
 u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;profile=scratch+0x600;data=scratch+0x1000
 payload,bits=pack(parts);u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0))
 u.mem_write(profile+0x20,struct.pack('<I',width));u.mem_write(profile+0x28,struct.pack('<f',1/((1<<width)-1)));u.mem_write(profile+0x2c,struct.pack('<I',width));u.mem_write(profile+0x40,struct.pack('<d',360/(1<<width)))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,profile),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'kind':kind,'width':width,'input_hex':payload.hex(),'expected':expected,'expected_bits':bits}
 try:
  u.emu_start(0x1800d1930 if kind=='normal' else 0x1800d3d90,stop,timeout=100000,count=100000)
  actual=list(struct.unpack('<fff',u.mem_read(out,12)));read=struct.unpack('<i',u.mem_read(reader+0x10,4))[0];overflow=u.mem_read(reader+0x20,1)[0]
  row.update(actual=actual,actual_bits=read,overflow=overflow,passed=actual==expected and read==bits and not overflow and u.reg_read(UC_X86_REG_RIP)==stop)
 except UcError as e:row.update(passed=False,error=str(e),rip=hex(u.reg_read(UC_X86_REG_RIP)))
 rows.append(row)
summary={'manifest':'8766757721818354077','method':'isolated native normal vector and presence-conditioned precise angle decoders, configured profiles; no OS imports or network','cases':len(rows),'passed':sum(x['passed']for x in rows)}
summary['scope']='all permitted normal/precise profile widths1..31, masks/signs and boundary magnitudes'
summary['cases_sha256']=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
Path('.agent-tmp/gotv-research-plan/geometry-profile-boundary-emulation.json').write_text(json.dumps({'summary':summary,'failures':[r for r in rows if not r['passed']]},indent=2)+'\n');print(json.dumps(summary));print(json.dumps([x for x in rows if not x['passed']][:5]))
