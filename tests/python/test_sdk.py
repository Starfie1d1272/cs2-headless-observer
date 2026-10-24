"""Actual ctypes/C ABI with a synthetic, socket-free fixture, never Valve auth."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from sdk import NativePort


@unittest.skipUnless(os.environ.get('GOTV_ABI_FIXTURE') or shutil.which('g++'), 'Build the C ABI fixture with tools/verify_all.py or install g++')
class SdkAbiTest(unittest.TestCase):
    def test_64_bit_handles_bytes_and_cleanup_cross_native_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(os.environ.get('GOTV_ABI_FIXTURE', str(Path(temporary) / 'abi.so')))
            if not os.environ.get('GOTV_ABI_FIXTURE'):
                source = Path(__file__).resolve().parents[1] / 'native/abi_fixture.cpp'
                subprocess.run(['g++', '-std=c++20', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(library)], check=True, capture_output=True)
            # The production owner is a dedicated process. Exit that owner before
            # deleting its DLL: Windows keeps loaded libraries locked even after session.close().
            subprocess.run([sys.executable, '-c',
                'from test_sdk import SdkAbiTest; import sys; from pathlib import Path; '
                'SdkAbiTest().verify_library(Path(sys.argv[1]))', str(library)],
                cwd=Path(__file__).parent, check=True, capture_output=True, text=True)

    def verify_library(self, library):
        port = NativePort(library, '127.0.0.1:27020', 42)
        self.assertEqual(port.handle, 0x1234567887654321)
        self.assertEqual(port.remote_id(), 76561198000000001)
        self.assertEqual(port.state, 5)
        self.assertEqual(port.failure, 0)
        self.assertEqual(port.remote_end_reason, 1234)  # Synthetic callback fixture only.
        self.assertEqual(port.local_id(), 76561198000000042)
        port.accept_server_auth2()
        port.pump(43)
        port.request_ticket()
        self.assertEqual(port.with_auth(lambda data: len(data)), len(b'SYNTHETIC-NOT-A-TICKET'))
        port.send(b'a\0b', 5)
        port.send(b'a\0b', 1)
        self.assertEqual(port.receive(), (b'a\0b', True))
        with self.assertRaisesRegex(ValueError, 'send-failed'): port.send(b'bad', 8)
        with self.assertRaisesRegex(ValueError, 'send-boundary'): port.send(b'a', 123)
        port.close()
        port.close()
        self.assertIsNone(port.handle)
        self.assertEqual(port.state, 6)


if __name__ == '__main__': unittest.main(verbosity=2)

