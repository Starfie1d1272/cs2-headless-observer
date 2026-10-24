import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ViewerEvent } from '../../tools/demo/viewer-research.js';

const fixture = vi.hoisted(() => ({
  mode: 'pull',
  eventWrite: vi.fn(),
  close: vi.fn(),
  reportWrite: vi.fn(),
  cancel: vi.fn(),
}));
vi.mock('node:fs/promises', async (importOriginal) => ({
  ...(await importOriginal<typeof import('node:fs/promises')>()),
  mkdir: vi.fn(),
  open: vi.fn(() => Promise.resolve({ writeFile: fixture.eventWrite, close: fixture.close })),
  writeFile: fixture.reportWrite,
}));
vi.mock('node:util', async (importOriginal) => ({
  ...(await importOriginal<typeof import('node:util')>()),
  parseArgs: () => ({
    values: { input: 'unit.dem', output: 'unit-output', seconds: '10', offset: '120' },
  }),
}));
vi.mock('../../tools/demo/follow.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../tools/demo/follow.js')>()),
  growingDemo: () =>
    Promise.resolve(
      new ReadableStream<Uint8Array>(
        {
          pull(controller) {
            controller.enqueue(Buffer.from('PBDEMS2\0'));
          },
          cancel: fixture.cancel,
        },
        { highWaterMark: 0 },
      ),
    ),
}));
vi.mock('../../tools/demo/viewer-research.js', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../tools/demo/viewer-research.js')>()),
  viewerDecoder: (emit: (event: ViewerEvent) => void) => ({
    cancel: vi.fn(),
    async parse(stream: ReadableStream<Uint8Array>) {
      const reader = stream.getReader();
      try {
        await reader.read();
        emit({
          kind: 'cursor',
          tick: 1,
          tickInterval: 1 / 64,
          map: null,
          warmup: null,
          round: null,
          weapon: null,
          actor: null,
          target: null,
        });
        if (fixture.mode === 'parser-error') throw new RangeError('private-parser-payload');
        if (fixture.mode === 'pull') await reader.read();
        return { status: 'complete' };
      } finally {
        reader.releaseLock();
      }
    },
  }),
}));

const ioError = (code: string) => Object.assign(new Error('private-path-and-credential'), { code });
const originalExitCode = process.exitCode;

beforeEach(() => {
  vi.resetModules();
  fixture.mode = 'pull';
  fixture.eventWrite.mockReset().mockRejectedValue(ioError('ENOSPC'));
  fixture.close.mockReset().mockResolvedValue(undefined);
  fixture.reportWrite.mockReset().mockResolvedValue(undefined);
  fixture.cancel.mockReset().mockResolvedValue(undefined);
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  process.exitCode = 0;
});
afterEach(() => {
  process.exitCode = originalExitCode;
  vi.restoreAllMocks();
});

describe('decoder finalization under failed writes', () => {
  it.each(['pull', 'final'] as const)(
    'does not retry a partial %s write and still closes and reports',
    async (mode) => {
      fixture.mode = mode;
      await import('../../tools/demo/decode.js');
      expect(fixture.eventWrite).toHaveBeenCalledTimes(1);
      expect(fixture.close).toHaveBeenCalledTimes(1);
      expect(fixture.cancel).toHaveBeenCalledTimes(1);
      expect(fixture.reportWrite).toHaveBeenCalledTimes(1);
      const report = JSON.parse(String(fixture.reportWrite.mock.calls[0]![1])) as Record<
        string,
        unknown
      >;
      expect(report).toMatchObject({
        outcome: 'failed',
        eventsWriteFailed: true,
        failure: { reason: 'ENOSPC', stage: 'write-events' },
      });
      expect(process.exitCode).toBe(1);
      expect(JSON.stringify(vi.mocked(console.error).mock.calls)).not.toContain('private-');
    },
  );

  it('preserves ENOSPC while cancel, close and report each fail, with a safe stderr fallback', async () => {
    fixture.cancel.mockRejectedValue(ioError('EIO'));
    fixture.close.mockRejectedValue(ioError('EBADF'));
    fixture.reportWrite.mockRejectedValue(ioError('ENOSPC'));
    await import('../../tools/demo/decode.js');
    expect(fixture.eventWrite).toHaveBeenCalledTimes(1);
    expect(fixture.close).toHaveBeenCalledTimes(1);
    expect(fixture.reportWrite).toHaveBeenCalledTimes(1);
    const stderr = vi.mocked(console.error).mock.calls;
    expect(stderr).toHaveLength(1);
    const report = JSON.parse(String(stderr[0]![0])) as Record<string, unknown>;
    expect(report).toMatchObject({
      reportWritten: false,
      outcome: 'failed',
      failure: { reason: 'ENOSPC', stage: 'write-events' },
    });
    expect(report.finalizationFailures).toEqual([
      { category: 'io', reason: 'EIO', stage: 'cancel-source' },
      { category: 'io', reason: 'EBADF', stage: 'close-events' },
      { category: 'io', reason: 'ENOSPC', stage: 'write-report' },
    ]);
    expect(JSON.stringify(stderr)).not.toContain('private-');
    expect(process.exitCode).toBe(1);
  });

  it('keeps the parser as the first cause when the final event flush and report fail', async () => {
    fixture.mode = 'parser-error';
    fixture.reportWrite.mockRejectedValue(ioError('ENOSPC'));
    await import('../../tools/demo/decode.js');
    expect(fixture.close).toHaveBeenCalledTimes(1);
    const stderr = JSON.stringify(vi.mocked(console.error).mock.calls);
    const report = JSON.parse(String(vi.mocked(console.error).mock.calls[0]![0])) as Record<
      string,
      unknown
    >;
    expect(report.failure).toMatchObject({
      stage: 'parse-demo',
      reason: 'unclassified-error',
      errorType: 'RangeError',
    });
    expect(report.finalizationFailures).toEqual([
      { category: 'io', reason: 'ENOSPC', stage: 'write-events' },
      { category: 'io', reason: 'ENOSPC', stage: 'write-report' },
    ]);
    expect(stderr).not.toContain('private-');
    expect(report.reportWritten).toBe(false);
    expect(process.exitCode).toBe(1);
  });

  it('marks an otherwise complete decode as failed if only report persistence fails', async () => {
    fixture.mode = 'final';
    fixture.eventWrite.mockResolvedValue(undefined);
    fixture.reportWrite.mockRejectedValue(ioError('ENOSPC'));
    await import('../../tools/demo/decode.js');
    const report = JSON.parse(String(vi.mocked(console.error).mock.calls[0]![0])) as Record<
      string,
      unknown
    >;
    expect(report).toMatchObject({
      outcome: 'failed',
      reportWritten: false,
      eventsWriteFailed: false,
      failure: { reason: 'ENOSPC', stage: 'write-report' },
    });
    expect(process.exitCode).toBe(1);
  });
});
