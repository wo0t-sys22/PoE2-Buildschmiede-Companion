"""Offline artwork shared by the build HUD and planner. Requires only Tcl/Tk."""

from collections import OrderedDict
from functools import lru_cache
import json
from pathlib import Path
import struct
import tkinter as tk
from zipfile import BadZipFile, ZipFile
import zlib

from poe2_hud_icons import hud_icon


PACK = Path(__file__).with_name("poe2_build_art.zip")
CURRENCY_PACK = PACK.with_name("poe2_currency_art.zip")
_CACHE_LIMIT = 256


@lru_cache(maxsize=1)
def _pack():
    # Opening a ZIP rereads its entire directory. Keep one read-only handle for
    # the process so drawing a viewport costs only the visible images.
    return _read_pack(PACK)


@lru_cache(maxsize=1)
def _currency_pack():
    if not CURRENCY_PACK.is_file():
        return None, {"refs": {}}
    return _read_pack(CURRENCY_PACK)


def _read_pack(path):
    archive = ZipFile(path)
    try:
        return archive, json.loads(archive.read("art-index.json"))
    except Exception:
        archive.close()
        raise


def item_art_ref(name, base=""):
    """Resolve either a unique item or its base, in English or German."""
    try:
        index = _pack()[1]["items"]
    except (BadZipFile, OSError, KeyError, ValueError):
        return ""
    return next((index[key] for value in (name, base) if isinstance(value, str)
                 and (key := value.strip().casefold()) in index), "")


@lru_cache(maxsize=128)
def _pixels(key):
    name = "rgba/" + key
    archive = _pack()[0]
    if name not in archive.NameToInfo:
        archive = _currency_pack()[0]
        if archive is None:
            raise KeyError(name)
    data = archive.read(name)
    count = data[0]
    sizes = struct.unpack_from(f">{count}H", data, 1)
    offset = 1 + 2 * count
    has_alpha = data[offset]
    palette_start = offset + 1
    index_start = palette_start + 768
    pixel_count = sum(size * size for size in sizes)
    alpha_start = index_start + pixel_count
    if not sizes or len(data) != alpha_start + (pixel_count if has_alpha else 0):
        raise ValueError("Invalid build artwork")
    indices = data[index_start:alpha_start]
    rgba = bytearray(pixel_count * 4)
    for channel in range(3):
        table = palette_start + channel * 256
        rgba[channel::4] = indices.translate(data[table:table+256])
    rgba[3::4] = data[alpha_start:] if has_alpha else b"\xff" * pixel_count
    view = memoryview(rgba)
    offset = 0
    images = {}
    for size in sizes:
        end = offset + 4 * size * size
        images[size] = view[offset:end]
        offset = end
    return images


def _positions(source, target):
    # Half-pixel mapping aligns image centres, including on odd UI scales.
    coordinates = [min(source - 1, max(0, (i + .5) * source / target - .5)) for i in range(target)]
    return [(int(pos), min(source - 1, int(pos) + 1), round(256 * (pos - int(pos)))) for pos in coordinates]


def _resize(pixels, source, target):
    """Bilinear interpolation with premultiplied alpha, from a filtered mip."""
    xy = _positions(source, target)
    result = bytearray(target * target * 4)
    dest = 0
    for y0, y1, fy in xy:
        top, bottom = y0 * source * 4, y1 * source * 4
        for x0, x1, fx in xy:
            a, b, c, d = top + 4*x0, top + 4*x1, bottom + 4*x0, bottom + 4*x1
            wa = (256-fx) * (256-fy) * pixels[a+3]
            wb = fx * (256-fy) * pixels[b+3]
            wc = (256-fx) * fy * pixels[c+3]
            wd = fx * fy * pixels[d+3]
            alpha = wa + wb + wc + wd
            if alpha:
                for k in range(3):
                    result[dest+k] = (wa*pixels[a+k] + wb*pixels[b+k] + wc*pixels[c+k] + wd*pixels[d+k] + alpha//2) // alpha
                result[dest+3] = (alpha + 32768) >> 16
            dest += 4
    return result


def _png(pixels, size):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))

    stride = size * 4
    rows = b"".join(b"\0" + pixels[n:n+stride] for n in range(0, len(pixels), stride))
    header = struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b"")


def build_icon(master, ref, size=32):
    """Return a filtered square PhotoImage; unknown art stays optional."""
    if not ref or not isinstance(ref, str):
        return None
    try:
        key = _pack()[1]["refs"].get(ref)
        if not key and ref.startswith("currency/"):
            key = _currency_pack()[1]["refs"].get(ref)
    except (BadZipFile, KeyError, OSError, ValueError):
        return None
    if not key:
        return None
    limit = 224 if ref.startswith("art/tree/") else 108
    size = max(1, min(limit, int(size)))
    root = master._root()
    cache = getattr(root, "_poe2_build_icon_cache", None)
    if cache is None:
        root._poe2_build_icon_cache = cache = OrderedDict()
    entry = key, size
    if entry not in cache:
        try:
            images = _pixels(key)
            source = next((k for k in images if k >= size), max(images))
            pixels = images[source] if source == size else _resize(images[source], source, size)
            cache[entry] = tk.PhotoImage(master=root, data=_png(pixels, size), format="png")
        except (tk.TclError, OSError, BadZipFile, KeyError, ValueError, struct.error):
            return None
        if len(cache) > _CACHE_LIMIT:
            cache.popitem(last=False)
    cache.move_to_end(entry)
    return cache[entry]


def gem_icon(master, ref, size, *, empty=False):
    """Keep gems aligned with unambiguous line symbols for missing art or free sockets."""
    if ref and not empty:
        image = build_icon(master, ref, size)
        if image is not None:
            return image
    root = master._root()
    placeholders = getattr(root, "_poe2_gem_placeholders", None)
    if placeholders is None:
        root._poe2_gem_placeholders = placeholders = {}
    key = ("empty_socket" if empty else "gem", max(1, min(108, int(size))))
    if key not in placeholders:
        placeholders[key] = hud_icon(root, *key, "#79818a")
    return placeholders[key]
