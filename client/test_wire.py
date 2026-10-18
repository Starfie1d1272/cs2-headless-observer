"""Synthetic wire boundary tests. These fixtures are NOT captured CS2 traffic."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from wire import fields, gns_metadata, inspect_pcap, payload_metadata


class WireTest(unittest.TestCase):
    def test_auth_payload_is_never_exported(self):
        secret = b'PRIVATE_PASSWORD_AND_TICKET'
        data = b'\x08\xef\x6e\x10\x03\x18\x01' + b'\x32' + bytes([len(secret)]) + secret
        data += b'\x42' + bytes([len(secret)]) + secret
        row = payload_metadata('c2s-connect', data)
        self.assertEqual(row['host_version'], 14191)
        self.assertEqual(row['auth_steam_bytes'], len(secret))
        self.assertNotIn(secret.decode(), json.dumps(row))

    def test_signon_two_is_only_connected(self):
        self.assertEqual(payload_metadata('signon', b'\x08\x02')['state'], 'CONNECTED')
        self.assertEqual(payload_metadata('signon', b'\x08\x06')['state'], 'FULL')
        with self.assertRaises(ValueError):
            payload_metadata('signon', b'\x08\x02\x08\x06')

    def test_malformed_protobuf(self):
        for data in [b'\x00', b'\x0a\xff', b'\x0f', b'\x08' + b'\xff' * 10,
                     b'\x0a\x03a', b'\x08' * 65536]:
            with self.subTest(data=data[:10]), self.assertRaises(ValueError):
                fields(data)

    def test_closed_2033_and_padding(self):
        body = b'\x18\xf1\x0f\x12\x06secret'
        padded = b'\x24' + struct.pack('<H', len(body)) + body
        row = gns_metadata(padded.ljust(512, b'\0'))
        self.assertEqual(row, {'kind': 'connection_closed', 'reason_code': 2033})
        self.assertNotIn('secret', json.dumps(row))
        with self.assertRaises(ValueError):
            gns_metadata(padded)

    def test_transport_success_is_not_viewer_success(self):
        # A syntactically shaped ConnectOK and two data packets; no auth or game semantics.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.pcap'
            packets = [b'\x23\x0d\x01\0\0\0', b'\x80abcdef', b'\x80ghijkl']
            raw = struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
            for index, payload in enumerate(packets):
                ip = bytearray(20)
                ip[0], ip[9] = 0x45, 17
                ip[2:4] = struct.pack('!H', 28 + len(payload))
                ip[12:16], ip[16:20] = bytes([192, 0, 2, 1]), bytes([192, 0, 2, 2])
                frame = bytes(12) + b'\x08\x00' + ip
                frame += struct.pack('!HHHH', 27020, 50000, 8 + len(payload), 0) + payload
                raw += struct.pack('<IIII', 100 + index, 0, len(frame), len(frame)) + frame
            path.write_bytes(raw)
            rows = []
            summary = inspect_pcap(path, ('192.0.2.1', 27020), rows.append)
            self.assertEqual(summary['matched_packets'], 3)
            self.assertEqual(summary['flows'][0]['data_candidates'], 2)
            self.assertEqual(summary['ordinary_viewer_signon'], 'INCONCLUSIVE')
            self.assertEqual(summary['continuous_game_data'], 'INCONCLUSIVE')
            self.assertNotIn('192.0.2', json.dumps(rows))
            path.write_bytes(raw[:-1])
            with self.assertRaises(ValueError):
                inspect_pcap(path, ('192.0.2.1', 27020), rows.append)


if __name__ == '__main__':
    unittest.main(verbosity=2)
