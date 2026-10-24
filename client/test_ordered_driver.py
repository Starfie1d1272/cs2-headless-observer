"""Actual Node parser pipe + synthetic SDK port only; never contacts a server."""
import os
import struct
import time
import unittest
from channel import encode_message, join_messages, reliable_frame, decode_frame, messages, unreliable_frame
from driver import ObserverDriver
from handshake import blob, number
from ordered_parser_bridge import OrderedParserBridge
from test_driver import Port
from wire import fields, scalar as pb_scalar

WORKER = os.environ.get('GOTV_ORDERED_WORKER')
def bits(v, n): return [(v >> i) & 1 for i in range(n)]
def packed(wire):
    result = bytearray((len(wire) + 7) // 8)
    for i, value in enumerate(wire): result[i // 8] |= value << (i % 8)
    return bytes(result)
def scalar(v): return [0, 1, 0] + bits(v, 8)  # Native verified PlusOne, finish codebook.
def info(): return number(1, 14191) + number(2, 7) + number(11, 1) + number(12, 0) + b'\x6d' + struct.pack('<f', 1/64) + blob(15, b'de_test')
def schema():
    serializer = number(1, 0) + number(2, 0) + number(3, 0)
    field = number(1, 2) + number(2, 1) + number(10, 3)
    return blob(1, serializer) + b''.join(blob(2, s) for s in (b'Root', b'value', b'uint32', b'fixed8')) + blob(3, field)
def table():
    base = packed(scalar(5))
    wire = [1, 1, 0] + bits(48, 8) + bits(0, 8) + [1] + bits(len(base), 17)
    for b in base: wire += bits(b, 8)
    return blob(1, b'instancebaseline') + number(2, 1) + blob(7, packed(wire))
def full(tick):
    wire = bits(0, 6) + bits(2, 2) + [0] + bits(1, 17) + bits(0, 8) + scalar(9)
    return number(2, 1) + number(10, 0) + number(12, tick) + blob(7, packed(wire)) + blob(19, b'')

@unittest.skipUnless(WORKER, 'Set GOTV_ORDERED_WORKER to locally built worker')
class OrderedDriverTests(unittest.TestCase):
    def setUp(self):
        self.port = Port()
        self.parser = OrderedParserBridge(source='ahead', channel=1, world=1, worker=WORKER)
        self.output = []
        self.driver = ObserverDriver(self.port, host_version=14191, password=bytearray(), emit=self.output.append, parser=self.parser)
        # Test starts after handshake; this is not an authenticated real connection.
        self.driver.phase = 'channel'
        self.driver._account_id = 123
        self.now = 1
    def tearDown(self):
        self.driver.close()
        self.parser.close()
    def send(self, messages, hint=0):
        body, _ = join_messages([encode_message(i, b) for i, b in messages])
        self.port.incoming.append((reliable_frame(body, hint), True))
        self.step()
    def step(self):
        self.now += 1
        self.driver.step(self.now)
    def until(self, condition):
        limit = time.monotonic() + 5
        while not condition():
            self.step()
            if time.monotonic() > limit: self.fail('Expected synthetic transition did not complete')
            time.sleep(.005)
    def initialize(self):
        self.send([(40, info()), (7, number(1, 3) + number(2, 7))])
        self.until(lambda: self.driver._new_sent)
        self.send([(41, schema()), (42, blob(2, number(1, 0) + blob(3, b'Root'))), (44, table()),
                   (7, number(1, 4) + number(2, 7))])
        self.until(lambda: self.driver._prespawn_sent)
        self.send([(7, number(1, 5) + number(2, 7))])
        self.until(lambda: self.driver._spawn_sent)
    def test_full_recovery_and_world_fencing(self):
        self.initialize()
        self.assertFalse(self.driver._full_sent)
        self.send([(4, number(1, 100)), (55, full(100))])
        self.until(lambda: self.driver._full_sent)
        self.assertEqual(self.driver._processed_entity_tick, 100)
        self.assertTrue(any(row['kind'] == 'cursor' and row['tick'] == 100 for row in self.output))
        self.send([(4, number(1, 101)), (55, number(6, 99) + number(12, 101) + blob(19, b''))])
        self.until(lambda: self.driver._full_update_outstanding)
        self.assertIsNone(self.driver._processed_entity_tick)
        self.assertTrue(any(row['kind'] == 'discontinuity' for row in self.output))
        self.send([(4, number(1, 102)), (55, full(102))])
        self.until(lambda: self.driver._processed_entity_tick == 102)
        self.until(lambda: any(row['kind'] == 'cursor' and row['tick'] == 102 for row in self.output))
        self.assertFalse(self.driver._recovery_pending)
        before = self.driver.feedback.sequence
        self.send([(51, b'')])
        self.until(lambda: self.parser.completed_sequence == self.parser.sequence)
        self.assertEqual(self.parser.identity['world'], 2)
        self.assertEqual(self.driver.signon.state, 2)
        self.assertFalse(self.driver._full_sent)
        self.assertIsNone(self.driver._processed_entity_tick)
        self.assertGreaterEqual(self.driver.feedback.sequence, before)
        self.assertEqual(self.port.closed, 0)
        self.initialize()
        self.assertFalse(self.driver._full_sent)
        self.send([(4, number(1, 5)), (55, full(5))])
        self.until(lambda: self.driver._full_sent)
        self.assertEqual(self.driver._processed_entity_tick, 5)

    def test_transport_context_is_per_frame_and_message_before_filtering(self):
        self.initialize()
        self.send([(4, number(1, 90))])
        self.until(lambda: self.parser.completed_sequence == self.parser.sequence)
        # PacketEntities itself assigns positive receive metadata before dispatch.
        self.send([(55, full(100))])
        self.until(lambda: self.driver._full_sent)
        self.assertEqual(self.driver._processed_entity_tick, 100)
        self.assertEqual(self.driver.decoder.tick, 90)
        descriptor = blob(1, number(1, 17) + blob(2, b'round_start'))
        self.send([(205, descriptor), (207, number(2, 17))], hint=200)
        self.until(lambda: self.parser.completed_sequence == self.parser.sequence)
        self.assertEqual([r for r in self.output if r['kind'] == 'round_start'][-1]['tick'], 200)
        # The framing pass sees a suppressed Tick; its game callback does not.
        self.send([(61, number(1, 1) + number(3, 1)), (61, number(1, 1) + number(3, 1)),
                   (4, number(1, 400)), (61, number(3, 0)), (207, number(2, 17))])
        self.until(lambda: self.parser.completed_sequence == self.parser.sequence)
        self.assertEqual(self.driver.decoder.tick, 90)
        self.assertEqual([r for r in self.output if r['kind'] == 'round_start'][-1]['tick'], 400)
        # An unrelated unreliable frame has no inherited reliable-frame context.
        body, _ = join_messages([encode_message(207, number(2, 17))])
        self.port.incoming.append((unreliable_frame(body, 1, 0, (0, 0, 0)), False))
        self.step()
        self.until(lambda: self.parser.completed_sequence == self.parser.sequence)
        self.assertEqual([r for r in self.output if r['kind'] == 'round_start'][-1]['tick'], 0)

    def test_source_lifecycle_events_are_forwarded_without_synthesizing_round_start(self):
        self.initialize()
        self.send([(4, number(1, 100)), (55, full(100))])
        self.until(lambda: self.driver._full_sent)
        names = ('round_prestart', 'round_poststart', 'round_freeze_end',
                 'round_officially_ended', 'round_announce_warmup', 'begin_new_match',
                 'round_announce_match_start', 'cs_win_panel_round', 'cs_win_panel_match',
                 'player_sound')
        descriptors = b''.join(blob(1, number(1, index) + blob(2, name.encode()))
                               for index, name in enumerate(names, 17))
        self.send([(205, descriptors)] + [(207, number(2, index) + number(4, 123))
                                         for index in range(17, 17 + len(names))], hint=120)
        self.until(lambda: self.parser.completed_sequence == self.parser.sequence)
        lifecycle = [row for row in self.output if row.get('type') == 'raw-event']
        self.assertEqual([row['name'] for row in lifecycle], list(names[:-1]))
        for row in lifecycle:
            self.assertEqual((row['tick'], row['eventServerTick'], row['committedTick']), (120, 123, 100))
            self.assertEqual(row['fields'], {})
            self.assertEqual((row['source'], row['world']), ('ahead', 1))
        self.assertFalse(any(row['kind'] == 'round_start' for row in self.output))

    def test_event_subscription_and_changelevel_keep_channel(self):
        self.initialize()
        descriptor = blob(1, number(1, 17) + blob(2, b'round_start'))
        self.send([(205, descriptor)])
        self.until(lambda: any(m.message_id == 206 for data, flags in self.port.sent
            for m in messages(decode_frame(data, gns_reliable=bool(flags & 8)).body)[0]))
        subscriptions = [m for data, flags in self.port.sent
            for m in messages(decode_frame(data, gns_reliable=bool(flags & 8)).body)[0] if m.message_id == 206]
        values = fields(subscriptions[-1].body)
        self.assertEqual(pb_scalar(values, 1), 0)
        self.assertEqual(len(values[2]), 16)
        self.assertEqual(values[2][0][1], 1 << 17)
        self.send([(4, number(1, 100)), (55, full(100))])
        self.until(lambda: self.driver._full_sent)
        before = self.driver.feedback.sequence
        self.send([(61, number(1, 8) + number(3, 1)), (61, number(3, 0)),
                   (7, number(1, 7) + number(2, 7)),
                   (61, number(1, 1) + number(3, 1)), (4, number(1, 2)), (61, number(3, 0))])
        self.until(lambda: self.parser.completed_sequence == self.parser.sequence)
        self.assertEqual(self.driver.signon.state, 2)
        self.assertEqual(self.parser.identity['world'], 2)
        self.assertEqual(self.driver.reliable_filter.last_tick, 1)
        self.assertEqual(self.driver.decoder.tick, 2)
        self.assertFalse(self.driver._full_sent)
        self.assertEqual(self.port.closed, 0)
        self.assertGreaterEqual(self.driver.feedback.sequence, before)

if __name__ == '__main__': unittest.main()
