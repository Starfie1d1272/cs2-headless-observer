"""Synthetic SDK port with the real driver, worker and process pipes; no network or Steam."""
import base64,json,sys
from pathlib import Path
from support.sdk_port import Port
from handshake import number,blob
from channel import encode_message,join_messages,reliable_frame
import driver,sdk
root=Path(__file__).resolve().parents[2]
class SyntheticPort(Port):
    def __init__(self, marker, *args, **kwargs):
        super().__init__();self.marker=Path(marker);self.pumps=0
        frames=json.loads((root/'tests/fixtures/synthetic-channel.json').read_text())['frames']
        self.initial=[(base64.b64decode(row['bodyBase64']),row['reliable']) for row in frames]
        descriptor=blob(1,number(1,17)+blob(2,b'weapon_fire')+blob(3,number(1,1)+blob(2,b'weapon')))
        data,_=join_messages([encode_message(205,descriptor)]);self.initial.append((reliable_frame(data,0),True))
        event=number(2,17)+blob(3,blob(2,b'x'*2000))
        data,_=join_messages([encode_message(207,event) for _ in range(32)])
        self.flood=(reliable_frame(data,100),True)
    def pump(self, now):
        self.pumps+=1
        self.incoming.append(self.initial.pop(0) if self.initial else self.flood)
        if self.pumps==12:self.marker.with_suffix('.progress').write_text('synthetic-ready')
    def close(self):
        super().close();self.marker.write_text(json.dumps({'closed':self.closed,'pumps':self.pumps,'synthetic':True}))
Base=driver.ObserverDriver
class SyntheticDriver(Base):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.phase='channel';self._account_id=1
sdk.NativePort=SyntheticPort;driver.ObserverDriver=SyntheticDriver
raise SystemExit(driver.main())
