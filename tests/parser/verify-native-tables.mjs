import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {NativeStringTables,nativeSnappySize,nativeTableDecompress,SnappyDecoder}=await import(pathToFileURL(resolve(process.argv[2])).href);
const root=process.env.GOTV_FIXTURE_ROOT,resultRoot=process.env.GOTV_RESULT_ROOT;
if(!root||!resultRoot)throw new Error('Use tools/verification/verify_cohesive_parser.mjs');
const snappy=new SnappyDecoder();
const bits=(v,n)=>Array.from({length:n},(_,i)=>(v>>>i)&1);
const bytes=b=>[...b].flatMap(v=>bits(v,8));
const str=s=>bytes([...new TextEncoder().encode(s),0]);
const pack=wire=>{const b=new Uint8Array(Math.ceil(wire.length/8));wire.forEach((v,i)=>b[i>>>3]|=v<<(i&7));return b;};
const entry=(key,value)=>[1,...(key===undefined?[0]:[1,0,...str(key)]),...(value===undefined?[0]:[1,...bits(value.length,17),...bytes(value)])];
let checks=0;const check=fn=>{fn();checks++;};
for(const item of JSON.parse(fs.readFileSync(root+'table-decompression-emulation.json')).cases){
 check(()=>assert.equal(Buffer.from(nativeTableDecompress(Buffer.from(item.input_hex,'hex'),2_000_000,snappy)).toString('hex'),item.expected_hex));
}
check(()=>assert.equal(nativeSnappySize(Uint8Array.of(255,255,255,255,15)),null));
check(()=>assert.throws(()=>nativeTableDecompress(Uint8Array.of(3,8,97,98,99),2,snappy),/Snappy table capacity/));
check(()=>assert.throws(()=>nativeTableDecompress(Uint8Array.of(255,255),1,snappy),/Raw table capacity/));
const tables=new NativeStringTables(snappy);
check(()=>assert.equal(tables.create({name:'unprojected',num_entries:0}),0));
check(()=>assert.equal(tables.create({name:'instancebaseline',num_entries:2,string_data:pack([...entry('0',[1,2]),...entry('1:alternate',[3])])}),1));
check(()=>assert.deepEqual([...tables.classBaseline(0)],[1,2]));
check(()=>assert.deepEqual([...tables.indexedBaseline(1)],[3]));
const copy=tables.indexedBaseline(0);copy[0]=99;
check(()=>assert.equal(tables.indexedBaseline(0)[0],1));
tables.update({table_id:1,num_changed_entries:1,string_data:pack(entry(undefined,[4]))});
check(()=>assert.deepEqual([...tables.classBaseline(0)],[4]));
check(()=>assert.equal(tables.get(1,0).key,'0'));
tables.update({table_id:1,num_changed_entries:1,string_data:pack(entry('ignored-replacement',undefined))});
check(()=>assert.equal(tables.get(1,0).key,'0'));
check(()=>assert.equal(tables.classBaseline(0).length,0));
// Keyless existing update contributes its resolved key to THIS blob's history.
tables.update({table_id:1,num_changed_entries:3,string_data:pack([
 ...entry(undefined,[5]),...entry(undefined,[6]),1,1,1,...bits(1,5),...bits(2,5),...str('new'),0])});
check(()=>assert.equal(tables.get(1,2).key,'1:new'));
check(()=>assert.throws(()=>tables.update({table_id:1,num_changed_entries:2,string_data:pack(entry(undefined,[7]))}),/exhausted/));
check(()=>assert.deepEqual([...tables.classBaseline(0)],[5]));
check(()=>assert.throws(()=>tables.update({table_id:9,num_changed_entries:0}),/Unknown/));
const fixed=tables.create({name:'fixed',user_data_fixed_size:true,user_data_size:2,user_data_size_bits:9,num_entries:1,
 string_data:pack([1,1,0,...str('k'),1,...bits(0x1ff,9)])});
check(()=>assert.deepEqual([...tables.get(fixed,0).value],[255,1]));
check(()=>assert.throws(()=>tables.create({name:'bad',user_data_fixed_size:true,user_data_size:1,user_data_size_bits:9}),/fixed/));
check(()=>assert.equal(tables.count,3));
const literal=b=>Uint8Array.of(b.length,(b.length-1)<<2,...b);
const wire=pack(entry('x',[8]));
const compressed=tables.create({name:'compressed',num_entries:1,data_compressed:true,uncompressed_size:wire.length,string_data:literal(wire)});
check(()=>assert.equal(tables.get(compressed,0).value[0],8));
check(()=>assert.throws(()=>tables.create({name:'oversized',num_entries:1,data_compressed:true,uncompressed_size:1,string_data:literal(wire)}),/capacity/));
check(()=>assert.equal(tables.count,4));
tables.clear();check(()=>assert.equal(tables.count,0));check(()=>assert.equal(tables.classBaseline(0),undefined));
const output={checks,passed:true,scope:'Transactional indexed string tables and fixed-build Snappy/raw fallback; no runtime/live acceptance'};
fs.writeFileSync(resultRoot+'native-string-tables-comparison.json',JSON.stringify(output,null,2)+'\n');console.log(output);
