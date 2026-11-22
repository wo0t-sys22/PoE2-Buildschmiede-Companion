"""Native, width-aware browser for the Buildschmiede affix database."""

from dataclasses import dataclass, field, replace
import re
import tkinter as tk
from urllib.parse import urlencode, urlsplit
import webbrowser

from poe2_affix_catalog import AffixFilters, QUICK_TAGS, options, search, tag_label
from poe2_lexicon import catalogue
from poe2_lexicon_ui import _item_lines
from poe2_overlay_controls import FlowRow
from poe2_overlay_lookup import QUERY_LIMIT, search_text
from poe2_website_content import localized_text


CATALOG_URL = "https://buildschmiede.de/grundlagen/affixe-modifikatoren/"
RESULTS_PER_PAGE = 12
VARIANTS_PER_PAGE = 8
CHOICES_PER_PAGE = 14
FILTER_LABELS = {
    "category": ("Kategorie", "Category"),
    "profile": ("Attributprofil", "Attribute profile"),
    "base": ("Basis", "Base"),
    "database": ("Modifikatorliste", "Modifier list"),
    "pool": ("Modpool", "Mod pool"),
    "side": ("Modart", "Modifier type"),
    "tag": ("Tag", "Tag"),
    "sort": ("Sortierung", "Sort"),
}
ADVANCED_FILTERS = ("database", "pool", "side", "tag", "sort")
CATEGORY_SECTIONS = (
    (("Rüstung & Nebenhand", "Armour & off-hand"),
     ("boots", "body", "helmet", "gloves", "shield", "buckler", "focus", "quiver")),
    (("Einhandwaffen", "One-handed weapons"),
     ("onehand-axe", "onehand-sword", "onehand-mace", "dagger", "claw", "wand", "sceptre", "spear", "flail")),
    (("Zweihandwaffen", "Two-handed weapons"),
     ("twohand-axe", "twohand-sword", "twohand-mace", "bow", "crossbow", "staff", "warstaff", "talisman", "traptool")),
    (("Schmuck & Zubehör", "Jewellery & accessories"),
     ("belt", "amulet", "ring", "charms", "jewels", "life-flasks", "mana-flasks")),
    (("Allgemeine Mechaniken", "General mechanics"),
     ("waystones", "relics", "strongboxes", "shrines", "burning-monolith", "trial-sekhemas", "trial-chaos")),
    (("Liga-Mechaniken", "League mechanics"),
     ("aldur", "temple", "essence", "azmeri", "rogue-exile", "abyss", "breach", "ritual", "delirium", "expedition", "league")),
)
CATEGORY_HEADINGS = {key: title for title, keys in CATEGORY_SECTIONS for key in keys}
COLOR = re.compile(r"#[0-9a-f]{6}", re.IGNORECASE)


@dataclass
class AffixBrowser:
    filters: AffixFilters = field(default_factory=AffixFilters)
    show_tags: bool = False
    show_advanced: bool = False
    page: int = 0
    picker: str = ""
    picker_query: str = ""
    picker_page: int = 0
    current: str = ""
    variant_page: int = 0

    def set_filters(self, **changes):
        self.filters = replace(self.filters, **changes)
        self.page = self.variant_page = self.picker_page = 0
        self.current = self.picker = self.picker_query = ""


def render_affix_tool(window, parent):
    _AffixView(window, parent).draw()


def render_affix_tip(window, parent, key):
    view = _AffixView(window, parent)
    drawers = {"itemGuide": view.draw_item_guide, "affixGuide": view.draw_guide,
               "weightGuide": view.draw_weight_guide}
    drawers[key](view.root)


class _AffixView:
    def __init__(self, window, parent):
        self.window = window
        self.state = window.affix_browser
        self.language = window.app.language
        self.en = self.language == "en"
        self.catalog = catalogue()
        self.style = self.catalog.get("affixUi", {})
        self.theme = window.theme
        self.px = window.layout.px
        self.surface = parent.cget("background")
        self.root = tk.Frame(parent, bg=self.surface)
        self.root.pack(fill="x")
        families = window.app.font_families
        body = next((families[k] for k in ("instrument sans", "inter", "segoe ui", "dejavu sans") if k in families),
                    window.app.ui_family)
        serif = next((families[k] for k in ("georgia", "liberation serif", "dejavu serif") if k in families), body)
        cinzel = window.layout.font("Cinzel", 12, "bold")
        heading = "Cinzel" if cinzel.actual("family").casefold() == "cinzel" else serif
        self.body_font = window.layout.font(body, 10)
        self.small_font = window.layout.font(body, 9)
        self.button_font = window.layout.font(body, 9, "bold")
        self.heading_font = window.layout.font(heading, 12, "bold")
        self.title_font = window.layout.font(heading, 14)
        self.tag_font = window.layout.font(serif, 9)
        self.memo_filters = None
        self.available = {}
        self.results = None

    def text(self, german, english):
        return english if self.en else german

    def localized(self, value):
        if isinstance(value, list):
            return value[{"hybrid": 0, "de": 1, "en": 2}[self.language]]
        return localized_text(value, self.language) if isinstance(value, dict) else (value or "")

    def label(self, parent, value, *, tone="text", small=False, colors=None, color=None):
        if value:
            font = self.heading_font if tone == "gold" else self.small_font if small else self.body_font
            self.window.pack_message(parent, value, font=font, tone=tone, manual_colors=colors, body_color=color)

    def row(self, parent, *, distribute=False):
        row = FlowRow(parent, bg=parent.cget("background"), gap=self.px(4), distribute=distribute)
        row.pack(fill="x", padx=self.px(4), pady=(0, self.px(4)))
        return row

    def button(self, parent, value, action, *, active=False, color=None):
        button = self.window.small_button(parent, value, action)
        button.configure(font=self.button_font)
        if active:
            button.configure(bg=self.theme.selection_color, fg=self.theme.selection_text)
        if color:
            button.configure(fg=color, activeforeground=color)
            if active:
                button.configure(bg=self.theme.active)
        return button

    def wide_button(self, parent, value, action, *, active=False):
        button = self.button(parent, value, action, active=active)
        button.configure(anchor="w", justify="left", padx=self.px(8), pady=self.px(4))
        button.bind("<Configure>", lambda event: button.configure(wraplength=max(1, event.width - self.px(20))))
        button.pack(fill="x", padx=self.px(4), pady=(0, self.px(3)))
        return button

    def link(self, row, text, url):
        if url and urlsplit(url).scheme == "https":
            self.button(row, text, lambda: webbrowser.open(url), color=self.theme.accent)

    def disclosure(self, parent, title, render, *, expanded=False, changed=None):
        body = tk.Frame(parent, bg=self.surface)
        arrow = "▾" if expanded else "▸"

        def toggle():
            if changed:
                changed()
                return
            if body.winfo_manager():
                body.pack_forget()
                control.configure(text=f"▸ {title}")
            else:
                show()
                control.configure(text=f"▾ {title}")
            self.window._schedule_targets()

        def show():
            if not body.winfo_children():
                render(body)
            body.pack(fill="x", after=control, padx=self.px(4), pady=(0, self.px(4)))

        control = self.wide_button(parent, f"{arrow} {title}", toggle, active=expanded)
        if expanded:
            show()

    def draw(self):
        for control in self.root.winfo_children():
            control.destroy()
        if self.state.filters != self.memo_filters:
            self.available = options(self.state.filters, self.language)
            self.memo_filters = self.state.filters
            self.results = None
        title = self.text("PoE 2 Affix-Datenbank", "PoE 2 affix database")
        self.window.pack_message(self.root, title, font=self.title_font, body_color="#f5eee2")
        if self.state.picker == "refine" and not self.item_refinements():
            self.state.picker = ""
        if self.state.picker == "refine":
            self.draw_refinement()
        elif self.state.picker:
            self.draw_picker(self.available)
        else:
            self.draw_navigation()
            self.draw_filters(self.available)
            self.draw_results()
        self.window._schedule_targets()

    def draw_navigation(self):
        current = self.state.filters
        field = tk.Frame(self.root, bg=self.surface)
        field.pack(fill="x", padx=self.px(4), pady=(0, self.px(4)))
        search_label = self.text("Affix oder Gegenstand suchen", "Search for an affix or item")
        search = self.button(field, current.query or search_label, lambda: self.prompt(
            search_label, current.query, lambda value: self.set_filters(query=value[:QUERY_LIMIT])))
        search.configure(compound="left", anchor="w", bg=self.theme.field_color, font=self.body_font, padx=self.px(8))
        self.window._set_hud_icon(search, "lookup", self.window._icon_pixels(13), self.theme.accent)
        if current.query:
            clear = self.button(field, "×", lambda: self.set_filters(query=""))
            clear.pack(side="right", padx=(self.px(4), 0))
        search.pack(side="left", fill="x", expand=True)
        self.fit_caption(search, current.query or search_label, inset=40, font=self.body_font)
        actions = self.row(self.root, distribute=True)
        for view, label in (("affixes", self.text("Affixe", "Affixes")),
                            ("items", self.text("Gegenstände", "Items"))):
            self.button(actions, label, lambda view=view: self.set_view(view),
                        active=current.view == view)

    def fit_caption(self, button, caption, *, inset=20, font=None):
        font = font or self.button_font

        def fit(event):
            available = max(0, event.width - self.px(inset))
            text = caption
            if font.measure(text) > available:
                while text and font.measure(text + "…") > available:
                    text = text[:-1]
                text += "…"
            if button.cget("text") != text:
                button.configure(text=text)

        button.bind("<Configure>", fit)

    def toggle(self, key):
        setattr(self.state, key, not getattr(self.state, key))
        self.draw()

    def prompt(self, title, initial, apply, *, validate=None):
        self.window._open_input_dialog(title, initial, apply, self.text("Übernehmen", "Apply"), validate=validate)

    def set_filters(self, *, picker="", **changes):
        self.state.set_filters(**changes)
        self.state.picker = picker
        self.draw()
        self.scroll_top()

    def set_view(self, view):
        if view != self.state.filters.view:
            self.set_filters(**vars(AffixFilters(view=view, query=self.state.filters.query)))

    def scroll_top(self):
        if canvas := getattr(self.window, "route_canvas", None):
            canvas.yview_moveto(0)

    def draw_filters(self, available):
        current = self.state.filters
        affixes = current.view == "affixes"
        primary = tk.Frame(self.root, bg=self.surface)
        primary.pack(fill="x", padx=self.px(4), pady=(0, self.px(4)))
        if affixes:
            self.level_button(primary, "max_level", "max.").pack(side="right", padx=(self.px(4), 0))
            self.level_button(primary, "min_level", "min.").pack(side="right", padx=(self.px(4), 0))
        selection = self.item_selection() or self.text("Gegenstand wählen", "Choose item")
        caption = selection + " ▾"
        choose = self.button(primary, caption, lambda: self.select_picker("refine" if current.category else "category"),
                             active=bool(self.item_selection()))
        choose.configure(anchor="w", padx=self.px(6))
        choose.pack(side="left", fill="x", expand=True)
        self.fit_caption(choose, caption)
        actions = self.row(self.root)
        if affixes:
            tag_caption = self.tag_title(current.tag) if current.tag else "Tags"
            tag_caption += " ▴" if self.state.show_tags else " ▾"
            self.button(actions, tag_caption, lambda: self.toggle("show_tags"),
                        active=self.state.show_tags or bool(current.tag), color=self.color(current.tag) if current.tag else None)
        extra_count = sum(bool(getattr(current, key)) for key in self.advanced_keys())
        filter_caption = self.text("Filter", "Filters") + (f" ({extra_count})" if extra_count else "")
        filter_caption += " ▴" if self.state.show_advanced else " ▾"
        self.button(actions, filter_caption, lambda: self.toggle("show_advanced"), active=self.state.show_advanced)
        if current != AffixFilters(view=current.view, query=current.query):
            self.button(actions, self.text("Zurücksetzen", "Reset"), self.reset)
        if affixes and self.state.show_tags:
            valid = dict(available.get("tag", ()))
            self.tags(self.root, (tag for tag in self.style.get("quickTags", QUICK_TAGS) if tag in valid))
        if self.state.show_advanced:
            extra = self.row(self.root)
            for key in self.advanced_keys():
                self.filter_button(extra, key, available)

    def advanced_keys(self):
        return ADVANCED_FILTERS if self.state.filters.view == "affixes" else ("tag", "sort")

    def level_button(self, parent, key, label):
        number = getattr(self.state.filters, key)
        bound = "≥" if key == "min_level" else "≤"
        prompt = f"iLvl {label}"
        caption = f"iLvl {bound}{number}" if number else prompt
        return self.button(parent, caption, lambda: self.prompt(
            prompt, str(number or ""), lambda value: self.set_filters(**{key: int(value or 0)}),
            validate=lambda value: not value or value.isascii() and value.isdecimal() and 1 <= len(value) <= 3),
            active=bool(number))

    def selection_label(self, key):
        value = getattr(self.state.filters, key)
        return dict(self.available.get(key, ())).get(value, value)

    def item_selection(self):
        return self.selection_label("base") or self.selection_label("category") or self.selection_label("profile")

    def item_refinements(self):
        keys = ("profile", "base") if self.state.filters.view == "affixes" else ("profile",)
        return tuple(key for key in keys if self.available.get(key))

    def reset(self):
        current = self.state.filters
        self.set_filters(**vars(AffixFilters(view=current.view, query=current.query)))

    def filter_button(self, row, key, available):
        current = getattr(self.state.filters, key)
        values = dict(available.get(key, ()))
        if not any(values) and not current:
            return
        title = self.text(*FILTER_LABELS[key])
        caption = values.get(current, current) if current else title
        self.button(row, caption + " ▾", lambda: self.select_picker(key), active=bool(current))

    def select_picker(self, key):
        self.state.picker = key
        self.state.picker_query = ""
        self.state.picker_page = 0
        self.draw()
        self.scroll_top()

    def draw_refinement(self):
        title = self.selection_label("category") or self.text("Gegenstand wählen", "Choose item")
        self.label(self.root, title, tone="gold")
        actions = self.row(self.root)
        self.button(actions, self.text("Kategorien", "Categories"), lambda: self.select_picker("category"))
        for key in self.item_refinements():
            self.filter_button(actions, key, self.available)
        self.wide_button(self.root, self.text("Treffer zeigen", "Show results"), lambda: self.select_picker(""), active=True)

    def draw_picker(self, available):
        key = self.state.picker
        controls = self.row(self.root)
        title = self.text(*FILTER_LABELS[key])
        back = "refine" if key in ("profile", "base") and self.state.filters.category else ""
        self.button(controls, self.text("Zurück", "Back"), lambda: self.select_picker(back))
        self.button(controls, self.text("Auswahl suchen", "Find an option"), lambda: self.prompt(
            title, self.state.picker_query, self.picker_query))
        self.label(self.root, title, tone="gold")
        if self.state.picker_query:
            self.label(self.root, self.state.picker_query, small=True)
        words = search_text(self.state.picker_query).split()
        aliases = self.style.get("categoryAliases", {}) if key == "category" else {}
        values = [(value, label) for value, label in available.get(key, ()) if value and all(
            word in search_text(" ".join((value, label, *aliases.get(value, ())))) for word in words
        )]
        self.wide_button(self.root, self.text("Alle Kategorien", "All categories") if key == "category"
                         else self.text("Alle", "All"), lambda: self.choose(key, ""),
                         active=not getattr(self.state.filters, key))
        if not values:
            self.label(self.root, self.text("Keine passende Auswahl", "No matching option"), tone="muted")
            return
        page = self.pager(self.root, self.state.picker_page, len(values), CHOICES_PER_PAGE,
                          lambda value: self.go("picker_page", value))
        last_heading = None
        for value, label in values[page * CHOICES_PER_PAGE:(page + 1) * CHOICES_PER_PAGE]:
            if key == "category" and not words:
                heading = CATEGORY_HEADINGS.get(value) or ("Weitere Kategorien", "More categories")
                if heading != last_heading:
                    self.label(self.root, self.text(*heading), small=True, color="#c2c4c6")
                    last_heading = heading
            self.wide_button(self.root, label, lambda value=value: self.choose(key, value),
                             active=value == getattr(self.state.filters, key))

    def picker_query(self, value):
        self.state.picker_query = value[:QUERY_LIMIT]
        self.go("picker_page", 0)

    def choose(self, key, value):
        reset = {"category": ("profile", "base", "database"), "profile": ("base", "database"),
                 "base": ("database",), "database": ("base",)}
        updates = dict.fromkeys(reset.get(key, ()), "")
        updates[key] = value
        refine = bool(value) and key in ("category", "profile")
        self.set_filters(picker="refine" if refine else "", **updates)

    def go(self, field_name, page):
        setattr(self.state, field_name, page)
        if field_name == "page":
            self.state.current = ""
            self.state.variant_page = 0
        self.draw()
        if field_name == "page":
            self.scroll_top()

    def pager(self, parent, page, total, size, change):
        page = max(0, min(page, (total - 1) // size))
        first = page * size
        row = self.row(parent)
        tk.Label(row, text=f"{first + 1}–{min(first + size, total)} / {total}",
                 bg=row.cget("background"), fg="#c2c4c6", font=self.small_font,
                 padx=self.px(4), pady=self.px(4))
        if total > size:
            if page:
                self.button(row, self.text("Zurück", "Previous"), lambda: change(page - 1))
            if first + size < total:
                self.button(row, self.text("Weiter", "Next"), lambda: change(page + 1))
        return page

    def draw_guide(self, body):
        guide = self.catalog.get("affixGuide", {})
        self.label(body, self.localized(guide.get("summary")))
        for section in guide.get("sections", ()):
            self.label(body, self.localized(section.get("title")), tone="gold")
            for line in section.get("lines", ()):
                self.label(body, self.localized(line.get("text")))
        sources = self.row(body)
        for source in guide.get("sources", ()):
            self.link(sources, self.localized(source.get("label")), source.get("url"))
        self.link(sources, self.text("Web-Ansicht", "Web view"), CATALOG_URL + "?" + urlencode({"sprache": self.language}))

    def draw_item_guide(self, body):
        if not (guide := self.style.get("itemGuide")):
            return
        self.label(body, self.localized(guide["intro"]))
        video = f'https://www.youtube.com/watch?v={guide["video"]}'
        for index, (title, detail) in enumerate(zip(guide["facts"][::2], guide["facts"][1::2])):
            moment = guide["factTimes"][index]
            self.link(self.row(body), self.localized(title), f"{video}&t={moment}s")
            self.label(body, self.localized(detail))
        for section in guide["sections"]:
            self.link(self.row(body), self.localized(section["title"]), f'{video}&t={section["time"]}s')
            self.label(body, self.localized(section["body"]))
        for level, en, de in guide["rolls"]:
            self.label(body, f"iLvl {level} · {de if self.language == 'de' else en}")
        sources = self.row(body)
        self.link(sources, self.text("Video ansehen", "Watch the video"), video)
        for url in guide["sources"]:
            self.link(sources, self.source_name(url), url)

    def draw_weight_guide(self, body):
        if not (guide := self.style.get("weightGuide")):
            return
        self.label(body, self.localized(guide["text"]))
        self.link(self.row(body), "PoE2DB", self.localized(guide["url"]))

    def draw_results(self):
        current = self.state.filters
        if self.results is None:
            self.results = search(current, self.language)
        if not self.results:
            self.label(self.root, self.text("Keine Treffer", "No results"), tone="muted")
            return
        page = self.pager(self.root, self.state.page, len(self.results), RESULTS_PER_PAGE,
                          lambda value: self.go("page", value))
        items = current.view == "items"
        for result in self.results[page * RESULTS_PER_PAGE:(page + 1) * RESULTS_PER_PAGE]:
            ident = result["id"]
            caption = result["title"]
            if not items:
                caption += "\n" + self.family_summary(result)
            self.disclosure(self.root, caption, lambda body, result=result: self.draw_item(body, result) if items
                            else self.draw_family(body, result), expanded=self.state.current == ident,
                            changed=lambda ident=ident: self.select_result(ident))

    def family_summary(self, family):
        level = family.get("max_level") or "—"
        weight = family.get("weight")
        total = self.text("Gewichtssumme", "Total weight")
        if weight is None:
            weight = "—"
        elif family.get("partial_weight"):
            weight = f"≥{weight}"
        group = family.get("section", "")
        return " · ".join(filter(None, (group, f'{len(family["variants"])} {self.text("Varianten", "variants")}',
                                        f"iLvl {level}", f"{total} {weight}")))

    def select_result(self, ident):
        self.state.current = "" if self.state.current == ident else ident
        self.state.variant_page = 0
        self.draw()

    def color(self, tag):
        value = self.style.get("tagColors", {}).get(tag) or self.style.get("defaultTagColor")
        return value if isinstance(value, str) and COLOR.fullmatch(value) else None

    def tag_title(self, tag):
        return self.localized(self.style.get("tagLabels", {}).get(tag)) or tag_label(tag, self.language)

    def pick_tag(self, tag):
        self.state.show_tags = False
        self.set_filters(tag="" if self.state.filters.tag == tag else tag)

    def tags(self, body, tags):
        tags = tuple(dict.fromkeys(tag for tag in tags if tag != "default"))
        if tags:
            row = self.row(body)
            for tag in tags:
                current = self.state.filters.tag == tag
                button = self.button(row, self.tag_title(tag), lambda tag=tag: self.pick_tag(tag),
                                     active=current, color=self.color(tag))
                button.configure(font=self.tag_font)

    def draw_family(self, body, family):
        variants = family["variants"]
        page = self.pager(body, self.state.variant_page, len(variants), VARIANTS_PER_PAGE,
                          lambda value: self.go("variant_page", value))
        for variant in variants[page * VARIANTS_PER_PAGE:(page + 1) * VARIANTS_PER_PAGE]:
            tier = str(variant.get("tier") or "")
            tier = (tier if tier.startswith("T") else f"T{tier}") if tier else "—"
            weight = variant.get("weight")
            if weight is None:
                weight = self.text("Garantiert", "Guaranteed") if variant.get("guaranteed") else "—"
            weight_label = self.text("Rollgewicht", "Roll weight")
            title = f'{tier} · iLvl {variant.get("level") or "—"} · {weight_label} {weight}'
            self.label(body, title, tone="gold")
            self.label(body, variant.get("name"), tone="muted", small=True)
            if profiles := variant.get("profiles"):
                self.label(body, " · ".join(label for label, _ in profiles), tone="muted", small=True)
            tags = variant.get("tags", ())
            colors = {self.tag_title(tag): color for tag in tags if (color := self.color(tag))}
            for line in variant.get("stats", ()):
                self.label(body, line, colors=colors)
            self.tags(body, tags)
            self.disclosure(body, self.text("Regeln", "Rules"), lambda rules, variant=variant: self.draw_rules(rules, variant))

    def draw_rules(self, body, variant):
        def rule_text(rule):
            tag, weight = rule
            eligible = self.text("rollbar", "eligible") if weight > 0 else self.text("ausgeschlossen", "excluded")
            return f"{tag} · {eligible}"

        if rule := variant.get("matching_rule"):
            self.label(body, rule_text(rule), small=True)
        if rules := variant.get("weights"):
            for rule in rules:
                self.label(body, rule_text(rule), small=True)
        else:
            if bases := variant.get("bases"):
                self.label(body, " · ".join(bases), small=True)
            if excluded := variant.get("excluded"):
                title = self.text("Ausgeschlossen", "Excluded")
                self.label(body, f"{title} · " + " · ".join(excluded), small=True)
        self.label(body, variant.get("condition"), small=True)
        self.label(body, variant["id"], tone="muted", small=True)
        if profiles := variant.get("profiles"):
            sources = self.row(body)
            for label, url in profiles:
                if url:
                    self.link(sources, label, url)
        elif source := variant.get("source"):
            self.link(self.row(body), self.source_name(source), source)

    def draw_item(self, body, result):
        item = result["item"]
        kind = item.get("kind")
        item_type = item.get("item", {}).get("type") or item.get("type", "")
        label = {"unique": self.text("Einzigartig", "Unique"), "currency": self.text("Währung", "Currency"),
                 "waystone": self.text("Wegstein", "Waystone"), "tablet": self.text("Tablet", "Tablet")}.get(kind, item_type)
        self.label(body, " · ".join(filter(None, (label, item.get("base")))), tone="muted", small=True)
        self.label(body, " · ".join(_item_lines(item, self.en, self.language == "de")), small=True)
        self.label(body, item.get("item", {}).get("implicit"))
        self.label(body, self.localized(item.get("description")))
        for line in item.get("stats", ()):
            self.label(body, line)
        if variants := item.get("variants"):
            self.label(body, self.text("Varianten", "Variants") + " · " + " · ".join(variants))
        self.tags(body, item.get("tags", ()))
        source = (item.get("sourceDe") if self.language == "de" else None) or item.get("source")
        base = item.get("base") or item.get("modBase") if kind else item.get("name")
        category = {"waystone": "waystones", "tablet": "tablets"}.get(kind, "")
        if source or base or category:
            actions = self.row(body)
            if source:
                self.link(actions, self.source_name(source), source)
            if base or category:
                label = self.text("Affixe dieser Basis", "Affixes for this base") if base else self.text(
                    "Modifikatoren der Kategorie", "Modifiers for this category")
                self.button(actions, label, lambda: self.set_filters(**{
                    **vars(AffixFilters()), "base": base or "", "category": category,
                }))

    @staticmethod
    def source_name(url):
        return "PoE2Wiki" if "poe2wiki.net" in url else "PoE2DB"
