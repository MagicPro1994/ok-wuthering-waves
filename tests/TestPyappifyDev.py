import os
import unittest
from unittest import mock

from src.pyappify_dev import ensure_pyappify_env


class TestPyappifyDev(unittest.TestCase):
    def test_sets_defaults_outside_launcher(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            ensure_pyappify_env()
            self.assertEqual(os.environ['PYAPPIFY_VERSION'], '1.2.2')
            self.assertEqual(os.environ['PYAPPIFY_PYTHON_TEST'], '1')

    def test_leaves_launcher_environment_alone(self):
        with mock.patch.dict(os.environ, {'PYAPPIFY_VERSION': '1.3.0'}, clear=True):
            ensure_pyappify_env()
            self.assertEqual(os.environ['PYAPPIFY_VERSION'], '1.3.0')
            self.assertNotIn('PYAPPIFY_PYTHON_TEST', os.environ)


if __name__ == '__main__':
    unittest.main()
