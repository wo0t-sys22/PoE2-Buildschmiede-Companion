"""Overlay verified German passive records on the English, ID-based build catalogue."""

from collections import Counter
import gzip
import json
from pathlib import Path
import re


_LINK = re.compile(r"\[([^\[\]]+)\]")
_NUMBER = re.compile(r"(-?\d+(?:[.,]\d+)?)(\s*%)?")


def effect_numbers(lines):
    """Compare displayed rolls, including percentage units, across both languages."""
    text = _LINK.sub(lambda m: m[1].split("|")[-1], " ".join(lines))
    return Counter((amount.replace(",", "."), bool(percent)) for amount, percent in _NUMBER.findall(text))


def passive_records(data):
    for ident, row in data["nodes"].items():
        yield str(ident), row
    for position in data.get("plannerTree", {}).get("nodes", {}).values():
        for row in position.get("variants", {}).values():
            yield str(row["id"]), row
        for row in position.get("choices", ()):
            yield str(row["id"]), row


def apply_passive_de(data, supplement=None):
    if supplement is None:
        with gzip.open(Path(__file__).with_name("poe2_passive_de.json.gz"), "rt", encoding="utf-8") as stream:
            supplement = json.load(stream)
    for ident, row in passive_records(data):
        entry = supplement["nodes"].get(ident)
        if not entry or row.get("name") != entry["name"]:
            continue
        if entry.get("de"):
            previous = row.get("de")
            if previous and previous != entry["de"]:
                row["aliases"] = list(dict.fromkeys((*row.get("aliases", ()), previous)))
            row["de"] = entry["de"]
        stats = row.get("stats", [])
        for profile in entry.get("effects", ()):
            if stats == profile[0] and effect_numbers(stats) == effect_numbers(profile[1]):
                row["statsDe"] = profile[1]
                break
