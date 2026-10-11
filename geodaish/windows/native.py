"""Small, typed Win32 boundary. Importable on non-Windows test hosts."""

import ctypes as C
from ctypes import wintypes as W
from pathlib import PureWindowsPath
import sys
import time

import numpy as np


class NativeError(RuntimeError):
    pass


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", W.DWORD), ("data", INPUTUNION)]


class WindowsGame:
    def __init__(self, title="Geometry Dash", jump_key="space"):
        if sys.platform != "win32":
            raise NativeError("This adapter requires Windows")
        self.jump_vk, self.jump_scan, self.jump_flags = {"space": (0x20,0x39,0), "up": (0x26,0x48,1)}[jump_key]
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self._prototypes()
        try:
            self.user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        except AttributeError:
            self.user.SetProcessDPIAware()
        windows = []
        callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

        @callback_type
        def visit(hwnd, _):
            name = C.create_unicode_buffer(512)
            self.user.GetWindowTextW(hwnd, name, len(name))
            if name.value == title and self.user.IsWindowVisible(hwnd):
                pid = self._pid(hwnd)
                if self._exe(pid).lower() == "geometrydash.exe":
                    windows.append((hwnd, pid))
            return True

        self.user.EnumWindows(visit, 0)
        if len(windows) != 1:
            raise NativeError(f"Expected one visible GeometryDash.exe window titled {title!r}; found {len(windows)}")
        self.hwnd, self.pid = windows[0]
        self.title = title

    def _prototypes(self):
        u, k = self.user, self.kernel
        u.GetForegroundWindow.restype = W.HWND
        u.IsWindow.argtypes = u.IsWindowVisible.argtypes = u.IsIconic.argtypes = [W.HWND]
        u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
        u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        u.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        u.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
        u.SendInput.restype = W.UINT
        u.GetAsyncKeyState.argtypes = [C.c_int]
        u.GetAsyncKeyState.restype = C.c_short
        u.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
        u.UnregisterHotKey.argtypes = [W.HWND, C.c_int]
        u.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
        k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        k.OpenProcess.restype = W.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        k.CloseHandle.argtypes = [W.HANDLE]

    def _pid(self, hwnd):
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return pid.value

    def _exe(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            name, size = C.create_unicode_buffer(32768), W.DWORD(32768)
            if self.kernel.QueryFullProcessImageNameW(handle, 0, name, C.byref(size)):
                return PureWindowsPath(name.value).name
            return ""
        finally:
            self.kernel.CloseHandle(handle)

    def available(self):
        return bool(self.user.IsWindow(self.hwnd) and self._pid(self.hwnd) == self.pid
                    and self.user.IsWindowVisible(self.hwnd) and not self.user.IsIconic(self.hwnd))

    def focused(self):
        return self.available() and self.user.GetForegroundWindow() == self.hwnd

    def client_region(self):
        if not self.available():
            raise NativeError("Game window was closed, minimized or replaced")
        rect, point = W.RECT(), W.POINT()
        if not self.user.GetClientRect(self.hwnd, C.byref(rect)) or not self.user.ClientToScreen(self.hwnd, C.byref(point)):
            raise NativeError("Could not read the game client rectangle")
        if rect.right < 100 or rect.bottom < 100:
            raise NativeError("Game client is too small to capture")
        return {"left": point.x, "top": point.y, "width": rect.right, "height": rect.bottom}

    def key_down(self, vk):
        return bool(self.user.GetAsyncKeyState(vk) & 0x8000)

    def register_stop(self):
        # Register on the watchdog thread; WM_HOTKEY queues even brief presses.
        if not self.user.RegisterHotKey(None, 0x4744, 0x4000, 0x78):
            raise NativeError("Cannot reserve F9 stop hotkey; close another adapter/hotkey owner")

    def stop_requested(self):
        message = W.MSG()
        requested = False
        while self.user.PeekMessageW(C.byref(message), None, 0x0312, 0x0312, 1):
            requested |= message.wParam == 0x4744
        return requested

    def unregister_stop(self):
        self.user.UnregisterHotKey(None, 0x4744)

    def send_jump(self, down):
        # Only a release is allowed after focus loss: clean up our own held key.
        if down and not self.focused():
            raise NativeError("Refusing jump: Geometry Dash is not foreground")
        event = INPUT(type=1)
        event.ki = KEYBDINPUT(self.jump_vk, self.jump_scan, self.jump_flags | (0 if down else 0x0002), 0, 0)
        if self.user.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
            raise NativeError("SendInput failed; check that the game and adapter use the same elevation level")


class GameCapture:
    def __init__(self, game):
        import mss
        self.game = game
        self.screen = mss.mss()

    def grab(self):
        region = self.game.client_region()
        started = time.perf_counter()
        raw = np.asarray(self.screen.grab(region))
        # MSS is BGRA, policy detector takes RGB, never the whole desktop.
        frame = np.ascontiguousarray(raw[:, :, 2::-1])
        return frame, time.perf_counter(), time.perf_counter() - started

    def close(self):
        self.screen.close()
