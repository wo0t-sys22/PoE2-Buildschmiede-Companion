"""Font-independent, scalable line icons for the native HUD."""

from base64 import b64encode
from functools import lru_cache
from math import ceil, cos, hypot, pi, sin
from struct import pack
from tkinter import PhotoImage
from zlib import compress, crc32


def ring(x, y, radius):
    return tuple((x + radius * cos(i * pi / 8), y + radius * sin(i * pi / 8)) for i in range(17))


SHAPES = {
    "inventory": (((5, 7), (12, 3), (19, 7), (19, 17), (12, 21), (5, 17), (5, 7)),
                  ((5, 7), (12, 11), (19, 7)), ((12, 11), (12, 21))),
    "gem": (((3, 9), (8, 4), (16, 4), (21, 9), (12, 21), (3, 9)),
            ((3, 9), (21, 9)), ((9, 9), (12, 20), (15, 9))),
    "empty_socket": (ring(12, 12, 7.5),),
    "save": (((4, 3), (16, 3), (20, 7), (20, 21), (4, 21), (4, 3)),
             ((8, 3), (8, 8), (15, 8), (15, 3)), ((8, 20), (8, 13), (16, 13), (16, 20))),
    "import": (((12, 2), (12, 14)), ((7, 9), (12, 14), (17, 9)),
               ((4, 14), (4, 20), (20, 20), (20, 14))),
    "quest": (
        ((5, 3), (19, 3), (19, 21), (5, 21), (5, 3)),
        ((9, 8), (15, 8)), ((9, 12), (15, 12)), ((9, 16), (13, 16)),
    ),
    "boss": (
        ((6, 18), (19, 5), (20, 4), (20, 8), (9, 19)),
        ((4, 20), (6, 18)), ((5, 15), (9, 19)),
        ((18, 18), (5, 5), (4, 4), (4, 8), (9, 13)),
        ((20, 20), (18, 18)), ((19, 15), (15, 19)),
    ),
    "build": (
        ((12, 7), (12, 11), (5, 15)), ((12, 11), (19, 15)),
        ((12, 3), (14, 5), (12, 7), (10, 5), (12, 3)),
        ((5, 15), (8, 18), (5, 21), (2, 18), (5, 15)),
        ((19, 15), (22, 18), (19, 21), (16, 18), (19, 15)),
    ),
    "lookup": (ring(10, 10, 6), ((14.5, 14.5), (20, 20))),
    "learn": (((2, 9), (12, 4), (22, 9), (12, 14), (2, 9)),
              ((6, 11), (6, 16), (12, 19), (18, 16), (18, 11)), ((22, 9), (22, 15))),
    "zoom_out": (ring(10, 10, 6), ((14.5, 14.5), (20, 20)), ((7, 10), (13, 10))),
    "zoom_in": (ring(10, 10, 6), ((14.5, 14.5), (20, 20)), ((7, 10), (13, 10)), ((10, 7), (10, 13))),
    "timer": (ring(12, 13, 7), ((9, 2), (15, 2)), ((12, 2), (12, 6)), ((18, 7), (20, 5)),
              ((12, 9), (12, 13), (15, 13))),
    "checklist": (
        ((5, 3), (19, 3), (19, 21), (5, 21), (5, 3)),
        ((8, 9), (9, 10), (12, 7)), ((14, 9), (16, 9)),
        ((8, 16), (9, 17), (12, 14)), ((14, 16), (16, 16)),
    ),
    "checklist_off": (
        ((5, 3), (19, 3), (19, 21), (5, 21), (5, 3)),
        ((8, 9), (10, 9)), ((13, 9), (16, 9)),
        ((8, 16), (10, 16)), ((13, 16), (16, 16)),
    ),
    "checkbox": (((4, 4), (20, 4), (20, 20), (4, 20), (4, 4)),),
    "checked": (((4, 4), (20, 4), (20, 20), (4, 20), (4, 4)), ((8, 12), (11, 15), (16, 9))),
    "settings": (
        ring(12, 12, 7), ring(12, 12, 3),
        *(((12 + 7 * cos(i * pi / 4), 12 + 7 * sin(i * pi / 4)),
           (12 + 9.5 * cos(i * pi / 4), 12 + 9.5 * sin(i * pi / 4))) for i in range(8)),
    ),
    "detailed": (
        ((4, 6), (4, 6)), ((9, 6), (20, 6)),
        ((4, 12), (4, 12)), ((9, 12), (20, 12)),
        ((4, 18), (4, 18)), ((9, 18), (20, 18)),
    ),
    "compact": (((4, 8), (20, 8)), ((4, 16), (14, 16))),
    "locked": (
        ((5, 10), (19, 10), (19, 21), (5, 21), (5, 10)),
        ((8, 10), (8, 6), (10, 3), (14, 3), (16, 6), (16, 10)), ((12, 14), (12, 17)),
    ),
    "unlocked": (
        ((5, 10), (19, 10), (19, 21), (5, 21), (5, 10)),
        ((8, 10), (8, 6), (10, 3), (14, 3), (16, 6)), ((12, 14), (12, 17)),
    ),
    "eye": (
        ((3, 12), (7, 8), (12, 6), (17, 8), (21, 12), (17, 16), (12, 18), (7, 16), (3, 12)),
        ring(12, 12, 2.5),
    ),
}


def _chunk(name, data):
    return pack(">I", len(data)) + name + data + pack(">I", crc32(name + data))


@lru_cache(maxsize=128)
def _alpha_mask(name, size):
    scale = size / 24
    toolbar = name in {"quest", "boss", "build", "lookup", "learn", "settings"}
    reach = max(0.75 if toolbar else 0.85, (1.02 if toolbar else 1.24) * scale) + 0.5
    alpha = bytearray(size * size)
    for shape in SHAPES[name]:
        for (x1, y1), (x2, y2) in zip(shape, shape[1:]):
            start_x, start_y = x1 * scale, y1 * scale
            dx, dy = (x2 - x1) * scale, (y2 - y1) * scale
            length = dx * dx + dy * dy or 1
            top = max(0, int(min(start_y, start_y + dy) - reach))
            bottom = min(size, ceil(max(start_y, start_y + dy) + reach))
            left = max(0, int(min(start_x, start_x + dx) - reach))
            right = min(size, ceil(max(start_x, start_x + dx) + reach))
            for row in range(top, bottom):
                for column in range(left, right):
                    offset_x, offset_y = column + 0.5 - start_x, row + 0.5 - start_y
                    fraction = max(0, min(1, (offset_x * dx + offset_y * dy) / length))
                    distance = hypot(offset_x - fraction * dx, offset_y - fraction * dy)
                    pixel = row * size + column
                    alpha[pixel] = max(alpha[pixel], round(255 * max(0, min(1, reach - distance))))
    return bytes(alpha)


@lru_cache(maxsize=128)
def _raster(name, size, color):
    rgb = bytes.fromhex(color.removeprefix("#"))
    alpha = _alpha_mask(name, size)
    pixels = bytearray()
    for row in range(0, len(alpha), size):
        pixels.append(0)
        for opacity in alpha[row:row + size]:
            pixels.extend((*rgb, opacity))
    header = pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", compress(pixels)) + _chunk(b"IEND", b"")
    return b64encode(png).decode("ascii")


def hud_icon(master, name, size, color):
    return PhotoImage(master=master, data=_raster(name, size, color), format="png")
