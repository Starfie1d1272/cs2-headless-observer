"""Synthetic schema boundary tests; no authentication or source traffic."""
import struct
import unittest
from handshake import number, blob
from live_probe import LiveDecoder, client_info
from channel import encode_message, join_messages, messages, unreliable_frame, decode_frame
from wire import fields, scalar


def descriptor(event_id=17, name=b'weapon_fire'):
    key = number(1, 1) + blob(2, b'weapon')
    unknown = number(1, 9) + blob(2, b'userid')
    return blob(1, number(1, event_id) + blob(2, name) + blob(3, key) + blob(3, unknown))


def event(tick=42, weapon=b'weapon_awp'):
    return number(2, 17) + blob(3, number(1, 1) + blob(2, weapon)) + blob(3, number(1, 9) + number(5, 4)) + number(4, tick)


class LiveTest(unittest.TestCase):
    def test_initial_load_creation_sequence_does_not_require_later_update(self):
        d = LiveDecoder(lambda _: None)
        d.consume(8, blob(1, b'world') + number(4, 1) + number(10, 71) + number(16, 10))
        self.assertEqual(d.max_creation_sequence, 10)
        self.assertEqual(d.spawn_groups[1]['creation_sequence'], 10)
        self.assertEqual(d.ready_spawn_groups, set())
        d.consume(51, b'')
        self.assertEqual(d.max_creation_sequence, 0)

    def test_descriptor_driven_event_retains_raw_weapon_and_event_tick(self):
        output = []
        d = LiveDecoder(output.append)
        d.consume(4, number(1, 44))
        d.consume(205, descriptor())
        d.consume(207, event())
        self.assertEqual((output[0]['kind'], output[0]['tick'], output[0]['weapon']), ('weapon_fire', 42, 'weapon_awp'))
        self.assertEqual(output[0]['tick_source'], 'event.server_tick')
        self.assertIsNone(output[0]['actor'])
        self.assertEqual(output[0]['online_success'], 'INCONCLUSIVE')
        d.consume(207, number(2, 900))
        self.assertEqual(d.unresolved_events, 1)
        self.assertEqual(len(output), 1)
        with self.assertRaisesRegex(ValueError, 'event-key-count'):
            d.consume(207, number(2, 17))
        with self.assertRaisesRegex(ValueError, 'event-name-mismatch'):
            d.consume(207, event() + blob(1, b'player_death'))

    def test_missing_event_tick_uses_only_explicit_net_tick(self):
        output = []
        d = LiveDecoder(output.append)
        d.consume(205, blob(1, number(1, 17) + blob(2, b'round_start')))
        d.consume(207, number(2, 17))
        self.assertIsNone(output[-1]['tick'])
        d.consume(4, number(1, 60))
        d.consume(207, number(2, 17))
        self.assertEqual((output[-1]['tick'], output[-1]['tick_source']), (60, 'net_Tick'))
        d.consume(4, number(1, 59))
        d.consume(207, number(2, 17))
        self.assertEqual(output[-1]['tick'], 59)
        self.assertIn(17, d.descriptors)

    def test_unknown_group_creation_advances_global_without_inventing_group(self):
        d = LiveDecoder(lambda _: None)
        d.consume(11, number(1, 99) + number(2, 3) + number(3, 8))
        self.assertEqual(d.max_creation_sequence, 8)
        self.assertEqual(d.spawn_groups, {})
        d.consume(12, number(1, 99) + number(3, 5))
        self.assertEqual(d.spawn_groups, {})
        d.consume(51, b'')
        self.assertEqual(d.max_creation_sequence, 0)
        self.assertIsNone(d.server)
        self.assertIsNone(d.tick)

    def test_serverinfo_and_table_presence_never_unlock_initialization(self):
        d = LiveDecoder(lambda _: None)
        info = number(1, 14191) + number(2, 7) + b'\x6d' + struct.pack('<f', 1 / 64) + blob(15, b'de_test')
        d.consume(40, info)
        d.consume(42, blob(2, number(1, 0) + blob(3, b'CCSGameRulesProxy')))
        d.consume(44, blob(1, b'instancebaseline'))
        d.consume(45, number(1, 0))
        d.consume(55, b'')
        self.assertFalse(d.tables[0]['decoded'])
        self.assertIn('entity-full-snapshot', d.blockers())
        with self.assertRaisesRegex(ValueError, 'serverinfo-changed'):
            d.consume(40, info.replace(b'de_test', b'de_next'))
        with self.assertRaisesRegex(ValueError, 'before-create'):
            d.consume(45, number(1, 1))
        payload = client_info(server_count=7, send_table_crc=0x12345678, account_id=123)
        self.assertEqual(scalar(fields(payload), 1, 5), b'\x78\x56\x34\x12')
        self.assertEqual(scalar(fields(payload), 3), 0)
        full_tables = fields(client_info(server_count=7, account_id=123))
        self.assertEqual(scalar(full_tables, 1, 5), bytes(4))
        self.assertEqual(scalar(full_tables, 2), 7)
        self.assertEqual(scalar(full_tables, 5), 123)
        # The event-only world keeps parent identities and waits for complete
        # manifests; it never executes a resource path or loads a save game.
        child = blob(1, b'child') + number(4, 2) + number(18, 1)
        d.consume(8, child)
        self.assertEqual(d.ready_world_groups(), [])
        d.consume(8, blob(1, b'de_test') + number(4, 1) + number(11, 1))
        self.assertEqual(d.ready_world_groups(), [])
        d.consume(9, number(1, 1) + number(3, 0))
        self.assertEqual(d.ready_world_groups(), [1, 2])
        self.assertEqual(d.ready_world_groups(), [])
        d.consume(12, number(1, 2))
        self.assertNotIn(2, d.ready_spawn_groups)
        d.consume(8, blob(1, b'saved') + number(4, 3) + number(9, 1))
        with self.assertRaisesRegex(ValueError, 'savegame-world'):
            d.ready_world_groups()

    def test_serializer_references_packed_and_unpacked(self):
        d = LiveDecoder(lambda _: None)
        for indices in (number(3, 0), blob(3, b'\0')):
            data = blob(1, number(1, 0) + number(2, 0) + indices) + blob(2, b'Test') + blob(2, b'') + blob(3, b'')
            d.consume(41, data)
            self.assertEqual(d.serializers, {('Test', 0)})
        with self.assertRaisesRegex(ValueError, 'serializer-field-boundary'):
            d.consume(41, blob(1, number(1, 0) + number(2, 0) + number(3, 2)) + blob(2, b'Test'))

    def test_exact_bit_join_matches_independent_integer_oracle(self):
        chunks = [encode_message(n, bytes([n & 255]) * length) for n, length in [(7, 1), (40, 257), (4096, 2048), (4, 2)]]
        expected, bits = 0, 0
        for data, count in chunks:
            expected |= (int.from_bytes(data, 'little') & ((1 << count) - 1)) << bits
            bits += count
        combined, count = join_messages(chunks)
        self.assertEqual((combined, count), (expected.to_bytes((bits + 7) // 8, 'little'), bits))
        decoded, padding = messages(combined, count)
        self.assertEqual([m.message_id for m in decoded], [7, 40, 4096, 4])
        self.assertEqual(padding, 0)
        frame = decode_frame(unreliable_frame(combined, 1, 0, (0xfffd,) * 3), gns_reliable=False)
        self.assertEqual((frame.sequence, frame.acknowledgement, frame.body), (1, 0, combined))
        with self.assertRaisesRegex(ValueError, 'message-bit-span'):
            join_messages([(b'\0\0', 1)])
        with self.assertRaisesRegex(ValueError, 'history-count'):
            unreliable_frame(b'', 1, 0, ())


if __name__ == '__main__':
    unittest.main(verbosity=2)
