"""Read-only fixed-build event type and method dispatch evidence."""
from pathlib import Path
exec(Path(__file__).with_name('verify-coordinate-default-profile.py').read_text().split('client = module(')[0])
server = module(sys.argv[1], '09e8c04c5f44040155d04fa79a3f43491d542a386f45807ed77785729e5925a9')
expected = ['local','string','float','long','short','byte','bool','uint64','strict_ehandle','playercontroller']
rows = []
for index, name in enumerate(expected):
    pointer, kind = struct.unpack('<QI', server(0x18193c6d0 + index * 16, 12))
    actual = server(pointer, len(name) + 1)
    assert kind == index and actual == name.encode() + b'\0'
    rows.append({'type':kind,'name':name})
methods = []
for slot, address, name in [(0x60,0x180bf9c60,'GetEHandle'),(0x68,0x180bf9cf0,'GetEntity'),
                            (0x70,0x180bf9ca0,'GetEntityIndex'),(0x78,0x180bfb630,'GetPlayerSlot'),
                            (0xd8,0x180c1f6d0,'SetEntity(handle)'),(0xe0,0x180c22080,'SetPlayer(slot)'),
                            (0xe8,0x180c21e10,'SetPlayer(entity)'),(0xf0,0x180c22130,'SetPlayerRaw')]:
    assert struct.unpack('<Q',server(0x181940d20 + slot,8))[0] == address
    methods.append({'slot':hex(slot),'method':name,'target':hex(address)})
assert struct.unpack('<Q',server(0x181940e38+0x58,8))[0] == 0x180c1dd90
client = module(sys.argv[2], '659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0')
client_methods = []
for slot, address, name in [(0x68,0x1809e46d0,'GetEntity'),(0x70,0x1809e4680,'GetEntityIndex'),(0x78,0x1809e8a50,'GetPlayerSlot')]:
    assert struct.unpack('<Q',client(0x181c315c0+slot,8))[0] == address
    client_methods.append({'slot':hex(slot),'method':name,'target':hex(address)})
print(json.dumps({'client_methods':client_methods,'manifest':'8766757721818354077','types':rows,'methods':methods,
                  'serialize_event':'0x180c1dd90','method':'fixed-hash read-only constants/vtable verification; no online execution'},indent=2))
