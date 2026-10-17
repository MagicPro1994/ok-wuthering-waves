import ctypes
import math
import random as _random
import time

MOVE = 0x0001
LEFTDOWN = 0x0002
LEFTUP = 0x0004
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


def to_screen(origin, size, fx, fy):
    return int(origin[0] + fx * size[0]), int(origin[1] + fy * size[1])


class Win32Api:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.user32.SetProcessDPIAware()

    def set_cursor(self, x, y):
        self.user32.SetCursorPos(int(x), int(y))

    def mouse_event(self, flags, dx=0, dy=0):
        self.user32.mouse_event(flags, int(dx), int(dy), 0, 0)

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def set_foreground(self, hwnd):
        self.user32.SetForegroundWindow(hwnd)

    def keybd_alt(self):
        self.user32.keybd_event(VK_MENU, 0, 0, 0)
        self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    def client_origin(self, hwnd):
        import win32gui
        return win32gui.ClientToScreen(hwnd, (0, 0))

    def client_size(self, hwnd):
        import win32gui
        return win32gui.GetClientRect(hwnd)[2:]


class RealInput:
    """Real-cursor input for what PostMessage cannot do (cargo pieces, time dial, camera)."""

    def __init__(self, hwnd, api=None, sleep=time.sleep, rng=_random):
        self.hwnd = hwnd
        self.api = api or Win32Api()
        self.sleep = sleep
        self.rng = rng

    def focus(self):
        for _ in range(5):
            if self.api.foreground() == self.hwnd:
                return
            self.api.keybd_alt()
            self.api.set_foreground(self.hwnd)
            self.sleep(self.rng.uniform(0.15, 0.35))
        if self.api.foreground() != self.hwnd:
            raise RuntimeError("game window not in foreground")

    def rel_move(self, dx, dy):
        self.api.mouse_event(MOVE, dx, dy)

    def drag(self, x1, y1, x2, y2, duration=0.9):
        self.focus()
        origin = self.api.client_origin(self.hwnd)
        size = self.api.client_size(self.hwnd)
        start = to_screen(origin, size, x1, y1)
        end = to_screen(origin, size, x2, y2)
        self.api.set_cursor(*start)
        self.sleep(self.rng.uniform(0.15, 0.3))
        self.api.mouse_event(LEFTDOWN)
        self.sleep(self.rng.uniform(0.2, 0.3))
        steps = max(12, int(duration / 0.015))
        wobble = self.rng.uniform(2.0, 6.0)
        phase = self.rng.uniform(0, math.pi)
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)
            x = start[0] + (end[0] - start[0]) * eased
            y = start[1] + (end[1] - start[1]) * eased + wobble * math.sin(math.pi * t + phase) * (1 - t)
            self.api.set_cursor(x, y)
            self.sleep(self.rng.uniform(0.010, 0.020))
        self.api.set_cursor(*end)
        self.sleep(self.rng.uniform(0.2, 0.3))
        self.api.mouse_event(LEFTUP)

    def click(self, x, y):
        """A real click with the cursor, for screens that ignore the posted clicks (the fishing result)."""
        self.focus()
        origin = self.api.client_origin(self.hwnd)
        size = self.api.client_size(self.hwnd)
        self.api.set_cursor(*to_screen(origin, size, x, y))
        self.sleep(self.rng.uniform(0.15, 0.3))
        self.api.mouse_event(LEFTDOWN)
        self.sleep(self.rng.uniform(0.06, 0.12))
        self.api.mouse_event(LEFTUP)
