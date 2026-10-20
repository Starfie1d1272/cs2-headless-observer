from pathlib import Path
exec(Path(__file__).with_name('gotv-emulate-aggregate.py').read_text().split('rows=[];cases=[]')[0])
root=Path('.agent-tmp/gotv-research-plan')
configs=[]
for source in ['quantizer-native-matrix.json','quantizer-native-default-bounds.json','origin-cell-native-configurations.json']:
 for row in json.loads((root/source).read_text()):
  if row.get('expected_native_fatal') or (row['effective_bits']>31 and not row['raw']):continue
  if row['config_hex'] not in {x['config_hex']for x in configs}:configs.append(row)
rows=[]
for index,q in enumerate(configs):
 width=q['effective_bits'];active=[x for x in [1,2,4] if q['effective_flags']&x]
 options=[]
 if q['raw']:options=[(x,32)for x in [0,0x80000000,0x3f800000,0xc2f60000]]
 else:
  for choice in range(len(active)):options.append((1<<choice,choice+1))
  for value in sorted({0,1,(1<<width)//2,(1<<width)-1,((1<<width)*37)//101}):options.append((value<<len(active),width+len(active)))
 for dim in [1,2,3,4,6,8]:
  for value,count in options:
   payload=sum(value<<(count*n)for n in range(dim)).to_bytes((count*dim+7)//8,'little');bits=count*dim
   u.mem_write(scratch,b'\0'*0x5000);u.mem_write(stack+0xf000,b'\0'*0x1000)
   reader=scratch;desc=scratch+0x100;config=scratch+0x200;out=scratch+0x400;data=scratch+0x1000;rsp=stack+0xff08
   u.mem_write(data,payload+b'\0'*16);u.mem_write(reader,struct.pack('<Qiii',data,len(payload),bits,0));u.mem_write(config,bytes.fromhex(q['config_hex']));u.mem_write(desc+0x26,struct.pack('<H',dim<<12|3<<7));u.mem_write(rsp,struct.pack('<Q',stop));u.mem_write(rsp+0x28,struct.pack('<Q',out))
   for reg,v in [(UC_X86_REG_RSP,rsp),(UC_X86_REG_RCX,0),(UC_X86_REG_RDX,reader),(UC_X86_REG_R8,desc),(UC_X86_REG_R9,config),(UC_X86_REG_EFLAGS,2)]:u.reg_write(reg,v)
   record={'config':index,'dimension':dim,'input_hex':payload.hex(),'expected_bits':bits}
   try:
    u.emu_start(0x1800d1520,stop,timeout=100000,count=100000)
    read=struct.unpack('<i',u.mem_read(reader+16,4))[0];overflow=u.mem_read(reader+32,1)[0]
    record.update(native_hex=bytes(u.mem_read(out,dim*4)).hex(),native_bits=read,overflow=overflow,completed=read==bits and not overflow and u.reg_read(UC_X86_REG_RIP)==stop)
   except UcError as e:record.update(completed=False,error=str(e))
   rows.append(record)
result={'manifest':'8766757721818354077','configs':configs,'cases':rows};(root/'quantized-configured-read-vectors.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
summary={'manifest':result['manifest'],'configs':len(configs),'cases':len(rows),'completed':sum(r['completed']for r in rows),'native_function':'networksystem0d1520','method':'decode saved native configuration bytes across dimensions1/2/3/4/6/8 and sentinel/integer boundary inputs; no import execution','vectors_sha256':hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
(root/'quantized-configured-read-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));assert all(r['completed']for r in rows)
