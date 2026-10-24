from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-fieldpath-depths.py').read_text().split('ops=json.load')[0])
ops=json.load(open('.agent-tmp/gotv-research-plan/field-path-opcodes.json'));rows=[]
for op,depth in [(5,10),(7,10),(13,9),(15,8)]:
 u.mem_write(scratch,b'\0'*0x2000);u.mem_write(stack+0xf000,b'\0'*0x1000);p=scratch;r=scratch+0x100;data=scratch+0x1000
 u.mem_write(p,struct.pack('<'+'h'*depth,*range(depth)));u.mem_write(p+0x18,struct.pack('<h',depth));u.mem_write(data,b'\0'*64);u.mem_write(r,struct.pack('<Qiii',data,64,512,0));rsp=stack+0xff08;u.mem_write(rsp,struct.pack('<Q',stop))
 for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,p),(UC_X86_REG_RDX,r),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
 row={'opcode':op,'depth':depth,'function':ops[op]['decode']}
 try:u.emu_start(int(ops[op]['decode'],16),stop,timeout=1000000,count=100000);row['returned']=u.reg_read(UC_X86_REG_RIP)==stop
 except UcError as e:row['error']=str(e)
 row.update(rip=hex(u.reg_read(UC_X86_REG_RIP)),result_depth=struct.unpack('<h',u.mem_read(p+0x18,2))[0],overflow=u.mem_read(r+0x20,1)[0]);rows.append(row)
print(json.dumps(rows,indent=2));Path('.agent-tmp/gotv-research-plan/field-path-depth-limit-probe.json').write_text(json.dumps(rows,indent=2)+'\n')

assert all(r.get('returned') and r['overflow']==1 and r['result_depth']==r['depth'] for r in rows)
