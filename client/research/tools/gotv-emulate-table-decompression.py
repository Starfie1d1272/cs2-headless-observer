from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
from unicorn.x86_const import UC_X86_REG_RAX

cases = []
for payload in [b'', b'a', b'abc', bytes(range(32))]:
    encoded = varuint(len(payload)) + (bytes([(len(payload) - 1) << 2]) + payload if payload else b'')
    cases.append(('snappy-literal', encoded, payload))
cases += [('snappy-copy', bytes([6, 8]) + b'abc' + bytes([10, 3, 0]), b'abcabc')]
for payload in [b'not snappy', b'abc', b'\xff\xff\xff\xff\xff', b'']:
    cases.append(('raw-fallback', payload, payload))

rows = []
for kind, payload, expected in cases:
    u.mem_write(scratch, b'\0' * 0x5000)
    u.mem_write(stack + 0xf000, b'\0' * 0x1000)
    data, out, sizeptr = scratch + 0x1000, scratch + 0x2000, scratch + 0x3000
    u.mem_write(data, payload + b'\0' * 64)
    u.mem_write(sizeptr, struct.pack('<I', 1024))
    rsp = stack + 0xff08
    u.mem_write(rsp, struct.pack('<Q', stop))
    u.mem_write(rsp + 0x28, struct.pack('<Q', len(payload)))
    for reg, value in [(UC_X86_REG_RSP, rsp), (UC_X86_REG_RCX, 0),
                       (UC_X86_REG_RDX, out), (UC_X86_REG_R8, sizeptr),
                       (UC_X86_REG_R9, data), (UC_X86_REG_EFLAGS, 2)]:
        u.reg_write(reg, value)
    row = {'kind': kind, 'input_hex': payload.hex(), 'expected_hex': expected.hex()}
    try:
        u.emu_start(0x1800fb100, stop, timeout=100000, count=1000000)
        length = struct.unpack('<I', u.mem_read(sizeptr, 4))[0]
        if length > 1024:
            raise ValueError('native-output-capacity')
        actual = bytes(u.mem_read(out, length))
        ok = u.reg_read(UC_X86_REG_RAX) & 255
        row.update(actual_hex=actual.hex(), actual_size=length, returned=ok,
                   passed=actual == expected and ok == 1 and u.reg_read(UC_X86_REG_RIP) == stop)
    except (UcError, ValueError) as error:
        row.update(passed=False, error=str(error), rip=hex(u.reg_read(UC_X86_REG_RIP)))
    rows.append(row)
summary = {'manifest': '8766757721818354077', 'function': 'networksystem0fb100',
           'method': 'isolated complete table-decompression wrapper; no OS imports/stubs/network',
           'cases': len(rows), 'passed': sum(x['passed'] for x in rows)}
Path('.agent-tmp/gotv-research-plan/table-decompression-emulation.json').write_text(
    json.dumps({'summary': summary, 'cases': rows}, indent=2) + '\n')
print(json.dumps(summary))
print(json.dumps([row for row in rows if not row['passed']]))
