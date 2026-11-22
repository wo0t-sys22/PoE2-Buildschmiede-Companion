"""Native browser for the public Lexicon inside the HUD search."""

from dataclasses import dataclass, replace
from itertools import chain
import tkinter as tk
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import webbrowser

from poe2_build_art import build_icon
from poe2_term_tooltip import tooltip_art_ref
from poe2_language import display_label
from poe2_lexicon_explain import augments, entry_copy
from poe2_lexicon import (AFFIX_SIDES, GERMAN_ITEM_TYPES, GROUPS, ITEM_KINDS, NODE_KINDS, TOPICS, affix_applies,
                          affix_weight, base_items, bundled_lexicon, german_stat_translations,
                          public_name, public_stats, web_url)
from poe2_overlay_controls import FlowRow
from poe2_overlay_lookup import PAGE_SIZE, catalogue_entries, find_entries, published_terms, search_text


CATALOGUE_GROUPS = ("nodes", "items", "affixes", "pools")
FACETS = {"terms": TOPICS, "nodes": NODE_KINDS, "items": ITEM_KINDS, "affixes": AFFIX_SIDES}
ITEM_STATS = {
    "Armour": ("Rüstung", "Armour"), "Evasion": ("Ausweichen", "Evasion"),
    "EnergyShield": ("Energieschild", "Energy Shield"), "Ward": ("Runenschutz", "Runic Ward"),
    "BlockChance": ("Blockchance", "Block chance"), "AttackRateBase": ("Angriffe/s", "Attacks/s"),
    "CritChanceBase": ("Kritchance", "Critical chance"), "ReloadTimeBase": ("Nachladezeit (s)", "Reload time (s)"),
    "duration": ("Dauer (s)", "Duration (s)"), "chargesUsed": ("Ladungen pro Nutzung", "Charges used"),
    "chargesMax": ("Max. Ladungen", "Max. charges"), "life": ("Leben", "Life"), "mana": ("Mana", "Mana"),
}
DAMAGE_TYPES = {
    "Physical": ("Physisch", "Physical"), "Fire": ("Feuer", "Fire"), "Cold": ("Kälte", "Cold"),
    "Lightning": ("Blitz", "Lightning"), "Chaos": ("Chaos", "Chaos"),
}
VARIANTS_PER_PAGE = 8
AUGMENT_SLOTS = {
    "weapon": "Martial Weapon", "armour": "Armour", "body armour": "Body Armour",
    "boots": "Boots", "bow": "Bow", "buckler": "Buckler", "caster": "Caster Weapon",
    "crossbow": "Crossbow", "focus": "Focus", "gloves": "Gloves", "helmet": "Helmet",
    "martial weapon wand or staff": "Martial Weapon, Wand or Staff", "one hand mace": "One Hand Mace",
    "quarterstaff": "Quarterstaff", "sceptre": "Sceptre", "shield": "Shield", "spear": "Spear",
    "staff": "Staff", "talisman": "Talisman", "two hand mace": "Two Hand Mace", "wand": "Wand",
}
AUGMENT_SLOTS_DE = {
    "Martial Weapon": "Kampfwaffe", "Armour": "Rüstung", "Caster Weapon": "Zauberwaffe",
    "Martial Weapon, Wand or Staff": "Kampfwaffe, Zauberstab oder Stab", "Quarterstaff": "Kampfstab",
}


def _currency_articles(entries, item_entries):
    """Put item facts and editorial explanation in one result when the names match."""
    articles = {search_text(entry.target["row"]["title"].get("en", "")): entry
                for entry in entries if entry.target["row"].get("topic") == "currency"
                and entry.target["row"]["title"].get("en")}
    article_ids={entry.target["row"]["currencyId"]:entry for entry in entries if entry.target["row"].get("currencyId")}
    used = set()
    items = []
    for entry in item_entries:
        if entry.target["facet"] == "currency":
            row = entry.target["row"]
            article = article_ids.get(row["currencyId"]) or articles.get(search_text(row["name"]))
            if article:
                used.add(article.target["row"]["id"])
                entry = replace(entry, target={**entry.target, "article": article.target["row"]},
                                keywords=entry.keywords + " " + article.keywords,
                                aliases=tuple(dict.fromkeys((*entry.aliases, *article.aliases))))
        items.append(entry)
    return [entry for entry in entries if entry.target["row"]["id"] not in used], items


@dataclass
class LexiconBrowser:
    query: str = ""
    group: str = "all"
    facet: str = ""
    variant_page: int = 0
    base: dict | None = None
    show_original: bool = False

    def matches(self, language, website):
        if website is None:
            website = bundled_lexicon()
        if self.group == "items":
            _, entries = _currency_articles(tuple(published_terms(language, website)),
                                            catalogue_entries(language, "items"))
        elif self.group in CATALOGUE_GROUPS:
            entries = catalogue_entries(language, self.group)
        else:
            entries = published_terms(language, website)
            if self.group == "mechanics":
                entries = (entry for entry in entries if entry.target["row"].get("mechanic"))
            elif self.group == "all" and self.query:
                terms, items = _currency_articles(tuple(entries), catalogue_entries(language, "items"))
                entries = chain(terms, items, *(catalogue_entries(language, group)
                                                for group in CATALOGUE_GROUPS if group != "items"))
        if self.facet:
            entries = (entry for entry in entries if
                       (entry.target["row"].get("topic") if self.group == "terms" else entry.target.get("facet"))
                       == self.facet)
        if self.group == "affixes" and self.base:
            entries = (entry for entry in entries if any(affix_applies(row, self.base) for row in entry.target["rows"]))
        return find_entries(entries, self.query, "lexicon")


def render_lexicon(window, parent):
    browser = window.lexicon
    language = window.app.language
    en = language == "en"
    theme = window.theme
    px = window.layout.px

    def text(de, english):
        return english if en else de

    def message(value, **style):
        if value:
            return window.pack_message(parent, value, **style)

    def article_title(value, summary, **style):
        canvas = message(value, **style)
        target = window.lookup_entry.target
        node = target["ident"] if target["group"] == "nodes" and target["facet"] not in ("skill", "support") else None
        ref = tooltip_art_ref(target.get("row", {}), node_id=node)

        def title_at_point(x, y):
            bounds = canvas.bbox("ink")
            if bounds and bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]:
                return value, (value, summary, None, ref)
            return None

        canvas.detail_at_point = title_at_point
        window.app.term_tips.register(canvas)

    def picture(ref):
        if image := build_icon(parent, ref, px(64)):
            label = tk.Label(parent, image=image, bg=parent.cget("background"), bd=0)
            label.icon = image
            label.pack(anchor="w", padx=px(8), pady=(0, px(4)))

    def row(distribute=False):
        controls = FlowRow(parent, bg=parent.cget("background"), gap=px(4), distribute=distribute)
        controls.pack(fill="x", padx=px(4), pady=(0, px(4)))
        return controls

    def button(container, title, action, *, active=False):
        widget = window.small_button(container, title, action)
        if active:
            widget.configure(bg=theme.selection_color, fg=theme.selection_text)
        return widget

    def link(container, label, url):
        if url and urlsplit(url).scheme == "https":
            widget = button(container, label + " ↗", lambda: webbrowser.open(url))
            widget.configure(fg=theme.accent)

    def pages(page, size, count, go):
        if count <= size:
            return
        controls = row()
        if page:
            button(controls, text("Zurück", "Previous"), lambda: go(page - 1))
        if (page + 1) * size < count:
            button(controls, text("Weiter", "Next"), lambda: go(page + 1))

    if window.lookup_entry:
        actions = row()
        button(actions, text("Zurück zur Liste", "Back to list"), lambda: window._set_lookup(page=window.lookup_page))
        _render_article(window, language, message, row, button, link, pages, picture=picture, title=article_title)
        return

    def set_group(group):
        browser.group, browser.facet = group, ""
        browser.base = None
        window._set_lookup()

    def set_facet(facet):
        browser.facet = "" if browser.facet == facet else facet
        window._set_lookup()

    categories = row()
    for group, names in GROUPS.items():
        button(categories, display_label(names, language), lambda group=group: set_group(group),
               active=group == browser.group)
    link(categories, text("Web-Ansicht", "Web view"), web_url(language))
    if facets := FACETS.get(browser.group):
        filters = row()
        for facet, names in facets.items():
            button(filters, display_label(names, language), lambda facet=facet: set_facet(facet),
                   active=facet == browser.facet)
    if browser.group == "affixes" and browser.base:
        toolbar = row()
        base = browser.base
        base_title = base.get("de") or base["name"] if language == "de" else base["name"]
        button(toolbar, base_title + " ×", lambda: set_group("affixes"), active=True)

    matches = browser.matches(language, window.app.website_lexicon())
    if not matches:
        message(text("Keine Treffer", "No results"), tone="muted")
        return
    page = min(window.lookup_page, (len(matches) - 1) // PAGE_SIZE)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(matches))
    if browser.group == "all" and not browser.query:
        message(text("Begriffe aus dem Lexikon", "Lexicon articles"), tone="gold")
    message(f"{start + 1}–{end} / {len(matches)}", tone="muted", points=9)
    for entry in matches[start:end]:
        target = entry.target
        subtitle = " · ".join(entry.details[1:] if target["group"] == "terms" else entry.details)
        caption = f"{entry.title}\n{subtitle}" if subtitle else entry.title
        widget = button(parent, caption, lambda entry=entry: window._pick_lookup(entry))
        widget.configure(anchor="w", justify="left", padx=px(8), pady=px(4))
        space = px(22)
        if target.get("facet") == "currency":
            if image := build_icon(parent, target["row"].get("imageLocal"), px(32)):
                widget.configure(image=image, compound="left")
                widget.icon = image
                space += image.width()
        widget.bind("<Configure>", lambda event, space=space: event.widget.configure(
            wraplength=max(1, event.width - space)))
        widget.pack(fill="x", padx=px(4), pady=(0, px(3)))
    pages(page, PAGE_SIZE, len(matches), lambda page: window._set_lookup(page=page))


def _localized_url(url, language):
    parts = urlsplit(url)
    if parts.hostname != "buildschmiede.de":
        return url
    params = dict(parse_qsl(parts.query))
    params["sprache"] = language
    return urlunsplit(parts._replace(query=urlencode(params)))


def _render_article(window, language, message, row, button, link, pages, *, picture=None, title=None):
    entry = window.lookup_entry
    target = entry.target
    group = target["group"]
    record = target.get("row", {})
    en, de = language == "en", language == "de"

    def text(german, english):
        return english if en else german

    def lines(values):
        for value in public_stats(values):
            message(value)

    def modifiers(original, german=()):
        if not de:
            lines(original)
        elif german:
            source_lines = public_stats(original)
            for line in public_stats(german):
                if line in source_lines:
                    originals.append(line)
                else:
                    message(line)
        else:
            translations = german_stat_translations()
            for line in public_stats(original):
                if translated := translations.get(line):
                    message(translated)
                else:
                    originals.append(line)

    def source(url):
        if url and urlsplit(url).scheme == "https":
            host = urlsplit(url).hostname
            label = {"poe2dat.com": "PoE2DAT", "www.poe2wiki.net": "PoE2Wiki"}.get(host, "PoE2DB")
            links.append((label, url))

    def editorial_links(article):
        for item in article.get("links", ()):
            label = item["label"]
            if isinstance(label, dict):
                label = label.get(language) or label.get("en" if en else "de")
            if label:
                links.append((label, item["url"]))

    links = []
    originals = []
    url = None
    summary, paragraphs = entry_copy(entry, language)
    if title:
        title(entry.title, summary, tone="gold")
    else:
        message(entry.title, tone="gold")
    if group == "terms":
        message(entry.details[1], tone="muted", points=9)
        if language == "hybrid":
            titles = [name for name in dict.fromkeys(record["title"].values()) if name != entry.title]
            message(" · ".join(titles), tone="muted", points=10)
        message(summary)
        editorial_links(record)
        url = record.get("url")
    elif group == "nodes":
        message(" · ".join(entry.details), tone="muted", points=9)
        if language == "hybrid" and record.get("de") != entry.title:
            message(record.get("de"), tone="muted", points=10)
        message(summary)
        stats = record.get("statsHybrid") if language == "hybrid" else None
        modifiers(stats or record.get("stats", ()), record.get("statsDe", ()))
        if family := record.get("family"):
            if family != record["name"]:
                family = (record.get("familyDe") if de else None) or family
                message(text("Familie", "Family") + " · " + family, tone="muted", points=10)
        weapon = record.get("weapon") or ""
        if de:
            weapons = [GERMAN_ITEM_TYPES.get(name.strip()) for name in weapon.split(",")]
            message(", ".join(filter(None, weapons)))
            if weapon and not all(weapons):
                originals.append(weapon)
            if tags := record.get("tagsDe"):
                message(tags)
            elif tags := record.get("tags"):
                originals.append(tags)
        else:
            lines([record.get("tags") or "", weapon])
        if positions := target["positions"]:
            message(text("Positionen im Passivbaum", "Positions in the passive tree") + f" · {sum(positions.values())}",
                    tone="muted", points=10)
        source(record.get("source"))
        if target["facet"] != "support":
            fragment = ("skill-" if target["facet"] == "skill" else "passiv-") + target["ident"]
            url = web_url(language, fragment)
    elif group == "items":
        currency = target["facet"] == "currency"
        if currency and picture:
            picture(record.get("imageLocal"))
        base_name = record.get("base")
        base_record = base_items().get(base_name) if base_name else None
        if de and base_name:
            if not base_record or not base_record.get("de"):
                originals.append(base_name)
            base_name = base_record.get("de") if base_record else None
        message(" · ".join(filter(None, (*entry.details, base_name))), tone="muted", points=10)
        message(summary)
        if article := target.get("article"):
            editorial_links(article)
            url = article.get("url")
        if currency:
            for slot, effects in augments().get(record["currencyId"], {}).items():
                label_en = AUGMENT_SLOTS.get(slot, slot)
                label = (AUGMENT_SLOTS_DE.get(label_en) or GERMAN_ITEM_TYPES.get(label_en, label_en)) if de else label_en
                message(label, tone="muted", points=10)
                lines(effects.get("de" if de else "en", ()))
                if de and len(effects.get("de", ())) != len(effects.get("en", ())):
                    originals.extend(effects["en"])
                if effects.get("bound"):
                    message(text("Fassungsgebunden", "Socket-bound"), tone="muted", points=9)
        lines(_item_lines(record, en, de))
        modifiers((record.get("item", {}).get("implicit") or "", *record.get("stats", ()), *record.get("variants", ())))
        source((record.get("sourceDe") if de else None) or record.get("source"))
        base = record if record.get("kind") in {None, "tablet", "waystone"} else base_items().get(record.get("base"))
        if base:
            def show_affixes():
                browser = window.lexicon
                browser.group, browser.facet, browser.query, browser.base = "affixes", "", "", base
                window._set_lookup()
            button(row(), text("Passende Affixe", "Applicable affixes"), show_affixes)
        if not currency:
            url = web_url(language, "affix-katalog")
    else:
        message(" · ".join(entry.details), tone="muted", points=10)
        message(summary)
        variants = target["rows"]
        base = window.lexicon.base
        if group == "affixes" and base and window.lexicon.group == "affixes":
            variants = [variant for variant in variants if affix_applies(variant, base)]
        page = min(window.lexicon.variant_page, (len(variants) - 1) // VARIANTS_PER_PAGE)
        start = page * VARIANTS_PER_PAGE
        for variant in variants[start:start + VARIANTS_PER_PAGE]:
            if group == "pools":
                tier, level, names_en, names_de, stats_en, stats_de, weight = variant
                names = names_de if de else names_en or names_de
                name = " / ".join(names)
                if de and not names_de:
                    originals.extend(names_en)
                suffix = text(f" · Rollgewicht {weight}", f" · Roll weight {weight}") if type(weight) is int else ""
            else:
                tier, level = variant.get("tier"), variant["level"]
                source_name = public_name(variant["name"], variant["id"])
                name = (variant.get("de") or "") if de else source_name
                if de and source_name and not name:
                    originals.append(source_name)
                stats_en, stats_de = variant["stats"], variant.get("statsDe", ())
                weight = affix_weight(variant, base) if base else None
                suffix = text(f" · Rollgewicht {weight}", f" · Roll weight {weight}") if type(weight) is int else ""
                source(variant.get("source"))
            level_label = display_label((f"Gegenstandsstufe {level}", f"Itemlevel {level}", f"Item level {level}"),
                                        language)
            tier_label = str(tier) if tier and str(tier).startswith("T") else f"T{tier}" if tier else ""
            label = " · ".join(filter(None, (name, tier_label, level_label)))
            message(label + suffix, tone="gold", points=10)
            modifiers(stats_en or (() if de else stats_de), stats_de)
        def go(page):
            window.lexicon.variant_page = page
            window.refresh_guide()
        pages(page, VARIANTS_PER_PAGE, len(variants), go)
        source(target.get("url"))
        url = web_url(language, "affix-katalog")
    if paragraphs:
        message(text("Erklärung & Praxis", "Explanation & examples"), tone="gold")
        for paragraph in paragraphs:
            message(paragraph)
    description = record.get("description") or {}
    if description and not description.get("en" if en else "de"):
        originals.extend(public_stats((description.get("de" if en else "en") or "",)))
    if originals:
        def toggle_original():
            window.lexicon.show_original = not window.lexicon.show_original
            window.refresh_guide()
        show = window.lexicon.show_original
        message(text("Ein Teil der Texte ist nur in der Originalsprache verfügbar.",
                     "Some text is only available in its original language."), tone="muted", points=9)
        label = text("Originaltext ausblenden", "Hide original text") if show else text("Originaltext anzeigen", "Show original text")
        button(row(), label, toggle_original)
        if show:
            lines(dict.fromkeys(originals))
    if url:
        links.insert(0, (text("Eintrag im Web", "Entry on the web"), url))
    if links:
        actions = row()
        shown = set()
        for name, url in links:
            url = _localized_url(url, language)
            parts = urlsplit(url)
            identity = url
            if parts.hostname == "poe2db.tw":
                path = parts.path.strip("/").split("/")
                if path[0] in ("us", "de", "en"):
                    path = path[1:]
                identity = parts.hostname, tuple(path), parts.query, parts.fragment
            if identity not in shown:
                link(actions, name, url)
                shown.add(identity)


def _item_lines(record, en, de):
    values = record.get("item", {})
    requirements = values.get("req", {})
    if level := requirements.get("level"):
        yield ("Level " if en else "Stufe ") + str(level)
    for key, labels in {"str": ("Stärke", "Strength"), "dex": ("Geschick", "Dexterity"),
                        "int": ("Intelligenz", "Intelligence")}.items():
        if amount := requirements.get(key):
            yield f"{amount} {labels[not de]}"
    for field in ("armour", "weapon", "charm", "flask"):
        stats = values.get(field, {})
        for key, labels in ITEM_STATS.items():
            if key in stats:
                suffix = "%" if key in {"BlockChance", "CritChanceBase"} else ""
                yield f"{labels[not de]} {stats[key]}{suffix}"
        for key, labels in DAMAGE_TYPES.items():
            if key + "Min" in stats and key + "Max" in stats:
                yield f"{labels[not de]} {stats[key + 'Min']}–{stats[key + 'Max']}"
    if area_level := record.get("areaLevel"):
        yield ("Area level " if en else "Gebietsstufe ") + str(area_level)
    if map_tier := record.get("mapTier"):
        yield ("Tier " if en else "Wegsteinstufe ") + str(map_tier)
