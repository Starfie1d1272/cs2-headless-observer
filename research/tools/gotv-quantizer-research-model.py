import struct,math,json
from pathlib import Path
def f(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def i(x):return ((int(x)+(1<<31))%(1<<32))-(1<<31)
def shift(n):return i(1<<(n&31))
def model(bits,flags,low,high):
 low=f(low);high=f(high);flags&=15
 if not 1<=bits<=31:return {'raw':True,'bits':32}
 if (low==0 and flags&1)or(high==0 and flags&2):flags&=~4
 if low==0 and flags&4:flags=(flags&~4)|1
 if high==0 and flags&4:flags=(flags&~4)|2
 if low>0 or high<0:flags&=~4
 if flags&8:flags&=8
 steps=shift(bits);offset=0
 if flags&1:offset=f(f(high-low)/f(steps));high=f(high-offset)
 elif flags&2:offset=f(f(high-low)/f(steps));low=f(low+offset)
 if flags&8:
  delta=i(int(high)-int(low));exp=delta.bit_length()-1 if delta>1 else 0;rang=shift(exp+1)
  while shift(bits)<rang:
   bits+=1
   if bits>64:raise ValueError('native integer bit growth exceeded research budget')
  steps=shift(bits);offset=f(f(rang)/f(steps));high=f(f(low+f(rang))-offset)
 maximum=i(steps-1);delta=f(high-low);mul=float(maximum)
 if abs(delta)>f(0.001):mul/=delta
 def over(m):
  prod=m*delta
  return (int(prod)&0xffffffff)>(maximum&0xffffffff) or prod>float(maximum&0xffffffff)
 if over(mul):
  word=0x3f800000
  while over(struct.unpack('<f',struct.pack('<I',word))[0]*mul):
   word-=1
   if word<0x3f700000:raise ValueError('multiplier adjustment budget')
  mul*=struct.unpack('<f',struct.pack('<I',word))[0]
 dec=1.0/maximum
 def quant(v):
  if v<low:return low
  if v>high:return high
  q=int(f(v-low)*mul+0.5)&0xffffffff
  return min(high,f(q*dec*f(high-low)+low))
 effective=flags
 for bit,value in [(1,low),(2,high),(4,0.0)]:
  if flags&bit and quant(value)==value:effective&=~bit
 return {'raw':False,'bits':bits,'low':low,'high':high,'dec_mul':dec,'high_low_mul':mul,'flags':effective}
rows=json.load(open('.agent-tmp/gotv-research-plan/quantizer-native-matrix.json'));out=[]
for r in rows:
 m=model(r['bits'],r['flags'],r['low'],r['high']);actualmul=struct.unpack_from('<d',bytes.fromhex(r['config_hex']),8)[0]
 same=m['raw']==r['raw']and m['bits']==r['effective_bits']and(m['raw']or(m['low']==r['configured_low']and m['high']==r['configured_high']and m['flags']==r['effective_flags']and m['dec_mul']==r['dec_mul']and m['high_low_mul']==actualmul))
 out.append({'input':{k:r[k]for k in ['bits','flags','low','high']},'same':same,'model':m,'native_high_low_mul':actualmul,'native':{k:r[k]for k in ['effective_bits','effective_flags','configured_low','configured_high','dec_mul']}})
Path('.agent-tmp/gotv-research-plan/quantizer-research-model-comparison.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'cases':len(out),'matched':sum(x['same']for x in out),'mismatches':[x for x in out if not x['same']][:4]},indent=2))
