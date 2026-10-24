from ticket_lease import TicketLease
"""Synthetic protocol/schema and lifecycle tests; no real Steam tickets or GOTV sessions."""
import struct
import unittest
from handshake import connect_inner_message, parse_connection_inner, signon_message_bits, Challenge, SignonSequence, connect_payload, parse_challenge_body, signon_payload
from wire import fields, scalar


class HandshakeTest(unittest.TestCase):
    def test_auth_callback_and_prefix(self):
        cancelled = []
        lease = TicketLease(17, b'unit-only-not-a-ticket', cancelled.append)
        with self.assertRaisesRegex(ValueError, 'ticket-not-ready'):
            lease.auth_steam(42)
        self.assertFalse(lease.callback(99, 1))
        self.assertTrue(lease.callback(17, 1))
        self.assertEqual(lease.auth_steam(42), b'\x2a' + bytes(7) + b'unit-only-not-a-ticket')
        lease.close()
        lease.close()
        self.assertEqual(cancelled, [17])
        self.assertFalse(lease.callback(17, 1))
        with self.assertRaisesRegex(ValueError, 'ticket-not-ready'):
            lease.auth_steam(42)

    def test_failed_ticket_never_releases_bytes(self):
        cancelled = []
        lease = TicketLease(3, b'unit-only', cancelled.append)
        self.assertFalse(lease.callback(3, 2))
        self.assertEqual(cancelled, [3])
        with self.assertRaises(ValueError):
            lease.auth_steam(42)

    def test_challenge_auth3_layout_and_bounds(self):
        data = struct.pack('<IIHQB', 123, 3, 0, 456, 1) + b'unit-context\0'
        value = parse_challenge_body(data)
        self.assertEqual((value.number, value.secure, value.context), (123, True, b'unit-context'))
        self.assertNotIn('unit-context', repr(value))
        for bad in [data[:-1], data + b'\0', data[:8] + b'\x01\0' + data[10:], data[:4] + b'\x04\0\0\0' + data[8:]]:
            with self.assertRaises(ValueError):
                parse_challenge_body(bad)

    def test_connect_protobuf_uses_exact_fields_not_a_fake_udp_frame(self):
        challenge = Challenge(7, 456, True, b'unit-context')
        payload = connect_payload(host_version=1234, challenge=challenge, auth_steam=bytes(8) + b'unit-ticket',
            player_name='probe', encrypted_password=bytes(96), reservation_cookie=0, low_violence=False)
        decoded = fields(payload)
        self.assertEqual([scalar(decoded, n) for n in [1, 2, 3, 5]], [1234, 3, 7, 0])
        self.assertEqual(scalar(decoded, 4, 1), bytes(8))
        self.assertEqual(scalar(fields(scalar(decoded, 7, 2)), 1, 2), b'probe')
        self.assertEqual(scalar(decoded, 6, 2), bytes(96))
        self.assertEqual(scalar(decoded, 9, 2), b'unit-context')
        self.assertFalse(payload.startswith(b'\xff\xff\xff\xff'))

    def test_server_auth2_omits_ticket_and_preserves_negotiated_protocol(self):
        value = parse_challenge_body(struct.pack('<IIHQB', 123, 2, 7, 0, 1) + b'unit-context\0')
        self.assertEqual((value.auth_protocol, value.server_steam_id, value.secure), (2, 0, False))
        kwargs = dict(host_version=1234, challenge=value, player_name='probe',
                      encrypted_password=bytes(96), reservation_cookie=0, low_violence=False)
        decoded = fields(connect_payload(auth_steam=b'', **kwargs))
        self.assertEqual(scalar(decoded, 2), 2)
        self.assertNotIn(8, decoded)
        self.assertEqual(scalar(decoded, 6, 2), bytes(96))
        with self.assertRaisesRegex(ValueError, 'auth-payload-size-or-protocol'):
            connect_payload(auth_steam=b'should-not-send', **kwargs)

    def test_inner_framing_and_bit_alignment(self):
        # Literal wire expectations from the recovered byte/bit layout, not a real capture.
        self.assertEqual(connect_inner_message(bytes.fromhex('08 01')), bytes.fromhex('ff ff ff ff 6b 02 08 01'))
        self.assertEqual(parse_connection_inner(bytes.fromhex('ff ff ff ff 42 00') + b'0' * 10), {'kind': 'connection-inner', 'addon_name_bytes': None})
        for bad in [bytes.fromhex('ff ff ff ff 42 01'), bytes.fromhex('ff ff ff ff 42 00 00')]:
            with self.assertRaises(ValueError):
                parse_connection_inner(bad)
        with self.assertRaisesRegex(ValueError, 'writer-budget'):
            connect_inner_message(bytes(1194))
        self.assertEqual(signon_message_bits(3, 17), (bytes.fromhex('87 01 c2 00 44 04 06 00'), 62))

    def test_signon_wire_and_initialization_barriers(self):
        # Schema literal oracle: enum field 1 = NEW, uint32 field 2 = 17, field 3 = 0.
        self.assertEqual(signon_payload(3, 17), bytes.fromhex('08 03 10 11 18 00'))
        sequence = SignonSequence()
        self.assertEqual(sequence.acknowledgement(),
                         (7, bytes.fromhex('08 02 10 ff ff ff ff 0f 18 00')))
        self.assertIsNone(sequence.spawn_count)
        sequence.server_info(17)
        with self.assertRaisesRegex(ValueError, 'skipped-signon'):
            sequence.receive(signon_payload(4, 17))
        sequence.receive(signon_payload(3, 17))
        with self.assertRaisesRegex(ValueError, 'nonadvancing'):
            sequence.receive(signon_payload(2, 17))
        with self.assertRaisesRegex(ValueError, 'initialization-not-implemented'):
            sequence.acknowledgement()
        with self.assertRaisesRegex(ValueError, 'nonadvancing'):
            sequence.receive(signon_payload(3, 17))
        with self.assertRaisesRegex(ValueError, 'spawn-count-mismatch'):
            sequence.receive(signon_payload(4, 18))
        sequence.receive(signon_payload(4, 17))
        with self.assertRaisesRegex(ValueError, 'initialization-not-implemented'):
            sequence.acknowledgement()  # Cannot bypass unimplemented NEW by jumping to 4.
        sequence.receive(signon_payload(5, 17))
        with self.assertRaises(ValueError):
            sequence.acknowledgement()
        self.assertEqual(sequence.receive(signon_payload(6, 17)), {'received_state': 6})
        with self.assertRaises(ValueError):
            sequence.server_info(18)


if __name__ == '__main__':
    unittest.main(verbosity=2)

