import type {BitBuffer} from '../ubitreader.js';
import {readNativeFieldPaths} from './nativeFieldPaths.js';
import {NativeSchema,type NativeMetadata,type NativeResolvedPath,type NativeSchemaField} from './nativeSchema.js';
import type {NativeWireValue} from './nativeFieldCodec.js';

export type NativeFieldRecord=Readonly<{
 path:readonly number[];field:NativeSchemaField;
 operation:NativeResolvedPath['operation'];value:NativeWireValue;
}>;
export type NativePointerState=Readonly<{present:boolean;selector?:number}>;
export type NativeEntityFieldLimits=Readonly<{paths:number;arrayLength:number;records:number}>;
const defaults:NativeEntityFieldLimits=Object.freeze({paths:65536,arrayLength:65536,records:262144});
const key=(path:readonly number[])=>path.join('.');
const copyValue=(value:NativeWireValue):NativeWireValue=>
 value instanceof Uint8Array?value.slice():Array.isArray(value)?Object.freeze([...value]):value;

/** Immutable logical fields; retained serialized metadata is a separate owner. */
export class NativeEntityFields {
 private constructor(
  readonly schema:NativeSchema,readonly classId:number,
  private readonly values:Map<string,NativeFieldRecord>,
  private readonly metadata:Map<string,NativeMetadata>,
  private readonly pointers:Map<string,NativePointerState>,
 ) {}
 static empty(schema:NativeSchema,classId:number):NativeEntityFields {
  schema.getClass(classId);
  return new NativeEntityFields(schema,classId,new Map(),new Map(),new Map());
 }
 get fieldCount(){return this.values.size;}
 getMetadata(path:readonly number[]):NativeMetadata|undefined{return this.metadata.get(key(path));}
 getPointer(path:readonly number[]):NativePointerState|undefined{return this.pointers.get(key(path));}
 get(path:readonly number[]):NativeFieldRecord|undefined {
  const record=this.values.get(key(path));
  return record&&Object.freeze({...record,value:copyValue(record.value)});
 }
 *entries(name?:string):IterableIterator<NativeFieldRecord> {
  // Yield defensive copies for each record matching the optional field name.
  for(const record of this.values.values())if(name===undefined||record.field.name===name)
   yield Object.freeze({...record,value:copyValue(record.value)});
 }

 /** Apply a stored sparse baseline to an existing logical object. Omitted
  * baseline fields do not erase reused same-class/same-serial entity fields.
  * Container and pointer operations still own their descendant lifetimes.
  */
 applyTo(previous:NativeEntityFields):NativeEntityFields {
  if(previous.schema!==this.schema||previous.classId!==this.classId)throw new Error('Entity schema identity mismatch');
  const values=new Map(previous.values),metadata=new Map(previous.metadata),pointers=new Map(previous.pointers);
  const sorted=[...this.values.values()].sort((a,b)=>{
   for(let i=0;i<Math.min(a.path.length,b.path.length);i++)if(a.path[i]!==b.path[i])return a.path[i]!-b.path[i]!;
   return a.path.length-b.path.length;
  });
  const prune=(path:readonly number[],minimum?:number)=>{
   const prefix=key(path)+'.';
   const remove=(candidate:string)=>candidate.startsWith(prefix)&&
    (minimum===undefined||Number(candidate.slice(prefix.length).split('.',1)[0])>=minimum);
   for(const candidate of values.keys())if(remove(candidate))values.delete(candidate);
   for(const candidate of pointers.keys())if(remove(candidate))pointers.delete(candidate);
  };
  for(const record of sorted){
   const resolved=this.schema.resolve(this.classId,record.path,path=>this.metadata.get(key(path)));
   for(const ancestor of resolved.ancestors){
    if(ancestor.kind!=='pointer')continue;
    const ancestorKey=key(ancestor.path),next=this.pointers.get(ancestorKey);
    if(!next?.present)throw new Error('Stored field below absent pointer');
    const old=pointers.get(ancestorKey);
    if(old?.present!==true||old.selector!==next.selector)prune(ancestor.path);
    pointers.set(ancestorKey,next);
    if(next.selector===undefined)metadata.delete(ancestorKey);
   }
   const name=key(record.path);
   if(record.operation==='array')prune(record.path,record.value as number);
   if(record.operation==='pointer'){
    const next=this.pointers.get(name);
    if(!next)throw new Error('Missing stored pointer state');
    const old=pointers.get(name);
    if(!next.present||old?.present!==true||old.selector!==next.selector)prune(record.path);
    pointers.set(name,next);
   }
   values.set(name,record);
  }
  // Serialized metadata and implicit pointer ancestors can exist without a
  // separate transmitted root value; preserve their independent ownership.
  for(const [name,value] of this.metadata)metadata.set(name,value);
  for(const [name,value] of this.pointers)if(!pointers.has(name))pointers.set(name,value);
  if(values.size>defaults.records||metadata.size>defaults.records||pointers.size>defaults.records)
   throw new Error('Entity field storage budget');
  return new NativeEntityFields(this.schema,this.classId,values,metadata,pointers);
 }

 /**
  * Work on private copies. Nothing is published until the entire field block
  * succeeds; the snapshot owner still controls the later packet-level commit.
  */
 static decode(
  schema:NativeSchema,classId:number,reader:BitBuffer,previous:NativeEntityFields,
  bitLength?:number,limits:NativeEntityFieldLimits=defaults,
 ):Readonly<{state:NativeEntityFields;consumedBits:number;changedPaths:readonly (readonly number[])[]}> {
  if(previous.schema!==schema||previous.classId!==classId)throw new Error('Entity schema identity mismatch');
  for(const name of ['paths','arrayLength','records'] as const) {
   const value=limits[name];
   if(!Number.isSafeInteger(value)||value<0||value>1_000_000)throw new Error('Invalid entity field limit: '+name);
  }
  const initialBits=reader.RemainingBits;
  if(bitLength!==undefined&&(!Number.isSafeInteger(bitLength)||bitLength<0||bitLength>initialBits))
   throw new Error('Invalid entity field bit length');
  const budget=bitLength??initialBits;
  const paths=readNativeFieldPaths(reader,limits.paths,budget);
  const values=new Map(previous.values),metadata=new Map(previous.metadata),pointers=new Map(previous.pointers);
  const meta=(prefix:readonly number[])=>metadata.get(key(prefix));
  const removeDescendants=(prefix:readonly number[],minimumIndex?:number)=>{
   const start=key(prefix)+'.';
   const removed=(candidate:string)=>{
    if(!candidate.startsWith(start))return false;
    if(minimumIndex===undefined)return true;
    const index=Number(candidate.slice(start.length).split('.',1)[0]);
    return index>=minimumIndex;
   };
   for(const candidate of values.keys())if(removed(candidate))values.delete(candidate);
   for(const candidate of pointers.keys())if(removed(candidate))pointers.delete(candidate);
   // Native delta metadata merge retains dormant descendant records. They
   // must not be confused with visible logical fields or live pointer objects.
  };
  for(const path of paths) {
   const resolved=schema.resolve(classId,path,meta);
   for(const ancestor of resolved.ancestors) {
    if(ancestor.kind==='pointer'&&pointers.get(key(ancestor.path))?.present===false)
     throw new Error('Field below absent pointer');
   }
   const name=key(path),field=resolved.field;
   let value:NativeWireValue;
   if(resolved.operation==='array') {
    if(!field.container)throw new Error('Missing array definition');
    // Ordinary fixed-array accessors use the declared extent without a wire
    // resize value. Dynamic vectors carry a varuint length.
    const size=field.container.kind==='fixed'?field.container.size:reader.ReadUVarInt32();
    if(!Number.isSafeInteger(size)||size<0||size>limits.arrayLength)throw new Error('Array length budget');
    removeDescendants(path,size);
    metadata.set(name,Object.freeze({kind:0,value:size}));
    value=size;
   } else if(resolved.operation==='pointer') {
    const present=reader.readBoolean();
    let selector:number|undefined;
    if(present&&field.variants.length) {
     selector=reader.readUbitVar();
     if(!Number.isInteger(selector)||selector<1||selector>field.variants.length)
      throw new Error('Invalid polymorphic pointer selector');
    }
    const old=pointers.get(name);
    if(!present||old?.present!==true||old.selector!==selector)removeDescendants(path);
    pointers.set(name,Object.freeze({present,...(selector===undefined?{}:{selector})}));
    if(selector!==undefined)metadata.set(name,Object.freeze({kind:1,value:selector}));
    value=present;
   } else {
    if(!field.codec)throw new Error('Missing field codec');
    value=field.codec(reader);
   }
   if(initialBits-reader.RemainingBits>budget)throw new Error('Entity field boundary exceeded');
   // A successfully decoded descendant establishes that its pointer ancestors
   // are present, even when a baseline did not include their presence field.
   for(const ancestor of resolved.ancestors) {
    if(ancestor.kind!=='pointer')continue;
    const ancestorKey=key(ancestor.path);
    if(!pointers.has(ancestorKey)) {
     const active=meta(ancestor.path);
     pointers.set(ancestorKey,Object.freeze({present:true,
      ...(active?.kind===1?{selector:active.value}:{})}));
    }
   }
   values.set(name,Object.freeze({path,field,operation:resolved.operation,value:copyValue(value)}));
   if(values.size>limits.records||metadata.size>limits.records||pointers.size>limits.records)
    throw new Error('Entity field storage budget');
  }
  const consumedBits=initialBits-reader.RemainingBits;
  if(bitLength!==undefined&&consumedBits!==bitLength)throw new Error('Entity field length mismatch');
  if(values.size>limits.records||metadata.size>limits.records||pointers.size>limits.records)
   throw new Error('Entity field storage budget');
  return Object.freeze({
   state:new NativeEntityFields(schema,classId,values,metadata,pointers),
   consumedBits,changedPaths:paths,
  });
 }
}
