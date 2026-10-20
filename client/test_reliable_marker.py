import unittest
from channel import ReliableMessageFilter
from handshake import number

class ReliableMarkerTests(unittest.TestCase):
    def test_filter_region_and_new_marker_do_not_clear_filter(self):
        state = ReliableMessageFilter()
        self.assertTrue(state.accept(61, number(1, 5) + number(3, 1)))
        self.assertTrue(state.accept(207, b''))
        self.assertTrue(state.accept(61, number(1, 5) + number(3, 1)))
        self.assertFalse(state.accept(207, b''))
        self.assertTrue(state.accept(61, number(1, 6) + number(3, 1)))
        self.assertEqual(state.last_tick, 6)
        self.assertFalse(state.accept(55, b''))
        self.assertTrue(state.accept(61, number(3, 0)))
        self.assertTrue(state.accept(55, b''))

    def test_client_owner_and_channel_filter_are_distinct(self):
        state = ReliableMessageFilter()
        state.accept(61, number(1, 8) + number(3, 1))
        state.accept(61, number(1, 8) + number(3, 1))
        state.replace_client_owner()
        self.assertEqual(state.last_tick, 0)
        self.assertTrue(state.filtered)
        state.accept(61, number(3, 0))
        state.accept(61, number(1, 1) + number(3, 1))
        self.assertFalse(state.filtered)
        self.assertEqual(state.last_tick, 1)

    def test_signed_marker(self):
        state = ReliableMessageFilter()
        state.accept(61, number(1, 0xffffffff) + number(3, 1))
        self.assertTrue(state.filtered)
        self.assertEqual(state.last_tick, 0)

if __name__ == '__main__':
    unittest.main()
