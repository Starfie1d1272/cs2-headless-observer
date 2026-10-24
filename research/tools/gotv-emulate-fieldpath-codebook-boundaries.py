"""Whole-list reader with the fixed build's actual Huffman table."""
from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-fieldpath-depths.py').read_text().split('ops=json.load')[0])
from unicorn.x86_const import UC_X86_REG_R8,UC_X86_REG_R9,UC_X86_REG_RAX

profile=json.loads(Path('.agent-tmp/gotv-research-plan/huffman-codebook-authority.json').read_text())
assert profile['sha256']==hashlib.sha256(b).hexdigest()
codes={r['symbol']:[int(c)for c in r['wire_bits_first_to_last']] for r in profile['codes']}
table=bytes(v&255 for row in profile['decoder_table'] for v in row)
def packed(bits):
    out=bytearray((len(bits)+7)//8)
    for i,bit in enumerate(bits):out[i//8]|=bit<<(i%8)
    return bytes(out)
longest=max(codes,key=lambda op:len(codes[op]))
cases=[
    ('finish-opcode',codes[39],1),
    ('plusN-root-sentinel',codes[4]+[0,0,0,1]+[(32763>>i)&1 for i in range(17)],1),
    ('truncated-plusN',codes[4]+[0],0),
    ('truncated-long-code',codes[longest][:-1],0),
]
results=[]
for offset in range(8):
    for name,wire,expected in cases:
        u.mem_write(scratch,b'\0'*0x3000)
        u.mem_write(stack+0xe000,b'\0'*0x2000)
        reader=scratch+0x100;out=scratch+0x200;tree=scratch+0x300;data=scratch+0x1000
        u.mem_write(base+0x2a6240,struct.pack('<Q',tree))
        u.mem_write(tree,table)
        bits=[1]*offset+wire
        u.mem_write(data,packed(bits)+b'\0'*64)
        u.mem_write(reader,struct.pack('<Qiii',data,64,len(bits),offset))
        rsp=stack+0xff08
        u.mem_write(rsp,struct.pack('<Q',stop))
        for reg,value in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,reader),
                          (UC_X86_REG_R8,out),(UC_X86_REG_R9,0),(UC_X86_REG_EFLAGS,2)]:
            u.reg_write(reg,value)
        u.emu_start(base+0x10eba0,stop,timeout=1000000,count=100000)
        row={'name':name,'start_bit':offset,'valid_bits':len(bits),
             'returned':u.reg_read(UC_X86_REG_RIP)==stop,
             'success':u.reg_read(UC_X86_REG_RAX)&255,
             'fields':struct.unpack('<i',u.mem_read(out,4))[0],
             'end_bit':struct.unpack('<i',u.mem_read(reader+16,4))[0],
             'overflow':u.mem_read(reader+32,1)[0]}
        assert row['returned'] and row['success']==expected and row['fields']==0
        assert bool(row['overflow'])==(not bool(expected))
        if expected:assert row['end_bit']==len(bits)
        results.append(row)
result={'manifest':'8766757721818354077','module_sha256':hashlib.sha256(b).hexdigest(),
        'method':'Real whole-list10eba0 and opcode handlers with the actual fixed-build Huffman table derived by verify-huffman-codebook.py; isolated Unicorn, no imports or allocator hooks.',
        'cases':len(results),'passed':len(results),'rows':results,
        'scope':'Actual-codebook termination/truncation boundaries at all byte alignments; complements the separately verified 40 opcode semantics, not a live stream.'}
Path('.agent-tmp/gotv-research-plan/field-path-codebook-boundaries.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k]for k in ['cases','passed','method','scope']}))
