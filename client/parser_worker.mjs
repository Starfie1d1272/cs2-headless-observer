// Local process protocol: adapted Demo bytes in; scalar events/checkpoints out.
// No networking, Steam credentials, arbitrary commands or rendering.
import { Readable } from 'node:stream';
import process from 'node:process';
import { ordinaryViewerProtocol } from 'cs2parser';
import { viewerDecoder } from './viewer-research.ts';

const send = (record) => {
  if (process.stdout.writableLength > 8 * 1024 ** 2) throw new Error('parser-output-budget');
  process.stdout.write(JSON.stringify(record) + '\n');
};
if (ordinaryViewerProtocol !== 1) throw new Error('ordinary-viewer-parser-build-required');
let recovering = false;
const decoder = viewerDecoder(
  (event) => {
    if (!recovering) send({ type: 'event', event });
  },
  (checkpoint) => send({ type: 'checkpoint', ...checkpoint }),
  {
    ordinaryViewer: true,
    onOnlineReceipt: (receipt) => {
      recovering = false;
      send({ type: 'receipt', ...receipt });
    },
    onOnlineRecovery: (gap) => {
      recovering = true;
      send({ type: 'recovery', ...gap });
    },
  },
);
process.once('SIGTERM', () => decoder.cancel());
process.stdout.on('error', () => {
  decoder.cancel();
  process.exitCode = 1;
});
try {
  const outcome = await decoder.parse(Readable.toWeb(process.stdin));
  send({ type: 'end', status: outcome.status });
  if (outcome.status === 'error') process.exitCode = 1;
} catch (error) {
  send({
    type: 'error',
    code: 'parser-failed',
    name: String(error?.name ?? 'Error').slice(0, 128),
    message: String(error?.message ?? error).slice(0, 2048),
    stack: String(error?.stack ?? '').slice(0, 8192),
  });
  process.exitCode = 1;
}
