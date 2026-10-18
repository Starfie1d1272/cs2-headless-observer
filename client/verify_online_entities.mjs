import console from 'node:console';
import process from 'node:process';
// Synthetic protocol bitstreams. This verifies decoder semantics, not an online server.
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const source = process.argv[2];
if (!source) throw new Error('Expected the patched parser source directory');
const load = (path) => import(pathToFileURL(resolve(source, path)).href);
const { EntityParser } = await load('src/parser/entities/entityParser.ts');
const { OnlineEntityState } = await load('src/parser/entities/onlineState.ts');
const { constructorFieldHelper, Decoders, Field, FieldTypeEnum } = await load(
  'src/parser/entities/constructorFields.ts',
);
const bits = (...parts) => {
  const out = new Uint8Array(Math.ceil(parts.reduce((s, [, n]) => s + n, 0) / 8));
  let p = 0;
  for (const [v, n] of parts)
    for (let i = 0; i < n; i++, p++) out[p >>> 3] |= ((v >>> i) & 1) << (p & 7);
  return out;
};
const fields = [
  new Field(FieldTypeEnum.Value, { name: 'value', decoder: Decoders.NoscaleDecoder, prop_id: 0 }),
];
const names = {},
  decoders = {},
  info = {};
constructorFieldHelper.traverseFields(fields, 'Test', names, { id: 0 }, decoders, info);
const schema = {
  classes: [{ class_id: 0, name: 'Test', serializer: { name: 'Test', fields } }],
  classIdBits: 1,
  propIdToName: names,
  propIdToDecoder: decoders,
  propIdToInfo: info,
  propNameById: Object.values(names),
  propInfoById: Object.values(info),
};
const p = new EntityParser(schema, () => {});
p.directEntities = [];
p.directPropInfoById = schema.propInfoById;
p.online = new OnlineEntityState();
const receipts = [];
p.onOnlineReceipt = (x) => receipts.push(x);
const create = (value) => bits([0, 6], [2, 2], [0, 1], [0, 17], [0, 8], [2, 3], [value, 32]);
const packet = (data, meta = {}) => ({
  entity_data: data,
  updated_entries: 1,
  alternate_baselines: [],
  non_transmitted_entities: { header_count: 0, data: new Uint8Array() },
  ...meta,
});
p.tick = 10;
p.parseEntityPacket(packet(create(0x3f800000), { update_baseline: true, baseline: 0 }), []);
assert.equal(p.directEntities[0].properties['Test.value'], 1);
p.tick = 11;
p.parseEntityPacket(
  packet(bits([0, 6], [3, 2]), { legacy_is_delta: true, delta_from: 10, baseline: 1 }),
  [],
);
assert.equal(p.directEntities[0], undefined);
// A zero-field create inherits the entity bank, rather than the class default.
p.tick = 12;
p.parseEntityPacket(
  packet(bits([0, 6], [2, 2], [0, 1], [1, 17], [0, 8], [1, 2]), {
    legacy_is_delta: true,
    delta_from: 11,
    baseline: 1,
  }),
  [],
);
assert.equal(p.directEntities[0].properties['Test.value'], 1);
assert.deepEqual(receipts, [
  { tick: 10, baselineAck: 0 },
  { tick: 11, baselineAck: null },
  { tick: 12, baselineAck: null },
]);
console.log(
  'Actual entity bitstream: baseline capture, deletion, re-entry with empty delta inherited bank, exact receipt passed',
);
const gaps = [];
p.onOnlineRecovery = (x) => gaps.push(x);
p.tick = 13;
p.parseEntityPacket(
  packet(bits([0, 8], [2, 3], [0x40800000, 32]), { legacy_is_delta: true, delta_from: 8 }),
  [],
);
assert.equal(p.directEntities[0].properties['Test.value'], 1);
assert.equal(p.online.waitingFull, true);
p.tick = 14;
p.parseEntityPacket(
  packet(bits([0, 8], [2, 3], [0x40800000, 32]), { legacy_is_delta: true, delta_from: 13 }),
  [],
);
assert.equal(receipts.length, 3);
assert.deepEqual(gaps, [{ tick: 13, deltaFrom: 8 }]);
p.tick = 15;
p.parseEntityPacket(packet(create(0x40400000), {}), []);
assert.equal(p.directEntities[0].properties['Test.value'], 3);
assert.equal(p.online.waitingFull, false);
p.onlineBaselineEntries.set(9, bits([2, 3], [0x40e00000, 32]));
p.tick = 16;
p.parseEntityPacket(
  packet(bits([0, 8], [1, 2]), {
    legacy_is_delta: true,
    delta_from: 15,
    alternate_baselines: [{ entity_index: 0, baseline_index: 9 }],
  }),
  [],
);
assert.equal(p.directEntities[0].properties['Test.value'], 7);
p.tick = 17;
p.parseEntityPacket(
  packet(bits([0, 6], [1, 2]), {
    legacy_is_delta: true,
    delta_from: 16,
    non_transmitted_entities: { header_count: 1, data: bits([0, 6], [1, 1]) },
  }),
  [],
);
assert.equal(p.directEntities[0].properties['Test.value'], 7);
p.tick = 18;
p.parseEntityPacket(
  packet(new Uint8Array(), {
    updated_entries: 0,
    legacy_is_delta: true,
    delta_from: 17,
    non_transmitted_entities: { header_count: 1, data: bits([0, 6], [0, 1]) },
  }),
  [],
);
assert.equal(p.directEntities[0], undefined);
p.tick = 19;
p.parseEntityPacket(
  packet(new Uint8Array(), {
    updated_entries: 0,
    legacy_is_delta: true,
    delta_from: 18,
    outofpvs_entity_updates: {
      count: 1,
      data: bits([0, 6], [1, 1], [0, 1], [2, 17], [0, 8], [2, 3], [0x41100000, 32]),
    },
  }),
  [],
);
assert.equal(p.directEntities[0].properties['Test.value'], 9);
p.tick = 20;
p.parseEntityPacket(
  packet(new Uint8Array(), {
    updated_entries: 0,
    legacy_is_delta: true,
    delta_from: 19,
    outofpvs_entity_updates: { count: 1, data: bits([0, 6], [0, 1], [2, 3], [0x41200000, 32]) },
  }),
  [],
);
assert.equal(p.directEntities[0].properties['Test.value'], 10);
console.log(
  'Actual binary cases: missing frame suppresses deltas until full reset; alternate baseline, dormant reconciliation, out-of-PVS create/update passed',
);
const { FullFrameAssembler } = await load('src/parser/entities/fullFrameSplit.ts');
const { SnappyDecoder } = await load('src/compression/wasm.ts');
const snappy = new SnappyDecoder();
const assembler = new FullFrameAssembler();
const unpack = (bytes) => snappy.uncompress(bytes);
// Raw Snappy literal containing PacketEntities.server_tick = 100.
assert.equal(
  assembler.consume({ tick: 100, section: 0, total: 2, data: Uint8Array.of(2, 4) }, unpack),
  null,
);
assert.equal(
  assembler.consume({ tick: 100, section: 1, total: 2, data: Uint8Array.of(96, 100) }, unpack)
    .packet.server_tick,
  100,
);
assert.equal(
  assembler.consume({ tick: 101, section: 1, total: 2, data: Uint8Array.of(96, 101) }, unpack),
  null,
);
assert.equal(
  assembler.consume({ tick: 101, section: 0, total: 3, data: Uint8Array.of(2, 4) }, unpack),
  null,
);
assert.equal(
  assembler.consume({ tick: 101, section: 2, total: 3, data: Uint8Array.of(96, 101) }, unpack),
  null,
);
assert.throws(
  () =>
    assembler.consume(
      { tick: 102, section: 0, total: 1, data: Uint8Array.of(2, 4, 96, 100) },
      unpack,
    ),
  /identity/,
);
snappy.release();
console.log(
  'Full-frame split: real Snappy assembly, missing initial/middle section, and tick identity verified',
);
const priorReceipts = receipts.length;
p.tick = 21;
p.parseEntityPacket(packet(new Uint8Array(), { updated_entries: 0, pending_full_frame: true }), []);
assert.equal(receipts.length, priorReceipts);
assert.equal(gaps.at(-1).request, false);
p.tick = 20;
p.parseEntityPacket(packet(create(0x3f800000)), []);
assert.equal(receipts.length, priorReceipts);
p.tick = 22;
p.parseEntityPacket(packet(create(0x40000000)), []);
assert.equal(receipts.at(-1).tick, 22);
console.log(
  'Pending full-frame placeholder is not acknowledged as decoded; stale full snapshot is ignored',
);
