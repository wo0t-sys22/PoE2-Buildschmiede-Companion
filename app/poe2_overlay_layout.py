"""Persistent window geometry and per-monitor typography."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tkinter import font as tkfont


HUD_SIZE = (432, 368)
HUD_MIN_SIZE = (340, 275)


class OverlayLayout:
    def __init__(self, window, directory: Path, native=None):
        self.window = window
        self.path = directory / "poe2_overlay_window.json"
        self.native = native
        self.fonts = {}
        self.gesture = None
        self.scale = 100
        self.dpi = 96
        self.x, self.y = 26, 26
        self.width, self.height = HUD_SIZE
        self.has_geometry = False
        self.collapsed_height = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for key in ("x", "y", "width", "height", "scale"):
                    if type(saved.get(key)) is int:
                        setattr(self, key, saved[key])
                self.has_geometry = all(type(saved.get(key)) is int for key in ("x", "y", "width", "height"))
        except (OSError, ValueError):
            pass
        self.scale = min(160, max(80, self.scale))

    def px(self, length):
        return max(1, round(length * self.dpi / 96))

    def font(self, family, points, weight="normal"):
        key = (family, points, weight)
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(
                root=self.window, family=family, size=self._font_pixels(points), weight=weight,
            )
        return self.fonts[key]

    def _font_pixels(self, points):
        return -max(8, round(points * self.dpi / 72 * self.scale / 100))

    def sync_dpi(self):
        dpi = self.native.dpi_for_window(self.native.hwnd(self.window)) if self.native else 0
        if not dpi:
            dpi = round(self.window.winfo_fpixels("1i"))
        if dpi <= 0 or dpi == self.dpi:
            return False
        self.dpi = dpi
        self._resize_fonts()
        return True

    def _resize_fonts(self):
        for (_, points, _), font in self.fonts.items():
            font.configure(size=self._font_pixels(points))

    def restore(self):
        self.window.update_idletasks()
        if self.has_geometry:
            self.place(self.x, self.y, self.width, self.height)
            self.sync_dpi()
            return

        self.sync_dpi()
        point = self.native.pointer() if self.native else None
        work = self.native.work_area(point=point or (0, 0)) if self.native else None
        left, top, right, bottom = work or self._screen()
        width, height = HUD_SIZE
        for _ in range(2):
            w = min(self.px(width), self._width_limit(left, right))
            h = min(self.px(height), round((bottom - top) * .63))
            x, y = (left + right - w) // 2, (top + bottom - h) // 2
            self.place(x, y, w, h)
            if not self.sync_dpi():
                break
        self.has_geometry = True

    def _screen(self):
        return 0, 0, self.window.winfo_screenwidth(), self.window.winfo_screenheight()

    def _work_area(self, x, y, width, height):
        rect = (x, y, x + max(1, width), y + max(1, height))
        work = (self.native.work_area(rect=rect) if self.native else None) or self._screen()
        display = self.native.work_area(rect=rect, full_monitor=True) if self.native else None
        # Allow the HUD to meet the physical left edge even with a docked taskbar.
        return (display[0], *work[1:]) if display else work

    @staticmethod
    def _width_limit(left, right):
        return max(1, (right - left) // 5)

    def height_limit(self, rect):
        display = self.native.work_area(rect=rect, full_monitor=True) if self.native else None
        _, top, _, bottom = display or self._screen()
        return max(1, round((bottom - top) * 1500 / 2160))

    def place(self, x, y, width, height):
        left, top, right, bottom = self._work_area(x, y, width, height)
        min_width, min_height = HUD_MIN_SIZE
        self.width = min(max(width, self.px(min_width * self.scale / 100)), self._width_limit(left, right))
        self.height = min(max(height, self.px(min_height * self.scale / 100)), bottom - top,
                          self.height_limit((x, y, x + width, y + height)))
        if self.collapsed_height is not None:
            self.height = min(self.collapsed_height, bottom - top)
        self.x = min(max(x, left), right - self.width)
        self.y = min(max(y, top), bottom - self.height)
        if self.native:
            self.native.place(self.native.hwnd(self.window), self.x, self.y, self.width, self.height)
        else:
            self.window.geometry(f"{self.width}x{self.height}+{self.x}+{self.y}")

    def enforce_width(self):
        if self.native:
            rect = self.native.positioned_at(self.native.hwnd(self.window))
        else:
            rect = (self.window.winfo_rootx(), self.window.winfo_rooty(),
                    self.window.winfo_width(), self.window.winfo_height())
        if rect:
            x, y, width, height = rect
            left, _, right, _ = self._work_area(x, y, width, height)
            if width > self._width_limit(left, right):
                self.place(x, y, width, height)

    def pointer(self, event):
        return (self.native.pointer() if self.native else None) or (event.x_root, event.y_root)

    def begin(self, operation, event):
        if self.native:
            rect = self.native.positioned_at(self.native.hwnd(self.window))
            if rect:
                self.x, self.y, self.width, self.height = rect
        self.gesture = operation, self.pointer(event), (self.x, self.y, self.width, self.height)

    def move(self, event):
        if not self.gesture:
            return
        operation, (start_x, start_y), (x, y, width, height) = self.gesture
        pointer_x, pointer_y = self.pointer(event)
        dx, dy = pointer_x - start_x, pointer_y - start_y
        if operation == "resize":
            self.place(x, y, width + dx, height + dy)
        else:
            self.place(x + dx, y + dy, width, height)

    def finish(self):
        if self.gesture:
            self.gesture = None
            self.save()

    def zoom(self, step):
        current = self.scale
        self.scale = min(160, max(80, self.scale + step))
        if self.scale != current:
            self._resize_fonts()
            self.place(self.x, self.y, self.width, self.height)
            self.save()

    def save(self):
        geometry = {key: getattr(self, key) for key in ("x", "y", "width", "height", "scale")}
        if self.collapsed_height is not None:
            geometry["height"] = self.expanded_height
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            logging.exception("Fensterposition konnte nicht gespeichert werden.")
