"""Single place for operating-system decisions of the desktop guide.

The HUD talks to the operating system only through the object returned by
``create_native_overlay()``:

- ``plattform/windows.py``: ``WindowsOverlay`` (Win32).
- ``plattform/linux.py``: ``LinuxOverlay`` (X11, also XWayland under Wayland desktops).
- Any other system runs without a native backend (``None``): opaque HUD without click-through.

Backends set ``color_key``. Only a colour-key backend (Windows) can make the HUD
background see-through; the HUD then uses separate click-target and backdrop windows.
Without a colour key the HUD keeps an opaque background, and the backend limits mouse
input to the buttons through ``set_input_region``.

Further platform specific spots outside this package:
- ``server._steam_paths`` / ``server.find_client_log``: Steam and Proton locations of Client.txt.
- ``server.GuideServer``: socket reuse differs between Windows and other systems.
- ``Windows/`` and ``Linux/`` in the project folder: starters, release manifests and packaging.
"""

from __future__ import annotations

from functools import lru_cache
import logging
import os
from pathlib import Path
import sys
from typing import Protocol

IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
APP_USER_MODEL_ID = "Bildschmiede.PoE2Companion"


class NativeOverlay(Protocol):
    """Methods and attributes the HUD uses on the native backend."""

    color_key: bool  # True: TRANSPARENT pixels of the HUD are not drawn and let clicks through

    def claim(self) -> bool: ...  # single-instance handover, False: another guide takes over
    def close(self) -> None: ...
    def recovery_requested(self) -> bool: ...
    def hwnd(self, window): ...  # opaque handle, only passed back to this backend
    def dpi_for_window(self, hwnd) -> int: ...  # 0: let Tk decide
    def pointer(self) -> tuple[int, int] | None: ...
    def set_click_mode(self, window, enabled, *, no_activate=False, alpha=255) -> None: ...
    def set_input_region(self, window, rectangles) -> None: ...  # None: whole window takes input
    # Optional (Linux): transparent_background, mirror_update(window, alpha), mirror_hide(window)
    # and mirror_close(window, alpha) show the HUD see-through via an ARGB mirror window;
    # see poe2_overlay_controls.BackgroundMirror.
    def set_opacity(self, window, alpha) -> None: ...
    def stack_below(self, window, target, rect) -> None: ...
    def set_wheel_target(self, owner, rect, exclude=None) -> None: ...
    def start_hotkeys(self, queue) -> None: ...
    def configure_hotkeys(self, bindings) -> None: ...
    def style_dialog(self, window, *, palette=None) -> None: ...
    def display_bounds(self, window) -> tuple[int, int, int, int]: ...
    def work_area(self, *, rect=None, point=None, full_monitor=False): ...
    def positioned_at(self, hwnd): ...
    def place(self, hwnd, x, y, width, height) -> None: ...


def data_dir(base_dir: Path, installed: bool) -> Path:
    """User data folder: per-user app data for the installed build, otherwise next to the app."""
    if installed and IS_WINDOWS:
        return Path(os.environ["LOCALAPPDATA"]) / "Bildschmiede" / "PoE2-Companion"
    if installed:
        # Packaged Linux builds follow the XDG base directory convention.
        root = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        return Path(root) / "Bildschmiede" / "PoE2-Companion"
    return base_dir / "userdata"


def set_app_id() -> None:
    """Group the guide windows under its own taskbar icon."""
    if IS_WINDOWS:
        from ctypes import windll
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


@lru_cache(maxsize=None)
def register_bundled_fonts(folder: Path) -> None:
    """Make bundled fonts available to this process before Tk chooses its fonts."""
    paths = tuple(sorted(folder.glob("*.ttf")))
    if not paths:
        return
    if IS_WINDOWS:
        from plattform.windows import register_private_fonts
    elif IS_LINUX:
        from plattform.linux import register_private_fonts
    else:
        return
    try:
        register_private_fonts(paths)
    except OSError as error:
        logging.warning("Mitgelieferte Schriften konnten nicht geladen werden: %s", error)


def create_native_overlay() -> NativeOverlay | None:
    if IS_WINDOWS:
        from plattform.windows import WindowsOverlay
        return WindowsOverlay()
    if IS_LINUX and os.environ.get("DISPLAY"):
        from plattform.linux import LinuxOverlay
        try:
            return LinuxOverlay()
        except OSError as error:
            logging.warning("X11-Anbindung nicht verfügbar, HUD läuft ohne Klickdurchlässigkeit: %s", error)
    return None
