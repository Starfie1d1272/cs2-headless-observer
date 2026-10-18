"""Bounded local parser subprocess. Only validated channel bodies enter this pipe."""
from collections import deque
import json
from pathlib import Path
import queue
import subprocess
import threading
from parser_stream import ParserStream
from wire import ProbeError


class ParserBridge:
    def __init__(self, node='node', worker=None):
        self._input = queue.Queue(maxsize=4)
        self._output = queue.Queue(maxsize=4096)
        self._failure = None
        self.failure_details = None
        self._closed = False
        self._parts = []
        self.sequence = 0
        self.checkpoint = None
        self._pending_controls = []
        self._receipts = deque()
        worker = Path(worker) if worker is not None else Path(__file__).with_name('parser_worker.mjs')
        self.process = subprocess.Popen([node, str(worker)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.stream = ParserStream(self._parts.append)
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._writer.start(); self._reader.start()

    def _write(self):
        try:
            while not self._closed:
                data = self._input.get()
                if data is None:
                    return
                view = memoryview(data)
                while view and not self._closed:
                    count = self.process.stdin.write(view)
                    if not count:
                        raise OSError('parser-pipe-closed')
                    view = view[count:]
        except Exception:
            if not self._closed:
                self._failure = 'parser-input-failed'

    def _read(self):
        try:
            while not self._closed:
                line = self.process.stdout.readline(65537)
                if not line:
                    if not self._closed:
                        self._failure = 'parser-exited'
                    return
                if len(line) > 65536 or not line.endswith(b'\n'):
                    raise ValueError('parser-record-size')
                row = json.loads(line)
                if isinstance(row, dict) and row.get('type') == 'error':
                    self.failure_details = {key: str(row.get(key, ''))[:limit] for key, limit in [('name', 128), ('message', 2048), ('stack', 8192)]}
                    detail = row.get('message')
                    self._failure = 'parser-error: ' + (detail[:2048] if isinstance(detail, str) else 'missing error detail')
                    return
                if not isinstance(row, dict) or row.get('type') not in ('event', 'checkpoint', 'receipt', 'recovery'):
                    raise ValueError('parser-terminal-record')
                self._output.put_nowait(row)
        except Exception:
            if not self._closed:
                self._failure = 'parser-output-failed'

    def submit(self, packet):
        self.check()
        self.stream.consume_packet(packet)
        sequence = self.stream.checkpoint()
        data = b''.join(self._parts)
        self._parts.clear()
        if len(data) > 8 * 1024**2:
            raise ProbeError('parser-frame-budget')
        try:
            self._input.put_nowait(data)
        except queue.Full:
            raise ProbeError('parser-input-backpressure') from None
        self.sequence = sequence
        return sequence

    def check(self):
        if self._failure:
            raise ProbeError(self._failure)
        if self._closed or self.process.poll() is not None:
            raise ProbeError('parser-not-running')

    def poll(self, emit):
        self.check()
        while True:
            try:
                row = self._output.get_nowait()
            except queue.Empty:
                return
            if row['type'] == 'event':
                if not isinstance(row.get('event'), dict):
                    raise ProbeError('parser-event-shape')
                emit(row['event'])
            elif row['type'] in ('receipt', 'recovery'):
                if type(row.get('tick')) is not int or not 0 <= row['tick'] <= 0x7fffffff:
                    raise ProbeError('parser-control-tick')
                if row['type'] == 'receipt':
                    value = row.get('baselineAck')
                    if value is not None and (type(value) is not int or value not in (0, 1)):
                        raise ProbeError('parser-baseline-receipt')
                else:
                    requested = row.get('request', True)
                    if type(requested) is not bool:
                        raise ProbeError('parser-recovery-request')
                    if not (requested is False and row.get('deltaFrom') is None):
                        if type(row.get('deltaFrom')) is not int or not 0 <= row['deltaFrom'] < row['tick']:
                            raise ProbeError('parser-recovery-reference')
                if len(self._pending_controls) + len(self._receipts) >= 4096:
                    raise ProbeError('parser-control-budget')
                self._pending_controls.append(row)
            else:
                previous = self.checkpoint['sequence'] if self.checkpoint else 0
                if (type(row.get('sequence')) is not int or row['sequence'] != previous + 1
                    or row['sequence'] > self.sequence
                    or type(row.get('schemaFields')) is not int or row['schemaFields'] < 0
                    or type(row.get('stringTables')) is not int or row['stringTables'] < 0
                    or type(row.get('serverInfo')) is not bool):
                    raise ProbeError('parser-checkpoint-shape')
                self._receipts.extend({**control, 'sequence': row['sequence']} for control in self._pending_controls)
                self._pending_controls.clear()
                self.checkpoint = row

    def pop_receipts(self):
        result = list(self._receipts)
        self._receipts.clear()
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._input.put_nowait(None)
        except queue.Full:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=3)
        self._writer.join(timeout=1); self._reader.join(timeout=1)
        self.process.stdin.close(); self.process.stdout.close()
