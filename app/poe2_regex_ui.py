"""Controls for the inline PoE 2 Regex Tool in the HUD."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import webbrowser

from poe2_overlay_controls import FlowRow
from poe2_regex import (
    BOUNDS, CATEGORIES, LIMIT, PRESETS, PROFILE_LIMIT, RARITIES, available, export_profile,
    fresh, load_export, preset_profile, query_length, search_query, type_names,
)


MODS_PER_PAGE = 8
REGEX_WEBSITE_URL = "https://buildschmiede.de/regex/"
ITEM_FAMILIES = (
    (("Waffen", "Weapons"), (
        "Claws", "Daggers", "Wands", "One_Hand_Swords", "One_Hand_Axes", "One_Hand_Maces",
        "Sceptres", "Spears", "Flails", "Bows", "Staves", "Two_Hand_Swords", "Two_Hand_Axes",
        "Two_Hand_Maces", "Quarterstaves", "Crossbows", "Traps", "Talismans",
    )),
    (("Rüstung", "Armour"), ("Gloves", "Boots", "Body_Armours", "Helmets")),
    (("Schmuck", "Jewellery"), ("Amulets", "Rings", "Belts")),
    (("Nebenhand", "Off-hand"), ("Quivers", "Shields", "Bucklers", "Foci")),
)


@dataclass
class RegexState:
    profile: dict = field(default_factory=fresh)
    drafts: dict = field(default_factory=dict)
    query: str = ""
    page: int = 0
    category_open: bool = False
    show_types: bool = False
    show_filters: bool = False
    show_presets: bool = False
    item_family: int = 0

    def set_profile(self, profile):
        self.drafts[self.profile["cat"]] = self.profile
        self.profile = profile
        self.query = ""
        self.page = 0
        if profile["cat"] == "Vendor":
            first_type = next(iter(profile["types"]), None)
            self.item_family = next((i for i, (_, keys) in enumerate(ITEM_FAMILIES) if first_type in keys), 0)


def copy_regex(window, result, language):
    english = language == "en"
    try:
        window.window.clipboard_clear()
        window.window.clipboard_append(result)
    except tk.TclError:
        window.flash("Could not copy." if english else "Kopieren fehlgeschlagen.")
    else:
        window.flash("Search copied. Paste into the in-game search box with Ctrl+F." if english
                     else "Suchtext kopiert. Im Spiel mit Strg+F einfügen.")


def render_regex(window, parent):
    state = window.app.regex_state
    profile = state.profile
    category = profile["cat"]
    language = window.app.language
    english = language == "en"
    client = "de" if language == "de" else "en"
    theme = window.theme
    px = window.layout.px

    def label(german, translated):
        return translated if english else german

    def row(container=parent, *, distribute=False, top=0):
        actions = FlowRow(container, bg=container.cget("background"), gap=px(4), distribute=distribute)
        actions.pack(fill="x", padx=px(4), pady=(px(top), px(4)))
        return actions

    def button(container, text, action, *, active=False, disabled=False):
        control = window.small_button(container, text, action)
        if active:
            control.configure(bg=theme.selection_color, fg=theme.selection_text)
        if disabled:
            control.configure(state="disabled")
        return control

    def set_field(key, value):
        profile[key] = value
        window.refresh_guide()

    def toggle_panel(key):
        setattr(state, key, not getattr(state, key))
        window.refresh_guide()

    def panel_button(container, title, key):
        opened = getattr(state, key)
        button(container, ("▾ " if opened else "▸ ") + title, lambda: toggle_panel(key), active=opened)

    def choose_category(key):
        if key != category:
            state.set_profile(state.drafts.get(key) or fresh(key))
        state.category_open = True
        window.refresh_guide()

    def back_to_categories():
        state.category_open = False
        window.refresh_guide()

    def reset():
        state.set_profile(fresh(category))
        state.drafts.pop(category, None)
        state.category_open = state.show_types = state.show_presets = state.show_filters = False
        window.refresh_guide()

    def select_profile(value):
        state.set_profile(value)
        window.refresh_guide()

    def edit(title, initial, update, validate=None):
        window._open_input_dialog(title, initial, update, label("Übernehmen", "Apply"), validate=validate)

    def toggle(key, item):
        values = profile[key]
        if item in values:
            values.remove(item)
        else:
            values.append(item)
        if key == "types":
            mods = available(profile)
            profile["rules"] = [rule for rule in profile["rules"] if rule["key"] in mods]
            state.page = 0
        window.refresh_guide()

    try:
        result = search_query(profile, client)
        invalid = False
    except ValueError:
        result, invalid = "", True
    length = query_length(result)
    copy_enabled = bool(result) and length <= LIMIT

    def open_website():
        try:
            if webbrowser.open(REGEX_WEBSITE_URL):
                return
        except webbrowser.Error:
            pass
        window.flash(label("Website konnte nicht geöffnet werden.", "Could not open the website."))

    window.pack_message(parent, label("PoE 2 Regex-Tool", "PoE 2 Regex Tool"), tone="gold")
    window.pack_message(parent, label("Client-Sprache: Deutsch", "Client language: German") if client == "de"
                        else label("Client-Sprache: Englisch", "Client language: English"), tone="muted", points=9)
    if result:
        output = tk.Label(parent, text=result, anchor="w", justify="left", padx=px(4),
                          bg=theme.field_color, fg=theme.text, font=window.layout.font("Courier", 9))
        output.bind("<Configure>", lambda event: output.configure(wraplength=max(1, event.width - px(8))))
        output.pack(fill="x", padx=px(4), pady=(0, px(4)))
    actions = row()
    button(actions, label("Regex kopieren", "Copy regex"), lambda: copy_regex(window, result, language),
           active=copy_enabled, disabled=not copy_enabled)
    website = button(actions, label("Ausführliche Web-Ansicht ↗", "Detailed web view ↗"), open_website)
    website.configure(fg=theme.accent)
    button(actions, label("Zurücksetzen", "Reset"), reset)
    window.pack_message(parent, label("Wertebereich oder Mod prüfen.", "Check range or modifier.") if invalid
                        else f"{length} / {LIMIT}", tone="danger" if invalid or length > LIMIT else "muted", points=9)

    if not state.category_open:
        categories = row(distribute=True, top=4)
        for key, names in CATEGORIES.items():
            button(categories, names[english], lambda key=key: choose_category(key), active=key == category)
        return

    navigation = row(top=4)
    if state.show_types:
        button(navigation, f"← {CATEGORIES[category][english]}", lambda: toggle_panel("show_types"))
    else:
        button(navigation, label("← Bereiche", "← Categories"), back_to_categories)
        window.pack_message(parent, CATEGORIES[category][english], tone="gold")
        options = row()
        panel_button(options, label("Beispiele", "Presets"), "show_presets")
        panel_button(options, label("Gegenstände", "Item types"), "show_types")
        panel_button(options, label("Filter & Profile", "Filters & profiles"), "show_filters")
    if state.show_presets and not state.show_types:
        presets = row()
        for preset in PRESETS:
            button(presets, preset[english], lambda preset=preset: select_profile(preset_profile(preset)))

    names = type_names(category, client)
    chosen = profile["types"]
    keys = names
    if state.show_types:
        if category == "Vendor":
            window.pack_message(parent, label("Gegenstandsklassen", "Item classes"), tone="gold")
            families = row(distribute=True)

            def choose_family(index):
                state.item_family = index
                window.refresh_guide()

            for index, (titles, family_keys) in enumerate(ITEM_FAMILIES):
                count = sum(key in chosen for key in family_keys)
                title = label(*titles)
                button(families, f"{title} ({count})" if count else title,
                       lambda index=index: choose_family(index), active=index == state.item_family)
            keys = ITEM_FAMILIES[state.item_family][1]
        types = row(distribute=category == "Vendor")
        for key in keys:
            name = names[key].replace("One Hand ", "1H ").replace("Two Hand ", "2H ")
            selected = key in chosen
            button(types, f"✓ {name}" if selected else name,
                   lambda key=key: toggle("types", key), active=selected)
    if chosen:
        summary = " · ".join(names[key] for key in chosen)
        window.pack_message(parent, f"{label('Auswahl', 'Selected')} · {summary}", tone="muted", points=9)

    mods = available(profile)
    if state.show_filters:
        _render_filters(window, profile, mods, copy_enabled, label, row, button, edit,
                        set_field, toggle, select_profile)

    def set_query(value):
        state.query = value[:96]
        state.page = 0
        window.refresh_guide()

    search = row(top=6)
    button(search, label("Mods suchen", "Search mods"), lambda: edit(
        label("Mods durchsuchen", "Search mods"), state.query, set_query))
    if state.query:
        button(search, label("Suche leeren", "Clear search"), lambda: set_query(""))
        window.pack_message(parent, state.query, tone="muted", points=9)
    selected = {rule["key"]: rule for rule in profile["rules"]}
    if selected:
        window.pack_message(parent, label("Ausgewählte Mods", "Selected mods"), tone="gold")
        for key, rule in selected.items():
            mod = mods[key]
            card = tk.Frame(parent, bg=theme.field_color, highlightthickness=1, highlightbackground=theme.edge)
            card.guide_card_color = theme.field_color
            card.pack(fill="x", padx=px(4), pady=(0, px(5)))
            window.pack_message(card, mod[client], points=10)
            group = row(card)
            for use, title in (("want", label("Suchen", "Find")), ("avoid", label("Meiden", "Avoid"))):
                active = use == rule["use"]
                button(group, title, lambda rule=rule, use=use: _edit_rule(rule, "use", use, window), active=active)
            if mod.get(client + "Minimum") or rule["min"]:
                button(group, f"Min. {rule['min']}" if rule["min"] else "Min.", lambda rule=rule: edit(
                    label("Mindestwert (0–9999)", "Minimum (0–9999)"), str(rule["min"]),
                    lambda value: _edit_rule(rule, "min", int(value or 0), window),
                    lambda value: not value or (value.isascii() and value.isdecimal() and len(value) <= 4)))
            button(group, label("Entfernen", "Remove"),
                   lambda key=key: set_field("rules", [rule for rule in profile["rules"] if rule["key"] != key]))

    query = state.query.casefold()
    filtered = [(key, mod) for key, mod in mods.items()
                if key not in selected and query in (mod["de"] + " " + key).casefold()]
    page = min(state.page, max(0, (len(filtered) - 1) // MODS_PER_PAGE))
    start = page * MODS_PER_PAGE
    window.pack_message(parent, label("Mod hinzufügen", "Add a mod"), tone="gold")
    candidates = row()
    for key, mod in filtered[start:start + MODS_PER_PAGE]:
        control = button(candidates, mod[client], lambda key=key: set_field(
            "rules", [*profile["rules"], {"key": key, "use": "want", "min": 0}]))
        control.configure(wraplength=max(px(60), window.layout.width - px(48)), justify="left")
    if not filtered:
        window.pack_message(parent, label("Keine passenden Mods.", "No matching mods."), tone="muted", points=9)
    if len(filtered) > MODS_PER_PAGE:
        pages = row()

        def go(offset):
            state.page = page + offset
            window.refresh_guide()

        button(pages, label("Zurück", "Previous"), lambda: go(-1), disabled=not page)
        button(pages, label("Weiter", "Next"), lambda: go(1), disabled=start + MODS_PER_PAGE >= len(filtered))
        window.pack_message(parent, f"{start + 1}–{min(start + MODS_PER_PAGE, len(filtered))} / {len(filtered)}",
                            tone="muted", points=9)


def _edit_rule(rule, key, value, window):
    rule[key] = value
    window.refresh_guide()


def _render_filters(window, profile, mods, copy_enabled, label, row, button, edit,
                    set_field, toggle, select_profile):
    category = profile["cat"]
    flags = row()
    for key, names in RARITIES.items():
        button(flags, label(*names), lambda key=key: toggle("rarities", key), active=key in profile["rarities"])
    if category == "Waystones":
        for key, text in (("corrupt", label("Verderbt", "Corrupted")), ("clean", label("Unverderbt", "Uncorrupted"))):
            button(flags, text, lambda key=key: set_field("state", "" if profile["state"] == key else key),
                   active=profile["state"] == key)
        button(flags, "Delirium", lambda: set_field("delirious", not profile["delirious"]), active=profile["delirious"])
    bounds = row()
    for bound in BOUNDS[category]:
        name = label(bound.de, bound.en)
        low, high = profile["bounds"].get(bound.key, ("", ""))

        def edit_bound(bound=bound, name=name, low=low, high=high):
            def pair(value):
                lower, _, upper = value.partition("-")
                return [lower.strip(), upper.strip()]

            def valid(value):
                limits = pair(value)
                return all(not side or (side.isascii() and side.isdecimal() and len(side) <= 4 and int(side) <= bound.cap)
                           for side in limits) and int(limits[0] or 0) <= int(limits[1] or bound.cap)

            edit(f"{name} (Min-Max, 0–{bound.cap})", f"{low}-{high}" if low or high else "",
                 lambda value: set_field("bounds", {**profile["bounds"], bound.key: pair(value)}), valid)

        button(bounds, f"{name} {low}–{high}" if low or high else name, edit_bound, active=bool(low or high))

    actions = row()
    any_mode = profile["mode"] == "any"
    button(actions, label("Mind. ein Mod", "Any modifier") if any_mode else label("Alle Gruppen", "All groups"),
           lambda: set_field("mode", "all" if any_mode else "any"), active=any_mode)
    for group in dict.fromkeys(mods[rule["key"]].get("group", "Modifiers")
                               for rule in profile["rules"] if rule["use"] == "want"):
        current = profile["groups"].get(group, "all")
        button(actions, f"{group} · {label('Alle', 'All') if current == 'all' else label('Mind. einer', 'Any')}",
               lambda group=group, current=current: set_field(
                   "groups", {**profile["groups"], group: "any" if current == "all" else "all"}),
               active=current == "any", disabled=any_mode)
    button(actions, label("Mindestwerte abrunden", "Round minimums"),
           lambda: set_field("round", not profile["round"]), active=profile["round"])
    button(actions, label("Eigener Suchtext", "Custom search"), lambda: edit(
        label("Eigener Suchtext", "Custom search"), profile["custom"], lambda value: set_field("custom", value)))

    def import_file():
        path = filedialog.askopenfilename(parent=window.window, filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with Path(path).open("rb") as source:
                data = source.read(PROFILE_LIMIT + 1)
            if len(data) > PROFILE_LIMIT:
                raise ValueError("profile size")
            select_profile(load_export(json.loads(data)))
        except (OSError, ValueError):
            window.flash(label("Ungültiges Regex-Profil.", "Invalid Regex profile."))

    def export_file():
        path = filedialog.asksaveasfilename(parent=window.window, defaultextension=".json",
                                            initialfile="buildschmiede-regex.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        client = "de" if window.app.language == "de" else "en"
        try:
            data = export_profile(profile, Path(path).stem, client)
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            window.flash(label("Profil konnte nicht gespeichert werden.", "Could not save profile."))

    profiles = row()
    button(profiles, label("Profil importieren", "Import profile"), import_file)
    button(profiles, label("Profil exportieren", "Export profile"), export_file, disabled=not copy_enabled)
    button(profiles, label("Zurücksetzen", "Reset"), lambda: select_profile(fresh(category)))
