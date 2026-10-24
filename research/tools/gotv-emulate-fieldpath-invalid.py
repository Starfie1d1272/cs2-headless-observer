"""Probe failure boundaries without loading the DLL or making network calls."""
from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-fieldpath-depths.py').read_text().split('ops=json.load')[0])
ops=json.load(open('.agent-tmp/gotv-research-plan/field-path-opcodes.json'))
def bits(value,n):return [(value>>i)&1 for i in range(n)]
def payload(values):
 out=bytearray((len(values)+7)//8)
 for i,v in enumerate(values):out[i//8]|=v<<(i%8)
 return bytes(out)
cases=[]
for op in (27,28,37):cases.append((f'underflow-op{op}',op,[0],[],0))
for op in (0,1,2,3):
 for initial in (32766,32767):cases.append((f'component-{initial}-op{op}',op,[initial],[],0))
for raw in (bytes.fromhex('00'),bytes.fromhex('7f'),bytes.fromhex('8000'),bytes.fromhex('ffffffff0f'),bytes.fromhex('ffffffff7f'),bytes.fromhex('8080808080'),bytes.fromhex('808080808000')):
 wire=[1]+[v for b in raw for v in bits(b,8)]
 cases.append(('signed-varint-'+raw.hex(),36,[10],wire,len(wire)))
for n in (0,1,2,7,8,9,16,32):cases.append((f'truncated-varint-{n}',36,[10],[1]+bits(0xffffffff,32),n))
rows=[]
for name,op,initial,wire,bitlimit in cases:
 u.mem_write(scratch,b'\0'*0x2000);u.mem_write(stack+0xf000,b'\0'*0x1000)
 p=scratch+0x40;r=scratch+0x100;data=scratch+0x1000
 u.mem_write(p,struct.pack('<'+'h'*len(initial),*initial));u.mem_write(p+0x18,struct.pack('<h',len(initial)))
 u.mem_write(data,payload(wire)+b'\0'*64);u.mem_write(r,struct.pack('<Qiii',data,64,bitlimit,0))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,p),(UC_X86_REG_RDX,r),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'name':name,'opcode':op,'initial':initial,'input_hex':payload(wire).hex(),'valid_bits':bitlimit}
 try:
  u.emu_start(int(ops[op]['decode'],16),stop,timeout=1000000,count=100000)
  row['returned']=u.reg_read(UC_X86_REG_RIP)==stop
 except UcError as e:row['error']=str(e)
 n=struct.unpack('<h',u.mem_read(p+0x18,2))[0]
 row.update(rip=hex(u.reg_read(UC_X86_REG_RIP)),depth=n,path=list(struct.unpack('<'+'h'*max(0,min(12,n)),u.mem_read(p,max(0,min(12,n))*2))),bits=struct.unpack('<i',u.mem_read(r+0x10,4))[0],overflow=u.mem_read(r+0x20,1)[0])
 rows.append(row)
result={'manifest':'8766757721818354077','module_sha256':hashlib.sha256(b).hexdigest(),'method':'Isolated fixed-function Unicorn emulation; no OS imports, SDK, network or DLL loading; malformed input observations are not a requirement to emulate unsafe behavior','rows':rows}
Path('.agent-tmp/gotv-research-plan/field-path-invalid-probe.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
