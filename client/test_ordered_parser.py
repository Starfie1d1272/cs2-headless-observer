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
