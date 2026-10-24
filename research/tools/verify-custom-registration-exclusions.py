"""Read-only fixed-PE validation of two resolved non-serializer call sites."""
import hashlib,json,struct,sys
from pathlib import Path
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
from capstone.x86 import X86_REG_RIP,X86_OP_MEM
p=Path(sys.argv[1]);data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
assert sha=='09e8c04c5f44040155d04fa79a3f43491d542a386f45807ed77785729e5925a9'
pe=struct.unpack_from('<I',data,60)[0];count=struct.unpack_from('<H',data,pe+6)[0];opt=struct.unpack_from('<H',data,pe+20)[0];sections=[]
for i in range(count):
 vs,va,rs,rp=struct.unpack_from('<IIII',data,pe+24+opt+40*i+8);sections.append((va,max(vs,rs),rp))
def off(a):return next(rp+a-0x180000000-va for va,size,rp in sections if va<=a-0x180000000<va+size)
c=Cs(CS_ARCH_X86,CS_MODE_64);c.detail=True
rows=[]
for start,end,site,load,nameaddr,event in [(0x180ddb070,0x180ddb270,0x180ddb248,0x180ddb23b,0x18198d3b0,'hltv_title'),(0x180dde5b0,0x180dde7d0,0x180dde7be,0x180dde7b1,0x18178a9d0,'hltv_chat')]:
 ins={i.address:i for i in c.disasm(data[off(start):off(end)],start)}
 call=ins[site];assert call.mnemonic=='call' and call.op_str=='qword ptr [rax + 0x50]'
 x=ins[load];mem=x.operands[1];assert x.mnemonic=='mov' and mem.type==X86_OP_MEM and mem.mem.base==X86_REG_RIP
 owner=x.address+x.size+mem.mem.disp;assert owner==0x182182cf8
 o=off(nameaddr);assert data[o:data.find(b'\0',o)].decode()==event
 rows.append({'call':hex(site),'owner_global':hex(owner),'slot':'0x50','event':event,'classification':'IGameEventManager2::FreeEvent','reason':'Same owner creates the named event through slot0x30 and serializes it through0x58; slot0x50 matches pinned IGameEventManager2 FreeEvent. This is not the serializer registration owner.'})
result={'module':'server.dll','sha256':sha,'method':'Fixed-hash read-only aligned instructions, owner-global and embedded event-name checks; interface meaning cross-checked with pinned igameevents.h','sdk_commit':'5864d8db8519e80a0d870c0e0474eddc8172fb4e','sdk_source':'https://github.com/alliedmodders/s2sdk/blob/5864d8db8519e80a0d870c0e0474eddc8172fb4e/public/igameevents.h','resolved_exclusions':rows,'checks':2,'passed':2}
Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n');print('2/2 resolved non-serializer call sites verified')
