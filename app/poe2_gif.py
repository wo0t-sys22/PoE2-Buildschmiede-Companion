"""Play the HUD's bundled GIFs using Tk for pixel decoding."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from struct import pack, unpack_from
from time import perf_counter
import tkinter as tk


@dataclass(frozen=True)
class GifFrame:
    image: bytes
    bounds: tuple[int, int, int, int]
    delay: int
    disposal: int
    transparent: bool


def _sub_blocks_end(data, offset):
    while offset < len(data):
        count = data[offset]
        offset += count + 1
        if not count:
            return offset
    raise ValueError("Incomplete GIF data")


def _palette_size(flags):
    return 3 * (2 << (flags & 7)) if flags & 128 else 0


@lru_cache(maxsize=8)
def load_gif(path: Path):
    data = path.read_bytes()
    if len(data) < 14 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("Invalid GIF header")
    width, height = unpack_from("<HH", data, 6)
    palette_end = 13 + _palette_size(data[10])
    color_offset = 13 + data[11] * 3
    background = "#" + data[color_offset:color_offset + 3].hex() if color_offset + 3 <= palette_end else ""
    frames = []
    offset = palette_end
    control = b""
    while offset < len(data):
        marker = data[offset]
        if marker == 0x3b:
            if frames:
                return width, height, background, tuple(frames)
            break
        if marker == 0x21 and offset + 1 < len(data):
            end = _sub_blocks_end(data, offset + 2)
            if data[offset + 1] == 0xf9 and end - offset == 8:
                control = data[offset:end]
            offset = end
            continue
        if marker != 0x2c or offset + 10 >= len(data):
            break
        left, top, w, h = unpack_from("<HHHH", data, offset + 1)
        if not w or not h or left + w > width or top + h > height:
            raise ValueError("Invalid GIF frame dimensions")
        end = _sub_blocks_end(data, offset + 11 + _palette_size(data[offset + 9]))
        # Decode each rectangle independently, without rescanning earlier frames.
        image = (data[:6] + pack("<HH", w, h) + data[10:palette_end] + control
                 + b"\x2c\0\0\0\0" + data[offset + 5:end] + b"\x3b")
        delay = int.from_bytes(control[4:6], "little") * 10
        flags = control[3] if control else 0
        frames.append(GifFrame(image, (left, top, left + w, top + h),
                               max(20, delay) if delay else 100, (flags >> 2) & 7, bool(flags & 1)))
        offset, control = end, b""
    raise ValueError("Missing GIF frames or trailer")


def preview_size(width, height, available_width, *, max_zoom=1, max_stretch=1.0):
    """Fit the full frame, using whole-pixel zoom for magnification.

    max_stretch > 1 lets a clip grow smoothly to the available width, up to that factor.
    """
    zoom = min(max_zoom, available_width // width)
    if zoom >= 1 and not (max_stretch > zoom and available_width > width * zoom):
        return width * zoom, height * zoom
    target = min(available_width, int(width * max(max_stretch, zoom)))
    return target, max(1, round(height * target / width))


@lru_cache(maxsize=16)
def _shrink_samples(width, height, target_width, target_height):
    # Group neighboring pixels so small reductions can copy sections of a row.
    columns = []
    for column in range(target_width):
        x = column * width // target_width * 3
        if columns and columns[-1][1] == x:
            columns[-1] = columns[-1][0], x + 3
        else:
            columns.append((x, x + 3))
    rows = tuple(row * height // target_height * width * 3 for row in range(target_height))
    return tuple(columns), rows


class AnimatedGif(tk.Label):
    def __init__(self, parent, path, *, background, max_zoom=1, max_stretch=1.0):
        width, height, self.background, self.frames = load_gif(path)
        self.max_stretch = max_stretch
        self.path = path
        self.screen = tk.PhotoImage(master=parent, width=width, height=height)
        super().__init__(parent, bg=background, bd=0, highlightthickness=0, image=self.screen)
        self.preview = self.screen
        self.preview_dimensions = width, height
        self.max_zoom = max_zoom
        self.index = 0
        self.timer = None
        self.previous = None
        self._draw_frame()
        self.bind("<Map>", self._schedule)
        self.bind("<Unmap>", self._pause)
        self.bind("<Destroy>", self._pause)
        self.bind("<Configure>", self._fit)

    def _copy(self, target, source, *options):
        self.tk.call(target, "copy", source, *options)

    def _clear(self, frame, bounds):
        if self.background and not frame.transparent:
            self.screen.put(self.background, to=bounds)
        elif bounds == (0, 0, self.screen.width(), self.screen.height()):
            self.screen.blank()
        else:
            left, top, right, bottom = bounds
            empty = tk.PhotoImage(master=self, width=right - left, height=bottom - top)
            self._copy(self.screen, empty, "-to", left, top, "-compositingrule", "set")

    def _draw_frame(self):
        frame = self.frames[self.index]
        if self.index == 0:
            self._clear(frame, (0, 0, self.screen.width(), self.screen.height()))
        self.previous = self.screen.copy() if frame.disposal == 3 else None
        photo = tk.PhotoImage(master=self, data=frame.image, format="gif")
        self._copy(self.screen, photo, "-to", *frame.bounds[:2])
        self._update_preview()

    def _update_preview(self):
        if self.preview is self.screen:
            return
        width, height = self.screen.width(), self.screen.height()
        target_width, target_height = self.preview_dimensions
        if target_width > width and target_width % width == 0:
            zoom = target_width // width
            self._copy(self.preview, self.screen, "-zoom", zoom, zoom, "-compositingrule", "set")
            return
        ppm = self.tk.call(self.screen, "data", "-format", "ppm", "-background", self.cget("bg"))
        pixels = ppm[-width * height * 3:]
        columns, rows = _shrink_samples(width, height, target_width, target_height)
        shrunk = b"".join(pixels[row + left:row + right] for row in rows for left, right in columns)
        header = f"P6\n{target_width} {target_height}\n255\n".encode("ascii")
        self.preview.configure(data=header + shrunk, format="ppm")

    def _fit(self, event):
        original = self.screen.width(), self.screen.height()
        size = preview_size(*original, max(1, event.width), max_zoom=self.max_zoom, max_stretch=self.max_stretch)
        if size != self.preview_dimensions:
            self.preview_dimensions = size
            self.preview = self.screen if size == original else tk.PhotoImage(master=self)
            self._update_preview()
            self.configure(image=self.preview)

    def _schedule(self, event=None, *, render_ms=0):
        if self.timer is None and len(self.frames) > 1:
            delay = max(1, self.frames[self.index].delay - render_ms)
            self.timer = self.after(delay, self._advance)

    def _advance(self):
        self.timer = None
        if not self.winfo_viewable():
            # A child may map before its containing HUD window is shown.
            self.timer = self.after(150, self._advance)
            return
        started = perf_counter()
        frame = self.frames[self.index]
        if frame.disposal == 2:
            self._clear(frame, frame.bounds)
        elif self.previous:
            self._copy(self.screen, self.previous, "-compositingrule", "set")
        self.index = (self.index + 1) % len(self.frames)
        self._draw_frame()
        self._schedule(render_ms=round((perf_counter() - started) * 1000))

    def _pause(self, event=None):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
