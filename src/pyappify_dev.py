"""Make the About tab's update check work when the app runs outside the PyAppify launcher."""
import os


def ensure_pyappify_env():
    """Fake a supporting PyAppify launcher when none is running.

    The launcher sets PYAPPIFY_VERSION. Without it, pyappify.get_version_list() raises
    before reaching its test-mode mock. Run this before anything imports pyappify.
    Does nothing under the real launcher.
    """
    if os.environ.get('PYAPPIFY_VERSION'):
        return
    os.environ['PYAPPIFY_VERSION'] = '1.2.2'
    os.environ.setdefault('PYAPPIFY_PYTHON_TEST', '1')
