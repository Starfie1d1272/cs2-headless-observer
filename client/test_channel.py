"""Synthetic packets only; no source session, secrets or captured ciphertext."""
import struct
import unittest
from channel import decode_frame, reliable_frame, messages, encode_message, lz4_block, UnreliableOrder, UnreliableFeedback
from handshake import signon_message_bits


class ChannelTest(unittest.TestCase):
    def test_literal_ubitvar_widths_and_six_bit_signon(self):
        # Independently calculated UBitVar width boundary literals (empty protobuf).
        for number, encoded, bits in [(15, '0f00', 14), (16, '500000', 18),
            (255, 'df0300', 18), (256, '200400', 22), (4095, 'ef3f00', 22),
            (4096, '304000000000', 42), (0xffffffff, 'ffffffff0300', 42)]:
            self.assertEqual(encode_message(number, b''), (bytes.fromhex(encoded), bits))
            decoded, tail = messages(bytes.fromhex(encoded), bits)
            self.assertEqual([(m.message_id, m.body) for m in decoded], [(number, b'')])
            self.assertEqual(tail, 0)
        data, bits = signon_message_bits(3, 17)
        self.assertEqual(encode_message(7, bytes.fromhex('080310111800')), (data, bits))

    def test_unaligned_multiple_messages_and_trailing_padding(self):
        first, n = encode_message(7, b'\x08\x03')
        second, m = encode_message(40, b'\x08\x01')
        joined = (int.from_bytes(first, 'little') | (int.from_bytes(second, 'little') << n))
        data = joined.to_bytes((n + m + 7) // 8, 'little')
        parsed, padding = messages(data)
        self.assertEqual([(x.message_id, x.body) for x in parsed], [(7, b'\x08\x03'), (40, b'\x08\x01')])
        self.assertEqual(padding, len(data) * 8 - n - m)
        with self.assertRaises(ValueError):
            messages(data, n + m - 1)
        with self.assertRaises(ValueError):
            messages(b'\x07')

    def test_frame_headers_reliability_and_order(self):
        payload, _ = signon_message_bits(3, 17)
        frame = decode_frame(reliable_frame(payload, 6400), gns_reliable=True)
        self.assertEqual((frame.reliable_tick_hint, frame.body), (6400, payload))
        self.assertNotIn(payload.hex(), repr(frame))
        with self.assertRaisesRegex(ValueError, 'reliability-mismatch'):
            decode_frame(reliable_frame(payload, 6400), gns_reliable=False)
        order = UnreliableOrder()
        def incoming(sequence):
            return decode_frame(bytes([2, sequence, 4]) + struct.pack('<3H', 1, 0xfffd, 0xffff), gns_reliable=False)
        self.assertEqual(order.accept(incoming(10)), {'accepted': True, 'gap': 0})
        self.assertEqual(order.accept(incoming(12)), {'accepted': True, 'gap': 1})
        self.assertFalse(order.accept(incoming(11))['accepted'])
        self.assertFalse(order.accept(incoming(12))['accepted'])
        self.assertEqual(incoming(12).history_raw, (1, 0xfffd, 0xffff))
        with self.assertRaisesRegex(ValueError, 'bit-underflow'):
            decode_frame(b'\x02\x01\x01', gns_reliable=False)

    def test_unreliable_feedback_literal_sequence_ack_and_loss_history(self):
        feedback = UnreliableFeedback()
        self.assertEqual(feedback.frame(), bytes.fromhex('02 01 00 fd ff fd ff fd ff'))
        incoming = lambda n: decode_frame(bytes([2, n, 0]) + bytes.fromhex('fd ff fd ff fd ff'), gns_reliable=False)
        feedback.observe(incoming(3))
        self.assertEqual(feedback.frame(), bytes.fromhex('02 02 03 fd ff ff ff ff ff'))
        feedback.observe(incoming(2))  # Late arrival: do not rewind the acknowledged sequence.
        self.assertEqual(feedback.frame(), bytes.fromhex('02 03 03 fd ff fe ff ff ff'))
        feedback.observe(incoming(3))  # Duplicate changes neither receipt state nor latency.
        feedback.observe(decode_frame(reliable_frame(b'', 100), gns_reliable=True))
        self.assertEqual(feedback.frame(b'x'), bytes.fromhex('02 04 03 fd ff fe ff ff ff 78'))
        feedback.observe(incoming(6))
        self.assertEqual(feedback.frame(), bytes.fromhex('02 05 06 fd ff ff ff ff ff'))
        self.assertEqual(len(feedback.history), 3)
        feedback.sequence = 0x80000000
        with self.assertRaisesRegex(ValueError, 'outgoing-sequence-restart-required'):
            feedback.frame()

    def test_compression_is_lz4_block_after_channel_header(self):
        # One literal-only raw LZ4 block, deliberately not a Demo Snappy wrapper.
        block = b'\x50hello'
        self.assertEqual(lz4_block(block, 5), b'hello')
        self.assertEqual(decode_frame(b'\x03\x11\x05' + block, gns_reliable=True).body, b'hello')
        header = b'\x04\x01\x01' + bytes(6)
        self.assertEqual(decode_frame(header + b'\x05' + block, gns_reliable=False).body, b'hello')
        for bad, size in [(b'', 0), (b'\xf0', 15), (b'\x50hi', 5),
                          (b'\x10a\0\0', 5), (b'\x10a\x02\0', 5),
                          (b'\x10a\x01\0', 5), (block, 4), (block, 6)]:
            with self.assertRaises(ValueError):
                lz4_block(bad, size)
        self.assertEqual(lz4_block(b'\0', 0), b'')
        with self.assertRaisesRegex(ValueError, 'empty-compressed'):
            decode_frame(b'\x03\x11\0\0', gns_reliable=True)
        with self.assertRaisesRegex(ValueError, 'varuint32-overflow'):
            decode_frame(b'\xff\xff\xff\xff\xff', gns_reliable=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)

