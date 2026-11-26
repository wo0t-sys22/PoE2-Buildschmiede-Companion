"""Win32 window styles, monitor DPI and global guide shortcuts."""

from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import logging
import os
import socket
import struct
import time
from threading import Event, Thread

from poe2_hotkeys import HUD_HOTKEYS, timer_bindings  # noqa: F401  (re-exported for older imports)
from poe2_overlay_version import APP_NAME, BUILD, BUILD_LABEL, running_guide_build


WM_MOUSEWHEEL = 0x020A
GUIDE_WINDOWS = {f"{APP_NAME} – Kampagne", f"{APP_NAME} – Endgame & Atlas"}


def _bind(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = args
    return function


def register_private_fonts(paths) -> None:
    # GDI keeps a private copy for this process and releases it on exit.
    gdi = c.WinDLL("gdi32")
    register = _bind(gdi, "AddFontMemResourceEx", w.HANDLE, c.c_void_p, w.DWORD,
                     c.c_void_p, c.POINTER(w.DWORD))
    for path in paths:
        data = path.read_bytes()
        font_count = w.DWORD()
        if not register(c.create_string_buffer(data), len(data), None, c.byref(font_count)):
            logging.warning("Schrift konnte nicht geladen werden: %s", path.name)


class MonitorInfo(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD),
    ]


class Message(c.Structure):
    _fields_ = [
        ("hwnd", w.HWND), ("message", w.UINT), ("wParam", w.WPARAM),
        ("lParam", w.LPARAM), ("time", w.DWORD), ("point", w.POINT), ("private", w.DWORD),
    ]


class MouseEvent(c.Structure):
    _fields_ = [
        ("point", w.POINT), ("data", w.DWORD), ("flags", w.DWORD),
        ("time", w.DWORD), ("extra_info", c.c_size_t),
    ]


class WindowsOverlay:
    color_key = True  # the HUD's TRANSPARENT colour is invisible and lets clicks through
    COLOR_KEY = 0x00010101
    LAYERED = 0x00080000
    TOOL_WINDOW = 0x00000080
    TRANSPARENT_STYLE = 0x00000020
    NO_ACTIVATE = 0x08000000
    PASS_THROUGH = TRANSPARENT_STYLE | NO_ACTIVATE

    def __init__(self):
        user = c.WinDLL("user32", use_last_error=True)
        kernel = c.WinDLL("kernel32", use_last_error=True)
        try:
            dpi_awareness = _bind(user, "SetProcessDpiAwarenessContext", w.BOOL, w.HANDLE)
            dpi_awareness(w.HANDLE(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            self.dpi_for_window = _bind(user, "GetDpiForWindow", w.UINT, w.HWND)
        except AttributeError:
            _bind(user, "SetProcessDPIAware", w.BOOL)()
            self.dpi_for_window = lambda hwnd: 0
        self.ancestor = _bind(user, "GetAncestor", w.HWND, w.HWND, w.UINT)
        self.monitor_from_window = _bind(user, "MonitorFromWindow", w.HMONITOR, w.HWND, w.DWORD)
        self.monitor_from_point = _bind(user, "MonitorFromPoint", w.HMONITOR, w.POINT, w.DWORD)
        self.monitor_from_rect = _bind(user, "MonitorFromRect", w.HMONITOR, c.POINTER(w.RECT), w.DWORD)
        self.monitor_info = _bind(user, "GetMonitorInfoW", w.BOOL, w.HMONITOR, c.POINTER(MonitorInfo))
        self.cursor_pos = _bind(user, "GetCursorPos", w.BOOL, c.POINTER(w.POINT))
        self.window_rect = _bind(user, "GetWindowRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
        self.window_pos = _bind(user, "SetWindowPos", w.BOOL,
                                w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT)
        self.get_style = _bind(user, "GetWindowLongW", w.LONG, w.HWND, c.c_int)
        self.set_style = _bind(user, "SetWindowLongW", w.LONG, w.HWND, c.c_int, w.LONG)
        set_window_long = "SetWindowLongPtrW" if c.sizeof(c.c_void_p) == 8 else "SetWindowLongW"
        self.set_window_long_ptr = _bind(user, set_window_long, c.c_ssize_t, w.HWND, c.c_int, c.c_ssize_t)
        self.set_layered = _bind(user, "SetLayeredWindowAttributes", w.BOOL, w.HWND, w.COLORREF, w.BYTE, w.DWORD)
        self.register = _bind(user, "RegisterHotKey", w.BOOL, w.HWND, c.c_int, w.UINT, w.UINT)
        self.unregister = _bind(user, "UnregisterHotKey", w.BOOL, w.HWND, c.c_int)
        self.peek = _bind(user, "PeekMessageW", w.BOOL, c.POINTER(Message), w.HWND, w.UINT, w.UINT, w.UINT)
        self.key_state = _bind(user, "GetAsyncKeyState", w.SHORT, c.c_int)
        self.mouse_proc = c.WINFUNCTYPE(c.c_ssize_t, c.c_int, w.WPARAM, w.LPARAM)
        self.hook_mouse = _bind(user, "SetWindowsHookExW", w.HANDLE,
                                c.c_int, self.mouse_proc, w.HMODULE, w.DWORD)
        self.unhook_mouse = _bind(user, "UnhookWindowsHookEx", w.BOOL, w.HANDLE)
        self.next_mouse_hook = _bind(user, "CallNextHookEx", c.c_ssize_t,
                                     w.HANDLE, c.c_int, w.WPARAM, w.LPARAM)
        self.wait_input = _bind(user, "MsgWaitForMultipleObjectsEx", w.DWORD,
                                w.DWORD, c.POINTER(w.HANDLE), w.DWORD, w.DWORD, w.DWORD)
        self.module_handle = _bind(kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)
        self.window_enum_proc = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        self.enum_windows = _bind(user, "EnumWindows", w.BOOL, self.window_enum_proc, w.LPARAM)
        self.window_pid = _bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
        self.window_title = _bind(user, "GetWindowTextW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
        self.post_message = _bind(user, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        self.create_event = _bind(kernel, "CreateEventW", w.HANDLE, c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR)
        self.signal = _bind(kernel, "SetEvent", w.BOOL, w.HANDLE)
        self.wait = _bind(kernel, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)
        self.close_handle = _bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
        self.event = None
        self.worker = None
        self.stop = Event()
        self.extra_hotkeys = {}
        self.wheel_target = None

    def claim(self):
        deadline = time.monotonic() + 4
        requested = set()
        while True:
            c.set_last_error(0)
            handle = self.create_event(None, False, False, r"Local\terence.PoE2IngameGuide")
            error = c.get_last_error()
            if not handle:
                raise c.WinError(error)
            if error != 183:  # ERROR_ALREADY_EXISTS
                self.event = handle
                return True
            try:
                peer = self._running_overlay()
                if peer:
                    build, pid = peer
                    if build >= BUILD:
                        if not self.signal(handle):
                            raise c.WinError(c.get_last_error())
                        return False
                    if pid not in requested and self._request_guide_close(pid):
                        logging.info("Vorherigen PoE2 Ingame Guide zum Schließen aufgefordert.")
                        requested.add(pid)
            finally:
                self.close_handle(handle)
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Ein anderer Ingame Guide läuft noch. Beende ihn mit F10 und starte {BUILD_LABEL} erneut.")
            time.sleep(.08)

    def _running_overlay(self):
        listeners = self._local_listeners()
        pids = {pid for _, pid in listeners if pid != os.getpid()}
        windows = self._guide_windows(pids)
        peers = []
        for port, pid in listeners:
            if pid in windows:
                build = running_guide_build(port)
                if build is not None:
                    peers.append((build, pid))
        return max(peers, default=None, key=lambda peer: peer[0])

    def _local_listeners(self):
        ip_helper = c.WinDLL("iphlpapi")
        table = _bind(ip_helper, "GetExtendedTcpTable", c.c_uint32,
                      c.c_void_p, c.POINTER(c.c_uint32), w.BOOL, c.c_uint32, c.c_int, c.c_uint32)
        size = c.c_uint32()
        table(None, c.byref(size), False, socket.AF_INET, 3, 0)  # TCP_TABLE_OWNER_PID_LISTENER
        for _ in range(2):
            buffer = c.create_string_buffer(size.value)
            status = table(buffer, c.byref(size), False, socket.AF_INET, 3, 0)
            if status == 0:
                return self._loopback_listeners(buffer.raw)
            if status != 122:  # ERROR_INSUFFICIENT_BUFFER
                break
        return []

    @staticmethod
    def _loopback_listeners(data):
        if len(data) < 4:
            return []
        count, = struct.unpack_from("<I", data)
        row = struct.Struct("<6I")
        end = 4 + count * row.size
        if end > len(data):
            return []
        loopback = int.from_bytes(socket.inet_aton("127.0.0.1"), "little")
        return [
            (socket.ntohs(port & 0xffff), pid)
            for _, address, port, _, _, pid in row.iter_unpack(data[4:end])
            if address == loopback
        ]

    def _guide_windows(self, pids):
        windows = {}

        @self.window_enum_proc
        def find_window(hwnd, _):
            owner = w.DWORD()
            if not self.window_pid(hwnd, c.byref(owner)) or owner.value not in pids:
                return True
            title = c.create_unicode_buffer(96)
            if self.window_title(hwnd, title, len(title)) and title.value in GUIDE_WINDOWS:
                windows.setdefault(owner.value, hwnd)
            return True

        self.enum_windows(find_window, 0)
        return windows

    def _request_guide_close(self, pid):
        window = self._guide_windows({pid}).get(pid)
        return bool(window and self.post_message(window, 0x0010, 0, 0))  # WM_CLOSE

    def recovery_requested(self):
        return self.event is not None and self.wait(self.event, 0) == 0

    def hwnd(self, window):
        child = window.winfo_id()
        return self.ancestor(child, 2) or child  # GA_ROOT

    def work_area(self, *, rect=None, point=None, full_monitor=False):
        if point is not None:
            monitor = self.monitor_from_point(w.POINT(*point), 2)
        else:
            native_rect = w.RECT(*rect)
            monitor = self.monitor_from_rect(c.byref(native_rect), 2)
        info = MonitorInfo(size=c.sizeof(MonitorInfo))
        if monitor and self.monitor_info(monitor, c.byref(info)):
            bounds = info.monitor if full_monitor else info.work
            return bounds.left, bounds.top, bounds.right, bounds.bottom
        return None

    def display_bounds(self, window):
        info = MonitorInfo()
        info.size = c.sizeof(info)
        monitor = self.monitor_from_window(self.hwnd(window), 2)
        if self.monitor_info(monitor, c.byref(info)):
            r = info.monitor
            return r.left, r.top, r.right, r.bottom
        return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()

    def style_dialog(self, window, *, palette=None):
        # Supported attributes depend on the Windows build. The OS keeps its
        # standard title bar controls and ignores unsupported colour attributes.
        setter = _bind(c.WinDLL("dwmapi"), "DwmSetWindowAttribute", c.c_long,
                       w.HWND, w.DWORD, c.c_void_p, w.DWORD)
        colors = (0x44586D, 0x171717, 0xADCEE0)
        if palette:
            colors = tuple(int.from_bytes(bytes.fromhex(color[1:]), "little") for color in palette)
        hwnd = self.hwnd(window)
        for attribute, color in zip((20, 34, 35, 36), (1, *colors)):
            value = w.DWORD(color)
            setter(hwnd, attribute, c.byref(value), c.sizeof(value))

    def positioned_at(self, hwnd):
        rect = w.RECT()
        if self.window_rect(hwnd, c.byref(rect)):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        return None

    def place(self, hwnd, x, y, width, height):
        if not self.window_pos(hwnd, None, x, y, width, height, 0x0004 | 0x0010):
            raise c.WinError(c.get_last_error())

    def set_input_region(self, window, rectangles):
        """Not needed on Windows: the colour key and the click-target window route the input."""

    def set_opacity(self, window, alpha):
        """Apply the colour key and window alpha to an already layered window."""
        self.set_layered(self.hwnd(window), self.COLOR_KEY, alpha, 3)  # LWA_COLORKEY | LWA_ALPHA

    def stack_below(self, window, target, rect):
        """Place the window at rect directly below the native target window."""
        self.window_pos(self.hwnd(window), target, *rect, 0x0010)  # SWP_NOACTIVATE

    def pointer(self):
        point = w.POINT()
        if self.cursor_pos(c.byref(point)):
            return point.x, point.y
        return None

    def _style(self, hwnd):
        c.set_last_error(0)
        style = self.get_style(hwnd, -20)  # GWL_EXSTYLE
        if not style and c.get_last_error():
            raise c.WinError(c.get_last_error())
        return style

    def _set_extended_style(self, hwnd, style):
        c.set_last_error(0)
        if not self.set_style(hwnd, -20, style) and c.get_last_error():
            raise c.WinError(c.get_last_error())

    def set_click_mode(self, window, enabled, *, no_activate=False, alpha=255, owner=None):
        hwnd = self.hwnd(window)
        if owner is not None:
            # An owned window stays above its guide even if Tk raises the guide
            # while returning focus from a dialog. This does not make it a child.
            c.set_last_error(0)
            if not self.set_window_long_ptr(hwnd, -8, self.hwnd(owner)) and c.get_last_error():  # GWLP_HWNDPARENT
                raise c.WinError(c.get_last_error())
        original = self._style(hwnd)
        desired = (original | self.LAYERED | self.TOOL_WINDOW) & ~self.PASS_THROUGH
        if enabled:
            desired |= self.PASS_THROUGH
        elif no_activate:
            desired |= self.NO_ACTIVATE
        try:
            if original != desired:
                self._set_extended_style(hwnd, desired)
            flags = 1 if alpha == 255 else 3  # LWA_COLORKEY, plus LWA_ALPHA for the input window
            if not self.set_layered(hwnd, self.COLOR_KEY, alpha, flags):
                raise c.WinError(c.get_last_error())
            flags = 0x0001 | 0x0002 | 0x0010 | 0x0020
            if not self.window_pos(hwnd, w.HWND(-1), 0, 0, 0, 0, flags):  # HWND_TOPMOST
                raise c.WinError(c.get_last_error())
            if (self._style(hwnd) & self.PASS_THROUGH) != (desired & self.PASS_THROUGH):
                raise OSError("Windows hat den Klickmodus nicht übernommen.")
        except OSError:
            self._set_extended_style(hwnd, original)
            raise

    def start_hotkeys(self, queue):
        self.worker = Thread(target=self._hotkeys, args=(queue,), daemon=True)
        self.worker.start()

    def configure_hotkeys(self, bindings):
        self.extra_hotkeys = dict(bindings)

    def set_wheel_target(self, owner, rect, exclude=None):
        if rect is not None:
            self.wheel_target = (owner, rect, exclude)
        elif self.wheel_target is not None and self.wheel_target[0] is owner:
            self.wheel_target = None

    def _wheel_event(self, queue, code, message, address):
        target = self.wheel_target
        if code >= 0 and message == WM_MOUSEWHEEL and target is not None:
            owner, (left, top, right, bottom), exclude = target
            mouse = c.cast(address, c.POINTER(MouseEvent)).contents
            x, y = mouse.point.x, mouse.point.y
            covered = exclude and exclude[0] <= x < exclude[2] and exclude[1] <= y < exclude[3]
            if not covered and left <= x < right and top <= y < bottom:
                delta = c.c_short(mouse.data >> 16).value
                if delta:
                    queue.put((owner, delta))
                    return 1
        return self.next_mouse_hook(None, code, message, address)

    def _hotkeys(self, queue):
        message = Message()
        # Create the worker thread's message queue before registering thread hotkeys.
        self.peek(c.byref(message), None, 0, 0, 0)
        callback = self.mouse_proc(lambda code, msg, address: self._wheel_event(queue, code, msg, address))
        hook = None
        wheel_active = False
        bindings, registered, fallback, down = {}, set(), {}, {}
        try:
            while not self.stop.is_set():
                wanted_wheel = self.wheel_target is not None
                if wanted_wheel != wheel_active:
                    wheel_active = wanted_wheel
                    if wheel_active:
                        hook = self.hook_mouse(14, callback, self.module_handle(None), 0)  # WH_MOUSE_LL
                        if not hook:
                            logging.warning("Mausrad-Weiterleitung konnte nicht gestartet werden.")
                    elif hook:
                        self.unhook_mouse(hook)
                        hook = None
                wanted = self.extra_hotkeys
                if wanted != bindings:
                    for ident, binding in bindings.items():
                        if wanted.get(ident) != binding:
                            if ident in registered:
                                self.unregister(None, ident)
                                registered.remove(ident)
                            fallback.pop(ident, None)
                            down.pop(ident, None)
                    for ident, (mods, key) in wanted.items():
                        if bindings.get(ident) == (mods, key):
                            continue
                        if self.register(None, ident, mods | 0x4000, key):  # MOD_NOREPEAT
                            registered.add(ident)
                        else:
                            fallback[ident] = mods, key
                            down[ident] = True
                            logging.warning("Hotkey %s belegt. Tastenzustand wird als Ersatz gelesen.", ident)
                    bindings = wanted
                for ident, (mods, key) in fallback.items():
                    held = bool(self.key_state(key) & 0x8000)
                    if held and not down[ident] and self._modifiers() == mods:
                        queue.put(ident)
                    down[ident] = held
                while self.peek(c.byref(message), None, 0x0312, 0x0312, 1):  # WM_HOTKEY, PM_REMOVE
                    if int(message.wParam) in registered:
                        queue.put(int(message.wParam))
                if hook:
                    # Wake on sent mouse events rather than delaying them by the polling interval.
                    self.wait_input(0, None, 20, 0x0040 | 0x0080, 0x0004)
                else:
                    self.stop.wait(.02)
        finally:
            if hook:
                self.unhook_mouse(hook)
            for ident in registered:
                self.unregister(None, ident)

    def _modifiers(self):
        flags = sum(mask for key, mask in ((0x12, 1), (0x11, 2), (0x10, 4)) if self.key_state(key) & 0x8000)
        return flags | (8 if (self.key_state(0x5B) | self.key_state(0x5C)) & 0x8000 else 0)

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=.3)
        if self.event:
            self.close_handle(self.event)
            self.event = None
