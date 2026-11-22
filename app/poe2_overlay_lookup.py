from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata

from poe2_language import CATALOG, LANGUAGES, boss_text, display_label, ui_text
from poe2_build_editorial import BUILD_TOPICS, editorial_lines, plain_guide_text, stage_view
from poe2_lexicon_explain import term_summary
from poe2_lexicon import (AFFIX_SIDES, CURRENCY_FAMILIES, GERMAN_ITEM_TYPES, GROUPS, ITEM_KINDS, NODE_KINDS, TOPICS, affix_rows,
                          bundled_lexicon, catalogue, german_stat_translations, lexicon_item_available, node_rows, profile_rows,
                          public_name, public_stats)
from poe2_r18_features import GUIDE, localized
from poe2_respec import RESPEC
from poe2_website_content import localized_text

CATEGORIES = {
    "lexicon": ("Lexikon", "Lexikon", "Glossary"),
    "campaign": ("Kampagne", "Kampagne", "Campaign"),
    "atlas": ("Atlas", "Atlas", "Atlas"),
    "boss": ("Bosse", "Bosse", "Bosses"),
    "shortcuts": ("Tastenkürzel", "Shortcuts", "Shortcuts"),
    "tips": ("Tipps", "Tipps", "Tips"),
    "tools": ("Werkzeuge", "Tools", "Tools"),
    "builds": ("Builds", "Builds", "Builds"),
}
AFFIX_TIPS = {
    "affixGuide": ("Affixe verstehen", "Affixe verstehen", "Understand affixes"),
    "itemGuide": ("Welche Gegenstände sind wertvoll?", "Welche Items sind wertvoll?", "Which drops are worth keeping?"),
    "weightGuide": ("Was bedeutet Rollgewicht?", "Was bedeutet Rollgewicht?", "How roll weights work"),
}
QUERY_LIMIT = 96
PAGE_SIZE = 16


def search_text(value):
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", normalized))


@dataclass(frozen=True)
class LookupEntry:
    category: str
    title: str
    target: object
    details: tuple[str, ...]
    name: str
    keywords: str
    aliases: tuple[str, ...] = ()


def make(category, title, target=None, details=(), aliases=(), content=()):
    aliases = tuple(dict.fromkeys(alias for alias in aliases if alias))
    return LookupEntry(category, title, target, tuple(details), search_text(title),
                       search_text(" ".join((title, *aliases, *details, *content))),
                       tuple(search_text(alias) for alias in aliases))


@lru_cache(maxsize=1)
def _hidden_item_titles():
    hidden, visible = set(), set()
    for row in catalogue()["items"]:
        titles = visible if lexicon_item_available(row) else hidden
        titles.update(search_text(name) for name in (row["name"], row.get("de")) if name)
    return hidden - visible


def published_terms(language, website):
    hidden = _hidden_item_titles()
    for entry in website.values():
        if any(search_text(title) in hidden for title in entry["title"].values() if title):
            continue
        title = localized_text(entry["title"], language)
        summary = term_summary(entry, language)
        topic = display_label(TOPICS.get(entry.get("topic"), GROUPS["terms"]), language)
        details = (summary, topic)
        names = (name for value in (*entry["title"].values(), *(entry.get("aliases") or ()))
                 if (name := public_name(value, entry["id"])))
        content = [text for paragraph in entry.get("article", ()) for text in paragraph.values()]
        content.extend((entry.get("summary") or {}).values())
        yield make("lexicon", title, {"group": "terms", "row": entry}, details, names, content)


@lru_cache(maxsize=12)
def catalogue_entries(language, group):
    data = catalogue()
    german = language == "de"
    entries = []
    if group == "nodes":
        for kind, ident, row, positions in node_rows(data):
            title = row.get("de") or row["name"] if german else row["name"]
            label = display_label(NODE_KINDS[kind], language)
            details = (label, "Originalname") if german and not row.get("de") else (label,)
            words = [row["name"], row.get("de") or "", row.get("weapon") or "", row.get("tags") or "",
                     row.get("family") or "", row.get("tagsDe") or ""]
            words.extend((row.get("description") or {}).values())
            for field in ("stats", "statsDe", "statsHybrid"):
                words.extend(public_stats(row.get(field, ())))
            words.extend(german_stat_translations().get(stat, "") for stat in public_stats(row.get("stats", ())))
            aliases = (public_name(alias, ident) for alias in row.get("aliases", ()))
            entries.append(make("lexicon", title, {
                "group": group, "facet": kind, "ident": ident, "row": row, "positions": positions,
            }, details, aliases, words))
    elif group == "items":
        for row in data["items"]:
            if not lexicon_item_available(row):
                continue
            if row.get("referenceOnly"):
                row = {**row, "referenceOnly": False}
            title = row.get("de") or row["name"] if german else row["name"]
            kind = row.get("kind", "base")
            properties = row.get("item", {})
            item_type = properties.get("type")
            subtitle = (GERMAN_ITEM_TYPES.get(item_type) if german else item_type) or display_label(ITEM_KINDS[kind], language)
            stats = public_stats((*row.get("stats", ()), *row.get("variants", ()), properties.get("implicit", "")))
            content = (*stats, *(german_stat_translations().get(stat, "") for stat in stats),
                       *(row.get("description") or {}).values())
            aliases = (row["name"], row.get("de") or "", row.get("base") or "", *row.get("aliases", ()))
            details = (subtitle, "Originalname") if german and not row.get("de") else (subtitle,)
            if kind == "currency":
                family = row.get("currencyFamily")
                if family in CURRENCY_FAMILIES and family != "Currency":
                    details += (family if language == "en" else CURRENCY_FAMILIES[family],)
                    content += (family, CURRENCY_FAMILIES[family])
            entries.append(make("lexicon", title, {"group": group, "facet": kind, "row": row}, details, aliases, content))
    elif group == "affixes":
        for rows in affix_rows(data):
            first = rows[0]
            original = public_stats(first["stats"])
            german_stats = public_stats(first.get("statsDe", ())) if german else ()
            translation = (german_stats or tuple(filter(None, (german_stat_translations().get(x) for x in original)))
                           if german else ())
            stats = translation or original
            name = (first.get("de") if german else None) or first["name"]
            title = stats[0] if stats else public_name(name, first["id"])
            if not title:
                continue
            side = first["side"] if first["side"] in AFFIX_SIDES else "Other"
            details = (display_label(AFFIX_SIDES[side], language),)
            if german and not translation:
                details += ("Originaltext",)
            words = [text for row in rows for text in (public_name(row["name"], row["id"]), row.get("de", ""),
                                                       *public_stats(row["stats"]), *public_stats(row.get("statsDe", ())))]
            entries.append(make("lexicon", title, {"group": group, "facet": side, "rows": rows},
                                details, content=words))
    elif group == "pools":
        for names, urls, section, variants in profile_rows(data):
            first = variants[0]
            translation = (first[5] or first[3]) if german else ()
            stats = translation or first[4] or first[2] or first[3]
            title = stats[0]
            profile = names[not german]
            label = section[not german]
            words = [text for row in variants for column in row[2:6] for text in column]
            details = (profile, label, "Originaltext") if german and not translation else (profile, label)
            entries.append(make("lexicon", title, {
                "group": group, "facet": profile, "rows": variants, "url": urls[not german], "section": label,
            }, details, names, words))
    return tuple(entries)


def lookup_entries(language, campaign, companion, hotkeys, mode, website=None):
    # Only the public Lexicon belongs in search. TERM_CATALOG remains the HUD's internal term registry.
    yield from published_terms(language, bundled_lexicon() if website is None else website)

    for act, area, title, names, content in campaign:
        yield make("campaign", title, target=(act, area), aliases=names, content=content)

    for boss in companion.get("bosses", ()):
        title = boss_text(boss, language)["name"]
        variants = [boss_text(boss, lang) for lang in LANGUAGES]
        names = [name for fields in variants for name in (fields["name"], fields["zone"], fields["act"])]
        notes = [fields.get(key, "") for fields in variants for key in ("quick", "reward", "prep", "plan")]
        yield make("boss", title, target=boss, aliases=(*names, *boss.get("aliases", ())), content=notes)

    for key, label, aliases in hotkeys:
        yield make("shortcuts", label, details=(key,), aliases=aliases)
    for row in GUIDE.get("hotkeys", ()):
        key = row["key"]
        yield make("shortcuts", localized(row, language), details=(ui_text(key, language),),
                   aliases=(row["de"], row["en"], key, ui_text(key, "en")))

    yield make("tools", localized(RESPEC["title"], language), target="respec",
               aliases=(*RESPEC["title"].values(), *RESPEC["keywords"]))
    yield make("tools", "Crafting Helper" if language == "en" else "Crafting-Helfer",
               target="crafting-helper", aliases=("Crafting-Helfer", "Crafting Helper", "Herstellung"))
    yield make("tools", "PoE 2 Regex Tool" if language == "en" else "PoE 2 Regex-Tool", target="regex",
               aliases=("Händler", "Lager", "Vendor", "Stash", "Wegsteine", "Waystones", "Tablets", "Relikte", "Relics"))
    yield make("tools", "Affixes & Modifiers" if language == "en" else "Affixe & Modifikatoren", target="affixes",
               aliases=("Affix-Datenbank", "Affix database", "Crafting-Tags", "Crafting tags", "Modpools",
                        "Mod pools", "Rollgewicht", "Roll weight", "Itemlevel", "Gegenstandsstufe"))
    yield make("tools", "Web Build Planner ↗" if language == "en" else "Build-Planer auf der Website ↗",
               target="build-planner-web", aliases=("Build Planner", "Build-Planer", "Web-Planer", "Passive Tree", "Passivbaum"))
    for key, titles in AFFIX_TIPS.items():
        yield make("tips", display_label(titles, language), target=key,
                   aliases=(*titles, "Affix-Guide", "Affix guide"))
    for tip in GUIDE.get("tips", ()):
        yield make("tips", localized(tip["title"], language), details=(localized(tip["body"], language),),
                   aliases=tuple(tip["title"].values()), content=tuple(tip["body"].values()))
    for tip in CATALOG.get("townTipPool", {}).values():
        text = localized(tip.get(mode, {}), language)
        if text:
            content = [row[lang] for row in tip.values() for lang in LANGUAGES if lang in row]
            yield make("tips", text.split(". ", 1)[0].removesuffix("."), details=(text,), content=content)

    for build in companion.get("builds", ()):
        stages = [stage_view(stage, language) for stage in build.get("stages", ())]
        content = [plain_guide_text(line) for key in BUILD_TOPICS for line in editorial_lines(build, key, language)]
        content.extend(line for stage in stages for key in ("nextSteps", "playstyle", "why", "quests",
                                                             "skills", "passives", "craft") for line in stage[key])
        yield make("builds", build["name"], target=build,
                   aliases=(build["author"], *(stage["label"] for stage in stages)), content=content)


def find_entries(entries, query, category):
    phrase = search_text(query[:QUERY_LIMIT])
    words = phrase.split()
    if not words and query.strip():
        return []
    matches = [entry for entry in entries if (category == "all" or entry.category == category)
               and all(word in entry.keywords for word in words)]
    return sorted(matches, key=lambda entry: (
        not words and entry.target != "respec",
        not words and category == "tips" and entry.target not in AFFIX_TIPS,
        bool(words) and entry.name != phrase and phrase not in entry.aliases,
        bool(words) and entry.name != phrase,
        bool(words) and entry.category == "lexicon" and entry.target["group"] != "terms",
        bool(words) and not entry.name.startswith(phrase),
        not all(word in entry.name for word in words),
        entry.name,
    ))

