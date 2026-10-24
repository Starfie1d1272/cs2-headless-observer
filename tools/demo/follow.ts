import { open, stat } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';

export class SourceBoundary extends Error {}

/** Temporary EOF waits for growth. Each call owns one immutable file identity. */
export async function growingDemo(
  path: string,
  options: {
    signal: AbortSignal;
    follow: boolean;
    pollMs?: number;
    idleMs?: number;
    maxBytes?: number;
    onRead?: (offset: number, initialSize: number) => void;
    onIdle?: () => void;
  },
) {
  const file = await open(path, 'r');
  const initial = await file.stat();
  if (!initial.isFile()) {
    await file.close();
    throw new Error('source-not-file');
  }
  const maxBytes = options.maxBytes ?? 8 * 1024 ** 3;
  let offset = 0;
  let closed = false;
  let lastGrowth = performance.now();
  let idle = false;
  let anchor = Buffer.alloc(0);
  let anchorOffset = 16;
  const close = async () => {
    if (!closed) {
      closed = true;
      await file.close();
    }
  };
  const check = async () => {
    const [handle, current] = await Promise.all([file.stat(), stat(path)]);
    if (current.ino !== initial.ino || current.dev !== initial.dev) {
      throw new SourceBoundary('source-replaced');
    }
    if (handle.size < offset) throw new SourceBoundary('source-truncated');
    if (anchor.length) {
      const checkBytes = Buffer.alloc(anchor.length);
      const read = await file.read(checkBytes, 0, checkBytes.length, anchorOffset);
      if (read.bytesRead !== anchor.length || !checkBytes.equals(anchor)) {
        throw new SourceBoundary('source-consumed-tail-rewritten');
      }
    }
    return handle.size;
  };
  return new ReadableStream<Uint8Array>(
    {
      async pull(controller) {
        try {
          while (!closed) {
            options.signal.throwIfAborted();
            const size = await check();
            if (size > maxBytes) throw new Error('source-byte-budget');
            if (size > offset) {
              const bytes = Buffer.alloc(Math.min(64 * 1024, size - offset));
              const { bytesRead } = await file.read(bytes, 0, bytes.length, offset);
              if (bytesRead === 0) continue;
              // Verify identity again before handing bytes to the stateful parser.
              await check();
              offset += bytesRead;
              lastGrowth = performance.now();
              idle = false;
              // The demo trailer offsets in bytes 8..15 may change when recording ends.
              anchorOffset = Math.max(16, offset - 4096);
              anchor = Buffer.alloc(Math.max(0, offset - anchorOffset));
              if (anchor.length) {
                const r = await file.read(anchor, 0, anchor.length, anchorOffset);
                if (r.bytesRead !== anchor.length) throw new SourceBoundary('source-truncated');
              }
              options.onRead?.(offset, initial.size);
              controller.enqueue(bytes.subarray(0, bytesRead));
              return;
            }
            if (!options.follow) {
              await close();
              controller.close();
              return;
            }
            if (!idle && performance.now() - lastGrowth >= (options.idleMs ?? 1500)) {
              idle = true;
              options.onIdle?.();
            }
            await delay(options.pollMs ?? 50, undefined, { signal: options.signal });
          }
        } catch (error) {
          await close();
          controller.error(error);
        }
      },
      cancel: close,
    },
    { highWaterMark: 0 },
  );
}
