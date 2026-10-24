import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
const api=await import(pathToFileURL(resolve(process.argv[2])).href);
const {NativeObserverCore,CSVCMsg_ServerInfo:S,CSVCMsg_FlattenedSerializer:F,CSVCMsg_ClassInfo:C,CSVCMsg_CreateStringTable:T,CSVCMsg_UpdateStringTable:U,CSVCMsg_PacketEntities:P,CNETMsg_Tick:Tick,CMsgSource1LegacyGameEventList:L,CMsgSource1LegacyGameEvent:E}=api;
// Independent protobuf fixture writer; production generated bindings are decode-only.
const v=n=>{let x=BigInt.asUintN(64,BigInt(n)),b=[];do{let a=Number(x&127n);x>>=7n;b.push(a|(x?128:0));}while(x);return b;};
const encode=(schema,msg)=>{const out=[];for(const [name,[id,type]] of Object.entries(schema)){
 const value=msg[name];if(value===undefined)continue;for(const item of Array.isArray(value)?value:[value]){
  if(type==='n'){out.push(...v(id*8),...v(item));continue;}
  if(type==='f'){const b=new Uint8Array(4);new DataView(b.buffer).setFloat32(0,item,true);out.push(...v(id*8+5),...b);continue;}
  const b=type==='s'?new TextEncoder().encode(item):type==='b'?item:encode(type,item);out.push(...v(id*8+2),...v(b.length),...b);
 }}return Uint8Array.from(out);};
const schemas=new Map([
 [S,{server_count:[2,'n'],max_classes:[11,'n'],tick_interval:[13,'f'],map_name:[15,'s']}],
 [F,{serializers:[1,{serializer_name_sym:[1,'n'],serializer_version:[2,'n'],fields_index:[3,'n']}],symbols:[2,'s'],fields:[3,{var_type_sym:[1,'n'],var_name_sym:[2,'n'],var_encoder_sym:[10,'n']}]}],
 [C,{classes:[2,{class_id:[1,'n'],class_name:[3,'s']}]}],
 [T,{name:[1,'s'],num_entries:[2,'n'],string_data:[7,'b']}],
 [U,{table_id:[1,'n'],num_changed_entries:[2,'n'],string_data:[3,'b']}],
 [P,{updated_entries:[2,'n'],delta_from:[6,'n'],entity_data:[7,'b'],max_spawngroup_creationsequence:[10,'n'],server_tick:[12,'n'],non_transmitted_entities:[19,{header_count:[1,'n'],data:[2,'b']}]}],
 [Tick,{tick:[1,'n']}],
 [L,{descriptors:[1,{eventid:[1,'n'],name:[2,'s'],keys:[3,{type:[1,'n'],name:[2,'s']}]}]}],
 [E,{eventid:[2,'n'],keys:[3,{type:[1,'n'],val_string:[2,'s']}]}],
]);
const root=process.env.GOTV_FIXTURE_ROOT;
const resultRoot=process.env.GOTV_RESULT_ROOT;
if(!root||!resultRoot)throw new Error('Use tools/verification/verify_cohesive_parser.mjs');
const codes=Object.fromEntries(JSON.parse(fs.readFileSync(root+'huffman-codebook-authority.json')).codes.map(r=>[r.symbol,[...r.wire_bits_first_to_last].map(Number)]));
const bits=(v,n)=>Array.from({length:n},(_,i)=>(v>>>i)&1),bytes=b=>[...b].flatMap(v=>bits(v,8));
const pack=wire=>{const b=new Uint8Array(Math.ceil(wire.length/8));wire.forEach((v,i)=>b[i>>>3]|=v<<(i&7));return b;};
const scalar=v=>[...codes[0],...codes[39],...bits(v,8)];
const baseline=pack(scalar(5));
const create=[...bits(0,6),...bits(2,2),0,...bits(1,17),...bits(0,8),...scalar(9)];
const core=new NativeObserverCore({source:'ahead',channel:1,world:1});let sequence=0;
const send=(id,type,msg)=>core.consume({...core.currentIdentity,sequence:++sequence,messageId:id,body:type?encode(schemas.get(type),msg):new Uint8Array()});
let checks=0;const check=f=>{f();checks++;};
const initialize=()=>{
 send(40,S,{map_name:'de_test',server_count:1,tick_interval:1/64,max_classes:1});
 send(41,F,{symbols:['Root','value','uint32','fixed8'],serializers:[{serializer_name_sym:0,serializer_version:0,fields_index:[0]}],fields:[{var_name_sym:1,var_type_sym:2,var_encoder_sym:3,polymorphic_types:[]}]});
 send(42,C,{classes:[{class_id:0,class_name:'Root'}]});
 send(44,T,{name:'instancebaseline',num_entries:1,string_data:pack([1,1,0,...bytes([48,0]),1,...bits(baseline.length,17),...bytes(baseline)])});
};
initialize();check(()=>assert.equal(core.ready,true));
const packet={server_tick:10,updated_entries:1,entity_data:pack(create),alternate_baselines:[],cmd_recv_status:[],non_transmitted_entities:{header_count:0,data:new Uint8Array()},max_spawngroup_creationsequence:0};
send(4,Tick,{tick:10});
let out=send(55,P,packet);
check(()=>assert.match(out[0].reason,/admitted/));check(()=>assert.equal(core.committedTick,-1));check(()=>assert.equal(core.ready,true));
core.admitCreationSequence(0);out=send(55,P,packet);
check(()=>assert.equal(out[0].type,'receipt'));check(()=>assert.equal(out[0].tick,10));check(()=>assert.equal(out[0].world,1));
check(()=>assert.equal(core.committedTick,10));
const descriptor=name=>({descriptors:[{eventid:7,name,keys:[{name:'weapon',type:1}]}]});
send(205,L,descriptor('weapon_fire'));
const event={eventid:7,keys:[{type:1,val_string:'ak47'}]};
out=send(207,E,event);const first=out[0];
check(()=>assert.equal(first.name,'weapon_fire'));check(()=>assert.equal(first.tick,10));
send(4,Tick,{tick:9});send(205,L,descriptor('renamed_event'));out=send(207,E,event);
check(()=>assert.equal(out[0].tick,9));check(()=>assert.equal(out[0].name,'renamed_event'));
check(()=>assert.equal(first.name,'weapon_fire'));check(()=>assert.equal(first.fields.weapon,'ak47'));
check(()=>assert.equal(core.committedTick,10));
check(()=>assert.equal(out[0].identityResolved,false));
const before=core.committedTick;out=send(70,null,null);
check(()=>assert.equal(core.committedTick,before));check(()=>assert.equal(out.some(r=>r.type==='receipt'),false));
out=send(55,P,{...packet,delta_from:10,server_tick:11});
check(()=>assert.match(out[0].reason,/tick/));check(()=>assert.equal(core.committedTick,-1));
// Recovery may resume below the previous cursor; readiness cannot wait for its old tick.
send(4,Tick,{tick:3});out=send(55,P,{...packet,server_tick:3});
check(()=>assert.equal(out.some(r=>r.type==='receipt'&&r.tick===3),true));
check(()=>assert.equal(out.some(r=>r.type==='cursor'&&r.tick===3),true));
// Table failure is not repaired by a full snapshot using stale prior tables.
out=send(45,U,{table_id:99,num_changed_entries:0});
check(()=>assert.equal(out[0].worldReinitialization,true));check(()=>assert.equal(core.ready,false));
out=send(55,P,packet);check(()=>assert.equal(out[0].type,'blocked'));
core.resetWorld({...core.currentIdentity,world:2});initialize();
check(()=>assert.equal(core.ready,true));
check(()=>assert.throws(()=>core.consume({source:'ahead',channel:1,world:1,sequence:sequence+1,messageId:4,body:encode(schemas.get(Tick),{tick:10})}),/Retired/));
out=send(51,null,null);
check(()=>assert.equal(out[0].type,'world-reset'));check(()=>assert.equal(out[0].world,3));check(()=>assert.equal(core.ready,false));
check(()=>assert.equal(out[1].stringTables,0));
const other=new NativeObserverCore({source:'delayed',channel:1,world:1});
check(()=>assert.equal(other.committedTick,-1));check(()=>assert.equal(other.currentIdentity.world,1));
const result={checks,passed:true,scope:'Ordered protobuf data-plane core, receive tick and generation fences; not SDK/transport/worker integration or live acceptance'};
fs.writeFileSync(resultRoot+'native-observer-core-comparison.json',JSON.stringify(result,null,2)+'\n');console.log(result);
