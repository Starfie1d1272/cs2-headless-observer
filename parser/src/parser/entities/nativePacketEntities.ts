import {BitBuffer} from '../ubitreader.js';
import type {CSVCMsg_PacketEntities} from '../../ts-proto/netmessages.js';
import {NativeSchema} from './nativeSchema.js';
import {NativeEntityFields} from './nativeEntityFields.js';
import {NativeSnapshotState,type NativeSnapshotReceipt} from './nativeSnapshotState.js';

/** Table owner supplies revision-correct bytes. No missing baseline is silently empty. */
export interface NativeBaselineSource {
 classBaseline(classId:number):Uint8Array|undefined;
 indexedBaseline(index:number):Uint8Array|undefined;
}
/** Fixed-build ordinary forward adapter. Caller owns spawn-group admission,
 * world/schema/table readiness and recovery decisions; not a standalone live client.
 */
export class NativePacketEntities {
 constructor(readonly schema:NativeSchema,readonly snapshots:NativeSnapshotState,
  private readonly baselines:NativeBaselineSource){}
 decode(msg:CSVCMsg_PacketEntities,receiveTick:number):NativeSnapshotReceipt|null {
  const count=msg.updated_entries??0;
  const boundedCount=(value:number,name:string)=>{
   if(!Number.isInteger(value)||value<0||value>16384)throw new Error('Invalid '+name);
   return value;
  };
  boundedCount(count,'entity update count');
  if(msg.server_tick===undefined)throw new Error('Missing explicit server tick');
  const bank=msg.baseline??0;
  if(bank!==0&&bank!==1)throw new Error('Invalid baseline bank');
  const reader=new BitBuffer(msg.entity_data??new Uint8Array());
  const lengths:number[]=[];
  if(msg.serialized_entities?.length){
   const index=new BitBuffer(msg.serialized_entities);
   while(index.RemainingBits){
    if(lengths.length>=32768)throw new Error('Entity field length count budget');
    lengths.push(index.ReadUVarInt32());
   }
  }
  const overrides=new Map<number,number>();
  for(const entry of msg.alternate_baselines??[]){
   const id=entry.entity_index,index=entry.baseline_index;
   if(id===undefined||!Number.isInteger(id)||id<0||id>=16384||index===undefined||
    !Number.isInteger(index)||index<0||index>=65536||overrides.has(id))throw new Error('Invalid alternate baseline');
   overrides.set(id,index);
  }
  let lengthIndex=0;
  const decodeFields=(input:BitBuffer,previous:NativeEntityFields)=>{
   if(lengths.length&&lengthIndex>=lengths.length)throw new Error('Missing entity field length');
   const size=lengths.length?lengths[lengthIndex++]:undefined;
   return NativeEntityFields.decode(this.schema,previous.classId,input,previous,size).state;
  };
  const decodeBaseline=(classId:number,index?:number)=>{
   const bytes=index===undefined?this.baselines.classBaseline(classId):this.baselines.indexedBaseline(index);
   if(!bytes?.length)throw new Error(index===undefined?'Missing class baseline':'Missing alternate baseline');
   return NativeEntityFields.decode(this.schema,classId,new BitBuffer(bytes),NativeEntityFields.empty(this.schema,classId)).state;
  };
  return this.snapshots.transact({tick:receiveTick,serverTick:msg.server_tick,
   ...(msg.delta_from===undefined?{}:{deltaFrom:msg.delta_from}),baseline:bank,updateBaseline:msg.update_baseline===true},draft=>{
   const create=(input:BitBuffer,id:number)=>{
    const classId=input.ReadUBits(this.schema.classIdBits),serial=input.ReadUBits(17);
    input.ReadUVarInt32(); // Native entity creation token; not a frame tick or class ID.
    this.schema.getClass(classId);
    const old=draft.get(id);
    const current=old?.classId===classId&&old.serial===serial?old.fields:NativeEntityFields.empty(this.schema,classId);
    // Native create uses instance baseline if available, otherwise class key;
    // the alternate table-entry override belongs to update work items.
    const base=draft.baseline(id,classId)??decodeBaseline(classId);
    if(msg.update_baseline){
     const merged=decodeFields(input,base);
     draft.put({id,classId,serial,fields:merged.applyTo(current)});
     draft.saveBaseline(id,merged);
    }else{
     draft.put({id,classId,serial,fields:decodeFields(input,base.applyTo(current))});
    }
    draft.enter(id);
   };
   const update=(input:BitBuffer,id:number)=>{
    const entity=draft.get(id);
    if(!entity)throw new Error('Update of unknown entity');
    const alternate=overrides.get(id);
    const previous=alternate===undefined?entity.fields:decodeBaseline(entity.classId,alternate).applyTo(entity.fields);
    draft.put({...entity,fields:decodeFields(input,previous)});draft.enter(id);
   };
   const advance=(input:BitBuffer,id:number)=>{
    const next=id+1+input.readUbitVar();
    if(next<0||next>=16384)throw new Error('Invalid entity index');
    return next;
   };
   let id=-1;
   for(let i=0;i<count;i++){
    id=advance(reader,id);
    const type=reader.ReadUBits(2);
    if(type&1){draft.leave(id,type===3);continue;}
    if(type===2){create(reader,id);continue;}
    // Fixed-build 103800 consumes exactly two command bits; the deprecated
    // protobuf PVS flag does not add an older-demo two-bit payload here.
    update(reader,id);
   }
   const outside=msg.outofpvs_entity_updates;
   if(outside){
    const n=boundedCount(outside.count??0,'out-of-PVS count'),input=new BitBuffer(outside.data??new Uint8Array());
    id=-1;
    for(let i=0;i<n;i++){
     id=advance(input,id);
     if(input.ReadUBits(1))create(input,id);else update(input,id);
     draft.markOutOfPvs(id);
    }
   }
   const dormant=msg.non_transmitted_entities;
   if(dormant!==undefined){
    const n=boundedCount(dormant.header_count??0,'non-transmitted count'),input=new BitBuffer(dormant.data??new Uint8Array());
    id=-1;
    for(let i=0;i<n;i++){id=advance(input,id);draft.markDormant(id,input.ReadUBits(1)===1);}
    draft.removeAbsent();
   }else if(msg.delta_from!==undefined){
    const n=boundedCount(reader.readUbitVar(),'trailing delete count');id=-1;
    for(let i=0;i<n;i++){
     const step=reader.readUbitVar();
     if(step===0||id+step>=16384)throw new Error('Invalid trailing delete index');
     id+=step;draft.leave(id,true);
    }
   }
   if(lengthIndex!==lengths.length)throw new Error('Unused entity field lengths');
  });
 }
}
