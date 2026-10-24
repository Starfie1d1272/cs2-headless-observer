// Research-only compiled-field wrapper around the independent quantizer model.
import { configure } from './quantizer-model.mjs';
const f = Math.fround;
const max = f(3.4028234663852886e38);
export function configureField(bits, flags, low, high) {
  if (!(bits >= 1 && bits <= 31)) return { raw: true, bits: 32 };
  low = low === undefined || f(low) === -max ? 0 : f(low);
  high = high === undefined || f(high) === max ? f(((1 << bits) - 1) | 0) : f(high);
  if (!(high > low)) throw new Error('native-quantizer-invalid-range');
  return configure(bits, flags, low, high);
}
