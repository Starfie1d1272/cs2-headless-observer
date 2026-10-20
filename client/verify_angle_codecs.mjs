import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const root=process.argv[2];
if (!root) throw new Error('Expected patched parser source directory');
const {BitBuffer}=await import(pathToFileURL(root+'/src/parser/ubitreader.ts'));
const {constructorFieldHelper:h,findFieldType}=await import(pathToFileURL(root+'/src/parser/entities/constructorFields.ts'));
const bits=(...parts)=>{const b=new Uint8Array(Math.ceil(parts.reduce((s,[,n])=>s+n,0)/8));let p=0;for(const[v,n]of parts)for(let i=0;i<n;i++,p++)b[p>>>3]|=((v>>>i)&1)<<(p&7);return b;};
const decoder=(encoder,bitcount)=>h.findDecoder({encoder,bitcount,varName:'test',fieldType:findFieldType('QAngle')});
for(const encoder of ['qangle','qangle_precise','qangle_pitch_yaw']) for(const n of [1,7,13,24,31]) {
 const values=[0,2**(n-1),2**n-1],count=encoder==='qangle_pitch_yaw'?2:3;
 const wire=bits(...values.slice(0,count).map(v=>[v,n]),[0x5a,8]);
 const read=new BitBuffer(wire),d=decoder(encoder,n);
 const expected=values.map(v=>Math.fround(v*360/2**n));if(count===2)expected[2]=0;
 assert.deepEqual(h.decode(read,d),expected);assert.equal(read.ReadUBits(8),0x5a);
 const skip=new BitBuffer(wire);h.skip(skip,d);assert.equal(skip.ReadUBits(8),0x5a);
}
for(const n of [0,32]){
 const wire=bits([0x42b40000,32],[0x43340000,32],[0x5a,8]),d=decoder('qangle_pitch_yaw',n);
 const read=new BitBuffer(wire);assert.deepEqual(h.decode(read,d),[90,180,0]);assert.equal(read.ReadUBits(8),0x5a);
 const skip=new BitBuffer(wire);h.skip(skip,d);assert.equal(skip.ReadUBits(8),0x5a);
}
assert.deepEqual(h.decode(new BitBuffer(bits([0x42b40000,32],[0x43340000,32],[0,32])),decoder('qangle',32)),[90,180,0]);
for(const n of [-1,33])assert.throws(()=>decoder('qangle_pitch_yaw',n));
console.log('15 bounded angle profiles, two-axis raw encodings, skip alignment, raw three-axis compatibility and invalid bit counts passed');
const {EntityWasm}=await import(pathToFileURL(root+'/src/parser/entities/entityWasm.ts'));
for(const d of [decoder('qangle',13),decoder('qangle_pitch_yaw',0)]) {
 const accelerated=new EntityWasm(()=>[{decoder:d,indexDepth:-1,meta:undefined,children:null,element:null,propId:0,lifecycle:false,isResize:false,pathError:''}]);
 accelerated.setEntity(0,0);assert.equal(accelerated.enabled,false);
}
console.log('unsupported fixed WASM angle paths disable before packet execution');
