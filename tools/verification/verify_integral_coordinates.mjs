import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const root=process.argv[2];
if(!root)throw new Error('Expected patched parser source directory');
const {BitBuffer}=await import(pathToFileURL(root+'/src/parser/ubitreader.ts'));
const {constructorFieldHelper:h,findFieldType}=await import(pathToFileURL(root+'/src/parser/entities/constructorFields.ts'));
const bits=(...parts)=>{const b=new Uint8Array(Math.ceil(parts.reduce((s,[,n])=>s+n,0)/8));let p=0;for(const[v,n]of parts)for(let i=0;i<n;i++,p++)b[p>>>3]|=((v>>>i)&1)<<(p&7);return b;};
const d=type=>h.findDecoder({encoder:'coord_integral',bitcount:0,varName:'fixture',fieldType:findFieldType(type)});
const profile={coord_integer_bits:9,coord_fractional_bits:4,coord_integer_bits_mp:5,coord_fractional_bits_mp:3,normal_fractional_bits:11,angle_bits:20};
// Literal wire cases from the game's two flag bits followed by sign+magnitude.
for(const [params,wide,narrow] of [[undefined,14,11],[profile,9,5]])for(const [flags,packed,expected]of [[0,0,0],[1,0,0],[2,0,1],[2,1,-1],[3,0,1],[3,1,-1],[2,98,50],[3,30,16]]){
 const width=flags&1?narrow:wide;
 const wire=bits([flags,2],...(flags&2?[[packed,width+1]]:[]),[0x5a,8]);
 const reader=new BitBuffer(wire).setCoordinateEncoding(params);
 assert.equal(h.decode(reader,d('float32')),expected);assert.equal(reader.ReadUBits(8),0x5a);
 const skip=new BitBuffer(wire).setCoordinateEncoding(params);h.skip(skip,d('float32'));assert.equal(skip.ReadUBits(8),0x5a);
}
const vector=bits([3,2],[30,6],[2,2],[99,10],[0,2],[0x5a,8]);
const reader=new BitBuffer(vector).setCoordinateEncoding(profile);
assert.deepEqual(h.decode(reader,d('Vector')),[16,-50,0]);assert.equal(reader.ReadUBits(8),0x5a);
const skip=new BitBuffer(vector).setCoordinateEncoding(profile);h.skip(skip,d('Vector'));assert.equal(skip.ReadUBits(8),0x5a);
assert.throws(()=>h.decode(new BitBuffer(bits([2,2])),d('float32')),/exhausted/);
const {EntityWasm}=await import(pathToFileURL(root+'/src/parser/entities/entityWasm.ts'));
for(const decoder of [d('float32'),d('Vector')]){
 const wasm=new EntityWasm(()=>[{decoder,indexDepth:-1,meta:undefined,children:null,element:null,propId:0,lifecycle:false,isResize:false,pathError:''}]);
 wasm.setEntity(0,0);assert.equal(wasm.enabled,false);
}
console.log('16 scalar integral vectors, negotiated vector, skip alignment, truncation and WASM fallback passed');
