# Research-only VPK directory reader. Format cross-checked with ValvePak Package.Read.cs.
import sys,struct,zlib,json
from pathlib import Path
p=Path(sys.argv[1]);b=p.read_bytes();magic,version,size=struct.unpack_from('<III',b);assert magic==0x55aa1234 and version in(1,2)
header=12 if version==1 else 28;end=header+size;assert end<=len(b);pos=header;count=0
wanted=sys.argv[2] if len(sys.argv)>2 else 'replay_compat'
def string():
 global pos
 e=b.index(0,pos,end);r=b[pos:e].decode();pos=e+1;return r
while (ext:=string()):
 while (folder:=string()):
  while (name:=string()):
   assert pos+18<=end
   crc,pre,archive,off,length,term=struct.unpack_from('<IHHIIH',b,pos);pos+=18;assert term==65535 and pos+pre<=end
   preload=b[pos:pos+pre];pos+=pre;count+=1;path=(folder+'/' if folder!=' ' else '')+name+('.'+ext if ext!=' ' else '')
   if wanted in path:
    obj=dict(path=path,crc=hex(crc),preload=pre,archive=archive,offset=off,length=length,index=str(p));print(json.dumps(obj))
    q=p if archive==32767 else p.with_name(p.name.replace('_dir.vpk',f'_{archive:03}.vpk'))
    if not length:data=preload
    elif q.exists():
     with q.open('rb') as f:f.seek(off+(end if archive==32767 else 0));data=preload+f.read(length)
    else:continue
    assert len(data)==pre+length and zlib.crc32(data)==crc
    if len(sys.argv)>3:Path(sys.argv[3]).write_bytes(data)
assert pos==end
print('ENTRIES',count,file=sys.stderr)
