import unittest
from node_runtime import validate_info


class NodeRuntimeTests(unittest.TestCase):
    def info(self, version='24.0.0'):
        return {'version': version, 'platform': 'win32', 'arch': 'x64',
                'features': ['object', 'function', 'function']}

    def test_support_is_not_bound_to_a_patch_release_or_supplier(self):
        for version in ('24.0.0', '24.14.0', '24.21.0', '24.22.0', '26.0.0'):
            self.assertEqual(validate_info(self.info(version))['version'], version)

    def test_rejects_unsupported_runtime_and_missing_capabilities(self):
        for key, value in [('version', '22.0.0'), ('version', '24.0.0-rc.1'),
                           ('platform', None), ('arch', None), ('features', [])]:
            info = self.info(); info[key] = value
            with self.assertRaises(ValueError): validate_info(info)
