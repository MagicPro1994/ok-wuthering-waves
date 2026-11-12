"""Run the app under a custom process name (rj-helper.exe) instead of python.exe.

Windows takes a process's name from its exe file, so we keep a renamed copy of
the real interpreter inside the venv and relaunch through it. The copy lives in
a subfolder of the venv, so it finds pyvenv.cfg one level up and loads the
venv's packages like the normal interpreter does.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROCESS_NAME = 'rj-helper'
# Set this to any value to skip the rename and run as plain python.exe.
DISABLE_ENV = 'RJ_HELPER_DISABLE'

# Files the interpreter needs next to it to start.
RUNTIME_FILES = ('python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')


def is_renamed(executable=None):
    return Path(executable or sys.executable).stem.lower() == PROCESS_NAME


def _windowed(executable):
    return Path(executable).stem.lower().endswith('w')


def _needs_copy(source, target):
    try:
        a, b = source.stat(), target.stat()
    except FileNotFoundError:
        return True
    return a.st_size != b.st_size or a.st_mtime_ns != b.st_mtime_ns


def _copy(source, target):
    if not _needs_copy(source, target):
        return
    temporary = target.with_name(f'{target.name}.{os.getpid()}.tmp')
    shutil.copy2(source, temporary)
    try:
        os.replace(temporary, target)
    except OSError:
        os.unlink(temporary)
        # Another instance is running from the old copy. Use it if it exists.
        if not target.exists():
            raise


def prepare_interpreter(base_executable, venv_dir, windowed=False):
    """Copy the base interpreter into the venv as rj-helper.exe and return its path."""
    base_dir = Path(base_executable).parent
    folder = Path(venv_dir) / (f'{PROCESS_NAME}-gui' if windowed else PROCESS_NAME)
    folder.mkdir(exist_ok=True)
    version_dll = f'python{sys.version_info.major}{sys.version_info.minor}.dll'
    for name in (version_dll, *RUNTIME_FILES):
        if (base_dir / name).exists():
            _copy(base_dir / name, folder / name)
    target = folder / f'{PROCESS_NAME}.exe'
    _copy(base_dir / ('pythonw.exe' if windowed else 'python.exe'), target)
    return target


def ensure_process_name():
    """Relaunch this script through rj-helper.exe, then exit with its exit code.

    Does nothing when already running as rj-helper.exe, outside Windows, outside
    a venv, or when RJ_HELPER_DISABLE is set. Any setup error falls back to
    running normally, so the app always starts.
    """
    if sys.platform != 'win32' or getattr(sys, 'frozen', False) or os.environ.get(DISABLE_ENV):
        return
    if is_renamed() or sys.prefix == sys.base_prefix or not sys.argv or not sys.argv[0]:
        return
    base_executable = getattr(sys, '_base_executable', None) or sys.executable
    try:
        target = prepare_interpreter(base_executable, sys.prefix, _windowed(sys.executable))
    except OSError as error:
        print(f'Could not set up {PROCESS_NAME}.exe, running as {Path(sys.executable).name}: {error}',
              file=sys.stderr)
        return

    command = [str(target), *subprocess._args_from_interpreter_flags(), *sys.argv]
    process = subprocess.Popen(command)
    # Stay alive so the console and the caller see the real exit code. Ctrl+C
    # also reaches the child through the shared console, so let it handle that.
    while True:
        try:
            sys.exit(process.wait())
        except KeyboardInterrupt:
            continue
