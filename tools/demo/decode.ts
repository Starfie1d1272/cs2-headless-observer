/** Local file experiment, NOT a network spectator client. Never feeds production projections. */
import { randomUUID } from 'node:crypto';
import { open, mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { viewerDecoder } from './viewer-research.js';
import { growingDemo } from './follow.js';
import { describeFailure } from './failure.js';

const { values } = parseArgs({
  options: {
    input: { type: 'string' },
    output: { type: 'string' },
    follow: { type: 'boolean' },
    seconds: { type: 'string', default: '300' },
    offset: { type: 'string', default: '120' },
  },
});
const seconds = Number(values.seconds);
const offset = Number(values.offset);
if (
  !values.input ||
  !values.output ||
  !Number.isFinite(seconds) ||
  seconds <= 0 ||
  seconds > 14400 ||
  !Number.isFinite(offset) ||
  offset < 0 ||
  offset > 3600
) {
  throw new Error(
    'usage: --input FILE --output NEW_DIRECTORY [--follow --seconds 300 --offset 120]',
  );
}
await mkdir(values.output); // Never overwrite a prior evidence run.
const streamInstance = randomUUID();
const output = await open(join(values.output, 'events.jsonl'), 'wx', 0o600);
const abort = new AbortController();
const began = performance.now();
const cpu = process.cpuUsage();
const counts: Record<string, number> = {};
let sequence = 0;
let bytes = 0;
let initialBytes = 0;
let initialTick: number | null = null;
let appendedEvents = 0;
let stopped = false;
let writeQueue = '';
let eventsWriteFailed = false;
let failure = false;
let outcome: string = 'not-started';
let magicChecked = 0;
const magic = Buffer.from('PBDEMS2\0');
const decoder = viewerDecoder((event) => {
  counts[event.kind] = (counts[event.kind] ?? 0) + 1;
  // Read-ahead means byte position alone cannot establish fresh event provenance.
  // This is only an offline append observation, never a live-match success flag.
  if (bytes <= initialBytes || initialTick === null) initialTick = event.tick;
  const afterInitialBytes = bytes > initialBytes && event.tick > initialTick;
  if (afterInitialBytes && event.kind !== 'cursor') appendedEvents++;
  const record = {
    schema: 'cs2.observer.event.v1',
    streamInstance,
    sequence: ++sequence,
    observedAt: new Date().toISOString(),
    observedMonotonicMs: performance.now() - began,
    inputBytesRead: bytes,
    afterInitialBytes,
    source: 'demo-file',
    ...event,
    configuredOffsetSeconds: offset,
    displayTime: null,
    displayBinding: 'unverified',
  };
  writeQueue += JSON.stringify(record) + '\n';
  if (writeQueue.length > 8 * 1024 ** 2) throw new Error('event-output-budget');
});
const stop = () => {
  stopped = true;
  abort.abort();
  decoder.cancel();
};
process.once('SIGINT', stop);
process.once('SIGTERM', stop);
const timeout = setTimeout(stop, seconds * 1000);
let input: ReadableStream<Uint8Array> | undefined;
let sourceReader: ReadableStreamDefaultReader<Uint8Array> | undefined;
let failureStage = 'open-source';
let failureDetail: ReturnType<typeof describeFailure> | null = null;
const finalizationFailures: ReturnType<typeof describeFailure>[] = [];
const flushEvents = async () => {
  if (!writeQueue || eventsWriteFailed) return;
  // A failed write may already have persisted a prefix. Never retry this batch.
  const batch = writeQueue;
  writeQueue = '';
  failureStage = 'write-events';
  try {
    await output.writeFile(batch);
  } catch (error) {
    eventsWriteFailed = true;
    failureDetail ??= describeFailure(error, failureStage);
    throw error;
  }
};
const finalizeStep = async (stage: string, action: () => unknown) => {
  try {
    await action();
  } catch (error) {
    const detail = describeFailure(error, stage);
    // Cleanup/report failures must not replace the original decode/write failure.
    failureDetail ??= detail;
    finalizationFailures.push(detail);
    failure = true;
    outcome = 'failed';
  }
};
try {
  input = await growingDemo(values.input, {
    follow: values.follow ?? false,
    signal: abort.signal,
    onRead: (n, initial) => {
      bytes = n;
      initialBytes = initial;
    },
  });
  const reader = input.getReader();
  sourceReader = reader;
  failureStage = 'decode-or-read-source';
  const validated = new ReadableStream<Uint8Array>(
    {
      async pull(controller) {
        try {
          await flushEvents();
          failureStage = 'read-source';
          const next = await reader.read();
          if (next.done) {
            failureStage = 'validate-header';
            if (magicChecked < magic.length) throw new Error('incomplete-demo-header');
            controller.close();
            return;
          }
          failureStage = 'validate-header';
          for (
            let i = 0;
            i < next.value.length && magicChecked < magic.length;
            i++, magicChecked++
          ) {
            if (next.value[i] !== magic[magicChecked]) throw new Error('invalid-cs2-demo-magic');
          }
          failureStage = 'parse-demo';
          controller.enqueue(next.value);
        } catch (error) {
          failureDetail ??= describeFailure(error, failureStage);
          throw error;
        }
      },
      async cancel(reason) {
        await reader.cancel(reason);
      },
    },
    { highWaterMark: 0 },
  );
  outcome = (await decoder.parse(validated)).status;
  if (outcome !== 'complete' && !stopped) {
    failure = true;
    failureDetail ??= { category: 'parser-outcome', reason: outcome, stage: 'parse-demo' };
  }
  if (!failure) failureStage = 'none';
} catch (error) {
  failureDetail ??= describeFailure(error, failureStage);
  outcome = stopped ? 'stopped-incomplete' : 'failed';
  failure = !stopped || eventsWriteFailed;
} finally {
  clearTimeout(timeout);
  process.removeListener('SIGINT', stop);
  process.removeListener('SIGTERM', stop);
  abort.abort();
  if (sourceReader) {
    await finalizeStep('cancel-source', () => sourceReader!.cancel());
    await finalizeStep('release-source', () => sourceReader!.releaseLock());
  } else if (input) {
    await finalizeStep('cancel-source', () => input!.cancel());
  }
  await finalizeStep('write-events', flushEvents);
  await finalizeStep('close-events', () => output.close());
  const usage = process.cpuUsage(cpu);
  const report = {
    schema: 'cs2.observer.decode-report.v1',
    streamInstance,
    outcome,
    failureStage: failure ? (failureDetail?.stage ?? failureStage) : null,
    failure: failure ? failureDetail : null,
    finalizationFailures,
    eventsWriteFailed,
    counts,
    initialBytes,
    bytesRead: bytes,
    appendedEvents,
    elapsedMs: performance.now() - began,
    cpuMs: (usage.user + usage.system) / 1000,
    peakRssKiB: process.resourceUsage().maxRSS,
    configuredOffsetSeconds: offset,
    ordinaryViewerHandshake: 'INCONCLUSIVE',
    liveContinuousReceipt: 'INCONCLUSIVE',
    displayBinding: 'unverified',
    windows: 'NOT_RUN',
  };
  let reportWritten = false;
  await finalizeStep('write-report', async () => {
    await writeFile(join(values.output!, 'report.json'), JSON.stringify(report, null, 2) + '\n', {
      flag: 'wx',
      mode: 0o600,
    });
    reportWritten = true;
  });
  // A full disk can also reject report.json. Stderr carries sanitized first cause
  // and each finalization failure independently of that file's persistence.
  Object.assign(report, {
    outcome,
    failureStage: failure ? (failureDetail?.stage ?? failureStage) : null,
    failure: failure ? failureDetail : null,
    reportWritten,
  });
  if (failure) console.error(JSON.stringify(report));
  console.log(JSON.stringify(report));
  if (failure) process.exitCode = 1;
}
