"""Offline search and filter rules for the Buildschmiede affix database."""

from collections import defaultdict
from dataclasses import dataclass, replace
from functools import lru_cache
import re
import unicodedata

from poe2_lexicon import base_items, catalogue, german_stat_translations


@dataclass
class AffixFilters:
    view: str = "affixes"
    query: str = ""
    category: str = ""
    base: str = ""
    profile: str = ""
    database: str = ""
    pool: str = ""
    side: str = ""
    tag: str = ""
    min_level: int = 0
    max_level: int = 0
    sort: str = ""


WEAPONS = ("axe", "bow", "claw", "crossbow", "dagger", "flail", "mace", "sceptre", "spear", "staff", "sword", "talisman", "traptool", "wand")
ARMOUR = ("body", "helmet", "gloves", "boots")
OFFHAND = ("shield", "focus", "quiver")
JEWELLERY = ("amulet", "ring", "belt")
# Labels and base/tag rules in the website catalogue, in its category order.
CATEGORIES = {
    "boots": ("Stiefel", "Boots", ("boots",), "", ""),
    "body": ("Brustrüstungen", "Body armour", ("body",), "", ""),
    "helmet": ("Helme", "Helmets", ("helmet",), "", ""),
    "gloves": ("Handschuhe", "Gloves", ("gloves",), "", ""),
    "shield": ("Schilde", "Shields", ("shield",), "shield", ""),
    "buckler": ("Parierschilde", "Bucklers", ("shield",), "buckler", ""),
    "focus": ("Foki", "Foci", ("focus",), "", ""),
    "quiver": ("Köcher", "Quivers", ("quiver",), "", ""),
    "onehand-axe": ("Äxte (Einhand)", "Axes (one-handed)", ("axe",), "onehand", ""),
    "onehand-sword": ("Schwerter (Einhand)", "Swords (one-handed)", ("sword",), "onehand", ""),
    "onehand-mace": ("Streitkolben (Einhand)", "Maces (one-handed)", ("mace",), "onehand", ""),
    "dagger": ("Dolche", "Daggers", ("dagger",), "", ""),
    "claw": ("Klauen", "Claws", ("claw",), "", ""),
    "wand": ("Zauberstäbe", "Wands", ("wand",), "", ""),
    "sceptre": ("Zepter", "Sceptres", ("sceptre",), "", ""),
    "spear": ("Speere", "Spears", ("spear",), "", ""),
    "flail": ("Flegel", "Flails", ("flail",), "", ""),
    "twohand-axe": ("Äxte (Zweihand)", "Axes (two-handed)", ("axe",), "twohand", ""),
    "twohand-sword": ("Schwerter (Zweihand)", "Swords (two-handed)", ("sword",), "twohand", ""),
    "twohand-mace": ("Streitkolben (Zweihand)", "Maces (two-handed)", ("mace",), "twohand", ""),
    "bow": ("Bögen", "Bows", ("bow",), "", ""),
    "crossbow": ("Armbrüste", "Crossbows", ("crossbow",), "", ""),
    "staff": ("Stäbe", "Staves", ("staff",), "staff", ""),
    "warstaff": ("Kampfstäbe", "Quarterstaves", ("staff",), "warstaff", ""),
    "talisman": ("Talismane", "Talismans", ("talisman",), "", ""),
    "traptool": ("Fallen", "Traps", ("traptool",), "", ""),
    "belt": ("Gürtel", "Belts", ("belt",), "", ""),
    "amulet": ("Amulette", "Amulets", ("amulet",), "", ""),
    "ring": ("Ringe", "Rings", ("ring",), "", ""),
    "charms": ("Phiolen", "Charms", ("flask",), "utility_flask", "charms"),
    "jewels": ("Juwelen", "Jewels", ("jewel",), "", "jewels"),
    "life-flasks": ("Lebensfläschchen", "Life flasks", ("flask",), "life_flask", "flasks"),
    "mana-flasks": ("Manafläschchen", "Mana flasks", ("flask",), "mana_flask", "flasks"),
    "waystones": ("Wegsteine", "Waystones", (), "", "waystones"),
    "tablets": ("Tablets", "Tablets", (), "", "tablets"),
    "relics": ("Relikte", "Relics", (), "", ""),
    "league": ("Liga-Mechaniken", "League mechanics", (), "", "league"),
    "corruption": ("Verderbnis", "Corruption", (), "", "corruption"),
    "unique": ("Einzigartige Items", "Unique items", (), "", ""),
    "currency": ("Währung", "Currency", (), "", ""),
    "onehand": ("Alle Einhandwaffen", "All one-handed weapons", WEAPONS, "onehand", ""),
    "twohand": ("Alle Zweihandwaffen", "All two-handed weapons", WEAPONS, "twohand", ""),
    "armour": ("Alle Rüstungen", "All armour", ARMOUR, "", ""),
    "offhand": ("Alle Nebenhandbasen", "All off-hand bases", OFFHAND, "", ""),
    "weapons": ("Alle Waffen", "All weapons", WEAPONS, "", ""),
    "equipment": ("Ausrüstung", "Equipment", WEAPONS + ARMOUR + OFFHAND + JEWELLERY, "", ""),
    "jewellery": ("Schmuck", "Jewellery", JEWELLERY, "", ""),
    "flasks": ("Fläschchen", "Flasks", ("flask",), "", "flasks"),
}
ITEM_KINDS = {"unique": "unique", "currency": "currency", "waystones": "waystone", "tablets": "tablet"}
DB_GROUPS = {
    "onehand-axe": "One_Hand_Axes", "onehand-sword": "One_Hand_Swords", "onehand-mace": "One_Hand_Maces",
    "twohand-axe": "Two_Hand_Axes", "twohand-sword": "Two_Hand_Swords", "twohand-mace": "Two_Hand_Maces",
    "dagger": "Daggers", "claw": "Claws", "wand": "Wands", "sceptre": "Sceptres", "spear": "Spears", "flail": "Flails",
    "bow": "Bows", "crossbow": "Crossbows", "staff": "Staves", "warstaff": "Quarterstaves", "talisman": "Talismans",
    "traptool": "Traps", "focus": "Foci", "quiver": "Quivers", "buckler": "Bucklers", "amulet": "Amulets",
    "ring": "Rings", "belt": "Belts", "life-flasks": "Life_Flasks", "mana-flasks": "Mana_Flasks", "charms": "Charms",
}
DB_ARMOUR = {"body": "Body_Armours", "helmet": "Helmets", "gloves": "Gloves", "boots": "Boots", "shield": "Shields"}
PROFILE_TAG = re.compile(r"((?:str|dex|int)(?:_(?:str|dex|int))*)_(?:armour|shield)$")
JEWEL_PROFILE = re.compile(r"(?:Time-Lost_)?(?:Ruby|Emerald|Sapphire|Diamond)$")
QUICK_TAGS = ("life", "mana", "damage", "attack", "caster", "defences", "armour", "energy_shield", "evasion",
              "resistance", "fire", "cold", "lightning", "chaos", "physical", "elemental", "speed", "attribute", "critical", "minion")
TAG_LABELS = dict(zip(QUICK_TAGS, ("Leben", "Mana", "Schaden", "Angriff", "Zauber", "Verteidigung", "Rüstung",
                                   "Energieschild", "Ausweichen", "Widerstand", "Feuer", "Kälte", "Blitz", "Chaos",
                                   "Physisch", "Elementar", "Tempo", "Attribute", "Kritisch", "Kreaturen")))
TAG_LABELS.update(block="Block", ailment="Beeinträchtigung", resource="Ressource", gem="Gemme")
SIDES = {"Prefix": ("Präfixe", "Prefixes"), "Suffix": ("Suffixe", "Suffixes"), "Other": ("Weitere Mods", "Other modifiers")}
POOLS = {
    "equipment": ("Ausrüstung", "Equipment"), "league": ("Liga-Mechaniken", "League mechanics"),
    "essence": ("Essenzen", "Essences"), "unveiling": ("Enthüllte Mods", "Unveiled modifiers"),
    "corruption": ("Verderbnis", "Corruption"), "tablets": ("Tablets", "Tablets"), "waystones": ("Wegsteine", "Waystones"),
    "jewels": ("Juwelen", "Jewels"), "flasks": ("Fläschchen", "Flasks"), "charms": ("Charms", "Charms"), "runes": ("Runen", "Runes"),
}
SECTIONS = {
    "Prefix": ("Basispräfixe", "Base prefixes"), "Suffix": ("Basissuffixe", "Base suffixes"),
    "desecrated": ("Entweihung", "Desecrated modifiers"), "abyss": ("Abgrund (Abyss)", "Abyss"),
    "breach": ("Riss (Breach)", "Breach"), **POOLS,
}
AFFIX_SORT = {"name": ("Name A–Z", "Name A–Z"), "level": ("Itemlevel ↓", "Item level ↓"),
              "tier": ("Tier (T1 zuerst)", "Tier (T1 first)"), "weight": ("Rollgewicht ↓", "Roll weight ↓")}
ITEM_SORT = {"name": AFFIX_SORT["name"], "requirement": ("Stufenanforderung ↓", "Required level ↓")}
QUERY_EXPANSIONS = {
    "bewegungsgeschwindigkeit": "movement speed", "maximales leben": "maximum life", "maximalem leben": "maximum life",
    "maximales mana": "maximum mana", "maximalem mana": "maximum mana", "bestrahlung": "irradiated", "runenschutz": "runic ward",
    "feuerwiderstand": "fire resistance", "kaltewiderstand": "cold resistance", "blitzwiderstand": "lightning resistance",
    "chaoswiderstand": "chaos resistance",
}


def _fold(text):
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(char)).strip()


def _searchable(values):
    return _fold(" ".join(str(value) for value in values if value is not None))


def _pretty(key):
    label = key.replace("_", " ")
    return label[:1].upper() + label[1:]


def tag_label(key, language):
    labels = catalogue().get("affixUi", {}).get("tagLabels", {}).get(key, {})
    if label := labels.get(language):
        return label
    if match := PROFILE_TAG.fullmatch(key):
        labels = ("Stärke", "Geschick", "Intelligenz") if language == "de" else ("Strength", "Dexterity", "Intelligence")
        attributes = match[1].split("_")
        if language == "de" and len(attributes) == 3:
            return "Alle Attribute"
        return (" / " if language == "de" else " + ").join(dict(zip(("str", "dex", "int"), labels))[part] for part in attributes)
    return TAG_LABELS.get(key, _pretty(key)) if language == "de" else _pretty(key)


def _item_in(category, row):
    if not category:
        return True
    if category in ITEM_KINDS:
        return row.get("kind") == ITEM_KINDS[category]
    _, _, types, tag, _ = CATEGORIES[category]
    if category == "shield" and "buckler" in row["tags"]:
        return False
    return row.get("type") in types and (not tag or tag in row["tags"])


def _pool(row):
    if "essence" in row["id"].lower():
        return "essence"
    return "unveiling" if "unveiled_mod" in row["tags"] else row["category"]


@lru_cache(maxsize=1)
def _mods():
    translations = german_stat_translations()
    return tuple((row, _pool(row), row["side"] if row["side"] in SIDES else "Other",
                  _searchable((row["id"], row["name"], row.get("de"), row["group"], *row["stats"],
                               *(row.get("statsDe") or (translations.get(line, "") for line in row["stats"])),
                               *row["bases"], *row["tags"], *(tag_label(key, "de") for key in row["tags"]),
                               *(tag_label(key, "en") for key in row["tags"])))) for row in catalogue()["mods"])


@lru_cache(maxsize=1)
def _items():
    return tuple((row, _searchable((row["name"], row.get("de"), row.get("base"), row.get("kind"), row.get("type"),
                                   row.get("item", {}).get("implicit"), *row.get("aliases", ()), *row.get("stats", ()),
                                   *row.get("description", {}).values(), *row["tags"],
                                   *(tag_label(key, "de") for key in row["tags"]),
                                   *(tag_label(key, "en") for key in row["tags"])))) for row in catalogue()["items"])


@lru_cache(maxsize=2)
def _all_tags(items):
    if items:
        return {tag for row in catalogue()["items"] for tag in row["tags"] if tag != "default"}
    tags = {tag for row in catalogue()["mods"] for tag in row["tags"]}
    tags.update(tag for profile in catalogue()["profiles"].values() for _, _, families in profile[4]
                for _, rows in families for row in rows for tag in row[6])
    return tags


@lru_cache(maxsize=2)
def _category_ids(item_view):
    data = catalogue()
    domains = {row["category"] for row in data["mods"]}
    candidates = data["items"] if item_view else base_items().values()
    return tuple(key for key, names in CATEGORIES.items() if any(_item_in(key, row) for row in candidates)
                 or (not item_view and (DB_GROUPS.get(key) in data["profiles"] or names[4] in domains or key == "relics")))


def options(filters, language):
    """Return id/label choices for each filter, scoped by the selected category/profile."""
    item_view = filters.view == "items"
    locale = int(language != "de")
    ui_locale = int(language == "en")
    category = filters.category
    data = catalogue()
    profiles = data["profiles"]
    options = {}
    options["category"] = tuple((key, CATEGORIES[key][locale]) for key in _category_ids(item_view))
    group_items = tuple(row for row in data["items"] if _item_in(category, row))
    armour = DB_ARMOUR.get(category)
    tags = {tag for row in group_items for tag in row["tags"] if PROFILE_TAG.fullmatch(tag)}
    if armour and not item_view:
        tags = {tag for tag in tags if f"{armour}_{PROFILE_TAG.fullmatch(tag)[1]}" in profiles}
    options["profile"] = tuple((key, tag_label(key, language)) for key in sorted(tags)) if category else ()
    if category and not CATEGORIES[category][2]:
        pool = CATEGORIES[category][4]
        bases = {base for row in data["mods"] if row["category"] == pool for base in row["bases"]}
    else:
        bases = {row["name"] for row in group_items if "kind" not in row and (not filters.profile or filters.profile in row["tags"])}
    base_records = base_items() if language == "de" else {}
    options["base"] = tuple(sorted(((key, base_records.get(key, {}).get("de") or key) for key in bases),
                                   key=lambda entry: (_fold(entry[1]), entry[0])))
    options["database"] = tuple((key, record[locale]) for key, record in profiles.items())
    options["pool"] = tuple((key, POOLS.get(key, (_pretty(key),) * 2)[ui_locale]) for key in sorted({pool for _, pool, _, _ in _mods()}))
    options["side"] = tuple((key, labels[ui_locale]) for key, labels in SIDES.items())
    options["tag"] = tuple(sorted(((key, tag_label(key, language)) for key in _all_tags(item_view)), key=lambda entry: (_fold(entry[1]), entry[0])))
    options["sort"] = tuple((key, labels[ui_locale]) for key, labels in (ITEM_SORT if item_view else AFFIX_SORT).items())
    return options


def _profile_keys(filters, profiles):
    if filters.database in profiles:
        return (filters.database,)
    base = base_items().get(filters.base, {})
    category = filters.category or base.get("type", "")
    tags = base.get("tags", ())
    armour = DB_ARMOUR.get(base.get("type") or category)
    profile = filters.profile or next((tag for tag in tags if PROFILE_TAG.fullmatch(tag)), "")
    if armour and profile:
        match = PROFILE_TAG.fullmatch(profile)
        if match and (key := "Bucklers" if "buckler" in tags else f"{armour}_{match[1]}") in profiles:
            return (key,)
    named = filters.base.replace(" ", "_")
    weapon = next((tag for tag in tags if tag in ("onehand", "twohand")), "")
    for key in (DB_GROUPS.get(category), named, DB_GROUPS.get(f"{weapon}-{base.get('type')}")):
        if key in profiles:
            return (key,)
    if category in DB_ARMOUR:
        return tuple(key for key in profiles if key.startswith(DB_ARMOUR[category] + "_"))
    if category == "jewels":
        return tuple(key for key in profiles if JEWEL_PROFILE.fullmatch(key))
    prefixes = {"waystones": "Waystones_"}
    suffixes = {"tablets": "_Tablet", "relics": "_Relic"}
    if category in prefixes:
        return tuple(key for key in profiles if key.startswith(prefixes[category]))
    if category in suffixes:
        return tuple(key for key in profiles if key.endswith(suffixes[category]))
    return ()


def _matches(text, words):
    return all(word in text for word in words)


def _filters_match(filters, level, tags, pool, side):
    return (not filters.tag or filters.tag in tags) and (not filters.min_level or level >= filters.min_level) and (
        not filters.max_level or level <= filters.max_level) and (not filters.pool or pool == filters.pool) and (
        not filters.side or side == filters.side)


def _variant(ident, name, stats, tags, level, tier, weight, **details):
    return {"id": ident, "name": name, "stats": tuple(stats), "tags": tuple(tag for tag in tags if tag != "default"),
            "level": level, "tier": tier, "weight": weight, "source": "", "profiles": (), "matching_rule": None,
            "weights": (), "bases": (), "excluded": (), "condition": "", "guaranteed": False, **details}


def _representative(variants):
    return min(variants, key=lambda row: (row["tier"] or float("inf"), -row["level"]))


def _family(ident, section, category, side, variants):
    first = _representative(variants)
    stats = first["stats"]
    profiles = {name for row in variants for name, _ in row["profiles"]}
    known = [row["weight"] for row in variants if type(row["weight"]) is int] if len(profiles) <= 1 else []
    return {"id": ident, "title": stats[0] if stats else first["name"] or first["id"], "section": section,
            "category": category, "side": side, "variants": tuple(variants), "tags": first["tags"],
            "max_level": max(row["level"] for row in variants), "weight": sum(known) if known else None,
            "partial_weight": bool(known and len(known) < len(variants))}


def _ordering(row, sort):
    if sort == "weight":
        return -(row["weight"] if row["weight"] is not None else -1)
    if sort == "name":
        return _fold(row["name"] or (row["stats"] or (row["id"],))[0])
    if sort == "tier":
        return row["tier"] or float("inf")
    return -row["level"]


def _profile_section(name, sample):
    if name in {"Base Prefix", "Base Suffix"}:
        return "tablets" if "Tablet" in sample else "waystones" if "Waystone" in sample else "equipment"
    if "Essence" in name:
        return "essence"
    if "Desecrated" in name:
        return "unveiling"
    return "corruption" if "Corrupt" in name else "league"


def _profile_results(filters, words, language, keys):
    profiles = catalogue()["profiles"]
    locale = int(language != "de")
    groups = defaultdict(dict)
    scope = replace(filters, pool="") if filters.pool in {"jewels", "flasks", "charms"} else filters
    for key in keys:
        record = profiles[key]
        name, source = record[locale], record[locale + 2]
        for section_de, section_en, families in record[4]:
            side = next((side for side in ("Prefix", "Suffix") if section_en.endswith(side)), "Other")
            pool = _profile_section(section_en, profiles[keys[0]][1])
            section = (section_de, section_en)[locale]
            for family, rows in families:
                for tier, level, names_en, names_de, stats_en, stats_de, tags, weight, ident in rows:
                    if not _filters_match(scope, level, tags, pool, side):
                        continue
                    if words and not _matches(_searchable((*names_en, *names_de, *stats_en, *stats_de, *tags, section)), words):
                        continue
                    name_choices = names_de if locale == 0 and names_de else names_en
                    stats = stats_de if locale == 0 and stats_de else stats_en
                    signature = (tier, level, tuple(names_en), tuple(names_de), tuple(stats_en), tuple(stats_de), tuple(tags), weight, ident)
                    variants = groups[section, section_en, pool, side, family]
                    row = variants.get(signature)
                    if row is None:
                        row = variants[signature] = _variant(ident or family, next(iter(name_choices), ""), stats, tags, level, tier, weight,
                                                            source=source, guaranteed=section_en.startswith("Liquid Emotions "))
                    association = (name, source)
                    if len(keys) > 1 and association not in row["profiles"]:
                        row["profiles"] += (association,)
    sections = defaultdict(list)
    for (section, section_en, pool, side, family), distinct in groups.items():
        rows = sorted(distinct.values(), key=lambda row: _ordering(row, filters.sort or "tier"))
        sections[section_en].append(_family(f"{section_en}:{family}", section, pool, side, rows))
    if filters.sort:
        for families in sections.values():
            families.sort(key=lambda result: _ordering(result if filters.sort == "weight" else result["variants"][0], filters.sort))
    return tuple(result for families in sections.values() for result in families)


def _rule(row, tags):
    return next((match for match in row.get("weights", ()) if match[0] == "default" or match[0] in tags), None)


def _section(row, pool, side):
    ident = row["id"].lower()
    if pool == "essence":
        return pool
    if pool == "unveiling" or "desecrat" in ident:
        return "desecrated"
    if re.search(r"amanamu|ulam[ae]n|kurgal|abyss", ident):
        return "abyss"
    if "breach" in ident:
        return "breach"
    return side if side != "Other" and pool in {"equipment", "jewels", "flasks", "charms"} else pool


def _mod_results(filters, words, language):
    translations = german_stat_translations() if language == "de" else {}
    category = CATEGORIES.get(filters.category)
    domain = category[4] if category else ""
    item = base_items().get(filters.base)
    possible = set()
    if not filters.base and ((category and category[2]) or filters.profile):
        possible = {frozenset(row["tags"]) for row in base_items().values() if _item_in(filters.category, row)
                    and (not filters.profile or filters.profile in row["tags"])}
    groups = defaultdict(list)
    sections = defaultdict(list)
    for row, pool, side, text in _mods():
        if not _filters_match(filters, row["level"], row["tags"], pool, side):
            continue
        if (domain and row["category"] != domain) or not _matches(text, words):
            continue
        matched = _rule(row, item["tags"]) if item else None
        if filters.base:
            applies = matched is not None and matched[1] > 0 if item and row.get("weights") else filters.base in row["bases"]
            if not applies:
                continue
        if possible and not any((rule := _rule(row, tags)) and rule[1] > 0 for tags in possible):
            continue
        stats = (row.get("statsDe") or [translations.get(line, line) for line in row["stats"]]) if language == "de" else None
        key = (row["category"], pool, side, row["group"] or row["id"])
        if key not in groups:
            sections[_section(row, pool, side)].append(key)
        name = (row.get("de") if language == "de" else None) or row["name"]
        groups[key].append(_variant(row["id"], name, stats or row["stats"], row["tags"], row["level"], None, None,
                                    source=row.get("source", ""), matching_rule=matched, weights=tuple(row.get("weights", ())),
                                    bases=tuple(row["bases"]), excluded=tuple(row.get("excluded", ())), condition=row.get("condition", "")))
    results = []
    ordered_sections = dict.fromkeys(("Prefix", "Suffix", *sections))
    for key in ordered_sections:
        families = []
        section = SECTIONS.get(key, (_pretty(key),) * 2)[language == "en"]
        for category, pool, side, ident in sections[key]:
            variants = groups[category, pool, side, ident]
            variants.sort(key=lambda row: (_ordering(row, filters.sort), -row["level"], _fold(row["id"])))
            families.append(_family(f"{category}:{pool}:{side}:{ident}", section, category, side, variants))
        families.sort(key=lambda family: (_ordering(family["variants"][0], filters.sort) if filters.sort else 0, _fold(family["title"])))
        results.extend(families)
    return tuple(results)


def search(filters, language):
    """Find complete items or grouped modifier families for the given filters."""
    item_view = filters.view == "items"
    query = _fold(filters.query).translate(str.maketrans("‑–—", "---"))
    if query and not filters.database:
        aliases = catalogue().get("affixUi", {}).get("categoryAliases", {})
        for category in _category_ids(item_view):
            if filters.category and category != filters.category:
                continue
            if any(_fold(label).translate(str.maketrans("‑–—", "---")) == query
                   for label in (*CATEGORIES[category][:2], *aliases.get(category, ()))):
                filters = replace(filters, category=category)
                query = ""
                break
    words = (query if item_view else QUERY_EXPANSIONS.get(query, query)).split()
    if item_view:
        rows = [row for row, text in _items() if _item_in(filters.category, row) and _matches(text, words)
                and (not filters.tag or filters.tag in row["tags"]) and (not filters.profile or filters.profile in row["tags"])]
        rows.sort(key=lambda row: (-(row.get("item", {}).get("req", {}).get("level", 0)) if filters.sort == "requirement" else 0,
                                   _fold(row["name"])))
        return tuple({"id": f"{row.get('kind', 'base')}:{row['name']}", "title": (row.get("de") or row["name"]) if language == "de" else row["name"],
                      "item": row} for row in rows)
    profiles = _profile_keys(filters, catalogue()["profiles"])
    return _profile_results(filters, words, language, profiles) if profiles else _mod_results(filters, words, language)
