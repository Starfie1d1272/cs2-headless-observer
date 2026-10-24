"""Local synthetic log projection checks; no private capture is used."""
import json
from pathlib import Path
import tempfile
import unittest
from capture import safe_console_lines


class CaptureTest(unittest.TestCase):
    def test_challenges_addresses_credentials_and_raw_lines_are_omitted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'console.log'
            path.write_text(
                'Received S2C_CHALLENGE [987654321 auth 3] private-suffix\n'
                'Sending C2S_CONNECT [2000933 protocol 987654321 auth 3]\n'
                'CSteam3Client::GetAuthSessionTicket to SteamID private-identity\n'
                'password private-password; ticket private-ticket; 192.0.2.1:27020\n'
                'SignonState CONNECTED -> NEW\n')
            projected = safe_console_lines(path)
            self.assertEqual(projected[1], {'line': 2, 'kind': 'connect',
                'host_version': '2000933', 'auth_protocol': '3'})
            encoded = json.dumps(projected)
            for forbidden in ['987654321', 'private-', '192.0.2.1', 'password', 'raw']:
                self.assertNotIn(forbidden, encoded)
            self.assertEqual(len(projected), 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
