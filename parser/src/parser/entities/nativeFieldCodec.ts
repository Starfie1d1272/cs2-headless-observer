import type { BitBuffer } from '../ubitreader.js';
import { createNativeFieldQuantizer, decodeNativeQuantized } from './nativeQuantizedFloat.js';

/** Fixed-build wire values. Accessors/projection own storage narrowing and identity. */
export type NativeFloat = number | Readonly<{ kind: 'float32-nonfinite'; bits: number }>;
export type NativeWireValue = NativeFloat | bigint | boolean | Uint8Array | readonly NativeFloat[] | undefined;
export type NativeCoordinateProfile = Readonly<{
 integer: number; fraction: number; integerMp: number; fractionMp: number; normal: number; angle: number;
}>;
export type NativeFieldEncoding = Readonly<{
 category: number; dimensions: number; encoder?: string;
 bit_count?: number; encode_flags?: number; low_value?: number; high_value?: number;
}>;
export type NativeCodec = (reader: BitBuffer) => NativeWireValue;
const f = Math.fround;
const floatView = new DataView(new ArrayBuffer(4));
function readRawFloat32(r: BitBuffer): NativeFloat {
 const bits=r.ReadUBits(32);
 if((bits&0x7f800000)===0x7f800000)return Object.freeze({kind:'float32-nonfinite',bits});
 floatView.setUint32(0,bits,true);return floatView.getFloat32(0,true);
}

export function nativeCoordinateProfile(input?: {
 coord_integer_bits?: number; coord_fractional_bits?: number; coord_integer_bits_mp?: number;
 coord_fractional_bits_mp?: number; normal_fractional_bits?: number; angle_bits?: number;
}): NativeCoordinateProfile {
 const values = input ? [input.coord_integer_bits,input.coord_fractional_bits,input.coord_integer_bits_mp,
  input.coord_fractional_bits_mp,input.normal_fractional_bits,input.angle_bits] : [14,5,11,3,11,20];
 if (values.some(v => !Number.isInteger(v) || v! < 1 || v! > 31)) throw new Error('Invalid coordinate profile');
 const [integer,fraction,integerMp,fractionMp,normal,angle] = values as [number,number,number,number,number,number];
 if (Math.max(integer,integerMp)+3+Math.max(fraction,fractionMp)>32) throw new Error('Coordinate profile bit budget');
 return Object.freeze({integer,fraction,integerMp,fractionMp,normal,angle});
}
function readCoord(r: BitBuffer,p: NativeCoordinateProfile): number {
 const integer=r.readBoolean(),fraction=r.readBoolean();
 if (!integer&&!fraction) return 0;
 const negative=r.readBoolean(),whole=integer?r.ReadUBits(p.integer)+1:0;
 const part=fraction?f(r.ReadUBits(p.fraction)*f(2**-p.fraction)):0;
 const value=f(f(whole)+part);return negative?-value:value;
}
function readIntegral(r: BitBuffer,p: NativeCoordinateProfile): number {
 const compact=r.readBoolean();if(!r.readBoolean())return 0;
 const negative=r.readBoolean(),value=f(r.ReadUBits(compact?p.integerMp:p.integer)+1);
 return negative?-value:value;
}
function presentTriple(r: BitBuffer,read:()=>number): number[] {
 const present=[r.readBoolean(),r.readBoolean(),r.readBoolean()];
 return present.map(on=>on?read():0);
}
function readNormal(r: BitBuffer,p: NativeCoordinateProfile): number[] {
 const x=r.readBoolean(),y=r.readBoolean(),scale=f(1/(2**p.normal-1));
 const component=()=>{const sign=r.readBoolean(),value=f(r.ReadUBits(p.normal)*scale);return sign?-value:value;};
 const a=x?component():0,b=y?component():0,negative=r.readBoolean();
 const sum=f(f(a*a)+f(b*b)),z=sum<1?f(Math.sqrt(f(1-sum))):0;
 return [a,b,negative?-z:z];
}
function unsigned32(r: BitBuffer): number {
 let value=0;
 for(let n=0;n<5;n++){
  const byte=r.ReadByte();if(n===4&&byte>15)throw new Error('Unsigned varint32 overflow');
  value|=(byte&127)<<(n*7);if(!(byte&128))return value>>>0;
 }
 throw new Error('Unterminated varint32');
}
function bytes(r: BitBuffer,size:number,limit:number): Uint8Array {
 if(!Number.isSafeInteger(size)||size<0||size>limit||size*8>r.RemainingBits)throw new Error('Binary field budget');
 const result=new Uint8Array(size);r.readBytes(result);return result;
}
/** Bounds are observer policy, not protocol constants. Strings preserve original bytes. */
export function createNativeFieldCodec(field:NativeFieldEncoding,p:NativeCoordinateProfile,
 limits:Readonly<{stringBytes:number;binaryBytes:number}>={stringBytes:65536,binaryBytes:4*1024*1024}):NativeCodec {
 const {category,dimensions:dim}=field,encoder=(field.encoder??'default').toLowerCase();
 if(!Number.isInteger(category)||category<0||category>7||!Number.isInteger(dim)||dim<(category===6?0:1))throw new Error('Invalid native wire type');
 if(!Number.isSafeInteger(limits.stringBytes)||limits.stringBytes<1||!Number.isSafeInteger(limits.binaryBytes)||limits.binaryBytes<0)throw new Error('Invalid field limits');
 const stringLimit=limits.stringBytes,binaryLimit=limits.binaryBytes;
 if(category===3){
  if(![1,2,3,4,6,8].includes(dim))throw new Error('Unsupported float dimension');
  if(encoder==='default'){
   const q=createNativeFieldQuantizer(field);
   return r=>{const read=()=>q.raw?readRawFloat32(r):decodeNativeQuantized(r,q);return dim===1?read():Array.from({length:dim},read);};
  }
  if(encoder==='coord'||encoder==='coord_integral'){
   if(![1,3,6,8].includes(dim))throw new Error('Unsupported coordinate dimension');
   const first=encoder==='coord'?readCoord:readIntegral;
   return r=>{
    if(dim===1)return first(r,p);
    const values=[first(r,p),first(r,p),first(r,p)];
    if(dim===6||dim===8)values.push(...presentTriple(r,()=>readCoord(r,p)));
    return values; // dimension8 retains the six matrix-conversion inputs, not a render matrix.
   };
  }
  if(encoder==='normal'){
   if(dim!==3)throw new Error('Unsupported normal dimension');return r=>readNormal(r,p);
  }
  if(['qangle','qangle_precise','qangle_pitch_yaw'].includes(encoder)){
   if(dim!==3)throw new Error('Unsupported angle dimension');
   const width=field.bit_count??0;
   if(!Number.isInteger(width)||width<0||width>32)throw new Error('Invalid angle bitcount');
   const count=encoder==='qangle_pitch_yaw'?2:3;
   return r=>{
    if(width===0&&encoder==='qangle')return presentTriple(r,()=>readCoord(r,p));
    if(width===0&&encoder==='qangle_precise')return presentTriple(r,()=>f(f(r.ReadUBits(p.angle)*(360/2**p.angle))-180));
    const raw=encoder!=='qangle_precise'&&(width===0||width===32);
    const values=Array.from({length:count},()=>raw?readRawFloat32(r):f((r.ReadUBits(width)|0)*(360/(2**(width&31)))));
    if(count===2)values.push(0);return values;
   };
  }
  throw new Error('Unsupported float encoder: '+encoder);
 }
 if(dim!==1&&!(category===6&&dim===0))throw new Error('Unsupported scalar dimension');
 if(category===1||category===2){
  const signed=category===1;
  switch(encoder){
   case 'default':return r=>{const value=r.readUVarInt64();return signed?(value>>1n)^-(value&1n):value;};
   case 'fixed8':return r=>{const value=r.ReadUBits(8);return signed?(value<<24)>>24:value;};
   case 'fixed32':return r=>{const value=r.ReadUBits(32);return signed?value|0:value;};
   case 'fixed64':return r=>{const value=BigInt(r.ReadUBits(32))|(BigInt(r.ReadUBits(32))<<32n);return signed?BigInt.asIntN(64,value):value;};
   default:throw new Error('Unsupported integer encoder: '+encoder);
  }
 }
 if(encoder!=='default')throw new Error('Unsupported scalar encoder: '+encoder);
 if(category===0)return ()=>undefined;
 if(category===4)return r=>readRawFloat32(r); // native double-family wire encoding is float32
 if(category===7)return r=>r.readBoolean();
 if(category===6)return r=>bytes(r,unsigned32(r),binaryLimit);
 if(category===5)return r=>{
  const result:number[]=[];
  for(let n=0;n<=stringLimit;n++){
   const value=r.ReadByte();if(!value)return Uint8Array.from(result);
   if(n===stringLimit)break;result.push(value);
  }
  throw new Error('String field budget');
 };
 throw new Error('Unsupported native wire type');
}
