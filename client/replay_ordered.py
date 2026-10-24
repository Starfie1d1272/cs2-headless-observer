"""Replay private SDK channel samples offline; never initializes Steam or sockets.

This checks the current driver/parser against captured application traffic. It
cannot prove authentication, reconnect behavior or a working online endpoint.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
from driver import MAGIC, ObserverDriver
from ordered_parser_bridge import OrderedParserBridge


class OfflinePort:
    def send(self, data, flags):
        pass  # Replay acknowledgements never leave this process.

    def close(self):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--worker', type=Path, required=True)
    ap.add_argument('--node', default='node')
    ap.add_argument('--host-version', type=int, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    parser = OrderedParserBridge(source='offline:channel-replay', channel=1, world=1,
                                 worker=args.worker, node=args.node)
    counts = {}
    frames = 0
    last_ms = 0
    def digest(path):
        with path.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest()

    result = {'evidence': 'CAPTURED_CHANNEL_OFFLINE_REPLAY', 'online': False,
              'sampleSha256': digest(args.input), 'workerSha256': digest(args.worker)}
    with (args.output / 'events.jsonl').open('x', encoding='utf8') as events:
        def emit(row):
            counts[row['kind']] = counts.get(row['kind'], 0) + 1
            events.write(json.dumps(row) + '\n')

        driver = ObserverDriver(OfflinePort(), host_version=args.host_version,
                                password=bytearray(), emit=emit, parser=parser)
        driver.phase = 'channel'
        driver._account_id = 1  # Local discarded ClientInfo, never an online identity.
        try:
            with args.input.open('rb') as source:
                if source.read(len(MAGIC)) != MAGIC:
                    raise ValueError('sample-magic')
                while header := source.read(13):
                    if len(header) != 13:
                        raise ValueError('sample-truncated-header')
                    size, elapsed, reliable = struct.unpack('<IQB', header)
                    if not 0 < size <= 4 * 1024**2 or reliable not in (0, 1) or elapsed < last_ms:
                        raise ValueError('sample-record-boundary')
                    body = source.read(size)
                    if len(body) != size:
                        raise ValueError('sample-truncated-body')
                    driver.receive(body, bool(reliable), elapsed)
                    deadline = time.monotonic() + 15
                    while parser.completed_sequence < driver._parser_sequence:
                        parser.poll(emit)
                        if time.monotonic() >= deadline:
                            raise TimeoutError('replay-parser-timeout')
                        time.sleep(.0005)
                    driver._advance_initialization(elapsed)
                    driver._send_processed_tick(elapsed)
                    frames += 1
                    last_ms = elapsed
            result.update(complete=True, frames=frames, sampleDurationMs=last_ms,
                          counts=counts, parserCheckpoint=parser.checkpoint)
        except Exception as error:
            result.update(complete=False, frames=frames, sampleDurationMs=last_ms,
                          counts=counts, error=type(error).__name__ + ': ' + str(error))
            raise
        finally:
            driver.close()
            parser.close()
            (args.output / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
