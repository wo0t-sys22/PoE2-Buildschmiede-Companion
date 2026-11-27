"""Native browser for the public Lexicon inside the HUD search."""

from dataclasses import dataclass
import tkinter as tk
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import webbrowser

from poe2_affix_catalog import tag_label
from poe2_build_art import build_icon
from poe2_term_tooltip import tooltip_art_ref
from poe2_language import display_label
from poe2_lexicon_explain import augments, currencies, entry_copy
from poe2_lexicon import (AFFIX_SIDES, GERMAN_ITEM_TYPES, GROUPS, ITEM_KINDS, MECHANICS_LABELS, NODE_KINDS, TOPICS,
                          affix_weight, base_items, bundled_lexicon, catalogue, german_stat_translations, league_guides,
                          lexicon_guides, lineage_sources, public_name, public_stats, web_url)
from poe2_overlay_controls import FlowRow
from poe2_overlay_lookup import (AFFIX_TIPS, PAGE_SIZE, catalogue_entries, editorial_entries, find_entries,
                                 lexicon_search_entries, lexicon_terms_and_items, lineage_support_entries, make, modifier_entries,
                                 published_terms)
from poe2_overlay_theme_art import mix_color
from poe2_r18_features import PALETTE
from poe2_website_content import localized_text


LINEAGE_LABELS = ("Abstammungs-Unterstützungen", "Lineage Supports", "Lineage Support Gems")
FACETS = {
    "terms": {"mechanics": MECHANICS_LABELS, **TOPICS},
    "supports": {"lineage": LINEAGE_LABELS},
    "passives": {key: label for key, label in NODE_KINDS.items() if key not in {"skill", "support"}},
    "items": {key: label for key, label in ITEM_KINDS.items() if key != "currency"},
    "mods": AFFIX_SIDES,
}
GROUP_ALIASES = {"mechanics": "terms", "nodes": "skills", "pools": "mods"}
NODE_GROUPS = {"skills": {"skill"}, "supports": {"support"}, "passives": FACETS["passives"].keys()}
LEAGUE_VISUALS = {
    "abyss": ("#b8d77d", "currency.preserved-rib"),
    "delirium": ("#b9aff6", "currency.potent-liquid-contempt"),
    "ritual": ("#f09baa", "currency.an-audience-with-the-king"),
    "essence": ("#83caee", "currency.essence-of-the-body"),
    "azmeri-spirit": ("#7fd6b2", "currency.wolf-idol"),
    "breach": ("#e1a0e4", "currency.breach-splinter"),
    "expedition": ("#edc482", "currency.expedition-logbook"),
    "aldur": ("#8bd4dd", "currency.the-runefathers-alloy"),
    "atziri": ("#f6a08a", "currency.vaal-armourers-infuser"),
}
TITLE_ROLE_COLORS = {
    "currency": "#edc482", "unique": "#efb287",
    "gem": "#8ad9be", "support": "#abd889",
    **{role: PALETTE[role] for role in ("rare", "magic", "quest", "life_flask", "mana_flask")},
}
# Short RC27 encounter steps. Detailed explanations and rewards are in the shared guide data.
LEAGUE_STEPS = {
    "abyss": (
        ("Gegner an Spalten besiegen", "Gegner an Fissures besiegen", "Kill monsters at the fissures"),
        ("Welle an der Grube besiegen", "Welle am Abyss Pit besiegen", "Clear the wave at the pit"),
        ("Zugang zu den Tiefen prüfen", "Zugang zu den Depths prüfen", "Check for a path to the Depths"),
    ),
    "delirium": (
        ("Durch den Spiegel laufen", "Durch den Mirror laufen", "Step through the mirror"),
        ("Dem Nebel folgen", "Dem Fog folgen", "Follow the fog"),
        ("Zum Kartenboss vorrücken", "Zum Map Boss vorrücken", "Push towards the map boss"),
    ),
    "ritual": (
        ("Gegner im Kreis besiegen", "Ritual Circle freiräumen", "Clear the ritual circle"),
        ("Altar starten und Tribut holen", "Altar starten und Tribute holen", "Start the altar and earn Tribute"),
        ("Gabe kaufen oder vormerken", "Favours kaufen oder deferren", "Buy or defer a favour"),
    ),
    "essence": (
        ("Essenzen am Kristall prüfen", "Essences am Kristall prüfen", "Read the essences on the crystal"),
        ("Monster befreien", "Rare befreien", "Release the trapped monster"),
        ("Besiegen und Essenzen holen", "Rare besiegen und looten", "Defeat it and collect essences"),
    ),
    "azmeri-spirit": (
        ("Dem Irrlicht nähern", "Dem Wisp nähern", "Approach the wisp"),
        ("Durch Gegnergruppen folgen", "Durch lebende Packs folgen", "Follow it through living packs"),
        ("Besessenen Wirt besiegen", "Besessenen Host besiegen", "Defeat the possessed host"),
    ),
    "breach": (
        ("Den Riss öffnen", "Den Breach öffnen", "Open the Breach"),
        ("Gegner besiegen, Leiste füllen", "Mit Kills die Leiste füllen", "Kill Hiveborn to fill the bar"),
        ("Bei voller Leiste zurückkehren", "Bei 100 % zum Start zurück", "Return to the start at 100%"),
    ),
    "expedition": (
        ("Markierungen prüfen", "Marker prüfen", "Read the markers"),
        ("Sprengkette über die Ziele legen", "Explosives über die Ziele legen", "Chain explosives over targets"),
        ("Sprengen und Gegner besiegen", "Sprengen und Gegner besiegen", "Detonate and clear the enemies"),
    ),
    "aldur": (
        ("Runenrezept am Relikt wählen", "Runic Recipe am Remnant wählen", "Choose a runic recipe"),
        ("Gegner-Effekte prüfen", "Monster Mods prüfen", "Review monster modifiers"),
        ("Wellen besiegen, Beute holen", "Waves besiegen, Reward holen", "Beat the waves and claim loot"),
    ),
    "atziri": (
        ("Vaal-Leuchtfeuer aufladen", "Vaal Beacons aufladen", "Charge Vaal Beacons"),
        ("Räume und Wege verbinden", "Rooms und Paths verbinden", "Connect rooms and paths"),
        ("Tempel öffnen, Ziel erreichen", "Temple öffnen, Ziel erreichen", "Enter and reach the target room"),
    ),
}
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


def _is_game_mechanic(record):
    return record.get("mechanic") and record["id"] not in league_guides()


def _is_lineage_support(record):
    return "Lineage" in (tag.strip() for tag in (record.get("tags") or "").split(","))


@dataclass
class LexiconBrowser:
    query: str = ""
    group: str = "all"
    facet: str = ""
    variant_page: int = 0
    base: dict | None = None
    show_original: bool = False
    outer_results: tuple[str, int] | None = None

    @property
    def category(self):
        if self.group == "all" and not self.query:
            return "terms"
        return GROUP_ALIASES.get(self.group, self.group)

    def matches(self, language, website):
        if website is None:
            website = bundled_lexicon()
        group = self.category
        # The default search may look across tabs. A selected tab or base
        # can still narrow that same query.
        if group == "all" and self.query:
            entries = lexicon_search_entries(language, website)
        elif group in {"items", "currency"}:
            _, items = lexicon_terms_and_items(language, website)
            currency = group == "currency" or self.facet == "currency"
            entries = (entry for entry in items if (entry.target["facet"] == "currency") == currency)
        elif group in NODE_GROUPS:
            entries = catalogue_entries(language, "nodes")
            if self.group != "nodes":
                entries = (entry for entry in entries if entry.target["facet"] in NODE_GROUPS[group])
        elif group == "mods":
            entries = modifier_entries(language, self.base)
        else:
            entries = published_terms(language, website)
            if self.group == "mechanics" or (group == "terms" and self.facet == "mechanics"):
                entries = (entry for entry in entries if _is_game_mechanic(entry.target["row"]))
                return find_entries(entries, self.query, "lexicon")
            if group == "league":
                entries = (entry for entry in entries if entry.target["row"]["id"] in league_guides())
        if self.facet:
            def facet(entry):
                if group == "terms":
                    return entry.target["row"].get("topic")
                if group == "supports":
                    return "lineage" if _is_lineage_support(entry.target["row"]) else ""
                return entry.target.get("side" if group == "mods" else "facet")
            entries = (entry for entry in entries if facet(entry) == self.facet)
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

    def article_title(value, summary, *, ref, **style):
        canvas = message(value, **style)

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

    def button_art(widget, ref, size=26):
        image = build_icon(widget, ref, window._icon_pixels(size))
        if image:
            widget.configure(image=image, compound="left")
            widget.icon = image
            return image.width()
        return 0

    def row(distribute=False):
        controls = FlowRow(parent, bg=parent.cget("background"), gap=px(4), distribute=distribute)
        controls.pack(fill="x", padx=px(4), pady=(0, px(4)))
        return controls

    def button(container, title, action, *, active=False):
        widget = window.small_button(container, title, action)
        if active:
            widget.configure(bg=theme.selection_color, fg=theme.selection_text)
        return widget

    def link(container, label, url, *, wrap=None):
        if url and urlsplit(url).scheme == "https":
            widget = button(container, label + " ↗", lambda: webbrowser.open(url))
            widget.configure(fg=theme.accent)
            if wrap:
                widget.configure(wraplength=px(wrap), justify="left")

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
        back = text("Zurück zur Liste", "Back to list")
        selected = window.lookup_entry.target
        if browser.group == "league" and selected["group"] == "terms":
            back = text("Zurück zu Liga-Mechaniken", "Back to league mechanics")
        if browser.outer_results is not None:
            query, page = browser.outer_results
            button(actions, text("Zurück zu den Suchergebnissen", "Back to search results"),
                   lambda: window._set_lookup("all", query=query, page=page))
        else:
            button(actions, back, lambda: window._set_lookup(page=window.lookup_page))
        _render_article(window, language, message, row, button, link, pages, picture=picture,
                        title=article_title, button_art=button_art)
        return

    def set_group(group):
        browser.group, browser.facet = group, ""
        browser.base = None
        window._set_lookup()

    def set_facet(facet):
        browser.facet = "" if browser.facet == facet else facet
        window._set_lookup()

    def activate_preview(event):
        event.widget.invoke()
        return "break"

    categories = row()
    website = window.app.website_lexicon()
    active_category = browser.category
    for group, names in GROUPS.items():
        button(categories, display_label(names, language), lambda group=group: set_group(group),
               active=group == active_category)
    params = {"thema": active_category} if active_category in GROUPS else {}
    if browser.query:
        params["q"] = browser.query
    url = web_url(language, "lexikon-filter", **params)
    link(categories, text("Web-Ansicht", "Web view"), url)
    if facets := FACETS.get(active_category):
        filters = row()
        for facet, names in facets.items():
            button(filters, display_label(names, language), lambda facet=facet: set_facet(facet),
                   active=facet == browser.facet)
    if browser.category == "mods" and browser.base:
        toolbar = row()
        base = browser.base
        base_title = base.get("de") or base["name"] if language == "de" else base["name"]
        button(toolbar, base_title + " ×", lambda: set_group("mods"), active=True)

    matches = browser.matches(language, website)
    if not matches:
        message(text("Keine Treffer", "No results"), tone="muted")
        return
    page = min(window.lookup_page, (len(matches) - 1) // PAGE_SIZE)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(matches))
    message(f"{start + 1}–{end} / {len(matches)}", tone="muted", points=9)
    for entry in matches[start:end]:
        if entry.target["group"] in {"pools", "affixes"}:
            render_modifier_preview(window, parent, entry, language)
            continue
        accent, ref = _entry_visual(entry)
        subtitle = _preview_subtitle(entry, language)
        caption = f"{entry.title}\n{subtitle}" if subtitle else entry.title
        widget = button(parent, caption, lambda entry=entry: window._pick_lookup(entry))
        color = accent or theme.text
        widget.configure(anchor="w", justify="left", padx=px(8), pady=px(3), fg=color,
                         activeforeground=color, takefocus=True)
        space = px(24) + button_art(widget, ref)
        widget.bind("<Configure>", lambda event, space=space: event.widget.configure(
            wraplength=max(1, event.width - space)))
        widget.bind("<Return>", activate_preview)
        widget.pack(fill="x", padx=px(4), pady=(0, px(3)))
    pages(page, PAGE_SIZE, len(matches), lambda page: window._set_lookup(page=page))


def _localized_url(url, language):
    parts = urlsplit(url)
    if parts.hostname != "buildschmiede.de":
        return url
    params = [(key, language if key == "sprache" else value)
              for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    if not any(key == "sprache" for key, _ in params):
        params.append(("sprache", language))
    return urlunsplit(parts._replace(query=urlencode(params)))


def _league_related(guide, language, website):
    ids = [target["id"] for target in guide["tooltip_targets"]]
    terms = {ident: website[ident] for ident in ids if ident in website}
    found = {entry.target["row"]["id"]: entry for entry in published_terms(language, terms)}
    for entry in catalogue_entries(language, "items"):
        ident = entry.target["row"].get("currencyId")
        if ident in ids:
            found[ident] = entry
    return [found[ident] for ident in ids if ident in found]


def _lineage_location_entries(ids, language, website):
    locations = {ident: website[ident] for ident in ids if ident in website}
    return {entry.target["row"]["id"]: entry for entry in published_terms(language, locations)}


def _lineage_related(target, language, website):
    lineage = lineage_sources()
    group = target["group"]
    if group == "terms" and (location := lineage.locations.get(target["row"]["id"])):
        supports = lineage_support_entries(language)
        return [(supports[drop["supportId"]], localized_text(drop.get("note"), language))
                for drop in location["drops"] if drop["supportId"] in supports]
    if group == "nodes" and target["facet"] == "support":
        drops = lineage.by_support.get(target["ident"], ())
        results = _lineage_location_entries((ident for ident, _ in drops), language, website)
        return [(results[ident], localized_text(drop.get("note"), language))
                for ident, drop in drops if ident in results]
    return []


def _league_visual(guide):
    accent, icon_id = LEAGUE_VISUALS.get(guide["slug"], (None, ""))
    return accent, currencies().get(icon_id, {}).get("imageLocal")


def _entry_visual(entry):
    target = entry.target
    group, facet = target["group"], target.get("facet")
    record = target.get("row", {})
    if group == "terms":
        if guide := league_guides().get(record.get("id")):
            return _league_visual(guide)
        role = record.get("role")
    elif group == "nodes":
        role = {"skill": "gem", "support": "support"}.get(facet)
    elif group == "items":
        role = facet
    else:
        role = None
    node_id = target["ident"] if group == "nodes" and facet not in {"skill", "support"} else None
    return TITLE_ROLE_COLORS.get(role), tooltip_art_ref(record, node_id=node_id)


def _preview_subtitle(entry, language):
    target = entry.target
    if target.get("facet") == "support" and _is_lineage_support(target["row"]):
        return display_label(LINEAGE_LABELS, language)
    if target["group"] != "terms":
        return " · ".join(entry.details)
    record = target["row"]
    if record["id"] in league_guides():
        return display_label(GROUPS["league"], language)
    if record.get("mechanic"):
        return display_label(MECHANICS_LABELS, language)
    return " · ".join(entry.details[1:])


def _modifier_tags(window, row, tags, language, *, context=(), action=None):
    px, theme = window.layout.px, window.theme
    surface = row.cget("background")
    style = catalogue().get("affixUi", {})

    def pill(text, color=None):
        label = tk.Label(row, text=text, font=window.ui_font(8), padx=px(4), pady=px(1), bd=0,
                         fg=color or theme.text, bg=mix_color(surface, color, 0.12) if color else surface,
                         highlightthickness=1,
                         highlightbackground=mix_color(surface, color, 0.38) if color else theme.edge)
        if action:
            label.configure(cursor="hand2")
            label.bind("<ButtonRelease-1>", lambda event: action())

    for value in context:
        pill(value)
    for tag in tags:
        color = style.get("tagColors", {}).get(tag)
        pill(tag_label(tag, language), color if color != style.get("defaultTagColor") else None)


def render_modifier_preview(window, parent, entry, language):
    px = window.layout.px
    card = tk.Frame(parent, bg=window.theme.control)
    card.pack(fill="x", padx=px(4), pady=(0, px(3)))

    def open_entry(event=None):
        window._pick_lookup(entry)
        return "break"

    title = window.small_button(card, entry.title, open_entry)
    title.configure(anchor="w", justify="left", padx=px(8), pady=px(3), takefocus=True,
                    activeforeground=window.theme.text)
    title.bind("<Configure>", lambda event: title.configure(wraplength=max(1, event.width - px(20))))
    title.bind("<Return>", open_entry)
    title.pack(fill="x")
    tags = FlowRow(card, bg=card.cget("background"), gap=px(3))
    tags.pack(fill="x", padx=px(8), pady=(0, px(4)))
    _modifier_tags(window, tags, entry.target["tags"], language, context=entry.details, action=open_entry)


def _guide_url(value, language):
    if not isinstance(value, str):
        return ""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith("/") or "\\" in value:
        return ""
    return _localized_url(urlunsplit(parts._replace(scheme="https", netloc="buildschmiede.de")), language)


def _native_guide(window, local, label, language):
    kind, ident = local.get("kind"), local.get("id")
    if kind == "campaign" and ident:
        if window.lookup_category_available(kind) and (area := window.campaign_area_for_layout(ident)):
            return lambda: window.open_link(("area", area))
    elif kind == "atlas" and window.lookup_category_available(kind):
        if any(ident == quest["id"] or any(ident == step["id"] for step in quest["steps"])
               for quest in window.endgame._questlines()):
            return lambda: window.open_atlas_tab("quests", ident)
    entry = None
    if kind in {"faq", "constructs"}:
        if kind == "constructs" and not ident and window.lookup_category_available(kind):
            return lambda: window._set_lookup(kind, query="")
        entry = next((entry for entry in editorial_entries(language)
                      if entry.category == kind and entry.target["id"] == ident), None)
    elif kind in {"league", "lexicon"}:
        website = window.app.website_lexicon()
        record = website.get(ident) or next((row for row in website.values() if row.get("slug") == ident), None)
        if record and (kind == "lexicon" or record["id"] in league_guides()):
            entry = next(published_terms(language, {record["id"]: record}), None)
    elif kind == "build":
        build = next((build for build in window.companion.data.get("builds", ()) if build["id"] == ident), None)
        if build:
            entry = make("builds", build["name"], build)
    elif kind == "tips" and ident in AFFIX_TIPS:
        entry = make("tips", label, ident)
    elif kind == "crafting-helper":
        entry = make("tools", label, kind)
    if entry and window.lookup_entry_available(entry):
        return lambda: window._set_lookup(entry.category, query="", entry=entry)
    return None


def _related_guides(window, entry, language):
    record = entry.target.get("article") or entry.target.get("row") or {}
    slug = record.get("slug")
    if not slug and record.get("id", "").startswith("website."):
        fragment = urlsplit(record.get("url") or "").fragment
        slug = fragment.removeprefix("begriff-") if fragment.startswith("begriff-") else record["id"].removeprefix("website.")
    if not slug:
        return []
    terms, targets = lexicon_guides()
    links = []
    for ident in dict.fromkeys(terms.get(slug, ())):
        if target := targets.get(ident):
            label = localized_text(target["label"], language)
            action = _native_guide(window, target.get("local") or {}, label, language)
            url = _guide_url(target.get("url"), language)
            if label and (action or url):
                links.append((label, action, url))
    return links


def _render_league_sections(guide, language, message, *, compact):
    sections = {section["key"]: section["text"][language] for section in guide["sections"]}
    headings = (
        ("play", ("So läuft die Begegnung ab", "So läuft die Begegnung ab", "How the encounter plays out"), "info"),
        ("purpose", ("Wann lohnt es sich?", "Wann lohnt es sich?", "When is it worth doing?"), "success"),
        ("scale", ("Aufwand und Ertrag", "Aufwand und Ertrag", "Difficulty and rewards"), "info"),
        ("rewards", ("Belohnungen", "Belohnungen", "Rewards"), "quest"),
    )
    for key, label, tone in headings:
        if not sections.get(key):
            continue
        message(display_label(label, language), tone=tone)
        if key == "play" and (steps := LEAGUE_STEPS.get(guide["slug"])):
            captions = [display_label(step, language) for step in steps]
            accent = LEAGUE_VISUALS[guide["slug"]][0]
            message(" → ".join(captions), manual_colors=dict.fromkeys(captions, accent), points=10)
            if compact:
                continue
        for paragraph in sections[key].split("\n\n"):
            first, separator, _ = paragraph.partition(". ")
            message(first + "." if compact and key in {"purpose", "scale"} and separator else paragraph)


def _render_article(window, language, message, row, button, link, pages, *, picture=None, title=None, button_art=None):
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
    guide = league_guides().get(record.get("id")) if group == "terms" else None
    lineage = lineage_sources()
    lineage_location = lineage.locations.get(record["id"]) if group == "terms" else None
    lineage_support = group == "nodes" and target["facet"] == "support" and target["ident"] in lineage.by_support
    related_guides = _related_guides(window, entry, language)
    summary, paragraphs = entry_copy(entry, language)
    accent, ref = _entry_visual(entry)
    if title:
        title(entry.title, summary, ref=ref, body_color=accent)
    else:
        message(entry.title, body_color=accent)
    if ref and picture:
        picture(ref)
    if group == "terms":
        subtitle = _preview_subtitle(entry, language)
        if guide:
            subtitle += " · Patch " + guide["patch"]
        message(subtitle, tone="muted", points=9)
        if language == "hybrid":
            titles = [name for name in dict.fromkeys(record["title"].values()) if name != entry.title]
            message(" · ".join(titles), tone="muted", points=10)
        message(summary)
        if guide:
            url = web_url(language, "begriff-" + guide["slug"], thema="league")
        else:
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
        if lineage_support:
            url = web_url(language, "support-" + target["ident"], thema="supports")
        elif target["facet"] != "support":
            fragment = ("skill-" if target["facet"] == "skill" else "passiv-") + target["ident"]
            url = web_url(language, fragment)
    elif group == "items":
        currency = target["facet"] == "currency"
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
                browser.group, browser.facet, browser.query, browser.base = "mods", "", "", base
                window._set_lookup()
            button(row(), text("Passende Affixe", "Applicable affixes"), show_affixes)
        if currency and not url and record.get("currencyId"):
            url = web_url(language, "lexikon-filter", thema="currency", currency=record["currencyId"])
        elif not currency:
            url = web_url(language, "affix-katalog")
    else:
        message(" · ".join(entry.details), tone="muted", points=10)
        message(summary)
        variants = target["rows"]
        base = window.lexicon.base if window.lexicon.category == "mods" else None
        page = min(window.lexicon.variant_page, (len(variants) - 1) // VARIANTS_PER_PAGE)
        start = page * VARIANTS_PER_PAGE
        for variant in variants[start:start + VARIANTS_PER_PAGE]:
            if group == "pools":
                tier, level = variant.tier, variant.level
                names_en, names_de = variant.names_en, variant.names_de
                stats_en, stats_de = variant.stats_en, variant.stats_de
                weight, tags = variant.weight, variant.tags
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
                tags = tuple(tag for tag in variant["tags"] if tag != "default")
                weight = affix_weight(variant, base) if base else None
                suffix = text(f" · Rollgewicht {weight}", f" · Roll weight {weight}") if type(weight) is int else ""
                source(variant.get("source"))
            level_label = display_label((f"Gegenstandsstufe {level}", f"Itemlevel {level}", f"Item level {level}"),
                                        language)
            tier_label = str(tier) if tier and str(tier).startswith("T") else f"T{tier}" if tier else ""
            label = " · ".join(filter(None, (name, tier_label, level_label)))
            message(label + suffix, tone="gold", points=10)
            modifiers(stats_en or (() if de else stats_de), stats_de)
            if tags:
                _modifier_tags(window, row(), tags, language)
        def go(page):
            window.lexicon.variant_page = page
            window.refresh_guide()
        pages(page, VARIANTS_PER_PAGE, len(variants), go)
        source(target.get("url"))
        url = web_url(language, "affix-katalog")
    if paragraphs and not guide and (not lineage_location or record.get("article")):
        message(text("Erklärung & Praxis", "Explanation & examples"), tone="gold")
        for paragraph in paragraphs:
            message(paragraph)
    if guide:
        _render_league_sections(guide, language, message, compact=window.guide_mode == "veteran")
        if guide["slug"] == "delirium":
            button(row(), text("Konstrukt-Fundorte", "Construct maps"),
                   lambda: window._set_lookup("constructs", query=""))
        related = _league_related(guide, language, window.app.website_lexicon())
        if related:
            message(text("Im Lexikon nachschlagen", "Explore in the glossary"), tone="gold")
            controls = row()
            for item in related:
                widget = button(controls, item.title, lambda item=item: window._pick_lookup(item))
                ref = tooltip_art_ref(item.target["row"])
                if button_art:
                    button_art(widget, ref, 22)
                    widget.configure(wraplength=window.layout.px(150), fg=window.theme.accent)
                preview = (item.title, entry_copy(item, language)[0], None, ref)
                widget.detail_at_point = lambda x, y, preview=preview: (preview[0], preview)
                window.app.term_tips.register(widget)
    website = window.app.website_lexicon() if lineage_location or lineage_support else {}
    related = _lineage_related(target, language, website) if website else []
    if related:
        headline = (display_label(LINEAGE_LABELS, language) if lineage_location
                    else text("Fundorte", "Drop locations"))
        message(headline, tone="gold")
        controls = None
        for item, note in related:
            if controls is None:
                controls = row()
            widget = button(controls, item.title, lambda item=item: window._pick_lookup(item))
            widget.configure(fg=window.theme.accent, wraplength=window.layout.px(220), justify="left")
            if button_art:
                _, ref = _entry_visual(item)
                button_art(widget, ref, 22)
            if note:
                message(note)
                controls = None
    if lineage_location and (slugs := lineage_location.get("related")):
        available = {item["slug"]: ident for ident, item in lineage.locations.items()}
        ids = [available[slug] for slug in slugs if slug in available]
        locations = _lineage_location_entries(ids, language, website)
        if locations:
            message(text("Passende Orte", "Related locations"), tone="gold")
            controls = row()
            for item in locations.values():
                widget = button(controls, item.title, lambda item=item: window._pick_lookup(item))
                widget.configure(fg=window.theme.accent, wraplength=window.layout.px(220), justify="left")
    if related_guides:
        message(text("Passende Guides", "Related guides"), tone="gold")
        controls = row()
        for label, action, url in related_guides:
            if action:
                widget = button(controls, label, action)
                widget.configure(fg=window.theme.accent, wraplength=window.layout.px(220), justify="left")
            else:
                link(controls, label, url, wrap=220)
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
    profiles = target.get("profiles", ())
    if len(profiles) > 1:
        count = len(profiles)
        label = text(f"Profile & Quellen ({count})", f"Profiles & sources ({count})")

        def toggle_profiles():
            if profile_links.winfo_manager():
                profile_links.pack_forget()
                toggle.configure(text="▸ " + label)
            else:
                profile_links.pack(fill="x", padx=window.layout.px(4), pady=(0, window.layout.px(4)))
                toggle.configure(text="▾ " + label)

        toggle = button(row(), "▸ " + label, toggle_profiles)
        profile_links = row()
        profile_links.pack_forget()
        for profile, source_url in profiles:
            link(profile_links, profile, source_url, wrap=180)


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
