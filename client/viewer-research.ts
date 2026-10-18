/** Research-only scalar event outlet. This module implements NO online GOTV transport. */
import { DemoReader, EntityMode } from 'cs2parser';

export interface ViewerEvent {
  kind: 'cursor' | 'weapon_fire' | 'player_death' | 'round_start' | 'round_end';
  tick: number;
  tickInterval: number | null;
  map: string | null;
  warmup: boolean | null;
  round: number | null;
  weapon: string | null;
  actor: string | null;
  target: string | null;
}

export class ViewerResearchError extends Error {
  constructor(
    readonly code:
      'tick-regressed' | 'invalid-source-tick' | 'map-or-server-changed' | 'invalid-source-clock',
    readonly previousTick?: number,
    readonly currentTick?: number,
  ) {
    super(code);
    this.name = 'ViewerResearchError';
  }
}

export interface ViewerParserCheckpoint {
  sequence: number;
  schemaFields: number;
  stringTables: number;
  serverInfo: boolean;
}

export function viewerDecoder(
  emit: (event: ViewerEvent) => void,
  processed?: (checkpoint: ViewerParserCheckpoint) => void,
  researchOptions: Record<string, unknown> = {},
) {
  const parser = new DemoReader();
  let map: string | null = null;
  let interval: number | null = null;
  let serverCount: number | undefined;
  let lastCursor = -Infinity;
  let lastSeenTick = -Infinity;
  let continuityFailure: ViewerResearchError | undefined;
  let stringTables = 0;
  let checkpointSequence = 0;
  parser.on('createstringtable', () => {
    // Count processed creation callbacks, including tables unused by this decoder.
    stringTables++;
  });
  parser.on('clearallstringtables', () => {
    stringTables = 0;
  });
  if (processed)
    parser.on('DEM_CustomData', (marker) => {
      const sequence = marker.callback_index;
      if (
        !Number.isSafeInteger(sequence) ||
        sequence !== checkpointSequence + 1 ||
        marker.data?.length
      ) {
        throw new Error('viewer-checkpoint-order');
      }
      checkpointSequence = sequence!;
      processed({
        sequence: checkpointSequence,
        schemaFields: Object.keys(parser.propIdToName ?? {}).length,
        stringTables,
        serverInfo: map !== null && interval !== null,
      });
    });
  const observeTick = (tick: number) => {
    if (continuityFailure) throw continuityFailure;
    if (!Number.isSafeInteger(tick) || tick < lastSeenTick) {
      continuityFailure = new ViewerResearchError(
        Number.isSafeInteger(tick) ? 'tick-regressed' : 'invalid-source-tick',
        Number.isFinite(lastSeenTick) ? lastSeenTick : undefined,
        Number.isFinite(tick) ? tick : undefined,
      );
      throw continuityFailure;
    }
    lastSeenTick = tick;
  };
  parser.on('tickstart', observeTick);
  parser.on('serverinfo', (info) => {
    if (map && (map !== info.map_name || serverCount !== info.server_count)) {
      throw new ViewerResearchError('map-or-server-changed');
    }
    map = info.map_name ?? null;
    serverCount = info.server_count;
    interval = info.tick_interval ?? null;
    if (!map || interval === null || !(interval > 0 && interval <= 1)) {
      throw new ViewerResearchError('invalid-source-clock');
    }
  });
  const send = (
    kind: ViewerEvent['kind'],
    weapon: string | null = null,
    actor: string | null = null,
    target: string | null = null,
  ) => {
    observeTick(parser.currentTick);
    const props = parser.gameRules?.entity?.properties;
    const warmup = props?.['CCSGameRulesProxy.CCSGameRules.m_bWarmupPeriod'];
    const round = props?.['CCSGameRulesProxy.CCSGameRules.m_totalRoundsPlayed'];
    emit({
      kind,
      tick: parser.currentTick,
      tickInterval: interval,
      map,
      warmup: typeof warmup === 'boolean' ? warmup : null,
      round: typeof round === 'number' ? round : null,
      weapon,
      actor,
      target,
    });
  };
  const id = (value: string | undefined): string | null =>
    value && /^7656119\d{10}$/.test(value) ? value : null;
  parser.on('tickend', () => {
    observeTick(parser.currentTick);
    if (!map || parser.currentTick < 0) return;
    if (interval && (parser.currentTick - lastCursor) * interval >= 1) {
      lastCursor = parser.currentTick;
      send('cursor');
    }
  });
  parser.gameEvents.on('weapon_fire', (e) => send('weapon_fire', e.weapon, id(e.player?.steamId)));
  parser.gameEvents.on('player_death', (e) =>
    send('player_death', e.weapon, id(e.attackerPlayer?.steamId), id(e.player?.steamId)),
  );
  parser.gameEvents.on('round_start', () => send('round_start'));
  parser.gameEvents.on('round_end', () => send('round_end'));
  return {
    parse: (input: ReadableStream<Uint8Array>) =>
      parser.parseDemo(input, { entities: EntityMode.ALL, ...researchOptions }),
    cancel: () => parser.cancel(),
  };
}
