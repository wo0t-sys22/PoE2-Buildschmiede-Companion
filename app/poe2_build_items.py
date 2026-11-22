"""Player-facing item cards shared by the native planner and the small HUD."""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re
import tkinter as tk

from poe2_build_art import build_icon, item_art_ref
from poe2_game_de import inverted_stat, translate_rolls
from poe2_lexicon import catalogue, german_stat_translations, public_stats
from poe2_lexicon_explain import currency_copy
from poe2_website_content import localized_text


RARITIES = {
    "normal": ("Normal", "Normal", "#a9b2bd"), "magic": ("Magisch", "Magic", "#9797ff"),
    "rare": ("Selten", "Rare", "#ffff77"), "unique": ("Einzigartig", "Unique", "#e5a16c"),
    "unknown": ("", "", "#a9b2bd"),
}
SECTIONS = {
    "properties": ("Eigenschaften", "Properties"), "explicit": ("Modifikatoren", "Modifiers"),
    "desecrated": ("Entweiht", "Desecrated"), "implicit": ("Implizit", "Implicit"),
    "enchant": ("Verzauberung", "Enchantment"), "rune": ("Runen", "Runes"),
    "requirements": ("Voraussetzungen", "Requirements"), "status": ("Zustand", "Status"),
    "description": ("Beschreibung", "Description"), "goal": ("Darauf achten", "What to look for"),
    "mod": ("Gewünschter Modifikator", "Target modifier"),
}
PROPERTIES = {
    "Energy Shield": "Energieschild", "Spirit": "Wille", "Armour": "Rüstung", "Evasion": "Ausweichen",
    "Evasion Rating": "Ausweichwert", "Quality": "Qualität", "Item Level": "Gegenstandsstufe",
    "Charm Slots": "Phiolen-Plätze", "Physical Damage": "Physischer Schaden", "Elemental Damage": "Elementarschaden",
    "Critical Hit Chance": "Kritische Trefferchance", "Attacks per Second": "Angriffe pro Sekunde",
    "Block Chance": "Blockchance", "Fire Damage": "Feuerschaden", "Cold Damage": "Kälteschaden",
    "Lightning Damage": "Blitzschaden", "Chaos Damage": "Chaosschaden", "Duration": "Dauer",
    "Charges Used": "Verbrauchte Füllungen", "Maximum Charges": "Maximale Füllungen", "Rune": "Rune",
    "Movement Speed Penalty": "Abzug auf Bewegungsgeschwindigkeit",
    "Life Recovered": "Wiederhergestelltes Leben", "Mana Recovered": "Wiederhergestelltes Mana",
}
REQUIREMENTS = {
    "LevelReq": ("Stufe", "Level"), "StrReq": ("Stärke", "Strength"),
    "IntReq": ("Intelligenz", "Intelligence"), "DexReq": ("Geschick", "Dexterity"),
    "Requires": ("Erfordert", "Requires"), "Requirement": ("Erfordert", "Requires"),
    "Requirements": ("Erfordert", "Requires"),
}
STATUS = {"Corrupted": "Verderbt", "Mirrored": "Gespiegelt", "Unidentified": "Nicht identifiziert"}
META = {"rarity", "seltenheit", "unique id", "item id", "item class", "league", "source", "prefix", "suffix",
        "crafted", "has alt variant", "variant", "selected variant", "quality catalyst", "catalystquality",
        "quality (attribute modifiers)", "sockets", "socket", "gegenstandsklasse", "sockel", "katalysator"}
TAGS = re.compile(r"\{([^{}]*)\}")
RANGE = re.compile(r"\(([+-]?\d+(?:\.\d+)?)\s*[-–—]\s*([+-]?\d+(?:\.\d+)?)\)")
NUMBERS = re.compile(r"[+-]?(?:" + RANGE.pattern + r"|\d+(?:\.\d+)?)")
RARITY_HEADER = re.compile(r"^(?:Rarity|Seltenheit):[ \t]*(\w+)", re.I | re.M)
RUNE_LINE = re.compile(r"^[ \t]*Rune:[ \t]*([^\r\n]*)", re.I | re.M)
SOCKET_LINE = re.compile(r"^[ \t]*(?:Sockets?|Sockel):[ \t]*([^\r\n]*)", re.I | re.M)


@dataclass(frozen=True)
class ItemCard:
    title: str
    base: str
    rarity: str
    icon: str
    sections: tuple
    rarity_label: str


def rarity_color(rarity):
    return RARITIES.get(rarity, RARITIES["normal"])[2]


@lru_cache(maxsize=1)
def _gear_data():
    with gzip.open(Path(__file__).with_name("poe2_build_import_gear.json.gz"), "rt", encoding="utf-8") as stream:
        return json.load(stream)


@lru_cache(maxsize=1)
def _items():
    return {key: row for row in catalogue()["items"]
            for key in (row["name"], row.get("gameId"), row.get("currencyId")) if key}


@lru_cache(maxsize=1)
def _base_aliases():
    data = _gear_data()
    names = defaultdict(set)
    for base in data["bases"]:
        for label in (base, _items().get(base, {}).get("de"), data["deNames"].get(base)):
            if label:
                names[label.casefold()].add(base)
    return {label: next(iter(bases)) for label, bases in names.items() if len(bases) == 1}


def canonical_base(name):
    """Resolve an unambiguous catalogue name without guessing at custom item names."""
    if not isinstance(name, str):
        return ""
    if name in _gear_data()["bases"]:
        return name
    return _base_aliases().get(name.strip().casefold(), name)


def _str(value):
    return value if isinstance(value, str) else ""


def _array(value):
    return value if isinstance(value, (tuple, list)) else ()


def imported_runes(gear):
    """Reserve positions represented by original item text, including unidentified runes."""
    raw = _str(gear.get("sourceText"))
    names = [name.strip() for name in RUNE_LINE.findall(raw)]
    if not names and ("{rune}" in raw or re.search(r" \(rune\)[ \t]*\r?$", raw, re.M | re.I)):
        sockets = SOCKET_LINE.search(raw)
        return ("?",) * max(1, len(re.findall(r"[A-Za-z]", sockets[1])) if sockets else 0)
    return tuple(name if name.casefold() != "none" else "" for name in names)


def _socketed_lines(gear, imported=()):
    for index, rune in enumerate(_array(gear.get("socketed"))):
        if index < len(imported) and imported[index]:
            continue
        if isinstance(rune, Mapping) and (name := _str(rune.get("name"))) and name != "None":
            yield f"Rune: {name}"
            yield from (effect for effect in _array(rune.get("effects")) if isinstance(effect, str))


def item_rarity(gear, record=None):
    raw = _str(gear.get("sourceText"))
    header = RARITY_HEADER.search(raw)
    declared = header[1] if header else _str(gear.get("rarity"))
    for key, (de, en, _) in RARITIES.items():
        if declared and declared.casefold() in (de.casefold(), en.casefold()):
            return key
    if gear.get("unique") or (record or {}).get("kind") == "unique":
        return "unique"
    if gear.get("mods"):
        base = _gear_data()["bases"].get(canonical_base(gear.get("base")), {})
        return "magic" if base.get("rarity") == "magic" else "rare"
    return "unknown" if raw else "normal"


def _rolled(lines, rolls):
    values = iter(_array(rolls))

    def replace(match):
        value = next(values, None)
        return str(value) if type(value) in (int, float) else match[0]

    return [RANGE.sub(replace, line) for line in lines if isinstance(line, str)]


def _interpolate(line, tags):
    fraction = next((tag[6:] for tag in tags if re.fullmatch(r"range:(?:0(?:\.\d+)?|1(?:\.0+)?)", tag)), "")
    if not fraction:
        return line

    def replace(match):
        if max(len(fraction), len(match[1]), len(match[2])) > 12:
            return match[0]
        low, high = Decimal(match[1]), Decimal(match[2])
        precision = min(low.as_tuple().exponent, high.as_tuple().exponent)
        value = low + (high - low) * Decimal(fraction)
        return format(value.quantize(Decimal(1).scaleb(precision), rounding=ROUND_HALF_UP), "f")

    return RANGE.sub(replace, line)


def _parsed_source(gear, title, base, *, affix_rows=None):
    groups = defaultdict(list)
    canonical = canonical_base(base)
    base_record = _items().get(canonical, {})
    headings = {title, base, gear.get("base"), canonical, base_record.get("de"),
                _gear_data()["deNames"].get(canonical)}
    lines = [line.strip() for line in gear["sourceText"].splitlines()]
    variant = next((line.partition(":")[2].strip() for line in lines if line.lower().startswith("selected variant:")), "1")
    implicit = 0
    properties = {key.casefold(): key for key in PROPERTIES}
    properties.update({name.casefold(): key for key, name in PROPERTIES.items()})
    requirements = {key.casefold(): key for key in REQUIREMENTS}
    requirements.update({name.casefold(): key for key, names in REQUIREMENTS.items() for name in names})
    for index, raw in enumerate(lines):
        if not raw or raw in headings or raw.strip("-= ") == "":
            continue
        label, separator, value = raw.partition(":")
        key, value = label.casefold(), value.strip()
        if separator and key.startswith(("quality (", "qualität (")) and key.endswith(")"):
            key = "quality"
        if separator and key == "implicits":
            implicit = int(value) if value.isascii() and value.isdigit() and len(value) <= 3 else 0
            continue
        if separator and key in META:
            continue
        if separator and key in properties:
            if key == "quality":
                if value.strip("+%") == "0":
                    continue
                if value.isdigit():
                    value = f"+{value}%"
            if key == "rune" and value.casefold() == "none":
                continue
            group = "rune" if key == "rune" else "properties"
            groups[group].append(f"{properties[key]}: {value}")
            continue
        if separator and key in requirements:
            if value and value != "0":
                groups["requirements"].append(f"{requirements[key]}: {value}")
            continue
        if raw in STATUS or raw in STATUS.values():
            groups["status"].append(next((en for en, de in STATUS.items() if de == raw), raw))
            continue
        tags = TAGS.findall(raw)
        group = next((key for key in ("rune", "desecrated", "enchant", "implicit") if key in tags),
                     "implicit" if implicit else "explicit")
        implicit = max(0, implicit - 1)
        if any(tag.startswith("variant:") and variant not in tag[8:].split(",") for tag in tags):
            continue
        clean = _interpolate(TAGS.sub("", raw).strip(), tags)
        visible = public_stats((clean,))
        groups[group].extend(visible)
        if affix_rows is not None and visible and group in ("explicit", "desecrated"):
            affix_rows.append((index, group, clean, tuple(tags)))
    return groups


def _catalogue_sections(gear, base, stats, *, unique=False):
    groups = defaultdict(list)
    groups["properties"].extend(base.get("stats", ()))
    if gear.get("level"):
        groups["properties"].append(f"Item Level: {gear['level']}")
    if type(gear.get("quality")) is int and gear["quality"] > 0:
        groups["properties"].append(f"Quality: +{gear['quality']}%")
    if base.get("reqLevel"):
        groups["requirements"].append(f"LevelReq: {base['reqLevel']}")
    for stat, value in base.get("requires", {}).items():
        if stat in ("str", "int", "dex") and value:
            groups["requirements"].append(f"{stat.capitalize()}Req: {value}")
    base_lines = base.get("implicit", ())
    implicit = _rolled(base_lines, gear.get("implicitRolls"))
    explicit = _rolled(stats, gear.get("uniqueRolls"))
    shared = 0
    if unique:
        # The source can include the base implicit at the start of its flat unique stats.
        for base_line, stat, inherited, rolled in zip(base_lines, stats, implicit, explicit):
            if base_line != stat or inherited != rolled:
                break
            shared += 1
    groups["implicit"].extend(implicit)
    groups["explicit"].extend(explicit[shared:])
    for mod in _array(gear.get("mods")):
        if isinstance(mod, Mapping):
            family = _gear_data()["tiers"].get(_str(mod.get("group")), {})
            groups["explicit"].extend(_rolled(family.get(str(mod.get("tier")), ()), mod.get("rolls")))
    return groups


def _display_line(line, language):
    key, sep, tail = line.partition(": ")
    if sep and key in REQUIREMENTS:
        return f"{REQUIREMENTS[key][language != 'de']} {tail}"
    if language != "de":
        return line
    data = _gear_data()
    if sep and key in PROPERTIES:
        label = _items().get(tail, {}).get("de") or data["deNames"].get(tail, tail)
        return f"{PROPERTIES[key]}: {label}"
    if sep and key == "Bonded":
        return "Gebunden: " + _display_line(tail, language)
    if exact := data["deNames"].get(line) or STATUS.get(line):
        return exact
    values = [match[0] for match in NUMBERS.finditer(line)]
    key = NUMBERS.sub("#", line).casefold().replace("+#", "#")
    template = data["patterns"].get(key)
    if template and template.count("#") == len(values):
        parts = iter(values)

        def substitute(match):
            value = next(parts)
            return "+" + value if match[0] == "+#" and not value.startswith(("+", "-")) else value

        localized = re.sub(r"\+?#", substitute, template)
        if not inverted_stat(line, localized):
            return localized
    return german_stat_translations().get(line) or translate_rolls(line, catalogue()["germanRollPatterns"]) or line


def item_card(gear, language, *, show_targets=False):
    """Format an editor gear record (including published overlayRef records) for both displays."""
    ref = gear["overlayRef"] if isinstance(gear.get("overlayRef"), Mapping) else {}
    name = next((_str(gear.get(key)) for key in ("sourceName", "unique", "item") if _str(gear.get(key))),
                _str(ref.get("name")) or _str(ref.get("id")) or _str(gear.get("base")))
    record = _items().get(_str(gear.get("unique")) or name) or _items().get(_str(ref.get("id"))) or {}
    source = _gear_data()
    unique = source["uniques"].get(_str(gear.get("unique")) or record.get("name") or name, {})
    base_name = canonical_base(_str(gear.get("base")) or unique.get("base") or _str(record.get("base"))
                               or _str(record.get("name")))
    base = source["bases"].get(base_name, {})
    raw = _str(gear.get("sourceText"))
    stats = unique.get("stats", ()) if unique else record.get("stats", ())
    german_rows = [] if language == "en" and not unique and re.search(r"^Seltenheit:", raw, re.I | re.M) else None
    if raw:
        groups = _parsed_source(gear, name, base_name, affix_rows=german_rows)
    else:
        groups = _catalogue_sections(gear, base, stats, unique=bool(unique))
    if raw and type(gear.get("level")) is int and not any(line.startswith("Item Level: ") for line in groups["properties"]):
        groups["properties"].append(f"Item Level: {gear['level']}")
    groups["rune"].extend(_socketed_lines(gear, imported_runes(gear) if raw else ()))
    if german_rows:
        from poe2_item_craft import english_imported_stats

        english = english_imported_stats(gear, german_rows)
        for section in ("explicit", "desecrated"):
            groups[section] = [english.get((section, line), line) for line in groups[section]]
    if not raw and unique.get("partialVariant"):
        groups["description"].append("Common modifiers across variants." if language == "en" else
                                     "Aufgeführt sind die gemeinsamen Modifikatoren der Varianten.")
    desc = (currency_copy(record, language)[0] if record.get("kind") == "currency"
            else localized_text(record.get("description"), language))
    if desc:
        groups["description"].append(desc)
    if note := _str(ref.get("note")):
        groups["description"].append(note)
    if show_targets:
        for key in ("goal", "mod"):
            if value := _str(gear.get(key)):
                groups[key].append(value)
    section_names = SECTIONS
    if raw and gear.get("editedImport"):
        section_names = {**SECTIONS, "properties": ("Eigenschaften beim Import", "Imported properties")}
    sections = tuple((labels[language == "en"], tuple(_display_line(line, language) for line in lines))
                     for key, labels in section_names.items() if (lines := groups.get(key)))
    rarity = "unique" if unique and not raw else item_rarity(gear, record)
    explicit_name = _str(gear.get("sourceName"))
    title_record = _items().get(explicit_name, {}) if explicit_name else record
    if explicit_name and canonical_base(explicit_name) == base_name:
        title_record = _items().get(base_name, {})
    title = title_record.get("name") or name
    if language == "de":
        title = title_record.get("de") or _gear_data()["deNames"].get(title, title)
        base_title = _items().get(base_name, {}).get("de") or source["deNames"].get(base_name, base_name)
    else:
        base_title = base_name
    icon = record.get("imageLocal") if record.get("kind") == "currency" else None
    icon = icon or item_art_ref(record.get("name") or name, base_name)
    return ItemCard(title, base_title if base_title != title else "", rarity, icon, sections,
                    RARITIES[rarity][language == "en"] if title else "")


def render_item_card(parent, card, theme, *, px=lambda n: n, font=None, gear=None, language="en", app=None):
    """Build a width-responsive, read-only card with game rarity colours."""
    color = rarity_color(card.rarity)
    frame = tk.Frame(parent, bg=theme.panel, highlightthickness=px(1), highlightbackground=color)
    frame.columnconfigure(0, weight=1)
    labels = []

    def label(parent, text, fg, size, weight="normal", **kwargs):
        face = font(size, weight) if font else ("TkDefaultFont", size, weight)
        widget = tk.Label(parent, text=text, fg=fg, bg=parent.cget("bg"), font=face, bd=0,
                          justify="left", anchor="w", wraplength=px(170), **kwargs)
        labels.append(widget)
        return widget

    head = tk.Frame(frame, bg=theme.control, padx=px(9), pady=px(6))
    head.grid(row=0, column=0, sticky="ew")
    head.columnconfigure(1, weight=1)
    icon = build_icon(head, card.icon, size=px(40)) if card.icon else None
    if icon:
        image = tk.Label(head, bg=theme.control, image=icon, bd=0)
        image.image = icon
        image.grid(row=0, column=0, rowspan=2, padx=(0, px(8)))
    header_row = 0
    if card.title:
        label(head, card.title, color, 12, "bold").grid(row=0, column=1, sticky="ew")
        header_row = 1
    subtitle = "  ·  ".join(filter(None, (card.base, card.rarity_label)))
    if subtitle:
        label(head, subtitle, theme.text, 9).grid(row=header_row, column=1, sticky="ew")
    if not (card.title or subtitle or icon):
        head.grid_remove()
    first_section = 1
    if gear is not None:
        from poe2_item_actions_ui import render_item_actions

        actions = render_item_actions(frame, gear, theme, language, px, app, card=card)
        if actions is not None:
            actions.grid(row=1, column=0, sticky="ew")
            first_section = 2
    for row, (heading, lines) in enumerate(card.sections, first_section):
        section = tk.Frame(frame, bg=theme.panel, padx=px(9), pady=px(3))
        section.grid(row=row, column=0, sticky="ew")
        label(section, heading, theme.accent, 9, "bold").pack(fill="x")
        tone = theme.text
        if heading in (*SECTIONS["explicit"], *SECTIONS["implicit"], *SECTIONS["enchant"]):
            tone = "#aaaaff"
        elif heading in SECTIONS["desecrated"]:
            tone = "#d1aeed"
        elif heading in SECTIONS["rune"]:
            tone = "#9cd4d1"
        label(section, "\n".join(lines), tone, 10).pack(fill="x")

    def wrap(event):
        for child in labels:
            inset = 74 if icon and child.master == head else 24
            width = max(px(40), event.width - px(inset))
            if child.winfo_pixels(child.cget("wraplength")) != width:
                child.configure(wraplength=width)

    frame.bind("<Configure>", wrap)
    return frame
