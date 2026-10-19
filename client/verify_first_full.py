"""Real Demo first-full parsing with a synthetic SPAWN state; no network connection."""
import argparse
import sys,ctypes,ctypes.util,time,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'client'))
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--fixture',type=Path,required=True)
ap.add_argument('--worker',type=Path,required=True)
ap.add_argument('--output',type=Path,required=True)
args=ap.parse_args()
from parser_bridge import ParserBridge
from parser_stream import frame
from wire import fields,scalar,varint
from handshake import number
from driver import ObserverDriver
from test_driver import Port
fixture=args.fixture
assert fixture.stat().st_size <= 512*1024**2, 'fixture-size-limit'
data=fixture.read_bytes();assert hashlib.sha256(data).hexdigest()=='143eb78444727c7a8afa29d807272076d14044fc9d7c233035d0b9a176e70f60'
snappy=ctypes.CDLL(ctypes.util.find_library('snappy'))
snappy.snappy_uncompressed_length.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
snappy.snappy_uncompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t)]
def decompress(raw):
 size=ctypes.c_size_t();assert snappy.snappy_uncompressed_length(raw,len(raw),ctypes.byref(size))==0 and size.value<=64*1024**2
 out=ctypes.create_string_buffer(size.value);assert snappy.snappy_uncompress(raw,len(raw),out,ctypes.byref(size))==0
 return out.raw[:size.value]
p=ParserBridge(worker=args.worker);port=Port();driver=ObserverDriver(port,host_version=14191,password=bytearray(b'offline'),emit=lambda _:None,parser=p)
driver.phase='channel';driver.signon.server_info(7)
for state in (3,4,5):driver.signon.receive(number(1,state)+number(2,7))
driver.signon.finish_spawn();driver._new_sent=driver._prespawn_sent=driver._spawn_sent=True
pos=16;packets=0;events=[]
try:
 while pos<len(data) and not driver._full_sent:
  command,pos=varint(data,pos);tick,pos=varint(data,pos);length,pos=varint(data,pos);raw=data[pos:pos+length];pos+=length
  if command&64:raw=decompress(raw)
  kind=command&~64
  if kind in (4,5):
   p._parts.append(frame(kind,p.stream.tick,raw));p.stream.have_serializers |= kind==4;p.stream.have_classes |= kind==5
  elif kind in (7,8):
   packet=scalar(fields(raw,limit=4*1024**2),3,2)
   if not packet:continue
   packets+=1;seq=p.submit(packet);driver._parser_sequence=seq
   deadline=time.monotonic()+10
   while not p.checkpoint or p.checkpoint['sequence']<seq:
    p.poll(events.append)
    assert time.monotonic()<deadline,'checkpoint-timeout'
    time.sleep(.001)
   driver._send_processed_tick(100+packets*100)
 assert driver._full_sent,'no-full-snapshot'
 result={'evidence':'REAL_DEMO_ENTITY_PARSE_WITH_SYNTHETIC_SPAWN_STATE_NO_NETWORK','fixture_sha256':hashlib.sha256(data).hexdigest(),'packets':packets,'parser_checkpoint':p.checkpoint,'received_signon_state':driver.signon.received_state,'effective_signon_state':driver.signon.state,'first_full_tick':driver.report()['last_processed_entity_tick'],'full_sent':driver._full_sent,'online_verified':False}
 with args.output.open('x') as output: output.write(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
finally:p.close()
