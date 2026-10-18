import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';

const [path] = process.argv.slice(2);
if (!path) throw new Error('report CAPTURE.jsonl > local-report.json');
let records = 0;
let kills = 0;
let liveKills = 0;
let incompleteIdentity = 0;
let firstLiveKill: string | null = null;
let lastLiveKill: string | null = null;
const statuses: Record<string, number> = {};
const generations = new Set<string>();
for await (const line of createInterface({ input: createReadStream(path), crlfDelay: Infinity })) {
  if (line.length > 16384) throw new Error('capture-line-budget');
  const row = JSON.parse(line) as {
    kind: string;
    reason?: string;
    live?: boolean;
    recordedAt: string;
    value?: {
      attacker?: string;
      victim?: string;
      scope: { receiverId: string; generation: number };
    };
  };
  records++;
  if (row.kind === 'status') {
    const reason = row.reason ?? 'unknown';
    statuses[reason] = (statuses[reason] ?? 0) + 1;
  }
  if (row.value)
    generations.add(JSON.stringify([row.value.scope.receiverId, row.value.scope.generation]));
  if (row.kind === 'kill') {
    kills++;
    if (!row.value?.attacker || !row.value.victim) incompleteIdentity++;
    if (row.live) {
      liveKills++;
      firstLiveKill ??= row.recordedAt;
      lastLiveKill = row.recordedAt;
    }
  }
}
console.log(
  JSON.stringify(
    {
      records,
      generations: generations.size,
      kills,
      liveKills,
      incompleteIdentity,
      firstLiveKill,
      lastLiveKill,
      statuses,
      liveRelay: 'INCONCLUSIVE: attach provider authorization and runtime sign-on evidence',
      continuousExport:
        'INCONCLUSIVE: compare firstLiveKill with independently captured tv_stoprecord/match-end time',
      programAlignment:
        'INCONCLUSIVE: attach same-event video/cursor pairs and errors; GSI alone has no proven matching tick',
      windowsIntegration: 'INCONCLUSIVE: no evidence inferred from this capture',
    },
    null,
    2,
  ),
);
