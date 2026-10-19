"""Manual complete-Demo control regression; no sockets, no Steam, not a CI gate."""
import sys,json,hashlib,collections,ctypes,ctypes.util,time,argparse
from pathlib import Path
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--fixture',type=Path,required=True)
ap.add_argument('--reference-worker',type=Path,required=True)
ap.add_argument('--candidate-worker',type=Path,required=True)
ap.add_argument('--output',type=Path,required=True)
args=ap.parse_args()
from parser_bridge import ParserBridge
from parser_stream import frame
from wire import fields,scalar,varint
fixture=args.fixture;data=fixture.read_bytes();assert hashlib.sha256(data).hexdigest()=='143eb78444727c7a8afa29d807272076d14044fc9d7c233035d0b9a176e70f60';lib=ctypes.CDLL(ctypes.util.find_library('snappy'))
lib.snappy_uncompressed_length.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)];lib.snappy_uncompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t)]
def decompress(raw):
 n=ctypes.c_size_t();assert lib.snappy_uncompressed_length(raw,len(raw),ctypes.byref(n))==0 and n.value<=64*1024**2
 out=ctypes.create_string_buffer(n.value);assert lib.snappy_uncompress(raw,len(raw),out,ctypes.byref(n))==0;return out.raw[:n.value]
workers=[ParserBridge(worker=path) for path in (args.reference_worker,args.candidate_worker)]
hashes=[hashlib.sha256(),hashlib.sha256()];counts=[collections.Counter(),collections.Counter()];receipts=[0,0]
def emit(i,event):
 hashes[i].update(json.dumps(event,sort_keys=True,separators=(',',':')).encode()+b'\n');counts[i][event['kind']]+=1
start=time.monotonic();pos=16;packets=0
try:
 while pos<len(data):
  command,pos=varint(data,pos);tick,pos=varint(data,pos);length,pos=varint(data,pos);raw=data[pos:pos+length];pos+=length
  if command&64:raw=decompress(raw)
  kind=command&~64
  if kind in (4,5):
   for p in workers:p._parts.append(frame(kind,p.stream.tick,raw));p.stream.have_serializers |= kind==4;p.stream.have_classes |= kind==5
  elif kind in (7,8):
   packet=scalar(fields(raw,limit=4*1024**2),3,2)
   if not packet:continue
   packets+=1
   for p in workers:p.submit(packet)
   deadline=time.monotonic()+15
   while any(not p.checkpoint or p.checkpoint['sequence']<packets for p in workers):
    for i,p in enumerate(workers):p.poll(lambda event,i=i:emit(i,event));receipts[i]+=len(p.pop_receipts())
    assert time.monotonic()<deadline,'parser-checkpoint-timeout'
    time.sleep(.0001)
   if packets%25000==0:print(json.dumps({'packets':packets,'seconds':round(time.monotonic()-start,1)}),flush=True)
 assert hashes[0].hexdigest()==hashes[1].hexdigest(), 'event-semantic-difference'
 result={'evidence':'REAL_DEMO_NETWORK_BODIES_THROUGH_BOTH_ADAPTERS_NO_NETWORK','fixture_sha256':hashlib.sha256(data).hexdigest(),'packets':packets,'equivalent':True,'event_sha256':hashes[0].hexdigest(),'counts':[dict(c) for c in counts],'receipts':receipts,'seconds':round(time.monotonic()-start,3),'online':False}
 with args.output.open('x') as output:output.write(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
finally:
 for p in workers:p.close()
