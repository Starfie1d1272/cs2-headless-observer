"""Fixed optional origin projection support; read-only PE facts."""
from pathlib import Path
exec(Path(__file__).with_name('verify-coordinate-default-profile.py').read_text().split('client = module(')[0])
tier0 = module(sys.argv[1], '990ea56bf1626d299ba54b64b423f2e409bd592bb737c7a5edf7972ad5c7143e')
integer = struct.unpack('<i',tier0(0x18039c400,4))[0]
floating = struct.unpack('<f',tier0(0x18039c40c,4))[0]
assert integer == floating == 16384
print(json.dumps({'manifest':'8766757721818354077','module':'tier0.dll',
 'default_max_coord':integer,'integer_address':'0x18039c400','float_address':'0x18039c40c',
 'quantizer_registry_lookup':'0x18015c380','method':'fixed-hash initial data; no claim about uninspected modules mutating exported globals'},indent=2))
