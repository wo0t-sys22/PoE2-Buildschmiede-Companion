"""Native Build Import Interface for importing, editing and displaying builds."""

from copy import deepcopy
import re
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser

from poe2_build_editorial import WEBSITE_TOPICS, phase_label
from poe2_build_import_interface import blank_setup, export_plan, import_plans, new_plan
from poe2_build_import_interface_tree import BuildImportTree
from poe2_lexicon import catalogue
from poe2_build_import_interface_inventory import BuildImportInventoryMixin
from poe2_build_import_interface_gems import BuildImportGemsMixin
from poe2_build_import_interface_guide import BuildImportGuideMixin
from poe2_hud_icons import hud_icon
from poe2_website_content import BUILD_PLANNER_URL


CLASS_DE = {"Ranger": "Waldläuferin", "Witch": "Hexe", "Sorceress": "Zauberin", "Mercenary": "Söldner",
            "Warrior": "Krieger", "Monk": "Mönch", "Huntress": "Jägerin", "Druid": "Druide"}


def _import_interface_bounds(work_area):
    """Centre the client on the HUD monitor, leaving room for window decorations."""
    left, top, right, bottom = work_area
    width, height = right - left, bottom - top
    max_height, max_width = max(1, height - 48), max(1, width - 20)
    previous_height = min(max_height, max(500, min(760, height - 90)))
    previous_width = min(max_width, max(675, min(1120, width - 50)))
    large_height = min(max_height, max(500, round(height * .88)))
    large_width = min(max_width, max(675, round(min(width * .86, large_height * 1.95))))
    client_height = round((previous_height + large_height) / 2)
    client_width = round((previous_width + large_width) / 2)
    return client_width, client_height, left + (width - client_width) // 2, top + (height - client_height - 34) // 2


class BuildImportInterfaceWindow(BuildImportInventoryMixin, BuildImportGemsMixin, BuildImportGuideMixin):
    def __init__(self, app):
        self.app = app
        self.language = app.language
        self.theme = app.theme
        self.store = app.build_import_store
        self.data = catalogue()
        self.classes = self.data["plannerTree"]["classes"]
        self.key, self.phase = None, -1
        self.hud_source_key = None
        self.build = new_plan()
        self.checkpoint = deepcopy(self.build)
        self.window = tk.Toplevel(app.root)
        self.window.title(self.text("Build Import Interface · PoE2 Companion", "Build Import Interface · PoE2 Companion"))
        work = None
        if getattr(app, "native", None):
            layout = app.current.layout
            work = app.native.work_area(rect=(layout.x, layout.y, layout.x + layout.width, layout.y + layout.height))
        bounds = work or (0, 0, self.window.winfo_screenwidth(), self.window.winfo_screenheight())
        w, h, x, y = _import_interface_bounds(bounds)
        self.window.minsize(min(675, w), min(500, h))
        self.window.geometry(f"{w}x{h}+{x}+{y}")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.configure(bg=self.theme.panel)
        self.styles()
        self.images = []
        content = ttk.Frame(self.window, padding=(12, 10), style="BuildImport.TFrame")
        content.pack(fill="both", expand=True)
        header = ttk.Frame(content, style="BuildImport.TFrame")
        header.pack(fill="x", pady=(0, 10))
        tk.Label(header, image=app.brand_mark(34), bg=self.theme.panel).pack(side="left", padx=(0, 7))
        tk.Label(header, text=self.text("Build Import Interface", "Build Import Interface"), bg=self.theme.panel,
                 fg=self.theme.accent, font=(app.brand_family, 17, "bold")).pack(side="left")
        self.saved = ttk.Combobox(header, state="readonly", width=18)
        self.saved.pack(side="left", padx=10)
        self.saved.bind("<<ComboboxSelected>>", self.open_saved)
        self.saved_label = self.text("Plan öffnen …", "Open plan …")
        ttk.Button(header, text=self.text("Speichern", "Save"), style="Primary.BuildImport.TButton",
                   image=self.icon("save", self.theme.selection_text), compound="left", command=self.save).pack(side="right")
        exchange = ttk.Menubutton(header, text="Import / Export", style="BuildImport.TMenubutton")
        exchange.pack(side="right", padx=6)
        menu = tk.Menu(exchange, tearoff=False, bg=self.theme.control, fg=self.theme.text,
                       activebackground=self.theme.active, activeforeground=self.theme.text)
        menu.add_command(label=self.text("Build-Datei importieren …", "Import build file …"), command=self.import_build)
        menu.add_command(label=self.text("PoB2-Code einfügen …", "Paste PoB2 code …"), command=self.import_pob_code)
        menu.add_separator()
        menu.add_command(label=self.text("Plan als JSON exportieren …", "Export plan as JSON …"), command=self.export_build)
        exchange.configure(menu=menu)
        ttk.Button(header, text=self.text("+ Neu", "+ New"), command=self.new).pack(side="right")

        website = ttk.Frame(content, style="BuildImport.TFrame")
        website.pack(fill="x", pady=(0, 10))
        ttk.Button(website, text=self.text("Web-Planer öffnen ↗", "Open web planner ↗"),
                   style="Primary.BuildImport.TButton", command=self.open_website).pack(side="left", padx=(0, 10))
        note = ttk.Label(website, style="Muted.BuildImport.TLabel", justify="left", text=self.text(
            "Experimentelle Schnittstelle zum Importieren von Builddaten. Dieses Tool darf nicht als Buildplaner verwendet werden.",
            "Experimental interface for importing build data. Do not use this tool as a build planner."))
        note.pack(side="left", fill="x", expand=True)
        note.bind("<Configure>", lambda event: note.configure(wraplength=max(1, event.width)))

        bar = ttk.Frame(content)
        bar.pack(fill="x", pady=(0, 10))
        self.name = tk.StringVar(self.window)
        self.name_entry = ttk.Entry(bar, textvariable=self.name, width=12)
        self.phase_picker = ttk.Combobox(bar, state="readonly", width=14)
        self.phase_picker.bind("<<ComboboxSelected>>", self.pick_phase)
        self.class_labels = {key: CLASS_DE.get(key, key) if self.language == "de" else key for key in self.classes}
        self.asc_labels = self.data.get("ascendancyLabelsDe", {}) if self.language == "de" else {}
        self.class_picker = ttk.Combobox(bar, state="readonly", width=9)
        self.class_picker.bind("<<ComboboxSelected>>", self.pick_class)
        self.asc_picker = ttk.Combobox(bar, state="readonly", width=13)
        self.asc_picker.bind("<<ComboboxSelected>>", self.pick_asc)
        fields = ((self.text("Build-Name", "Build name"), self.name_entry, 4),
                  (self.text("Guide-Phase", "Guide phase"), self.phase_picker, 4),
                  (self.text("Klasse", "Class"), self.class_picker, 1),
                  (self.text("Aszendenz", "Ascendancy"), self.asc_picker, 2))
        for col, (label, field, weight) in enumerate(fields):
            bar.columnconfigure(col, weight=weight)
            pad = (0, 6 if col < 3 else 0)
            ttk.Label(bar, text=label, style="Muted.BuildImport.TLabel").grid(row=0, column=col, sticky="w", padx=pad)
            field.grid(row=1, column=col, sticky="ew", padx=pad)

        footer = ttk.Frame(content)
        footer.pack(side="bottom", fill="x", pady=(6, 0))
        self.status = ttk.Label(footer, style="Muted.BuildImport.TLabel", anchor="w", wraplength=400)
        self.status.pack(side="left", fill="x", expand=True)
        self.use_button = ttk.Button(footer, text=self.text("Im HUD verwenden →", "Use in HUD →"), command=self.use_in_hud)
        self.use_button.pack(side="right", padx=(8, 0))
        self.guide_link = tk.Button(content, anchor="w", justify="left", cursor="hand2", relief="flat", bd=0,
                                    padx=7, pady=3, bg=self.theme.control, fg=self.theme.accent,
                                    activebackground=self.theme.active, activeforeground=self.theme.text,
                                    command=lambda: self.show_guide_topic(self.tabs.index("current")))

        self.tabs = ttk.Notebook(content, style="BuildImport.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        pages = [ttk.Frame(self.tabs, padding=12) for _ in range(4)]
        nav = (("Inventar", "Inventory", "inventory", "#e8c68f"),
               ("Fertigkeiten & Supports", "Skills & Supports", "gem", "#86d6ca"),
               ("Passivbaum", "Passive Tree", "build", "#c3ace5"),
               ("Guide-Phasen", "Guide Phases", "quest", "#99bedc"))
        for page, (de, en, glyph, color) in zip(pages, nav):
            self.tabs.add(page, text=self.text(de, en), compound="left", image=self.icon(glyph, color, 18))
        self.make_items(pages[0])
        self.make_gems(pages[1])
        self.tree = BuildImportTree(self, pages[2])
        self.make_phases(pages[3])
        self.apply_palette(content)
        self.show_saved()
        self.refresh()
        self.tabs.select(pages[2])
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.window.bind("<Control-s>", self.save_shortcut)
        self.window.lift()
        if getattr(app, "native", None):
            app.native.style_dialog(self.window, palette=(self.theme.edge, self.theme.panel, self.theme.text))

    def save_shortcut(self, _event):
        self.save()
        return "break"

    def open_website(self):
        try:
            if webbrowser.open(BUILD_PLANNER_URL):
                return
        except webbrowser.Error:
            pass
        self.give_status("Der Browser konnte nicht geöffnet werden.", "Could not open the browser.")

    def icon(self, name, color, size=15):
        image = hud_icon(self.window, name, size, color)
        self.images.append(image)
        return image

    def tab_changed(self, _event=None):
        tab = self.tabs.index("current")
        if tab == 3:
            self.refresh_phases()
        self.refresh_guide_link()

    def refresh_guide_link(self):
        tab = self.tabs.index("current")
        excerpt = self.guide_excerpt(tab) if tab < 3 else ""
        if excerpt:
            width = max(55, int((self.window.winfo_width() - 120) / 9))
            line = " ".join(excerpt.split())
            if len(line) > width:
                line = line[:width - 1].rsplit(" ", 1)[0] + "…"
            self.guide_link.configure(text=self.text("Phasenhinweis", "Phase note") + "   ·   " + line + "   →")
            self.guide_link.pack(side="bottom", fill="x", before=self.tabs, pady=(5, 0))
        else:
            self.guide_link.pack_forget()

    def open_guide_target(self, kind, ident):
        tab = {"item": 0, "group": 1, "gem": 1, "node": 2}.get(kind)
        if tab is None:
            return False
        self.tabs.select(tab)
        if kind == "item":
            found = self.focus_slot(ident)
        elif kind == "node":
            found = self.tree.open_node(str(ident))
        else:
            found = self.focus_guide_gem(kind, ident)
        if not found:
            self.give_status("Der Verweis ist in diesem Setup oder Katalog nicht aufgelöst.",
                             "This reference could not be found in this setup or catalogue.")
        return found

    def open_hud_section(self, phase_id, section, target=None, tree_scope=None):
        """Navigate the current draft without reloading it or recording a passive allocation."""
        phases = self.build["phases"]
        if phases:
            index = next((i for i, row in enumerate(phases) if row["id"] == phase_id), None)
            if index is None:
                self.give_status("Diese HUD-Phase ist in deinem Entwurf nicht mehr vorhanden.",
                                 "This HUD phase is no longer present in your draft.")
                return
            if index != self.phase:
                self.phase = index
                self.refresh()
        if section is None:
            return
        choices = {"craft": 0, "skills": 1, "passives": 2}
        self.tabs.select(choices[section])
        if section == "craft" and target:
            self.open_guide_target("item", target)
        elif section == "passives":
            scope = {"main": "main", "weaponSet1": "I", "weaponSet2": "II", "ascendancy": "asc"}.get(tree_scope)
            if scope and self.tree.scope != scope:
                self.tree.change_scope(scope)
            if target:
                self.open_guide_target("node", target)

    def styles(self):
        style = ttk.Style(self.window)
        theme = self.theme
        style.configure("BuildImport.TFrame", background=theme.panel)
        style.configure("BuildImport.TLabel", background=theme.panel, foreground=theme.text)
        edges = dict(bordercolor=theme.edge, lightcolor=theme.edge, darkcolor=theme.edge)
        style.configure("BuildImport.TNotebook", background=theme.panel, **edges)
        style.configure("Heading.BuildImport.TLabel", foreground=theme.text, font=(self.app.ui_family, 12, "bold"))
        style.configure("Muted.BuildImport.TLabel", foreground="#b9b7b2")
        style.configure("BuildImport.TNotebook.Tab", background=theme.control, foreground=theme.text,
                        padding=(9, 6), **edges)
        style.map("BuildImport.TNotebook.Tab", background=[("selected", theme.active), ("active", theme.field_color)],
                  foreground=[("selected", theme.text)], padding=[("selected", (9, 6))],
                  expand=[("selected", (0, 0, 0, 0))])
        style.configure("BuildImport.TButton", background=theme.control, foreground=theme.text,
                        anchor="center", padding=(8, 4), **edges)
        style.map("BuildImport.TButton", background=[("active", theme.active)],
                  bordercolor=[("active", theme.accent)], foreground=[("disabled", theme.edge), ("active", theme.text)])
        style.configure("Primary.BuildImport.TButton", background=theme.selection_color, foreground=theme.selection_text,
                        bordercolor=theme.accent, font=(self.app.ui_family, 10, "bold"))
        style.map("Primary.BuildImport.TButton", background=[("active", theme.accent), ("!disabled", theme.selection_color)],
                  foreground=[("disabled", theme.edge), ("!disabled", theme.selection_text)])
        style.configure("Gems.BuildImport.Treeview", background=theme.control, fieldbackground=theme.control,
                        foreground=theme.text, rowheight=36, indent=3, relief="flat", **edges)
        style.map("Gems.BuildImport.Treeview", background=[("selected", theme.active)],
                  foreground=[("selected", theme.selection_color)])
        for orient in ("Vertical", "Horizontal"):
            style.configure(f"BuildImport.{orient}.TScrollbar", troughcolor=theme.panel, background=theme.field_color,
                            arrowcolor=theme.text, gripcount=0, **edges)
        style.configure("BuildImport.TMenubutton", background=theme.control, foreground=theme.text,
                        arrowcolor=theme.accent, padding=(6, 4), **edges)
        for widget in ("TEntry", "TCombobox", "TSpinbox"):
            name = f"BuildImport.{widget}"
            style.configure(name, fieldbackground=theme.field_color, background=theme.control,
                            foreground=theme.text, arrowcolor=theme.accent, **edges,
                            insertcolor=theme.text, selectbackground=theme.selection_color,
                            selectforeground=theme.selection_text)
            style.map(name, fieldbackground=[("readonly", theme.field_color)],
                      foreground=[("disabled", theme.edge), ("readonly", theme.text)])

    def apply_palette(self, widget):
        if isinstance(widget, ttk.Scrollbar) and not widget.cget("style"):
            widget.configure(style=f"BuildImport.{str(widget.cget('orient')).title()}.TScrollbar")
        elif isinstance(widget, (ttk.Frame, ttk.Label, ttk.Button, ttk.Menubutton, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
            if not widget.cget("style"):
                widget.configure(style=f"BuildImport.{widget.winfo_class()}")
        elif isinstance(widget, (tk.Listbox, tk.Text)) and not getattr(widget, "build_import_colors", False):
            widget.configure(background=self.theme.field_color, foreground=self.theme.text,
                             selectbackground=self.theme.selection_color, selectforeground=self.theme.selection_text)
            if isinstance(widget, tk.Text):
                widget.configure(insertbackground=self.theme.text)
        for child in widget.winfo_children():
            self.apply_palette(child)

    def text(self, german, english):
        return english if self.language == "en" else german

    @property
    def setup(self):
        return self.build["phases"][self.phase]["setup"] if self.phase >= 0 else self.build

    def give_status(self, german, english):
        self.status.configure(text=self.text(german, english))

    def error(self, error):
        messagebox.showerror(self.text("Build Import Interface", "Build Import Interface"), str(error), parent=self.window)

    def show_saved(self):
        bundled = getattr(self.app, "bundled_plans", {})
        self.saved_ids = [*self.store.plans, *bundled]
        self.saved.configure(values=[self.saved_label, *(row["name"] for row in self.store.plans.values()),
                                     *("Guide · " + row["name"] for row in bundled.values())])
        key = self.key or self.hud_source_key
        self.saved.current(1 + self.saved_ids.index(key) if key in self.saved_ids else 0)

    def discard(self):
        self.build["name"] = self.name.get().strip()
        return self.build == self.checkpoint or messagebox.askyesno(
            self.text("Ungespeicherter Plan", "Unsaved plan"),
            self.text("Ungespeicherte Änderungen verwerfen?", "Discard unsaved changes?"), parent=self.window)

    def close(self):
        if self.discard():
            self.window.destroy()

    def relocalize(self):
        """Rebuild translated widgets, keeping the unsaved document and its navigation."""
        other = type(self)(self.app)
        other.key, other.hud_source_key = self.key, self.hud_source_key
        other.build, other.checkpoint, other.phase = self.build, self.checkpoint, self.phase
        other.name.set(self.name.get())
        other.weapon_set, other.gear_slot = self.weapon_set, self.gear_slot
        other.guide_topic = self.guide_topic
        other.show_saved()
        other.refresh()
        other.refresh_gems(self.selected_index(self.gems) or 0)
        socket = self.selected_index(self.socket_list)
        if socket is not None and other.socket_list.exists(str(socket)):
            other.socket_list.selection_set(str(socket))
            other.show_socket()
        other.tree.set_scope(self.tree.scope, home=False)
        other.tree.selected, other.tree.history = self.tree.selected, self.tree.history
        other.tree.center, other.tree.zoom = self.tree.center, self.tree.zoom
        other.tree.fit_on_draw = self.tree.fit_on_draw
        other.tree.show_details()
        other.tabs.select(self.tabs.index("current"))
        other.window.geometry(self.window.geometry())
        if self.window.state() == "zoomed":
            other.window.state("zoomed")
        self.window.destroy()
        return other

    def load(self, build, key=None, *, hud_source_key=None):
        self.key, self.build = key, deepcopy(build)
        self.hud_source_key = hud_source_key
        self.build.setdefault("phases", [])
        self.phase = next((i for i, phase in enumerate(self.build["phases"]) if phase["id"] == build.get("phaseId")),
                          0 if self.build["phases"] else -1)
        self.guide_topic = ("overview" if self.build.get("editorial") or any(self.build.get(field)
                            for field in WEBSITE_TOPICS.values()) else "general")
        self.name.set(build["name"])
        self.show_saved()
        self.refresh()
        self.checkpoint = deepcopy(self.build)

    def new(self):
        if self.discard():
            self.load(new_plan())
            self.tabs.select(2)
            self.give_status("Leerer Plan geöffnet.", "Blank plan opened.")

    def open_saved(self, _event=None):
        index = self.saved.current() - 1
        if index >= 0 and self.discard():
            key = self.saved_ids[index]
            if key in self.store.plans:
                self.load(self.store.plans[key], key)
            else:
                self.load(self.app.bundled_plans[key], hud_source_key=key)
                self.give_status("Guide als Entwurf geöffnet. Speichern legt eine eigene Kopie an.",
                                 "Guide opened as a draft. Save to create your own copy.")
        else:
            self.show_saved()

    def import_build(self):
        file = filedialog.askopenfilename(parent=self.window, title=self.text("Build importieren", "Import build"),
                                          filetypes=[(self.text("Build-Dateien", "Build files"), "*.json *.build *.zip *.xml *.txt *.pob *.pob2"),
                                                     ("Buildschmiede JSON", "*.json"), ("PoE2 / Mobalytics", "*.build *.zip"),
                                                     ("Path of Building 2", "*.xml *.txt *.pob *.pob2"),
                                                     (self.text("Alle Dateien", "All files"), "*")])
        if file:
            self.accept_import(lambda: import_plans(file))

    def import_pob_code(self):
        from poe2_build_interchange import pob_code, pob_plan

        code = simpledialog.askstring("Path of Building 2", self.text(
            "Exportcode des aktiven Setups einfügen", "Paste the export code for the active setup"), parent=self.window)
        if code:
            self.accept_import(lambda: [pob_plan(pob_code(code))])

    def accept_import(self, reader):
        written = []
        try:
            plans = reader()
            if not self.discard():
                return
            for build in plans:
                key = next((ident for ident, plan in self.store.plans.items() if plan == build), None)
                key = key or self.store.save(build)
                self.app.update_imported_build(key)
                written.append(key)
        except (OSError, ValueError) as error:
            self.error(error)
        if written:
            self.load(self.store.plans[written[0]], written[0])
            self.give_status(f"{len(written)} Build(s) importiert. In Suche → Builds verfügbar.",
                             f"{len(written)} build(s) imported. Available in Search → Builds.")
            if len(plans) == 1 and plans[0].get("importFormat") == "pob2-active":
                self.give_status("Aktives PoB2-Setup importiert · Ausrüstung, Gemmen und Passivbaum.",
                                 "Active PoB2 setup imported · gear, gems and passive tree.")
            missing = {node for plan in plans for setup in (plan, *(p["setup"] for p in plan.get("phases", [])))
                       if isinstance(setup.get("unresolvedGamePassives"), list)
                       for node in setup["unresolvedGamePassives"] if isinstance(node, str)}
            if missing:
                preview = ", ".join(sorted(missing)[:3]) + (" …" if len(missing) > 3 else "")
                self.give_status(f"Importiert. {len(missing)} Passiv-IDs ohne Knoten im Offline-Baum ({preview}). Alle IDs sind im Plan gespeichert.",
                                 f"Imported. {len(missing)} passive IDs have no node in the offline tree ({preview}). All IDs are saved in the plan.")

    def export_build(self):
        if not self.prepare_save():
            return
        basename = re.sub(r'[^\w -]', '_', self.build["name"]).strip(" .") or "Build"
        file = filedialog.asksaveasfilename(parent=self.window, title=self.text("Plan exportieren", "Export plan"),
                                            defaultextension=".json", initialfile=basename + ".json",
                                            filetypes=[("Buildschmiede JSON", "*.json")])
        if file:
            try:
                export_plan(self.build, file, website_language=self.language)
            except (OSError, ValueError) as error:
                self.error(error)
            else:
                self.give_status("Bearbeitbare JSON-Datei exportiert.", "Editable JSON file exported.")

    def prepare_save(self):
        self.build["name"] = self.name.get().strip()
        if not self.build["name"]:
            self.give_status("Gib deinem Plan oben einen Namen, um ihn zu speichern.",
                             "Give your plan a name above to save it.")
            self.name_entry.focus_set()
            return False
        tab = self.tabs.index("current")
        if tab == 0:
            self.save_slot()
        elif tab == 1 and self.save_gem() is False:
            return False
        elif tab == 3:
            self.save_phase_notes()
        return True

    def save(self):
        if not self.prepare_save():
            return False
        try:
            self.key = self.store.save(self.build, self.key)
        except (OSError, ValueError) as error:
            self.error(error)
            return False
        self.app.update_imported_build(self.key)
        self.checkpoint = deepcopy(self.build)
        self.show_saved()
        self.give_status("Plan lokal gespeichert.", "Plan saved locally.")
        return True

    def use_in_hud(self):
        if self.save():
            self.app.show_build_guide(self.key)
            self.give_status("Build im HUD aktiv. Die Phase folgt deiner Charakterstufe.",
                             "Build active in the HUD. The phase follows your character level.")

    def refresh(self):
        for key, value in blank_setup().items():
            self.setup.setdefault(key, value)
        phases = self.build["phases"]
        self.phase_picker.configure(values=[self.text("Aktuelles Setup", "Current setup"),
                                            *(phase_label(row, self.language) for row in phases)])
        self.phase_picker.current(self.phase + 1)
        class_name = self.setup.get("className", "")
        self.class_picker.configure(values=[self.text("Klasse wählen", "Choose class"), *self.class_labels.values()])
        self.class_picker.set(self.class_labels.get(class_name, class_name) or self.class_picker["values"][0])
        asc = self.setup.get("ascendancy", "")
        self.asc_ids = self.classes.get(class_name, {}).get("ascendancies", [])
        self.asc_picker.configure(values=[self.text("Aszendenz wählen", "Choose ascendancy"),
                                          *(self.asc_labels.get(key, key) for key in self.asc_ids)])
        self.asc_picker.set(self.asc_labels.get(asc, asc) or self.asc_picker["values"][0])
        self.refresh_gear()
        self.refresh_gems()
        self.tree.refresh()
        self.refresh_phases()
        self.refresh_guide_link()

    def pick_class(self, _event=None):
        index = self.class_picker.current()
        self.setup["className"] = list(self.class_labels)[index - 1] if index > 0 else ""
        self.setup["ascendancy"] = ""
        self.refresh()

    def pick_asc(self, _event=None):
        index = self.asc_picker.current()
        self.setup["ascendancy"] = self.asc_ids[index - 1] if index > 0 else ""
        self.tree.refresh()

    def pick_phase(self, _event=None):
        self.phase = self.phase_picker.current() - 1
        self.remember_phase()
        self.refresh()

    def remember_phase(self):
        self.build["phaseId"] = self.build["phases"][self.phase]["id"] if self.phase >= 0 else ""

    @staticmethod
    def listbox(parent, height=12):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        box = tk.Listbox(frame, height=height, exportselection=False, relief="flat", borderwidth=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        return box

    @staticmethod
    def replace_rows(box, rows, index=0):
        box.delete(0, "end")
        if rows:
            box.insert("end", *rows)
            choose = min(index, len(rows) - 1)
            box.selection_set(choose)
            box.see(choose)

    @staticmethod
    def field(parent, label, widget):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(7, 2))
        widget.pack(fill="x")
        return widget

