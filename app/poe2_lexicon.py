"""The player-facing Website Lexicon and its offline game catalogues."""

from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re
from typing import NamedTuple
from urllib.parse import urlencode, urlsplit

from poe2_game_de import apply_game_de
import poe2_shared_game_data as shared
from poe2_passive_de import apply_passive_de, passive_records
from poe2_website_content import lexicon_index, validate_lexicon


LEXICON_URL = "https://buildschmiede.de/lexikon/"
DATA_DIR = Path(__file__).parent
GROUPS = {
    "terms": ("Begriffe", "Begriffe", "Terms"),
    "league": ("Liga-Mechaniken", "Liga-Mechaniken", "League mechanics"),
    "currency": ("Währungen & Materialien", "Währungen & Materialien", "Currencies & Materials"),
    "skills": ("Fertigkeiten", "Fertigkeiten", "Skills"),
    "supports": ("Unterstützungen", "Unterstützungen", "Support Gems"),
    "passives": ("Passive", "Passive", "Passives"),
    "items": ("Gegenstände", "Gegenstände", "Items"),
    "mods": ("Affixe", "Affixe", "Affixes"),
}
MECHANICS_LABELS = ("Spielmechaniken", "Spielmechaniken", "Game mechanics")
TOPICS = {
    "currency": ("Währung & Gemmen", "Währung & Gemmen", "Currency & Gems"),
    "normal": ("Ausrüstung", "Ausrüstung", "Equipment"),
    "gem": ("Fertigkeiten & Mechaniken", "Skills & Mechaniken", "Skills & Mechanics"),
    "support": ("Unterstützungsgemmen", "Supports", "Supports"),
    "mod": ("Werte & Schaden", "Werte & Schaden", "Stats & Damage"),
    "info": ("Orientierung & Endspiel", "Orientierung & Endgame", "Navigation & Endgame"),
    "quest": ("Aufgaben & Prüfungen", "Quest & Prüfungen", "Quests & Trials"),
}
NODE_KINDS = {
    "skill": ("Aktive Fertigkeiten", "Aktive Skills", "Active skills"),
    "support": ("Unterstützungsgemmen", "Support-Gemmen", "Support gems"),
    "small": ("Kleine passive Fertigkeiten", "Kleine Passives", "Small passives"),
    "notable": ("Bedeutende passive Fertigkeiten", "Notables", "Notables"),
    "keystone": ("Schlüsselfertigkeiten", "Keystones", "Keystones"),
    "socket": ("Juwelensockel", "Juwelensockel", "Jewel sockets"),
}
ITEM_KINDS = {
    "base": ("Basisgegenstände", "Basen", "Base items"),
    "unique": ("Einzigartige Gegenstände", "Einzigartige Items", "Uniques"),
    "currency": ("Währung", "Währung", "Currency"),
    "waystone": ("Wegsteine", "Wegsteine", "Waystones"),
    "tablet": ("Tafeln", "Tablets", "Tablets"),
}
CURRENCY_FAMILIES = {
    "Currency": "Währung", "Essences": "Essenzen", "Delirium": "Delirium", "Breach": "Riss",
    "Abyss": "Abgrund", "Atziri's Temple": "Atziris Tempel", "Fragments": "Fragmente",
    "Runes": "Runen", "Ritual": "Ritual", "Soul Cores": "Seelenkerne", "Idols": "Götzen",
    "Uncut Gems": "Ungeschnittene Gemmen", "Expedition": "Expedition",
}
GERMAN_ITEM_TYPES = {
    "Amulet": "Amulett", "Belt": "Gürtel", "Body Armour": "Körperrüstung", "Boots": "Stiefel",
    "Bow": "Bogen", "Charm": "Phiole", "Claw": "Klaue", "Crossbow": "Armbrust", "Dagger": "Dolch",
    "Fishing Rod": "Angelrute", "Flail": "Flegel", "Flask": "Fläschchen", "Focus": "Fokus",
    "Gloves": "Handschuhe", "Helmet": "Helm", "Jewel": "Juwel",
    "One Hand Axe": "Einhandaxt", "One Hand Mace": "Einhandstreitkolben", "One Hand Sword": "Einhandschwert",
    "Quarterstaff": "Kampfstab", "Quiver": "Köcher", "Ring": "Ring", "Sceptre": "Zepter", "Shield": "Schild",
    "Spear": "Speer", "Staff": "Stab", "Talisman": "Talisman", "TrapTool": "Falle",
    "Two Hand Axe": "Zweihandaxt", "Two Hand Mace": "Zweihandstreitkolben", "Two Hand Sword": "Zweihandschwert",
    "Wand": "Zauberstab",
    "Any Martial Weapon": "Beliebige Kampfwaffe", "Any Melee Martial Weapon": "Beliebige Nahkampfwaffe",
    "Any non-Talisman Martial Weapon": "Beliebige Kampfwaffe (Talisman ausgenommen)",
    "Any non-Talisman Melee Martial Weapon": "Beliebige Nahkampfwaffe (Talisman ausgenommen)",
    "Unarmed": "Unbewaffnet", "Any Shield": "Beliebiger Schild", "Armoured Shield": "Rüstungsschild",
    "Any Melee Martial Weapon or Unarmed": "Beliebige Nahkampfwaffe oder unbewaffnet",
}
AFFIX_SIDES = {
    "Prefix": ("Präfix", "Präfix", "Prefix"),
    "Suffix": ("Suffix", "Suffix", "Suffix"),
    "Other": ("Weitere Modifikatoren", "Weitere Mods", "Other modifiers"),
}
VARIANT_MARKER = re.compile(r"\{variant:[^}]+\}\s*")
ENGINE_STAT = re.compile(r"^[a-z][a-z0-9_ ]+ \[\d+\]$")
ENGINE_NAME = re.compile(r"^\w+[._:]\w+[.\w:]*$")
CAMEL_ID = re.compile(r"[a-z][A-Z]")


def public_name(value, identifier=None):
    """Discard identifiers used as stand-ins for missing player-facing names."""
    if not value or value == identifier or ENGINE_NAME.fullmatch(value):
        return ""
    if " " not in value and len(CAMEL_ID.findall(value)) >= 2:
        return ""
    return value


def public_stats(values):
    return tuple(clean for value in values if (clean := VARIANT_MARKER.sub("", value).strip())
                 and not ENGINE_STAT.fullmatch(clean))


def lexicon_prose(value, language):
    """Hybrid uses German prose; other modes only show text in the selected language."""
    if not value:
        return ""
    return value.get(language) or (value.get("de", "") if language == "hybrid" else "")


def web_url(language, fragment="", **params):
    return LEXICON_URL + "?" + urlencode({"sprache": language, **params}) + ("#" + fragment if fragment else "")


@lru_cache(maxsize=1)
def league_guides():
    with (DATA_DIR / "shared-data" / "league-mechanics.v1.json").open(encoding="utf-8") as source:
        document = json.load(source)
    return {row["id"]: {**row, "patch": document["patch"]} for row in document["entries"]}


@lru_cache(maxsize=1)
def lexicon_guides():
    path = DATA_DIR / "shared-data" / "lexicon-guides.v1.json"
    try:
        with path.open(encoding="utf-8") as source:
            data = json.load(source)
    except (OSError, ValueError):
        return {}, {}
    if isinstance(data, dict) and data.get("schema") == "buildschmiede.lexicon-guides.v1":
        terms, targets = data.get("terms"), data.get("targets")
        if isinstance(terms, dict) and isinstance(targets, dict):
            return terms, targets
    return {}, {}


@lru_cache(maxsize=1)
def lexicon_practice():
    with (DATA_DIR / "poe2_lexicon_practice.json").open(encoding="utf-8") as source:
        return json.load(source)


@lru_cache(maxsize=1)
def bundled_lexicon():
    doc = shared.current(shared.LEXICON)
    entries = lexicon_index(validate_lexicon(deepcopy(doc)))
    for entry in entries.values():
        entry.setdefault("slug",entry["id"].removeprefix("website.").replace(".","-").replace("_","-"))
        entry.setdefault("topic", entry.get("role","normal"))
        if "icon" in entry:
            entry["imageLocal"] = shared.native_ref(entry)
            entry.pop("icon")
    return entries


def merge_published_lexicon(remote):
    """Update editorial fields from the validated feed and retain offline articles by ID."""
    bundled = bundled_lexicon()
    if not remote:
        return bundled
    merged = dict(bundled)
    slugs = {entry["slug"]: ident for ident, entry in bundled.items()}
    local = shared.local_editorial_changes(shared.LEXICON,shared.current(shared.LEXICON))
    for new in remote["entries"]:
        remote_id = new["id"]
        url = urlsplit(new.get("url") or "")
        anchor = url.fragment.removeprefix("begriff-") if url.fragment.startswith("begriff-") else ""
        if not anchor and url.path.startswith(("/lexikon/", "/begriff/")):
            anchor = url.path.strip("/").rsplit("/", 1)[-1]
        ident = remote_id if remote_id in bundled else slugs.get(anchor, remote_id)
        old = merged.get(ident, {})
        if not old and not (new.get("summary") or new.get("url")):
            continue
        titles = {language: name for language, value in new["title"].items()
                  if (name := public_name(value, remote_id))}
        if not old and not titles:
            continue
        merged[ident] = {
            **old,
            "id": ident,
            "title": {**old.get("title", {}), **titles},
            "summary": {**old.get("summary", {}), **(new.get("summary") or {})},
            "aliases": tuple(dict.fromkeys((*old.get("aliases", ()), *(new.get("aliases") or ())))),
            "url": new.get("url") or old.get("url"),
        }
    for ident, fields in local.items():
        # A manually edited local field retains precedence over stale cached REST content.
        if ident in merged:
            for field in ("title","summary","aliases","url"):
                if field in fields:
                    merged[ident][field] = fields[field]
    return merged


@lru_cache(maxsize=1)
def catalogue():
    with gzip.open(DATA_DIR / "poe2_lexicon_catalog.json.gz", "rt", encoding="utf-8") as source:
        data = json.load(source)
    with gzip.open(DATA_DIR / "poe2_currency_catalog.json.gz", "rt", encoding="utf-8") as source:
        currencies = json.load(source)["items"]
    data["items"] = [row for row in data["items"] if row.get("kind") != "currency"] + shared.currency_rows(currencies)
    supplement = shared.current(shared.TRANSLATIONS)
    apply_game_de(data,{**supplement,"granted":deepcopy(supplement.get("granted",{}))})
    apply_passive_de(data)
    shared.localized_game_rows(data,supplement)
    return data


@lru_cache(maxsize=1)
def _item_availability():
    with (DATA_DIR / "poe2_lexicon_availability.json").open(encoding="utf-8") as source:
        data = json.load(source)
    return data["excluded"], frozenset(data["verifiedReferenceCurrencies"])


def lexicon_item_available(row):
    if row.get("kind") == "currency" and type(row.get("visible")) is bool:
        return row["visible"]
    excluded, verified = _item_availability()
    kind = row.get("kind") or "base"
    ident = row["currencyId"] if kind == "currency" else row["name"]
    return ident not in excluded.get(kind, ()) and (not row.get("referenceOnly") or ident in verified)


@lru_cache(maxsize=1)
def german_stat_translations():
    """Exact, unambiguous German stat lines shared by the offline catalogues."""
    data = catalogue()
    candidates = defaultdict(set)

    def add_pair(original, german):
        if len(original) == len(german):
            for en, de in zip(original, german):
                en_line, de_line = public_stats((en,)), public_stats((de,))
                if en_line and de_line and en_line != de_line:
                    candidates[en_line[0]].add(de_line[0])

    for row in data["mods"]:
        add_pair(row["stats"], row.get("statsDe", ()))
    for _, row in passive_records(data):
        if row.get("statsDe"):
            add_pair(row.get("stats", ()), row["statsDe"])
    for profile in data["profiles"].values():
        for _, _, families in profile[4]:
            for _, rows in families:
                for variant in rows:
                    add_pair(variant[4], variant[5])
    result = {original: next(iter(names)) for original, names in candidates.items() if len(names) == 1}
    for origin, translated in data.get("plannerStatTranslations", {}).items():
        original = public_stats((origin,))
        german = public_stats((translated,))
        if original and german and original != german:
            result[original[0]] = german[0]
    return result


def display_stats(values, language, *, german=(), hybrid=()):
    if language == "de":
        if german:
            return public_stats(german)
        translations = german_stat_translations()
        return tuple(translations.get(line, line) for line in public_stats(values))
    return public_stats((hybrid if language == "hybrid" else ()) or values)


@lru_cache(maxsize=1)
def base_items():
    return {row["name"]: row for row in catalogue()["items"] if "kind" not in row}


def affix_weight_rule(row, base):
    tags = base["tags"]
    return next((rule for rule in row.get("weights", ()) if rule[0] == "default" or rule[0] in tags), None)


def affix_weight(row, base):
    rule = affix_weight_rule(row, base)
    return rule[1] if rule else None


def affix_applies(row, base):
    if (kind := base.get("kind")) in {"waystone", "tablet"}:
        names = {kind.title() + "s", base["name"], base.get("modBase")}
        return row["category"] == kind + "s" and not names.isdisjoint(row["bases"])
    if row.get("weights"):
        return (affix_weight(row, base) or 0) > 0
    return base["name"] in row["bases"]


def node_rows(data):
    """Fold identical small-passive effects together as the website's Lexicon does."""
    for ident, row in data["skills"].items():
        yield "skill", ident, row, None
    for ident, row in data.get("supports", {}).items():
        yield "support", ident, row, None
    families = {}
    for ident, row in data["nodes"].items():
        kind, stats = row["type"], row.get("stats")
        if kind != "small" or not stats:
            yield kind, ident, row, None
            continue
        key = (row["name"], tuple(stats))
        if key not in families:
            families[key] = (ident, row.copy(), Counter())
        _, representative, positions = families[key]
        for field in ("de", "statsDe", "statsHybrid"):
            if row.get(field) and not representative.get(field):
                representative[field] = row[field]
        if row.get("aliases"):
            representative["aliases"] = list(dict.fromkeys((*representative.get("aliases", ()), *row["aliases"])))
        positions[row.get("class") or ""] += 1
    for ident, row, positions in families.values():
        yield "small", ident, row, positions


def affix_rows(data):
    groups = defaultdict(list)
    for row in data["mods"]:
        groups[row["category"], row["side"], row["group"] or row["id"]].append(row)
    for rows in groups.values():
        yield sorted(rows, key=lambda row: -row["level"])


class ProfileVariant(NamedTuple):
    tier: int | str | None
    level: int
    names_en: tuple[str, ...]
    names_de: tuple[str, ...]
    stats_en: tuple[str, ...]
    stats_de: tuple[str, ...]
    weight: int | None
    ident: str
    tags: tuple[str, ...]


def profile_rows(data, profile_ids):
    for profile_id in profile_ids:
        profile = data["profiles"][profile_id]
        de, en, url_de, url_en, sections = profile[:5]
        for section_de, section_en, families in sections:
            for family, rows in families:
                variants = []
                for tier, level, names_en, names_de, stats_en, stats_de, tags, weight, ident, *rest in rows:
                    en_names = tuple(name for label in names_en if (name := public_name(label, ident)))
                    de_names = tuple(name for label in names_de if (name := public_name(label, ident)))
                    en_stats, de_stats = public_stats(stats_en), public_stats(stats_de)
                    if en_names or de_names or en_stats or de_stats:
                        public_tags = tuple(dict.fromkeys(tag for tag in tags if tag != "default"))
                        variants.append(ProfileVariant(tier, level, en_names, de_names, en_stats, de_stats,
                                                       weight, ident, public_tags))
                if variants:
                    yield family, (de, en), (url_de, url_en), (section_de, section_en), variants
