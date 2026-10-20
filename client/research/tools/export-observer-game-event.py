import sys,struct,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[3] if len(sys.argv)>3 else str(Path(__file__).resolve().parents[2]))
from ordered_parser_bridge import OrderedParserBridge
from handshake import number,blob
from test_ordered_driver import bits,packed,info
steam=76561198000000123
name='CCSPlayerController'
def field_wire():return [0,1,0]+bits(steam,64)
def table(name,data):
 w=[1,1,0]+bits(48,8)+bits(0,8)+[1]+bits(len(data),17)
 for b in data:w+=bits(b,8)
 return blob(1,name.encode())+number(2,1)+blob(7,packed(w))
serializer=number(1,0)+number(2,0)+number(3,0)
field=number(1,2)+number(2,1)+number(10,3)
schema=blob(1,serializer)+b''.join(blob(2,s.encode()) for s in (name,'m_steamID','uint64','fixed64'))+blob(3,field)
full=number(2,1)+number(10,0)+number(12,99)+blob(7,packed(bits(1,6)+bits(2,2)+[0]+bits(1,17)+bits(0,8)+field_wire()))+blob(19,b'')
keys=[(9,'userid'),(1,'weapon'),(6,'silenced')]
desc=blob(1,number(1,17)+blob(2,b'weapon_fire')+b''.join(blob(3,number(1,t)+blob(2,n.encode())) for t,n in keys))
event=number(2,17)+blob(3,number(1,9)+number(5,0))+blob(3,number(1,1)+blob(2,b'ak47'))+blob(3,number(1,6)+number(7,0))
messages=[(40,info()),(41,schema),(42,blob(2,number(1,0)+blob(3,name.encode()))),(44,table('instancebaseline',packed(field_wire()))),(44,table('userinfo',b'\x11'+struct.pack('<Q',steam)+number(3,42))),(55,full),(205,desc),(207,event)]
b=OrderedParserBridge(source='ahead:fixture',channel=1,world=2,worker=sys.argv[1]);rows=[];emitted=[]
try:
 for i,body in messages:b.submit_batch([('message',i,body,99 if i!=207 else 100)])
 end=time.monotonic()+5
 while b.completed_sequence<len(messages):
  rows+=b.poll(emit=emitted.append)
  if time.monotonic()>end:raise RuntimeError('timeout')
  time.sleep(.005)
 events=[r for r in emitted if r.get('kind')=='weapon_fire'];assert len(events)==1,(rows,emitted)
 event=events[0];assert event['players']['userid']['userId']==42,event
 with open(sys.argv[2],'w') as f:json.dump(event,f,indent=2)
 Path(sys.argv[2]).with_suffix('.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in emitted))
 print(json.dumps(event,indent=2))
finally:b.close()
