"""The interface's equipment slots, catalogue picks and optional upgrade targets."""

from functools import lru_cache
import re
import tkinter as tk
from tkinter import font as tkfont, ttk

from poe2_affix_catalog import AffixFilters, CATEGORIES, WEAPONS, _item_in, search
from poe2_build_art import build_icon, item_art_ref
from poe2_build_items import SECTIONS, item_card, item_rarity, rarity_color, render_item_card
from poe2_build_loadout import SLOTS, slot_label
from poe2_lexicon import base_items, catalogue, public_stats
from poe2_overlay_controls import AutoHideScrollbar
from poe2_overlay_lookup import search_text


SILHOUETTES = {
    "main": "weapon", "off": "shield", "helm": "helmet", "body": "body_armour",
    "gloves": "gloves", "amulet": "amulet", "belt": "belt", "boots": "boots",
    "ring1": "ring_left", "ring2": "ring_right",
}
FLASK_ALIASES = {"flask1": "lifeFlask", "flask2": "manaFlask"}
SLOT_EXAMPLES = {"flask1": "Lesser Life Flask", "lifeFlask": "Lesser Life Flask",
                 "flask2": "Lesser Mana Flask", "manaFlask": "Lesser Mana Flask",
                 "charm": "Staunching Charm", "jewel": "Ruby"}
ITEM_TYPES = tuple(CATEGORIES)[:list(CATEGORIES).index("mana-flasks") + 1]
ITEM_TYPE_LABELS = {**{key: CATEGORIES[key][:2] for key in ITEM_TYPES}, "other": ("Weitere", "Other")}

# Columns and rows are measured in half-slot units. Jewellery occupies the
# gaps around the torso; the narrower layout moves it into its own row.
EQUIPMENT = {
    "main": (0, 0, 4, 2), "helm": (0, 3, 2, 2), "off": (0, 6, 4, 2),
    "amulet": (1, 5, 1, 1), "body": (2, 3, 3, 2),
    "ring1": (3, 2, 1, 1), "ring2": (3, 5, 1, 1),
    "gloves": (4, 0, 2, 2), "belt": (5, 3, 1, 2), "boots": (4, 6, 2, 2),
}
COMPACT_EQUIPMENT = {
    "main": (0, 0, 4, 2), "helm": (0, 2, 2, 2), "off": (0, 4, 4, 2),
    "body": (2, 2, 3, 2), "gloves": (4, 0, 2, 2), "belt": (5, 2, 1, 2), "boots": (4, 4, 2, 2),
    "ring1": (6, 0, 1, 2), "amulet": (6, 2, 1, 2), "ring2": (6, 4, 1, 2),
}


def _slot_kind(slot):
    if slot in ("lifeFlask", "manaFlask"):
        return "flask"
    return re.sub(r"-?\d+$", "", slot)


def _slot_keys(gear):
    defaults = [FLASK_ALIASES[k] if k in FLASK_ALIASES and k not in gear and FLASK_ALIASES[k] in gear else k
                for k in SLOTS]
    return list(dict.fromkeys((*defaults, *gear)))


def _name(gear):
    ref = gear.get("overlayRef") or {}
    return next((gear[k] for k in ("sourceName", "unique", "item", "base") if gear.get(k)), "") or (
        (ref.get("name") or ref.get("id") or "") if isinstance(ref, dict) else "")


@lru_cache(maxsize=1)
def _items_by_name():
    return {row["name"]: row for row in catalogue()["items"] if row.get("kind") in (None, "unique")}


def _fits_slot(slot, row):
    kind = _slot_kind(slot)
    item_type, tags = row.get("type"), row["tags"]
    if kind == "main":
        return item_type in WEAPONS
    if kind == "off":
        return item_type in ("shield", "focus", "quiver", "sceptre") or (
            item_type in ("mace", "sword", "axe", "dagger", "claw") and "onehand" in tags)
    if kind in ("flask", "charm"):
        if slot in ("lifeFlask", "manaFlask"):
            return ("life_flask" if slot == "lifeFlask" else "mana_flask") in tags
        return item_type == "flask" and ("utility_flask" in tags) == (kind == "charm")
    if kind == "helm":
        return item_type == "helmet"
    return item_type == kind if kind in ("amulet", "body", "gloves", "ring", "belt", "boots", "jewel") else True


@lru_cache(maxsize=1)
def _classified_items():
    items = _items_by_name()
    rows = []
    for row in items.values():
        category = next((key for key in ITEM_TYPES if _item_in(key, row)), "other")
        base = items.get(row.get("base"), {})
        kind = CATEGORIES["unique"][:2] if row.get("kind") == "unique" else ("Basis", "Base")
        index = search_text(" ".join((row["name"], row.get("de", ""), *ITEM_TYPE_LABELS[category], *kind,
                                     base.get("name", ""), base.get("de", ""), *row.get("aliases", ()))))
        rows.append((category, row, index))
    return rows


@lru_cache(maxsize=64)
def _slot_candidates(slot, language):
    rows = []
    for _category, row, index in _classified_items():
        if _fits_slot(slot, row):
            name = row["name"]
            label = (row.get("de") or name) if language == "de" else name
            rows.append((name, label, index))
    return sorted(rows, key=lambda entry: entry[1].casefold())


def _item_matches(slot, language, query):
    normalized = search_text(query)
    words = normalized.split()
    rows = [(name, label) for name, label, index in _slot_candidates(slot, language)
            if all(word in index for word in words)]
    if normalized:
        def rank(entry):
            names = [search_text(value) for value in entry]
            return (normalized not in names, not any(name.startswith(normalized) for name in names))

        rows.sort(key=rank)
    return rows[:12]


def _mod_scope(slot, gear):
    known = _items_by_name().get(_name(gear), {})
    base = gear.get("base") or known.get("base") or known.get("name") or ""
    row = base_items().get(base, {})
    kind = _slot_kind(slot)
    category = {"main": "weapons", "off": "offhand", "helm": "helmet", "jewel": "jewels",
                "charm": "charms", "flask": "flasks"}.get(kind, kind)
    if slot == "lifeFlask" or "life_flask" in row.get("tags", ()):
        category = "life-flasks"
    elif slot == "manaFlask" or "mana_flask" in row.get("tags", ()):
        category = "mana-flasks"
    elif row and row["type"] not in ("flask", "jewel"):
        category = row["type"]
    if row and row["type"] in ("axe", "sword", "mace"):
        hands = "twohand" if "twohand" in row["tags"] else "onehand"
        category = f"{hands}-{row['type']}"
    return category, base if row else ""


def _modifier_matches(slot, gear, language, query):
    known = _items_by_name().get(_name(gear), {})
    if item_rarity(gear, known) == "unique":
        def fixed_mods(locale):
            headings = {SECTIONS[k][locale == "en"] for k in ("implicit", "explicit", "enchant", "rune")}
            return [line for heading, lines in item_card(gear, locale).sections if heading in headings for line in lines]

        words = search_text(query).split()
        translated = fixed_mods(language)
        alternate = fixed_mods("en" if language == "de" else "de")
        return [(line, line) for i, line in enumerate(translated)
                if all(w in search_text(line + " " + (alternate[i] if i < len(alternate) else "")) for w in words)][:10]

    category, base = _mod_scope(slot, gear)
    filters = AffixFilters(base=base, category=category if category in CATEGORIES else "", query=query)
    seen = {}
    matches = sorted(search(filters, language), key=lambda f: (f["category"] != "equipment", len(f["title"])))
    for family in matches:
        variant = family["variants"][0]
        stats = public_stats(variant["stats"])
        if not stats:
            continue
        line = " · ".join(stats)
        tag = " · ".join(filter(None, (family["section"], f"T{variant['tier']}" if variant.get("tier") else "")))
        if line not in seen:
            seen[line] = f"{line}   ·   {tag}" if tag else line
        if len(seen) == 10:
            break
    return list(seen.items())


class Suggestions:
    """An anchored, keyboard-accessible list that leaves focus in the search field."""

    def __init__(self, entry, theme, matches, choose, no_matches, *, preview=False, hint=""):
        self.entry, self.theme = entry, theme
        self.matches, self.choose, self.no_matches = matches, choose, no_matches
        self.popup = self.box = self.pending = self.focus_job = None
        self.preview, self.detail = preview, None
        self.hint = hint
        self.rows = []
        entry.bind("<KeyRelease>", self._typing)
        entry.bind("<Down>", lambda _: self._step(1))
        entry.bind("<Up>", lambda _: self._step(-1))
        entry.bind("<Return>", self._enter)
        entry.bind("<Escape>", lambda _: self.close())
        entry.bind("<Unmap>", lambda _: self.close())
        entry.bind("<Destroy>", lambda _: self.close())
        entry.bind("<FocusOut>", self._focus_out)

    def _focus_out(self, _event):
        # A click on the list runs on release, after focus has left the entry.
        if self.popup and not self.focus_job:
            self.focus_job = self.entry.after_idle(self._check_focus)

    def _check_focus(self):
        self.focus_job = None
        if self.popup and self.entry.focus_get() not in (self.entry, self.box):
            self.close()

    def _typing(self, event):
        if event.keysym in ("Up", "Down", "Right", "Left", "Return", "Escape", "Tab",
                            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"):
            return
        self.close()
        if self.entry.get().strip():
            self.pending = self.entry.after(140, self.open)

    def close(self):
        if self.focus_job:
            self.entry.after_cancel(self.focus_job)
            self.focus_job = None
        if self.pending:
            self.entry.after_cancel(self.pending)
            self.pending = None
        if self.popup:
            self.popup.destroy()
            self.popup = self.box = self.detail = None
        self.rows = []

    def open(self):
        self.close()
        entry = self.entry
        if not entry.winfo_viewable():
            return
        self.rows = self.matches(entry.get().strip())
        top = self.popup = tk.Toplevel(entry)
        top.withdraw()
        top.overrideredirect(True)
        top.transient(entry.winfo_toplevel())
        top.configure(bg=self.theme.accent)
        box = self.box = tk.Listbox(top, exportselection=False, activestyle="none",
                                    height=min(5, len(self.rows)) or 1, relief="flat", bd=0, highlightthickness=0,
                                    bg=self.theme.control, fg=self.theme.text, selectbackground=self.theme.selection_color,
                                    selectforeground=self.theme.selection_text, takefocus=False)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        if self.rows:
            box.insert("end", *(display for _value, display in self.rows))
            box.selection_set(0)
        else:
            box.insert("end", self.no_matches)
        box.bind("<ButtonRelease-1>", self._click)
        box.bind("<Escape>", lambda _: self.close())
        box.bind("<Return>", self._enter)
        width = min(max(entry.winfo_width(), 330), entry.winfo_screenwidth())
        if self.preview and self.rows:
            self.detail = tk.Label(top, text=self.rows[0][1], anchor="w", justify="left", bd=0, height=3,
                                   bg=self.theme.panel, fg=self.theme.accent, wraplength=width-16, padx=6)
            self.detail.pack(fill="x", padx=1, pady=(0, 1))
            box.bind("<Motion>", lambda event: self.detail.configure(text=self.rows[box.nearest(event.y)][1]))
        elif self.hint and self.rows:
            tk.Label(top, text=self.hint, anchor="w", bg=self.theme.panel, fg=self.theme.text,
                     padx=6, pady=3).pack(fill="x", padx=1, pady=(0, 1))
        top.update_idletasks()
        height = top.winfo_reqheight()
        x, y = entry.winfo_rootx(), entry.winfo_rooty() + entry.winfo_height()
        if 0 <= x < entry.winfo_screenwidth():
            x = min(x, entry.winfo_screenwidth() - width)
        if y + height > entry.winfo_screenheight():
            y = entry.winfo_rooty() - height
        # Tk uses a leading + for an absolute (possibly negative) desktop coordinate.
        top.geometry(f"{width}x{height}+{x}+{y}")
        top.deiconify()
        top.lift()

    def _step(self, step):
        if not self.popup:
            self.open()
        elif self.rows:
            old = self.box.curselection()
            index = min(max((old[0] if old else 0) + step, 0), len(self.rows) - 1)
            self.box.selection_clear(0, "end")
            self.box.selection_set(index)
            self.box.see(index)
            if self.detail:
                self.detail.configure(text=self.rows[index][1])
        return "break"

    def _click(self, event):
        if self.rows:
            self._accept(self.box.nearest(event.y))

    def _enter(self, _event):
        if self.pending:
            self.open()
        if self.popup and self.rows:
            selected = self.box.curselection()
            self._accept(selected[0] if selected else 0)
        else:
            self.close()
        return "break"

    def _accept(self, index):
        value = self.rows[index][0]
        self.close()
        self.entry.focus_set()
        self.choose(value)


class _ScrollColumn:
    def __init__(self, parent, color):
        frame = self.frame = tk.Frame(parent, bg=color)
        canvas = self.canvas = tk.Canvas(frame, bg=color, highlightthickness=0, width=1, height=1)
        scrollbar = AutoHideScrollbar(frame, orient="vertical", command=canvas.yview)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        # Reserve the gutter so hiding the bar doesn't grow the paper doll
        # and immediately make the scrollbar necessary again.
        frame.columnconfigure(1, minsize=scrollbar.winfo_reqwidth())
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        canvas.configure(yscrollcommand=scrollbar.set)
        self.body = tk.Frame(canvas, bg=color)
        slot = canvas.create_window(0, 0, anchor="nw", window=self.body)
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(slot, width=event.width))
        self.body.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))

    def bind_wheel(self, widget):
        if not getattr(widget, "_inventory_wheel_bound", False):
            for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(event, self._scroll)
            widget._inventory_wheel_bound = True
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def _scroll(self, event):
        if self.canvas.yview() == (0.0, 1.0):
            return
        direction = -1 if event.num == 4 or (event.num != 5 and event.delta > 0) else 1
        self.canvas.yview_scroll(direction * 2, "units")
        return "break"


class BuildImportInventoryMixin:
    def make_items(self, page):
        self.gear_slot = "main1"
        self.weapon_set = "1"
        self.editing_gear = False
        self.upgrade_open = False
        theme = self.theme
        # Keep the equipment board and its reading column together on wide screens.
        # Tk points follow display scaling, unlike a fixed pixel maximum.
        board = tk.Frame(page, bg=theme.panel)
        board.place(relx=.5, y=0, relheight=1, anchor="n")
        limit = page.winfo_pixels("825p")
        def resize_board(event):
            if event.widget is page:
                board.place_configure(width=min(limit, event.width))

        page.bind("<Configure>", resize_board, add="+")
        board.columnconfigure(0, weight=9, uniform="gear")
        board.columnconfigure(1, weight=11, uniform="gear")
        board.rowconfigure(0, weight=1)
        self.equipment = _ScrollColumn(board, theme.panel)
        self.equipment.frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.inspector = _ScrollColumn(board, theme.panel)
        self.inspector.frame.grid(row=0, column=1, sticky="nsew")
        left = self.equipment.body
        toolbar = tk.Frame(left, bg=theme.panel)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text=self.text("Waffenset", "Weapon set")).pack(side="left", padx=(0, 5))
        self.set_buttons = {}
        for key, label in (("1", "I"), ("2", "II")):
            button = tk.Button(toolbar, text=label, width=3, relief="flat", bd=0, cursor="hand2",
                               command=lambda k=key: self._switch_set(k))
            button.pack(side="left", padx=(0, 3))
            self.set_buttons[key] = button
        self.gear_grid = tk.Frame(left, bg=theme.panel)
        self.gear_grid.pack(fill="x")
        self.gear_caption = tk.Label(left, bg=theme.panel, fg=theme.accent, anchor="w", width=1)
        self.gear_caption.pack(fill="x", pady=(2, 4))
        self.belt_heading = ttk.Label(left, text=self.text("Fläschchen & Phiolen", "Flasks & charms"))
        self.belt_heading.pack(anchor="w", pady=(3, 2))
        self.belt_grid = tk.Frame(left, bg=theme.panel)
        self.belt_grid.pack(fill="x")
        self.extra_heading = ttk.Label(left, text=self.text("Juwelen & weitere Plätze", "Jewels & other slots"))
        self.extra_grid = tk.Frame(left, bg=theme.panel)
        self.tile_font = tkfont.Font(root=page, family=self.app.ui_family, size=9)
        self.compact_width = page.winfo_pixels("270p")
        self.tile_width = 0
        self.slot_buttons = {}
        self.gear_grid.bind("<Configure>", self._arrange_slots)
        self.jewel_button = ttk.Button(left, text=self.text("+ Juwelenslot", "+ Jewel socket"), command=self.add_jewel)
        self.jewel_button.pack(anchor="w", pady=6)

        right = self.inspector.body
        self.slot_title = tk.Label(right, anchor="w", bg=theme.panel, fg=theme.accent, font=(self.app.ui_family, 13, "bold"))
        self.slot_title.pack(fill="x")
        ttk.Label(right, text=self.text("Gegenstand suchen", "Search items")).pack(anchor="w", pady=(5, 0))
        searchbar = ttk.Frame(right)
        searchbar.pack(fill="x", pady=(4, 8))
        self.item_picker = ttk.Entry(searchbar, width=10)
        self.item_picker.pack(side="left", fill="x", expand=True)
        ttk.Button(searchbar, text=self.text("Katalog …", "Catalogue …"),
                   command=self._open_catalogue).pack(side="left", padx=(4, 0))
        self.remove_item_button = ttk.Button(searchbar, text=self.text("Ablegen", "Unequip"),
                                              command=lambda: self._choose_item(""))
        self.remove_item_button.pack(side="left", padx=(4, 0))
        self.item_suggestions = Suggestions(self.item_picker, theme,
            lambda query: _item_matches(self.gear_slot, self.language, query), self._choose_item,
            self.text("Kein Treffer. Mit Enter eigenen Namen verwenden.", "No match. Press Enter to use your own name."),
            hint=self.text("Mit Klick oder ↑ ↓ und Enter ausrüsten.", "Click or use ↑ ↓ and Enter to equip."))
        self.item_picker.bind("<Return>", self._typed_item)

        self.craft_button = ttk.Button(right, command=self._open_craft)
        self.craft_button.pack(anchor="w", pady=(0, 6))
        self.upgrade_toggle = tk.Button(right, anchor="w", relief="flat", bd=0, padx=8, pady=5,
                                        bg=theme.control, fg=theme.text, activebackground=theme.active,
                                        activeforeground=theme.text, command=self._toggle_upgrade)
        self.upgrade_toggle.pack(fill="x", pady=(0, 5))
        self.upgrade_fields = ttk.Frame(right, padding=(4, 0, 4, 6))
        self.goal_text = tk.StringVar(right)
        self.mod_text = tk.StringVar(right)
        self.item_goal = self.field(self.upgrade_fields, self.text("Wofür brauche ich das Upgrade?", "Why upgrade this slot?"),
                                    ttk.Entry(self.upgrade_fields, textvariable=self.goal_text))
        self.item_mod = self.field(self.upgrade_fields, self.text("Gewünschter Wert (z. B. Leben)", "Wanted stat (e.g. life)"),
                                   ttk.Entry(self.upgrade_fields, textvariable=self.mod_text))
        self.mod_suggestions = Suggestions(self.item_mod, theme,
            lambda q: _modifier_matches(self.gear_slot, self.setup["gear"].get(self.gear_slot, {}), self.language, q),
            self.mod_text.set, self.text("Kein Katalogtreffer. Eigener Wunschwert bleibt erhalten.",
                                         "No catalogue match. Your custom target is kept."), preview=True)
        self.goal_text.trace_add("write", self._edit_target)
        self.mod_text.trace_add("write", self._edit_target)
        self.item_preview = tk.Frame(right, bg=theme.panel)
        self.item_preview.pack(fill="x", pady=(3, 0))

    def _open_catalogue(self, *, bases=False):
        from poe2_build_import_interface_crafting import BaseCatalogue
        self.item_suggestions.close()
        return BaseCatalogue(self, bases=bases)

    def _open_craft(self):
        from poe2_build_import_interface_crafting import CraftEditor
        item = self.setup["gear"].get(self.gear_slot, {})
        if not _name(item):
            return self._open_catalogue(bases=True)
        return CraftEditor(self, self.gear_slot, item)

    def _apply_craft(self, slot, gear):
        self.focus_slot(slot)
        self._write_slot(gear)
        self._draw_tiles()
        self.show_slot()

    def _browse_items(self):
        self.item_picker.focus_set()
        self.item_suggestions.open()

    def _typed_item(self, event):
        if self.item_suggestions.pending or self.item_suggestions.popup:
            if self.item_suggestions.pending:
                self.item_suggestions.open()
            if not self.item_suggestions.rows and (name := self.item_picker.get().strip()):
                self.item_suggestions.close()
                self._choose_item(name)
                return "break"
            return self.item_suggestions._enter(event)
        if name := self.item_picker.get().strip():
            rows = _item_matches(self.gear_slot, self.language, name)
            self._choose_item(rows[0][0] if rows else name)
        return "break"

    def _toggle_upgrade(self):
        self.upgrade_open = not self.upgrade_open
        self.mod_suggestions.close()
        self._upgrade_caption()
        if self.upgrade_open:
            self.item_goal.focus_set()

    def _upgrade_caption(self):
        target = self.mod_text.get() or self.goal_text.get()
        title = self.text("Upgrade planen", "Plan an upgrade")
        if not self.upgrade_open and target:
            title += "  ·  " + target
        self.upgrade_toggle.configure(text=("▾  " if self.upgrade_open else "▸  ") + title)
        if self.upgrade_open:
            self.upgrade_fields.pack(before=self.item_preview, fill="x")
        else:
            self.upgrade_fields.pack_forget()

    def _choose_item(self, name):
        previous = self.setup["gear"].get(self.gear_slot, {})
        if _name(previous) != name:
            next_item = {k: previous[k] for k in ("goal", "mod") if previous.get(k)}
            if name:
                known = _items_by_name().get(name)
                if known and known.get("kind") == "unique":
                    next_item.update(unique=name, base=known.get("base", ""))
                else:
                    next_item["base" if known else "item"] = name
            self._write_slot(next_item)
        self._draw_tiles()
        self.show_slot()

    def _write_slot(self, gear):
        all_gear = self.setup["gear"]
        if gear or _slot_kind(self.gear_slot) == "jewel":
            all_gear[self.gear_slot] = gear
        else:
            all_gear.pop(self.gear_slot, None)

    def _edit_target(self, *_):
        if self.editing_gear:
            return
        item = dict(self.setup["gear"].get(self.gear_slot, {}))
        for key, value in (("goal", self.goal_text.get()), ("mod", self.mod_text.get())):
            if value.strip():
                item[key] = value.strip()
            else:
                item.pop(key, None)
        self._write_slot(item)

    def save_slot(self):
        # Target fields are bound directly to the current draft. Pending item searches
        # do not replace an equipped item until the user chooses a result.
        return True

    def _switch_set(self, key):
        self.weapon_set = key
        if _slot_kind(self.gear_slot) in ("off", "main"):
            self.gear_slot = _slot_kind(self.gear_slot) + key
        self._draw_tiles()
        self.show_slot()

    def _arrange_slots(self, event=None):
        width = event.width if event else self.gear_grid.winfo_width()
        if width < 12 or not self.slot_buttons or event and self.tile_width == width:
            return
        self.tile_width = width
        compact = width < self.compact_width
        columns = 6 if compact else 8
        layout = COMPACT_EQUIPMENT if compact else EQUIPMENT
        cell = width // columns
        grid = self.gear_grid
        for col in range(8):
            grid.columnconfigure(col, weight=int(col < columns), minsize=cell if col < columns else 0)
        for row in range(7):
            grid.rowconfigure(row, minsize=cell if row < 6 or compact else 0)
        for slot, (row, col, height, span) in layout.items():
            key = slot + self.weapon_set if slot in ("main", "off") else slot
            self._place_tile(key, row, col, height, span, cell * span, cell * height)

        for grid, keys, cols in ((self.belt_grid, self.belt_slots, max(5, len(self.belt_slots))),
                                 (self.extra_grid, self.extra_slots, 4)):
            if not keys:
                continue
            for col in range(max(cols, grid.grid_size()[0])):
                grid.columnconfigure(col, weight=int(col < cols), minsize=width // cols if col < cols else 0)
            tile_height = max(cell, self.gear_grid.winfo_pixels("45p"))
            for i, key in enumerate(keys):
                row, col = divmod(i, cols)
                self._place_tile(key, row, col, 1, 1, width // cols, tile_height)

    def _place_tile(self, key, row, col, height, span, width, pixels):
        button = self.slot_buttons[key]
        frame = button.master
        frame.configure(width=max(1, width-4), height=max(1, pixels-4))
        frame.grid(row=row, column=col, rowspan=height, columnspan=span, sticky="nsew", padx=2, pady=2)
        label, name = self.tile_labels[key]
        image = button.image
        image_height = image.height() if image else 0
        lines = (pixels - image_height - 7) // self.tile_font.metrics("linespace")
        # On small jewellery slots the icon is sufficient; hover and selection
        # always expose the complete slot and item name.
        if lines <= 0 and image:
            caption = ""
        else:
            label = self._short_caption(label, width - 8)
            caption = label
            if name and lines > 1:
                caption += "\n" + self._short_caption(name, width - 8)
        if button.cget("text") != caption:
            button.configure(text=caption)

    def _short_caption(self, text, width):
        if self.tile_font.measure(text) <= width:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.tile_font.measure(text[:mid] + "…") <= width:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + "…"

    def _caption(self, key):
        self.gear_caption.configure(text=" · ".join(filter(None, self.tile_labels.get(key, ()))))

    def _draw_tiles(self):
        grid, theme = self.gear_grid, self.theme
        for section in (grid, self.belt_grid, self.extra_grid):
            for child in section.winfo_children():
                child.destroy()
        for key, button in self.set_buttons.items():
            button.configure(bg=theme.selection_color if key == self.weapon_set else theme.control,
                             fg=theme.selection_text if key == self.weapon_set else theme.text,
                             activebackground=theme.active, activeforeground=theme.text)
        core = [key + self.weapon_set if key in ("main", "off") else key for key in EQUIPMENT]
        extra = [key for key in self.slots if key not in core and _slot_kind(key) not in ("main", "off")]
        # Life and mana flank the charms, as on the equipment screen.
        order = ("flask1", "lifeFlask", "charm1", "charm2", "charm3", "flask2", "manaFlask")
        self.belt_slots = [key for key in order if key in extra]
        self.extra_slots = [key for key in extra if key not in self.belt_slots]
        if self.extra_slots:
            self.extra_heading.pack(before=self.jewel_button, anchor="w", pady=(6, 2))
            self.extra_grid.pack(before=self.jewel_button, fill="x")
        else:
            self.extra_heading.pack_forget()
            self.extra_grid.pack_forget()
        parents = dict.fromkeys(core, grid)
        parents.update(dict.fromkeys(self.belt_slots, self.belt_grid))
        parents.update(dict.fromkeys(self.extra_slots, self.extra_grid))
        self.slot_buttons = {}
        self.tile_labels = {}
        for key, parent in parents.items():
            gear = self.setup["gear"].get(key, {})
            name = _name(gear)
            fallback = SILHOUETTES.get(key) or SILHOUETTES.get(_slot_kind(key))
            ref = item_art_ref(name, gear.get("base") or "") if name else ""
            small = _slot_kind(key) in ("ring", "amulet", "belt", "charm", "jewel", "flask")
            art = build_icon(grid, ref, 28 if small else 48) if ref else None
            if not art and fallback:
                art = build_icon(grid, f"assets/ui/icon_{fallback}.png", 28)
            elif not art:
                example = SLOT_EXAMPLES.get(key) or SLOT_EXAMPLES.get(_slot_kind(key))
                if example:
                    art = build_icon(grid, item_art_ref(example), 28)
            active = key == self.gear_slot
            color = theme.accent if active else theme.edge
            rarity = item_rarity(gear, _items_by_name().get(_name(gear), {}))
            ink = rarity_color(rarity) if name and rarity != "normal" else theme.text
            border = tk.Frame(parent, bg=color)
            border.pack_propagate(False)
            label = slot_label(key, self.language)
            if name:
                record = _items_by_name().get(name, {})
                if self.language == "de":
                    name = record.get("de") or name
            self.tile_labels[key] = label, name
            button = tk.Button(border, text="", bg=theme.active if active else theme.control, fg=ink,
                               activebackground=theme.selection_color, activeforeground=theme.selection_text,
                               relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                               padx=1, pady=1, justify="center", font=self.tile_font,
                               command=lambda k=key: self.focus_slot(k))
            if art:
                button.configure(image=art, compound="top")
            button.image = art
            for event in ("<Enter>", "<FocusIn>"):
                button.bind(event, lambda _, k=key: self._caption(k))
            for event in ("<Leave>", "<FocusOut>"):
                button.bind(event, lambda _: self._caption(self.gear_slot))
            button.pack(fill="both", expand=True, padx=1, pady=1)
            self.slot_buttons[key] = button
        self._arrange_slots()
        self._caption(self.gear_slot)
        self.equipment.bind_wheel(self.equipment.frame)
        self.jewel_button.state(["disabled"] if len(self.setup["gear"]) >= 64 else ["!disabled"])

    def focus_slot(self, slot):
        if slot not in self.slots:
            counterpart = FLASK_ALIASES.get(slot) or next((k for k, v in FLASK_ALIASES.items() if v == slot), "")
            if counterpart not in self.slots:
                return False
            slot = counterpart
        old_slot = self.gear_slot
        self.gear_slot = slot
        if re.fullmatch(r"(main|off)[12]", slot):
            self.weapon_set = slot[-1]
        if slot in self.slot_buttons:
            if old_slot in self.slot_buttons:
                old = self.slot_buttons[old_slot]
                old.master.configure(bg=self.theme.edge)
                old.configure(bg=self.theme.control)
            new = self.slot_buttons[slot]
            new.master.configure(bg=self.theme.accent)
            new.configure(bg=self.theme.active)
        else:
            self._draw_tiles()
        self.show_slot()
        self._caption(slot)
        return True

    def refresh_gear(self, index=None):
        self.slots = _slot_keys(self.setup["gear"])
        if index is not None:
            self.gear_slot = self.slots[min(index, len(self.slots)-1)]
        elif self.gear_slot not in self.slots:
            self.gear_slot = "main1"
        if re.fullmatch(r"(main|off)[12]", self.gear_slot):
            self.weapon_set = self.gear_slot[-1]
        self._draw_tiles()
        self.show_slot()

    def show_slot(self):
        self.item_suggestions.close()
        self.mod_suggestions.close()
        self.item_picker.delete(0, "end")
        item = self.setup["gear"].get(self.gear_slot, {})
        self.slot_title.configure(text=slot_label(self.gear_slot, self.language))
        self.editing_gear = True
        try:
            self.goal_text.set(item.get("goal") or "")
            self.mod_text.set(item.get("mod") or "")
        finally:
            self.editing_gear = False
        self._upgrade_caption()
        self.remove_item_button.state(["!disabled"] if _name(item) else ["disabled"])
        from poe2_item_craft import craftable
        equipped = bool(_name(item))
        can_edit = not equipped or craftable(item)
        if not equipped:
            label = self.text("Gegenstand bauen …", "Craft an item …")
        elif can_edit:
            label = self.text("Modifikatoren bearbeiten …", "Edit modifiers …")
        elif item_rarity(item) == "unique":
            label = self.text("Einzigartiger Gegenstand · feste Modifikatoren", "Unique item · fixed modifiers")
        else:
            label = self.text("Für diese Basis fehlen Affixdaten", "No affix data for this base")
        self.craft_button.configure(text=label)
        self.craft_button.state(["!disabled"] if can_edit else ["disabled"])
        for child in self.item_preview.winfo_children():
            child.destroy()
        if _name(item) or item.get("sourceText") or item.get("mods"):
            card = item_card(item, self.language)
            render_item_card(self.item_preview, card, self.theme,
                             font=lambda size, weight: (self.app.ui_family, size, weight),
                             gear=item, language=self.language, app=self.app).pack(fill="x")
        else:
            tk.Label(self.item_preview, text=self.text("Platz frei. Suche eine Basis oder einen einzigartigen Gegenstand.",
                                                        "Empty slot. Search for a base or a unique item."),
                     bg=self.theme.panel, fg=self.theme.text, justify="left", anchor="w", wraplength=265,
                     padx=4, pady=12).pack(fill="x")
        self.inspector.canvas.yview_moveto(0)
        self.inspector.bind_wheel(self.inspector.frame)

    def add_jewel(self):
        if len(self.setup["gear"]) >= 64:
            return
        used = {int(m[1]) for key in self.slots if (m := re.fullmatch(r"jewel-?(\d+)", key))}
        suffix = next(i for i in range(1, 66) if i not in used)
        key = f"jewel-{suffix}"
        self.setup["gear"][key] = {}
        self.slots = _slot_keys(self.setup["gear"])
        self.focus_slot(key)
        self.equipment.canvas.update_idletasks()
        self.equipment.canvas.yview_moveto(1)
