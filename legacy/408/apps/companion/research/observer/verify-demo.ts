/** Explicit real-input experiment; no fixture download and no skipped success. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, open, writeFile, mkdtemp, rm, stat } from 'node:fs/promises';
import { Readable } from 'node:stream';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { createResearchDemoReceiver } from '@mizar/telemetry-cstv/research';
import type { ResearchKill, ResearchSample } from '@mizar/telemetry-cstv/research';
import { growingDemo } from './follow.js';
import { Assist } from './assist.js';

const [demo, oracle, output] = process.argv.slice(2);
assert(demo && oracle && output, 'verify-demo DEMO DAK-KILLS.json NEW-REPORT.json');
const hash = createHash('sha256');
for await (const bytes of createReadStream(demo) as AsyncIterable<Buffer>) hash.update(bytes);
const sha = hash.digest('hex');
assert.equal(
  sha,
  '143eb78444727c7a8afa29d807272076d14044fc9d7c233035d0b9a176e70f60',
  'use the documented upstream fixture',
);
const scope = {
  matchId: 'upstream-fixture',
  mapExecution: 'ancient-1',
  receiverId: 'offline',
  generation: 1,
};
const baseline: ResearchKill[] = [];
const samples: ResearchSample[] = [];
const start = performance.now();
const receiver = createResearchDemoReceiver({
  scope,
  kill: (x) => baseline.push(x),
  sample: (x) => samples.push(x),
});
assert.deepEqual(
  await receiver.parse(Readable.toWeb(createReadStream(demo)) as ReadableStream<Uint8Array>),
  { status: 'complete' },
);
receiver.cancel(); // terminal cancellation must be safe
const expected = JSON.parse(await readFile(oracle, 'utf8')) as {
  tick: number;
  attacker_steamid: string | null;
  user_steamid: string | null;
}[];
const comparable = (kills: ResearchKill[]) => kills.map((x) => [x.tick, x.attacker, x.victim]);
assert.deepEqual(
  comparable(baseline),
  expected.map((x) => [x.tick, x.attacker_steamid, x.user_steamid]),
);
const baselineMs = performance.now() - start;

const dir = await mkdtemp(join(tmpdir(), 'observer-real-'));
const growingPath = join(dir, 'recording.dem');
const abort = new AbortController();
const incremental: ResearchKill[] = [];
let firstKillBytes = 0;
let bytesWritten = 0;
let writerFinished = false;
let firstKillResolve!: () => void;
const firstKill = new Promise<void>((resolve) => {
  firstKillResolve = resolve;
});
const size = (await stat(demo)).size;
const incrementalStart = performance.now();
try {
  await writeFile(growingPath, new Uint8Array());
  const parser = createResearchDemoReceiver({
    scope,
    sample: () => {},
    kill: (x) => {
      incremental.push(x);
      if (incremental.length === 1) {
        assert.equal(writerFinished, false);
        assert(bytesWritten < size);
        firstKillBytes = bytesWritten;
        firstKillResolve();
      }
    },
  });
  const parse = parser.parse(
    await growingDemo(growingPath, { signal: abort.signal, follow: true, pollMs: 2 }),
  );
  const writer = await open(growingPath, 'a');
  const write = (async () => {
    try {
      // Uneven boundaries split protobuf varints and compressed frames naturally.
      for await (const bytes of createReadStream(demo, {
        highWaterMark: 131071,
      }) as AsyncIterable<Buffer>) {
        let offset = 0;
        while (offset < bytes.length)
          offset += (await writer.write(bytes, offset, bytes.length - offset)).bytesWritten;
        bytesWritten += bytes.length;
        if (bytesWritten >= 16 * 1024 ** 2 && firstKillBytes === 0) {
          await Promise.race([
            firstKill,
            delay(5000).then(() => {
              throw new Error('no-kill-before-producer-EOF');
            }),
          ]);
        }
        if (bytesWritten % (131071 * 16) === 0) await delay(1);
      }
      writerFinished = true;
    } finally {
      await writer.close();
    }
  })();
  try {
    const result = await Promise.all([parse, write]);
    assert.deepEqual(result[0], { status: 'complete' });
    assert.deepEqual(comparable(incremental), comparable(baseline));
  } finally {
    abort.abort();
    await Promise.allSettled([parse, write]);
  }
} finally {
  abort.abort();
  await rm(dir, { recursive: true });
}

// Real parsed events, synthetic arrival schedules. This is NOT a broadcast delay measurement.
const engine = new Assist({ displayEvidence: 'synthetic-timeline-experiment' });
const cursors = { early: 0, program: 0 };
const sampleCursors = { early: 0, program: 0 };
let cues = 0;
let aligned = 0;
const leads: number[] = [];
for (let t = 0; t < 2900; t += 0.25) {
  for (const role of ['early', 'program'] as const) {
    const time = t - (role === 'program' ? 12 : 0);
    const roleScope = { ...scope, receiverId: role };
    while (sampleCursors[role] < samples.length && samples[sampleCursors[role]]!.tick / 64 <= time)
      sampleCursors[role]++;
    const current = samples[Math.max(0, sampleCursors[role] - 1)]!;
    // Deliver all events before the next sample; no backward tick injection.
    while (cursors[role] < baseline.length && baseline[cursors[role]]!.tick / 64 <= time) {
      const kill = baseline[cursors[role]++]!;
      engine.feed(
        role,
        { kind: 'kill', live: true, value: { ...kill, scope: roleScope } },
        t * 1000,
      );
    }
    if (time >= 0)
      engine.feed(
        role,
        {
          kind: 'sample',
          live: true,
          value: { ...current, tick: Math.floor(time * 64), scope: roleScope },
        },
        t * 1000,
      );
  }
  const projection = engine.project(t * 1000);
  if (projection.available) {
    aligned++;
    leads.push(projection.leadSeconds);
    if (projection.cue) cues++;
  }
}
assert(aligned > 0 && cues > 0);
assert(leads.every((x) => Math.abs(x - 12) < 0.001));
assert.equal(engine.project(3_000_000).cue, null);
const report = {
  result: 'PASS',
  fixture: {
    sha256: sha,
    bytes: size,
    upstream: 'osztenkurden/cs2parser test-fixtures/v2/demo.dem',
  },
  environment: { node: process.version, platform: process.platform, arch: process.arch },
  parser: 'cs2parser@2.7.2',
  oracle: 'DAK extraction dependency demoparser2@0.42.0',
  offline: {
    kills: baseline.length,
    identityComplete: baseline.filter((x) => x.attacker && x.victim).length,
    exactDakTupleParity: true,
    elapsedMs: Math.round(baselineMs),
  },
  incremental: {
    kills: incremental.length,
    firstKillBeforeProducerEOF: true,
    firstKillBytes,
    fixtureBytes: size,
    exactOfflineParity: true,
    elapsedMs: Math.round(performance.now() - incrementalStart),
  },
  simulatedTimeline: {
    imposedDelaySeconds: 12,
    alignedSamples: aligned,
    cueSamples: cues,
    minLead: Math.min(...leads),
    maxLead: Math.max(...leads),
    staleWithdrawn: true,
  },
  rssBytes: process.memoryUsage().rss,
  liveRelay: 'INCONCLUSIVE: no CS2 runtime or authorized source',
  liveContinuousExport: 'INCONCLUSIVE',
  realLeadAndDrift: 'INCONCLUSIVE',
  windowsIntegration: 'INCONCLUSIVE',
};
await writeFile(output, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
console.log(JSON.stringify(report));
