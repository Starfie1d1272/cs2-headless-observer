// Independent fixed-build cell-width metadata check, not a runtime decoder.
import { readFileSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { configure } from './quantizer-model.mjs';
const f = Math.fround, shift = n => 1 << (n & 31);
function cellWidth(bits, flags, low, high) {
  const q = configure(bits, flags, low, high);
  if(q.raw) return 0;
  low=f(low);high=f(high);flags &=15;
  if ((low===0 && flags&1)||(high===0 && flags&2)) flags &=~4;
  if(low===0 && flags&4)flags=(flags&~4)|1;
  if(high===0 && flags&4)flags=(flags&~4)|2;
  if(low>0||high<0)flags &=~4;
  if(flags&8)flags &=8;
  let offset=flags&3 ? f(f(high-low)/f(shift(bits))) : 0;
  if(flags&8){
    const delta=((Math.trunc(high)|0)-(Math.trunc(low)|0))|0;
    const exponent=delta>1 ?31-Math.clz32(delta):0;
    offset=f(f(shift(exponent+1))/f(shift(q.bits)));
  }
  const adjustedLow=flags&1?q.low:flags&2?f(q.low-offset):q.low;
  const adjustedHigh=flags&1?f(q.high+offset):q.high;
  const range=f(adjustedHigh-adjustedLow), rounded=Math.trunc(f(range+0.5))>>>0;
  return range<1||!rounded||(rounded&(rounded-1))!==0?0:31-Math.clz32(rounded);
}
const rows=['quantizer-native-matrix.json','origin-cell-native-configurations.json'].flatMap(name=>JSON.parse(readFileSync('.agent-tmp/gotv-research-plan/'+name,'utf8')));
const results=rows.map(r=>{
  const actual=cellWidth(r.bits,r.flags,r.low,r.high),expected=Buffer.from(r.config_hex,'hex')[30]>>>2;
  assert.equal(actual,expected,JSON.stringify({bits:r.bits,flags:r.flags,low:r.low,high:r.high}));
  return {input:{bits:r.bits,flags:r.flags,low:r.low,high:r.high},rangeWidth:actual,originCellShift:actual||10,matched:true};
});
writeFileSync('.agent-tmp/gotv-research-plan/origin-cell-width-comparison.json',JSON.stringify({cases:results.length,matched:results.length,results},null,2)+'\n');
console.log(JSON.stringify({cases:results.length,matched:results.length}));
