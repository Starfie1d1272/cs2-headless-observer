import unittest
from observer_settings import ObserverSettings
from handshake import blob, number
from wire import fields, scalar

class ObserverSettingsTests(unittest.TestCase):
    def test_only_truthful_owned_values(self):
        settings = ObserverSettings()
        rows = fields(scalar(fields(settings.userinfo()), 1, 2))[1]
        names = [scalar(fields(payload), 1, 2) for wire, payload in rows]
        self.assertEqual(names, [b'name', b'tv_relay', b'rate'])
        rate = fields(settings.query(number(1, 8) + blob(2, b'rate')))
        self.assertEqual(scalar(rate, 2), 0)
        self.assertEqual(scalar(rate, 4, 2), b'786432')
        result = fields(settings.query(number(1, 7) + blob(2, b'tv_relay')))
        self.assertEqual(scalar(result, 1), 7)
        self.assertEqual(scalar(result, 2), 0)
        self.assertEqual(scalar(result, 4, 2), b'0')

    def test_unknown_host_secret_name_never_queries_host(self):
        result = fields(ObserverSettings().query(number(1, 0xffffffff) + blob(2, b'OPENAI_API_KEY')))
        self.assertEqual(scalar(result, 1), 0xffffffff)
        self.assertEqual(scalar(result, 2), 1)
        self.assertEqual(scalar(result, 3, 2), b'OPENAI_API_KEY')
        self.assertEqual(scalar(result, 4, 2), b'')

if __name__ == '__main__':
    unittest.main()
