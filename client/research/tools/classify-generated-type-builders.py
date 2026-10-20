# Targeted static evidence extraction, not a runtime decoder.
from pathlib import Path
exec(Path(__file__).with_name('find-generated-type-calls.py').read_text().split('names=set()')[0])
from capstone.x86_const import X86_REG_RDX,X86_REG_RIP
rows=json.loads(Path('.agent-tmp/gotv-research-plan/generated-type-constructor-calls.json').read_text());primitives={r['name']for r in json.loads(Path('.agent-tmp/gotv-research-plan/primitive-type-catalog.json').read_text())}
def offset(a):
 for _,v,s,r in ss:
  if 0x180000000+v<=a<0x180000000+v+s:return r+a-0x180000000-v
 raise ValueError(hex(a))
def string(a):
 try:q=offset(a);e=b.index(0,q,q+200);return b[q:e].decode()
 except:return None
cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True;result=[];seen=set()
for row in rows:
 if row['type']in primitives:continue
 key=(row['type'],row['constructor'])
 if key in seen:continue
 seen.add(key);addr=int(row['constructor'],16);q=offset(addr);flags=[];underlying=[];rdx=None
 for ins in cs.disasm(b[q:q+2048],addr):
  if ins.mnemonic.startswith('ret'):break
  if ins.mnemonic=='lea'and len(ins.operands)==2:
   d,s=ins.operands
   if d.type==X86_OP_REG and d.reg==X86_REG_RDX and s.type==X86_OP_MEM and s.mem.base==X86_REG_RIP:rdx=string(ins.address+ins.size+s.mem.disp)
   elif d.type==X86_OP_REG and s.type==X86_OP_MEM and s.mem.disp==0x130:underlying.append({'address':hex(ins.address),'candidate':rdx})
  if ins.mnemonic=='mov'and len(ins.operands)==2:
   d,s=ins.operands
   if d.type==X86_OP_MEM and 0x144<=d.mem.disp<=0x151 and s.type==X86_OP_IMM:flags.append({'address':hex(ins.address),'offset':hex(d.mem.disp),'value':s.imm,'base':ins.reg_name(d.mem.base)})
 result.append({**row,'flag_writes':flags,'underlying_string_candidates':underlying})
Path('.agent-tmp/gotv-research-plan/generated-type-builder-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
for r in result:
 if r['type'] in ['GameTime_t','GameTick_t'] and any(x['type']==r['type']for x in result[:result.index(r)]):continue
 print(r['type'],r['constructor'],r['stack_argument_5'],[(x['offset'],x['value'])for x in r['flag_writes']],r['underlying_string_candidates'])
