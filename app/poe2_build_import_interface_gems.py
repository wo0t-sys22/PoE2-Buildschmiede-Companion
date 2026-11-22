"""Skill groups and a searchable, offline gem picker for the desktop interface."""

import tkinter as tk
from tkinter import messagebox, ttk

from poe2_build_art import gem_icon
from poe2_build_loadout import resolve_asset
from poe2_lexicon import public_name
from poe2_overlay_controls import AutoHideScrollbar
from poe2_overlay_lookup import search_text
from poe2_website_content import localized_text


SKILL_GROUPS = {
    "Mace": ("Streitkolben", "Maces"),
    "Bow": ("Bögen", "Bows"),
    "Crossbow": ("Armbrüste", "Crossbows"),
    "Quarterstaff": ("Kampfstäbe", "Quarterstaves"),
    "Spear": ("Speere", "Spears"),
    "Talisman": ("Talismane", "Talismans"),
    "Shield": ("Schilde", "Shields"),
    "Unarmed": ("Unbewaffnet", "Unarmed"),
    "Elemental": ("Elementar", "Elemental"),
    "Occult": ("Okkult", "Occult"),
    "Primal": ("Urkraft", "Primal"),
    "Granted": ("Gewährte Fertigkeiten", "Granted skills"),
    "Other": ("Weitere Fertigkeiten", "Other skills"),
}
WEAPON_SKILL_GROUPS = {
    "One Hand Mace": "Mace", "Two Hand Mace": "Mace",
    "Armoured Shield": "Shield", "Any Shield": "Shield",
}


def skill_groups(record):
    groups = set(record.get("groups") or ())
    groups.update(WEAPON_SKILL_GROUPS.get(weapon, weapon)
                  for weapon in (record.get("weapon") or "").split(", "))
    return tuple(group for group in SKILL_GROUPS if group in groups) or ("Other",)


def socket_id(socket):
    return socket.get("id", "") if isinstance(socket, dict) else socket or ""


def is_skill_socket(socket):
    return isinstance(socket, dict) and socket.get("kind") == "skill"


def gem_name(record, language, fallback=""):
    return (record.get("de") if language == "de" else "") or record.get("name") or fallback


def socket_choices(data, gem_id):
    ids = data["skillSupports"].get(gem_id)
    return data["supports"] if ids is None else {i: data["supports"][i] for i in ids if i in data["supports"]}


def catalog_id(gem, group, data):
    """Older guide exports may supply only a display name or a game metadata ID."""
    ident = socket_id(gem)
    if ident in data[group]:
        return ident
    ref = gem.get("overlayRef") if isinstance(gem, dict) else None
    kind = "skill" if group == "skills" else "support"
    candidate = resolve_asset(kind, ref or {"id": ident}, "en")
    if not ref and (not candidate or not candidate.record):
        candidate = resolve_asset(kind, {"name": ident}, "en")
    return candidate.id if candidate and candidate.record else ident


class GemPreview:
    def __init__(self, parent, interface, line_limit=5):
        self.interface = interface
        self.line_limit = line_limit
        self.fit_job = None
        theme = interface.theme
        self.frame = tk.Frame(parent, bg=theme.control, padx=9, pady=7)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(3, weight=1)
        self.image = tk.Label(self.frame, bg=theme.control)
        self.image.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self.title = tk.Label(self.frame, bg=theme.control, fg=interface.gem_color, anchor="w",
                              justify="left", font=(interface.app.ui_family, 12, "bold"))
        self.title.grid(row=0, column=1, sticky="ew")
        self.tags = tk.Label(self.frame, bg=theme.control, fg=theme.accent, anchor="w", justify="left")
        self.tags.grid(row=1, column=1, sticky="ew")
        self.frame.bind("<Configure>", self._resize_header)
        self.body = tk.Text(self.frame, wrap="word", height=3, width=10, bg=theme.control, fg=theme.text,
                            font=(interface.app.ui_family, 10), bd=0, highlightthickness=0, padx=0, pady=2)
        self.body.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(5, 0))
        scroll = AutoHideScrollbar(self.frame, command=self.body.yview)
        scroll.grid(row=3, column=2, sticky="ns")
        self.body.configure(yscrollcommand=scroll.set)
        self.body.bind("<Configure>", self._schedule_height)
        self.body.bind("<Destroy>", self._cancel_height)
        self.body.build_import_colors = True

    def _resize_header(self, event):
        width = max(80, event.width - 90)
        self.title.configure(wraplength=width)
        self.tags.configure(wraplength=width)

    def _schedule_height(self, _event=None):
        if self.fit_job is None:
            self.fit_job = self.body.after_idle(self._fit_height)

    def _cancel_height(self, _event):
        if self.fit_job is not None:
            self.body.after_cancel(self.fit_job)
            self.fit_job = None

    def _fit_height(self):
        self.fit_job = None
        if self.body.winfo_width() > 10:
            count = self.body.count("1.0", "end-1c", "displaylines")
            lines = min(self.line_limit, 1 + (count[0] if count else 0))
            if int(self.body["height"]) != lines:
                self.body.configure(height=lines)

    def show(self, record, title, note="", *, empty=False):
        language = self.interface.language
        icon = gem_icon(self.image, record.get("icon"), size=52, empty=empty)
        self.image.configure(image=icon)
        self.image.image = icon
        self.title.configure(text=title)
        tags = (record.get("tagsDe") if language == "de" else "") or record.get("tags", "")
        self.tags.configure(text=tags)
        text = localized_text(record.get("description"), language)
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", "\n\n".join(dict.fromkeys(s for s in (note, text) if s)))
        self.body.configure(state="disabled")
        self.body.yview_moveto(0)
        self._schedule_height()


class GemPicker:
    def __init__(self, interface, records, title, on_choose, initial="", action=None, *, grouped=False):
        self.records = records
        self.on_choose = on_choose
        self.language = interface.language
        self.t = interface.text
        self.grouped = grouped
        self.groups = {i: skill_groups(row) for i, row in records.items()} if grouped else {}
        locale = "de" if self.language == "de" else "en"
        self.labels = {i: row.get("variantLabel", {}).get(locale) or gem_name(row, self.language, i)
                       for i, row in records.items()}
        self.rows = sorted(records, key=lambda i: self.labels[i].casefold())
        self.index = {i: self.search_index(i) for i in self.rows}
        self.window = win = tk.Toplevel(interface.window)
        win.title(title)
        win.transient(interface.window)
        win.configure(bg=interface.theme.panel)
        px, py = interface.window.winfo_rootx(), interface.window.winfo_rooty()
        pw, ph = interface.window.winfo_width(), interface.window.winfo_height()
        native = getattr(interface.app, "native", None)
        area = native.work_area(rect=(px, py, px + pw, py + ph)) if native else None
        left, top, right, bottom = area or (0, 0, win.winfo_screenwidth(), win.winfo_screenheight())
        width = min(780, max(510, pw - 70), max(1, right - left - 16))
        height = min(490, max(350, ph - 90), max(1, bottom - top - 48))
        x = max(left, min(right - width - 8, px + (pw - width) // 2))
        y = max(top, min(bottom - height - 40, py + (ph - height) // 2))
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.minsize(min(470, width), min(310, height))
        page = ttk.Frame(win, padding=12, style="BuildImport.TFrame")
        page.pack(fill="both", expand=True)
        page.rowconfigure(2, weight=1)
        page.columnconfigure(0, weight=1, uniform="gem-catalog")
        page.columnconfigure(1, weight=1, uniform="gem-catalog")
        ttk.Label(page, text=title, style="Heading.BuildImport.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.query = tk.StringVar(win)
        searchrow = ttk.Frame(page)
        searchrow.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(searchrow, text=interface.text("Suchen", "Search")).pack(side="left", padx=(0, 6))
        search = ttk.Entry(searchrow, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        left = ttk.Frame(page)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 9))
        theme = interface.theme
        style = ttk.Style(win)
        style.configure("Picker.BuildImport.Treeview", background=theme.field_color, fieldbackground=theme.field_color,
                        foreground=theme.text, rowheight=win.winfo_pixels("16p"), indent=16, relief="flat",
                        bordercolor=theme.edge)
        style.map("Picker.BuildImport.Treeview", background=[("selected", theme.active)],
                  foreground=[("selected", theme.selection_color)])
        self.list = ttk.Treeview(left, show="tree", selectmode="browse", style="Picker.BuildImport.Treeview")
        self.list.column("#0", width=120, minwidth=30)
        self.list.tag_configure("category", foreground=theme.accent, font=(interface.app.ui_family, 10, "bold"))
        scroll = AutoHideScrollbar(left, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=scroll.set)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.list.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.preview = GemPreview(page, interface, line_limit=9)
        self.preview.frame.grid(row=2, column=1, sticky="new")
        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.count = ttk.Label(actions, style="Muted.BuildImport.TLabel")
        self.count.pack(side="left")
        self.apply = ttk.Button(actions, text=action or interface.text("Auswählen", "Select"),
                                style="Primary.BuildImport.TButton", command=self.choose)
        if self.on_choose:
            self.apply.pack(side="right")
        ttk.Button(actions, text=interface.text("Schließen", "Close"), command=win.destroy).pack(side="right", padx=6)
        self.list.bind("<<TreeviewSelect>>", self.inspect)
        self.list.bind("<Double-1>", self.choose)
        self.list.bind("<Return>", self.choose)
        search.bind("<Return>", self.choose)
        search.bind("<Down>", lambda e: self.list.focus_set())
        win.bind("<Escape>", lambda e: win.destroy())
        self.query.trace_add("write", lambda *_: self.filter())
        self.filter(initial)
        interface.apply_palette(page)
        win.grab_set()
        search.focus_set()

    def search_index(self, ident):
        record = self.records[ident]
        fields = (record.get(key) or "" for key in ("name", "de", "tags", "tagsDe", "family", "familyDe", "weapon"))
        labels = (label for group in self.groups.get(ident, ()) for label in SKILL_GROUPS[group])
        return search_text(" ".join((*fields, *labels, self.labels[ident], ident)))

    def filter(self, initial=""):
        words = search_text(self.query.get()).split()
        self.matches = [key for key in self.rows if all(word in self.index[key] for word in words)]
        self.list.delete(*self.list.get_children())
        self.ident_by_row = {}
        self.label_by_group = {}
        if self.grouped:
            categories = [(group, [key for key in self.matches if group in self.groups[key]]) for group in SKILL_GROUPS]
        else:
            categories = [("", self.matches)]
        for group, ids in categories:
            if not ids:
                continue
            parent = ""
            if group:
                label = self.t(*SKILL_GROUPS[group])
                parent = self.list.insert("", "end", text=f"{label} · {len(ids)}", tags=("category",), open=bool(words))
                self.label_by_group[parent] = label
            for ident in ids:
                item = self.list.insert(parent, "end", text=self.labels[ident])
                self.ident_by_row[item] = ident
        selected = next((item for item, ident in self.ident_by_row.items() if ident == initial), None)
        if selected is None:
            rows = self.ident_by_row if words or not self.grouped else self.label_by_group
            selected = next(iter(rows), None)
        if selected:
            self.list.selection_set(selected)
            self.list.focus(selected)
            self.list.see(selected)
        self.count.configure(text=f"{len(self.matches)} " + self.t("Treffer", "matches"))
        self.inspect()

    def inspect(self, _event=None):
        selected = next(iter(self.list.selection()), "")
        ident = self.ident_by_row.get(selected)
        if ident is not None:
            self.preview.show(self.records[ident], self.labels[ident])
        elif selected in self.label_by_group:
            self.preview.show({}, self.label_by_group[selected],
                              self.t("Gruppe öffnen oder nach einer Fertigkeit suchen.",
                                     "Open the group or search for a skill."), empty=True)
        else:
            self.preview.show({}, self.t("Keine Treffer", "No matches"), empty=True)
        self.apply.configure(state="normal" if ident is not None and self.on_choose else "disabled")

    def choose(self, _event=None):
        selected = next(iter(self.list.selection()), "")
        if self.on_choose and selected in self.ident_by_row:
            ident = self.ident_by_row[selected]
            self.window.destroy()
            self.on_choose(ident)
        elif selected in self.label_by_group:
            self.list.item(selected, open=not self.list.item(selected, "open"))
            self.list.focus_set()
        return "break"


class BuildImportGemsMixin:
    def make_gems(self, page):
        self.gem_color = "#86d6ca"
        self.gem_images = {}
        page.columnconfigure(0, weight=4, uniform="gems")
        page.columnconfigure(1, weight=6, uniform="gems")
        page.rowconfigure(0, weight=1)
        left = ttk.Frame(page)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.group_title = ttk.Label(left, style="Heading.BuildImport.TLabel")
        self.group_title.pack(anchor="w")
        ttk.Button(left, text=self.text("+ Fertigkeit wählen", "+ Choose skill"),
                   command=self.choose_skill).pack(fill="x", pady=(6, 7))
        self.gems = self.gem_list(left, self.select_gem)
        self.gems.bind("<ButtonRelease-1>", self.inspect_skill)
        self.gems.bind("<Return>", self.inspect_skill)
        self.gem_remove = ttk.Button(left, text=self.text("Fertigkeit entfernen", "Remove skill"), command=self.remove_gem)
        self.gem_remove.pack(side="bottom", before=self.gems.master, anchor="w", pady=(3, 0))
        right = ttk.Frame(page)
        right.grid(row=0, column=1, sticky="nsew")
        self.gem_card = GemPreview(right, self)
        self.gem_card.frame.pack(fill="x", pady=(0, 8))
        self.gem_values = tk.Frame(self.gem_card.frame, bg=self.theme.control)
        self.gem_vars = []
        self.value_gem = None
        for i, (label, lo, hi) in enumerate(((self.text("Stufe", "Level"), 1, 40), (self.text("Qualität %", "Quality %"), 0, 100))):
            tk.Label(self.gem_values, text=label, fg=self.theme.text, bg=self.theme.control).grid(
                row=0, column=2*i, sticky="w", padx=(0, 4))
            var = tk.StringVar(self.window)
            entry = ttk.Spinbox(self.gem_values, width=4, from_=lo, to=hi, textvariable=var)
            entry.grid(row=0, column=2*i+1, sticky="w", padx=(0, 10))
            entry.bind("<FocusOut>", self.finish_gem_values)
            var.trace_add("write", lambda *_: self.update_gem_values())
            self.gem_vars.append(var)
        self.socket_panel = ttk.Frame(right)
        self.socket_title = ttk.Label(self.socket_panel, style="Heading.BuildImport.TLabel")
        self.socket_title.pack(anchor="w", pady=(0, 5))
        actions = ttk.Frame(self.socket_panel)
        actions.pack(fill="x", pady=(0, 5))
        self.socket_edit = ttk.Button(actions, text=self.text("Support wählen", "Choose support"), command=self.choose_socket)
        self.socket_edit.pack(side="left")
        self.socket_clear = ttk.Button(actions, text=self.text("Sockel leeren", "Clear socket"), command=self.clear_socket)
        self.socket_clear.pack(side="left", padx=(6, 0))
        self.socket_list = self.gem_list(self.socket_panel, self.show_socket, height=5, stretch=False)
        self.socket_list.bind("<Double-1>", self.choose_socket)
        self.socket_list.bind("<Return>", self.choose_socket)
        self.edited_gem = None

    def gem_list(self, parent, callback, height=4, stretch=True):
        frame = ttk.Frame(parent)
        frame.pack(fill="both" if stretch else "x", expand=stretch)
        rows = ttk.Treeview(frame, show="tree", selectmode="browse", height=height, style="Gems.BuildImport.Treeview")
        rows.column("#0", width=80, minwidth=20)
        scroll = AutoHideScrollbar(frame, orient="vertical", command=rows.yview)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        rows.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        rows.configure(yscrollcommand=scroll.set)
        rows.bind("<<TreeviewSelect>>", callback)
        return rows

    def reference(self, gem, group):
        ident = catalog_id(gem, group, self.data)
        record = self.data[group].get(ident) or self.data["skills"].get(ident) or {}
        ref = (gem.get("overlayRef") or {}) if isinstance(gem, dict) else {}
        fallback = ref.get("name") or public_name(ident) or self.text("Importierte Gemme", "Imported gem")
        return record, gem_name(record, self.language, fallback), ref.get("note", "")

    def insert_gem(self, rows, index, title, record, *, empty=False):
        image = gem_icon(self.window, record.get("icon"), size=30, empty=empty)
        self.gem_images[rows, index] = image
        rows.insert("", "end", iid=str(index), text=title, image=image)

    @staticmethod
    def selected_index(rows):
        return int(rows.selection()[0]) if rows.selection() else None

    def refresh_gems(self, index=0):
        groups = self.setup["gems"]
        self.edited_gem = None
        self.gem_images.clear()
        self.gems.delete(*self.gems.get_children())
        self.group_title.configure(text=f"{self.text('Fertigkeiten', 'Skills')} · {len(groups)}")
        for i, group in enumerate(groups):
            row, title, _ = self.reference(group, "skills")
            self.insert_gem(self.gems, i, title, row)
        if groups:
            index = str(min(max(0, index), len(groups) - 1))
            self.gems.selection_set(index)
            self.gems.see(index)
        self.select_gem()

    def select_gem(self, _event=None):
        index = self.selected_index(self.gems)
        gem = self.setup["gems"][index] if index is not None else None
        if gem is not None and self.edited_gem is gem:
            if _event is None:
                self.show_socket()
            return
        self.edited_gem = None
        self.socket_list.delete(*self.socket_list.get_children())
        for key in [k for k in self.gem_images if k[0] is self.socket_list]:
            del self.gem_images[key]
        self.edited_gem = gem
        self.gem_remove.configure(state="normal" if gem else "disabled")
        sockets = gem.get("sockets", []) if gem else []
        title = (self.text("Gemmensockel", "Gem sockets") if any(map(is_skill_socket, sockets))
                 else self.text("Support-Sockel", "Support sockets"))
        count = sum(bool(socket_id(s)) for s in sockets)
        self.socket_title.configure(text=f"{title} · {count}/5" if gem else title)
        if gem:
            self.socket_panel.pack(fill="both", expand=True)
            for i in range(5):
                socket = sockets[i] if i < len(sockets) else None
                active = is_skill_socket(socket)
                row, title, _ = self.reference(socket, "skills" if active else "supports") if socket else (
                    {}, self.text("Freier Sockel", "Empty socket"), "")
                if active:
                    title = self.text("Fertigkeit", "Skill") + " · " + title
                self.insert_gem(self.socket_list, i, f"{i+1}   {title}", row, empty=not socket_id(socket))
        else:
            self.socket_panel.pack_forget()
        self.show_socket()

    def show_gem_values(self, gem):
        if self.value_gem is gem:
            return
        self.value_gem = None
        if gem:
            self.gem_vars[0].set(gem.get("level", 1))
            self.gem_vars[1].set(gem.get("quality", 0))
            self.gem_values.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        else:
            self.gem_values.grid_remove()
        self.value_gem = gem

    def update_gem_values(self):
        gem = self.value_gem
        if not gem:
            return True
        try:
            level, quality = (int(var.get()) for var in self.gem_vars)
        except ValueError:
            return False
        if not (1 <= level <= 40 and 0 <= quality <= 100):
            return False
        for key, value, default in (("level", level, 1), ("quality", quality, 0)):
            if value != gem.get(key, default):
                gem[key] = value
        return True

    def finish_gem_values(self, _event):
        if self.value_gem and not self.update_gem_values():
            self.gem_vars[0].set(self.value_gem.get("level", 1))
            self.gem_vars[1].set(self.value_gem.get("quality", 0))
            self.give_status("Level 1–40 und Qualität 0–100. Der letzte gültige Wert gilt.",
                             "Level 1–40 and quality 0–100. The last valid value was kept.")

    def save_gem(self):
        if not self.update_gem_values():
            self.error(self.text("Level 1–40 und Qualität 0–100 eingeben.", "Enter level 1–40 and quality 0–100."))
            return False
        return True

    def show_socket(self, _event=None):
        gem = self.edited_gem
        index = self.selected_index(self.socket_list)
        sockets = gem.get("sockets", []) if gem else []
        socket = sockets[index] if index is not None and index < len(sockets) else None
        self.socket_clear.configure(state="normal" if socket else "disabled")
        has_space = len(sockets) < 5 or any(not socket_id(s) for s in sockets)
        edit_label = self.text("Support tauschen", "Replace support") if socket else self.text("Support wählen", "Choose support")
        if is_skill_socket(socket):
            edit_label = self.text("Durch Support ersetzen", "Replace with support")
        if gem and index is None and not has_space:
            edit_label = self.text("Sockel zum Tauschen wählen", "Select a socket to replace")
        self.socket_edit.configure(state="normal" if gem else "disabled", text=edit_label)
        if socket:
            self.show_gem_values(socket if is_skill_socket(socket) else None)
            self.gem_card.show(*self.reference(socket, "skills" if is_skill_socket(socket) else "supports"))
        elif gem:
            self.show_gem_values(gem)
            self.gem_card.show(*self.reference(gem, "skills"))
        else:
            self.show_gem_values(None)
            self.gem_card.show({}, self.text("Erste Fertigkeit wählen", "Choose your first skill"),
                               self.text("Wähle links eine Fertigkeit. Danach siehst du, welche Supports zu ihr passen.",
                                         "Choose a skill on the left to see which supports can be socketed."), empty=True)

    def inspect_skill(self, _event=None):
        self.socket_list.selection_remove(*self.socket_list.selection())
        self.show_socket()

    def choose_skill(self, initial=""):
        GemPicker(self, self.data["skills"], self.text("Fertigkeit wählen", "Choose skill"), self.add_gem, initial,
                  self.text("Zum Setup hinzufügen", "Add to setup"), grouped=True)

    def add_gem(self, ident):
        gems = self.setup["gems"]
        if len(gems) >= 64:
            self.error(self.text("Das Setup enthält bereits 64 Fertigkeiten.", "The setup already contains 64 skills."))
            return
        gems.append({"id": ident, "sockets": [], "level": 1, "quality": 0, "enabled": True, "weaponSet": "both"})
        self.refresh_gems(len(gems) - 1)

    def remove_gem(self):
        index = self.selected_index(self.gems)
        if index is None:
            return
        _, title, _ = self.reference(self.edited_gem, "skills")
        if messagebox.askyesno(self.text("Fertigkeit entfernen", "Remove skill"),
                               self.text(f"{title} mit ihren Supports entfernen?", f"Remove {title} and its supports?"),
                               parent=self.window):
            self.setup["gems"].pop(index)
            self.refresh_gems(index)

    def choose_socket(self, _event=None, initial=""):
        gem = self.edited_gem
        if not gem:
            return
        sockets = gem.get("sockets", [])
        index = self.selected_index(self.socket_list)
        if index is None:
            index = next((i for i in range(5) if i >= len(sockets) or not socket_id(sockets[i])), None)
            if index is None:
                self.give_status("Wähle den Sockel, dessen Support du tauschen möchtest.",
                                 "Select the socket whose support you want to replace.")
                if initial:
                    GemPicker(self, {initial: self.data["supports"][initial]}, self.text("Empfohlener Support", "Recommended support"),
                              None, initial)
                else:
                    self.socket_list.focus_set()
                    self.socket_list.focus("0")
                    self.socket_list.selection_set("0")
                    self.socket_list.see("0")
                    self.show_socket()
                return
        selected = socket_id(sockets[index]) if index < len(sockets) else ""
        _, title, _ = self.reference(gem, "skills")
        GemPicker(self, socket_choices(self.data, catalog_id(gem, "skills", self.data)), f"Support · {title}",
                  lambda ident: self.set_socket(index, ident), initial or selected,
                  self.text(f"In Sockel {index+1} einsetzen", f"Insert into socket {index+1}"))

    def set_socket(self, index, ident):
        gem = self.edited_gem
        sockets = gem.setdefault("sockets", [])
        while len(sockets) <= index:
            sockets.append(None)
        if socket_id(sockets[index]) != ident:
            sockets[index] = {"id": ident, "kind": "support", "level": 1, "quality": 0} if ident else None
        while sockets and not socket_id(sockets[-1]):
            sockets.pop()
        self.edited_gem = None
        self.select_gem()
        self.socket_list.selection_set(str(index))
        self.show_socket()

    def clear_socket(self):
        index = self.selected_index(self.socket_list)
        if self.edited_gem and index is not None:
            self.set_socket(index, "")

    def focus_guide_gem(self, kind, ident):
        for i, gem in enumerate(self.setup["gems"]):
            indexes = [j for j, sock in enumerate(gem.get("sockets", ())) if socket_id(sock) == ident]
            if (kind == "group" and i == ident) or (kind == "gem" and (gem["id"] == ident or indexes)):
                self.refresh_gems(i)
                if indexes:
                    self.socket_list.selection_set(str(indexes[0]))
                    self.show_socket()
                return True
        if ident in self.data["skills"]:
            self.choose_skill(ident)
            return True
        if ident in self.data["supports"]:
            gem = self.edited_gem
            if gem and ident in socket_choices(self.data, catalog_id(gem, "skills", self.data)):
                self.choose_socket(initial=ident)
            else:
                row = self.data["supports"][ident]
                GemPicker(self, {ident: row}, self.text("Empfohlener Support", "Recommended support"), None, ident)
            return True
        return False
