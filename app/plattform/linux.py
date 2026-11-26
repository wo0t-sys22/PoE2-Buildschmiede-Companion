"""X11 integration of the HUD for Linux desktops.

Tk always talks X11 on Linux, so under Wayland desktops the guide runs through XWayland.
PoE2 under Steam/Proton is an X11 client as well, which keeps the guide, its global
hotkeys and the game in the same X11 world.

What this backend provides:
- click-through: the X Shape extension limits mouse input to the guide's buttons,
- global hotkeys: XGrabKey on the root window in a worker thread with its own connection,
- monitor and work area: XRandR monitors and _NET_WORKAREA,
- single instance: a lock file with handover to a newer build, like on Windows.

Without a colour key the HUD keeps an opaque background; the guide's transparency
slider maps to the window opacity (needs a compositing desktop, which KDE and GNOME are).
"""

from __future__ import annotations

import ctypes as c
import ctypes.util
import errno
import logging
import os
from pathlib import Path
import signal
import tempfile
from threading import Event, Thread
import time

from poe2_overlay_version import BUILD, BUILD_LABEL, running_guide_build

# X11 modifier masks
SHIFT_MASK, LOCK_MASK, CONTROL_MASK, MOD1_MASK, MOD2_MASK, MOD4_MASK = 1, 2, 4, 8, 16, 64
# poe2_hotkeys uses the Win32 flags ALT=1, CTRL=2, SHIFT=4, WIN=8
MODIFIERS = {1: MOD1_MASK, 2: CONTROL_MASK, 4: SHIFT_MASK, 8: MOD4_MASK}
RELEVANT_MASK = SHIFT_MASK | CONTROL_MASK | MOD1_MASK | MOD4_MASK
# Grab each key also with Caps Lock and Num Lock, otherwise it fails while they are on.
LOCK_VARIANTS = (0, LOCK_MASK, MOD2_MASK, LOCK_MASK | MOD2_MASK)
XK_F1 = 0xFFBE
KEY_PRESS, KEY_RELEASE = 2, 3
GRAB_MODE_ASYNC = 1
SHAPE_INPUT, SHAPE_SET, UNSORTED = 2, 0, 0
BAD_ACCESS = 10
QUIT_ACTION = 3  # HUD_HOTKEYS id of "Overlay beenden"


def x_modifiers(flags):
    mask = 0
    for flag, x_mask in MODIFIERS.items():
        if flags & flag:
            mask |= x_mask
    return mask


def x_keysym(virtual_key):
    """Translate the Win32 virtual-key codes produced by poe2_hotkeys into X11 keysyms."""
    if 0x70 <= virtual_key <= 0x87:  # F1-F24
        return XK_F1 + virtual_key - 0x70
    if 0x30 <= virtual_key <= 0x39:  # 0-9
        return virtual_key
    if 0x41 <= virtual_key <= 0x5A:  # A-Z, X11 keysyms of the unshifted letters
        return virtual_key + 0x20
    raise ValueError(f"Keine X11-Taste für {virtual_key:#x}")


def overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def monitor_for(monitors, *, rect=None, point=None):
    """Monitor (left, top, right, bottom) that holds the point or overlaps the rectangle most."""
    if not monitors:
        return None
    if point is not None:
        x, y = point
        for monitor in monitors:
            if monitor[0] <= x < monitor[2] and monitor[1] <= y < monitor[3]:
                return monitor
        rect = (x, y, x + 1, y + 1)
    if rect is not None:
        best = max(monitors, key=lambda monitor: overlap(monitor, rect))
        if overlap(best, rect):
            return best
        # Off-screen: like MONITOR_DEFAULTTONEAREST, take the closest monitor.
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        return min(monitors, key=lambda m: (max(m[0] - cx, 0, cx - m[2]) ** 2 + max(m[1] - cy, 0, cy - m[3]) ** 2))
    return monitors[0]


def clip(monitor, work):
    if work is None:
        return monitor
    area = max(monitor[0], work[0]), max(monitor[1], work[1]), min(monitor[2], work[2]), min(monitor[3], work[3])
    return area if area[0] < area[2] and area[1] < area[3] else monitor


def loopback_listeners(tcp_table, inodes):
    """Ports of /proc/net/tcp sockets listening on 127.0.0.1 and owned by the given inodes."""
    ports = []
    for line in tcp_table.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[3] != "0A":  # TCP_LISTEN
            continue
        address, _, port = fields[1].partition(":")
        if address == "0100007F" and fields[9] in inodes:
            ports.append(int(port, 16))
    return ports


def socket_inodes(pid):
    inodes = set()
    try:
        for entry in os.scandir(f"/proc/{pid}/fd"):
            try:
                target = os.readlink(entry.path)
            except OSError:
                continue
            if target.startswith("socket:["):
                inodes.add(target[8:-1])
    except OSError:
        pass
    return inodes


def runtime_dir():
    return Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())


class XRectangle(c.Structure):
    _fields_ = [("x", c.c_short), ("y", c.c_short), ("width", c.c_ushort), ("height", c.c_ushort)]


class XKeyEvent(c.Structure):
    _fields_ = [
        ("type", c.c_int), ("serial", c.c_ulong), ("send_event", c.c_int), ("display", c.c_void_p),
        ("window", c.c_ulong), ("root", c.c_ulong), ("subwindow", c.c_ulong), ("time", c.c_ulong),
        ("x", c.c_int), ("y", c.c_int), ("x_root", c.c_int), ("y_root", c.c_int),
        ("state", c.c_uint), ("keycode", c.c_uint), ("same_screen", c.c_int),
    ]


class XEvent(c.Union):
    _fields_ = [("type", c.c_int), ("xkey", XKeyEvent), ("pad", c.c_long * 24)]


class XErrorEvent(c.Structure):
    _fields_ = [
        ("type", c.c_int), ("display", c.c_void_p), ("resourceid", c.c_ulong), ("serial", c.c_ulong),
        ("error_code", c.c_ubyte), ("request_code", c.c_ubyte), ("minor_code", c.c_ubyte),
    ]


class XRRMonitorInfo(c.Structure):
    _fields_ = [
        ("name", c.c_ulong), ("primary", c.c_int), ("automatic", c.c_int), ("noutput", c.c_int),
        ("x", c.c_int), ("y", c.c_int), ("width", c.c_int), ("height", c.c_int),
        ("mwidth", c.c_int), ("mheight", c.c_int), ("outputs", c.c_void_p),
    ]


class XVisualInfo(c.Structure):
    _fields_ = [
        ("visual", c.c_void_p), ("visualid", c.c_ulong), ("screen", c.c_int), ("depth", c.c_int),
        ("klass", c.c_int), ("red_mask", c.c_ulong), ("green_mask", c.c_ulong), ("blue_mask", c.c_ulong),
        ("colormap_size", c.c_int), ("bits_per_rgb", c.c_int),
    ]


class XSetWindowAttributes(c.Structure):
    _fields_ = [
        ("background_pixmap", c.c_ulong), ("background_pixel", c.c_ulong), ("border_pixmap", c.c_ulong),
        ("border_pixel", c.c_ulong), ("bit_gravity", c.c_int), ("win_gravity", c.c_int),
        ("backing_store", c.c_int), ("backing_planes", c.c_ulong), ("backing_pixel", c.c_ulong),
        ("save_under", c.c_int), ("event_mask", c.c_long), ("do_not_propagate_mask", c.c_long),
        ("override_redirect", c.c_int), ("colormap", c.c_ulong), ("cursor", c.c_ulong),
    ]


class XImage(c.Structure):
    _fields_ = [
        ("width", c.c_int), ("height", c.c_int), ("xoffset", c.c_int), ("format", c.c_int),
        ("data", c.c_void_p), ("byte_order", c.c_int), ("bitmap_unit", c.c_int),
        ("bitmap_bit_order", c.c_int), ("bitmap_pad", c.c_int), ("depth", c.c_int),
        ("bytes_per_line", c.c_int), ("bits_per_pixel", c.c_int), ("red_mask", c.c_ulong),
        ("green_mask", c.c_ulong), ("blue_mask", c.c_ulong), ("obdata", c.c_void_p),
        ("funcs", c.c_void_p * 6),  # create, destroy, get_pixel, put_pixel, sub_image, add_pixel
    ]


IMAGE_DESTROY = c.CFUNCTYPE(c.c_int, c.POINTER(XImage))
ZPIXMAP, TRUE_COLOR, ALL_PLANES = 2, 4, 0xFFFFFFFF
CW_BACK_PIXEL, CW_BORDER_PIXEL, CW_OVERRIDE_REDIRECT, CW_COLORMAP = 1 << 1, 1 << 3, 1 << 9, 1 << 13
XA_CARDINAL = 6
MIRROR_HIDDEN_ALPHA = 1  # the Tk window stays mapped and clickable, but practically invisible


def _pixel(rgb, alpha, alpha_index):
    r, g, b = rgb
    return bytes((b, g, r, alpha)) if alpha_index == 3 else bytes((alpha, r, g, b))


def color_key_to_alpha(pixels, alpha_index, key=(1, 1, 1), translucent=None):
    """32-bit ZPixmap pixels of the HUD -> premultiplied ARGB.

    The key colour (TRANSPARENT #010101) becomes fully transparent. `translucent` maps further
    key colours {(r, g, b): ((r, g, b), alpha)} to a colour with partial alpha, e.g. half-
    transparent menu bars and cards. alpha_index is 3 for LSBFirst (B, G, R, X) and 0 for
    MSBFirst (X, R, G, B). Key colours never contain 0xFF, so every match contains exactly one
    alpha byte and stays pixel-aligned.
    """
    data = bytearray(pixels)
    data[alpha_index::4] = b"\xff" * (len(data) // 4)
    data = data.replace(_pixel(key, 255, alpha_index), b"\x00\x00\x00\x00")
    for source, (color, alpha) in (translucent or {}).items():
        premultiplied = tuple(channel * alpha // 255 for channel in color)
        data = data.replace(_pixel(source, 255, alpha_index), _pixel(premultiplied, alpha, alpha_index))
    return data


ERROR_HANDLER = c.CFUNCTYPE(c.c_int, c.c_void_p, c.POINTER(XErrorEvent))


def _bind(library, name, result, *args):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = args
    return function


def _library(name, required=True):
    path = ctypes.util.find_library(name)
    if not path:
        if required:
            raise OSError(f"lib{name} nicht gefunden")
        return None
    return c.CDLL(path)


def register_private_fonts(paths) -> None:
    fontconfig = _library("fontconfig", required=False)
    if fontconfig is None:
        return
    current_config = _bind(fontconfig, "FcConfigGetCurrent", c.c_void_p)
    add_font = _bind(fontconfig, "FcConfigAppFontAddFile", c.c_int, c.c_void_p, c.c_char_p)
    config = current_config()
    if config:
        for path in paths:
            if not add_font(config, os.fsencode(path.resolve())):
                logging.warning("Schrift konnte nicht geladen werden: %s", path.name)


class Xlib:
    """The few libX11, libXext and libXrandr calls the guide needs."""

    def __init__(self):
        x11 = _library("X11")
        p, ul, i, ui = c.c_void_p, c.c_ulong, c.c_int, c.c_uint
        self.init_threads = _bind(x11, "XInitThreads", i)
        self.open_display = _bind(x11, "XOpenDisplay", p, c.c_char_p)
        self.close_display = _bind(x11, "XCloseDisplay", i, p)
        self.default_root = _bind(x11, "XDefaultRootWindow", ul, p)
        self.default_screen = _bind(x11, "XDefaultScreen", i, p)
        self.display_width = _bind(x11, "XDisplayWidth", i, p, i)
        self.display_height = _bind(x11, "XDisplayHeight", i, p, i)
        self.keysym_to_keycode = _bind(x11, "XKeysymToKeycode", c.c_ubyte, p, ul)
        self.grab_key = _bind(x11, "XGrabKey", i, p, i, ui, ul, i, i, i)
        self.ungrab_key = _bind(x11, "XUngrabKey", i, p, i, ui, ul)
        self.pending = _bind(x11, "XPending", i, p)
        self.next_event = _bind(x11, "XNextEvent", i, p, c.POINTER(XEvent))
        self.sync = _bind(x11, "XSync", i, p, i)
        self.flush = _bind(x11, "XFlush", i, p)
        self.set_error_handler = _bind(x11, "XSetErrorHandler", p, ERROR_HANDLER)
        self.detectable_repeat = _bind(x11, "XkbSetDetectableAutoRepeat", i, p, i, c.POINTER(i))
        self.query_pointer = _bind(x11, "XQueryPointer", i, p, ul, c.POINTER(ul), c.POINTER(ul),
                                   c.POINTER(i), c.POINTER(i), c.POINTER(i), c.POINTER(i), c.POINTER(ui))
        self.intern_atom = _bind(x11, "XInternAtom", ul, p, c.c_char_p, i)
        self.get_property = _bind(x11, "XGetWindowProperty", i, p, ul, ul, c.c_long, c.c_long, i, ul,
                                  c.POINTER(ul), c.POINTER(i), c.POINTER(ul), c.POINTER(ul), c.POINTER(p))
        self.free = _bind(x11, "XFree", i, p)
        # ARGB mirror window (see LinuxOverlay.mirror_update)
        self.match_visual_info = _bind(x11, "XMatchVisualInfo", i, p, i, i, i, c.POINTER(XVisualInfo))
        self.create_colormap = _bind(x11, "XCreateColormap", ul, p, ul, p, i)
        self.create_window = _bind(x11, "XCreateWindow", ul, p, ul, i, i, ui, ui, ui, i, ui, p, ul,
                                   c.POINTER(XSetWindowAttributes))
        self.destroy_window = _bind(x11, "XDestroyWindow", i, p, ul)
        self.map_raised = _bind(x11, "XMapRaised", i, p, ul)
        self.unmap_window = _bind(x11, "XUnmapWindow", i, p, ul)
        self.raise_window = _bind(x11, "XRaiseWindow", i, p, ul)
        self.move_resize = _bind(x11, "XMoveResizeWindow", i, p, ul, i, i, ui, ui)
        self.create_gc = _bind(x11, "XCreateGC", p, p, ul, ul, p)
        self.free_gc = _bind(x11, "XFreeGC", i, p, p)
        self.get_image = _bind(x11, "XGetImage", c.POINTER(XImage), p, ul, i, i, ui, ui, ul, i)
        self.create_image = _bind(x11, "XCreateImage", c.POINTER(XImage), p, p, ui, i, i, c.c_char_p, ui, ui, i, i)
        self.put_image = _bind(x11, "XPutImage", i, p, ul, p, c.POINTER(XImage), i, i, i, i, ui, ui)
        self.change_property = _bind(x11, "XChangeProperty", i, p, ul, ul, ul, i, i, c.c_void_p, i)
        xext = _library("Xext", required=False)
        self.shape_rectangles = xext and _bind(xext, "XShapeCombineRectangles", None,
                                               p, ul, i, i, i, c.POINTER(XRectangle), i, i, i)
        self.shape_mask = xext and _bind(xext, "XShapeCombineMask", None, p, ul, i, i, i, ul, i)
        xrandr = _library("Xrandr", required=False)
        self.get_monitors = xrandr and _bind(xrandr, "XRRGetMonitors", c.POINTER(XRRMonitorInfo),
                                             p, ul, i, c.POINTER(i))
        self.free_monitors = xrandr and _bind(xrandr, "XRRFreeMonitors", None, c.POINTER(XRRMonitorInfo))


class LinuxOverlay:
    color_key = False  # X11 has no colour key for Tk windows: opaque HUD, input region instead

    def __init__(self, xlib=None):
        self.x = xlib or Xlib()
        self.x.init_threads()  # before any other Xlib call: Tk and the hotkey thread share Xlib
        self.errors = []
        self._error_handler = ERROR_HANDLER(self._x_error)
        self.x.set_error_handler(self._error_handler)
        self.display = self.x.open_display(None)
        if not self.display:
            raise OSError("X-Display nicht erreichbar (DISPLAY=%s)" % os.environ.get("DISPLAY", ""))
        self.root = self.x.default_root(self.display)
        self.stop = Event()
        self.worker = None
        self.queue = None
        self.extra_hotkeys = {}
        self.wheel_target = None
        self.lock = None
        uid = os.getuid() if hasattr(os, "getuid") else 0
        self.lock_path = runtime_dir() / f"poe2-companion-{uid}.lock"
        self.show_path = runtime_dir() / f"poe2-companion-{uid}.show"
        self._shape_warned = False
        self._argb = None  # XVisualInfo of a 32-bit ARGB visual, False if none
        self.mirrors = {}  # Tk window path -> ARGB mirror window state

    def _x_error(self, display, event):
        # Xlib's default handler would end the process, e.g. when another program owns a hotkey.
        self.errors.append((display, event.contents.error_code))
        return 0

    # Single instance ------------------------------------------------------------------

    def claim(self):
        import fcntl
        deadline = time.monotonic() + 4
        requested = set()
        while True:
            handle = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    os.close(handle)
                    raise
                pid = self._lock_owner(handle)
                os.close(handle)
                build = self._peer_build(pid)
                if build is not None and build >= BUILD:
                    self.show_path.touch()
                    return False
                if pid and build is not None and pid not in requested:
                    os.kill(pid, signal.SIGTERM)
                    logging.info("Vorherigen PoE2 Ingame Guide zum Schließen aufgefordert.")
                    requested.add(pid)
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Ein anderer Ingame Guide läuft noch. Beende ihn mit F10 und starte {BUILD_LABEL} erneut.")
                time.sleep(.08)
                continue
            os.ftruncate(handle, 0)
            os.write(handle, str(os.getpid()).encode())
            self.lock = handle
            self.show_path.unlink(missing_ok=True)
            signal.signal(signal.SIGTERM, self._terminate)
            return True

    @staticmethod
    def _lock_owner(handle):
        try:
            return int(os.pread(handle, 16, 0).decode().strip() or 0)
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _peer_build(pid):
        if not pid:
            return None
        try:
            table = Path("/proc/net/tcp").read_text()
        except OSError:
            return None
        builds = [build for port in loopback_listeners(table, socket_inodes(pid))
                  if (build := running_guide_build(port)) is not None]
        return max(builds, default=None)

    def _terminate(self, signum, frame):
        # A newer guide asks this one to close: take the regular F10 path in the Tk loop.
        if self.queue is not None:
            self.queue.put(QUIT_ACTION)
        else:
            raise SystemExit(0)

    def recovery_requested(self):
        try:
            self.show_path.unlink()
            return True
        except OSError:
            return False

    # Windows and monitors ---------------------------------------------------------------

    def hwnd(self, window):
        # The Tk toplevel itself serves as handle: geometry stays in Tk's hands.
        return window

    @staticmethod
    def _xid(window):
        window.update_idletasks()
        return int(window.wm_frame(), 16)

    def dpi_for_window(self, hwnd):
        scale = os.environ.get("POE2_SCALE", "")
        try:
            return round(96 * float(scale)) if scale else 0
        except ValueError:
            return 0

    def pointer(self):
        root, child = c.c_ulong(), c.c_ulong()
        x, y, wx, wy, mask = c.c_int(), c.c_int(), c.c_int(), c.c_int(), c.c_uint()
        if self.x.query_pointer(self.display, self.root, c.byref(root), c.byref(child),
                                c.byref(x), c.byref(y), c.byref(wx), c.byref(wy), c.byref(mask)):
            return x.value, y.value
        return None

    def _monitors(self):
        monitors = []
        if self.x.get_monitors:
            count = c.c_int()
            info = self.x.get_monitors(self.display, self.root, 1, c.byref(count))
            if info:
                try:
                    for index in range(count.value):
                        m = info[index]
                        monitors.append((m.x, m.y, m.x + m.width, m.y + m.height))
                finally:
                    self.x.free_monitors(info)
        if not monitors:
            screen = self.x.default_screen(self.display)
            monitors.append((0, 0, self.x.display_width(self.display, screen),
                             self.x.display_height(self.display, screen)))
        return monitors

    def _workarea(self):
        atom = self.x.intern_atom(self.display, b"_NET_WORKAREA", 1)
        if not atom:
            return None
        kind, fmt, count, after, data = c.c_ulong(), c.c_int(), c.c_ulong(), c.c_ulong(), c.c_void_p()
        status = self.x.get_property(self.display, self.root, atom, 0, 4, 0, 0, c.byref(kind), c.byref(fmt),
                                     c.byref(count), c.byref(after), c.byref(data))
        try:
            if status != 0 or fmt.value != 32 or count.value < 4 or not data:
                return None
            x, y, width, height = c.cast(data, c.POINTER(c.c_long))[:4]
            return x, y, x + width, y + height
        finally:
            if data:
                self.x.free(data)

    def work_area(self, *, rect=None, point=None, full_monitor=False):
        monitor = monitor_for(self._monitors(), rect=rect, point=point)
        if monitor is None or full_monitor:
            return monitor
        return clip(monitor, self._workarea())

    def display_bounds(self, window):
        x, y = window.winfo_rootx(), window.winfo_rooty()
        rect = (x, y, x + max(1, window.winfo_width()), y + max(1, window.winfo_height()))
        return monitor_for(self._monitors(), rect=rect)

    def positioned_at(self, hwnd):
        hwnd.update_idletasks()
        return hwnd.winfo_rootx(), hwnd.winfo_rooty(), hwnd.winfo_width(), hwnd.winfo_height()

    def place(self, hwnd, x, y, width, height):
        hwnd.geometry(f"{width}x{height}+{x}+{y}")

    def style_dialog(self, window, *, palette=None):
        """Window decorations belong to the desktop on Linux."""

    # Input --------------------------------------------------------------------------------

    def _shape(self, xid, kind, rectangles):
        if not self.x.shape_rectangles:
            if not self._shape_warned:
                logging.warning("libXext fehlt: Spielmodus ohne Klickdurchlässigkeit.")
                self._shape_warned = True
            return
        if rectangles is None:
            self.x.shape_mask(self.display, xid, kind, 0, 0, 0, SHAPE_SET)
        else:
            boxes = (XRectangle * max(1, len(rectangles)))()
            for box, (left, top, right, bottom) in zip(boxes, rectangles):
                box.x, box.y = max(-32768, left), max(-32768, top)
                box.width, box.height = max(0, right - left), max(0, bottom - top)
            self.x.shape_rectangles(self.display, xid, kind, 0, 0, boxes, len(rectangles), SHAPE_SET, UNSORTED)
        self.x.flush(self.display)

    def set_input_region(self, window, rectangles):
        """Mouse input only inside the rectangles (window coordinates); None: whole window."""
        self._shape(self._xid(window), SHAPE_INPUT, rectangles)

    def set_click_mode(self, window, enabled, *, no_activate=False, alpha=255, owner=None):
        self.set_opacity(window, alpha)
        # Play mode starts without input; the guide's InputRegion then adds its buttons.
        self.set_input_region(window, () if enabled else None)

    def set_opacity(self, window, alpha):
        mirror = self.mirrors.get(str(window))
        if mirror is not None:
            # The visible picture is the mirror; the Tk window stays practically invisible.
            self._mirror_opacity(mirror, alpha)
            alpha = MIRROR_HIDDEN_ALPHA
        window.attributes("-alpha", alpha / 255)

    # See-through background under XWayland -------------------------------------------------
    #
    # Tk windows have no alpha channel and XWayland ignores window shapes for drawing. Like
    # Electron apps (e.g. Exiled Exchange), the guide therefore shows its picture in an X11
    # window with a 32-bit ARGB visual: the Tk window keeps position, input region and hotkeys
    # but is practically invisible; the mirror above it takes no input and shows the Tk picture
    # with the TRANSPARENT colour (#010101) as alpha 0, like the colour key on Windows.

    @property
    def transparent_background(self):
        """True when a 32-bit ARGB visual and the Shape extension (input pass-through) exist."""
        if self._argb is None:
            info = XVisualInfo()
            screen = self.x.default_screen(self.display)
            found = self.x.match_visual_info(self.display, screen, 32, TRUE_COLOR, c.byref(info))
            self._argb = info if found and info.visual else False
        return bool(self._argb) and bool(self.x.shape_rectangles)

    def _mirror_opacity(self, mirror, alpha):
        if mirror["alpha"] == alpha:
            return
        value = (c.c_ulong * 1)(min(0xFFFFFFFF, round(alpha / 255 * 0xFFFFFFFF)))
        atom = self.x.intern_atom(self.display, b"_NET_WM_WINDOW_OPACITY", 0)
        self.x.change_property(self.display, mirror["window"], atom, XA_CARDINAL, 32, 0, value, 1)
        mirror["alpha"] = alpha

    def _create_mirror(self):
        if not self.transparent_background:
            raise OSError("Kein 32-Bit-ARGB-Visual oder keine Shape-Erweiterung verfügbar.")
        visual = self._argb.visual
        attributes = XSetWindowAttributes()
        attributes.colormap = self.x.create_colormap(self.display, self.root, visual, 0)
        attributes.background_pixel = 0
        attributes.border_pixel = 0
        attributes.override_redirect = 1
        mask = CW_BACK_PIXEL | CW_BORDER_PIXEL | CW_OVERRIDE_REDIRECT | CW_COLORMAP
        window = self.x.create_window(self.display, self.root, 0, 0, 1, 1, 0, 32, 1, visual, mask,
                                      c.byref(attributes))
        if not window:
            raise OSError("ARGB-Fenster konnte nicht angelegt werden.")
        self._shape(window, SHAPE_INPUT, ())  # every click goes through to the Tk window or the game
        gc = self.x.create_gc(self.display, window, 0, None)
        return {"window": window, "gc": gc, "geometry": None, "mapped": False, "alpha": None, "picture": None}

    def mirror_update(self, window, alpha=255, translucent=None):
        """Copy the Tk window's current picture into its ARGB mirror. Returns False if not possible.

        translucent: {(r, g, b) of a key colour: ((r, g, b), alpha 0-255)} for half-transparent areas.
        """
        key = str(window)
        mirror = self.mirrors.get(key)
        if mirror is None:
            mirror = self.mirrors[key] = self._create_mirror()
            window.attributes("-alpha", MIRROR_HIDDEN_ALPHA / 255)
        self._mirror_opacity(mirror, alpha)
        window.update_idletasks()
        geometry = window.winfo_rootx(), window.winfo_rooty(), window.winfo_width(), window.winfo_height()
        if geometry[2] < 2 or geometry[3] < 2:
            return False
        translucent = dict(translucent or {})
        if geometry != mirror["geometry"] or translucent != mirror.get("translucent"):
            if geometry != mirror["geometry"]:
                self.x.move_resize(self.display, mirror["window"], *geometry)
                # XWayland may only pick up the input region of a mapped, current-size surface.
                self._shape(mirror["window"], SHAPE_INPUT, ())
            mirror["geometry"] = geometry
            mirror["translucent"] = translucent
            mirror["picture"] = None
        before = len(self.errors)
        image = self.x.get_image(self.display, self._xid(window), 0, 0, geometry[2], geometry[3], ALL_PLANES, ZPIXMAP)
        if not image or len(self.errors) > before:
            return False
        try:
            source = image.contents
            if source.bits_per_pixel != 32:
                raise OSError(f"Nicht unterstütztes Pixelformat: {source.bits_per_pixel} Bit")
            stride = source.bytes_per_line
            pixels = c.string_at(source.data, stride * source.height)
            alpha_index = 3 if source.byte_order == 0 else 0
        finally:
            IMAGE_DESTROY(image.contents.funcs[1])(image)
        if pixels != mirror["picture"]:
            mirror["picture"] = pixels
            argb = color_key_to_alpha(pixels, alpha_index, translucent=translucent)
            buffer = (c.c_char * len(argb)).from_buffer(argb)
            target = self.x.create_image(self.display, self._argb.visual, 32, ZPIXMAP, 0, buffer,
                                         geometry[2], geometry[3], 32, stride)
            if not target:
                return False
            try:
                self.x.put_image(self.display, mirror["window"], mirror["gc"], target, 0, 0, 0, 0,
                                 geometry[2], geometry[3])
            finally:
                target.contents.data = None  # Python owns the pixels
                IMAGE_DESTROY(target.contents.funcs[1])(target)
        if not mirror["mapped"]:
            self.x.map_raised(self.display, mirror["window"])
            mirror["mapped"] = True
            # Set the click-through again once the surface exists: XWayland may ignore an input
            # region set before mapping, then the mirror would swallow clicks now and then.
            self.x.sync(self.display, 0)
            self._shape(mirror["window"], SHAPE_INPUT, ())
        self.x.flush(self.display)
        return True

    def mirror_hide(self, window):
        mirror = self.mirrors.get(str(window))
        if mirror is not None and mirror["mapped"]:
            self.x.unmap_window(self.display, mirror["window"])
            mirror["mapped"] = False
            self.x.flush(self.display)

    def mirror_close(self, window, alpha=None):
        """Remove the mirror; the Tk window becomes visible again (alpha 0–255 or unchanged)."""
        mirror = self.mirrors.pop(str(window), None)
        if mirror is None or not self.display:
            return
        self.x.free_gc(self.display, mirror["gc"])
        self.x.destroy_window(self.display, mirror["window"])
        self.x.flush(self.display)
        if alpha is not None:
            try:
                window.attributes("-alpha", alpha / 255)
            except Exception:
                pass

    def stack_below(self, window, target, rect):
        self.place(window, *rect)
        window.lower(target)

    def set_wheel_target(self, owner, rect, exclude=None):
        # Wheel forwarding in play mode is not available on X11 yet; F9 enables scrolling.
        self.wheel_target = (owner, rect, exclude) if rect is not None else None

    # Global hotkeys -----------------------------------------------------------------------

    def start_hotkeys(self, queue):
        self.queue = queue
        self.worker = Thread(target=self._hotkeys, args=(queue,), daemon=True)
        self.worker.start()

    def configure_hotkeys(self, bindings):
        self.extra_hotkeys = dict(bindings)

    def _grab(self, display, root, bindings):
        grabbed = {}
        for ident, (flags, virtual_key) in bindings.items():
            try:
                keysym = x_keysym(virtual_key)
            except ValueError as error:
                logging.warning("Hotkey %s: %s", ident, error)
                continue
            keycode = self.x.keysym_to_keycode(display, keysym)
            if not keycode:
                logging.warning("Hotkey %s hat auf dieser Tastatur keine Taste.", ident)
                continue
            mask = x_modifiers(flags)
            before = len(self.errors)
            for extra in LOCK_VARIANTS:
                self.x.grab_key(display, keycode, mask | extra, root, 1, GRAB_MODE_ASYNC, GRAB_MODE_ASYNC)
            self.x.sync(display, 0)
            if any(code == BAD_ACCESS for owner, code in self.errors[before:] if owner == display):
                logging.warning("Hotkey %s ist bereits von einem anderen Programm belegt.", ident)
            grabbed[ident] = keycode, mask
        return grabbed

    def _ungrab(self, display, root, grabbed):
        for keycode, mask in grabbed.values():
            for extra in LOCK_VARIANTS:
                self.x.ungrab_key(display, keycode, mask | extra, root)
        self.x.sync(display, 0)

    @staticmethod
    def _key_event(queue, grabbed, held, kind, keycode, state):
        if kind == KEY_RELEASE:
            # Modifiers may already be up when the key is released: match the key alone.
            held.difference_update(ident for ident, (code, _) in grabbed.items() if code == keycode)
            return
        for ident, binding in grabbed.items():
            if binding == (keycode, state & RELEVANT_MASK) and ident not in held:
                held.add(ident)
                queue.put(ident)

    def _hotkeys(self, queue):
        display = self.x.open_display(None)
        if not display:
            logging.warning("Globale Hotkeys nicht verfügbar: keine zweite X-Verbindung.")
            return
        root = self.x.default_root(display)
        supported = c.c_int()
        self.x.detectable_repeat(display, 1, c.byref(supported))  # held keys: one press, one release
        bindings, grabbed, held = None, {}, set()
        event = XEvent()
        try:
            while not self.stop.is_set():
                wanted = self.extra_hotkeys
                if wanted != bindings:
                    self._ungrab(display, root, grabbed)
                    grabbed, held, bindings = self._grab(display, root, wanted), set(), wanted
                while self.x.pending(display):
                    self.x.next_event(display, c.byref(event))
                    if event.type not in (KEY_PRESS, KEY_RELEASE):
                        continue
                    self._key_event(queue, grabbed, held, event.type, event.xkey.keycode, event.xkey.state)
                self.stop.wait(.02)
        finally:
            self._ungrab(display, root, grabbed)
            self.x.close_display(display)

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=.3)
        for mirror in self.mirrors.values():
            if self.display:
                self.x.destroy_window(self.display, mirror["window"])
        self.mirrors.clear()
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.display:
            self.x.close_display(self.display)
            self.display = None
