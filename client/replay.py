#!/usr/bin/env python3
"""Replay private post-connection channel samples; never opens a socket or SDK."""
import argparse
import json
from pathlib import Path
import struct
from channel import MAX_BYTES, decode_frame, messages, UnreliableOrder
from driver import MAGIC
from live import LiveDecoder
from wire import ProbeError


def replay(handle, emit):
    if handle.read(len(MAGIC)) != MAGIC:
        raise ProbeError('sample-magic')
    decoder, order = LiveDecoder(emit), UnreliableOrder(initial=0)
    frames, previous, first, last = 0, -1, None, None
    while header := handle.read(13):
        if len(header) != 13:
            raise ProbeError('sample-truncated-header')
        size, elapsed, reliable = struct.unpack('<IQB', header)
        if not 0 < size <= MAX_BYTES or reliable not in (0, 1) or elapsed < previous:
            raise ProbeError('sample-header-boundary')
        data = handle.read(size)
        if len(data) != size:
            raise ProbeError('sample-truncated-body')
        previous, last = elapsed, elapsed
        if first is None: first = elapsed
        frame = decode_frame(data, gns_reliable=bool(reliable))
        frames += 1
        if not frame.reliable and not order.accept(frame)['accepted']:
            continue
        decoded, _ = messages(frame.body)
        for message in decoded:
            decoder.consume(message.message_id, message.body)
    return {'evidence': 'LOCAL_SAMPLE_REPLAY_NOT_NEW_LIVE_RECEIPT', 'frames': frames,
            'recorded_receive_span_ms': None if first is None else last - first,
            'net_message_counts': decoder.counts, 'initialization_blockers': decoder.blockers(),
            'online_success': 'INCONCLUSIVE'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    args = ap.parse_args()
    counts = {}
    def emit(event): counts[event['kind']] = counts.get(event['kind'], 0) + 1
    try:
        with args.input.open('rb') as handle: result = replay(handle, emit)
    except (ValueError, OSError):
        raise SystemExit('sample-replay-failed-details-omitted') from None
    result['events'] = counts
    print(json.dumps(result))


if __name__ == '__main__':
    main()
