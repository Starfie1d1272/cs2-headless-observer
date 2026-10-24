import type { BitBuffer } from '../ubitreader.js';

/** Fixed CS2 14191 configuration, independently checked against native output. */
export type NativeQuantizer = Readonly<{
 raw: boolean; bits: number; low: number; high: number;
 multiplier: number; decodeMultiplier: number; flags: number; cellRangeBits: number;
}>;
const f = Math.fround;
const MAX_FLOAT = 3.4028234663852886e38;
const int32 = (value: number) => Math.trunc(value) | 0;
const shift = (bits: number) => 1 << (bits & 31);
const floatWord = new DataView(new ArrayBuffer(4));
const fromWord = (word: number) => {
 floatWord.setUint32(0, word, true);
 return floatWord.getFloat32(0, true);
};
export function createNativeQuantizer(bits: number, flags: number, low: number, high: number): NativeQuantizer {
 if (![bits, flags].every(Number.isInteger)) throw new Error('Invalid native quantizer metadata');
 if (!(bits >= 1 && bits <= 31)) return Object.freeze({raw:true,bits:32,low:-MAX_FLOAT,high:MAX_FLOAT,multiplier:0,decodeMultiplier:0,flags:0,cellRangeBits:0});
 low = f(low); high = f(high); flags &= 15;
 if (![low, high].every(Number.isFinite) || high <= low) throw new Error('Invalid native quantizer range');
 if ((low === 0 && flags & 1) || (high === 0 && flags & 2)) flags &= ~4;
 if (low === 0 && flags & 4) flags = (flags & ~4) | 1;
 if (high === 0 && flags & 4) flags = (flags & ~4) | 2;
 if (low > 0 || high < 0) flags &= ~4;
 if (flags & 8) flags &= 8;
 let steps = shift(bits), offset = 0;
 if (flags & 1) { offset = f(f(high - low) / f(steps)); high = f(high - offset); }
 else if (flags & 2) { offset = f(f(high - low) / f(steps)); low = f(low + offset); }
 if (flags & 8) {
  const delta = int32(int32(high) - int32(low));
  const exponent = delta > 1 ? 31 - Math.clz32(delta) : 0;
  const range = shift(exponent + 1);
  while (shift(bits) < range) {
   if (++bits > 31) throw new Error('Unsupported native quantizer derived width');
  }
  steps = shift(bits);
  offset = f(f(range) / f(steps));
  high = f(f(low + f(range)) - offset);
 }
 const maximum = int32(steps - 1), delta = f(high - low);
 let multiplier = maximum;
 if (Math.abs(delta) > f(0.001)) multiplier /= delta;
 const overflows = (value: number) => {
  const product = value * delta;
  return (Math.trunc(product) >>> 0) > (maximum >>> 0) || product > (maximum >>> 0);
 };
 if (overflows(multiplier)) {
  let word = 0x3f800000;
  while (overflows(fromWord(word) * multiplier)) {
   if (--word < 0x3f700000) throw new Error('Native quantizer multiplier budget');
  }
  multiplier *= fromWord(word);
 }
 const decodeMultiplier = 1 / maximum;
 const quantize = (value: number) => {
  if (value < low) return low;
  if (value > high) return high;
  const encoded = Math.trunc(f(value - low) * multiplier + 0.5) >>> 0;
  return Math.min(high, f(encoded * decodeMultiplier * f(high - low) + low));
 };
 const rangeLow = flags & 1 ? low : flags & 2 ? f(low - offset) : low;
 const rangeHigh = flags & 1 ? f(high + offset) : high;
 const range = f(rangeHigh - rangeLow), roundedRange = Math.trunc(f(range + 0.5)) >>> 0;
 const cellRangeBits = range < 1 || !roundedRange || (roundedRange & (roundedRange - 1)) !== 0
  ? 0 : 31 - Math.clz32(roundedRange);
 let effective = flags;
 for (const [bit, value] of [[1, low], [2, high], [4, 0]] as const)
  if ((flags & bit) && quantize(value) === value) effective &= ~bit;
 return Object.freeze({raw:false,bits,low,high,multiplier,decodeMultiplier,flags:effective,cellRangeBits});
}
export function decodeNativeQuantized(reader: BitBuffer, q: NativeQuantizer): number {
 if (q.raw) return reader.readFloat32LE();
 if ((q.flags & 1) && reader.readBoolean()) return q.low;
 if ((q.flags & 2) && reader.readBoolean()) return q.high;
 if ((q.flags & 4) && reader.readBoolean()) return 0;
 return Math.min(q.high, f(reader.ReadUBits(q.bits) * q.decodeMultiplier * f(q.high - q.low) + q.low));
}

/** Protobuf presence matters: omitted endpoints have native sentinel defaults. */
export function createNativeFieldQuantizer(field: {
 bit_count?: number; encode_flags?: number; low_value?: number; high_value?: number;
}): NativeQuantizer {
 const bits = field.bit_count ?? 0;
 let low = field.low_value ?? -MAX_FLOAT, high = field.high_value ?? MAX_FLOAT;
 if (bits >= 1 && bits <= 31) {
  if (low === -MAX_FLOAT) low = 0;
  if (high === MAX_FLOAT) high = f((shift(bits) - 1) | 0);
 }
 return createNativeQuantizer(bits, field.encode_flags ?? 0, low, high);
}
