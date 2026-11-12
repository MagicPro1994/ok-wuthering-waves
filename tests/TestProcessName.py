import os
import sys
import tempfile
import unittest
from pathlib import Path

from src import process_name as pn


class TestProcessName(unittest.TestCase):
    def test_is_renamed(self):
        self.assertTrue(pn.is_renamed(r'C:\venv\rj-helper\rj-helper.exe'))
        self.assertTrue(pn.is_renamed(r'C:\venv\rj-helper\RJ-Helper.exe'))
        self.assertFalse(pn.is_renamed(r'C:\venv\Scripts\python.exe'))

    def test_windowed(self):
        self.assertTrue(pn._windowed('pythonw.exe'))
        self.assertFalse(pn._windowed('python.exe'))

    def test_prepare_copies_interpreter_and_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            base, venv = Path(root, 'base'), Path(root, 'venv')
            base.mkdir()
            venv.mkdir()
            version_dll = f'python{sys.version_info.major}{sys.version_info.minor}.dll'
            for name in ('python.exe', 'pythonw.exe', version_dll, 'python3.dll'):
                Path(base, name).write_bytes(name.encode())

            console = pn.prepare_interpreter(base / 'python.exe', venv)
            windowed = pn.prepare_interpreter(base / 'python.exe', venv, windowed=True)

            self.assertEqual(console, venv / 'rj-helper' / 'rj-helper.exe')
            self.assertEqual(console.read_bytes(), b'python.exe')
            self.assertEqual(windowed, venv / 'rj-helper-gui' / 'rj-helper.exe')
            self.assertEqual(windowed.read_bytes(), b'pythonw.exe')
            self.assertTrue((venv / 'rj-helper' / version_dll).exists())
            # Optional runtime files that the base install lacks are skipped.
            self.assertFalse((venv / 'rj-helper' / 'vcruntime140.dll').exists())

    def test_prepare_refreshes_stale_copy(self):
        with tempfile.TemporaryDirectory() as root:
            base, venv = Path(root, 'base'), Path(root, 'venv')
            base.mkdir()
            venv.mkdir()
            source = base / 'python.exe'
            source.write_bytes(b'old')
            target = pn.prepare_interpreter(source, venv)
            source.write_bytes(b'newer')
            os.utime(source, ns=(target.stat().st_mtime_ns + 10 ** 9,) * 2)
            pn.prepare_interpreter(source, venv)
            self.assertEqual(target.read_bytes(), b'newer')


if __name__ == '__main__':
    unittest.main()
