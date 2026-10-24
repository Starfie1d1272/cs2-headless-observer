import { closeSync, openSync, writeSync } from 'node:fs';
import { stat } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { parseArgs } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import { createResearchDemoReceiver } from '@mizar/telemetry-cstv/research';
import type { ResearchSample } from '@mizar/telemetry-cstv/research';
import { Assist } from './assist.js';
import type { Observation, Role } from './assist.js';
import { growingDemo, SourceBoundary } from './follow.js';

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    input: { type: 'string' },
    output: { type: 'string' },
    match: { type: 'string' },
    execution: { type: 'string' },
    follow: { type: 'boolean', default: false },
    seconds: { type: 'string', default: '14400' },
    early: { type: 'string' },
    program: { type: 'string' },
    'display-evidence': { type: 'string' },
    horizon: { type: 'string', default: '10' },
  },
});
const command = positionals[0];
if (positionals.length !== 1 || !['receive', 'assist'].includes(command ?? '') || !values.output) {
  throw new Error(
    'Usage: receive --input FILE --match ID --execution ID --output NEW.jsonl [--follow] [--seconds 14400]; assist --early FILE --program FILE --output NEW.jsonl [--display-evidence NOTE] [--horizon 10]',
  );
}
const duration = Number(values.seconds);
if (!Number.isFinite(duration) || duration < 1 || duration > 14400)
  throw new Error('seconds must be 1..14400');
const abort = new AbortController();
const timeout = setTimeout(() => abort.abort(new Error('duration-limit')), duration * 1000);
const stop = () => abort.abort(new Error('operator-stop'));
process.once('SIGINT', stop);
process.once('SIGTERM', stop);
const fd = openSync(values.output, 'wx', 0o600);
let written = 0;
let outputSequence = 0;
function diagnosticError(error: unknown, depth = 0): unknown {
  if (!(error instanceof Error)) return String(error);
  return {
    name: error.name,
    message: error.message,
    stack: error.stack,
    ...(error.cause === undefined
      ? {}
      : depth < 8
        ? { cause: diagnosticError(error.cause, depth + 1) }
        : { causeOmitted: 'depth-limit' }),
  };
}
const emit = (row: object) => {
  const bytes = Buffer.from(
    JSON.stringify({
      schema: 'mizar.observer.capture.v1',
      recordedAt: new Date().toISOString(),
      outputSequence: ++outputSequence,
      ...row,
    }) + '\n',
  );
  if (written + bytes.length > 256 * 1024 ** 2) throw new Error('output-byte-budget');
  let offset = 0;
  while (offset < bytes.length) {
    const count = writeSync(fd, bytes, offset, bytes.length - offset);
    if (count === 0) throw new Error('output-write-stalled');
    offset += count;
  }
  written += bytes.length;
};

async function receive() {
  if (!values.input || !values.match || !values.execution)
    throw new Error('input, match and execution are required');
  const receiverId = randomUUID();
  let generation = 0;
  while (!abort.signal.aborted) {
    if (++generation > 32) throw new Error('recovery-budget-exhausted');
    let live = false;
    let frontierTick: number | null = null;
    const eligible = (tick: number) => {
      if (!live) return false;
      frontierTick ??= tick;
      return tick > frontierTick;
    };
    let offset = 0;
    emit({ kind: 'status', reason: 'generation-start', receiverId, generation });
    const parser = createResearchDemoReceiver({
      scope: { matchId: values.match, mapExecution: values.execution, receiverId, generation },
      sample: (value) =>
        emit({ kind: 'sample', value, live: eligible(value.tick), bytesRead: offset }),
      kill: (value) => emit({ kind: 'kill', value, live: eligible(value.tick), bytesRead: offset }),
    });
    const cancel = () => parser.cancel();
    abort.signal.addEventListener('abort', cancel, { once: true });
    try {
      const stream = await growingDemo(values.input, {
        signal: abort.signal,
        follow: values.follow,
        onRead: (next, initial) => {
          offset = next;
          live = values.follow && next > initial;
        },
        onIdle: () => emit({ kind: 'status', reason: 'input-idle', receiverId, generation }),
      });
      const result = await parser.parse(stream);
      emit({
        kind: 'status',
        reason: result.status,
        receiverId,
        generation,
        bytesRead: offset,
        rssBytes: process.memoryUsage().rss,
      });
      if (!values.follow || abort.signal.aborted) {
        if (result.status === 'incomplete') process.exitCode = 2;
        return;
      }
      // Completion is not a new generation. Wait for an actual file boundary.
      const ended = await stat(values.input);
      while (!abort.signal.aborted) {
        await delay(100, undefined, { signal: abort.signal });
        const next = await stat(values.input);
        if (next.ino !== ended.ino || next.dev !== ended.dev || next.size < ended.size) break;
      }
    } catch (error) {
      if (abort.signal.aborted) return;
      if (!(error instanceof SourceBoundary)) throw error;
      emit({ kind: 'status', reason: error.message, receiverId, generation });
    } finally {
      abort.signal.removeEventListener('abort', cancel);
      parser.cancel();
    }
  }
}

function observation(row: unknown): Observation {
  if (!row || typeof row !== 'object') throw new Error('invalid-record');
  const r = row as Record<string, unknown>;
  if (r.kind === 'status' && typeof r.reason === 'string')
    return { kind: 'status', reason: r.reason.slice(0, 200) };
  if (
    (r.kind !== 'sample' && r.kind !== 'kill') ||
    typeof r.live !== 'boolean' ||
    !r.value ||
    typeof r.value !== 'object'
  )
    throw new Error('invalid-observation');
  const s = r.value as ResearchSample;
  if (
    !s.scope ||
    ![s.scope.matchId, s.scope.mapExecution, s.scope.receiverId, s.map].every(
      (x) => typeof x === 'string' && x.length > 0 && x.length <= 200,
    ) ||
    !Number.isSafeInteger(s.scope.generation) ||
    s.scope.generation < 1 ||
    !Number.isSafeInteger(s.tick) ||
    s.tick < 0 ||
    typeof s.tickInterval !== 'number' ||
    !(s.tickInterval > 0 && s.tickInterval <= 1) ||
    ![true, false, null].includes(s.paused) ||
    !(s.round === null || (Number.isSafeInteger(s.round) && s.round >= 0))
  )
    throw new Error('invalid-source-sample');
  if (r.kind === 'kill') {
    const k = r.value as Record<string, unknown>;
    if (
      !Number.isSafeInteger(k.sequence) ||
      Number(k.sequence) < 1 ||
      typeof k.weapon !== 'string' ||
      k.weapon.length > 100 ||
      ![k.attacker, k.victim].every(
        (x) => x === null || (typeof x === 'string' && /^7656119\d{10}$/.test(x)),
      )
    )
      throw new Error('invalid-kill');
  }
  return row as Observation;
}

async function assist() {
  if (!values.early || !values.program)
    throw new Error('early and program capture paths are required');
  const engine = new Assist({
    displayEvidence: values['display-evidence'] ?? null,
    horizonSeconds: Number(values.horizon),
  });
  const consume = async (role: Role, path: string) => {
    const stream = await growingDemo(path, {
      signal: abort.signal,
      follow: true,
      onIdle: () =>
        engine.feed(role, { kind: 'status', reason: 'capture-idle' }, performance.now()),
    });
    let pending = '';
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let lastSequence = 0;
    for await (const bytes of stream) {
      pending += decoder.decode(bytes, { stream: true });
      let newline: number;
      while ((newline = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (line.length > 16_384) throw new Error('capture-line-budget');
        const row = JSON.parse(line) as Record<string, unknown>;
        const age = Date.now() - Date.parse(String(row.recordedAt));
        if (
          row.schema !== 'mizar.observer.capture.v1' ||
          !Number.isSafeInteger(row.outputSequence) ||
          Number(row.outputSequence) <= lastSequence
        )
          throw new Error('capture-sequence');
        lastSequence = Number(row.outputSequence);
        if (!Number.isFinite(age) || age > 1500 || age < -250) {
          engine.feed(role, { kind: 'status', reason: 'capture-stale' }, performance.now());
          continue;
        }
        engine.feed(role, observation(row), performance.now());
      }
      if (pending.length > 16_384) throw new Error('capture-line-budget');
    }
  };
  const publish = async () => {
    while (!abort.signal.aborted) {
      emit(engine.project(performance.now()));
      await delay(100, undefined, { signal: abort.signal });
    }
  };
  const tasks = [consume('early', values.early), consume('program', values.program), publish()];
  try {
    await Promise.all(tasks);
  } catch (error) {
    if (!abort.signal.aborted) {
      emit({
        kind: 'status',
        reason: 'failed',
        error: diagnosticError(error),
      });
      process.exitCode = 1;
    }
  } finally {
    abort.abort();
    await Promise.allSettled(tasks);
    engine.invalidate('assist-stopped');
    emit(engine.project(performance.now()));
  }
}

try {
  if (command === 'receive') await receive();
  else await assist();
} catch (error) {
  if (!abort.signal.aborted) {
    emit({
      kind: 'status',
      reason: 'failed',
      error: diagnosticError(error),
    });
    process.exitCode = 1;
  }
} finally {
  abort.abort();
  clearTimeout(timeout);
  process.removeListener('SIGINT', stop);
  process.removeListener('SIGTERM', stop);
  closeSync(fd);
}
