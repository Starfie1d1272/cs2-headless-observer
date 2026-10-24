import { describe, it, expect } from 'vitest';
import { mkdtemp, writeFile, appendFile, rename, rm, open } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Assist } from './assist.js';
import type { Role } from './assist.js';
import { growingDemo, SourceBoundary } from './follow.js';
import type { ResearchSample } from '@mizar/telemetry-cstv/research';

const sample = (tick: number, role: Role): ResearchSample => ({
  scope: { matchId: 'match', mapExecution: 'map-run-1', receiverId: role, generation: 1 },
  map: 'de_ancient',
  tick,
  tickInterval: 1 / 64,
  paused: false,
  round: 1,
});
function scenario(displayEvidence: string | null = 'synthetic-display-only') {
  const engine = new Assist({ displayEvidence });
  let eSequence = 0;
  let pSequence = 0;
  for (let t = 0; t <= 62; t += 0.25) {
    for (const role of ['early', 'program'] as const) {
      const tick = Math.max(0, t - (role === 'program' ? 12 : 0)) * 64;
      const value = sample(tick, role);
      engine.feed(role, { kind: 'sample', live: true, value }, t * 1000);
      if ([20, 30, 40, 60].includes(tick / 64)) {
        engine.feed(
          role,
          {
            kind: 'kill',
            live: true,
            value: {
              ...value,
              sequence: role === 'early' ? ++eSequence : ++pSequence,
              round: tick / 640,
              attacker: '76561198000000001',
              victim: '76561198000000002',
              weapon: 'ak47',
            },
          },
          t * 1000,
        );
      }
    }
    engine.project(t * 1000);
  }
  return engine;
}

describe('private alignment and withdrawal', () => {
  it('uses three matched events, measures lead and exposes only the nearest cue', () => {
    const engine = scenario();
    expect(engine.project(62000)).toMatchObject({
      available: true,
      anchors: 3,
      leadSeconds: 12,
      driftPpm: 0,
      cue: { remainingSeconds: 10, attacker: '76561198000000001' },
    });
    expect(scenario(null).project(62000)).toMatchObject({
      available: false,
      reason: 'program-display-unverified',
      cue: null,
    });
  });
  it('withdraws without new input and cannot replay an old cue after recovery', () => {
    const engine = scenario();
    expect(engine.project(64000)).toMatchObject({ available: false, cue: null });
    for (const role of ['early', 'program'] as const)
      engine.feed(
        role,
        { kind: 'sample', live: true, value: sample(role === 'early' ? 64 * 64 : 52 * 64, role) },
        64000,
      );
    expect(engine.project(64000)).toMatchObject({ available: false, cue: null });
  });
  it.each(['pause', 'generation', 'map', 'execution', 'catchup', 'disconnect'] as const)(
    'clears alignment on %s',
    (reason) => {
      const engine = scenario();
      const value = sample(63 * 64, 'early');
      engine.feed(
        'early',
        reason === 'disconnect'
          ? { kind: 'status', reason }
          : {
              kind: 'sample',
              live: reason !== 'catchup',
              value: {
                ...value,
                paused: reason === 'pause',
                map: reason === 'map' ? 'de_nuke' : value.map,
                scope: {
                  ...value.scope,
                  generation: reason === 'generation' ? 2 : 1,
                  mapExecution: reason === 'execution' ? 'map-run-2' : 'map-run-1',
                },
              },
            },
        63000,
      );
      expect(engine.project(63000)).toMatchObject({ available: false, cue: null });
    },
  );
  it('rejects clock reversal and expires cues after their Program tick', () => {
    const engine = scenario();
    expect(() => engine.project(0)).toThrow('non-monotonic');
    for (let t = 62.25; t <= 73; t += 0.25) {
      for (const role of ['early', 'program'] as const)
        engine.feed(
          role,
          {
            kind: 'sample',
            live: true,
            value: sample((t - (role === 'program' ? 12 : 0)) * 64, role),
          },
          t * 1000,
        );
      engine.project(t * 1000);
    }
    expect(engine.project(73000)).toMatchObject({ available: true, cue: null });
  });
  it('invalidates a previously plausible mapping on an inconsistent matched event', () => {
    const engine = scenario();
    engine.feed(
      'program',
      {
        kind: 'kill',
        live: true,
        value: {
          ...sample(65 * 64, 'program'),
          sequence: 4,
          round: 6,
          attacker: '76561198000000001',
          victim: '76561198000000002',
          weapon: 'ak47',
        },
      },
      63000,
    );
    expect(engine.project(63000)).toMatchObject({
      available: false,
      reason: 'alignment-drift',
      cue: null,
    });
  });
  it('does not reuse an ambiguous same-round event as alignment evidence', () => {
    const engine = scenario();
    engine.feed(
      'early',
      {
        kind: 'kill',
        live: true,
        value: {
          ...sample(63 * 64, 'early'),
          sequence: 5,
          round: 6,
          attacker: '76561198000000001',
          victim: '76561198000000002',
          weapon: 'ak47',
        },
      },
      63000,
    );
    expect(engine.project(63000)).toMatchObject({
      available: false,
      reason: 'ambiguous-event',
      cue: null,
    });
  });
});

describe('actual file growth boundaries', () => {
  it('waits across EOF and reports idle, then reads only appended bytes', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'observer-'));
    const path = join(dir, 'grow.dem');
    const abort = new AbortController();
    try {
      await writeFile(path, Buffer.alloc(32, 7));
      let idleResolve!: () => void;
      const idle = new Promise<void>((resolve) => {
        idleResolve = resolve;
      });
      const stream = await growingDemo(path, {
        follow: true,
        signal: abort.signal,
        pollMs: 1,
        idleMs: 1,
        onIdle: idleResolve,
      });
      const reader = stream.getReader();
      expect((await reader.read()).value).toEqual(Buffer.alloc(32, 7));
      const next = reader.read();
      await idle;
      await appendFile(path, Buffer.from([1, 2, 3]));
      expect((await next).value).toEqual(Buffer.from([1, 2, 3]));
      await reader.cancel();
    } finally {
      abort.abort();
      await rm(dir, { recursive: true });
    }
  });
  it.each(['replace', 'truncate', 'rewrite'] as const)(
    'rejects %s without splicing bytes',
    async (action) => {
      const dir = await mkdtemp(join(tmpdir(), 'observer-'));
      const path = join(dir, 'grow.dem');
      const abort = new AbortController();
      try {
        await writeFile(path, Buffer.alloc(64, 7));
        const reader = (
          await growingDemo(path, { follow: true, signal: abort.signal })
        ).getReader();
        await reader.read();
        if (action === 'replace') {
          await writeFile(join(dir, 'next'), Buffer.alloc(64, 8));
          await rename(join(dir, 'next'), path);
        } else if (action === 'truncate') await writeFile(path, Buffer.alloc(8, 7));
        else {
          const file = await open(path, 'r+');
          await file.write(Buffer.from([8]), 0, 1, 40);
          await file.close();
        }
        await expect(reader.read()).rejects.toBeInstanceOf(SourceBoundary);
      } finally {
        abort.abort();
        await rm(dir, { recursive: true });
      }
    },
  );
});
