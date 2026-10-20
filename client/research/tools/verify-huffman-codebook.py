"""Fixed-build Huffman evidence. Isolated native heap operations, no OS imports."""
from pathlib import Path
import hashlib, struct, json, re, heapq
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from capstone.x86_const import X86_OP_MEM, X86_OP_IMM, X86_OP_REG, X86_REG_RAX, X86_REG_RDI, X86_REG_R8D
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
from unicorn.x86_const import UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_RSP, UC_X86_REG_RIP, UC_X86_REG_RAX, UC_X86_REG_EFLAGS

root=Path('.agent-tmp/gotv-research-plan')
binary=Path('.agent-tmp/gotv-tools/cs2/game/bin/win64/networksystem.dll')
b=binary.read_bytes()
sha=hashlib.sha256(b).hexdigest()
assert sha=='be7e13ad771b21c986e25d9469993a1225be5649473f3d722ca5eefe375d1bec'
pe=struct.unpack_from('<I',b,60)[0]; opt=pe+24
base=struct.unpack_from('<Q',b,opt+24)[0]
size=struct.unpack_from('<I',b,opt+56)[0]
sections=[]
u=Uc(UC_ARCH_X86,UC_MODE_64)
u.mem_map(base,(size+4095)&~4095)
u.mem_write(base,b[:struct.unpack_from('<I',b,opt+60)[0]])
for i in range(struct.unpack_from('<H',b,pe+6)[0]):
    p=opt+struct.unpack_from('<H',b,pe+20)[0]+40*i
    _,va,sz,raw=struct.unpack_from('<IIII',b,p+8)
    sections.append((base+va,sz,raw))
    if sz:u.mem_write(base+va,b[raw:raw+sz])
def off(a):
    for va,sz,raw in sections:
        if va<=a<va+sz:return raw+a-va
    raise ValueError(hex(a))

# The constructor repeatedly loads its frequency-vector pointer into RAX.
# Collect only stores through that exact pointer; register R8D is proven zero
# before this no-call block. Do not parse a decompiler's rendered text.
cs=Cs(CS_ARCH_X86,CS_MODE_64); cs.detail=True
weights={}; stores=[]; weights_rax=False
for ins in cs.disasm(b[off(0x1801d71f4):off(0x1801d71f4)+600],0x1801d71f4):
    ops=ins.operands
    if ins.mnemonic=='mov' and len(ops)==2:
        d,s=ops
        if d.type==X86_OP_REG and d.reg==X86_REG_RAX:
            weights_rax=s.type==X86_OP_MEM and s.mem.base==X86_REG_RDI and s.mem.disp==0x10
        if weights_rax and d.type==X86_OP_MEM and d.mem.base==X86_REG_RAX and d.mem.index==0 and d.size==4:
            if s.type==X86_OP_IMM:value=s.imm
            elif s.type==X86_OP_REG and s.reg==X86_REG_R8D:value=0
            else:raise AssertionError('Unresolved frequency store')
            assert d.mem.disp%4==0 and 0<=d.mem.disp//4<40
            index=d.mem.disp//4
            assert index not in weights
            weights[index]=value
            stores.append({'index':index,'weight':value,'address':hex(ins.address),'bytes':ins.bytes.hex()})
            if len(weights)==40:break
    if ins.mnemonic=='call':raise AssertionError('Unexpected call inside frequency writes')
assert len(weights)==40
weights=[weights[i] for i in range(40)]
reference=Path('.agent-tmp/gotv-cohesive-parser/src/parser/entities/fieldPaths.ts').read_text()
literal=re.search(r'const fieldPathTable = \[([\s\S]*?)\];',reference).group(1)
reference_weights=[int(x) for x in re.findall(r'\d+',literal)]
assert weights==reference_weights

scratch=0x10000000; stack=0x20000000; stop=0x30000000
u.mem_map(scratch,0x20000);u.mem_map(stack,0x10000);u.mem_map(stop,0x1000)
vector=scratch+0x100; array=scratch+0x1000; arg=scratch+0x500
# Reserve enough space to keep every native vector operation on its no-grow
# path. No allocator/import hook is installed.
u.mem_write(vector,struct.pack('<IIQ',0,100,array))
def call(address,rcx,rdx):
    rsp=stack+0xff08
    u.mem_write(rsp,struct.pack('<Q',stop))
    for reg,value in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,rcx),(UC_X86_REG_RDX,rdx),(UC_X86_REG_EFLAGS,2)]:
        u.reg_write(reg,value)
    u.emu_start(address,stop,timeout=100000,count=100000)
    assert u.reg_read(UC_X86_REG_RIP)==stop
    return u.reg_read(UC_X86_REG_RAX)
def count():return struct.unpack('<I',u.mem_read(vector,4))[0]
def push(address):
    n=count();u.mem_write(arg,struct.pack('<Q',address))
    call(0x1801d7da0,vector,arg);assert count()==n+1
def pop():
    n=count();assert n>0
    address=struct.unpack('<Q',u.mem_read(array,8))[0]
    if n>1:u.mem_write(array,bytes(u.mem_read(array+(n-1)*8,8)))
    u.mem_write(vector,struct.pack('<I',n-1))
    call(0x1801d80a0,vector,0)
    return address

nodes={}
def node(index,weight,left=None,right=None):
    a=scratch+0x8000+index*32
    leaf=left is None
    # Same sequence origin and layout as 1d7440: sequence=index+1;
    # leaf payload is symbol index, parent payload is first/second popped child.
    u.mem_write(a,struct.pack('<QIIQQ',0x1802144c0 if leaf else 0x1802144a8,
        weight,index+1,index if leaf else left,0 if leaf else right))
    nodes[a]={'weight':weight,'symbol':index if leaf else None,'left':left,'right':right}
    return a
for i,w in enumerate(weights):push(node(i,max(1,w)))
index=40
while count()>1:
    left=pop();right=pop()
    push(node(index,nodes[left]['weight']+nodes[right]['weight'],left,right));index+=1
native_root=pop();assert index==79

def codes(n,lookup,path=()):
    value=lookup[n]
    if value['symbol'] is not None:return {value['symbol']:path}
    return codes(value['left'],lookup,path+(0,))|codes(value['right'],lookup,path+(1,))
native_codes=codes(native_root,nodes)
# Independent reference priority queue, with the pinned source's weight/tie
# rule, rather than a copied result from the native heap.
heap=[];refnodes={}
for i,w in enumerate(reference_weights):
    refnodes[i]={'symbol':i,'left':None,'right':None}
    heapq.heappush(heap,(max(1,w),-i,i))
for i in range(40,79):
    lw,_,left=heapq.heappop(heap);rw,_,right=heapq.heappop(heap)
    refnodes[i]={'symbol':None,'left':left,'right':right}
    heapq.heappush(heap,(lw+rw,-i,i))
reference_codes=codes(heap[0][2],refnodes)
assert native_codes==reference_codes and len(native_codes)==40

# Exercise the native recursive tree-to-postorder-table builder with a
# preallocated 40-entry destination. Its real leaf/branch predicates execute
# from the mapped module; no allocation or operating-system import is needed.
owner=scratch+0x3000; table=scratch+0x5000
u.mem_write(owner+0x7a8,struct.pack('<IIQII',0,0,table,40,0x40000000))
last=call(0x1801d7030,owner,native_root)&255
assert last==38
post=bytes(u.mem_read(table,78))
rows=[]
for original_index in range(last,-1,-1):
    row=[]
    for child in struct.unpack_from('<bb',post,original_index*2):
        row.append(last-child if child>=0 else child)
    rows.append(row)
for symbol,path in native_codes.items():
    current=0
    for bit in path:
        assert current>=0
        current=rows[current][bit]
    assert current<0 and ~current==symbol

result={'manifest':'8766757721818354077','sha256':sha,
    'method':'Static constructor frequency extraction; real native insert/sift and tree-table builder in isolated Unicorn memory; preallocated storage, no allocator hooks or OS imports. Tree parent assembly follows inspected1d7440; table reversal follows inspected1d6de0.',
    'weights':weights,'frequency_stores':stores,'matched_codewords':40,
    'max_code_bits':max(map(len,native_codes.values())),
    'codes':[{'symbol':i,'wire_bits_first_to_last':''.join(map(str,native_codes[i])),'length':len(native_codes[i])} for i in range(40)],
    'decoder_table':rows,'scope':'Fixed-build actual Huffman selection, not just individual opcode behavior. No whole-game or live acceptance claim.'}
(root/'huffman-codebook-authority.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k]for k in ['matched_codewords','max_code_bits','method','scope']}))
