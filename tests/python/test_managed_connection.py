import io
import json
import unittest
from driver import read_managed_connection, connection_values

class ManagedConnectionTests(unittest.TestCase):
    def test_buffered_extra_input_is_observed_by_same_reader(self):
        from process_io import ManagedOwner
        owner = ManagedOwner(stream=io.BytesIO(b'{"endpoint":"127.0.0.1:27020","password":""}\nSTOP\n'),
                             configuration_reader=read_managed_connection)
        try:
            self.assertEqual(owner.configuration()[0], '127.0.0.1:27020')
            self.assertTrue(owner.stopped.wait(1))
        finally:
            self.assertTrue(owner.close())

    def test_final_unicode_budget_and_output_order(self):
        from process_io import PublicRecords, encode_record
        output = []
        emit = PublicRecords(output.append)
        emit({'kind': 'weapon_fire', 'fields': {'weapon': '中' * 20000}, 'sequence': None})
        emit({'kind': 'discontinuity', 'world': 2, 'sequence': None})
        self.assertLessEqual(len(encode_record(output[0])), 65536)
        self.assertEqual([r['sequence'] for r in output], [1, 2])
        from wire import ProbeError
        with self.assertRaisesRegex(ProbeError, 'output-record-budget'):
            emit({'kind': 'weapon_fire', 'fields': {'weapon': '中' * 30000}})

    def test_unread_output_pipe_can_be_cancelled_without_waiting_for_consumer(self):
        from process_io import OutputWriter
        import os, time
        read_fd, write_fd = os.pipe()
        writer = OutputWriter(write_fd)
        try:
            for _ in range(32):
                writer.emit({'kind': 'synthetic', 'value': 'x' * 60000})
            time.sleep(.02)
            start = time.monotonic()
            self.assertTrue(writer.abort())
            self.assertLess(time.monotonic() - start, 2)
        finally:
            os.close(read_fd); os.close(write_fd)

    def test_output_pipe_preserves_utf8_and_one_lf(self):
        from process_io import OutputWriter, encode_record
        import os
        read_fd, write_fd = os.pipe()
        if os.name == 'nt':
            import msvcrt
            msvcrt.setmode(write_fd, os.O_TEXT)  # Inherited stdio need not start in binary mode.
        writer = OutputWriter(write_fd)
        row = {'kind': 'synthetic', 'text': '中文\nsecond line'}
        try:
            writer.emit(row)
            self.assertTrue(writer.finish())
            os.close(write_fd); write_fd = None
            self.assertEqual(os.read(read_fd, 4096), encode_record(row))
        finally:
            os.close(read_fd)
            if write_fd is not None: os.close(write_fd)

    @unittest.skipUnless(__import__('os').environ.get('GOTV_ORDERED_WORKER'), 'Set GOTV_ORDERED_WORKER')
    def test_real_driver_worker_and_abandoned_process_pipes_clean_up(self):
        import os,subprocess,sys,tempfile,time,threading
        from pathlib import Path
        for mode in ('unread','closed','slow'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);marker=root/'sdk-cleanup.json';output=root/'run'
                helper=Path(__file__).resolve().parents[1]/'support/managed_pipe_driver.py'
                child=subprocess.Popen([sys.executable,'-B',str(helper),'--managed','--native',str(marker),
                    '--parser-worker',os.environ['GOTV_ORDERED_WORKER'],'--host-version','14193','--output',str(output)],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                reader=None
                try:
                    child.stdin.write(b'{"endpoint":"127.0.0.1:27020","password":"synthetic-only"}\n');child.stdin.flush()
                    if mode=='closed':child.stdout.close()
                    elif mode=='slow':
                        def slow():
                            while child.stdout.read(1024):time.sleep(.005)
                        reader=threading.Thread(target=slow,daemon=True);reader.start()
                    deadline=time.monotonic()+5
                    while not marker.with_suffix('.progress').exists() and child.poll() is None and time.monotonic()<deadline:
                        time.sleep(.01)
                    child.stdin.close()
                    try:
                        child.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait(timeout=5)
                        self.fail('Synthetic cleanup stalled:\n' + child.stderr.read().decode('utf-8', errors='replace'))
                    self.assertIn(child.returncode,(1,2))
                    self.assertEqual(json.loads(marker.read_text())['closed'],1)
                    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
                    self.assertTrue(report['cleanupCompleted'])
                    self.assertIn(report['reason'],('owner-stopped','output-closed','output-backpressure'))
                finally:
                    if child.poll() is None:child.kill();child.wait(timeout=5)
                    if not child.stdin.closed:child.stdin.close()
                    if reader:reader.join(timeout=2)
                    if not child.stdout.closed:child.stdout.close()
                    child.stderr.close()

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
            self.assertTrue(report['cleanupCompleted'])
            self.assertTrue(report['reportWritten'])
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
                with tempfile.TemporaryFile(mode='w+') as stdout_file, tempfile.TemporaryFile(mode='w+') as stderr_file, \
                     patch.object(sys, 'argv', argv), patch.object(sys, 'stdin', input_stream), \
                     patch.object(sys, 'stdout', stdout_file), patch.object(sys, 'stderr', stderr_file), \
                     patch.object(sdk, 'NativePort', fake_native):
                    result = driver.main()
                report = json.loads((output / 'report.json').read_text())
                self.assertEqual(result, 2)
                self.assertEqual(report['reason'], 'owner-stopped')
                self.assertEqual(port.closed, 1)
                self.assertFalse(port.ticket_requested)
                self.assertEqual(report['finalization_failures'], [])
                self.assertTrue(report['cleanupCompleted'])
        finally:
            if writer_open:
                os.close(write_fd)
