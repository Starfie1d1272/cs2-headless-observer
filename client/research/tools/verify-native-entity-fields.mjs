import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
if(!process.argv[2])throw new Error('Supply bundled ordinary entity-field module');
const {BitBuffer,NativeSchema,NativeEntityFields}=await import(pathToFileURL(resolve(process.argv[2])).href);
const root=process.env.GOTV_RESEARCH_ROOT??'.agent-tmp/gotv-research-plan/';
const codes=Object.fromEntries(JSON.parse(fs.readFileSync(root+'huffman-codebook-authority.json','utf8')).codes
 .map(r=>[r.symbol,[...r.wire_bits_first_to_last].map(Number)]));
const bits=(value,width)=>Array.from({length:width},(_,i)=>(value>>>i)&1);
const fp=value=>[1,...bits(value,2)];
const pack=wire=>{const data=new Uint8Array(Math.ceil(wire.length/8));wire.forEach((b,i)=>data[i>>>3]|=b<<(i&7));return data;};
const symbols=[],sym=s=>{let i=symbols.indexOf(s);if(i<0){i=symbols.length;symbols.push(s);}return i;};
const fields=[],field=(name,type,extra={})=>{
 const index=fields.length;fields.push({var_name_sym:sym(name),var_type_sym:sym(type),polymorphic_types:[],...extra});return index;
};
const u8=()=>({var_encoder_sym:sym('fixed8')});
const scalar=field('scalar','uint32',u8()),vector=field('items','CUtlVector< uint32 >',u8());
const pointer=field('pointer','Base*',{field_serializer_name_sym:sym('Base'),field_serializer_version:0,
 polymorphic_types:[{polymorphic_field_serializer_name_sym:sym('Variant'),polymorphic_field_serializer_version:0},
 {polymorphic_field_serializer_name_sym:sym('Other'),polymorphic_field_serializer_version:0}]});
const binary=field('binary','CUtlBinaryBlock'),fixed=field('fixed','uint32[2]',u8());
const baseValue=field('baseValue','uint32',u8()),variantValue=field('variantValue','uint32',u8()),otherValue=field('otherValue','uint32',u8());
const serializer=(name,indices)=>({serializer_name_sym:sym(name),serializer_version:0,fields_index:indices});
const schema=new NativeSchema({symbols,fields,serializers:[
 serializer('Root',[scalar,vector,pointer,binary,fixed]),serializer('Base',[baseValue]),
 serializer('Variant',[variantValue]),serializer('Other',[otherValue])
]},[{class_id:0,network_name:'Root'}],1);
const empty=NativeEntityFields.empty(schema,0);
const decode=(state,ops,payload,extraLength=0,limits)=>{
 const wire=[...ops,...codes[39],...payload],reader=new BitBuffer(pack([...wire,...Array(Math.max(0,extraLength)).fill(0)]));
 return NativeEntityFields.decode(schema,0,reader,state,wire.length+extraLength,limits).state;
};
const ops=[...codes[0],...codes[0],...codes[5],...codes[0],...codes[29],...codes[5],...codes[29],...codes[0],...codes[5],...codes[0]];
const payload=[...bits(5,8),...bits(2,8),...bits(10,8),...bits(20,8),1,...bits(1,6),...bits(30,8),
 ...bits(2,8),...bits(0xaa,8),...bits(0xbb,8),...bits(40,8),...bits(50,8)];
const state=decode(empty,ops,payload);
let checks=0;const check=run=>{run();checks++;};
check(()=>assert.equal(empty.fieldCount,0));
check(()=>assert.equal(state.get([0]).value,5));
check(()=>assert.equal(state.get([1,1]).value,20));
check(()=>assert.equal(state.get([2,0]).field.name,'variantValue'));
check(()=>assert.equal(state.get([2,0]).value,30));
check(()=>assert.equal(state.get([4]).value,2));
check(()=>assert.equal(state.get([4,1]).value,50));
check(()=>{const value=state.get([3]).value;value[0]=0;assert.equal(state.get([3]).value[0],0xaa);});
check(()=>{const value=[...state.entries()].find(r=>r.path.join('.')==='3').value;value[0]=0;assert.equal(state.get([3]).value[0],0xaa);});
const shrunk=decode(state,codes[1],bits(1,8));
check(()=>assert.equal(shrunk.get([1,1]),undefined));
check(()=>assert.equal(shrunk.get([1,0]).value,10));
check(()=>assert.equal(shrunk.getMetadata([1]).value,1));
check(()=>assert.equal(state.get([1,1]).value,20));
check(()=>assert.throws(()=>decode(shrunk,[...codes[10],...fp(0),...fp(0)],bits(60,8)),/out of bounds/));
const grown=decode(shrunk,codes[1],bits(3,8));
check(()=>assert.equal(grown.get([1,1]),undefined));
const kept=decode(state,codes[2],[1,...bits(1,6)]);
check(()=>assert.equal(kept.get([2,0]).value,30));
const absent=decode(state,codes[2],[0]);
check(()=>assert.equal(absent.get([2,0]),undefined));
check(()=>assert.equal(absent.getMetadata([2]).value,1));
check(()=>assert.equal(absent.getPointer([2]).present,false));
check(()=>assert.throws(()=>decode(absent,[...codes[9],...fp(3)],bits(60,8)),/absent pointer/));
const changed=decode(state,codes[2],[1,...bits(2,6)]);
check(()=>assert.equal(changed.get([2,0]),undefined));
check(()=>assert.equal(changed.getMetadata([2]).value,2));
const changedChild=decode(changed,[...codes[9],...fp(3)],bits(42,8));
check(()=>assert.equal(changedChild.get([2,0]).field.name,'otherValue'));
check(()=>assert.equal(changedChild.get([2,0]).value,42));
check(()=>assert.throws(()=>decode(state,codes[2],[1,...bits(0,6)])));
check(()=>assert.throws(()=>decode(state,codes[2],[1,...bits(3,6)])));
check(()=>assert.throws(()=>decode(state,codes[0],bits(7,7))));
check(()=>assert.throws(()=>decode(state,codes[0],bits(7,8),1)));
check(()=>assert.equal(state.get([0]).value,5));
check(()=>assert.throws(()=>decode(state,codes[0],bits(7,8),0,{paths:1})));
check(()=>assert.throws(()=>decode(state,[],[],0,{paths:1,arrayLength:10,records:1})));
check(()=>assert.throws(()=>decode(state,[...codes[0],...codes[0]],
 [...bits(99,8),...bits(0x81,8),...bits(0x80,8),...bits(4,8)]),/Array length budget/));
check(()=>assert.equal(state.get([0]).value,5));
check(()=>assert.equal(state.get([1,1]).value,20));
const inferred=decode(empty,[...codes[9],...fp(3)],bits(13,8));
check(()=>assert.equal(inferred.getPointer([2]).present,true));
check(()=>assert.equal(inferred.get([2,0]).field.name,'baseValue'));
const pointerVector=field('pointerVector','CUtlVector< Base* >',{
 field_serializer_name_sym:sym('Base'),field_serializer_version:0,
 polymorphic_types:[{polymorphic_field_serializer_name_sym:sym('Variant'),polymorphic_field_serializer_version:0}]});
const arraySchema=new NativeSchema({symbols,fields,serializers:[
 serializer('ArrayRoot',[pointerVector]),serializer('Base',[baseValue]),serializer('Variant',[variantValue])
]},[{class_id:0,network_name:'ArrayRoot'}],1);
const decodeArray=(previous,ops,payload)=>{
 const wire=[...ops,...codes[39],...payload];
 return NativeEntityFields.decode(arraySchema,0,new BitBuffer(pack(wire)),previous,wire.length).state;
};
const arrayState=decodeArray(NativeEntityFields.empty(arraySchema,0),
 [...codes[0],...codes[5],...codes[5]],[...bits(1,8),1,...bits(1,6),...bits(7,8)]);
check(()=>assert.equal(arrayState.get([0,0,0]).value,7));
check(()=>assert.equal(arrayState.getPointer([0,0]).present,true));
check(()=>assert.equal(arrayState.getMetadata([0,0]).value,1));
const arrayEmpty=decodeArray(arrayState,codes[0],bits(0,8));
check(()=>assert.equal(arrayEmpty.get([0,0,0]),undefined));
check(()=>assert.equal(arrayEmpty.getPointer([0,0]),undefined));
check(()=>assert.equal(arrayEmpty.getMetadata([0,0]).value,1));
const arrayGrown=decodeArray(arrayEmpty,codes[0],bits(1,8));
check(()=>assert.equal(arrayGrown.get([0,0,0]),undefined));
const arrayUpdated=decodeArray(arrayGrown,[...codes[17],...fp(0),...fp(0)],bits(11,8));
check(()=>assert.equal(arrayUpdated.get([0,0,0]).value,11));
check(()=>assert.equal(arrayUpdated.get([0,0,0]).field.name,'variantValue'));
check(()=>assert.equal(arrayState.get([0,0,0]).value,7));
const sparse=decode(empty,codes[0],bits(99,8));
const applied=sparse.applyTo(state);
check(()=>assert.equal(applied.get([0]).value,99));
check(()=>assert.equal(applied.get([1,1]).value,20));
check(()=>assert.equal(state.get([0]).value,5));
check(()=>assert.equal(empty.applyTo(state).get([2,0]).value,30));
check(()=>assert.equal(shrunk.applyTo(state).get([1,1]),undefined));
check(()=>assert.equal(arrayEmpty.applyTo(arrayState).get([0,0,0]),undefined));
check(()=>assert.equal(arrayUpdated.applyTo(arrayState).get([0,0,0]).value,11));
check(()=>assert.equal(inferred.applyTo(state).get([2,0]).field.name,'baseValue'));
check(()=>assert.equal(inferred.applyTo(state).getPointer([2]).selector,undefined));
check(()=>assert.throws(()=>sparse.applyTo(arrayState),/schema identity/));
const result={checks,passed:true,scope:'Transactional logical fields, array shrink and pointer lifetime in a new isolated component. Component checks only; integrated driver evidence is separate; no live acceptance.'};
fs.writeFileSync(root+'native-entity-fields-comparison.json',JSON.stringify(result,null,2)+'\n');
console.log(result);
