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
            with subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[2] / 'client/driver.py'),
                '--managed', '--native', str(root / 'absent-native-library'),
                '--parser-worker', os.environ['GOTV_ORDERED_WORKER'], '--host-version', '14191',
                '--source-id', '0123456789abcdef0123456789abcdef', '--output', str(output), '--seconds', '1'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
                process.stdin.write(json.dumps(connection)+'\n')
                process.stdin.flush()  # Keep the owner alive until the intentionally absent library fails.
                self.assertEqual(process.wait(timeout=10), 1)
                stdout, stderr = process.stdout.read(), process.stderr.read()
            self.assertEqual(stdout, '')
            self.assertNotIn(connection['password'], stderr)
            self.assertNotIn(connection['endpoint'], stderr)
            self.assertEqual(sorted(p.name for p in output.iterdir()), ['report.json'])
            report = json.loads((output / 'report.json').read_text())
            self.assertEqual(report['outcome'], 'failed')
            self.assertEqual(report['online_success'], 'INCONCLUSIVE')
            self.assertEqual(report['finalization_failures'], [])

    def test_owner_eof_is_a_stop_signal_without_blocking_reader(self):
        import os
        from driver import ManagedOwner
        read_fd, write_fd = os.pipe()
        owner = ManagedOwner(read_fd)
        try:
            self.assertFalse(owner.is_set())
            os.close(write_fd)
            self.assertTrue(owner.is_set())
            self.assertTrue(owner.is_set())
        finally:
            os.close(read_fd)

    @unittest.skipUnless(__import__('os').environ.get('GOTV_ORDERED_WORKER'), 'Set GOTV_ORDERED_WORKER')
    def test_owner_stop_runs_driver_and_parser_finalization(self):
        # Real CLI/worker and pipe, but the SDK port is the existing in-memory fixture.
        import os
        from pathlib import Path
        import sys
        import tempfile
        from unittest.mock import patch
        import driver
        import sdk
        from support.sdk_port import Port
        read_fd, write_fd = os.pipe()
        writer_open = True
        port = Port()
        def fake_native(*args, **kwargs):
            nonlocal writer_open
            os.close(write_fd)
            writer_open = False
            return port
        try:
            os.write(write_fd, b'{"endpoint":"127.0.0.1:27020","password":"synthetic-only"}\n')
            with os.fdopen(read_fd, 'r') as input_stream, tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / 'run'
                argv = ['driver.py', '--managed', '--native', str(Path(temp) / 'not-loaded'),
                        '--parser-worker', os.environ['GOTV_ORDERED_WORKER'], '--host-version', '14191',
                        '--output', str(output), '--seconds', '5']
                with patch.object(sys, 'argv', argv), patch.object(sys, 'stdin', input_stream), \
                     patch.object(sys, 'stdout', io.StringIO()), patch.object(sys, 'stderr', io.StringIO()), \
                     patch.object(sdk, 'NativePort', fake_native):
                    result = driver.main()
                report = json.loads((output / 'report.json').read_text())
                self.assertEqual(result, 2)
                self.assertEqual(report['reason'], 'owner-stopped')
                self.assertEqual(port.closed, 1)
                self.assertFalse(port.ticket_requested)
                self.assertEqual(report['finalization_failures'], [])
                self.assertEqual(report['online_success'], 'INCONCLUSIVE')
        finally:
            if writer_open:
                os.close(write_fd)
