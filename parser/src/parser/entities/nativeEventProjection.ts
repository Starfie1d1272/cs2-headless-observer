import {CMsgPlayerInfo} from '../../ts-proto/networkbasetypes.js';
import type {NativeSnapshotState,NativeEntity} from './nativeSnapshotState.js';
import type {NativeStringTables} from './nativeStringTables.js';
import type {NativeSchema} from './nativeSchema.js';
import type {NativeWireValue} from './nativeFieldCodec.js';
const steamId=(value:unknown)=>typeof value==='bigint'||typeof value==='string'?(/^7656119\d{10}$/.test(String(value))?String(value):null):null;
const field=(entity:NativeEntity,name:string):NativeWireValue=>{
 let found:NativeWireValue;let count=0;
 for(const record of entity.fields.entries())if(record.field.name===name&&record.operation==='value'){found=record.value;count++;}
 return count===1?found:undefined;
};
const uint32Value=(v:NativeWireValue)=>typeof v==='bigint'&&v>=0n&&v<=0xffffffffn?Number(v):typeof v==='number'&&Number.isInteger(v)&&v>=0&&v<=0xffffffff?v:undefined;
export interface NativePlayerIdentity {
 readonly domain:'player-controller-slot';
 readonly slot:number;
 readonly steamId:string;
 readonly userId:number|null;
 readonly controller:Readonly<{index:number;serial:number}>;
}
/** No historical slot guessing: a missing/mismatched identity remains null. */
export function projectNativeEvent(schema:NativeSchema|undefined,snapshots:NativeSnapshotState,tables:NativeStringTables,
 name:string,fields:Readonly<Record<string,unknown>>,types:ReadonlyMap<string,number>){
 const player=(key:string):NativePlayerIdentity|null=>{
  if(!schema||snapshots.waitingFull||types.get(key)!==9)return null;
  const raw=fields[key];if(typeof raw!=='number'||!Number.isInteger(raw))return null;
  const value=raw&65535;if(value===65535)return null;const slot=value&255;
  const controller=snapshots.getEntity(slot+1);
  if(!controller||!schema.getClass(controller.classId).name.endsWith('PlayerController'))return null;
  const id=steamId(field(controller,'m_steamID'));if(!id)return null;
  const info=tables.entryByName('userinfo',slot);if(!info?.value.length)return null;
  let stored;try{stored=CMsgPlayerInfo.decode(info.value);}catch{return null;}
  if(stored.fakeplayer||stored.ishltv||(steamId(stored.xuid)??steamId(stored.steamid))!==id)return null;
  return Object.freeze({domain:'player-controller-slot' as const,slot,steamId:id,
   userId:typeof stored.userid==='number'&&Number.isInteger(stored.userid)&&stored.userid>0?stored.userid:null,
   controller:Object.freeze({index:controller.id,serial:controller.serial})});
 };
 // Type9 identifies a controller independently of the optional type8 pawn.
 // A failed full native pawn proof must not erase a separately verified player.
 const pawn=(key:string):Readonly<{index:number;serial:number}>|null=>{
   if(!players[key]||types.get(key+'_pawn')!==8)return null;
   const controller=snapshots.getEntity(players[key]!.controller.index)!;
   const pawnKey=key+'_pawn';
   const rawPawn=fields[pawnKey];if(typeof rawPawn!=='number'||!Number.isInteger(rawPawn))return null;
   const handle=rawPawn>>>0;if(handle===0xffffffff||handle===0xfffffffe)return null;
   const pawn=snapshots.getEntity(handle&0x7fff);
   if(!pawn||pawn.serial!==(handle>>>15))return null;
   // Controller's field uses the DIFFERENT compressed14/10-bit handle domain.
   const linked=uint32Value(field(controller,'m_hPlayerPawn')??field(controller,'m_hPawn'));
   if(typeof linked!=='number'||(linked&0x3fff)!==pawn.id||((linked>>>14)&0x3ff)!==(pawn.serial&0x3ff))return null;
   return Object.freeze({index:pawn.id,serial:pawn.serial});
 };
 let warmup:boolean|null=null,round:number|null=null;
 if(schema&&!snapshots.waitingFull){
  for(const entity of snapshots.entries())if(schema.getClass(entity.classId).name==='CCSGameRulesProxy'){
   const w=field(entity,'m_bWarmupPeriod'),r=uint32Value(field(entity,'m_totalRoundsPlayed'));
   warmup=typeof w==='boolean'?w:null;round=typeof r==='number'&&Number.isInteger(r)?r:null;break;
  }
 }
 const players:Record<string,NativePlayerIdentity|null>=Object.create(null);
 for(const [key,type] of types)if(type===9)players[key]=player(key);
 Object.freeze(players);
 const pawns:Record<string,Readonly<{index:number;serial:number}>|null>=Object.create(null);
 for(const [key,type] of types)if(type===9&&types.has(key+'_pawn'))pawns[key]=pawn(key);
 Object.freeze(pawns);
 const actor=name==='player_death'?players.attacker?.steamId??null:name==='weapon_fire'?players.userid?.steamId??null:null;
 const target=name==='player_death'?players.userid?.steamId??null:null;
 return Object.freeze({actor,target,warmup,round,players,pawns,
  weapon:typeof fields.weapon==='string'?fields.weapon:null,
  identityResolved:name==='weapon_fire'?actor!==null:name==='player_death'?actor!==null&&target!==null:false});
}
