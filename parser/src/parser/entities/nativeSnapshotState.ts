import type {NativeEntityFields} from './nativeEntityFields.js';

export type NativeEntity = Readonly<{id:number;classId:number;serial:number;fields:NativeEntityFields}>;
type Frame = Readonly<{members:ReadonlySet<number>;dormant:ReadonlySet<number>;outside:ReadonlySet<number>}>;
type Baseline = Readonly<{classId:number;fields:NativeEntityFields}>;
export type NativeSnapshotHeader=Readonly<{
 tick:number;serverTick:number;deltaFrom?:number;baseline:0|1;updateBaseline:boolean;
}>;
export type NativeSnapshotReceipt=Readonly<{epoch:number;tick:number;full:boolean;baselineAck:0|1|null}>;
export class NativeMissingSnapshot extends Error {
 constructor(readonly tick:number,readonly deltaFrom:number){super(`Missing snapshot ${deltaFrom} for ${tick}`);}
}
const checkId=(id:number)=>{if(!Number.isInteger(id)||id<0||id>=16384)throw new Error('Invalid entity index');};

/** Forward-viewer owner. Historical frames contain membership, never stale property clones.
 * A synchronous transaction publishes all entities, frame membership and both banks together.
 * Decoder exceptions cannot mutate the committed state. Recovery is an explicit caller action.
 */
export class NativeSnapshotState {
 private entities=new Map<number,NativeEntity>();
 private frames=new Map<number,Frame>();
 private banks:[Map<number,Baseline>,Map<number,Baseline>]=[new Map(),new Map()];
 private latest=-1;
 private generation=0;
 private revision=0;
 private waiting=true;
 private active=false;
 constructor(readonly maxFrames=512){if(!Number.isInteger(maxFrames)||maxFrames<1||maxFrames>65536)throw new Error('Invalid frame budget');}
 get lastTick(){return this.latest;}
 get epoch(){return this.generation;}
 get waitingFull(){return this.waiting;}
 get entityCount(){return this.entities.size;}
 *entries(){yield* this.entities.values();}
 getEntity(id:number){checkId(id);return this.entities.get(id);}
 hasFrame(tick:number){return this.frames.has(tick);}
 /** Retain last visible entities, but retire ACK, baselines and all pending receipts. */
 recover(){this.generation++;this.revision++;this.latest=-1;this.waiting=true;this.frames.clear();this.banks=[new Map(),new Map()];}
 reset(){this.recover();this.entities=new Map();}

 transact(header:NativeSnapshotHeader,decode:(draft:NativeSnapshotDraft)=>void):NativeSnapshotReceipt|null {
  if(this.active)throw new Error('Nested snapshot transaction');
  const {tick,serverTick,deltaFrom,baseline,updateBaseline}=header;
  if(!Number.isInteger(tick)||tick<1||tick>0x7fffffff||serverTick!==tick)throw new Error('Invalid snapshot receive tick');
  if(baseline!==0&&baseline!==1)throw new Error('Invalid baseline bank');
  const delta=deltaFrom!==undefined;
  if(delta&&(!Number.isInteger(deltaFrom)||deltaFrom>=tick||deltaFrom< -0x80000000))throw new Error('Invalid delta reference');
  if(delta&&this.waiting)return null;
  if(delta&&tick<=this.latest)throw new Error('Nonadvancing forward delta snapshot');
  const source=delta?this.frames.get(deltaFrom!):undefined;
  if(delta&&!source)throw new NativeMissingSnapshot(tick,deltaFrom!);
  const restart=!delta&&this.latest>tick;
  const epoch=this.generation+(restart?1:0),revision=this.revision;
  // 047960 clears BOTH baseline banks on every full; frame history is cleared
  // separately only for a backward full. Keep those transitions independent.
  const banks:[Map<number,Baseline>,Map<number,Baseline>]=delta?
   [this.banks[0],this.banks[1]]:[new Map(),new Map()];
  const next=updateBaseline?new Map(banks[baseline]):null;
  const draft=new NativeSnapshotDraft(this.entities,source,banks[baseline],next);
  this.active=true;
  try {
   const result=decode(draft) as unknown;
   if(result!==undefined)throw new Error('Snapshot decoder must be synchronous and return void');
   if(this.revision!==revision)throw new Error('Retired snapshot transaction');
   const state=draft.seal();
   const entities=new Map(this.entities);
   for(const [id,entity] of state.overlay)if(entity===null)entities.delete(id);else entities.set(id,entity);
   const frames=restart?new Map<number,Frame>():new Map(this.frames);
   frames.set(tick,{members:state.members,dormant:state.dormant,outside:state.outside});
   if(delta)for(const old of frames.keys())if(old<deltaFrom!)frames.delete(old);
   // A still-referenced base must survive a long chain of forward deltas.
   // Keep the same bounded history budget; retire unreferenced frames first.
   while(frames.size>this.maxFrames){
    const old=[...frames.keys()].find(value=>value!==tick&&(!delta||this.maxFrames===1||value!==deltaFrom));
    if(old===undefined)throw new Error('Snapshot frame budget cannot retain active base');frames.delete(old);
   }
   if(next)banks[baseline===0?1:0]=next;
   this.entities=entities;this.frames=frames;this.banks=banks;
   this.latest=tick;this.generation=epoch;this.waiting=false;this.revision++;
   return Object.freeze({epoch,tick,full:!delta,baselineAck:updateBaseline?baseline:null});
  } finally {draft.close();this.active=false;}
 }
}

export class NativeSnapshotDraft {
 private open=true;
 private overlay=new Map<number,NativeEntity|null>();
 private members:Set<number>;
 private dormant:Set<number>;
 private outside=new Set<number>();
 constructor(private current:ReadonlyMap<number,NativeEntity>,source:Frame|undefined,
  private bank:ReadonlyMap<number,Baseline>,private next:Map<number,Baseline>|null){
  this.members=new Set(source?.members);this.dormant=new Set(source?.dormant);
 }
 private check(id:number){if(!this.open)throw new Error('Closed snapshot transaction');checkId(id);}
 get(id:number){this.check(id);return this.overlay.has(id)?this.overlay.get(id)??undefined:this.current.get(id);}
 baseline(id:number,classId:number){this.check(id);const base=this.bank.get(id);return base?.classId===classId?base.fields:undefined;}
 put(entity:NativeEntity){
  this.check(entity.id);
  if(!Number.isInteger(entity.serial)||entity.serial<0||entity.serial>=131072||entity.fields.classId!==entity.classId)
   throw new Error('Invalid entity identity');
  this.overlay.set(entity.id,Object.freeze({...entity}));
 }
 enter(id:number){this.check(id);if(!this.get(id))throw new Error('Missing entered entity');this.members.add(id);}
 leave(id:number,remove=false){this.check(id);this.members.delete(id);if(remove)this.overlay.set(id,null);}
 markOutOfPvs(id:number){this.check(id);this.members.delete(id);this.outside.add(id);}
 markDormant(id:number,value:boolean){this.check(id);if(value)this.dormant.add(id);else this.dormant.delete(id);}
 present(id:number){this.check(id);return this.members.has(id)||this.dormant.has(id);}
 /** Called only by the native-equivalent baseline-update work item, not every update. */
 saveBaseline(id:number,fields?:NativeEntityFields){this.check(id);const entity=this.get(id);if(!entity)throw new Error('Missing baseline entity');
  const saved=fields??entity.fields;
  if(saved.classId!==entity.classId||saved.schema!==entity.fields.schema)throw new Error('Baseline schema identity mismatch');
  this.next?.set(id,Object.freeze({classId:entity.classId,fields:saved}));}
 removeAbsent(){
  if(!this.open)throw new Error('Closed snapshot transaction');
  for(const id of new Set([...this.current.keys(),...this.overlay.keys()]))if(!this.present(id))this.overlay.set(id,null);
 }
 seal(){if(!this.open)throw new Error('Closed snapshot transaction');this.open=false;
  return {overlay:this.overlay,members:this.members,dormant:this.dormant,outside:this.outside};}
 close(){this.open=false;}
}
