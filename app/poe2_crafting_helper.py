"""Offline crafting recommendations from the shared affix profiles."""

from dataclasses import dataclass
from functools import lru_cache
import re
import tkinter as tk

from poe2_lexicon import catalogue, display_stats
from poe2_overlay_controls import FlowRow
from poe2_overlay_lookup import QUERY_LIMIT, make, search_text
from poe2_overlay_theme_art import mix_color
from poe2_regex import LIMIT, available, fresh, query_length, search_query, type_names
from poe2_regex_ui import copy_regex
from poe2_r18_features import BASE_DIR, PALETTE, read_json


TITLE = ("Crafting-Helfer", "Crafting Helper")
CRAFTING_TIPS = read_json(BASE_DIR / "shared-data" / "crafting-tips.v1.json")
RARITIES = {
    "normal": ("Normal", "Normal"),
    "magic1": ("Magisch · 1 Affix", "Magic · 1 affix"),
    "magic2": ("Magisch · 2 Affixe", "Magic · 2 affixes"),
    "rare": ("Selten", "Rare"),
}
SIDES = {"Prefix": ("Präfix", "prefix"), "Suffix": ("Suffix", "suffix")}
STEP_CURRENCY = {
    "normal": ("currency.orb_of_transmutation", "Umwandlungssphäre", "Orb of Transmutation"),
    "magic1": ("currency.orb_of_augmentation", "Aufwertungssphäre", "Orb of Augmentation"),
    "magic2": ("currency.regal_orb", "Hoheitliche Sphäre", "Regal Orb"),
    "rare": ("currency.exalted_orb", "Erhabene Sphäre", "Exalted Orb"),
}
EXCLUDED = re.compile(r"Tablet|Waystone|Relic|Ultimatum|Strongbox|Flask|Charm|Jewel|Ruby|Diamond|Sapphire|Emerald", re.I)
ATTRIBUTE_SUFFIX = re.compile(r"_(?:str|dex|int)(?:_(?:str|dex|int))*$")
STAT_VALUE = re.compile(r"^[+#%()\d.,\s–—−-]+")
STAT_RANGE = re.compile(r"\([−-]?\d+(?:[.,]\d+)?[-–—][−-]?\d+(?:[.,]\d+)?\)")
STAT_NUMBER = re.compile(r"(?<![^\W_])\d+(?:[.,]\d+)?")
STAT_LABELS = {
    "to maximum life": ("Maximales Leben", "Maximum Life"),
    "to maximum mana": ("Maximales Mana", "Maximum Mana"),
    "increased movement speed": ("Bewegungsgeschwindigkeit", "Movement Speed"),
    "increased physical damage": ("Physischer Schaden (%)", "Physical Damage (%)"),
    "increased spell damage": ("Zauberschaden", "Spell Damage"),
    "increased attack speed": ("Angriffsgeschwindigkeit", "Attack Speed"),
    "increased cast speed": ("Zaubergeschwindigkeit", "Cast Speed"),
    "to armour": ("Rüstung (+)", "Armour (+)"),
    "increased armour": ("Rüstung (%)", "Armour (%)"),
    "to accuracy rating": ("Genauigkeit", "Accuracy"),
    "to fire resistance": ("Feuerwiderstand", "Fire Resistance"),
    "to cold resistance": ("Kältewiderstand", "Cold Resistance"),
    "to lightning resistance": ("Blitzwiderstand", "Lightning Resistance"),
    "to chaos resistance": ("Chaoswiderstand", "Chaos Resistance"),
}
PER_PAGE = 7


@lru_cache(maxsize=1)
def item_types():
    groups = {}
    for key, profile in catalogue()["profiles"].items():
        if EXCLUDED.search(key) or not any(section == "Base Prefix" for _, section, _ in profile[4]):
            continue
        groups.setdefault(ATTRIBUTE_SUFFIX.sub("", key), []).append(key)
    return groups


@dataclass(frozen=True)
class Target:
    side: str
    family: str
    tier: int
    level: int
    names_en: tuple
    names_de: tuple
    values_en: tuple
    values_de: tuple
    modifier_id: str

    @property
    def key(self):
        return self.side, self.family

    def stats(self, language):
        return display_stats(self.values_en, language, german=self.values_de)

    def label(self, language):
        stats = self.stats(language)
        result = []
        for index, english in enumerate(self.stats("en")):
            labels = STAT_LABELS.get(STAT_VALUE.sub("", english).casefold())
            result.append(labels[language != "de"] if labels else (stats[index] if index < len(stats) else english))
        return " + ".join(result or (self.names_de if language == "de" and self.names_de else self.names_en))


def valid_item_level(value):
    return bool(re.fullmatch(r"[0-9]{1,3}", value)) and 1 <= int(value) <= 100


@lru_cache(maxsize=64)
def eligible_targets(base, level):
    profile = catalogue()["profiles"].get(base)
    if not profile or not 1 <= level <= 100:
        return ()
    result = []
    for _, section, families in profile[4]:
        if section not in {"Base Prefix", "Base Suffix"}:
            continue
        side = section.removeprefix("Base ")
        for family, rows in families:
            highest = max((row for row in rows if row[1] <= level and row[7] != 0),
                          key=lambda row: row[1], default=None)
            if highest:
                tier, required, names_en, names_de, stats_en, stats_de, _, _, modifier_id = highest
                result.append(Target(side, family, tier, required, tuple(names_en), tuple(names_de),
                                     tuple(stats_en), tuple(stats_de), modifier_id))
    return tuple(result)


def target_regex(item_type, target, language):
    client = "de" if language == "de" else "en"
    if item_type not in type_names("Vendor", client):
        return ""
    profile = fresh()
    profile["types"] = [item_type]
    choices = [row for row in available(profile).values() if row.get(client + "Pattern")]
    mod = next((row for row in choices if row["id"] == target.modifier_id), None)
    if mod is None and target.values_en:
        comparable = STAT_RANGE.sub("#", target.values_en[0]).casefold().strip()
        variable = STAT_NUMBER.sub("#", comparable)
        mod = next((row for row in choices
                    if row.get("enMinimum") and row["en"].casefold() == variable), None)
        if mod is None:
            mod = next((row for row in choices if row["en"].casefold() == comparable), None)
    if mod is None:
        return ""
    profile["rules"] = [{"key": mod["en"], "use": "want", "min": 0}]
    result = search_query(profile, client)
    return result if query_length(result) <= LIMIT else ""


def next_step(rarity, side, language):
    slot = SIDES[side][language == "en"]
    if language == "hybrid":
        return {
            "normal": "Mach die Base mit einer Orb of Transmutation Magic und prüfe den ersten Mod.",
            "magic1": "Ist der Slot für deinen Ziel-Mod frei? Dann kann eine Orb of Augmentation ihn rollen.",
            "magic2": "Beide Slots sind belegt. Sind beide Mods gut, macht eine Regal Orb das Item Rare und rollt einen weiteren Mod.",
            "rare": "Prüfe den freien Slot und die vorhandene Modgruppe. Auf einem passenden Rare kann eine Exalted Orb einen weiteren Mod rollen.",
        }[rarity]
    steps = {
        "normal": ("Mach den Gegenstand mit einer Umwandlungssphäre magisch und prüfe den ersten Mod.",
                   "Use an Orb of Transmutation and check the first modifier."),
        "magic1": (f"Ist der {slot}-Platz frei? Dann kann eine Aufwertungssphäre den Ziel-Mod hinzufügen.",
                   f"If the {slot} slot is free, an Orb of Augmentation can add the target modifier."),
        "magic2": ("Beide Plätze sind belegt. Behalte gute Mods. Eine Hoheitliche Sphäre macht den Gegenstand selten und fügt einen weiteren zufälligen Mod hinzu.",
                   "Both slots are occupied. Keep good rolls and use a Regal Orb to make the item rare and add a random modifier."),
        "rare": (f"Prüfe, ob ein {slot}-Platz frei und die Modgruppe verfügbar ist. Eine Erhabene Sphäre kann dann einen zufälligen Mod hinzufügen.",
                 f"Check for a free {slot} slot and an available mod group. An Exalted Orb can then add a random modifier."),
    }
    return steps[rarity][language == "en"]


@dataclass
class CraftingHelperState:
    item_type: str = "Boots"
    base: str = ""
    level: int = 1
    target: tuple = ()
    rarity: str = "normal"
    picker: str = ""
    query: str = ""
    page: int = 0
    details: bool = False
    show_checks: bool = False
    show_example: bool = False


def render_craft_helper(window, parent):
    _CraftingView(window, parent).draw()


class _CraftingView:
    def __init__(self, window, parent):
        self.window = window
        self.parent = parent
        self.language = window.app.language
        self.english = self.language == "en"
        self.state = window.app.crafting_helper
        self.px = window.layout.px

    def text(self, german, english):
        return english if self.english else german

    def message(self, value, **style):
        self.window.pack_message(self.parent, value, **style)

    def button(self, label, action, *, selected=False):
        button = self.window.small_button(self.parent, label, action)
        button.configure(anchor="w", justify="left")
        if selected:
            theme = self.window.theme
            button.configure(bg=theme.selection_color, fg=theme.selection_text)
        button.bind("<Configure>", lambda event: button.configure(wraplength=max(1, event.width - self.px(20))))
        button.pack(fill="x", pady=(0, self.px(4)))

    def update(self, **changes):
        for key, value in changes.items():
            setattr(self.state, key, value)
        self.window.refresh_guide()

    def draw(self):
        self.message(self.text(*TITLE), tone="gold", points=14)
        groups = item_types()
        if not groups:
            self.message(self.text("Die Mod-Daten sind nicht verfügbar.", "Modifier data is unavailable."))
            return
        state = self.state
        if state.item_type not in groups:
            state.item_type = next(iter(groups))
        bases = groups[state.item_type]
        if state.base not in bases:
            state.base = bases[0]
        targets = eligible_targets(state.base, state.level)
        target = next((target for target in targets if target.key == state.target), None)
        if target is None and targets:
            target = targets[0]
        state.target = target.key if target else ()
        profiles = catalogue()["profiles"]
        label_index = self.language != "de"
        types = [(key, profiles[keys[0]][label_index].split("(")[0].strip()) for key, keys in groups.items()]
        variants = [(key, profiles[key][label_index]) for key in bases]
        goals = [(item.key, f"{item.label(self.language)} · {self.text(*SIDES[item.side])}") for item in targets]
        rarities = [(key, self.text(*label)) for key, label in RARITIES.items()]
        fields = {
            "item_type": (self.text("Gegenstandsart", "Item type"), types),
            "base": (self.text("Basis", "Base"), variants),
            "target": (self.text("Gewünschter Wert", "Target modifier"), goals),
            "rarity": (self.text("Zustand des Gegenstands", "Item state"), rarities),
        }
        if state.picker in fields:
            self.draw_picker(*fields[state.picker])
            return
        for key in ("item_type", "base"):
            self.draw_field(key, *fields[key])
        self.button(self.text("Gegenstandsstufe (Itemlevel)", "Item level") + f" · {state.level}  ›", self.edit_level)
        if target:
            self.draw_field("target", *fields["target"])
        self.draw_field("rarity", *fields["rarity"])
        if not target:
            self.message(self.text("Für diese Basis und Stufe gibt es keinen passenden Mod.",
                                   "No modifier matches this base and item level."))
        else:
            self.draw_result(target)
        self.draw_checks()
        self.draw_example()

    def draw_example(self):
        expanded = self.state.show_example
        title = self.text("Praxisbeispiel · Bewegungsgeschwindigkeit", "Example · Movement Speed")
        self.button(f"{'▾' if expanded else '▸'} {title}", lambda: self.update(show_example=not expanded))
        if not expanded:
            return
        if self.language == "hybrid":
            lines = ("Wähle reine Dex-Boots und gib Itemlevel 70 ein. Der natürliche Movement-Speed-Prefix kann 30 % rollen. Für 35 % brauchst du Itemlevel 82.",
                     "Auf Magic Boots mit Life-Prefix kann eine Orb of Augmentation nur einen Suffix rollen. Bei einem Resistenz-Suffix kann der freie Prefix Movement Speed rollen.")
        else:
            lines = (self.text("Wähle reine Geschicklichkeitsstiefel und gib Gegenstandsstufe 70 ein. Das natürliche Präfix für Bewegungsgeschwindigkeit kann 30 % erreichen. Für 35 % brauchst du Gegenstandsstufe 82.",
                               "Select pure Dexterity boots and enter item level 70. The natural Movement Speed prefix can roll 30%. The 35% tier requires item level 82."),
                     self.text("Bei magischen Stiefeln mit Lebenspräfix kann eine Aufwertungssphäre nur ein Suffix hinzufügen. Bei einem Widerstandssuffix kann das freie Präfix Bewegungsgeschwindigkeit würfeln.",
                               "On magic boots with a life prefix, an Orb of Augmentation can only add a suffix. With a resistance suffix, the open prefix can roll Movement Speed."))
        for line in lines:
            self.message(line, marker=True)

    def draw_checks(self):
        if CRAFTING_TIPS.get("schema") != "buildschmiede.crafting-tips.v1":
            return
        expanded = self.state.show_checks
        title = CRAFTING_TIPS["title"][self.language]
        self.button(f"{'▾' if expanded else '▸'} {title}", lambda: self.update(show_checks=not expanded))
        if not expanded:
            return
        variant = "compact" if self.window.guide_mode == "veteran" else "detail"
        for check in CRAFTING_TIPS["checks"]:
            self.message(check[variant][self.language], marker=True)
        if not self.window.lookup_category_available("lexicon"):
            return
        links = FlowRow(self.parent, bg=self.parent.cget("background"), gap=self.px(4))
        links.pack(fill="x", pady=(self.px(4), 0))
        for ident in CRAFTING_TIPS["lexicon"]:
            entry = self.window.app.term_tips.build_lexicon_entry(("term", ident))
            if entry:
                self.window.small_button(links, entry.title, lambda entry=entry: self.window._pick_lookup(entry))

    def draw_field(self, field, title, choices):
        caption = dict(choices)[getattr(self.state, field)]
        self.button(f"{title} · {caption}  ›", lambda: self.update(picker=field, query="", page=0))

    def edit_level(self):
        self.window._open_input_dialog(
            self.text("Gegenstandsstufe (1–100)", "Item level (1–100)"), str(self.state.level),
            lambda value: self.update(level=int(value)), self.text("Übernehmen", "Apply"),
            validate=valid_item_level,
        )

    def draw_picker(self, title, choices):
        state = self.state
        field = state.picker
        self.button(self.text("‹ Zurück zum Crafting-Helfer", "‹ Back to Crafting Helper"), lambda: self.update(picker=""))
        self.message(title, tone="gold")
        if len(choices) > PER_PAGE:
            title = self.text("Auswahl durchsuchen", "Search choices")
            self.button(f"{title} · {state.query}" if state.query else title, lambda: self.window._open_input_dialog(
                title, state.query, lambda value: self.update(query=value[:QUERY_LIMIT], page=0),
                self.text("Suchen", "Search"),
            ))
            if state.query:
                self.button(self.text("Suche leeren", "Clear search"), lambda: self.update(query="", page=0))
        words = search_text(state.query).split()
        choices = [(key, label) for key, label in choices if all(word in search_text(label) for word in words)]
        if not choices:
            self.message(self.text("Keine passenden Einträge.", "No matching entries."))
            return
        current = getattr(state, field)
        pages = (len(choices) + PER_PAGE - 1) // PER_PAGE
        state.page = min(state.page, pages - 1)
        start = state.page * PER_PAGE
        for key, label in choices[start:start + PER_PAGE]:
            self.button(label, lambda value=key: self.update(picker="", **{field: value}), selected=key == current)
        if pages > 1:
            row = FlowRow(self.parent, bg=self.parent.cget("background"), gap=self.px(4))
            if state.page > 0:
                self.window.small_button(row, self.text("‹ Zurück", "‹ Previous"),
                                         lambda: self.update(page=state.page - 1))
            if state.page + 1 < pages:
                self.window.small_button(row, self.text("Weiter ›", "Next ›"),
                                         lambda: self.update(page=state.page + 1))
            row.pack(fill="x")
            self.message(f"{state.page + 1} / {pages}", tone="muted", points=9)

    def draw_result(self, target):
        state = self.state
        theme = self.window.theme
        background = mix_color(self.parent.cget("background"), theme.accent, 0.1)
        result = tk.Frame(self.parent, bg=background, highlightbackground=theme.accent, highlightthickness=1)
        result.guide_card_color = background
        result.pack(fill="x", pady=(self.px(3), self.px(6)))
        ident, german, english = STEP_CURRENCY[state.rarity]
        currency = german if self.language == "de" else english
        self.window.pack_message(result, self.text("Nächster Schritt", "Next step"), tone="gold", points=13)
        self.window.pack_message(result, next_step(state.rarity, target.side, self.language),
                                 term_refs={currency: ident}, manual_colors={currency: PALETTE["currency"]})
        self.window.pack_message(result, self.text("Der Zielwert ist ein möglicher Ausgang. Welche Modifikation entsteht, ist zufällig.",
                                                   "The target modifier is a possible outcome. The actual modifier is random."),
                                 tone="muted", points=10)
        indicator = "▾" if state.details else "▸"
        self.button(f"{indicator} {self.text('Ziel-Mod und Roll prüfen', 'Inspect target roll')}",
                    lambda: self.update(details=not state.details))
        if state.details:
            for line in target.stats(self.language):
                self.message(line)
            slot = self.text(*SIDES[target.side])
            level = self.text("Gegenstandsstufe", "Item level")
            self.message(f"{slot} · T{target.tier} · {level} {target.level}", tone="muted", points=10)
            self.button(self.text("In der Affix-Datenbank öffnen", "Open in the affix database"),
                        lambda: self.open_affix(target))
            if result := target_regex(state.item_type, target, self.language):
                self.button(self.text("Regex für den Ziel-Mod kopieren", "Copy regex for target modifier"),
                            lambda: copy_regex(self.window, result, self.language))

    def open_affix(self, target):
        names = target.names_de if self.language == "de" and target.names_de else target.names_en
        self.window.affix_browser.set_filters(view="affixes", database=self.state.base, category="", base="",
                                              max_level=self.state.level, min_level=0, pool="equipment",
                                              side=target.side, tag="", sort="", query=next(iter(names), ""))
        title = self.text("Affixe & Modifikatoren", "Affixes & Modifiers")
        self.window._set_lookup("tools", entry=make("tools", title, "affixes"))
