from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import chain
import re
import unicodedata
from urllib.parse import urlencode

from poe2_affix_catalog import AffixFilters, POOLS, profile_keys
from poe2_language import CATALOG, LANGUAGES, boss_text, display_label, ui_text
from poe2_build_editorial import BUILD_TOPICS, editorial_lines, plain_guide_text, stage_view
from poe2_lexicon_explain import term_summary
from poe2_lexicon import (AFFIX_SIDES, CURRENCY_FAMILIES, GERMAN_ITEM_TYPES, GROUPS, ITEM_KINDS, NODE_KINDS, TOPICS,
                          affix_applies, affix_rows, affix_weight_rule,
                          bundled_lexicon, catalogue, german_stat_translations, league_guides, lexicon_item_available, node_rows, profile_rows,
                          public_name, public_stats)
from poe2_r18_features import BASE_DIR, GUIDE, localized, read_json
from poe2_respec import RESPEC
from poe2_website_content import localized_text

CATEGORIES = {
    "lexicon": ("Lexikon", "Lexikon", "Glossary"),
    "campaign": ("Kampagne", "Kampagne", "Campaign"),
    "atlas": ("Atlas", "Atlas", "Atlas"),
    "boss": ("Bosse", "Bosse", "Bosses"),
    "shortcuts": ("Tastenkürzel", "Shortcuts", "Shortcuts"),
    "tips": ("Tipps", "Tipps", "Tips"),
    "faq": ("Häufige Fragen", "Häufige Fragen", "FAQ"),
    "constructs": ("Konstrukt-Fundorte", "Construct Maps", "Construct maps"),
    "tools": ("Werkzeuge", "Tools", "Tools"),
    "builds": ("Builds", "Builds", "Builds"),
}
FAQ_TOPICS = {
    "basics": (("Einstieg & Bedienung", "Einstieg & Bedienung", "Getting started"), "learn", "#ebc674"),
    "tools": (("Werkzeuge & Crafting", "Werkzeuge & Crafting", "Tools & crafting"), "settings", "#ffad75"),
    "builds": (("Build-Fragen", "Build-Fragen", "Build questions"), "build", "#98bfff"),
    "campaign": (("Kampagne", "Kampagne", "Campaign"), "quest", "#a2d397"),
    "mechanics": (("Mechaniken & Belohnungen", "Mechaniken & Belohnungen", "Mechanics & rewards"), "gem", "#d6aefa"),
    "atlas": (("Atlas & Quests", "Atlas & Quests", "Atlas & quests"), "checklist", "#88dfd7"),
}
AFFIX_TIPS = {
    "affixGuide": ("Affixe verstehen", "Affixe verstehen", "Understand affixes"),
    "itemGuide": ("Welche Gegenstände sind wertvoll?", "Welche Items sind wertvoll?", "Which drops are worth keeping?"),
    "weightGuide": ("Was bedeutet Rollgewicht?", "Was bedeutet Rollgewicht?", "How roll weights work"),
}
GUIDE_TIPS = (
    (
        ("Eigenen Beutefilter mit FilterBlade einstellen", "Eigenen Lootfilter mit FilterBlade einstellen", "Set up a loot filter with FilterBlade"),
        "/grundlagen/lootfilter-gegenstaende/", "filterblade",
        ("Auto-Adjust", "Strictness", "NeverSink", "Beutefilter", "Loot Filter"),
        (
            ("Wähle PoE 2, öffne Auto-Adjust for build und übernimm deine Charakterklasse. Für die ersten Karten ist Semi-Strict ein Ausgangspunkt.",
             "Wähle PoE 2, öffne Auto-Adjust for build und übernimm deine Charakterklasse. Für die ersten Maps ist Semi-Strict ein Ausgangspunkt.",
             "Select PoE 2, open Auto-Adjust for build and apply your character class. Semi-Strict is a starting point for early maps."),
            ("Beispiel für eine Hexe: Prüfe in Simulate auf deiner Gebietsstufe normale Gebundene Sandalen und eine Hoheitliche Sphäre. Sind die Sandalen ausgeblendet, ändere ihre Regel in Customize und prüfe beide Funde erneut.",
             "Beispiel für eine Witch: Stelle in Simulate das Area Level deiner Map ein und prüfe normale Bound Sandals und eine Regal Orb. Sind die Sandalen ausgeblendet, ändere ihre Regel in Customize und prüfe beide Drops erneut.",
             "Witch example: Use Simulate at your area level to check normal Bound Sandals and a Regal Orb. If the sandals are hidden, change their rule in Customize and test both items again."),
            ("Unter Default filter colors kannst du beispielsweise Cobalt ausprobieren. Wähle Export filter to PoE und aktiviere deinen Filter im Spiel unter Optionen → Spiel → Gegenstandsfilter.",
             "Unter Default filter colors kannst du zum Beispiel Cobalt ausprobieren. Wähle Export filter to PoE und aktiviere deinen Filter im Spiel unter Options → Game → Item Filter.",
             "Try Cobalt under Default filter colors. Use Export filter to PoE, then select your filter in-game under Options → Game → Item Filter."),
        ),
    ),
    (
        ("Aufstiegspunkte 1–8", "Aufstiegspunkte 1–8", "Ascendancy points 1–8"),
        "/grundlagen/aufstiegspunkte/", "punktestand",
        ("Ascendancy", "Sekhemas", "Trial of Chaos", "Trialmaster", "Aszendenzpunkte"),
        (
            ("Zähle alle verdienten Aufstiegspunkte mit, auch die bereits vergebenen.",
             "Zähle alle verdienten Ascendancy Points mit, auch die bereits vergebenen.",
             "Count all your earned Ascendancy points, including those already spent."),
            ("0 → 2: Besiege Balbala und absolviere mit ihrer Barya das erste Stockwerk der Prüfung der Sekhemas.",
             "0 → 2: Besiege Balbala und absolviere mit ihrer Barya den ersten Floor im Trial of the Sekhemas.",
             "0 → 2: Defeat Balbala and use her Barya to clear the first floor of the Trial of the Sekhemas."),
            ("2 → 4: Spiele die vier Räume des Quest-Ultimatums aus den Feuchtlanden der Chimären oder das zweite Stockwerk der Sekhemas mit einer Dschinn-Barya ab Gebietsstufe 45.",
             "2 → 4: Spiele die vier Trials des Quest-Ultimatums aus den Chimeral Wetlands oder den zweiten Floor der Sekhemas mit einer Djinn Barya ab Area Level 45.",
             "2 → 4: Clear the four rooms of the Chimeral quest Ultimatum, or clear Sekhemas floor two with an area-level-45+ Djinn Barya."),
            ("4 → 6: Dschinn-Barya ab Gebietsstufe 60, drei Stockwerke. 6 → 8: Dschinn-Barya ab Gebietsstufe 75, vier Stockwerke einschließlich Zarokh. Prüfe vor dem Start die Punktezeile des Schlüssels.",
             "4 → 6: Djinn Barya ab Area Level 60, drei Floors. 6 → 8: Djinn Barya ab Area Level 75, vier Floors inklusive Zarokh. Prüfe vor dem Start die Punktezeile des Schlüssels.",
             "4 → 6: Area-level-60+ Djinn Barya, three floors. 6 → 8: Area-level-75+ Djinn Barya, four floors including Zarokh. Check the key's points line before you start."),
        ),
    ),
)
QUERY_LIMIT = 96
PAGE_SIZE = 16
CONSTRUCT_STATUS = {
    "candidate": ("Kandidat", "Kandidat", "Candidate"),
    "review": ("Prüffall", "Prüffall", "Needs review"),
    "conflicting": ("Widersprüchliche Berichte", "Widersprüchliche Berichte", "Conflicting reports"),
}


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
    url: str = ""


def make(category, title, target=None, details=(), aliases=(), content=(), *, url=""):
    aliases = tuple(dict.fromkeys(alias for alias in aliases if alias))
    return LookupEntry(category, title, target, tuple(details), search_text(title),
                       search_text(" ".join((title, *aliases, *details, *content))),
                       tuple(search_text(alias) for alias in aliases), url)


@lru_cache(maxsize=3)
def editorial_entries(language):
    directory = BASE_DIR / "shared-data"
    faq = read_json(directory / "faq.v1.json")
    maps = construct_catalog()
    entries = []
    if faq.get("schema") == "buildschmiede.faq.v1":
        for row in faq["entries"]:
            question, answer = row["question"], row["answer"]
            query = urlencode({"ansicht": "faq", "sprache": language})
            url = f'https://buildschmiede.de/grundlagen/?{query}#faq-{row["id"]}'
            topic = FAQ_TOPICS.get(row["topic"])
            entries.append(make("faq", question[language], {**row, "url": url},
                                (answer[language], row["patch"]),
                                (*question.values(), *row["aliases"]),
                                (*answer.values(), *(topic[0] if topic else ()))))
    if maps.get("schema_version") == 2:
        query = urlencode({"fundliste": "konstrukte", "sprache": language})
        rule = maps["regel"]
        chance = f'{rule["chance_durch_passive_pro_geeignetem_gegner"]:.0%}'
        condition = display_label((
            f'Nach einem Großen Spiegel „{rule["passive_de"]}“ wählen. Bei einem einzigartigen Konstrukt im aktiven Delirium-Nebel beträgt die Chance auf Groll {chance}.',
            f'Nach einem Grand Mirror „{rule["passive_en"]}“ wählen. Ein Unique Construct im aktiven Delirium Fog hat dann {chance} Chance auf Potent Liquid Contempt.',
            f'After a Grand Mirror, allocate “{rule["passive_en"]}”. A unique Construct killed in active Delirium fog then has a {chance} chance to drop Potent Liquid Contempt.',
        ), language)
        for row in maps["karten"]:
            title = row["karte_de"] if language == "de" else row["karte_en"]
            aliases = (row["karte_de"], row["karte_en"], row["quellbezeichnung"], row["boss_en"])
            evidence = display_label(CONSTRUCT_STATUS[row["evidence_class"]], language)
            url = f'https://buildschmiede.de/lexikon/?{query}#konstrukt-{row["slug"]}'
            target = {"id": row["slug"], "url": url}
            details = (row["boss_en"], evidence, row["detail"][language], condition,
                       "0.5.x · " + maps["geprueft_am"])
            entries.append(make("constructs", title, target, details, aliases,
                                (maps["gegenstand"]["de"], maps["gegenstand"]["en"],
                                 *row["detail"].values(), "Konstrukt Construct")))
    query = urlencode({"sprache": language})
    for titles, path, anchor, aliases, rows in GUIDE_TIPS:
        entries.append(make("tips", display_label(titles, language),
                            target=anchor, url=f"https://buildschmiede.de{path}?{query}#{anchor}",
                            details=tuple(display_label(row, language) for row in rows), aliases=(*titles, *aliases),
                            content=tuple(line for row in rows for line in row)))
    return tuple(entries)


@lru_cache(maxsize=1)
def construct_catalog():
    return read_json(BASE_DIR / "shared-data" / "konstrukt-fundorte.json")


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
        guide = league_guides().get(entry["id"])
        guide_aliases = guide.get("aliases", ()) if guide else ()
        names = (name for value in (*entry["title"].values(), *(entry.get("aliases") or ()), *guide_aliases)
                 if (name := public_name(value, entry["id"])))
        if guide:
            content = [*guide["summary"].values(), *(target["title"] for target in guide["tooltip_targets"])]
            content.extend(text for section in guide["sections"] for text in section["text"].values())
        else:
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
    elif group == "pools":
        return tuple(_profile_entries(data, language, data["profiles"]))
    return tuple(entries)


def lexicon_terms_and_items(language, website):
    """Merge a currency's public catalogue row with its editorial article."""
    terms = tuple(published_terms(language, website))
    articles = {search_text(entry.target["row"]["title"]["en"]): entry
                for entry in terms if entry.target["row"].get("topic") == "currency"
                and entry.target["row"]["title"].get("en")}
    article_ids = {entry.target["row"]["currencyId"]: entry for entry in terms
                   if entry.target["row"].get("currencyId")}
    used = set()
    items = []
    for entry in catalogue_entries(language, "items"):
        if entry.target["facet"] == "currency":
            row = entry.target["row"]
            article = article_ids.get(row["currencyId"]) or articles.get(search_text(row["name"]))
            if article:
                used.add(article.target["row"]["id"])
                entry = replace(entry, target={**entry.target, "article": article.target["row"]},
                                keywords=entry.keywords + " " + article.keywords,
                                aliases=tuple(dict.fromkeys((*entry.aliases, *article.aliases))))
        items.append(entry)
    return [entry for entry in terms if entry.target["row"]["id"] not in used], items


def lexicon_search_entries(language, website):
    terms, items = lexicon_terms_and_items(language, website)
    return chain(terms, items, catalogue_entries(language, "nodes"), modifier_entries(language))


def _raw_modifier_names(row):
    return (public_name(row["name"], row["id"]), public_name(row.get("de", ""), row["id"]))


@lru_cache(maxsize=1)
def _modifier_names_by_id():
    names = defaultdict(set)
    for row in catalogue()["mods"]:
        names[row["id"]].update(filter(None, _raw_modifier_names(row)))
    return {ident: tuple(sorted(labels)) for ident, labels in names.items()}


def _modifier_tags(tag_sets):
    first, *rest = tag_sets
    common = set(first).intersection(*rest)
    return tuple(tag for tag in dict.fromkeys(first) if tag != "default" and tag in common)


def _profile_entries(data, language, profile_ids, excluded_ids=()):
    german = language == "de"
    known_names = _modifier_names_by_id()
    groups = {}
    for family, names, urls, section, all_variants in profile_rows(data, profile_ids):
        variants = [row for row in all_variants if row.ident not in excluded_ids]
        if not variants:
            continue
        # Keep distinct families and sections apart, even when their displayed
        # text matches. Count the entire variant payload regardless of its order.
        key = (section, family, frozenset(Counter(variants).items()))
        if key not in groups:
            groups[key] = (variants, {})
        groups[key][1][names, urls] = None

    for (section, _, _), (variants, associations) in groups.items():
        first = variants[0]
        translation = (first.stats_de or first.names_de) if german else ()
        title = (translation or first.stats_en or first.names_en or first.names_de)[0]
        label = section[not german]
        profiles = tuple((names[not german], urls[not german]) for names, urls in associations)
        if len(profiles) == 1:
            profile, url = profiles[0]
        else:
            categories = {name.partition("(")[0].rstrip() for name, _ in profiles}
            category = categories.pop() if len(categories) == 1 else ""
            count = f"{len(profiles)} " + ("profiles" if language == "en" else "Profile")
            profile = " · ".join(filter(None, (category, count)))
            url = ""
        details = (profile, label, "Originaltext") if german and not translation else (profile, label)
        side = next((side for side in ("Prefix", "Suffix") if section[1].endswith(side)), "Other")
        words = [text for row in variants for text in
                 (*row.names_en, *row.names_de, *row.stats_en, *row.stats_de, *row.tags)]
        aliases = [name for names, _ in associations for name in names]
        aliases.extend(name for row in variants for name in known_names.get(row.ident, ()))
        yield make("lexicon", title, {
            "group": "pools", "facet": profile, "side": side, "rows": variants, "url": url,
            "profiles": profiles,
            "section": label, "tags": _modifier_tags(row.tags for row in variants),
        }, details, aliases, words)


def _raw_modifier_entries(data, language, covered_ids, base=None):
    german = language == "de"
    for family in affix_rows(data):
        rows = [row for row in family if row["id"] not in covered_ids and (not base or affix_applies(row, base))]
        if not rows:
            continue
        first = rows[0]
        original = public_stats(first["stats"])
        translation = ()
        if german:
            translation = public_stats(first.get("statsDe", ())) or tuple(
                filter(None, (german_stat_translations().get(stat) for stat in original)))
        name = (first.get("de") if german else None) or first["name"]
        stats = translation or original
        title = stats[0] if stats else public_name(name, first["id"])
        if not title:
            continue
        side = first["side"] if first["side"] in AFFIX_SIDES else "Other"
        details = (display_label(AFFIX_SIDES[side], language),)
        if labels := POOLS.get(first["category"]):
            details = (labels[language == "en"], *details)
        if german and not translation:
            details += ("Originaltext",)
        words = [text for row in rows for text in (*_raw_modifier_names(row), *public_stats(row["stats"]),
                                                   *public_stats(row.get("statsDe", ())), *row["tags"])]
        yield make("lexicon", title, {
            "group": "affixes", "facet": side, "side": side, "rows": rows,
            "tags": _modifier_tags(row["tags"] for row in rows),
        }, details, content=words)


def _profile_modifier_ids(entries):
    return {row.ident for entry in entries for row in entry.target["rows"] if row.ident}


@lru_cache(maxsize=3)
def _all_modifier_entries(language):
    profiles = catalogue_entries(language, "pools")
    return profiles + tuple(_raw_modifier_entries(catalogue(), language, _profile_modifier_ids(profiles)))


def modifier_entries(language, base=None):
    """Combine profile families with raw modifiers that have no profile result in this scope."""
    if not base:
        return _all_modifier_entries(language)
    data = catalogue()
    name = base.get("modBase") or base["name"]
    keys = profile_keys(AffixFilters(base=name), data["profiles"])
    # A selectable base must resolve to a single profile. Keep ordered item rules as
    # a fallback when the catalogue can only identify an equipment category.
    profiles = ()
    if len(keys) == 1:
        allowed, excluded = set(), set()
        for row in data["mods"]:
            if rule := affix_weight_rule(row, base):
                if rule[1] > 0:
                    allowed.add(row["id"])
                elif rule[0] != "default":
                    excluded.add(row["id"])
        profiles = tuple(_profile_entries(data, language, keys, excluded - allowed))
    return profiles + tuple(_raw_modifier_entries(data, language, _profile_modifier_ids(profiles), base))


def lookup_entries(language, campaign, companion, hotkeys, mode, website=None, *, search_catalogue=False):
    # Only the public Lexicon belongs in search. TERM_CATALOG remains the HUD's internal term registry.
    website = bundled_lexicon() if website is None else website
    if search_catalogue:
        yield from lexicon_search_entries(language, website)
    else:
        yield from published_terms(language, website)
    yield from editorial_entries(language)

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
    def rank(entry):
        names = (entry.name, *entry.aliases)
        return (
            not words and entry.target != "respec",
            not words and category == "tips" and entry.target not in AFFIX_TIPS,
            bool(words) and phrase not in names,
            bool(words) and entry.name != phrase,
            bool(words) and not any(phrase in name for name in names),
            bool(words) and not all(any(word in name for name in names) for word in words),
            bool(words) and entry.category == "lexicon" and entry.target["group"] != "terms",
            bool(words) and not entry.name.startswith(phrase),
            entry.name,
        )

    return sorted(matches, key=rank)

