"""Item clipboard interoperability and official Path of Exile 2 trade searches."""

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from functools import lru_cache
import gzip
from http.client import HTTPSConnection, HTTPException
import json
from pathlib import Path
import re
from threading import Lock, Thread
from time import monotonic
from urllib.parse import quote, urlencode

from poe2_build_items import (NUMBERS, RANGE, RARITY_HEADER, RUNE_LINE, SECTIONS, SOCKET_LINE,
                              _gear_data, _items, _parsed_source, _socketed_lines, canonical_base, imported_runes,
                              item_card)
from poe2_item_craft import english_imported_stats
from poe2_lexicon import catalogue, german_stat_translations
from poe2_overlay_version import BUILD_LABEL


TRADE_HOST = "www.pathofexile.com"
TRADE_SITE = f"https://{TRADE_HOST}/trade2/search/poe2"
TRADE_LEAGUE_PATH = "/api/trade2/data/leagues"
OFFLINE_TRADE_LEAGUES = ("Forbidden Rites", "HC Forbidden Rites", "Runes of Aldur", "HC Runes of Aldur",
                         "Standard", "Hardcore")
TRADE_STATS = Path(__file__).with_name("poe2_trade_stats.json.gz")
RARITIES = {"normal": "Normal", "magic": "Magic", "rare": "Rare", "unique": "Unique", "relic": "Relic"}
GAME_TAG = re.compile(r" (?P<tag>\((?:implicit|enchant|rune|fractured|crafted|desecrated|mutated)\))$")
NUMERIC = re.compile(r"[+-]?\d+(?:\.\d+)?")
LOCAL_NUMBER = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
TRADE_CATEGORY = {
    "Amulet": "accessory.amulet", "Belt": "accessory.belt", "Ring": "accessory.ring",
    "Body Armour": "armour.chest", "Helmet": "armour.helmet", "Gloves": "armour.gloves",
    "Boots": "armour.boots", "Shield": "armour.shield", "Focus": "armour.focus",
    "Buckler": "armour.buckler", "Quiver": "armour.quiver",
    "Bow": "weapon.bow", "Crossbow": "weapon.crossbow", "Claw": "weapon.claw",
    "Dagger": "weapon.dagger", "Spear": "weapon.spear", "Flail": "weapon.flail",
    "Talisman": "weapon.talisman", "Staff": "weapon.staff", "Quarterstaff": "weapon.warstaff",
    "Warstaff": "weapon.warstaff", "Wand": "weapon.wand", "Sceptre": "weapon.sceptre",
    "One Hand Sword": "weapon.onesword", "One Hand Axe": "weapon.oneaxe", "One Hand Mace": "weapon.onemace",
    "Two Hand Sword": "weapon.twosword", "Two Hand Axe": "weapon.twoaxe", "Two Hand Mace": "weapon.twomace",
}
EQUIPMENT_FILTERS = {"Armour": "ar", "Evasion Rating": "ev", "Evasion": "ev", "Energy Shield": "es",
                     "Spirit": "spirit", "Block Chance": "block"}
PSEUDO_PATTERNS = {
    "# to maximum life": "+# total maximum Life",
    "# to maximum mana": "+# total maximum Mana",
    "# to strength": "+# total Strength",
    "# to dexterity": "+# total Dexterity",
    "# to intelligence": "+# total Intelligence",
    "#% to fire resistance": "+#% total Elemental Resistance",
    "#% to cold resistance": "+#% total Elemental Resistance",
    "#% to lightning resistance": "+#% total Elemental Resistance",
    "#% to all elemental resistances": "+#% total Elemental Resistance",
}


def trade_league_name(value):
    name = value.strip() if isinstance(value, str) else ""
    return name if len(name) <= 100 and name.isprintable() else ""


def _download_trade_leagues():
    """Read public trade league IDs in the order shown by the PoE2 trade site."""
    limit = 64 * 1024
    try:
        with closing(HTTPSConnection(TRADE_HOST, timeout=4)) as connection:
            connection.request("GET", TRADE_LEAGUE_PATH, headers={
                "Accept": "application/json", "User-Agent": f"Buildschmiede Companion/{BUILD_LABEL}",
            })
            response = connection.getresponse()
            if response.status != 200:
                return ()
            body = response.read(limit + 1)
        if len(body) > limit:
            return ()
        data = json.loads(body)
    except (OSError, HTTPException, ValueError, RecursionError):
        return ()
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        return ()
    return tuple(dict.fromkeys(name for row in data["result"]
                               if isinstance(row, dict) and row.get("realm") == "poe2"
                               and (name := trade_league_name(row.get("id")))))


class TradeLeagues:
    """Refresh once in the background and reuse the last list for every dialog."""

    def __init__(self):
        self._leagues = OFFLINE_TRADE_LEAGUES
        self._refresh_at = 0
        self._pending = False
        self._lock = Lock()

    def snapshot(self, *, refresh=False):
        with self._lock:
            start = refresh and not self._pending and monotonic() >= self._refresh_at
            self._pending = self._pending or start
            result = self._leagues, self._pending
        if start:
            Thread(target=self._refresh, daemon=True).start()
        return result

    def _refresh(self):
        leagues = _download_trade_leagues()
        with self._lock:
            if leagues:
                self._leagues = leagues
            self._refresh_at = monotonic() + (3600 if leagues else 900)
            self._pending = False


trade_leagues = TradeLeagues()


def _raw_item(gear):
    raw = gear.get("sourceText")
    return raw.strip().replace("\r\n", "\n") if isinstance(raw, str) else ""


@lru_cache(maxsize=1)
def _english_stat_patterns():
    reverse = defaultdict(dict)
    general = catalogue()["germanRollPatterns"]
    for english, german in general.items():
        if english.count("#") == german.count("#"):
            reverse[_comparison_text(german)][_comparison_text(english)] = english
    for english, german in german_stat_translations().items():
        if RANGE.search(english) and RANGE.search(german):
            if len(RANGE.findall(english)) != len(RANGE.findall(german)):
                continue
            english, german = RANGE.sub("#", english), RANGE.sub("#", german)
        if english.count("#") == german.count("#"):
            reverse[_comparison_text(german)][_comparison_text(english)] = english
    return {german: next(iter(options.values())) for german, options in reverse.items() if len(options) == 1}


def _known_english_stat(line, patterns):
    if RANGE.search(line):
        return line
    if known := patterns.get(_comparison_text(line)):
        return known
    template = patterns.get(_comparison_text(LOCAL_NUMBER.sub("#", line)))
    rolls = LOCAL_NUMBER.findall(line)
    if not template or template.count("#") != len(rolls):
        return line
    values = iter(rolls)

    def substitute(match):
        value = next(values).replace(",", ".")
        return "+" + value if match[0].startswith("+") and value[0] not in "+-" else value

    return re.sub(r"\+?#", substitute, template)


def _english_sections(gear, card, base):
    raw = _raw_item(gear)
    if not raw:
        sections = dict(card.sections)
        return {key: list(sections.get(labels[1], ())) for key, labels in SECTIONS.items()}
    lines = []
    for line in raw.splitlines():
        if match := GAME_TAG.search(line):
            # The older PoB exporter uses braces; character clipboard text uses suffixes.
            line = "{" + match["tag"][1:-1] + "}" + line[:match.start()]
        lines.append(line)
    normalized = {**gear, "sourceText": "\n".join(lines)}
    affixes = []
    groups = _parsed_source(normalized, card.title, base, affix_rows=affixes)
    german = re.search(r"^Seltenheit:", raw, re.M | re.I)
    verified = english_imported_stats(normalized, affixes) if german else {}
    if german:
        patterns = _english_stat_patterns()
        for key in ("explicit", "desecrated", "implicit", "rune", "enchant"):
            for line in groups[key]:
                verified.setdefault((key, line), _known_english_stat(line, patterns))
            groups[key] = [verified.get((key, line), line) for line in groups[key]]
    for _, group, line, tags in affixes:
        flag = next((tag for tag in tags if tag in ("crafted", "fractured", "mutated")), None)
        canonical = verified.get((group, line), line)
        if flag and group == "explicit" and canonical in groups[group]:
            groups[group].remove(canonical)
            groups[flag].append(canonical)
    groups["rune"].extend(_socketed_lines(gear, imported_runes(gear)))
    return groups


def item_clipboard_text(gear):
    """Keep original English item text when available, or emit a PoB clipboard item."""
    raw = _raw_item(gear)
    header = RARITY_HEADER.search(raw)
    if header and header[0].startswith("Rarity:") and header[1].casefold() in RARITIES and (
            not gear.get("editedImport") and not gear.get("socketed")):
        prefix = raw[:header.start()].strip()
        if not prefix or (prefix.startswith("Item Class:") and "\n" not in prefix):
            return raw

    card = item_card(gear, "en")
    base = canonical_base(card.base or card.title)
    base_record = _gear_data()["bases"].get(base, {})
    if not base or (not base_record and base not in _items()):
        return ""

    groups = _english_sections(gear, card, base)
    modifier_groups = ("explicit", "implicit", "enchant", "rune", "desecrated", "crafted", "fractured", "mutated")
    lines = [line for group in modifier_groups for line in groups.get(group, ()) if not RUNE_LINE.match(line)]
    if any(RANGE.search(line) or "#" in line for line in lines):
        return ""  # A catalogue roll range is insufficient to export a concrete item.
    rarity = card.rarity
    if rarity == "unknown" and raw and not header and not gear.get("rarity"):
        first_line = raw.split("\n", 1)[0].strip()
        if canonical_base(first_line) == base and lines and all(_known_guide_stat(line) for line in lines):
            # Game build exports give the base and exact mod values but omit the original rarity.
            rarity = base_record.get("rarity")
    if rarity not in RARITIES:
        return ""
    result = [f"Rarity: {RARITIES[rarity]}"]
    if rarity in ("rare", "unique", "relic"):
        result.extend([card.title, base])
    else:
        result.append(base)

    properties = []
    for line in groups.get("properties", ()):
        if not line.startswith(("Item Level:", "Rune:")) and (
                not gear.get("editedImport") or line.startswith("Quality:")):
            properties.append(line)
    if properties:
        result.extend(["--------", *properties])
    requirements = []
    attributes = []
    for line in groups.get("requirements", ()):
        for word, internal, short in (("Level", "LevelReq", "Level"), ("Strength", "StrReq", "Str"),
                                      ("Dexterity", "DexReq", "Dex"), ("Intelligence", "IntReq", "Int")):
            if re.fullmatch(rf"(?:{word} |{internal}: )\d+", line):
                amount = line.rsplit(" ", 1)[1]
                attributes.append(f"Level {amount}" if short == "Level" else f"{amount} {short}")
                break
        else:
            if line.startswith(("Requires ", "Requires:")):
                requirements.append(line.replace("Requires ", "Requires: ", 1))
    if attributes and not requirements:
        requirements.append("Requires: " + ", ".join(attributes))
    if requirements:
        result.extend(["--------", *requirements])

    runes = imported_runes(gear)
    socketed = gear.get("socketed")
    socketed = socketed if isinstance(socketed, (list, tuple)) else ()
    sockets = SOCKET_LINE.search(raw)
    socket_values = sockets[1] if sockets else ""
    socket_count = max(socket_values.count("S"), len(runes), len(socketed))
    if socket_count > socket_values.count("S"):
        socket_values = " ".join("S" for _ in range(socket_count))
    if socket_values:
        result.extend(["--------", f"Sockets: {socket_values}"])
        for index in range(socket_values.count("S")):
            name = runes[index] if index < len(runes) else ""
            selected = socketed[index] if index < len(socketed) and isinstance(socketed[index], dict) else {}
            if name != "?":
                result.append(f"Rune: {name or selected.get('name') or 'None'}")
    level = next((line for line in groups.get("properties", ()) if line.startswith("Item Level: ")), "")
    if not level and type(gear.get("level")) is int:
        level = f"Item Level: {gear['level']}"
    if level:
        result.extend(["--------", level])
    for group, suffix in (("enchant", " (enchant)"), ("rune", " (rune)"), ("implicit", " (implicit)")):
        modifiers = [line + suffix for line in groups.get(group, ()) if not RUNE_LINE.match(line)]
        if modifiers:
            result.extend(["--------", *modifiers])
    modifiers = [line + (f" ({group})" if group != "explicit" else "")
                 for group in ("explicit", "desecrated", "crafted", "fractured", "mutated")
                 for line in groups.get(group, ())]
    if modifiers:
        result.extend(["--------", *modifiers])
    if groups.get("status"):
        result.extend(["--------", *groups["status"]])
    return "\n".join(result)


def _stat_template(value):
    return " ".join(NUMBERS.sub("#", value).casefold().replace("+#", "#").split())


@lru_cache(maxsize=1)
def _gear_stat_templates():
    return {_stat_template(line) for family in _gear_data()["tiers"].values()
            for tier in family.values() for line in tier}


def _known_guide_stat(line):
    template = _stat_template(line)
    return template in _gear_stat_templates() or template in _trade_stats()


def _comparison_text(value):
    return re.sub(r"\+(?=[#\d])", "", " ".join(value.casefold().split()))


@lru_cache(maxsize=2048)
def _trade_matcher(template):
    return re.compile(re.escape(_comparison_text(template)).replace(r"\#", NUMERIC.pattern))


@lru_cache(maxsize=1)
def _trade_stats():
    index = defaultdict(dict)
    try:
        with gzip.open(TRADE_STATS, "rt", encoding="utf-8") as file:
            stats = json.load(file)["stats"]
    except (OSError, ValueError, KeyError):
        return index
    for ident, name in stats:
        entries = index[_stat_template(name)]
        group = ident.split(".", 1)[0]
        entries[group] = (*entries.get(group, ()), (ident, name))
    return index


@dataclass(frozen=True)
class TradeFilter:
    id: str
    text: str
    value: str = ""
    group: str = "stat"
    selected: bool = False


@dataclass(frozen=True)
class TradeItem:
    title: str
    base: str
    category: str
    unique: str
    filters: tuple[TradeFilter, ...]
    unmatched: int
    league: str


def trade_item(gear):
    card = item_card(gear, "en")
    base = canonical_base(card.base or card.title)
    if not base or (base not in _gear_data()["bases"] and base not in _items()):
        return None
    base_record = _items().get(base, {}).get("item", {})
    kind = base_record.get("type") or _gear_data()["bases"].get(base, {}).get("type")
    if kind == "Staff" and base_record.get("subType") == "Warstaff":
        kind = "Warstaff"
    category = TRADE_CATEGORY.get(kind, "")
    unique = card.title if card.rarity in ("unique", "relic") else ""
    if unique and card.title not in _gear_data()["uniques"] and _items().get(card.title, {}).get("kind") != "unique":
        unique = ""
    groups = _english_sections(gear, card, base)
    filters = []
    seen = set()
    if _raw_item(gear) and not gear.get("editedImport"):
        for line in groups.get("properties", ()):
            prop, sep, value = line.partition(": ")
            filter_id = EQUIPMENT_FILTERS.get(prop)
            match = NUMERIC.match(value)
            if sep and filter_id and match and filter_id not in seen:
                filters.append(TradeFilter(filter_id, line, match[0], "equipment", True))
                seen.add(filter_id)

    defined = _trade_stats()
    unmatched = 0
    pseudo_totals = defaultdict(Decimal)
    matched = []
    for group in ("explicit", "implicit", "enchant", "rune", "desecrated", "crafted", "fractured", "mutated"):
        for line in groups.get(group, ()):
            if RUNE_LINE.match(line):
                continue
            if RANGE.search(line):
                unmatched += 1
                continue
            key = _stat_template(line)
            candidates = defined.get(key, {})
            text = _comparison_text(line)
            ids = {ident for ident, name in candidates.get("explicit" if group == "mutated" else group, ())
                   if _trade_matcher(name).fullmatch(text)}
            values = NUMERIC.findall(line)
            value = values[0] if len(values) == 1 and Decimal(values[0]) > 0 else ""
            pseudo = PSEUDO_PATTERNS.get(key)
            if pseudo and value and group in ("explicit", "implicit", "desecrated", "crafted", "fractured", "mutated"):
                pseudo_totals[pseudo] += Decimal(value) * (3 if key == "#% to all elemental resistances" else 1)
            if len(ids) != 1:
                unmatched += 1
                continue
            ident = ids.pop()
            if ident not in seen:
                matched.append((TradeFilter(ident, line, value), pseudo))
                seen.add(ident)

    pseudo_enabled = set()
    for name, value in pseudo_totals.items():
        ids = [ident for ident, template in defined.get(_stat_template(name), {}).get("pseudo", ())
               if _comparison_text(template) == _comparison_text(name)]
        if len(ids) == 1:
            sign = "%" if "%" in name else ""
            display = name.replace("#" + sign, f"{value:f}{sign}")
            filters.append(TradeFilter(ids[0], display, str(value), selected=True))
            pseudo_enabled.add(name)
    for row, pseudo in matched:
        # Prefer aggregate targets where available, with a few distinct modifiers as defaults.
        selected = not unique and pseudo not in pseudo_enabled and sum(f.selected for f in filters) < 8
        filters.append(TradeFilter(row.id, row.text, row.value, selected=selected))

    league = re.search(r"^League: ([^\r\n]+)", _raw_item(gear), re.M)
    return TradeItem(card.title, base, category, unique, tuple(filters), unmatched,
                     league[1].strip() if league else "")


def minimum_roll(value, percentage):
    """Return the minimum sent to Trade, or None if the filter has no minimum."""
    if not value or not percentage:
        return None
    precision = Decimal("0.01") if "." in value else Decimal("1")
    roll = Decimal(value)
    minimum = (roll * percentage / 100).quantize(precision, rounding=ROUND_FLOOR)
    if not minimum and roll > 0:
        minimum = min(roll, precision)
    return int(minimum) if precision == 1 else float(minimum)


def trade_url(item, league, selected, percentage=80, *, exact_base=True):
    """Build the percent-encoded search URL used by the official website."""
    league = trade_league_name(league)
    if not league:
        raise ValueError("invalid_league")
    if not 0 <= percentage <= 100:
        raise ValueError("invalid_percentage")
    query = {"status": {"option": "securable"}, "stats": [{"type": "and", "filters": []}], "filters": {}}
    if exact_base or not item.category or item.unique:
        query["type"] = item.base
    else:
        query["filters"]["type_filters"] = {"filters": {"category": {"option": item.category}}}
    if item.unique:
        query["name"] = item.unique
    equipment = {}
    for row in item.filters:
        if row.id not in selected:
            continue
        minimum = minimum_roll(row.value, percentage)
        limit = {"min": minimum} if minimum is not None else {}
        if row.group == "equipment":
            if limit:
                equipment[row.id] = limit
        else:
            ident, separator, option = row.id.partition("|")
            if separator:
                limit = {"option": int(option) if option.isdecimal() else option}
            query["stats"][0]["filters"].append({"id": ident, **({"value": limit} if limit else {})})
    if equipment:
        query["filters"]["equipment_filters"] = {"filters": equipment}
    payload = {"query": query, "sort": {"price": "asc"}}
    return f"{TRADE_SITE}/{quote(league, safe='')}?{urlencode({'q': json.dumps(payload, separators=(',', ':'))})}"
