"""Synthetic SDK conversation with the real driver, worker and process pipes."""
import base64,json,sys,faulthandler
faulthandler.dump_traceback_later(8)  # Synthetic fixture only: expose a stalled cleanup in CI.
from pathlib import Path
from support.sdk_port import Port
from handshake import number,blob
from channel import decode_frame,messages,encode_message,join_messages,reliable_frame
from wire import fields,scalar
import driver,sdk
root=Path(__file__).resolve().parents[2]
class SyntheticPort(Port):
    def __init__(self, marker, *args, **kwargs):
        super().__init__();self.marker=Path(marker);self.pumps=0
        self.signon_acks=set();self.initial_index=0;self.flood_frames=0
        frames=json.loads((root/'tests/fixtures/synthetic-channel.json').read_text())['frames']
        self.initial=[(base64.b64decode(row['bodyBase64']),row['reliable']) for row in frames]
        descriptor=blob(1,number(1,17)+blob(2,b'weapon_fire')+blob(3,number(1,1)+blob(2,b'weapon')))
        data,_=join_messages([encode_message(205,descriptor)]);self.initial.append((reliable_frame(data,0),True))
        event=number(2,17)+blob(3,blob(2,b'x'*2000))
        data,_=join_messages([encode_message(207,event) for _ in range(32)])
        self.flood=(reliable_frame(data,100),True)
    def pump(self, now):
        self.pumps+=1
        if self.incoming:return
        if self.initial:
            # Advance server phases after the corresponding client acknowledgement.
            required=(0,3,4,5,6,6)[self.initial_index]
            if required and required not in self.signon_acks:return
            self.incoming.append(self.initial.pop(0));self.initial_index+=1
        else:
            self.incoming.append(self.flood);self.flood_frames+=1
            if self.flood_frames==3:self.marker.with_suffix('.progress').write_text('synthetic-ready')
    def send(self, data, flags):
        super().send(data,flags)
        decoded,_=messages(decode_frame(data,gns_reliable=bool(flags&8)).body)
        for message in decoded:
            if message.message_id==7:self.signon_acks.add(scalar(fields(message.body),1))
    def close(self):
        super().close();self.marker.write_text(json.dumps({'closed':self.closed,'pumps':self.pumps,
            'synthetic':True,'signonAcks':sorted(self.signon_acks),'floodFrames':self.flood_frames}))
Base=driver.ObserverDriver
class SyntheticDriver(Base):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.phase='channel';self._account_id=1
sdk.NativePort=SyntheticPort;driver.ObserverDriver=SyntheticDriver
raise SystemExit(driver.main())
