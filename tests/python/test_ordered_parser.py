import json
import os
import subprocess
import time
import unittest
from pathlib import Path
from ordered_parser_bridge import OrderedParserBridge
from wire import ProbeError

WORKER = os.environ.get('GOTV_ORDERED_WORKER')

@unittest.skipUnless(WORKER, 'Set GOTV_ORDERED_WORKER to the locally built worker')
class OrderedParserTests(unittest.TestCase):
    def test_forced_parent_exit_reaps_the_owned_parser(self):
        import sys
        code = "from ordered_parser_bridge import OrderedParserBridge; import os,sys; b=OrderedParserBridge(source='synthetic-owner',channel=1,world=1,worker=os.environ['GOTV_ORDERED_WORKER']); print(b.process.pid,flush=True); sys.stdin.buffer.read()"
        parent = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            pid = int(parent.stdout.readline())
            if os.name == 'nt':
                import ctypes as c
                from ctypes import wintypes as w
                k=c.WinDLL('kernel32',use_last_error=True)
                k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
                k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.CloseHandle.argtypes=[w.HANDLE]
                handle=k.OpenProcess(0x100000,False,pid)
                self.assertTrue(handle)
                try:
                    parent.kill();parent.wait(timeout=5)
                    self.assertEqual(k.WaitForSingleObject(handle,5000),0)
                finally:k.CloseHandle(handle)
            else:
                parent.kill();parent.wait(timeout=5)
                # The parser also observes its owned stdin EOF on non-Windows hosts.
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    try:os.kill(pid,0)
                    except ProcessLookupError:break
                    time.sleep(.01)
                else:self.fail('Parser survived its owner')
        finally:
            if parent.poll() is None:parent.kill();parent.wait(timeout=5)
            parent.stdin.close();parent.stdout.close();parent.stderr.close()

    def setUp(self):
        self.bridge = OrderedParserBridge(source='ahead', channel=1, world=1, worker=WORKER)

    def tearDown(self):
        self.bridge.close()
        self.assertIsNotNone(self.bridge.process.poll())
        self.assertFalse(self.bridge._writer.is_alive())
        self.assertFalse(self.bridge._reader.is_alive())

    def until(self, condition):
        rows = []
        deadline = time.monotonic() + 5
        while not condition(rows):
            rows.extend(self.bridge.poll())
            if time.monotonic() > deadline:
                self.fail('Worker did not reach expected checkpoint')
            time.sleep(.005)
        return rows

    def test_tick_order_and_world_fence(self):
        self.bridge.submit_message(4, b'\x08\x0a')
        self.bridge.submit_message(4, b'\x08\x09')
        rows = self.until(lambda _: self.bridge.completed_sequence == 2)
        ticks = [r['tick'] for r in rows if r['type'] == 'checkpoint']
        self.assertEqual(ticks, [10, 9])
        self.bridge.submit_message(51, b'')
        self.bridge.submit_message(4, b'\x08\x05')
        rows = self.until(lambda _: self.bridge.completed_sequence == 4)
        self.assertTrue(all(r['world'] == 2 for r in rows))
        self.assertEqual(self.bridge.checkpoint['tick'], 5)
        self.assertFalse(self.bridge.checkpoint['schemaReady'])

    def test_backpressure_reserves_nothing(self):
        self.until(lambda rows: any(r['type'] == 'initialized' for r in rows))
        with self.bridge._lock:
            self.bridge._queued_bytes = self.bridge.MAX_QUEUED_BYTES
        before = self.bridge.sequence, self.bridge.identity.copy()
        try:
            with self.assertRaisesRegex(ProbeError, 'backpressure'):
                self.bridge.submit_message(51, b'')
            self.assertEqual((self.bridge.sequence, self.bridge.identity), before)
        finally:
            with self.bridge._lock:
                self.bridge._queued_bytes = 0
        self.bridge.submit_message(4, b'\x08\x01')
        self.until(lambda _: self.bridge.completed_sequence == 1)

    def test_close_uses_eof_and_normal_worker_exit(self):
        self.bridge.submit_message(4, b'\x08\x0a')
        self.until(lambda _: self.bridge.completed_sequence == 1)
        self.bridge.close()
        self.assertEqual(self.bridge.process.returncode, 0)
        self.assertFalse(self.bridge._writer.is_alive())
        self.assertFalse(self.bridge._reader.is_alive())

    def test_explicit_reset_preserves_message_sequence(self):
        self.bridge.submit_message(4, b'\x08\x03')
        self.until(lambda _: self.bridge.completed_sequence == 1)
        self.bridge.reset_world()
        self.bridge.admit_creation_sequence(2)
        self.bridge.submit_message(4, b'\x08\x02')
        rows = self.until(lambda _: self.bridge.completed_sequence == 2)
        self.assertEqual(self.bridge.identity['world'], 2)
        self.assertTrue(any(r['type'] == 'creation-sequence-admitted' for r in rows))

    def test_reject_retired_receipt(self):
        self.bridge.submit_message(4, b'\x08\x03')
        self.until(lambda _: self.bridge.completed_sequence == 1)
        self.bridge.reset_world()
        self.bridge._output.put_nowait(dict(type='receipt', source='ahead', channel=1, world=1,
                sequence=1, tick=3, epoch=0, full=True, baselineAck=None))
        self.assertFalse(any(r['type'] == 'receipt' for r in self.bridge.poll()))

    def test_two_processes_do_not_share_world_or_clock(self):
        other = OrderedParserBridge(source='delayed', channel=1, world=1, worker=WORKER)
        try:
            other.submit_message(4, b'\x08\x63')
            self.bridge.submit_message(4, b'\x08\x0a')
            self.bridge.submit_message(51, b'')
            self.until(lambda _: self.bridge.completed_sequence == 2)
            deadline = time.monotonic() + 5
            while other.completed_sequence != 1:
                other.poll()
                if time.monotonic() > deadline:
                    self.fail('Second source did not reach checkpoint')
                time.sleep(.005)
            self.assertEqual(other.identity['world'], 1)
            self.assertEqual(other.checkpoint['tick'], 99)
            self.assertEqual(self.bridge.identity['world'], 2)
            self.assertEqual(self.bridge.checkpoint['tick'], -1)
        finally:
            other.close()

    def test_malformed_input_worker_terminates_without_payload_echo(self):
        payload = '\n'.join([json.dumps(dict(type='init', source='test', channel=0, world=0)),
             json.dumps(dict(type='message', source='test', channel=0, world=0,
                             sequence=1, messageId=4, bodyBase64='!!!='))]) + '\n'
        result = subprocess.run(['node', WORKER], input=payload, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(records[-1]['type'], 'error')
        self.assertNotIn('!!!=', result.stdout)

if __name__ == '__main__':
    unittest.main()
