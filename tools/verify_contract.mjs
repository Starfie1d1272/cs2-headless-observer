// Contract checks use actual exported synthetic records; no SDK or network.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import Ajv2020 from 'ajv/dist/2020.js';
import { Consumer } from '../examples/managed_consumer.mjs';
const schema = JSON.parse(
  fs.readFileSync(new URL('../schemas/managed-event.schema.json', import.meta.url), 'utf8'),
);
const fixture = JSON.parse(
  fs.readFileSync(new URL('../examples/managed-events.json', import.meta.url), 'utf8'),
);
const validate = new Ajv2020({ strict: false }).compile(schema);
for (const row of fixture.records) assert.ok(validate(row), JSON.stringify(validate.errors));
const cursor = fixture.records.find((x) => x.kind === 'cursor');
assert.ok(cursor);
assert.equal(validate({ ...cursor, sequence: null }), false);
assert.equal(validate({ ...cursor, tickInterval: 0 }), false);
assert.equal(validate({ ...cursor, extraFutureField: true }), true);
assert.equal(
  validate({ ...cursor, roundClock: { ...cursor.roundClock, committedTick: 0 } }),
  false,
);
const { roundClock, ...legacyCursor } = cursor;
assert.equal(validate(legacyCursor), true);
const session = {
  kind: 'session-start',
  protocol: 2,
  source: cursor.source,
  channel: 2,
  world: 1,
  sequence: 10,
};
assert.equal(validate(session), true);
assert.equal(validate({ ...session, world: 2 }), false);
assert.equal(validate({ ...session, protocol: 1 }), false);
assert.equal(validate({ ...cursor, supervisorForwardUs: 14 }), true);
const owner = new Consumer(cursor.source);
owner.accept({ ...session, channel: 1, sequence: 1 });
for (const row of fixture.records) owner.accept({ ...row, sequence: owner.sequence + 1 });
owner.accept({
  kind: 'discontinuity',
  source: cursor.source,
  channel: 1,
  world: cursor.world + 1,
  sequence: owner.sequence + 1,
  reason: 'synthetic-reset',
});
assert.equal(owner.ready, false);
owner.accept({ ...cursor, sequence: owner.sequence + 1 });
assert.equal(owner.ready, false);
owner.accept({ ...cursor, world: cursor.world + 1, sequence: owner.sequence + 1 });
assert.equal(owner.ready, true);
owner.accept({
  kind: 'discontinuity',
  source: cursor.source,
  channel: 1,
  world: owner.world,
  sequence: owner.sequence + 1,
  reason: 'synthetic-reconnect',
  scope: 'connection',
});
assert.equal(owner.ready, false);
owner.accept({ ...session, sequence: owner.sequence + 1 });
owner.accept({ ...cursor, channel: 1, sequence: owner.sequence + 1 });
assert.equal(owner.ready, false);
owner.accept({ ...cursor, channel: 2, world: 1, sequence: owner.sequence + 1 });
assert.equal(owner.ready, true);
console.log(JSON.stringify({ schemaFixtureRecords: fixture.records.length, passed: true }));
