// Research model derived independently from fixed native configuration output.
// This does not enable out-of-budget widths in the production decoder.
import { readFileSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const f = Math.fround;
const i = value => Math.trunc(value) | 0;
const shift = n => 1 << (n & 31);
const word = new DataView(new ArrayBuffer(4));
const asFloat = value => { word.setUint32(0,value,true); return word.getFloat32(0,true); };
export function configure(bits, flags, low, high) {
 low=f(low); high=f(high); flags &= 15;
 if (!(bits>=1 && bits<=31)) return {raw:true,bits:32};
 if ((low===0 && flags&1)||(high===0 && flags&2)) flags &= ~4;
 if (low===0 && flags&4) flags=(flags&~4)|1;
 if (high===0 && flags&4) flags=(flags&~4)|2;
 if (low>0 || high<0) flags &= ~4;
 if (flags&8) flags &=8;
 let steps=shift(bits), offset=0;
 if(flags&1) {offset=f(f(high-low)/f(steps));high=f(high-offset);}
 else if(flags&2) {offset=f(f(high-low)/f(steps));low=f(low+offset);}
 if(flags&8) {
  const delta=i(i(high)-i(low));
  const exponent=delta>1 ? 31-Math.clz32(delta) : 0;
  const range=shift(exponent+1);
  while(shift(bits)<range) {if(++bits>64) throw Error('Native width-growth research budget');}
  steps=shift(bits); offset=f(f(range)/f(steps)); high=f(f(low+f(range))-offset);
 }
 const maximum=i(steps-1), delta=f(high-low);
 let mul=maximum;
 if(Math.abs(delta)>f(0.001)) mul/=delta;
 const over=value => {const p=value*delta;return (Math.trunc(p)>>>0)>(maximum>>>0)||p>(maximum>>>0);};
 if(over(mul)) {
  let factor=0x3f800000;
  while(over(asFloat(factor)*mul)) {if(--factor<0x3f700000)throw Error('Multiplier research budget');}
  mul*=asFloat(factor);
 }
 const dec=1/maximum;
 const quant=value => {
  if(value<low)return low;
  if(value>high)return high;
  const q=Math.trunc(f(value-low)*mul+0.5)>>>0;
  return Math.min(high,f(q*dec*f(high-low)+low));
 };
 let effective=flags;
 for(const [bit,value] of [[1,low],[2,high],[4,0]])if(flags&bit && quant(value)===value)effective &=~bit;
 return {raw:false,bits,low,high,dec_mul:dec,high_low_mul:mul,flags:effective};
}
if(process.argv[2]) {
 const rows=JSON.parse(readFileSync(process.argv[2],'utf8'));
 const results=rows.map(r=>{
  const model=configure(r.bits,r.flags,r.low,r.high);
  const bytes=Buffer.from(r.config_hex,'hex');
  const expected=r.raw?{raw:true,bits:r.effective_bits}:{raw:false,bits:r.effective_bits,low:r.configured_low,high:r.configured_high,dec_mul:r.dec_mul,high_low_mul:bytes.readDoubleLE(8),flags:r.effective_flags};
  assert.deepEqual(model,expected,JSON.stringify({bits:r.bits,flags:r.flags,low:r.low,high:r.high}));
  return {input:{bits:r.bits,flags:r.flags,low:r.low,high:r.high},model,matched:true,decoderWidthSupported:model.raw||model.bits<=31};
 });
 const output={summary:{cases:results.length,matched:results.length,unsupportedWidths:results.filter(r=>!r.decoderWidthSupported).length},results};
 if(process.argv[3])writeFileSync(process.argv[3],JSON.stringify(output,null,2)+'\n');
 console.log(JSON.stringify(output.summary));
}
