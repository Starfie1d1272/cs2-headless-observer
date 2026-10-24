"""Generate wholly synthetic application-channel frames; no game or player data."""
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'client'), str(ROOT/'tests')]
from channel import encode_message, join_messages, reliable_frame
from handshake import blob, number
from support.protocol import info, schema, table, full

groups = [
    [(40, info()), (7, number(1, 3)+number(2, 7))],
    [(41, schema()), (42, blob(2,number(1,0)+blob(3,b'Root'))), (44, table()), (7, number(1,4)+number(2,7))],
    [(7, number(1,5)+number(2,7))],
    [(4, number(1,100)), (55, full(100))],
    [(205, blob(1,number(1,17)+blob(2,b'round_freeze_end'))), (207,number(2,17))],
]
frames=[]
for index, messages in enumerate(groups,1):
    body,_=join_messages([encode_message(i,b) for i,b in messages])
    frames.append({'elapsedMs':index*10,'reliable':True,'bodyBase64':base64.b64encode(reliable_frame(body,100)).decode('ascii')})
fixture={'schema':'cs2-observer-synthetic-channel/1','provenance':'WHOLLY_SYNTHETIC_NO_MATCH_NO_PLAYER_DATA',
         'hostVersion':14191,'expectedEvent':'round_freeze_end','frames':frames}
destination=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('synthetic-channel.json')
destination.write_text(json.dumps(fixture,indent=2)+'\n',encoding='utf-8')
print('Wrote synthetic five-frame fixture')
