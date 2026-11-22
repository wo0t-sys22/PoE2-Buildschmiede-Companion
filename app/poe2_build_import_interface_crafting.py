"""Slot-based equipment catalogue and a draft editor for rolled item modifiers."""

from copy import deepcopy
from functools import lru_cache
import tkinter as tk
from tkinter import ttk

from poe2_build_art import build_icon
from poe2_build_items import _display_line, item_card, rarity_color, render_item_card
from poe2_build_loadout import slot_label
from poe2_build_import_interface_inventory import ITEM_TYPE_LABELS, _ScrollColumn, _classified_items, _fits_slot
from poe2_item_craft import (affix_caps, augment_choices, craft_choices, craftable, equipped_affixes, item_level,
                            item_quality, midpoint_roll, put_affix, remove_affix, set_augment, set_item_level,
                            set_item_quality, socket_slots)
from poe2_lexicon import base_items, catalogue
from poe2_overlay_controls import AutoHideScrollbar
from poe2_overlay_lookup import search_text


def _display(row, lang):
    return (row.get("de") or row["name"]) if lang == "de" else row["name"]


@lru_cache(maxsize=1)
def _source_labels():
    labels = {en.rsplit(" ", 1)[0]: de.rsplit(" ", 1)[0]
              for profile in catalogue()["profiles"].values() for de, en, _ in profile[4]
              if en.endswith((" Prefix", " Suffix"))}
    labels.update({"Essence": "Essenz", "Perfect Essence / Alloy": "Perfekte Essenz / Legierung"})
    return labels


def _list(parent, height, *, horizontal=False):
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    box = tk.Listbox(frame, width=12, height=height, exportselection=False, activestyle="dotbox",
                     relief="flat", highlightthickness=1)
    box.grid(row=0, column=0, sticky="nsew")
    scroll = AutoHideScrollbar(frame, orient="vertical", command=box.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    box.configure(yscrollcommand=scroll.set)
    if horizontal:
        bar = AutoHideScrollbar(frame, orient="horizontal", command=box.xview)
        bar.grid(row=1, column=0, sticky="ew")
        box.configure(xscrollcommand=bar.set)
    return frame, box


class _BuildImportDialog:
    def __init__(self, interface, title, width, height, *, parent=None):
        self.interface = interface
        self.text = interface.text
        self.lang = interface.language
        parent = parent or interface.item_picker.winfo_toplevel()
        win = self.window = tk.Toplevel(parent)
        win.withdraw()
        win.title(title)
        win.transient(parent)
        win.configure(bg=interface.theme.panel)
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        native = getattr(interface.app, "native", None)
        area = native.work_area(rect=(px, py, px + pw, py + ph)) if native else None
        left, top, right, bottom = area or (0, 0, win.winfo_screenwidth(), win.winfo_screenheight())
        w = min(width, max(1, right - left - 16))
        h = min(height, max(1, bottom - top - 48))
        x = max(left, min(right-w-8, px + (pw-w)//2))
        y = max(top, min(bottom-h-40, py + (ph-h)//2))
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.minsize(min(490, w), min(height-110, h))
        win.bind("<Escape>", lambda _: win.destroy())
        self.body = ttk.Frame(win, padding=12)
        self.body.pack(fill="both", expand=True)

    def show(self, focus):
        self.palette()
        self.window.deiconify()
        self.window.grab_set()
        focus.focus_set()

    def palette(self):
        apply = getattr(self.interface, "apply_palette", None)
        if apply:
            apply(self.window)

    def heading(self, parent, label):
        return tk.Label(parent, text=label, anchor="w", bg=self.interface.theme.panel,
                        fg=self.interface.theme.accent, font=(self.interface.app.ui_family, 11, "bold"))


class BaseCatalogue(_BuildImportDialog):
    def __init__(self, interface, *, bases=False):
        super().__init__(interface, interface.text("Gegenstand wählen", "Choose an item"), 740, 525)
        text = self.text
        self.locale = int(self.lang == "en")
        filters = ttk.Frame(self.body)
        filters.pack(fill="x")
        self.keys = interface.slots
        self.slot = ttk.Combobox(filters, values=[slot_label(s, self.lang) for s in self.keys],
                                 state="readonly", width=12)
        self.slot.current(self.keys.index(interface.gear_slot))
        self.group = ttk.Combobox(filters, state="readonly", width=14)
        self.kind = ttk.Combobox(filters, state="readonly", width=15, values=(text("Alle", "All"),
                                 text("Basen", "Bases"), text("Einzigartige", "Uniques")))
        self.kind.current(int(bases))
        self.query = tk.StringVar(self.window)
        search = ttk.Entry(filters, textvariable=self.query, width=10)
        for col, (label, widget) in enumerate(((text("Platz", "Slot"), self.slot),
                                             (text("Gegenstandstyp", "Item type"), self.group),
                                             (text("Basen oder Uniques", "Bases or uniques"), self.kind))):
            filters.columnconfigure(col, weight=1)
            ttk.Label(filters, text=label).grid(row=0, column=col, sticky="w")
            widget.grid(row=1, column=col, sticky="ew", padx=(0, 6))
        ttk.Label(filters, text=text("Name oder Typ suchen", "Search by name or type")).grid(row=2, column=0,
                                                                                           columnspan=3, sticky="w", pady=(6, 0))
        search.grid(row=3, column=0, columnspan=3, sticky="ew", padx=(0, 6))
        self.count = self.heading(self.body, "")
        self.count.pack(fill="x", pady=(12, 4))
        results = ttk.Frame(self.body)
        results.pack(fill="both", expand=True)
        results.rowconfigure(0, weight=1)
        results.columnconfigure(0, weight=11, uniform="items")
        results.columnconfigure(1, weight=9, uniform="items")
        frame, self.bases = _list(results, 10, horizontal=True)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.preview = _ScrollColumn(results, interface.theme.panel)
        self.preview.frame.grid(row=0, column=1, sticky="nsew")
        footer = ttk.Frame(self.body)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text=text("Schließen", "Close"), command=self.window.destroy).pack(side="left")
        self.craft = ttk.Button(footer, text=text("Basis craften …", "Craft base …"),
                                command=lambda: self.accept(True))
        self.craft.pack(side="right")
        self.equip = ttk.Button(footer, text=text("Ausrüsten", "Equip"), command=self.accept,
                                style="Primary.BuildImport.TButton")
        self.equip.pack(side="right", padx=6)
        self.slot.bind("<<ComboboxSelected>>", self.change_slot)
        self.group.bind("<<ComboboxSelected>>", self.filter)
        self.kind.bind("<<ComboboxSelected>>", self.filter)
        self.query.trace_add("write", self.filter)
        self.bases.bind("<<ListboxSelect>>", self.select)
        self.bases.bind("<Double-1>", lambda _: self.accept())
        self.bases.bind("<Return>", lambda _: self.accept())
        search.bind("<Down>", lambda _: self.bases.focus_set())
        search.bind("<Return>", lambda _: self.accept())
        self.change_slot()
        self.show(search)

    def change_slot(self, *_):
        self.slot_key = self.keys[self.slot.current()]
        self.scope = [(key, row, words) for key, row, words in _classified_items() if _fits_slot(self.slot_key, row)]
        present = {key for key, _, _ in self.scope}
        self.groups = [""] + sorted(present, key=lambda k: ITEM_TYPE_LABELS[k][self.locale].casefold())
        self.group.configure(values=[self.text("Alle Typen", "All types")] +
                                    [ITEM_TYPE_LABELS[k][self.locale] for k in self.groups[1:]])
        self.group.current(0)
        self.filter()

    def filter(self, *_):
        group = self.groups[self.group.current()]
        kind = self.kind.current()
        words = search_text(self.query.get()).split()
        self.rows = sorted(((k, r) for k, r, search in self.scope
                            if (not group or group == k) and (not kind or kind == 1 + bool(r.get("kind")))
                            and all(w in search for w in words)),
                           key=lambda pair: (bool(pair[1].get("kind")), ITEM_TYPE_LABELS[pair[0]][self.locale].casefold(),
                                             _display(pair[1], self.lang).casefold()))
        self.bases.delete(0, "end")
        self.bases.insert("end", *(f"  {_display(r, self.lang)}    ·    {ITEM_TYPE_LABELS[k][self.locale]}"
                                   for k, r in self.rows))
        for i, (_, row) in enumerate(self.rows):
            if row.get("kind") == "unique":
                self.bases.itemconfigure(i, foreground=rarity_color("unique"))
        self.count.configure(text=f"{len(self.rows)} {self.text('Treffer', 'matches')}")
        if self.rows:
            self.bases.selection_set(0)
        self.select()

    def select(self, *_):
        for child in self.preview.body.winfo_children():
            child.destroy()
        idx = self.bases.curselection()
        if idx:
            _, row = self.rows[idx[0]]
            gear = self.gear(row)
            card = item_card(gear, self.lang)
            interface = self.interface
            render_item_card(self.preview.body, card, interface.theme,
                             font=lambda size, weight: (interface.app.ui_family, size, weight),
                             gear=gear, language=self.lang, app=interface.app).pack(fill="x")
            self.equip.state(["!disabled"])
            self.craft.state(["!disabled"] if craftable(gear) else ["disabled"])
        else:
            ttk.Label(self.preview.body, text=self.text("Keine passenden Gegenstände.", "No matching items.")).pack(anchor="w")
            self.palette()
            self.equip.state(["disabled"])
            self.craft.state(["disabled"])
        self.preview.canvas.yview_moveto(0)
        self.preview.bind_wheel(self.preview.frame)

    @staticmethod
    def gear(row):
        if row.get("kind") == "unique":
            return {"unique": row["name"], "base": row.get("base", "")}
        return {"base": row["name"]}

    def accept(self, craft=False):
        idx = self.bases.curselection()
        if not idx:
            return
        row = self.rows[idx[0]][1]
        slot = self.slot_key
        interface = self.interface
        old = interface.setup["gear"].get(slot, {})
        gear = {**{k: old[k] for k in ("goal", "mod") if old.get(k)}, **self.gear(row)}
        if craft and not craftable(gear):
            return
        self.window.destroy()
        if craft:
            return CraftEditor(interface, slot, gear)
        interface._apply_craft(slot, gear)


ERRORS = {
    "invalid_item": ("Diese Basis unterstützt keine frei wählbaren Affixe.", "This base has no editable affixes."),
    "invalid_level": ("Gegenstandsstufe prüfen.", "Check the item level."),
    "invalid_quality": ("Qualität als ganze Zahl von 0 bis 100 eingeben.", "Enter quality as an integer from 0 to 100."),
    "invalid_affix": ("Dieser Modifikator passt nicht zur Basis.", "This modifier does not fit the base."),
    "invalid_tier": ("Dieser Rang ist auf der Gegenstandsstufe nicht verfügbar.", "This tier is unavailable at this item level."),
    "invalid_roll": ("Bitte einen Wert im angezeigten Bereich eingeben.", "Enter a value within the displayed range."),
    "no_capacity": ("Alle passenden Affixplätze sind belegt.", "All matching affix slots are occupied."),
    "group_conflict": ("Ein Modifikator derselben Gruppe ist bereits vorhanden.", "A modifier from this group is already present."),
    "unknown_key": ("Modifikator erneut auswählen.", "Select the modifier again."),
}


class CraftEditor(_BuildImportDialog):
    def __init__(self, interface, slot, gear):
        super().__init__(interface, interface.text("Gegenstand bauen", "Craft item"), 860, 680)
        self.slot_key, self.gear = slot, deepcopy(gear)
        self.side, self.replace = "prefix", None
        text = self.text
        top = ttk.Frame(self.body)
        top.pack(fill="x", pady=(0, 6))
        base = gear.get("base", "")
        name = _display(base_items().get(base, {"name": base}), self.lang)
        title = gear.get("sourceName") or name
        card = item_card(gear, self.lang)
        if title == base:
            title = card.title or name
        header = self.heading(top, f"{title}  ·  {slot_label(slot, self.lang)}")
        self.art = build_icon(self.window, card.icon, 34)
        if self.art:
            header.configure(image=self.art, compound="left", padx=5)
        header.pack(side="left")
        properties = ttk.Frame(self.body)
        properties.pack(fill="x", pady=(0, 9))
        self.heading(properties, text("Gegenstandsstufe", "Item level")).pack(side="left", padx=(0, 6))
        self.level = tk.StringVar(value=str(item_level(gear)))
        level_box = ttk.Spinbox(properties, from_=1, to=100, width=5, textvariable=self.level, command=self.change_level)
        level_box.pack(side="left", padx=(0, 16))
        level_box.bind("<FocusOut>", self.change_level)
        level_box.bind("<Return>", self.change_level)
        ttk.Label(properties, text=text("Qualität (%)", "Quality (%)")).pack(side="left", padx=(0, 5))
        self.quality = tk.StringVar(value=str(item_quality(gear)))
        ttk.Spinbox(properties, from_=0, to=100, width=5, textvariable=self.quality).pack(side="left", padx=(0, 16))
        if socket_slots(self.gear):
            self.socket_button = ttk.Button(properties, command=lambda: RuneEditor(self))
            self.socket_button.pack(side="left")
            self.show_sockets()
        self.current = ttk.Frame(self.body)
        self.current.pack(fill="x")
        self.side_labels = {"prefix": text("Präfixe", "Prefixes"), "suffix": text("Suffixe", "Suffixes"),
                            "unknown": text("Weitere importierte Mods", "Other imported modifiers")}
        self.cols, self.boxes, self.counts, self.add_buttons = {}, {}, {}, {}
        for col, side in enumerate(self.side_labels):
            group = ttk.Frame(self.current)
            self.cols[side] = group
            if col < 2:
                group.grid(row=0, column=col, sticky="nsew", padx=(0, 4) if col == 0 else (4, 0))
                self.current.columnconfigure(col, weight=1, uniform="sides")
            head = ttk.Frame(group)
            head.pack(fill="x")
            self.counts[side] = self.heading(head, "")
            self.counts[side].pack(side="left")
            if side != "unknown":
                button = ttk.Button(head, text=text("+ Wählen", "+ Choose"), width=10,
                                    command=lambda s=side: self.start(s))
                button.pack(side="right")
                self.add_buttons[side] = button
            frame, box = _list(group, 2 if col == 2 else 3, horizontal=True)
            frame.pack(fill="x")
            self.boxes[side] = box
            box.bind("<<ListboxSelect>>", lambda _, s=side: self.select_current(s))

        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=(6, 2))
        self.mode = self.heading(bar, "")
        self.mode.pack(side="left")
        self.side_pick = ttk.Combobox(bar, state="readonly", values=[text("Präfix", "Prefix"), text("Suffix", "Suffix")], width=8)
        self.side_pick.bind("<<ComboboxSelected>>", self.switch_unknown)
        self.remove = ttk.Button(bar, text=text("Aus Item entfernen", "Remove from item"), command=self.delete)
        self.remove.pack(side="right")
        self.selected_label = ttk.Label(self.body, wraplength=620, justify="left")
        self.search = tk.StringVar()
        find = ttk.Frame(self.body)
        find.pack(fill="x", pady=(2, 4))
        ttk.Label(find, text=text("Modifikator suchen", "Find modifier")).pack(side="left", padx=(0, 6))
        self.entry = ttk.Entry(find, textvariable=self.search)
        self.entry.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", self.filter)
        self.family_frame, self.families = _list(self.body, 5, horizontal=True)
        self.family_frame.pack(fill="both", expand=True)
        self.families.bind("<<ListboxSelect>>", self.select_family)
        self.effect = ttk.Label(self.body, anchor="w", wraplength=720, justify="left")
        self.effect.pack(fill="x", pady=(6, 2))
        self.params = ttk.Frame(self.body)
        self.params.pack(fill="x")
        ttk.Label(self.params, text=text("Rang", "Tier")).grid(row=0, column=0, sticky="w")
        self.tier = ttk.Combobox(self.params, width=21, state="readonly")
        self.tier.grid(row=1, column=0, padx=(0, 10))
        self.tier.bind("<<ComboboxSelected>>", self.select_tier)
        self.roll_box = ttk.Frame(self.params)
        self.roll_box.grid(row=0, rowspan=2, column=1, sticky="w")
        self.assign = ttk.Button(self.params, command=self.put)
        self.assign.grid(row=1, column=2, sticky="e")
        self.params.columnconfigure(2, weight=1)
        self.message = ttk.Label(self.body, anchor="w", wraplength=640)
        self.message.pack(fill="x", pady=(4, 0))
        footer = ttk.Frame(self.body)
        footer.pack(fill="x", pady=(6, 0))
        ttk.Button(footer, text=text("Verwerfen", "Discard"), command=self.window.destroy).pack(side="left")
        ttk.Button(footer, text=text("Gegenstand übernehmen", "Apply item"), command=self.commit,
                   style="Primary.BuildImport.TButton").pack(side="right")
        self.refresh()
        free = next((s for s, button in self.add_buttons.items() if button.instate(["!disabled"])), None)
        if not free and (side := next((s for s, rows in self.records.items() if rows), None)):
            self.boxes[side].selection_set(0)
            self.select_current(side)
        else:
            self.start(free or "prefix")
        self.show(self.entry)

    def error(self, exc):
        de, en = ERRORS.get(str(exc), ERRORS["invalid_roll"])
        self.message.configure(text=self.text(de, en))

    def show_sockets(self):
        slots = socket_slots(self.gear)
        filled = sum(bool(name) for name, _ in slots)
        self.socket_button.configure(text=f"{self.text('Runen & Sockel', 'Runes & sockets')} · {filled}/{len(slots)}")

    def change_level(self, *_):
        try:
            level = int(self.level.get().strip())
        except ValueError:
            self.error(ValueError("invalid_level"))
            return False
        if level != item_level(self.gear):
            try:
                set_item_level(self.gear, level)
            except ValueError as exc:
                self.error(exc)
                return False
            self.load_choices()
        self.message.configure(text="")
        return True

    def refresh(self):
        records = equipped_affixes(self.gear, self.lang)
        self.records = {s: [r for r in records if r["side"] == s] for s in self.side_labels}
        caps = dict(zip(("prefix", "suffix"), affix_caps(self.gear)))
        for side, rows in self.records.items():
            box = self.boxes[side]
            box.delete(0, "end")
            box.insert("end", *(r["label"] for r in rows))
            label = self.side_labels[side]
            self.counts[side].configure(text=f"{label}  {len(rows)}/{caps[side]}" if side in caps else label)
            if side in caps:
                available = len(rows) < caps[side] and len(records) < sum(caps.values())
                self.add_buttons[side].state(["!disabled"] if available else ["disabled"])
        if self.records["unknown"]:
            self.cols["unknown"].grid(row=1, column=0, columnspan=2, sticky="ew")
        else:
            self.cols["unknown"].grid_remove()

    def start(self, side, record=None):
        self.side, self.replace = side, record
        for label, box in self.boxes.items():
            if not record or label != record["side"]:
                box.selection_clear(0, "end")
        self.remove.state(["!disabled"] if record else ["disabled"])
        self.side_pick.pack_forget()
        self.selected_label.pack_forget()
        if record:
            self.selected_label.configure(text=record["label"])
            self.selected_label.pack(before=self.entry.master, fill="x", pady=(0, 3))
        if record and record["side"] == "unknown":
            self.side_pick.pack(side="left", padx=5)
            self.side_pick.current(int(side == "suffix"))
        self.mode.configure(text=(self.text("Modifikator ersetzen", "Replace modifier") if record else
                                  {"prefix": self.text("Präfix hinzufügen", "Add prefix"),
                                   "suffix": self.text("Suffix hinzufügen", "Add suffix")}[side]))
        self.assign.configure(text=self.text("Ersetzen", "Replace") if record else self.text("Hinzufügen", "Add"))
        self.message.configure(text="")
        self.choices = []
        self.search.set("")
        self.load_choices()

    def select_current(self, side):
        idx = self.boxes[side].curselection()
        if idx:
            self.start("prefix" if side == "unknown" else side, self.records[side][idx[0]])

    def switch_unknown(self, *_):
        self.side = ("prefix", "suffix")[self.side_pick.current()]
        self.load_choices()

    def load_choices(self):
        key = self.replace["key"] if self.replace else None
        choices = craft_choices(self.gear, self.side, self.lang, replace_key=key)
        self.choices = []
        for row in choices:
            name = row["label"]
            source = row["source"]
            if source != "Base":
                local = _source_labels().get(source, source) if self.lang == "de" else source
                name = f"{name}  ·  {local}"
            self.choices.append({**row, "display": name, "search": search_text(name)})
        self.choices.sort(key=lambda row: (row["source"] != "Base", row["display"].casefold()))
        self.filter()

    def filter(self, *_):
        words = search_text(self.search.get()).split()
        self.visible = [row for row in self.choices if all(word in row["search"] for word in words)]
        self.families.delete(0, "end")
        self.families.insert("end", *(row["display"] for row in self.visible))
        if self.visible:
            current = self.replace.get("family") if self.replace else None
            idx = next((i for i, r in enumerate(self.visible) if r["id"] == current), 0)
            self.families.selection_set(idx)
            self.families.see(idx)
        self.select_family()

    def select_family(self, *_):
        idx = self.families.curselection()
        self.family = self.visible[idx[0]] if idx else None
        tiers = self.family["tiers"] if self.family else []
        captions = [f"T{v['tier']}   ·   {self.text('ab Stufe', 'from level')} {v['level']}" for v in tiers]
        self.tier.configure(values=captions)
        if tiers:
            current = self.replace.get("tier") if self.replace else None
            self.tier.current(next((i for i, r in enumerate(tiers) if r["id"] == current), 0))
        else:
            self.tier.set("")
        self.select_tier()

    def select_tier(self, *_):
        for child in self.roll_box.winfo_children():
            child.destroy()
        self.rolls = []
        ix = self.tier.current()
        if not self.family or ix < 0:
            self.variant = None
            self.assign.state(["disabled"])
            caps = affix_caps(self.gear)
            full = not self.replace and (len(self.records[self.side]) >= caps[self.side == "suffix"]
                                         or sum(map(len, self.records.values())) >= sum(caps))
            self.effect.configure(text=self.text("Zum Tauschen oben einen belegten Platz wählen.",
                                                  "Select an equipped modifier above to replace it.") if full else
                                  self.text("Keine passenden Modifikatoren.", "No matching modifiers."))
            return
        self.variant = self.family["tiers"][ix]
        self.effect.configure(text=self.variant["label"])
        current = self.replace or {}
        same_tier = self.family["id"] == current.get("family") and self.variant["id"] == current.get("tier")
        preset = current.get("rolls", []) if same_tier else []
        for i, (low, high) in enumerate(self.variant["ranges"]):
            value = preset[i] if i < len(preset) else midpoint_roll(low, high)
            var = tk.StringVar(value=f"{value:g}")
            self.rolls.append(var)
            ttk.Label(self.roll_box, text=f"{self.text('Wert', 'Roll')} {low:g}–{high:g}").grid(row=0, column=i, sticky="w")
            decimals = max(len(str(bound).partition(".")[2]) for bound in (low, high))
            step = 10 ** -decimals
            ttk.Spinbox(self.roll_box, textvariable=var, from_=low, to=high, increment=step,
                        width=7).grid(row=1, column=i, padx=(0, 8), sticky="w")
        self.assign.state(["!disabled"])
        if apply := getattr(self.interface, "apply_palette", None):
            apply(self.roll_box)

    def put(self):
        if not self.change_level() or not self.variant:
            return
        try:
            values = [float(v.get().replace(",", ".")) for v in self.rolls]
        except ValueError:
            self.error(ValueError("invalid_roll"))
            return
        try:
            put_affix(self.gear, self.family["id"], self.variant["id"], values,
                      replace_key=self.replace["key"] if self.replace else None)
        except ValueError as exc:
            self.error(exc)
            return
        self.refresh()
        self.start(self.side)

    def delete(self):
        if self.replace:
            try:
                remove_affix(self.gear, self.replace["key"])
            except ValueError as exc:
                self.error(exc)
                return
            self.refresh()
            self.start(self.side)

    def commit(self):
        if not self.change_level():
            return
        try:
            set_item_quality(self.gear, self.quality.get().strip())
        except ValueError as exc:
            self.error(exc)
            return
        self.window.destroy()
        self.interface._apply_craft(self.slot_key, self.gear)


class RuneEditor(_BuildImportDialog):
    def __init__(self, editor):
        self.editor = editor
        self.gear = editor.gear
        super().__init__(editor.interface, editor.text("Runen & Sockel", "Runes & sockets"), 690, 445,
                         parent=editor.window)
        text = self.text
        self.augments = augment_choices(self.gear)
        self.heading(self.body, text("Runen & Sockel", "Runes & sockets")).pack(fill="x", pady=(0, 6))
        fields = ttk.Frame(self.body)
        fields.pack(fill="x", pady=(0, 6))
        fields.columnconfigure(1, weight=1)
        ttk.Label(fields, text=text("Sockel", "Socket")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(fields, text=text("Rune oder Wirkung suchen", "Search by rune or effect")).grid(row=0, column=1, sticky="w")
        self.slot = ttk.Combobox(fields, state="readonly", width=30)
        self.slot.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.slot.bind("<<ComboboxSelected>>", self.filter)
        self.query = tk.StringVar()
        entry = ttk.Entry(fields, textvariable=self.query)
        entry.grid(row=1, column=1, sticky="ew")
        self.query.trace_add("write", self.filter)
        frame, self.choices = _list(self.body, 8)
        frame.pack(fill="both", expand=True)
        self.choices.bind("<<ListboxSelect>>", self.select)
        self.choices.bind("<Double-1>", lambda _: self.change())
        self.choices.bind("<Return>", lambda _: self.change())
        entry.bind("<Down>", lambda _: self.choices.focus_set())
        self.preview = ttk.Label(self.body, justify="left", anchor="w", wraplength=610)
        self.preview.pack(fill="x", pady=6)
        self.preview.bind("<Configure>", lambda event: self.preview.configure(wraplength=max(100, event.width - 4)))
        footer = ttk.Frame(self.body)
        footer.pack(fill="x")
        ttk.Button(footer, text=text("Schließen", "Close"), command=self.window.destroy).pack(side="left")
        self.clear = ttk.Button(footer, text=text("Sockel leeren", "Clear socket"), command=lambda: self.change(False))
        self.clear.pack(side="right")
        self.assign = ttk.Button(footer, text=text("Einsetzen", "Insert"), command=self.change,
                                 style="Primary.BuildImport.TButton")
        self.assign.pack(side="right", padx=6)
        self.rows = []
        for name, effects in self.augments.items():
            label = self.local_name(name)
            lines = [_display_line(effect, self.lang) for effect in effects]
            words = search_text(" ".join((name, label, *lines, *effects)))
            self.rows.append((name, label, "\n".join(lines), words))
        self.rows.sort(key=lambda row: row[1].casefold())
        slots = socket_slots(self.gear)
        first = next((i for i, (name, _) in enumerate(slots) if not name), 0)
        self.refresh(first)
        self.window.bind("<Destroy>", self.restore_parent)
        self.show(entry)

    def local_name(self, name):
        if not name:
            return self.text("Leer", "Empty")
        return self.text("Unbekannte Rune", "Unknown rune") if name == "?" else _display_line(f"Rune: {name}", self.lang).partition(": ")[2]

    def refresh(self, index):
        self.slots = socket_slots(self.gear)
        self.slot.configure(values=[f"{i+1} · {self.local_name(name)}" for i, (name, _) in enumerate(self.slots)])
        self.slot.current(index)
        self.filter()

    def filter(self, *_):
        name, locked = self.slots[self.slot.current()]
        words = search_text(self.query.get()).split()
        self.visible = [row for row in self.rows if not locked and all(word in row[3] for word in words)]
        self.choices.delete(0, "end")
        self.choices.insert("end", *(row[1] for row in self.visible))
        if self.visible:
            index = next((i for i, row in enumerate(self.visible) if row[0] == name), 0)
            self.choices.selection_set(index)
            self.choices.see(index)
        self.select()

    def select(self, *_):
        name, locked = self.slots[self.slot.current()]
        selected = self.choices.curselection()
        self.assign.configure(text=self.text("Tauschen", "Replace") if name else self.text("Einsetzen", "Insert"))
        self.assign.state(["!disabled"] if selected and not locked else ["disabled"])
        self.clear.state(["!disabled"] if name and not locked else ["disabled"])
        if locked:
            description = self.text("Beim Import erfasster Sockeleffekt.", "Socket effect from the original import.")
        elif selected:
            description = self.visible[selected[0]][2]
        else:
            description = self.text("Keine passenden Sockeleinsätze.", "No matching socket augments.")
        self.preview.configure(text=description)

    def change(self, insert=True):
        selected = self.choices.curselection()
        if not (self.assign.instate(["!disabled"]) if insert else self.clear.instate(["!disabled"])):
            return
        index = self.slot.current()
        try:
            set_augment(self.gear, index, self.visible[selected[0]][0] if insert else "")
        except ValueError:
            self.preview.configure(text=self.text("Für diesen Sockel ist die gewählte Änderung nicht möglich.",
                                                  "This socket does not support the selected change."))
            return
        self.editor.show_sockets()
        self.refresh(index)

    def restore_parent(self, event):
        if event.widget == self.window and self.editor.window.winfo_viewable():
            self.editor.window.grab_set()
            self.editor.socket_button.focus_set()
