"""Integrated synthetic SDK port. Never generates usable tickets or sends packets."""
import io
import struct
import unittest
from channel import encode_message, join_messages, reliable_frame, decode_frame, messages, unreliable_frame
from driver import ObserverDriver, DriverError, SampleWriter
from handshake import blob, number, initial_challenge_request
from replay import replay
from wire import fields, scalar, varint


class Port:
    def __init__(self):
        self.state, self.incoming, self.sent, self.closed = 3, [], [], 0
        self.ticket_requested = False
    def remote_id(self): return 456
    def local_id(self): return 76561198000000123
    def accept_server_auth2(self):
        assert self.state == 3
        self.state = 7
    def pump(self, now): pass
    def receive(self): return self.incoming.pop(0) if self.incoming else None
    def send(self, data, flags): self.sent.append((data, flags))
    def request_ticket(self): self.ticket_requested = True; self.state = 4
    def with_auth(self, consume): return consume(struct.pack('<Q', 76561198000000123) + b'SYNTHETIC-NOT-A-TICKET')
    def close(self): self.closed += 1; self.state = 6


class DriverTest(unittest.TestCase):
    def test_promoted_delivery_keeps_application_sequence_filter(self):
        driver = ObserverDriver(Port(), host_version=14191, password=bytearray(), emit=lambda _: None)
        driver.phase = 'channel'
        for tick in (100, 200):
            encoded, _ = encode_message(4, number(1, tick))
            driver.receive(unreliable_frame(encoded, 1, 0, (0, 0, 0)), True, tick)
        self.assertEqual(driver.decoder.tick, 100)
        driver.close()

    def ready(self):
        port, output, sample, password = Port(), [], io.BytesIO(), bytearray(b'unit-only')
        driver = ObserverDriver(port, host_version=14191, password=password, emit=output.append,
                                capture=SampleWriter(sample), now_ms=10)
        driver.step(11)
        self.assertEqual(port.sent, [(bytes.fromhex('ffffffff71') + b'connect0x00000000\0', 5)])
        self.assertEqual(port.sent[0][0], initial_challenge_request())
        port.incoming.append((b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', 0, 3, 0, 456, 1) + b'connect0x00000000\0', False))
        driver.step(12)
        self.assertTrue(port.ticket_requested)
        self.assertEqual(driver.report()['challenge_metadata']['auth_protocol'], 3)
        self.assertTrue(driver.report()['challenge_metadata']['server_identity_matches'])
        self.assertEqual(len(port.sent), 1)  # No auth/connect before SDK callback gate.
        port.state = 5
        driver.step(13)
        self.assertEqual(port.sent[-1][1], 5)
        data = port.sent[-1][0]
        size, pos = varint(data, 5)
        self.assertEqual(len(data) - pos, size)
        f = fields(data[pos:])
        self.assertEqual(len(scalar(f, 6, 2)), 96)
        self.assertEqual(scalar(f, 8, 2), struct.pack('<Q', 76561198000000123) + b'SYNTHETIC-NOT-A-TICKET')
        self.assertEqual(password, b'unit-only')  # Retained only until connection acceptance.
        self.assertEqual(sample.getvalue(), b'MZRCS2\x01\0')  # No handshake/credentials captured.
        port.incoming.append((b'\xff\xff\xff\xffB\0' + b'0' * 10, False))
        driver.step(14)
        self.assertEqual(driver.phase, 'channel')
        self.assertEqual(password, bytes(len(password)))
        self.assertIsNone(driver.decoder.server)
        self.assertEqual(len(port.sent), 3)
        self.assertEqual(port.sent[-1][1], 8)
        ack = decode_frame(port.sent[-1][0], gns_reliable=True)
        self.assertEqual(ack.reliable_tick_hint, 0)
        decoded, _ = messages(ack.body)
        self.assertEqual([(m.message_id, m.body) for m in decoded],
                         [(6, driver.settings.userinfo()),
                          (7, bytes.fromhex('08 02 10 ff ff ff ff 0f 18 00'))])
        return driver, port, output, sample

    def test_challenge_retries_at_official_default_without_extending_deadline(self):
        port = Port()
        driver = ObserverDriver(port, host_version=14191, password=bytearray(), emit=lambda _: None)
        driver.step(1)
        driver.step(500)
        self.assertEqual(len(port.sent), 1)
        driver.step(501)
        self.assertEqual(port.sent, [(initial_challenge_request(), 5)] * 2)
        self.assertEqual(driver.deadline, 15001)
        with self.assertRaisesRegex(DriverError, 'phase-timeout'):
            driver.step(15001)
        driver.close()

    def test_auth2_rechallenge_uses_new_number_and_keeps_password_until_connected(self):
        port, password = Port(), bytearray(b'unit-only')
        driver = ObserverDriver(port, host_version=14191, password=password, emit=lambda _: None)
        challenge = lambda n, context: (b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', n, 2, 0, 456, 0) + context + b'\0', False)
        driver.step(1)
        port.incoming.append(challenge(7, b'connect0x00000000'))
        driver.step(2)
        first = port.sent[-1][0]
        deadline = driver.deadline
        driver.step(501)
        self.assertEqual(port.sent[-1], (b'\xff\xff\xff\xffqconnect0x00000007\0', 5))
        port.incoming.append(challenge(9, b'connect0x00000007'))
        driver.step(502)
        second = port.sent[-1][0]
        self.assertNotEqual(first, second)
        from password import transform_password
        size, pos = varint(second, 5)
        self.assertEqual(scalar(fields(second[pos:pos + size]), 6, 2), transform_password(b'unit-only', 9))
        self.assertEqual(driver.deadline, deadline)
        port.incoming.append((b'\xff\xff\xff\xffB\0' + b'0' * 10, False))
        driver.step(503)
        self.assertEqual(password, bytes(len(password)))
        sent = len(port.sent)
        port.incoming.append(challenge(9, b'connect0x00000007'))
        driver.step(1001)
        self.assertTrue(all(flags == 1 for _, flags in port.sent[sent:]))
        driver.close()

    def test_channel_feedback_runs_during_initialization_and_repeats_processed_tick(self):
        driver, port, _, _ = self.ready()
        driver.step(110)
        self.assertEqual(port.sent[-1], (bytes.fromhex('02 01 00 fd ff fd ff fd ff'), 1))
        port.incoming.append((bytes.fromhex('02 03 00 fd ff fd ff fd ff'), False))
        driver.step(210)
        self.assertEqual(port.sent[-1], (bytes.fromhex('02 02 03 fd ff ff ff ff ff'), 1))
        port.incoming.append((bytes.fromhex('02 02 00 fd ff fd ff fd ff'), False))
        driver._full_sent = True
        driver._processed_entity_tick = 1380
        driver.step(310)
        feedback = decode_frame(port.sent[-1][0], gns_reliable=False)
        self.assertEqual((feedback.sequence, feedback.acknowledgement), (3, 3))
        self.assertEqual(feedback.history_raw, (0xfffd, 0xfffe, 0xffff))
        tick_messages, _ = messages(feedback.body)
        self.assertEqual([(m.message_id, scalar(fields(m.body), 1)) for m in tick_messages], [(4, 1380)])
        driver.step(410)
        repeat = decode_frame(port.sent[-1][0], gns_reliable=False)
        self.assertEqual(repeat.body, feedback.body)
        self.assertEqual(repeat.sequence, 4)
        driver._recovery_pending = True
        driver.step(510)
        self.assertEqual(decode_frame(port.sent[-1][0], gns_reliable=False).body, b'')
        driver.close()

    def test_missing_challenge_identity_uses_trusted_peer_without_skipping_ticket(self):
        port = Port()
        driver = ObserverDriver(port, host_version=14191, password=bytearray(), emit=lambda _: None)
        driver.step(1)
        packet = b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', 7, 3, 0, 0, 1) + b'connect0x00000000\0'
        port.incoming.append((packet, False))
        driver.step(2)
        self.assertTrue(port.ticket_requested)
        self.assertEqual(driver.phase, 'ticket')
        self.assertEqual(len(port.sent), 1)
        driver.close()

    def test_conflicting_challenge_identity_still_rejected(self):
        port = Port()
        driver = ObserverDriver(port, host_version=14191, password=bytearray(), emit=lambda _: None)
        driver.step(1)
        packet = b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', 7, 3, 0, 999, 1) + b'connect0x00000000\0'
        port.incoming.append((packet, False))
        with self.assertRaisesRegex(DriverError, 'challenge-peer-mismatch'):
            driver.step(2)
        self.assertFalse(port.ticket_requested)
        driver.close()

    def test_auth3_duplicate_challenge_waits_for_same_ticket_and_rejects_downgrade(self):
        port = Port()
        driver = ObserverDriver(port, host_version=14191, password=bytearray(b'unit-only'), emit=lambda _: None)
        packet = lambda n, auth: (b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', n, auth, 0, 456, auth == 3) + b'connect0x00000000\0', False)
        driver.step(1)
        port.incoming.append(packet(7, 3))
        driver.step(2)
        deadline = driver.deadline
        port.incoming.append(packet(9, 3))
        driver.step(3)
        self.assertEqual((driver.phase, port.state), ('ticket', 4))
        self.assertEqual(driver.deadline, deadline)
        self.assertEqual(len(port.sent), 1)
        port.state = 5
        driver.step(4)
        self.assertEqual(driver.phase, 'connection')
        port.incoming.append(packet(9, 2))
        with self.assertRaisesRegex(DriverError, 'challenge-auth-changed'):
            driver.step(5)
        driver.close()

    def test_driver_requests_full_schema_at_new_and_capture_replays(self):
        driver, port, output, sample = self.ready()
        info = number(1, 14191) + number(2, 7) + b'\x6d' + struct.pack('<f', 1 / 64) + blob(15, b'de_test')
        descriptor = blob(1, number(1, 17) + blob(2, b'weapon_fire') + blob(3, number(1, 1) + blob(2, b'weapon')))
        event = number(2, 17) + blob(3, number(1, 1) + blob(2, b'weapon_awp')) + number(4, 100)
        body, _ = join_messages([encode_message(n, b) for n, b in [(40, info), (205, descriptor), (207, event), (7, number(1, 3) + number(2, 7))]])
        port.incoming.append((reliable_frame(body, 0), True))
        driver.step(20)
        self.assertEqual((driver.phase, driver.reason), ('channel', None))
        self.assertEqual(len(port.sent), 5)  # q, connect, CONNECTED, ClientInfo, NEW.
        info_messages, _ = messages(decode_frame(port.sent[-2][0], gns_reliable=bool(port.sent[-2][1] & 8)).body)
        self.assertEqual(info_messages[0].message_id, 20)
        info_fields = fields(info_messages[0].body)
        self.assertEqual(scalar(info_fields, 1, 5), bytes(4))
        self.assertEqual(scalar(info_fields, 2), 7)
        self.assertEqual(scalar(info_fields, 3), 0)
        self.assertEqual(scalar(info_fields, 5), 76561198000000123 & 0xffffffff)
        ack_messages, _ = messages(decode_frame(port.sent[-1][0], gns_reliable=bool(port.sent[-1][1] & 8)).body)
        self.assertEqual((ack_messages[0].message_id, ack_messages[0].body),
                         (7, bytes.fromhex('08 03 10 07 18 00')))
        self.assertEqual(output[0]['weapon'], 'weapon_awp')
        self.assertEqual(driver.report()['online_success'], 'INCONCLUSIVE')
        self.assertNotIn('SYNTHETIC', str(driver.report()))
        sample.seek(0)
        replayed = []
        report = replay(sample, replayed.append)
        self.assertEqual(output, replayed)
        self.assertEqual(report['frames'], 1)
        # Further traffic must not repeat NEW. PRESPAWN stays explicit until
        # schema/entity initialization is wired to the existing parser.
        body, _ = join_messages([encode_message(7, number(1, 4) + number(2, 7))])
        port.incoming.append((reliable_frame(body, 0), True))
        driver.step(21)
        self.assertEqual((driver.phase, driver.reason), ('blocked', 'prespawn-initialization-required'))
        self.assertEqual(len(port.sent), 5)
        driver.close()
        self.assertEqual(port.closed, 1)

    def test_full_requires_a_processed_full_snapshot_and_does_not_wait_for_remote_full(self):
        driver, port, _, _ = self.ready()
        class Parser:
            checkpoint = {'sequence': 1, 'schemaFields': 1, 'serverInfo': True, 'stringTables': 0}
            controls = []
            def pop_receipts(self):
                controls, self.controls = self.controls, []
                return controls
        driver.parser = Parser()
        driver._parser_sequence = 1
        driver.signon.server_info(7)
        for state in (3, 4, 5):
            driver.signon.receive(number(1, state) + number(2, 7))
        driver.signon.finish_spawn()
        driver._new_sent = driver._prespawn_sent = driver._spawn_sent = True
        driver._advance_initialization(100)
        self.assertFalse(driver._full_sent)
        driver._parser_sequence = 2  # Later traffic cannot stall a completed full snapshot.
        driver.parser.controls = [{'type': 'receipt', 'sequence': 1, 'tick': 100, 'baselineAck': None, 'full': True}]
        driver._send_processed_tick(200)
        self.assertTrue(driver._full_sent)
        self.assertEqual(driver.signon.state, 6)
        sent = [m for data, reliable in port.sent[3:] for m in messages(decode_frame(data, gns_reliable=bool(reliable & 8)).body)[0]]
        self.assertEqual(sent[0].message_id, 7)
        self.assertEqual(scalar(fields(sent[0].body), 1), 6)
        self.assertEqual(driver.report()['received_signon_state'], 5)
        self.assertEqual(driver.report()['effective_signon_state'], 6)
        before = len(port.sent)
        driver.signon.receive(number(1, 6) + number(2, 7))
        driver._advance_initialization(300)
        self.assertEqual(len(port.sent), before)

    def test_remote_full_and_delta_receipt_do_not_replace_first_full_snapshot(self):
        driver, port, _, _ = self.ready()
        class Parser:
            checkpoint = {'sequence': 1, 'schemaFields': 1, 'serverInfo': True, 'stringTables': 0}
            controls = []
            def pop_receipts(self):
                controls, self.controls = self.controls, []
                return controls
        driver.parser = Parser()
        driver._parser_sequence = 1
        driver.signon.server_info(7)
        for state in (3, 4, 5):
            driver.signon.receive(number(1, state) + number(2, 7))
        driver.signon.finish_spawn()
        driver._new_sent = driver._prespawn_sent = driver._spawn_sent = True
        driver.signon.receive(number(1, 6) + number(2, 7))
        driver._advance_initialization(100)
        self.assertFalse(driver._full_sent)
        driver.parser.controls = [{'type': 'receipt', 'sequence': 1, 'tick': 100, 'baselineAck': None, 'full': False}]
        driver._send_processed_tick(200)
        self.assertFalse(driver._full_sent)
        self.assertEqual(len(port.sent), 3)
        driver.parser.controls = [{'type': 'receipt', 'sequence': 1, 'tick': 101, 'baselineAck': 0, 'full': True}]
        driver._send_processed_tick(300)
        self.assertTrue(driver._full_sent)
        self.assertEqual(driver.report()['received_signon_state'], 6)
        self.assertEqual(driver.report()['baseline_ack_count'], 1)

    def test_tick_receipt_waits_for_processed_entities_and_is_rate_bounded(self):
        driver, port, _, _ = self.ready()
        class Parser:
            checkpoint = {'sequence': 0}
            controls = []
            def pop_receipts(self):
                ready = [r for r in self.controls if r['sequence'] <= self.checkpoint['sequence']]
                self.controls = [r for r in self.controls if r not in ready]
                return ready
        driver.parser = Parser()
        driver._full_sent = True
        driver.parser.controls = [{'type': 'receipt', 'sequence': 1, 'tick': 100, 'baselineAck': None}]
        driver.decoder.tick = 200  # A raw receive tick is not a parsed snapshot.
        driver._send_processed_tick(200)
        self.assertEqual(len(port.sent), 3)
        driver.parser.checkpoint = {'sequence': 1}
        driver._send_processed_tick(200)
        decoded, _ = messages(decode_frame(port.sent[-1][0], gns_reliable=bool(port.sent[-1][1] & 8)).body)
        self.assertEqual((decoded[0].message_id, scalar(fields(decoded[0].body), 1)), (4, 100))
        driver.parser.controls = [{'type': 'receipt', 'sequence': 2, 'tick': 101, 'baselineAck': None}]
        driver.parser.checkpoint = {'sequence': 2}
        driver._send_processed_tick(250)
        self.assertEqual(len(port.sent), 4)
        driver._send_processed_tick(300)
        self.assertEqual(driver.report()['last_acknowledged_entity_tick'], 101)
        driver.parser.controls = [{'type': 'recovery', 'sequence': 3, 'tick': 103, 'deltaFrom': 102}]
        driver.parser.checkpoint = {'sequence': 3}
        driver._send_processed_tick(400)
        decoded, _ = messages(decode_frame(port.sent[-1][0], gns_reliable=bool(port.sent[-1][1] & 8)).body)
        self.assertEqual(scalar(fields(decoded[0].body), 1), 0xffffffff)
        size = len(port.sent)
        driver._send_processed_tick(500)
        self.assertEqual(len(port.sent), size)
        driver.parser.controls = [{'type': 'receipt', 'sequence': 4, 'tick': 110, 'baselineAck': 1}]
        driver.parser.checkpoint = {'sequence': 4}
        driver._send_processed_tick(600)
        decoded, _ = messages(decode_frame(port.sent[-2][0], gns_reliable=bool(port.sent[-2][1] & 8)).body)
        self.assertEqual((decoded[0].message_id, scalar(fields(decoded[0].body), 1), scalar(fields(decoded[0].body), 2)), (23, 110, 1))
        self.assertEqual(driver.report()['full_update_requests'], 1)
        self.assertEqual(driver.report()['last_acknowledged_entity_tick'], 110)
        size = len(port.sent)
        driver.parser.controls = [{'type': 'recovery', 'sequence': 5, 'tick': 111, 'deltaFrom': None, 'request': False}]
        driver.parser.checkpoint = {'sequence': 5}
        driver._send_processed_tick(700)
        self.assertEqual(len(port.sent), size)
        driver.parser.controls = [{'type': 'receipt', 'sequence': 6, 'tick': 112, 'baselineAck': None}]
        driver.parser.checkpoint = {'sequence': 6}
        driver._send_processed_tick(800)
        self.assertEqual(driver.report()['last_acknowledged_entity_tick'], 112)
        self.assertEqual(driver.report()['full_update_requests'], 1)
        # Two distinct gaps can be repaired/observed inside the 100 ms tick-ACK
        # window. The old -1 acknowledgement must not suppress the new request.
        for sequence, receipt, now in [
            (7, {'type': 'recovery', 'tick': 114, 'deltaFrom': 113}, 810),
            (8, {'type': 'receipt', 'tick': 120, 'baselineAck': None}, 820),
            (9, {'type': 'recovery', 'tick': 122, 'deltaFrom': 121}, 830),
        ]:
            driver.parser.controls = [{**receipt, 'sequence': sequence}]
            driver.parser.checkpoint = {'sequence': sequence}
            driver._send_processed_tick(now)
        self.assertEqual(driver.report()['full_update_requests'], 3)
        decoded, _ = messages(decode_frame(port.sent[-1][0], gns_reliable=bool(port.sent[-1][1] & 8)).body)
        self.assertEqual(scalar(fields(decoded[0].body), 1), 0xffffffff)
        size = len(port.sent)
        driver._send_processed_tick(840)
        self.assertEqual(len(port.sent), size)
        driver.close()

    def test_server_auth2_connects_without_ticket_using_authenticated_transport(self):
        for peer in (0, 456):
            port = Port()
            password = bytearray(b'unit-only')
            driver = ObserverDriver(port, host_version=14191, password=password, emit=lambda _: None)
            driver.step(1)
            port.incoming.append((b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', 7, 2, 7, peer, 0) + b'connect0x00000000\0', False))
            driver.step(2)
            self.assertFalse(port.ticket_requested)
            self.assertEqual((driver.phase, port.state), ('connection', 7))
            self.assertEqual(password, b'unit-only')
            data = port.sent[-1][0]
            size, pos = varint(data, 5)
            self.assertEqual(len(data) - pos, size)
            decoded = fields(data[pos:])
            self.assertEqual(scalar(decoded, 2), 2)
            self.assertNotIn(8, decoded)
            self.assertEqual(driver._account_id, port.local_id() & 0xffffffff)
            port.incoming.append((b'\xff\xff\xff\xffB\0' + b'0' * 10, False))
            driver.step(3)
            self.assertEqual(driver.phase, 'channel')
            driver.close()
        port = Port()
        driver = ObserverDriver(port, host_version=14191, password=bytearray(), emit=lambda _: None)
        driver.step(1)
        port.incoming.append((b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', 7, 2, 0, 999, 0) + b'connect0x00000000\0', False))
        with self.assertRaisesRegex(DriverError, 'challenge-peer-mismatch'): driver.step(2)
        self.assertEqual(port.state, 3)
        driver.close()

    def test_wrong_peer_context_and_timeouts_do_not_request_ticket(self):
        for server, context, expected in [(999, b'connect0x00000000', 'peer-mismatch'), (456, b'wrong', 'context-mismatch')]:
            port = Port()
            driver = ObserverDriver(port, host_version=14191, password=bytearray(), emit=lambda _: None)
            driver.step(1)
            port.incoming.append((b'\xff\xff\xff\xffA' + struct.pack('<IIHQB', 0, 3, 0, server, 1) + context + b'\0', False))
            with self.assertRaisesRegex(DriverError, expected): driver.step(2)
            self.assertFalse(port.ticket_requested)
            driver.close()
        port = Port()
        driver = ObserverDriver(port, host_version=14191, password=bytearray(), emit=lambda _: None)
        driver.step(1)
        with self.assertRaisesRegex(DriverError, 'phase-timeout'): driver.step(15001)
        driver.close()
        self.assertEqual(len(port.sent), 1)

    def test_no_auth_sample_and_truncated_sample_rejected(self):
        writer = SampleWriter(io.BytesIO())
        with self.assertRaises(ValueError): writer(b'\xff\xff\xff\xffkSECRET', False, 0)
        with self.assertRaisesRegex(ValueError, 'truncated-header'):
            replay(io.BytesIO(b'MZRCS2\x01\0x'), lambda _: None)
        driver, _, _, _ = self.ready()
        with self.assertRaisesRegex(DriverError, 'monotonic-clock-regressed'): driver.step(1)
        driver.close()


if __name__ == '__main__': unittest.main(verbosity=2)

