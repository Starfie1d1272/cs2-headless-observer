"""Exercise the real whole-list reader at its sentinel/failure return boundary.

Supply a two-leaf synthetic Huffman lookup to isolate dispatch termination.
This does not test the real Huffman table's codeword assignment.
"""
from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-fieldpath-depths.py').read_text().split('ops=json.load')[0])
from unicorn.x86_const import UC_X86_REG_R8,UC_X86_REG_R9,UC_X86_REG_RAX
def packed(v):
 out=bytearray((len(v)+7)//8)
 for i,b in enumerate(v):out[i//8]|=b<<(i%8)
 return bytes(out)
cases=[('finish-opcode',39,[0]),('plusN-reaches-root-sentinel',4,[0,0,0,0,1]+[(32763>>i)&1 for i in range(17)]),('truncated-plusN',4,[0,0])]
rows=[]
for name,op,wire in cases:
 u.mem_write(scratch,b'\0'*0x3000);u.mem_write(stack+0xe000,b'\0'*0x2000)
 r=scratch+0x100;out=scratch+0x200;tree=scratch+0x300;data=scratch+0x1000
 u.mem_write(base+0x2a6240,struct.pack('<Q',tree));u.mem_write(tree,bytes([(~op)&255]*2))
 u.mem_write(data,packed(wire)+b'\0'*64);u.mem_write(r,struct.pack('<Qiii',data,64,len(wire),0))
 rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,r),(UC_X86_REG_R8,out),(UC_X86_REG_R9,0),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'name':name,'opcode':op,'input_hex':packed(wire).hex(),'valid_bits':len(wire)}
 try:
  u.emu_start(base+0x10eba0,stop,timeout=1000000,count=100000)
  row['returned']=u.reg_read(UC_X86_REG_RIP)==stop
 except UcError as e:row['error']=str(e)
 row.update(rip=hex(u.reg_read(UC_X86_REG_RIP)),success=u.reg_read(UC_X86_REG_RAX)&255,fields=struct.unpack('<i',u.mem_read(out,4))[0],bits=struct.unpack('<i',u.mem_read(r+16,4))[0],overflow=u.mem_read(r+32,1)[0]);rows.append(row)
result={'manifest':'8766757721818354077','module_sha256':hashlib.sha256(b).hexdigest(),'method':'Whole-list native function10eba0 plus native opcode handlers, isolated Unicorn; synthetic two-leaf lookup isolates dispatch, no imported callbacks','rows':rows}
Path('.agent-tmp/gotv-research-plan/field-path-termination-probe.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
assert all(x.get('returned') and x['fields']==0 for x in rows)
assert [x['success'] for x in rows]==[1,1,0]
assert [x['overflow'] for x in rows]==[0,0,1]
