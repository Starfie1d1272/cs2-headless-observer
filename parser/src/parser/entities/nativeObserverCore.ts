import {CSVCMsg_ServerInfo,CSVCMsg_FlattenedSerializer,CSVCMsg_ClassInfo,CSVCMsg_CreateStringTable,CSVCMsg_UpdateStringTable,CSVCMsg_PacketEntities} from '../../ts-proto/netmessages.js';
import {CNETMsg_Tick} from '../../ts-proto/networkbasetypes.js';
import {CMsgSource1LegacyGameEventList,CMsgSource1LegacyGameEvent,type CMsgSource1LegacyGameEventList_descriptor_t} from '../../ts-proto/gameevents.js';
import {SnappyDecoder} from '../../compression/wasm.js';
import {NativeStringTables} from './nativeStringTables.js';
import {NativeSchema} from './nativeSchema.js';
import {NativeSnapshotState} from './nativeSnapshotState.js';
import {NativePacketEntities} from './nativePacketEntities.js';
import {projectNativeEvent,projectRoundClock} from './nativeEventProjection.js';

export type NativeSourceIdentity=Readonly<{source:string;channel:number;world:number}>;
export type NativeMessageEnvelope=Readonly<NativeSourceIdentity&{sequence:number;messageId:number;body:Uint8Array;contextTick?:number}>;
export type NativeCoreRecord=Readonly<NativeSourceIdentity&{sequence:number;tick:number;type:string;[name:string]:unknown}>;

/** Ordered, synchronous data-plane decoder. Actual SDK/transport/control state
 * stays in its parent; this class never authenticates, sends ACKs or claims FULL.
 * Outputs carry generation fences so the parent can reject retired receipts.
 */
export class NativeObserverCore {
 private identity:NativeSourceIdentity;
 private sequence=0;
 private tick=-1;
 private lastCursor=-Infinity;
 private tables=new NativeStringTables(new SnappyDecoder());
 private snapshots=new NativeSnapshotState();
 private server:CSVCMsg_ServerInfo|undefined;
 private serializers:CSVCMsg_FlattenedSerializer|undefined;
 private classes:CSVCMsg_ClassInfo|undefined;
 private schema:NativeSchema|undefined;
 private packets:NativePacketEntities|undefined;
 private descriptors=new Map<number,CMsgSource1LegacyGameEventList_descriptor_t>();
 private descriptorGeneration=0;
 private knownCreationSequence=-1;
 private halted=false;
 constructor(identity:NativeSourceIdentity){this.validateIdentity(identity);this.identity=Object.freeze({...identity});}
 private validateIdentity(identity:NativeSourceIdentity){
  if(typeof identity.source!=='string'||!identity.source||identity.source.length>128||![identity.channel,identity.world].every(v=>Number.isSafeInteger(v)&&v>=0))throw new Error('Invalid source identity');
 }
 get currentIdentity(){return this.identity;}
 get ready(){return !this.halted&&this.schema!==undefined&&this.server!==undefined;}
 get committedTick(){return this.snapshots.lastTick;}
 /** This is evidence supplied by the control/world owner, never inferred from
  * a PacketEntities request for a future creation sequence. */
 admitCreationSequence(sequence:number){
  if(!Number.isInteger(sequence)||sequence<0||sequence>0xffffffff||sequence<this.knownCreationSequence)throw new Error('Invalid admitted creation sequence');
  this.knownCreationSequence=sequence;
 }
 resetWorld(identity:NativeSourceIdentity){
  this.validateIdentity(identity);
  if(identity.source!==this.identity.source||identity.channel!==this.identity.channel||identity.world<=this.identity.world)
   throw new Error('Invalid world transition');
  this.identity=Object.freeze({...identity});this.tick=-1;this.lastCursor=-Infinity;this.tables.clear();this.snapshots.reset();
  this.server=undefined;this.serializers=undefined;this.classes=undefined;this.schema=undefined;this.packets=undefined;
  this.descriptors.clear();this.descriptorGeneration++;this.knownCreationSequence=-1;this.halted=false;
 }
 private build(){
  if(this.schema||!this.server||!this.serializers||!this.classes)return;
  const max=this.server.max_classes;if(max===undefined)throw new Error('Missing ServerInfo max_classes');
  if(!this.classes.classes.length||this.classes.classes.some(c=>c.class_id===undefined||c.class_id>=this.classes!.classes.length))throw new Error('ClassInfo index exceeds announced class count');
  const schema=new NativeSchema(this.serializers,this.classes.classes.map(c=>({class_id:c.class_id,network_name:c.class_name})),max);
  this.schema=schema;this.packets=new NativePacketEntities(schema,this.snapshots,this.tables);
 }
 consume(input:NativeMessageEnvelope):readonly NativeCoreRecord[]{
  if(input.source!==this.identity.source||input.channel!==this.identity.channel||input.world!==this.identity.world)
   throw new Error('Retired message generation');
  if(input.sequence!==this.sequence+1||!Number.isSafeInteger(input.sequence))throw new Error('Message sequence mismatch');
  if(!Number.isInteger(input.messageId)||input.messageId<0||input.body.length>4*1024**2)throw new Error('Message envelope budget');
  if(input.contextTick!==undefined&&(!Number.isInteger(input.contextTick)||input.contextTick< -0x80000000||input.contextTick>0x7fffffff))throw new Error('Invalid transport message tick');
  this.sequence=input.sequence;
  const output:NativeCoreRecord[]=[];
  const record=(type:string,data:Record<string,unknown>={})=>output.push(Object.freeze({...this.identity,sequence:this.sequence,tick:input.contextTick??this.tick,networkTick:this.tick,type,...data}));
  if(this.halted){record('blocked',{reason:'world-reinitialization-required'});return Object.freeze(output);}
  try{
   switch(input.messageId){
    case 4:{const msg=CNETMsg_Tick.decode(input.body);if(msg.tick===undefined||msg.tick<0||msg.tick>0x7fffffff)throw new Error('Invalid network clock');this.tick=msg.tick;break;}
    case 40:{
     const msg=CSVCMsg_ServerInfo.decode(input.body);
     if(this.server&&(['server_count','map_name','max_classes','protocol','tick_interval'] as const).some(key=>this.server![key]!==msg[key]))throw new Error('ServerInfo changed without world boundary');
     if(!(msg.tick_interval!>0&&msg.tick_interval!<=1)||!msg.map_name)throw new Error('Invalid ServerInfo clock/map');
     this.server=msg;this.build();break;
    }
    case 41:if(this.schema)throw new Error('Serializer replacement needs world boundary');this.serializers=CSVCMsg_FlattenedSerializer.decode(input.body);this.build();break;
    case 42:{
     const msg=CSVCMsg_ClassInfo.decode(input.body);
     if(msg.create_on_client){if(!this.schema)throw new Error('Cached classes unavailable');break;}
     if(this.schema)throw new Error('Class replacement needs world boundary');this.classes=msg;this.build();break;
    }
    case 44:this.tables.create(CSVCMsg_CreateStringTable.decode(input.body));break;
    case 45:this.tables.update(CSVCMsg_UpdateStringTable.decode(input.body));break;
    case 51:{
     this.resetWorld({...this.identity,world:this.identity.world+1});
     record('world-reset',{reason:'clear-all-string-tables'});break;
    }
    case 55:{
     if(!this.packets)throw new Error('Entities before schema readiness');
     const msg=CSVCMsg_PacketEntities.decode(input.body);
     if(msg.max_spawngroup_creationsequence!==undefined&&msg.max_spawngroup_creationsequence>this.knownCreationSequence)
      throw new Error('Snapshot exceeds admitted world creation sequence');
     const priorEpoch=this.snapshots.epoch;
     const receipt=this.packets.decode(msg,input.contextTick??this.tick);
     if(receipt){
      record('receipt',receipt);
      if(receipt.epoch!==priorEpoch){record('gap',{reason:'snapshot-epoch-restarted'});this.lastCursor=-Infinity;}
      if(this.server?.tick_interval&&(receipt.tick-this.lastCursor)*this.server.tick_interval>=1){
       this.lastCursor=receipt.tick;
       record('cursor',{map:this.server.map_name??null,tickInterval:this.server.tick_interval,roundClock:projectRoundClock(this.schema,this.snapshots,receipt.tick),
        ...projectNativeEvent(this.schema,this.snapshots,this.tables,'cursor',{},new Map())});
      }
     }
     break;
    }
    case 70:break; // Ordinary forward handler021ba0; optional replay is not live state.
    case 205:{
     const msg=CMsgSource1LegacyGameEventList.decode(input.body),next=new Map<number,CMsgSource1LegacyGameEventList_descriptor_t>();
     if(msg.descriptors.length>512)throw new Error('Event descriptor budget');
     for(const d of msg.descriptors){
      if(d.eventid===undefined||d.eventid<0||d.eventid>=512||!d.name||d.name.length>256||next.has(d.eventid)||d.keys.length>256)
       throw new Error('Invalid event descriptor');
      const names=new Set<string>();for(const k of d.keys){if(!k.name||k.name.length>256||names.has(k.name)||k.type===undefined||k.type<0||!Number.isSafeInteger(k.type))throw new Error('Invalid event key descriptor');names.add(k.name);}
      next.set(d.eventid,d);
     }
     this.descriptors=next;this.descriptorGeneration++;
     record('event-subscriptions',{descriptorGeneration:this.descriptorGeneration,ids:Object.freeze([...next.keys()]),playerSlot:this.server?.player_slot??null});break;
    }
    case 207:{
     const msg=CMsgSource1LegacyGameEvent.decode(input.body),d=this.descriptors.get(msg.eventid??-1);
     if(d?.keys.some(k=>k.type!>9)){record('diagnostic',{reason:'unsupported-event-field-type',eventId:d.eventid});break;}
     if(!d){record('gap',{reason:'event-descriptor-missing'});break;}
     if(msg.keys.length!==d.keys.length)throw new Error('Event key count mismatch');
     const fields:Record<string,unknown>=Object.create(null);
     for(let i=0;i<d.keys.length;i++){
      const definition=d.keys[i]!,value=msg.keys[i]!;
      if(value.type!==undefined&&value.type!==definition.type)throw new Error('Event key type mismatch');
      const type=definition.type!;
      fields[definition.name!]=type===1?value.val_string??'':type===2?value.val_float??0:
       type===3||type===8?value.val_long??0:type===4||type===9?value.val_short??0:
       type===5?value.val_byte??0:type===6?value.val_bool??false:type===7?value.val_uint64??'0':null;
     }
     record('raw-event',{name:d.name,eventId:d.eventid,descriptorGeneration:this.descriptorGeneration,
      fields:Object.freeze(fields),eventServerTick:msg.server_tick??null,committedTick:this.snapshots.lastTick,
      map:this.server?.map_name??null,tickInterval:this.server?.tick_interval??null,
      ...projectNativeEvent(this.schema,this.snapshots,this.tables,d.name!,fields,new Map(d.keys.map(k=>[k.name!,k.type!]))) });break;
    }
    default:break; // Control owner handles its registered messages; no commands execute here.
   }
   record('checkpoint',{classCount:this.classes?.classes.length??0,schemaReady:this.ready,schemaFields:this.ready?this.serializers!.fields.length:0,serverInfo:!this.halted&&this.server!==undefined,stringTables:this.tables.count,committedTick:this.snapshots.lastTick});
  }catch(error){
   // A failed ordered message cannot lead to an ACK from a later unrelated
   // delta. Keep last visible entities but explicitly retire snapshot authority.
   const reason=error instanceof Error?error.message:'decode-failed';
   if(input.messageId===207){record('gap',{reason});}
   else{
    this.snapshots.recover();
    this.lastCursor=-Infinity;
    if(input.messageId!==55)this.halted=true;
    record('recovery',{reason,snapshotEpoch:this.snapshots.epoch,worldReinitialization:this.halted});
   }
   record('checkpoint',{classCount:this.classes?.classes.length??0,schemaReady:this.ready,schemaFields:this.ready?this.serializers!.fields.length:0,serverInfo:!this.halted&&this.server!==undefined,stringTables:this.tables.count,committedTick:this.snapshots.lastTick});
  }
  return Object.freeze(output);
 }
}
