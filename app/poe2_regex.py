"""Native port of the Buildschmiede PoE 2 search generator."""

import json
from pathlib import Path
from typing import NamedTuple


CATALOG = json.loads(Path(__file__).with_name("poe2_regex_catalog.json").read_text(encoding="utf-8"))
LIMIT = 250
PROFILE_LIMIT = 262144
CATEGORIES = {
    "Vendor": ("Händler & Lager", "Vendor & stash"),
    "Waystones": ("Wegsteine", "Waystones"),
    "Tablet": ("Tafeln", "Tablets"),
    "Relic": ("Relikte", "Relics"),
}
RARITIES = {"Normal": ("Normal", "Normal"), "Magic": ("Magisch", "Magic"), "Rare": ("Selten", "Rare")}
TIERS = {"Waystones_low_tier": "[1-5]", "Waystones_mid_tier": "([6-9]|10)", "Waystones_top_tier": "1[1-6]"}
PRESETS = (
    ("Akt 1 · Lauftempo", "Act 1 · Movement Speed", "Boots", "MovementVelocity1", "want"),
    ("Lager durchsuchen", "Search stash", None, None, "want"),
    ("Gefährlicher Wegstein-Mod", "Dangerous Waystone mod", "Waystones_low_tier", "MapPlayerRecoveryRate1", "avoid"),
    ("Tablet · Wegsteine farmen", "Tablet · Farm Waystones", "Irradiated_Tablet", "TowerMapDroppedMapsIncrease", "want"),
)


class Bound(NamedTuple):
    key: str
    de: str
    en: str
    pattern_de: str
    pattern_en: str
    cap: int


BOUNDS = {
    "Vendor": (
        Bound("ilvl", "Gegenstandsstufe", "Item level", "gegenstandsstufe: #", "item level: #", 100),
        Bound("level", "Benötigte Stufe", "Required level", "(?:^stufe: |erfordert.*stufe )#",
              "(?:^level: |requires.*level )#", 100),
        Bound("sockets", "Sockel", "Sockets", "sockel: ", "sockets: ", 6),
    ),
    "Waystones": (
        Bound("tier", "Wegsteinstufe", "Waystone tier", r"level #\)", r"tier #\)", 16),
        Bound("revives", "Wiederbelebungen", "Revives", "wiederbelebungen: #", "revives?: #", 6),
        Bound("rarity", "Gegenstandsseltenheit", "Item rarity", r"gegenstandsseltenheit: \+?#", r"item rarity: \+?#", 999),
        Bound("pack", "Gruppengröße", "Pack size", r"gruppengröße: \+?#", r"pack size: \+?#", 999),
        Bound("mr", "Monsterseltenheit", "Monster rarity", r"monsterseltenheit: \+?#", r"monster rarity: \+?#", 999),
        Bound("eff", "Schlagkraft der Monster", "Monster effectiveness",
              r"(?:schlagkraft der monster|monsterschlagkraft): \+?#", r"monster effectiveness: \+?#", 999),
        Bound("drop", "Wegstein-Dropchance", "Waystone drop chance",
              r"(?:wegstein-dropchance|fallchance für wegsteine): \+?#", r"waystone drop chance: \+?#", 9999),
    ),
    "Tablet": (
        Bound("uses", "Verbleibende Nutzungen", "Uses remaining",
              "(?:verbleibende (?:nutzungen|verwendungen): #|# (?:nutzungen|verwendungen) verbleibend)",
              "(?:uses remaining: #|# uses? remaining)", 999),
    ),
    "Relic": (),
}


def category_of(base):
    if base == "Vendor" or base.startswith("Waystones"):
        return "Vendor" if base == "Vendor" else "Waystones"
    return "Tablet" if base.endswith("_Tablet") else "Relic"


def type_names(category, client):
    if category == "Vendor":
        return {key: names[client == "en"] for key, names in CATALOG["Vendor"]["classes"].items()}
    return {key: base[client] for key, base in CATALOG.items() if category_of(key) == category}


def fresh(category="Vendor"):
    return dict(cat=category, types=[], rarities=[], bounds={}, rules=[], groups={},
                mode="all", state="", delirious=False, custom="", round=False)


def available(profile):
    category, types = profile["cat"], profile["types"]
    keys = ("Vendor",) if category == "Vendor" else types or type_names(category, "en")
    result = {}
    for key in keys:
        for mod in CATALOG[key]["mods"]:
            if mod.get("searchUnavailable") or mod["id"] in {*RARITIES, "ItemLevel"}:
                continue
            if category == "Vendor" and types and "classes" in mod and not set(types).intersection(mod["classes"]):
                continue
            result.setdefault(mod["en"], mod)
    return result


def preset_profile(preset):
    _, _, item, mod_id, use = preset
    if item is None:
        return fresh()
    category = "Vendor" if item in CATALOG["Vendor"]["classes"] else category_of(item)
    base = CATALOG["Vendor"] if category == "Vendor" else CATALOG[item]
    mod = next(mod for mod in base["mods"] if mod["id"] == mod_id)
    result = fresh(category)
    result["types"] = [item]
    result["rules"] = [{"key": mod["en"], "use": use, "min": 0}]
    return result


def digit_range(low, high):
    """Generate the same decimal-range pattern as the website, including its grouping."""
    if low == high:
        return low
    if len(low) != len(high):
        return "(" + "|".join(
            digit_range(low if length == len(low) else "1" + "0" * (length - 1),
                        high if length == len(high) else "9" * length)
            for length in range(len(low), len(high) + 1)
        ) + ")"
    if low[0] == high[0]:
        return low[0] + digit_range(low[1:], high[1:])
    if len(low) == 1:
        return f"[{low}-{high}]"

    width = len(low) - 1
    first, last = int(low[0]), int(high[0])
    zeros, nines = "0" * width, "9" * width
    lower_partial, upper_partial = low[1:] != zeros, high[1:] != nines
    parts = []
    if lower_partial:
        parts.append(low[0] + digit_range(low[1:], nines))
    a, b = first + lower_partial, last - upper_partial
    if a <= b:
        parts.append((str(a) if a == b else f"[{a}-{b}]") + r"\d" * width)
    if upper_partial:
        parts.append(high[0] + digit_range(zeros, high[1:]))
    return parts[0] if len(parts) == 1 else "(" + "|".join(parts) + ")"


def number_from(minimum):
    digits = str(minimum)
    parts = [digits]
    for index in reversed(range(len(digits))):
        next_digit = int(digits[index]) + 1
        if next_digit <= 9:
            part = "9" if next_digit == 9 else f"[{next_digit}-9]"
            parts.append(digits[:index] + part + r"\d" * (len(digits) - index - 1))
    parts.append(r"\d" * (len(digits) + 1) + r"\d*")
    return r"\b(" + "|".join(parts) + r")\b"


def escape(text):
    return "".join("\\" + char if char in ".*+?^$(){}|[]\\" else char for char in text)


def rounded_minimum(value, profile):
    return value // 10 * 10 if profile["round"] and value >= 10 else value


def query_length(text):
    return len(text.encode("utf-16-le")) // 2


def search_query(profile, client):
    category, types = profile["cat"], profile["types"]
    german = client == "de"
    terms = []

    def add(pattern, avoid=False):
        if pattern:
            terms.append('"' + ("!" if avoid else "") + pattern + '"')

    if category == "Waystones":
        add("wegstein" if german else "waystone")
        if 0 < len(types) < len(TIERS):
            add(("level " if german else "tier ") + "(" + "|".join(TIERS[key] for key in types) + r")\)")
    elif types:
        names = type_names(category, client)
        names_pattern = "|".join(escape(names[key].lower()) for key in types)
        if category == "Vendor":
            add(("gegenstandsklasse: " if german else "item class: ") + f"({names_pattern})$")
        else:
            add(names_pattern)
    elif category == "Tablet":
        add("tafel" if german else "tablet")
    elif category == "Relic":
        add("relikt" if german else "relic")

    if profile["rarities"]:
        rarities = "|".join(RARITIES[key][not german].lower() for key in profile["rarities"])
        add(("seltenheit: " if german else "rarity: ") + f"({rarities})$")
    if profile["state"]:
        add("^verderbt$" if german else "^corrupted$", profile["state"] == "clean")
    if profile["delirious"]:
        add("deliri" if german else "delirious")

    for bound in BOUNDS[category]:
        lower, upper = profile["bounds"].get(bound.key, ("", ""))
        if lower == upper == "":
            continue
        low, high = rounded_minimum(int(lower or 0), profile), int(upper or bound.cap)
        if not 0 <= low <= high <= bound.cap:
            raise ValueError(bound.key)
        pattern = bound.pattern_de if german else bound.pattern_en
        if bound.key == "sockets":
            if not low:
                add(pattern + rf"\S+(?: +\S+){{{high},}}$", avoid=True)
            else:
                add(pattern + rf"\S+(?: +\S+){{{low - 1},{high - 1}}}$")
        else:
            add(pattern.replace("#", r"\b" + digit_range(str(low), str(high)) + r"\b"))

    mods = available(profile)
    wanted, avoided = {}, []
    for rule in profile["rules"]:
        mod = mods.get(rule["key"])
        if mod is None:
            continue
        minimum = rounded_minimum(rule["min"], profile)
        pattern = mod.get(client + ("Minimum" if minimum else "Pattern"))
        if not pattern:
            raise ValueError(rule["key"])
        pattern = pattern.replace("#", number_from(minimum) if minimum else r"\d+")
        if rule["use"] == "avoid":
            avoided.append(pattern)
        else:
            wanted.setdefault(mod.get("group", "Modifiers"), []).append(pattern)
    if profile["mode"] == "any":
        add("|".join(pattern for group in wanted.values() for pattern in group))
    else:
        for group, patterns in wanted.items():
            if profile["groups"].get(group) == "any":
                add("|".join(patterns))
            else:
                for pattern in patterns:
                    add(pattern)
    add("|".join(avoided), avoid=True)
    if profile["custom"].strip():
        terms.append(profile["custom"].strip())
    return " ".join(terms)


def load_export(data):
    if not isinstance(data, dict) or data.get("format") != "buildschmiede-farming" or data.get("version") != 2:
        raise ValueError("profile")
    source = data.get("profile")
    if not isinstance(source, dict) or not isinstance(source.get("cat"), str) or source["cat"] not in CATEGORIES:
        raise ValueError("category")
    profile = fresh(source["cat"])
    profile.update({key: source.get(key, default) for key, default in profile.items()})
    if any(type(profile[key]) is not schema for key, schema in (
        ("types", list), ("rarities", list), ("bounds", dict), ("rules", list), ("groups", dict),
        ("mode", str), ("state", str), ("delirious", bool), ("custom", str), ("round", bool),
    )):
        raise ValueError("profile fields")
    if (profile["mode"] not in ("all", "any") or profile["state"] not in ("", "clean", "corrupt")
            or any(mode not in ("all", "any") for mode in profile["groups"].values())):
        raise ValueError("profile options")
    profile["custom"].encode("utf-8")
    for key, allowed in (("types", type_names(profile["cat"], "en")), ("rarities", RARITIES)):
        if any(not isinstance(name, str) or name not in allowed for name in profile[key]):
            raise ValueError(key)
        profile[key] = list(dict.fromkeys(profile[key]))
    for key, bounds in profile["bounds"].items():
        if (not isinstance(bounds, list) or len(bounds) != 2
                or any(value != "" and not (isinstance(value, (str, int)) and str(value).isascii()
                                            and str(value).isdecimal() and len(str(value)) <= 4) for value in bounds)):
            raise ValueError(key)
        profile["bounds"][key] = [str(value) for value in bounds]
    seen, mods = set(), available(profile)
    for rule in profile["rules"]:
        if (not isinstance(rule, dict) or not isinstance(rule.get("key"), str)
                or rule["key"] in seen or rule["key"] not in mods
                or rule.get("use") not in ("want", "avoid")
                or type(rule.get("min")) is not int or not 0 <= rule["min"] <= 9999):
            raise ValueError("rule")
        seen.add(rule["key"])
    return profile


def export_profile(profile, name, client):
    return dict(format="buildschmiede-farming", version=2, name=name, profile=profile,
                search=search_query(profile, client))
