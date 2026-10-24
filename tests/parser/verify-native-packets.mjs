import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const {NativeSnapshotState,NativePacketEntities,NativeSchema}=await import(pathToFileURL(resolve(process.argv[2])).href);
const root=process.env.GOTV_FIXTURE_ROOT;
const resultRoot=process.env.GOTV_RESULT_ROOT;
if(!root||!resultRoot)throw new Error('Use tools/verification/verify_cohesive_parser.mjs');
const codes=Object.fromEntries(JSON.parse(fs.readFileSync(root+'huffman-codebook-authority.json')).codes.map(r=>[r.symbol,[...r.wire_bits_first_to_last].map(Number)]));
const bits=(v,n)=>Array.from({length:n},(_,i)=>(v>>>i)&1);
const pack=wire=>{const b=new Uint8Array(Math.ceil(wire.length/8));wire.forEach((v,i)=>b[i>>>3]|=v<<(i&7));return b;};
const scalar=v=>[...codes[0],...codes[39],...bits(v,8)];
const schema=new NativeSchema({symbols:['Root','value','uint32','fixed8'],serializers:[{serializer_name_sym:0,serializer_version:0,fields_index:[0]}],fields:[{var_name_sym:1,var_type_sym:2,var_encoder_sym:3,polymorphic_types:[]}]},[{class_id:0,network_name:'Root'}],1);
let baseline=pack(scalar(5));
const state=new NativeSnapshotState();
const parser=new NativePacketEntities(schema,state,{classBaseline:()=>baseline,indexedBaseline:i=>i===2?pack(scalar(55)):undefined});
const create=(value,serial=1)=>[...bits(0,6),...bits(2,2),0,...bits(serial,17),...bits(0,8),...scalar(value)];
const update=value=>[...bits(0,6),...bits(0,2),...scalar(value)];
const msg=(tick,wire,extra={})=>({server_tick:tick,updated_entries:1,entity_data:pack(wire),alternate_baselines:[],cmd_recv_status:[],non_transmitted_entities:{header_count:0,data:new Uint8Array()},...extra});
let checks=0;const check=fn=>{fn();checks++;};
let result=parser.decode(msg(10,create(9),{update_baseline:true,serialized_entities:Uint8Array.of(scalar(9).length)}),10);
check(()=>assert.equal(result.full,true));check(()=>assert.equal(result.baselineAck,0));
check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,9));
result=parser.decode(msg(11,update(12),{delta_from:10,legacy_is_delta:false,has_pvs_vis_bits_deprecated:1}),11);
check(()=>assert.equal(result.full,false));check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,12));
check(()=>assert.throws(()=>parser.decode(msg(12,update(15),{delta_from:11,serialized_entities:Uint8Array.of(1)}),12),/boundary|budget|length|exhausted|Truncated/i));
check(()=>assert.equal(state.lastTick,11));check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,12));
check(()=>assert.throws(()=>parser.decode(msg(12,update(15),{delta_from:11,serialized_entities:Uint8Array.of(scalar(15).length,2)}),12),/Unused/));
check(()=>assert.equal(state.lastTick,11));
parser.decode(msg(12,create(18,2),{delta_from:11,baseline:1}),12);
check(()=>assert.equal(state.getEntity(0).serial,2));check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,18));
parser.decode(msg(13,[...bits(0,6),...bits(0,2),...codes[39]],{delta_from:12,alternate_baselines:[{entity_index:0,baseline_index:2}]}),13);
check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,55));
check(()=>assert.throws(()=>parser.decode(msg(14,update(1),{delta_from:13,alternate_baselines:[{entity_index:0,baseline_index:3}]}),14),/alternate baseline/));
check(()=>assert.equal(state.lastTick,13));
// A broken second entity must roll back the first staged mutation and the
// full-snapshot baseline reset together.
check(()=>assert.throws(()=>parser.decode(msg(14,[...create(77),...bits(0,6),...bits(2,2)],
 {updated_entries:2,update_baseline:true}),14),/exhausted/i));
check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,55));
check(()=>assert.equal(state.hasFrame(13),true));
// An explicitly present empty nontransmitted message uses the new path; its
// absence on a delta selects the native trailing-delete compatibility path.
parser.decode(msg(14,[...bits(1,6),...bits(1,6)],{delta_from:13,updated_entries:0,non_transmitted_entities:undefined}),14);
check(()=>assert.equal(state.getEntity(0),undefined));
check(()=>assert.throws(()=>parser.decode(msg(15,update(3),{delta_from:14}),15),/unknown entity/));
baseline=new Uint8Array();
check(()=>assert.throws(()=>parser.decode(msg(15,create(3)),15),/class baseline/));
check(()=>assert.equal(state.lastTick,14));
baseline=pack(scalar(5));
parser.decode(msg(15,create(3),{pending_full_frame:true,legacy_is_delta:true}),15);
check(()=>assert.equal(state.lastTick,15));check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,3));
check(()=>assert.throws(()=>parser.decode(msg(16,update(5)),17),/receive tick/));
parser.decode(msg(16,[],{updated_entries:0,delta_from:15,
 outofpvs_entity_updates:{count:1,data:pack([...bits(0,6),0,...scalar(20)])},
 non_transmitted_entities:{header_count:1,data:pack([...bits(0,6),1])}}),16);
check(()=>assert.equal(state.getEntity(0).fields.get([0]).value,20));
parser.decode(msg(17,[],{updated_entries:0,delta_from:16,
 outofpvs_entity_updates:{count:1,data:pack([...bits(0,6),0,...scalar(21)])},
 non_transmitted_entities:{header_count:1,data:pack([...bits(0,6),0])}}),17);
check(()=>assert.equal(state.getEntity(0),undefined));
const output={checks,passed:true,scope:'Synthetic fixed-profile PacketEntities through schema/field/snapshot components, not runtime or live GOTV acceptance'};
fs.writeFileSync(resultRoot+'native-packet-entities-comparison.json',JSON.stringify(output,null,2)+'\n');console.log(output);
