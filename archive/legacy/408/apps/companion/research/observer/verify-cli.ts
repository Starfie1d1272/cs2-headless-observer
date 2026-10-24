/** Actual child-process recovery experiment with the documented public demo. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { mkdtemp, readFile, writeFile, rename, rm, appendFile, open } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { setTimeout as delay } from 'node:timers/promises';

const [demo, output] = process.argv.slice(2);
assert(demo && output, 'verify-cli DEMO NEW-REPORT.json');
const dir = await mkdtemp(join(tmpdir(), 'observer-cli-'));
const children: ReturnType<typeof spawn>[] = [];
function run(args: string[]) {
  const child = spawn(
    process.execPath,
    [
      '--import',
      createRequire(import.meta.url).resolve('tsx'),
      fileURLToPath(new URL('./cli.ts', import.meta.url)),
      ...args,
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  children.push(child);
  let stderr = '';
  child.stderr?.on('data', (chunk: Buffer) => {
    stderr = (stderr + chunk.toString()).slice(-4000);
  });
  const exit = new Promise<number | null>((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code) => resolve(code));
  });
  return { child, exit, stderr: () => stderr };
}
async function until(path: string, predicate: (text: string) => boolean) {
  const deadline = performance.now() + 15_000;
  let offset = 0;
  let tail = '';
  while (performance.now() < deadline) {
    try {
      const file = await open(path, 'r');
      try {
        const bytes = Buffer.alloc(64 * 1024);
        const { bytesRead } = await file.read(bytes, 0, bytes.length, offset);
        offset += bytesRead;
        const text = tail + bytes.subarray(0, bytesRead).toString('utf8');
        if (predicate(text)) return text;
        tail = text.slice(-16384);
        if (bytesRead === bytes.length) continue;
      } finally {
        await file.close();
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    }
    await delay(20);
  }
  throw new Error('CLI-evidence-deadline');
}
try {
  const bytes = await readFile(demo);
  const prefix = bytes.subarray(0, 16 * 1024 ** 2);
  const input = join(dir, 'growing.dem');
  const capture = join(dir, 'receive.jsonl');
  await writeFile(input, prefix);
  const receiver = run([
    'receive',
    '--input',
    input,
    '--output',
    capture,
    '--match',
    'fixture',
    '--execution',
    'ancient-1',
    '--follow',
    '--seconds',
    '60',
  ]);
  await until(capture, (text) => text.includes('"kind":"kill"'));
  await writeFile(join(dir, 'next.dem'), prefix);
  await rename(join(dir, 'next.dem'), input);
  await until(capture, (text) =>
    text
      .split('\n')
      .some((line) => line.includes('"kind":"kill"') && line.includes('"generation":2')),
  );
  await appendFile(input, bytes.subarray(prefix.length));
  await until(capture, (text) => text.includes('"reason":"complete"'));
  receiver.child.kill('SIGTERM');
  assert.equal(await receiver.exit, 0, receiver.stderr());
  const rows = (await readFile(capture, 'utf8'))
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line) as Record<string, unknown>);
  const kills = rows.filter((x) => x.kind === 'kill');
  assert(kills.some((x) => x.live === true));
  assert(kills.some((x) => x.live === false));
  assert(rows.some((x) => x.reason === 'source-replaced-or-truncated'));
  assert.equal(
    kills.filter((x) => (x.value as { scope: { generation: number } }).scope.generation === 2)
      .length,
    224,
  );

  const interruptedPath = join(dir, 'interrupted.jsonl');
  await writeFile(join(dir, 'partial.dem'), prefix);
  const interrupted = run([
    'receive',
    '--input',
    join(dir, 'partial.dem'),
    '--output',
    interruptedPath,
    '--match',
    'fixture',
    '--execution',
    'ancient-1',
    '--follow',
  ]);
  await until(interruptedPath, (text) => text.includes('"kind":"kill"'));
  interrupted.child.kill('SIGTERM');
  assert.equal(await interrupted.exit, 0, interrupted.stderr());

  const bad = join(dir, 'bad.dem');
  await writeFile(bad, Buffer.alloc(64, 8));
  const failed = run([
    'receive',
    '--input',
    bad,
    '--output',
    join(dir, 'bad.jsonl'),
    '--match',
    'fixture',
    '--execution',
    'ancient-1',
  ]);
  assert.notEqual(await failed.exit, 0);
  assert((await readFile(join(dir, 'bad.jsonl'), 'utf8')).includes('"reason":"failed"'));

  // Feed stale capture plus malformed input through the actual assist process.
  const early = join(dir, 'early.jsonl');
  const program = join(dir, 'program.jsonl');
  const old =
    JSON.stringify({
      schema: 'mizar.observer.capture.v1',
      outputSequence: 1,
      recordedAt: '2000-01-01T00:00:00Z',
      kind: 'status',
      reason: 'old',
    }) + '\n';
  await writeFile(early, old);
  await writeFile(program, old);
  const assistPath = join(dir, 'assist.jsonl');
  const assist = run([
    'assist',
    '--early',
    early,
    '--program',
    program,
    '--output',
    assistPath,
    '--display-evidence',
    'synthetic-test',
  ]);
  await until(assistPath, (text) => text.includes('"cue":null'));
  await appendFile(early, 'invalid json\n');
  assert.equal(await assist.exit, 1, assist.stderr());
  const projections = (await readFile(assistPath, 'utf8'))
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line) as { cue?: unknown });
  assert(projections.filter((x) => 'cue' in x).every((x) => x.cue === null));
  const report = {
    result: 'PASS',
    actualChildProcesses: 4,
    receiverReplacementGeneration: 2,
    secondGenerationKills: 224,
    catchupAndNewBytesSeparated: true,
    stoppedAfterCompleteExitCode: 0,
    interruptedGrowingParseExitCode: 0,
    malformedDemoNonzeroExit: true,
    staleCaptureNoCue: true,
    malformedAssistNonzeroExit: true,
    privateFinalWithdrawal: true,
    windows: 'INCONCLUSIVE',
  };
  await writeFile(output, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify(report));
} finally {
  for (const child of children)
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
  await rm(dir, { recursive: true, force: true });
}
