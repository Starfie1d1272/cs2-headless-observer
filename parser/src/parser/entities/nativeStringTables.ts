import type {CSVCMsg_CreateStringTable,CSVCMsg_UpdateStringTable} from '../../ts-proto/netmessages.js';
import type {SnappyDecoder} from '../../compression/types.js';
import {BitBuffer} from '../ubitreader.js';

/** Validate raw Snappy without allocating its claimed output. null means raw
 * fallback, not decode failure after an otherwise valid oversized block. */
export function nativeSnappySize(data:Uint8Array):number|null {
 let p=0,size=0,shift=0,done=false;
 for(let i=0;i<5;i++){
  const byte=data[p++];if(byte===undefined||(i===4&&byte>15))return null;
  size+=(byte&127)*2**shift;
  if(!(byte&128)){done=true;break;}shift+=7;
 }
 if(!done)return null;
 let written=0;
 const read=(n:number)=>{if(p+n>data.length)return null;let value=0;for(let i=0;i<n;i++)value+=data[p++]!*2**(i*8);return value;};
 while(p<data.length){
  const tag=data[p++]!,kind=tag&3;let length:number,offset:number|null;
  if(kind===0){
   length=tag>>>2;
   if(length<60)length++;else{const value=read(length-59);if(value===null)return null;length=value+1;}
   if(p+length>data.length)return null;p+=length;
  }else{
   if(kind===1){const low=read(1);if(low===null)return null;length=4+((tag>>>2)&7);offset=((tag&224)<<3)|low;}
   else{length=1+(tag>>>2);offset=read(kind===2?2:4);}
   if(offset===null||offset===0||offset>written)return null;
  }
  written+=length;if(written>size)return null;
 }
 return written===size?size:null;
}
export function nativeTableDecompress(data:Uint8Array,capacity:number,snappy:SnappyDecoder):Uint8Array {
 if(!Number.isSafeInteger(capacity)||capacity<0||capacity>64*1024**2)throw new Error('Invalid table decompression budget');
 const size=nativeSnappySize(data);
 if(size===null){if(data.length>capacity)throw new Error('Raw table capacity');return data.slice();}
 if(size>capacity)throw new Error('Snappy table capacity');
 const output=snappy.uncompress(data);
 if(output.length!==size)throw new Error('Snappy table output size');
 return output.slice();
}
type Entry=Readonly<{key:Uint8Array;value:Uint8Array;revision:number}>;
type Table=Readonly<{name:string;fixed:boolean;size:number;bits:number;flags:number;varint:boolean;entries:ReadonlyMap<number,Entry>}>;
const maximumEntryBytes=0x138800;
const decoder=new TextDecoder();
const keyIdentity=(bytes:Uint8Array)=>Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
/** All tables retain creation IDs and indexed keys, including unprojected names.
 * Local budgets below are deliberate observer bounds, not asserted wire limits. */
export class NativeStringTables {
 private tables:Table[]=[];
 private revision=0;
 private retainedBytes=0;
 private bytes(table:Table){let sum=0;for(const e of table.entries.values())sum+=e.key.length+e.value.length;return sum;}
 constructor(private snappy:SnappyDecoder){}
 get count(){return this.tables.length;}
 clear(){this.tables=[];this.retainedBytes=0;this.revision++;}
 get(tableId:number,index:number){const entry=this.tables[tableId]?.entries.get(index);return entry&&{
  key:decoder.decode(entry.key),value:entry.value.slice(),revision:entry.revision};}
 entryByName(name:string,index:number){const id=this.tables.findIndex(t=>t.name===name);return id<0?undefined:this.get(id,index);}
 classBaseline(classId:number){
  const table=this.tables.find(t=>t.name==='instancebaseline');if(!table)return undefined;
  const name=String(classId);for(const entry of table.entries.values())if(decoder.decode(entry.key)===name)return entry.value.slice();
  return undefined;
 }
 indexedBaseline(index:number){return this.tables.find(t=>t.name==='instancebaseline')?.entries.get(index)?.value.slice();}
 create(msg:CSVCMsg_CreateStringTable):number {
  if(this.tables.length>=1024||!msg.name||msg.name.length>1024||this.tables.some(t=>t.name===msg.name))throw new Error('Invalid string table name/count');
  const fixed=msg.user_data_fixed_size===true,size=msg.user_data_size??0,bits=msg.user_data_size_bits??0;
  if(!Number.isInteger(size)||size<0||size>maximumEntryBytes||!Number.isInteger(bits)||bits<0||(fixed&&bits>size*8))
   throw new Error('Invalid fixed string table size');
  let data=msg.string_data??new Uint8Array();
  if(data.length>32*1024**2)throw new Error('String table input budget');
  if(msg.data_compressed){
   const capacity=msg.uncompressed_size;
   if(capacity===undefined)throw new Error('Missing table uncompressed size');
   data=nativeTableDecompress(data,capacity,this.snappy);
  }
  const table:Table={name:msg.name,fixed,size,bits,flags:msg.flags??0,varint:msg.using_varint_bitcounts===true,entries:new Map()};
  const next=this.parse(table,data,msg.num_entries??0);
  const retained=this.retainedBytes+this.bytes(next);
  if(retained>128*1024**2)throw new Error('Global string table budget');
  this.retainedBytes=retained;
  const id=this.tables.length;this.tables.push(next);this.revision++;return id;
 }
 update(msg:CSVCMsg_UpdateStringTable):void {
  const id=msg.table_id;
  if(id===undefined||!Number.isInteger(id)||id<0||!this.tables[id])throw new Error('Unknown string table ID');
  const data=msg.string_data??new Uint8Array();if(data.length>32*1024**2)throw new Error('String table input budget');
  const next=this.parse(this.tables[id]!,data,msg.num_changed_entries??0);
  const retained=this.retainedBytes-this.bytes(this.tables[id]!)+this.bytes(next);
  if(retained>128*1024**2)throw new Error('Global string table budget');
  this.tables[id]=next;this.retainedBytes=retained;this.revision++;
 }
 private parse(table:Table,data:Uint8Array,count:number):Table {
  if(!Number.isInteger(count)||count<0||count>65536)throw new Error('String table entry count budget');
  const reader=new BitBuffer(data),entries=new Map(table.entries),history:Uint8Array[]=[];
  const names=new Set([...entries.values()].map(e=>keyIdentity(e.key)));
  let index=-1,total=0;
  for(const entry of entries.values())total+=entry.key.length+entry.value.length;
  const readKey=()=>{const out:number[]=[];while(true){const b=reader.ReadUBits(8);if(!b)break;if(out.length>=4096)throw new Error('String table key budget');out.push(b);}return Uint8Array.from(out);};
  for(let i=0;i<count;i++){
   index+=reader.readBoolean()?1:reader.ReadUVarInt32()+2;
   if(index<0||index>=65536)throw new Error('String table entry index budget');
   let supplied:Uint8Array|undefined;
   if(reader.readBoolean()){
    if(reader.readBoolean()){
     const position=reader.ReadUBits(5),length=reader.ReadUBits(5),prefix=history[position];
     if(!prefix||length>prefix.length)throw new Error('Invalid table key history');
     const suffix=readKey();supplied=new Uint8Array(length+suffix.length);supplied.set(prefix.subarray(0,length));supplied.set(suffix,length);
    }else supplied=readKey();
   }
   const old=entries.get(index),key=old?.key??supplied;
   if(!key)throw new Error('New string table entry lacks key');
   // Native AddString owns insertion/deduplication; do not invent sparse IDs.
   // Unsupported malformed/duplicate new-key streams fail closed locally.
   if(!old){
    if(index!==entries.size)throw new Error('Noncontiguous new string table entry');
    const name=keyIdentity(key);
    if(names.has(name))throw new Error('Duplicate new string table key');
    names.add(name);
   }
   let value:Uint8Array=new Uint8Array();
   if(reader.readBoolean()){
    let bitCount=table.bits,compressed=false;
    if(!table.fixed){
     if(table.flags&1)compressed=reader.readBoolean();
     const bytes=table.varint?reader.readUbitVar():reader.ReadUBits(17);
     if(bytes>maximumEntryBytes)throw new Error('String table value budget');bitCount=bytes*8;
    }
    if(bitCount>reader.RemainingBits)throw new Error('Truncated string table value');
    value=new Uint8Array(table.fixed?table.size:bitCount/8);
    const whole=bitCount>>>3;for(let byte=0;byte<whole;byte++)value[byte]=reader.ReadUBits(8);
    if(bitCount&7)value[whole]=reader.ReadUBits(bitCount&7);
    if(compressed)value=nativeTableDecompress(value,maximumEntryBytes,this.snappy);
   }
   total+=key.length+value.length-(old?old.key.length+old.value.length:0);
   if(total>64*1024**2)throw new Error('Retained string table byte budget');
   entries.set(index,Object.freeze({key:key.slice(),value,revision:this.revision+1}));
   history.push(key.slice(0,31));if(history.length>32)history.shift();
  }
  return Object.freeze({...table,entries});
 }
}
