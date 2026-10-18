/** Explicit research entry. No production source manager imports this module. */
import { DemoReader, EntityMode } from 'cs2parser';

export interface ResearchScope {
  readonly matchId: string;
  readonly mapExecution: string;
  readonly receiverId: string;
  readonly generation: number;
}

export interface ResearchSample {
  readonly scope: ResearchScope;
  readonly map: string;
  readonly tick: number;
  readonly tickInterval: number;
  readonly paused: boolean | null;
  readonly round: number | null;
}

export interface ResearchKill extends ResearchSample {
  readonly sequence: number;
  readonly attacker: string | null;
  readonly victim: string | null;
  readonly weapon: string;
}

function steamId(value: string | undefined): string | null {
  return value !== undefined && /^7656119\d{10}$/.test(value) ? value : null;
}

/** Keep mutable parser objects, userinfo slots, names and raw messages inside this adapter. */
export function createResearchDemoReceiver(options: {
  scope: ResearchScope;
  sample: (sample: ResearchSample) => void;
  kill: (kill: ResearchKill) => void;
}) {
  const parser = new DemoReader();
  let map = '';
  let tickInterval = 0;
  let sequence = 0;
  let lastSample = -Infinity;
  let lastPaused: boolean | null = null;
  let serverCount: number | undefined;
  let running = false;
  parser.on('serverinfo', (info) => {
    if (map && (map !== info.map_name || serverCount !== info.server_count)) {
      throw new Error('source-map-or-server-changed: start a new receiver generation');
    }
    map = info.map_name ?? '';
    tickInterval = info.tick_interval ?? 0;
    serverCount = info.server_count;
    if (!map || !(tickInterval > 0 && tickInterval <= 1)) {
      throw new Error('invalid-source-clock');
    }
  });
  const snapshot = (): ResearchSample => {
    const rules = parser.gameRules;
    // Do not use the helper's false fallback as evidence that pause is known.
    const pause = rules?.entity?.properties['CCSGameRulesProxy.CCSGameRules.m_bGamePaused'];
    const ct = rules?.entity?.properties['CCSGameRulesProxy.CCSGameRules.m_bCTTimeOutActive'];
    const t = rules?.entity?.properties['CCSGameRulesProxy.CCSGameRules.m_bTerroristTimeOutActive'];
    const round = rules?.entity?.properties['CCSGameRulesProxy.CCSGameRules.m_totalRoundsPlayed'];
    return {
      scope: options.scope,
      map,
      tick: parser.currentTick,
      tickInterval,
      paused: [pause, ct, t].every((v) => typeof v === 'boolean')
        ? Boolean(pause || ct || t)
        : null,
      round: typeof round === 'number' ? round : null,
    };
  };
  parser.on('tickend', () => {
    const sample = snapshot();
    if (sample.tick < 0 || !map) return;
    if (sample.tick < lastSample) throw new Error('source-tick-regressed');
    if (sample.tick - lastSample >= 16 || sample.paused !== lastPaused) {
      lastSample = sample.tick;
      lastPaused = sample.paused;
      options.sample(sample);
    }
  });
  parser.gameEvents.on('player_death', (event) => {
    // CS2's userid 0 is valid in the public fixture. Do not force it through the
    // production normalizer's positive-id contract or invent a Steam64 from a slot.
    options.kill({
      ...snapshot(),
      sequence: ++sequence,
      attacker: steamId(event.attackerPlayer?.steamId),
      victim: steamId(event.player?.steamId),
      weapon: event.weapon,
    });
  });
  return {
    async parse(stream: ReadableStream<Uint8Array>) {
      running = true;
      try {
        const magic = [80, 66, 68, 69, 77, 83, 50, 0];
        let checked = 0;
        const input = stream.getReader();
        let released = false;
        const release = () => {
          if (!released) {
            released = true;
            input.releaseLock();
          }
        };
        const validated = new ReadableStream<Uint8Array>(
          {
            async pull(controller) {
              try {
                const next = await input.read();
                if (next.done) {
                  release();
                  controller.close();
                  return;
                }
                const chunk = next.value;
                for (let i = 0; i < chunk.length && checked < magic.length; i++, checked++) {
                  if (chunk[i] !== magic[checked]) throw new Error('invalid-cs2-demo-magic');
                }
                controller.enqueue(chunk);
              } catch (error) {
                await input.cancel(error);
                release();
                controller.error(error);
              }
            },
            async cancel(reason: unknown) {
              if (!released) {
                await input.cancel(reason);
                release();
              }
            },
          },
          { highWaterMark: 0 },
        );
        return await parser.parseDemo(validated, { entities: EntityMode.ALL });
      } finally {
        running = false;
      }
    },
    cancel: () => {
      if (running) parser.cancel();
    },
  };
}
