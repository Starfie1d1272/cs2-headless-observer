import fs from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
if(!process.argv[2])throw new Error('Supply bundled ordinary path-reader module');
const {BitBuffer,createNativePathState,applyNativePathOperation,readNativeFieldPaths}
  =await import(pathToFileURL(resolve(process.argv[2])).href);
const root=process.env.GOTV_RESEARCH_ROOT??'.agent-tmp/gotv-research-plan/';
const caseBytes=gunzipSync(fs.readFileSync(root+'field-path-depth-model-cases.json.gz'));
assert.equal(createHash('sha256').update(caseBytes).digest('hex'),'f4ca2c5aba150bfc2a4a02e300144233177d826d08f1aff2deb5d9e15ebac451');
const cases=JSON.parse(caseBytes.toString('utf8'));
const native=JSON.parse(fs.readFileSync(root+'field-path-depth-emulation.json','utf8'));
assert.equal(native.summary.passed,cases.length);
let opCases=0;
for(const c of cases) {
  const state=createNativePathState();state.last=c.initial.length-1;
  c.initial.forEach((value,i)=>state.path[i]=value);
  const data=new Uint8Array(64);data[0]=c.first;
  const reader=new BitBuffer(data),start=reader.RemainingBits;
  applyNativePathOperation(c.op,reader,state);
  assert.deepEqual(state.path.slice(0,state.last+1),c.op===39?[32767]:c.expected,JSON.stringify(c));
  assert.equal(start-reader.RemainingBits,c.bits,JSON.stringify(c));
  opCases++;
}
const profile=JSON.parse(fs.readFileSync(root+'huffman-codebook-authority.json','utf8'));
const codes=Object.fromEntries(profile.codes.map(r=>[r.symbol,[...r.wire_bits_first_to_last].map(Number)]));
const pack=bits=>{
  const out=new Uint8Array(Math.ceil(bits.length/8));
  bits.forEach((v,i)=>out[i>>>3]|=v<<(i&7));return out;
};
const read=(wire,offset=0,budget=65536)=>{
  const reader=new BitBuffer(pack([...Array(offset).fill(1),...wire]));
  reader.consumePeeked(offset);
  const start=reader.RemainingBits,result=readNativeFieldPaths(reader,budget,wire.length);
  return {result,bits:start-reader.RemainingBits};
};
const fp17=n=>[0,0,0,1,...Array.from({length:17},(_,i)=>(n>>>i)&1)];
let listCases=0;
function check(fn){fn();listCases++;}
const longest=profile.codes.reduce((a,b)=>a.length>b.length?a:b).symbol;
for(let offset=0;offset<8;offset++) {
  check(()=>assert.deepEqual(read(codes[39],offset),{result:[],bits:codes[39].length}));
  const sentinel=[...codes[4],...fp17(32763)];
  check(()=>assert.deepEqual(read(sentinel,offset),{result:[],bits:sentinel.length}));
  check(()=>assert.throws(()=>read([...codes[4],0],offset)));
  check(()=>assert.throws(()=>read(codes[longest].slice(0,-1),offset)));
  check(()=>assert.deepEqual(read([...codes[0],...codes[0],...codes[2],...codes[39]],offset).result,[[0],[1],[4]]));
  check(()=>assert.deepEqual(read([...codes[7],...codes[27],...codes[39]],offset).result,[[0,0],[1]]));
}
check(()=>assert.throws(()=>{const s=createNativePathState();s.last=9;applyNativePathOperation(5,new BitBuffer(new Uint8Array()),s);}));
check(()=>assert.throws(()=>applyNativePathOperation(27,new BitBuffer(new Uint8Array()),createNativePathState())));
check(()=>assert.throws(()=>applyNativePathOperation(37,new BitBuffer(new Uint8Array()),createNativePathState())));
check(()=>assert.throws(()=>read([...codes[4],...fp17(32764)])));
check(()=>assert.deepEqual(read(codes[39],0,0).result,[]));
check(()=>assert.throws(()=>read([...codes[0],...codes[39]],0,0)));
const depth10=[...codes[0],...Array.from({length:9},()=>codes[5]).flat(),...codes[39]];
check(()=>assert.equal(read(depth10).result.at(-1).length,10));
check(()=>assert.throws(()=>read([...codes[0],...Array.from({length:10},()=>codes[5]).flat(),...codes[39]])));
const result={opcodeCases:opCases,listAndBoundaryCases:listCases,passed:true,
  scope:'New ordinary-viewer path-reader component versus retained fixed-native evidence; component checks only; integrated driver evidence is separate; no live acceptance.'};
fs.writeFileSync(root+'native-path-reader-comparison.json',JSON.stringify(result,null,2)+'\n');
console.log(result);
