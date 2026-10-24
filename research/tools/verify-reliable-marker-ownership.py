"""Verify fixed-build lifecycle dispatch and marker instructions without executing CS2."""
from pathlib import Path
exec(Path(__file__).with_name('verify-coordinate-default-profile.py').read_text().split('client = module(')[0])
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
engine = module(sys.argv[1], '6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21')
network = module(sys.argv[2], 'be7e13ad771b21c986e25d9469993a1225be5649473f3d722ca5eefe375d1bec')
rows = []
for reader, owner, vtable, slot, expected in [
    (engine, 'CNetworkClientService', 0x18057fac8, 0x1a8, 0x1801d8a90),
    (engine, 'CNetworkClientService', 0x18057fac8, 0xd8, 0x1801d6e90),
    (engine, 'CNetworkClientService', 0x18057fac8, 0x1b0, 0x1801d8ad0),
    (network, 'CNetChan', 0x1802358a0, 0x1f8, 0x1800c1cf0),
    (network, 'CNetChan', 0x1802358a0, 0x248, 0x1800c0f80),
    (network, 'CNetChan', 0x1802358a0, 0x250, 0x1800c1010),
]:
    actual = struct.unpack('<Q', reader(vtable + slot, 8))[0]
    assert actual == expected, (owner, slot, hex(actual))
    rows.append({'owner': owner, 'vtable': hex(vtable), 'slot': hex(slot), 'target': hex(actual)})
cs = Cs(CS_ARCH_X86, CS_MODE_64)
checks = [(0x18007a962, 'mov', 'qword ptr [rsi + 0x2c1430], 1'),
          (0x18008b047, 'mov', 'eax, dword ptr [r9 + 0x2c1434]'),
          (0x18008b0b7, 'mov', 'dword ptr [r9 + 0x2c1434], eax'),
          (0x18021b192, 'call', 'qword ptr [rax + 0x1a8]'),
          (0x180213740, 'call', 'qword ptr [rax + 0xd8]')]
instructions = []
for address, mnemonic, operand in checks:
    instruction = next(cs.disasm(engine(address, 16), address))
    assert (instruction.mnemonic, instruction.op_str) == (mnemonic, operand)
    instructions.append({'address': hex(address), 'instruction': mnemonic + ' ' + operand})
print(json.dumps({'manifest':'8766757721818354077', 'dispatch':rows,
                  'instructions':instructions, 'method':'fixed-hash static reads; no online or game execution'}, indent=2))
