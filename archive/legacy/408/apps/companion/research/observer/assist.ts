import type { ResearchKill, ResearchSample } from '@mizar/telemetry-cstv/research';

export type Role = 'early' | 'program';
export type Observation =
  | { kind: 'sample'; value: ResearchSample; live: boolean }
  | { kind: 'kill'; value: ResearchKill; live: boolean }
  | { kind: 'status'; reason: string };
type Point = { value: ResearchSample; at: number };
type SeenKill = { value: ResearchKill; at: number };
type Anchor = { x: number; y: number; at: number };
const scopeKey = (s: ResearchSample) => JSON.stringify([s.scope, s.map, s.tickInterval]);
const eventKey = (k: ResearchKill) => JSON.stringify([k.round, k.attacker, k.victim, k.weapon]);
const seconds = (s: ResearchSample) => s.tick * s.tickInterval;

/** Private research state, deliberately not a RuntimeState or Program projection. */
export class Assist {
  private points: Partial<Record<Role, Point>> = {};
  private kills: Record<Role, Map<string, SeenKill>> = { early: new Map(), program: new Map() };
  private anchors: Anchor[] = [];
  private used = new Set<string>();
  private lastSequence: Record<Role, number> = { early: 0, program: 0 };
  private candidates: ResearchKill[] = [];
  private reason = 'awaiting-sources';
  private healthy = false;
  private lastNow = -Infinity;
  private programRate: number | null = null;
  private ratePoint: Point | undefined;

  constructor(
    private readonly options: {
      displayEvidence: string | null;
      horizonSeconds?: number;
      staleMs?: number;
      maxKills?: number;
    },
  ) {
    if (!(this.horizon > 0 && this.horizon <= 30)) throw new Error('invalid-cue-horizon');
  }

  private get horizon() {
    return this.options.horizonSeconds ?? 10;
  }
  private get staleMs() {
    return this.options.staleMs ?? 1500;
  }

  invalidate(reason: string) {
    this.kills = { early: new Map(), program: new Map() };
    this.used.clear();
    this.anchors = [];
    this.candidates = [];
    this.healthy = false;
    this.programRate = null;
    this.ratePoint = undefined;
    this.reason = reason;
  }

  private clock(now: number) {
    if (!Number.isFinite(now) || now < this.lastNow) throw new Error('non-monotonic-clock');
    this.lastNow = now;
  }

  feed(role: Role, row: Observation, now: number) {
    this.clock(now);
    if (row.kind === 'status') {
      this.invalidate(row.reason);
      delete this.points[role];
      this.lastSequence[role] = 0;
      return;
    }
    const value = row.value;
    const previous = this.points[role];
    if (
      previous &&
      (scopeKey(previous.value) !== scopeKey(value) || value.tick < previous.value.tick)
    ) {
      this.invalidate('source-boundary');
      this.lastSequence[role] = 0;
    } else if (previous && now - previous.at > this.staleMs) {
      this.invalidate('stale-recovery');
    }
    if (!row.live || value.paused !== false) {
      this.invalidate(!row.live ? 'catchup' : 'paused-or-unknown');
      delete this.points[role];
      return;
    }
    if (role === 'program' && row.kind === 'sample') {
      if (this.ratePoint && now - this.ratePoint.at >= 500) {
        this.programRate =
          (seconds(value) - seconds(this.ratePoint.value)) / ((now - this.ratePoint.at) / 1000);
        this.ratePoint = { value, at: now };
        if (this.programRate < 0.8 || this.programRate > 1.2) {
          this.invalidate('program-playback-rate');
        }
      }
      this.ratePoint ??= { value, at: now };
    }
    this.points[role] = { value, at: now };
    const early = this.points.early?.value;
    const program = this.points.program?.value;
    if (!early || !program) return;
    if (
      early.scope.matchId !== program.scope.matchId ||
      early.scope.mapExecution !== program.scope.mapExecution ||
      early.map !== program.map
    ) {
      this.invalidate('binding-mismatch');
      return;
    }
    // A new source cannot restore the old alignment using queued or replayed events.
    if (row.kind !== 'kill') return;
    const kill = row.value;
    if (kill.sequence <= this.lastSequence[role]) return;
    this.lastSequence[role] = kill.sequence;
    if (!kill.attacker || !kill.victim || kill.round === null) return;
    const key = eventKey(kill);
    if (this.kills[role].has(key)) {
      this.invalidate('ambiguous-event');
      return;
    }
    this.kills[role].set(key, { value: kill, at: now });
    if (role === 'early' && this.healthy) this.candidates.push(kill);
    for (const r of ['early', 'program'] as const) {
      for (const [k, item] of this.kills[r]) if (now - item.at > 300_000) this.kills[r].delete(k);
    }
    if (
      this.kills.early.size + this.kills.program.size > (this.options.maxKills ?? 2048) ||
      this.candidates.length > 2048 ||
      this.used.size > 2048
    ) {
      this.invalidate('buffer-budget');
      return;
    }
    const e = this.kills.early.get(key);
    const p = this.kills.program.get(key);
    if (!e || !p || this.used.has(key)) return;
    this.used.add(key);
    this.anchors.push({ x: seconds(e.value), y: seconds(p.value), at: now });
    this.anchors = this.anchors.slice(-12);
    const fit = this.fit();
    if (fit && (Math.abs(fit.slope - 1) > 0.002 || fit.residual > 0.1)) {
      this.invalidate('alignment-drift');
      return;
    }
    if (fit) {
      this.healthy = true;
      this.reason = 'aligned';
    }
  }

  private fit() {
    if (this.anchors.length < 3) return null;
    const n = this.anchors.length;
    const x = this.anchors.reduce((s, a) => s + a.x, 0) / n;
    const y = this.anchors.reduce((s, a) => s + a.y, 0) / n;
    const xx = this.anchors.reduce((s, a) => s + (a.x - x) ** 2, 0);
    if (
      Math.max(...this.anchors.map((a) => a.x)) - Math.min(...this.anchors.map((a) => a.x)) < 5 ||
      xx === 0
    )
      return null;
    const slope = this.anchors.reduce((s, a) => s + (a.x - x) * (a.y - y), 0) / xx;
    const offset = y - slope * x;
    const residual = Math.max(...this.anchors.map((a) => Math.abs(a.y - slope * a.x - offset)));
    return { slope, offset, residual, anchors: n };
  }

  project(now: number) {
    this.clock(now);
    const early = this.points.early;
    const program = this.points.program;
    if (!early || !program || now - early.at > this.staleMs || now - program.at > this.staleMs) {
      this.invalidate('source-stale');
    }
    if (this.anchors.length && now - this.anchors.at(-1)!.at > 120_000)
      this.invalidate('alignment-expired');
    const fit = this.fit();
    const base = {
      schema: 'mizar.observer.private.v1',
      role: 'lookahead',
      productionReady: false,
    } as const;
    if (
      !this.healthy ||
      !fit ||
      !program ||
      !early ||
      this.programRate === null ||
      !this.options.displayEvidence
    ) {
      return {
        ...base,
        available: false as const,
        reason: !this.options.displayEvidence ? 'program-display-unverified' : this.reason,
        cue: null,
      };
    }
    const programSeconds = seconds(program.value) + (now - program.at) / 1000;
    const lead = fit.slope * seconds(early.value) + fit.offset - programSeconds;
    // Drop expired events permanently. Only one nearest upcoming kill is exposed.
    this.candidates = this.candidates.filter(
      (k) => fit.slope * seconds(k) + fit.offset > programSeconds,
    );
    const candidate = this.candidates.find(
      (k) => fit.slope * seconds(k) + fit.offset - programSeconds <= this.horizon,
    );
    const uncertainty = fit.residual + program.value.tickInterval + (now - program.at) / 1000;
    const remaining = candidate
      ? fit.slope * seconds(candidate) + fit.offset - programSeconds
      : null;
    const cue =
      candidate && remaining !== null && remaining > uncertainty && lead > uncertainty
        ? {
            attacker: candidate.attacker,
            victim: candidate.victim,
            remainingSeconds: remaining,
            uncertaintySeconds: uncertainty,
          }
        : null;
    return {
      ...base,
      available: true as const,
      reason: 'aligned',
      cue,
      leadSeconds: lead,
      driftPpm: (fit.slope - 1) * 1e6,
      residualSeconds: fit.residual,
      anchors: fit.anchors,
      displayEvidence: this.options.displayEvidence,
    };
  }
}
