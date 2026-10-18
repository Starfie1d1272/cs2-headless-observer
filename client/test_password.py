"""Known answers from independently compiled public ICE code; all inputs synthetic."""
import json
from pathlib import Path
import unittest
from password import transform_password, ice1_encrypt


class PasswordTest(unittest.TestCase):
    def test_independent_known_answers(self):
        evidence = json.loads((Path(__file__).parent / 'evidence/password-oracle.json').read_text())
        for case in evidence['known_answers']:
            self.assertEqual(transform_password(bytes.fromhex(case['synthetic_password_hex']),
                case['challenge']).hex(), case['expected_hex'])

    def test_boundaries_do_not_silently_truncate_or_guess_encoding(self):
        self.assertIsNone(transform_password(b'', 0))
        self.assertEqual(len(transform_password(b'x' * 95, 1)), 96)
        for value in [b'x' * 96, b'x\0y', 'text-not-bytes', None]:
            with self.assertRaisesRegex(ValueError, 'password-byte-boundary'):
                transform_password(value, 1)
        for challenge in [-1, 2**32, True, 1.5]:
            with self.assertRaisesRegex(ValueError, 'challenge-range'):
                transform_password(b'unit', challenge)
        with self.assertRaisesRegex(ValueError, 'ice-input-boundary'):
            ice1_encrypt(bytes(8), bytes(7))


if __name__ == '__main__':
    unittest.main(verbosity=2)
