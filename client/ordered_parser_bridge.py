"""Generation-fenced ordered parser pipe. No Steam/network authority lives here."""
from collections import deque
import base64
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from wire import ProbeError


class OrderedParserBridge:
    ordered = True
    MAX_QUEUED_BYTES = 16 * 1024**2
    MAX_BODY = 4 * 1024**2
    FORWARDED_EVENTS = frozenset({
        'player_death', 'player_hurt', 'weapon_fire', 'grenade_thrown',
        'bomb_beginplant', 'bomb_abortplant', 'bomb_planted', 'bomb_begindefuse',
        'bomb_abortdefuse', 'bomb_defused', 'bomb_exploded', 'bomb_dropped', 'bomb_pickup',
        'round_start', 'round_end',
        'round_prestart', 'round_poststart', 'round_freeze_end', 'round_officially_ended',
        'round_announce_warmup', 'begin_new_match', 'round_announce_match_start',
        'cs_win_panel_round', 'cs_win_panel_match',
    })

    def __init__(self, *, source, channel, world, worker, node='node'):
        if (not isinstance(source, str) or not source or len(source) > 128 or
                any(type(x) is not int or x < 0 for x in (channel, world))):
            raise ProbeError('ordered-parser-identity')
        self.identity = dict(source=source, channel=channel, world=world)
        self.sequence = 0
        self.diagnostics = deque(maxlen=32)
        self.completed_sequence = 0
        self.checkpoint = None
        self._pending_controls = deque()
        self._receipts = deque()
        self._subscriptions = None
        self._closed = False
        self._failure = None
        self._queued_bytes = 0
        self._lock = threading.Lock()
        self._input = queue.Queue(maxsize=16)
        self._output = queue.Queue(maxsize=4096)
        from process_job import ParserJob
        self._job = ParserJob()
        try:
            self.process = subprocess.Popen([node, str(Path(worker))], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self._job.assign(self.process)
        except BaseException:
            if hasattr(self, 'process') and self.process.poll() is None:
                self.process.kill(); self.process.wait(timeout=3)
            self._job.close()
            raise
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._writer.start()
        self._reader.start()
        try:
            self._enqueue(dict(type='init', **self.identity))
            self.admit_creation_sequence(0)
        except Exception:
            self.close()
            raise

    def _enqueue(self, row):
        self.check()
        data = b''.join((json.dumps(item, separators=(',', ':'), ensure_ascii=True) + '\n').encode()
                        for item in (row if isinstance(row, list) else [row]))
        if len(data) > 8 * 1024**2:
            raise ProbeError('ordered-parser-record-budget')
        with self._lock:
            if self._queued_bytes + len(data) > self.MAX_QUEUED_BYTES:
                raise ProbeError('ordered-parser-input-backpressure')
            try:
                self._input.put_nowait(data)
            except queue.Full:
                raise ProbeError('ordered-parser-input-backpressure') from None
            self._queued_bytes += len(data)

    def _write(self):
        try:
            while not self._closed:
                data = self._input.get()
                if data is None:
                    return
                view = memoryview(data)
                while view:
                    count = self.process.stdin.write(view)
                    if not count:
                        raise OSError('parser-pipe-closed')
                    view = view[count:]
                with self._lock:
                    self._queued_bytes -= len(data)
        except Exception as error:
            if not self._closed:
                self._failure = 'ordered-parser-input-failed: ' + type(error).__name__

    def _read(self):
        try:
            while not self._closed:
                line = self.process.stdout.readline(65537)
                if not line:
                    if not self._closed:
                        self._failure = 'ordered-parser-exited'
                    return
                if len(line) > 65536 or not line.endswith(b'\n'):
                    raise ValueError('record-size')
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('record-shape')
                if row.get('type') == 'error':
                    self._failure = 'ordered-parser-error: ' + str(row.get('message', 'unknown'))[:1024]
                    return
                if row.get('type') not in {'initialized', 'world-reset', 'creation-sequence-admitted',
                        'checkpoint', 'receipt', 'cursor', 'raw-event', 'gap', 'recovery', 'blocked', 'event-subscriptions', 'diagnostic'}:
                    raise ValueError('record-type')
                self._output.put_nowait(row)
        except Exception as error:
            if not self._closed:
                self._failure = 'ordered-parser-output-failed: ' + type(error).__name__

    def submit_message(self, message_id, body):
        return self.submit_batch([('message', message_id, body)])

    def submit_batch(self, actions):
        identity = self.identity.copy()
        sequence = self.sequence
        rows = []
        for action in actions:
            if action[0] == 'message':
                _, message_id, body, *context = action
                if type(message_id) is not int or message_id < 0 or not isinstance(body, bytes) or len(body) > self.MAX_BODY:
                    raise ProbeError('ordered-parser-message-budget')
                sequence += 1
                if len(context) > 1 or (context and (type(context[0]) is not int or not -0x80000000 <= context[0] <= 0x7fffffff)):
                    raise ProbeError('ordered-parser-message-context')
                rows.append(dict(type='message', **identity, sequence=sequence, messageId=message_id,
                                 bodyBase64=base64.b64encode(body).decode('ascii'),
                                 **({'contextTick': context[0]} if context else {})))
                if message_id == 51:
                    identity = {**identity, 'world': identity['world'] + 1}
            elif action[0] == 'admit':
                if type(action[1]) is not int or not 0 <= action[1] <= 0xffffffff:
                    raise ProbeError('ordered-parser-creation-sequence')
                rows.append(dict(type='admit-creation-sequence', **identity, creationSequence=action[1]))
            elif action[0] == 'reset':
                identity = {**identity, 'world': identity['world'] + 1}
                rows.append(dict(type='reset-world', **identity))
            else:
                raise ProbeError('ordered-parser-batch-action')
        if rows:
            self._enqueue(rows)
        self.sequence = sequence
        if identity != self.identity:
            self.checkpoint = None
            self._pending_controls.clear()
            self._receipts.clear()
            self._subscriptions = None
        self.identity = identity
        return sequence

    def admit_creation_sequence(self, sequence):
        if type(sequence) is not int or not 0 <= sequence <= 0xffffffff:
            raise ProbeError('ordered-parser-creation-sequence')
        self._enqueue(dict(type='admit-creation-sequence', **self.identity, creationSequence=sequence))

    def reset_world(self):
        self.submit_batch([('reset',)])

    def check(self):
        if self._failure:
            raise ProbeError(self._failure)
        if self._closed or self.process.poll() is not None:
            raise ProbeError('ordered-parser-not-running')

    def poll(self, emit=None):
        self.check()
        result = []
        while True:
            try:
                row = self._output.get_nowait()
            except queue.Empty:
                return result
            if row.get('source') != self.identity['source'] or row.get('channel') != self.identity['channel']:
                raise ProbeError('ordered-parser-output-owner')
            world = row.get('world')
            if type(world) is not int or world > self.identity['world']:
                raise ProbeError('ordered-parser-output-world')
            sequence = row.get('sequence')
            if sequence is not None and (type(sequence) is not int or not 1 <= sequence <= self.sequence):
                raise ProbeError('ordered-parser-output-sequence')
            if row['type'] == 'initialized' and row.get('protocol') != 3:
                raise ProbeError('ordered-parser-protocol-version')
            if row['type'] == 'checkpoint':
                if sequence is None or sequence <= self.completed_sequence:
                    raise ProbeError('ordered-parser-checkpoint-order')
                self.completed_sequence = sequence
            if world != self.identity['world']:
                continue  # Retired output cannot grant readiness, identities or ACKs.
            if row['type'] == 'checkpoint':
                if type(row.get('schemaReady')) is not bool or type(row.get('stringTables')) is not int:
                    raise ProbeError('ordered-parser-checkpoint-shape')
                self.checkpoint = row
            if row['type'] == 'diagnostic':
                self.diagnostics.append({key: row.get(key) for key in ('reason', 'eventId')})
            if row['type'] == 'receipt':
                if (type(row.get('tick')) is not int or row['tick'] < 1 or
                        type(row.get('epoch')) is not int or row['epoch'] < 0 or
                        type(row.get('full')) is not bool or
                        (row.get('baselineAck') is not None and (type(row.get('baselineAck')) is not int or row['baselineAck'] not in (0, 1)))):
                    raise ProbeError('ordered-parser-receipt-shape')
            if row['type'] in ('receipt', 'recovery'):
                if len(self._pending_controls) + len(self._receipts) >= 4096:
                    raise ProbeError('ordered-parser-receipt-budget')
                self._pending_controls.append(row)
            if row['type'] == 'checkpoint':
                while self._pending_controls and self._pending_controls[0]['sequence'] <= sequence:
                    self._receipts.append(self._pending_controls.popleft())
            if row['type'] == 'recovery' and row.get('worldReinitialization'):
                raise ProbeError('ordered-parser-world-reinitialization: ' + str(row.get('reason', 'unknown'))[:1024])
            if row['type'] == 'event-subscriptions':
                self._subscriptions = row
            if emit is not None and row['type'] in ('gap', 'recovery', 'world-reset'):
                emit(dict(kind='discontinuity', reason=row.get('reason', row['type']),
                          **{key: row.get(key) for key in ('source', 'channel', 'world', 'sequence', 'tick')}))
            if emit is not None and (row['type'] == 'cursor' or (row['type'] == 'raw-event' and row.get('name') in self.FORWARDED_EVENTS)):
                emit(dict(kind='cursor' if row['type'] == 'cursor' else row['name'],
                    **({key: row.get(key) for key in ('type', 'name', 'fields', 'players', 'pawns', 'committedTick')} if row['type'] == 'raw-event' else {}),
                    **{key: row.get(key) for key in ('tick', 'tickInterval', 'map',
                    'warmup', 'round', 'weapon', 'actor', 'target', 'source', 'channel', 'world', 'sequence',
                    'descriptorGeneration', 'eventServerTick', 'networkTick', 'identityResolved')}))
            result.append(row)

    def pop_receipts(self):
        result = list(self._receipts)
        self._receipts.clear()
        return result

    def pop_subscriptions(self):
        result = self._subscriptions
        self._subscriptions = None
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            try:
                self._input.put_nowait(None)
            except queue.Full:
                pass
            self._writer.join(timeout=1)
            if not self._writer.is_alive():
                try:
                    self.process.stdin.close()  # Complete records then EOF; let the worker exit normally.
                except OSError:
                    pass
            if self.process.poll() is None:
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            self._writer.join(timeout=1)
            self._reader.join(timeout=1)
            self.process.stdin.close()
            self.process.stdout.close()
        finally:
            self._job.close()
