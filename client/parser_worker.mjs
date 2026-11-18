// The worker owns ordered world transactions. The parent owns the SDK and ACKs.
import { once } from 'node:events';
import process from 'node:process';
import { performance } from 'node:perf_hooks';
import { NativeObserverCore } from 'cs2parser/observer-core';

const MAX_INPUT = 8 * 1024 ** 2;
const MAX_BODY = 4 * 1024 ** 2;
const MAX_OUTPUT = 65536;
const RESULT_PREFIX = '{"type":"results","rows":[';
let core;
let batchId = 0;
let sequence = 0;
let results = [];
let resultBytes = RESULT_PREFIX.length + 3;

async function write(line) {
  if (!process.stdout.write(line)) await once(process.stdout, 'drain');
}

async function flush() {
  if (!results.length) return;
  await write(RESULT_PREFIX + results.join(',') + ']}\n');
  results = [];
  resultBytes = RESULT_PREFIX.length + 3;
}

function append(line, size) {
  results.push(line);
  resultBytes += size + 1;
}

const identity = (row) => ({ source: row.source, channel: row.channel, world: row.world });

function consume(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row))
    throw new Error('ordered-parser-record-shape');
  const current = core.currentIdentity;
  if (row.type === 'reset-world') {
    core.resetWorld({ ...current, world: row.world });
    return [{ type: 'world-reset', ...core.currentIdentity, reason: 'parent-world-boundary' }];
  }
  if (row.world !== current.world) throw new Error('ordered-parser-control-generation');
  if (row.type === 'admit-creation-sequence') {
    core.admitCreationSequence(row.creationSequence);
    return [
      { type: 'creation-sequence-admitted', ...current, creationSequence: row.creationSequence },
    ];
  }
  if (
    row.type !== 'message' ||
    typeof row.bodyBase64 !== 'string' ||
    row.bodyBase64.length > Math.ceil(MAX_BODY / 3) * 4 ||
    row.bodyBase64.length % 4 !== 0
  )
    throw new Error('ordered-parser-message-shape');
  const body = Buffer.from(row.bodyBase64, 'base64');
  if (body.length > MAX_BODY || body.toString('base64') !== row.bodyBase64)
    throw new Error('ordered-parser-body-budget-or-encoding');
  return core.consume(
    {
      ...current,
      sequence: row.sequence,
      messageId: row.messageId,
      body,
      contextTick: row.contextTick,
    },
    false,
  );
}

async function send(record) {
  const line = JSON.stringify(record);
  const size = Buffer.byteLength(line);
  if (size + RESULT_PREFIX.length + 4 > MAX_OUTPUT) throw new Error('ordered-parser-output-budget');
  if (resultBytes + size + 1 > MAX_OUTPUT) await flush();
  append(line, size);
}

async function batch(input) {
  if (input?.type === 'init') {
    if (core) throw new Error('ordered-parser-already-initialized');
    core = new NativeObserverCore(identity(input));
    await send({ type: 'initialized', protocol: 4, ...core.currentIdentity });
    await flush();
    return;
  }
  if (
    !core ||
    input?.type !== 'batch' ||
    !Array.isArray(input.rows) ||
    !input.rows.length ||
    input.rows.length > 49152 ||
    input.batch !== ++batchId
  )
    throw new Error('ordered-parser-batch-shape');
  const current = core.currentIdentity;
  if (
    input.source !== current.source ||
    input.channel !== current.channel ||
    input.world !== current.world
  )
    throw new Error('ordered-parser-batch-generation');
  let last;
  let decodeMs = 0;
  let messages = 0;
  const checkpoint = async () => {
    if (!last) return;
    await send({
      ...core.checkpoint(last.messageId === 51 ? undefined : last.contextTick),
      decodeUs: Math.round(decodeMs * 1000),
    });
    last = undefined;
    decodeMs = 0;
    messages = 0;
  };
  for (const row of input.rows) {
    const message = row?.type === 'message';
    const boundary = !message || row.messageId === 51;
    if (boundary) await checkpoint();
    const start = performance.now();
    const records = consume(row);
    if (message) {
      decodeMs += performance.now() - start;
      last = row;
      sequence = row.sequence;
      messages++;
    }
    let barrier = boundary;
    for (const record of records) {
      if (record.type === 'blocked') throw new Error(record.reason);
      await send(record);
      if (record.type === 'gap' || record.type === 'recovery') barrier = true;
    }
    if (barrier || messages >= 128 || decodeMs >= 2) {
      await checkpoint();
      await flush();
    }
  }
  await checkpoint();
  await send({ type: 'batch-complete', batch: batchId, sequence, ...core.currentIdentity });
  await flush();
}

process.stdout.on('error', () => {
  process.exitCode = 1;
  process.stdin.destroy();
});
process.once('SIGTERM', () => process.stdin.destroy());
let pending = [];
let bytes = 0;
function collect(part) {
  bytes += part.length;
  if (bytes > MAX_INPUT) throw new Error('ordered-parser-input-budget');
  if (part.length) pending.push(part);
}

try {
  for await (const chunk of process.stdin) {
    let start = 0;
    for (let end; (end = chunk.indexOf(10, start)) !== -1; start = end + 1) {
      collect(chunk.subarray(start, end));
      if (!bytes) throw new Error('ordered-parser-empty-record');
      const line = pending.length === 1 ? pending[0] : Buffer.concat(pending, bytes);
      pending = [];
      bytes = 0;
      let input;
      try {
        input = JSON.parse(line.toString('utf8'));
      } catch {
        throw new Error('ordered-parser-invalid-json');
      }
      await batch(input);
    }
    collect(chunk.subarray(start));
  }
  if (bytes) throw new Error('ordered-parser-truncated-record');
  await write(JSON.stringify({ type: 'end', status: 'complete' }) + '\n');
} catch (error) {
  process.exitCode = 1;
  if (!process.stdout.destroyed) {
    try {
      await write(
        JSON.stringify({
          type: 'error',
          code: 'ordered-parser-failed',
          message: String(error?.message ?? error).slice(0, 1024),
        }) + '\n',
      );
    } catch {
      // A closed stdout already terminates this worker.
    }
  }
}
