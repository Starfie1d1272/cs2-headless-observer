import { readFileSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { configureField } from './quantizer-field-defaults.mjs';
const root = new URL('../', import.meta.url);
const rows = JSON.parse(readFileSync(new URL('quantizer-native-default-bounds.json', root), 'utf8'));
let matched = 0, rejected = 0;
for (const r of rows) {
  if (r.expected_native_fatal) {
    assert.throws(() => configureField(r.bits, r.flags, r.low, r.high), /invalid-range/);
    rejected++;
    continue;
  }
  assert.equal(r.completed, true);
  const bytes = Buffer.from(r.config_hex, 'hex');
  const expected = r.raw ? { raw: true, bits: r.effective_bits } : {
    raw: false, bits: r.effective_bits, low: r.configured_low, high: r.configured_high,
    dec_mul: r.dec_mul, high_low_mul: bytes.readDoubleLE(8), flags: r.effective_flags,
  };
  assert.deepEqual(configureField(r.bits, r.flags, r.low, r.high), expected);
  matched++;
  if (r.low === -3.4028234663852886e38 && r.high === 3.4028234663852886e38)
    assert.deepEqual(configureField(r.bits, r.flags, undefined, undefined), expected);
}
const result = { cases: rows.length, matchedValidConfigurations: matched,
  matchedNativeFatalRejections: rejected, missingBoundsMatchNativeSentinels: true };
writeFileSync(new URL('quantizer-default-bounds-comparison.json', root), JSON.stringify(result, null, 2) + '\n');
console.log(result);
