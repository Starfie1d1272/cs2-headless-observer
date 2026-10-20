import io
import json
import unittest
from driver import read_managed_connection, connection_values

class ManagedConnectionTests(unittest.TestCase):
    def test_private_stdin_values(self):
        endpoint, password = read_managed_connection(io.BytesIO(b'{"endpoint":"127.0.0.1:27020","password":"fixture-only"}\n'))
        self.assertEqual(endpoint, '127.0.0.1:27020')
        self.assertEqual(password, bytearray(b'fixture-only'))
        password[:] = bytes(len(password))
    def test_empty_password_is_explicitly_supported(self):
        self.assertEqual(connection_values('[::1]:27020', '')[1], bytearray())
    def test_invalid_configuration_never_echoes_input(self):
        for raw in (b'{broken secret}', b' ' * 4097,
                    json.dumps({'endpoint':'not-a-host:27020','password':'secret'}).encode(),
                    json.dumps({'endpoint':'127.0.0.1:0','password':'secret'}).encode(),
                    json.dumps({'endpoint':'127.0.0.1:27020','password':'secret','token':'private'}).encode(),
                    json.dumps({'endpoint':'127.0.0.1:27020','password':'\u4e2d\u6587'}).encode(),
                    json.dumps({'endpoint':'127.0.0.1:27020','password':'a'*96}).encode()):
            with self.subTest(length=len(raw)):
                with self.assertRaisesRegex(ValueError, '^configuration-boundary$'):
                    read_managed_connection(io.BytesIO(raw))

    @unittest.skipUnless(__import__('os').environ.get('GOTV_ORDERED_WORKER'), 'Set GOTV_ORDERED_WORKER')
    def test_managed_start_failure_keeps_stdout_clean_and_does_not_capture(self):
        # Deliberately absent native library fails strict path resolution before any SDK load/socket.
        import os
        from pathlib import Path
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'run'
            connection = {'endpoint': '127.0.0.1:27020', 'password': 'synthetic-private-value'}
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('driver.py')),
                '--managed', '--native', str(root / 'absent-native-library'),
                '--parser-worker', os.environ['GOTV_ORDERED_WORKER'], '--host-version', '14191',
                '--source-id', '0123456789abcdef0123456789abcdef', '--output', str(output), '--seconds', '1'],
                input=json.dumps(connection)+'\n', text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '')
            self.assertNotIn(connection['password'], result.stderr)
            self.assertNotIn(connection['endpoint'], result.stderr)
            self.assertEqual(sorted(p.name for p in output.iterdir()), ['report.json'])
            report = json.loads((output / 'report.json').read_text())
            self.assertEqual(report['outcome'], 'failed')
            self.assertEqual(report['online_success'], 'INCONCLUSIVE')
            self.assertEqual(report['finalization_failures'], [])
