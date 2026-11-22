"""Offline Build Editor affix rules for catalogue gear and imported item text."""

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path
import re

from poe2_build_items import (NUMBERS, RANGE, RARITY_HEADER, STATUS, TAGS, _display_line, _gear_data, _items,
                              _parsed_source, _rolled, canonical_base, imported_runes, item_rarity)


LEVEL_LINE = re.compile(r"^(?:Item Level|Gegenstandsstufe):[ \t]*(\d+)[ \t]*(?=\r?$)", re.M | re.I)
QUALITY_LINE = re.compile(r"^[ \t]*(?:Quality|Qualität)(?: \([^)\r\n]+\))?:[ \t]*[+]?(\d{1,3})%?[ \t]*(?=\r?$)", re.M | re.I)
NUMBER = r"([+-]?\d+(?:\.\d+)?)"


@lru_cache(maxsize=1)
def _catalog():
    with gzip.open(Path(__file__).with_name("poe2_craft_catalog.json.gz"), "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _base(gear):
    return _catalog()["bases"].get(canonical_base(gear.get("base")), ("", 0, 0))


def craftable(gear):
    if not isinstance(gear.get("sourceText") or "", str) or not isinstance(gear.get("mods") or [], list):
        return False
    if not _base(gear)[0] or gear.get("unique") or item_rarity(gear) == "unique":
        return False
    ref = gear.get("overlayRef")
    keys = [gear.get("sourceName"), gear.get("item")]
    if isinstance(ref, dict):
        keys.extend((ref.get("name"), ref.get("id")))
    return not any(key in _gear_data()["uniques"] or _items().get(key, {}).get("kind") == "unique"
                   for key in keys if isinstance(key, str) and key)


def affix_caps(gear):
    return tuple(_base(gear)[1:]) if craftable(gear) else (0, 0)


def _level(value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,3}", str(value)):
        return None
    n = int(value)
    return n if 1 <= n <= 100 else None


def item_level(gear):
    if level := _level(gear.get("level")):
        return level
    match = LEVEL_LINE.search(gear.get("sourceText") or "")
    if match and (level := _level(match[1])):
        return level
    # Guide phase intervals refer to the character. An unspecified item level leaves all tiers available.
    return 100


def set_item_level(gear, level):
    level = _level(level)
    if not level:
        raise ValueError("invalid_level")
    if level < item_level(gear):
        families = _catalog()["families"]
        for mod in equipped_affixes(gear, "en"):
            tier = families.get(mod["family"], {}).get("tiers", {}).get(mod["tier"])
            if tier and tier[1] > level:
                raise ValueError("invalid_level")
    gear["level"] = level
    if raw := gear.get("sourceText"):
        gear["sourceText"] = LEVEL_LINE.sub(lambda m: m[0].replace(m[1], str(level), 1), raw)
        gear["editedImport"] = True


def _quality(value):
    if not re.fullmatch(r"[0-9]{1,3}", str(value)):
        return None
    number = int(value)
    return number if number <= 100 else None


def item_quality(gear):
    value = _quality(gear.get("quality"))
    if value is not None:
        return value
    match = QUALITY_LINE.search(gear.get("sourceText") or "")
    return (_quality(match[1]) or 0) if match else 0


def set_item_quality(gear, quality):
    quality = _quality(quality)
    if quality is None:
        raise ValueError("invalid_quality")
    if quality == item_quality(gear):
        return
    gear["quality"] = quality
    if raw := gear.get("sourceText"):
        if match := QUALITY_LINE.search(raw):
            start, end = match.span(1)
            gear["sourceText"] = raw[:start] + str(quality) + raw[end:]
            gear["editedImport"] = True
        else:
            label = "Qualität" if re.search(r"^Seltenheit:", raw, re.I | re.M) else "Quality"
            _splice_raw(gear, len(raw.splitlines()), 0, [f"{label}: +{quality}%"])


def midpoint_roll(low, high):
    lower, upper = Decimal(str(low)), Decimal(str(high))
    precision = min(lower.as_tuple().exponent, upper.as_tuple().exponent)
    return float(((lower + upper) / 2).quantize(Decimal(1).scaleb(precision), rounding=ROUND_HALF_UP))


def _socket_base(gear):
    return _gear_data()["bases"].get(canonical_base(gear.get("base")), {})


def augment_choices(gear):
    item_type = _socket_base(gear).get("type")
    if item_type == "Quarterstaff":
        item_type = "Warstaff"
    return {name: rows[item_type] for name, rows in _gear_data().get("augments", {}).items() if rows.get(item_type)}


def socket_slots(gear):
    """Return the socket names and whether each effect belongs to the original import."""
    imported = imported_runes(gear)
    equipped = gear.get("socketed")
    equipped = equipped if isinstance(equipped, list) else []
    total = max(_socket_base(gear).get("socketLimit", 0), len(imported), len(equipped))
    slots = []
    for index in range(total):
        name = imported[index] if index < len(imported) else ""
        if name:
            slots.append((name, True))
        else:
            entry = equipped[index] if index < len(equipped) else None
            name = entry.get("name") if isinstance(entry, dict) else ""
            slots.append((name if isinstance(name, str) and name != "None" else "", False))
    return slots


def set_augment(gear, index, name):
    slots = socket_slots(gear)
    if not 0 <= index < len(slots) or slots[index][1]:
        raise ValueError("invalid_socket")
    if slots[index][0] == name:
        return
    if name and index >= _socket_base(gear).get("socketLimit", 0):
        raise ValueError("invalid_socket")
    effects = augment_choices(gear).get(name)
    if name and not effects:
        raise ValueError("invalid_augment")
    current = gear.get("socketed")
    equipped = list(current) if isinstance(current, list) else []
    equipped.extend([None] * (index + 1 - len(equipped)))
    equipped[index] = {"name": name, "effects": list(effects)} if name else None
    while equipped and equipped[-1] is None:
        equipped.pop()
    if equipped:
        gear["socketed"] = equipped
    else:
        gear.pop("socketed", None)


def _number(value):
    return int(value) if "." not in value else float(value)


@lru_cache(maxsize=8192)
def _line_rule(line):
    """Match positional rolls while keeping fixed numbers and signs literal."""
    bounds = []
    parts = []
    offset = 0
    for match in RANGE.finditer(line):
        parts.extend((re.escape(line[offset:match.start()]), NUMBER))
        bounds.append(tuple(sorted((_number(match[1]), _number(match[2])))))
        offset = match.end()
    parts.append(re.escape(line[offset:]))
    return re.compile("".join(parts), re.I), tuple(bounds)


def _shape(line):
    return NUMBERS.sub("#", line).casefold()


@lru_cache(maxsize=24)
def _profile_rules(profile, language="en"):
    rules = defaultdict(list)
    families, stats = _catalog()["families"], _gear_data()["tiers"]
    for family_id in _catalog()["profiles"].get(profile, ()):
        for tier_id, lines in stats[family_id].items():
            if lines:
                if language == "de":
                    lines = [_display_line(line, "de") for line in lines]
                rules[_shape(lines[0])].append((family_id, tier_id, lines, families[family_id]["source"]))
    return rules


def _match(lines, rows):
    rolls = []
    for line, row in zip(lines, rows):
        pattern, bounds = _line_rule(line)
        matched = pattern.fullmatch(row[2])
        if not matched:
            return None
        values = [_number(n) for n in matched.groups()]
        if any(not low <= n <= high for n, (low, high) in zip(values, bounds)):
            return None
        rolls.extend(values)
    return rolls


def _raw_match(candidates, rows, pos, refs):
    start, kind, _, tags = rows[pos]
    matches = []
    for family_id, tier_id, lines, origin in candidates:
        segment = rows[pos:pos + len(lines)]
        if len(segment) != len(lines) or any(row[1] != kind or row[0] != start + i
                                              or _scope(row[3]) != _scope(tags) for i, row in enumerate(segment)):
            continue
        rolls = _match(lines, segment)
        if rolls is not None:
            # A known source wins a tie between identical tiers from different crafting methods.
            hint = refs.get(str(start)) == [family_id, tier_id]
            source_match = origin == ("Desecrated Modifiers" if kind == "desecrated" else "Base")
            matches.append(((len(lines), hint, source_match), family_id, tier_id, rolls))
    if matches:
        rank = max(entry[0] for entry in matches)
        winners = [entry for entry in matches if entry[0] == rank]
        if len({entry[1] for entry in winners}) == 1:
            _, family_id, tier_id, rolls = winners[0]
            return rank[0], family_id, tier_id, rolls
    return 1, "", "", []


def _scope(tags):
    return tuple(tag for tag in tags if not tag.startswith("range:"))


def _source_refs(gear):
    refs = gear.get("sourceAffixes")
    return refs if isinstance(refs, dict) else {}


@lru_cache(maxsize=8192)
def _label(lines, language):
    return " / ".join(_display_line(line, language) for line in lines)


def _entry(key, family_id, tier_id, rolls, lines, language, count=1):
    family = _catalog()["families"].get(family_id, {})
    return {"key": key, "family": family_id, "tier": tier_id, "side": family.get("side", "unknown"),
            "rolls": list(rolls), "label": _label(tuple(lines), language), "count": count}


def _identified_rows(gear, rows):
    profile = _base(gear)[0]
    index = _profile_rules(profile)
    refs = _source_refs(gear)
    pos = 0
    while pos < len(rows):
        shape = _shape(rows[pos][2])
        candidates = index.get(shape) or _profile_rules(profile, "de").get(shape, ())
        count, family_id, tier_id, rolls = _raw_match(candidates, rows, pos, refs)
        segment = rows[pos:pos + count]
        if family_id:
            lines = _rolled(_gear_data()["tiers"][family_id][tier_id], rolls)
        else:
            lines = [row[2] for row in segment]
        yield segment, family_id, tier_id, rolls, lines
        pos += count


def english_imported_stats(gear, rows):
    """Map recognised German item lines back to verified English tier text."""
    return {(row[1], row[2]): line for segment, _, _, _, lines in _identified_rows(gear, rows)
            for row, line in zip(segment, lines)}


def equipped_affixes(gear, language):
    """Keep ambiguous imported rolls editable without inventing a tier or affix group."""
    if not gear.get("sourceText"):
        entries = []
        for i, mod in enumerate(gear.get("mods") or ()):
            if not isinstance(mod, dict):
                continue
            family_id = mod["group"] if isinstance(mod.get("group"), str) else ""
            tier_id = str(mod.get("tier", ""))
            lines = _gear_data()["tiers"].get(family_id, {}).get(tier_id, ())
            rolls = mod["rolls"] if isinstance(mod.get("rolls"), (list, tuple)) else []
            effect = _rolled(lines, rolls) or ["Unbekannter Modifikator" if language == "de" else "Unknown modifier"]
            entries.append(_entry(f"mod:{i}", family_id, tier_id, rolls, effect, language))
        return entries

    rows = []
    _parsed_source(gear, gear.get("sourceName") or gear.get("item"), gear.get("base"), affix_rows=rows)
    return [_entry(f"raw:{segment[0][0]}", family_id, tier_id, rolls, lines, language, len(segment))
            for segment, family_id, tier_id, rolls, lines in _identified_rows(gear, rows)]


def _occupied(gear, replace_key):
    if not craftable(gear):
        raise ValueError("invalid_item")
    entries = equipped_affixes(gear, "en")
    previous = None
    if replace_key is not None:
        previous = next((entry for entry in entries if entry["key"] == replace_key), None)
        if previous is None:
            raise ValueError("unknown_key")
        entries.remove(previous)
    return entries, previous


def _restriction(gear, family_id, occupied, previous):
    families = _catalog()["families"]
    family = families[family_id]
    side = family["side"]
    caps = _base(gear)[1:]
    counts = Counter(entry["side"] for entry in occupied)
    if counts[side] >= caps[side == "suffix"] or (previous is None and len(occupied) >= sum(caps)):
        return "no_capacity"
    for entry in occupied:
        group = families.get(entry["family"], {}).get("group")
        if entry["family"] == family_id or (group and group == family["group"]):
            return "group_conflict"
    return ""


@lru_cache(maxsize=4096)
def _tier_view(family_id, tier_id, language):
    tier, level = _catalog()["families"][family_id]["tiers"][tier_id]
    lines = _gear_data()["tiers"][family_id][tier_id]
    ranges = [pair for line in lines for pair in _line_rule(line)[1]]
    return {"id": tier_id, "tier": tier, "level": level, "ranges": ranges, "label": _label(tuple(lines), language)}


def craft_choices(gear, side, language, replace_key=None):
    if not craftable(gear) or side not in ("prefix", "suffix"):
        return []
    occupied, previous = _occupied(gear, replace_key)
    level = item_level(gear)
    out = []
    for family_id in _catalog()["profiles"][_base(gear)[0]]:
        family = _catalog()["families"][family_id]
        if family["side"] != side or _restriction(gear, family_id, occupied, previous):
            continue
        tiers = [_tier_view(family_id, key, language) for key, (_, req) in family["tiers"].items() if req <= level]
        if tiers:
            label = tiers[0]["label"] if language == "de" else family["name"]
            out.append({"id": family_id, "label": label, "source": family["source"], "tiers": tiers})
    return out


def _splice_raw(gear, start, count, lines, family_id=None, tier_id=None):
    text = gear["sourceText"]
    newline = "\r\n" if "\r\n" in text else "\n"
    parts = text.split(newline)
    parts[start:start + count] = lines
    gear["sourceText"] = newline.join(parts)
    refs = {}
    for key, ref in _source_refs(gear).items():
        if isinstance(key, str) and key.isdecimal() and len(key) <= 8:
            position = int(key)
            if position < start or position >= start + count:
                refs[str(position if position < start else position + len(lines) - count)] = ref
    if family_id:
        refs[str(start)] = [family_id, tier_id]
    if refs:
        gear["sourceAffixes"] = refs
    else:
        gear.pop("sourceAffixes", None)
    gear["editedImport"] = True


def _promote(gear, occupied, side):
    counts = Counter(entry["side"] for entry in occupied)
    counts[side] += 1
    rare = max(counts.values()) > 1 or sum(counts.values()) > 2
    target = "rare" if rare else "magic"
    rarity = item_rarity(gear)
    if rarity == "rare" or rarity == target:
        return
    gear["rarity"] = target
    if raw := gear.get("sourceText"):
        def update_header(match):
            de = match[0].casefold().startswith("seltenheit")
            label = {"rare": "Selten", "magic": "Magisch"}[target] if de else target.upper()
            return match[0][:match.start(1) - match.start()] + label
        gear["sourceText"] = RARITY_HEADER.sub(update_header, raw, count=1)


def put_affix(gear, family_id, tier_id, rolls, replace_key=None):
    """Validate the entire change before mutating the draft, including roll precision."""
    occupied, previous = _occupied(gear, replace_key)
    if family_id not in _catalog()["profiles"][_base(gear)[0]]:
        raise ValueError("invalid_affix")
    family = _catalog()["families"][family_id]
    tier_id = str(tier_id)
    if tier_id not in family["tiers"] or family["tiers"][tier_id][1] > item_level(gear):
        raise ValueError("invalid_tier")
    if reason := _restriction(gear, family_id, occupied, previous):
        raise ValueError(reason)
    ranges = _tier_view(family_id, tier_id, "en")["ranges"]
    if not isinstance(rolls, (list, tuple)) or len(rolls) != len(ranges):
        raise ValueError("invalid_roll")
    values = []
    for n, (low, high) in zip(rolls, ranges):
        if type(n) not in (int, float) or not low <= n <= high or not math.isfinite(n):
            raise ValueError("invalid_roll")
        precision = max(len(str(bound).partition(".")[2]) for bound in (low, high))
        if round(n, precision) != n:
            raise ValueError("invalid_roll")
        values.append(int(n) if int(n) == n else n)

    _promote(gear, occupied, family["side"])
    if raw := gear.get("sourceText"):
        raw_lines = raw.splitlines()
        start, count = (int(previous["key"][4:]), previous["count"]) if previous else (len(raw_lines), 0)
        if not previous:
            while start and (raw_lines[start - 1].strip() in (*STATUS, *STATUS.values())
                             or not raw_lines[start - 1].strip("-= \t")):
                start -= 1
        tags = TAGS.findall(raw_lines[start]) if previous else ()
        kept = [tag for tag in tags if tag.startswith("variant:") or tag == "fractured"]
        if family["source"] == "Desecrated Modifiers":
            kept.append("desecrated")
        prefix = "".join("{" + tag + "}" for tag in kept)
        lines = _rolled(_gear_data()["tiers"][family_id][tier_id], values)
        if re.search(r"^Seltenheit:", raw, re.I | re.M):
            lines = [_display_line(line, "de") for line in lines]
        _splice_raw(gear, start, count, [prefix + line for line in lines], family_id, tier_id)
    else:
        if gear.get("mods") is None:
            gear["mods"] = []
        mods = gear["mods"]
        mod = {"group": family_id, "tier": tier_id, "rolls": values}
        if previous:
            mods[int(previous["key"][4:])] = mod
        else:
            mods.append(mod)


def remove_affix(gear, key):
    _, previous = _occupied(gear, key)
    if previous is None:
        raise ValueError("unknown_key")
    index = int(previous["key"][4:])
    if gear.get("sourceText"):
        _splice_raw(gear, index, previous["count"], [])
    else:
        del gear["mods"][index]
