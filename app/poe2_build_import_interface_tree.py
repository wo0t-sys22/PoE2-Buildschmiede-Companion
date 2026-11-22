"""Standalone interface view of the offline Buildschmiede passive tree."""

from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import math
import tkinter as tk
from tkinter import ttk

from poe2_build_art import build_icon
from poe2_build_tree_routes import ATTRIBUTES_DE, SCOPES, TreeRoutes, node_effective_record
from poe2_build_tree_ui import _geometry
from poe2_lexicon import catalogue, display_stats
from poe2_overlay_lookup import search_text


SURFACE = "#151918"
GOLD = "#e7bd75"
PREVIEW = "#87d6bf"
COLORS = {"main": GOLD, "I": "#79c8f4", "II": "#ec997e", "asc": "#c5a1eb"}
RADII = {"small": 31, "attribute": 31, "jewel": 45, "notable": 56, "keystone": 81, "root": 85}
FRAME_KIND = {"small": "Normal", "attribute": "Normal", "jewel": "Socket", "notable": "Notable", "keystone": "Keystone"}
KIND = {"small": ("Kleine Passive", "Small passive"), "attribute": ("Attribut", "Attribute"),
        "jewel": ("Juwelensockel", "Jewel socket"), "notable": ("Bedeutende Passive", "Notable"),
        "keystone": ("Schlüsselfertigkeit", "Keystone"), "root": ("Startpunkt", "Starting point")}
SIZES = (12, 16, 20, 24, 32, 40, 48)
CELL = 32
# Render a margin so small mouse and keyboard pans can move the existing scene.
PAN_MARGIN = 100


@lru_cache(maxsize=1)
def _curves():
    """Midpoints on the website's circular orbits for smooth canvas edges."""
    tree = catalogue()["plannerTree"]
    nodes = tree["nodes"]
    result = {}
    for a, b, orbit in tree.get("curves", ()):
        x1, y1 = nodes[a]["x"], nodes[a]["y"]
        dx, dy = nodes[b]["x"] - x1, nodes[b]["y"] - y1
        chord = math.hypot(dx, dy)
        radii = tree["orbitRadii"]
        if abs(orbit) >= len(radii):
            continue
        radius = radii[abs(orbit)]
        if not 0 < chord <= 2 * radius:
            continue
        sagitta = radius - math.sqrt(max(0, radius**2 - chord**2 / 4))
        offset = math.copysign(sagitta, orbit) / chord
        result[tuple(sorted((a, b)))] = (x1 + dx / 2 - offset * dy, y1 + dy / 2 + offset * dx)
    return result


class BuildImportTree:
    def __init__(self, interface, parent):
        self.interface = interface
        self.t = interface.text
        self.theme = interface.theme
        self.data = catalogue()
        self.tree_data = self.data["plannerTree"]
        self.nodes, self.edges = _geometry()
        self.scope = "main"
        self.selected = self.press = self.hover = None
        self.tip_job = self.draw_job = None
        self.motion = False
        self.history = []
        self.results = {}
        self.records = {}
        self.hit_cells = {}
        self.scene_key = None
        self.scene_offset = (0., 0.)
        self.whole_scene = False
        self.images = {}
        self.start_names = defaultdict(list)
        for name, entry in self.tree_data["classes"].items():
            self.start_names[entry["root"]].append(self.interface.class_labels.get(name, name))
        self.scope_names = dict(zip(SCOPES, (self.t("Gemeinsam", "Shared"), self.t("Waffenset I", "Weapon set I"),
                                              self.t("Waffenset II", "Weapon set II"), self.t("Aszendenz", "Ascendancy"))))

        tools = ttk.Frame(parent)
        tools.pack(fill="x", pady=(0, 5))
        self.buttons = {}
        for key, name in self.scope_names.items():
            button = tk.Button(tools, text=name, relief="flat", bd=0, padx=7, pady=4, cursor="hand2",
                               command=lambda scope=key: self.change_scope(scope))
            button.pack(side="left", padx=(0, 2))
            self.buttons[key] = button
        self.search = ttk.Combobox(tools, width=11)
        self.placeholder = self.t("Passive oder ID suchen", "Search passive or ID")
        self.search.pack(side="left", fill="x", expand=True, padx=(6, 3))
        self.search.bind("<FocusIn>", lambda _: self.search.set("") if self.search.get() == self.placeholder else None)
        self.search.bind("<FocusOut>", lambda _: self.search.set(self.placeholder) if not self.search.get().strip() else None)
        self.search.bind("<KeyRelease>", self.find)
        self.search.bind("<<ComboboxSelected>>", self.find_selected)
        self.search.bind("<Return>", self.find_selected)
        ttk.Button(tools, text=self.t("Suchen", "Find"), width=7, command=self.find_selected).pack(side="left")

        self.canvas = tk.Canvas(parent, bg=SURFACE, highlightthickness=1, highlightbackground=self.theme.edge,
                                cursor="hand2", takefocus=True, width=1, height=1)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.schedule_draw)
        self.canvas.bind("<ButtonPress-1>", self.start)
        self.canvas.bind("<B1-Motion>", self.pan)
        self.canvas.bind("<ButtonRelease-1>", self.stop)
        self.canvas.bind("<Motion>", self.pointer)
        self.canvas.bind("<Leave>", self.hide_tip)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", self.wheel)
        self.canvas.bind("<Button-5>", self.wheel)
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.canvas.bind(f"<{key}>", lambda _event, dx=dx, dy=dy: self.shift(dx, dy))
        for key in ("plus", "equal", "KP_Add"):
            self.canvas.bind(f"<{key}>", lambda _event: self.scale(1.4))
        for key in ("minus", "KP_Subtract"):
            self.canvas.bind(f"<{key}>", lambda _event: self.scale(1 / 1.4))
        self.canvas.bind("<Return>", lambda _event: self.toggle())
        self.canvas.bind("<Destroy>", self.dispose)
        self.center = (0., 0.)
        self.zoom = .13
        self.fit_on_draw = None

        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(6, 3))
        for label, width, action in (("−", 2, lambda: self.scale(1 / 1.4)), ("+", 2, lambda: self.scale(1.4)),
                                     (self.t("Übersicht", "Overview"), 9, self.reset_view),
                                     (self.t("Startpunkt", "Class start"), 10, self.focus_root),
                                     (self.t("Mein Pfad", "My path"), 9, self.fit_allocations)):
            ttk.Button(bar, text=label, width=width, command=action).pack(side="left", padx=(0, 3))
        self.allocate = tk.Button(bar, bd=0, padx=10, pady=4, cursor="hand2", command=self.toggle, relief="flat")
        self.allocate.pack(side="right")
        self.undo = ttk.Button(bar, text=self.t("Rückgängig", "Undo"), width=10, command=self.undo_edit)
        self.undo.pack(side="right", padx=(0, 4))
        heading = ttk.Frame(parent)
        heading.pack(fill="x")
        self.attribute = ttk.Combobox(heading, state="readonly", width=14)
        self.attribute.bind("<<ComboboxSelected>>", self.choose_attribute)
        self.title = tk.Label(heading, anchor="w", bg=self.theme.panel, fg=GOLD, font=(self.interface.app.ui_family, 10, "bold"))
        self.title.pack(side="left", fill="x", expand=True)
        self.details = tk.Text(parent, height=2, width=4, bd=0, wrap="word", relief="flat",
                               bg=self.theme.panel, fg=self.theme.text, font=(self.interface.app.ui_family, 10),
                               highlightthickness=0, cursor="arrow", takefocus=False)
        self.details.pack(fill="x")
        self.details.build_import_colors = True
        self.refresh()

    def dispose(self, _event=None):
        for job in (self.tip_job, self.draw_job):
            if job is not None:
                self.canvas.after_cancel(job)
        self.tip_job = self.draw_job = None

    def refresh(self):
        self.selected = None
        self.history.clear()
        self.set_scope(self.scope, home=True)

    def change_scope(self, key):
        if key == self.scope:
            return
        home = "asc" in {self.scope, key}
        self.selected = None
        self.set_scope(key, home=home)

    def set_scope(self, key, *, home):
        self.hide_tip()
        self.scope = key
        self.routes = TreeRoutes(self.tree_data, self.interface.setup, key)
        asc = self.interface.setup.get("ascendancy")
        if key == "asc":
            self.visible = {i: n for i, n in self.nodes.items() if n.get("asc") and (not asc or n["asc"] == asc)}
        else:
            self.visible = {i: n for i, n in self.nodes.items() if not n.get("asc") and
                            (n.get("kind") != "root" or i == self.routes.root or not self.routes.root)}
        self.visible_edges = tuple(edge for edge in self.edges if edge[0] in self.visible and edge[1] in self.visible)
        self.records.clear()
        self.search_words = None
        self.results.clear()
        self.search.set(self.placeholder)
        self.search.configure(values=())
        for scope, button in self.buttons.items():
            color = COLORS[scope]
            button.configure(bg=color if scope == key else self.theme.control,
                             fg=SURFACE if scope == key else self.theme.text,
                             activebackground=color, activeforeground=SURFACE)
        if home:
            if self.routes.root in self.visible:
                self.focus_root()
            elif self.scope == "asc":
                self.reset_view()
            else:
                # The empty interface opens on the class starts, with recognisable nodes.
                self.center = (0., 0.)
                self.fit_on_draw = (4050, 3920)
        self.show_details()
        self.schedule_draw()

    def record(self, ident):
        if ident not in self.records:
            self.records[ident] = node_effective_record(ident, self.interface.setup, self.data)
        return self.records[ident]

    def label(self, ident):
        if ident == self.routes.root:
            if self.scope == "asc":
                asc = self.interface.setup.get("ascendancy", "")
                return self.interface.asc_labels.get(asc, asc)
            return self.class_label()
        if ident in self.start_names:
            return " / ".join(self.start_names[ident])
        row = self.record(ident)
        return (row.get("de") if self.interface.language == "de" else None) or row.get("name") or ident

    def class_label(self):
        key = self.interface.setup.get("className", "")
        return self.interface.class_labels.get(key, key)

    def effects(self, ident):
        row = self.record(ident)
        stats = display_stats(row.get("stats", ()), self.interface.language,
                              german=row.get("statsDe", ()), hybrid=row.get("statsHybrid", ()))
        notes = self.interface.setup.get("treeNotes")
        note = notes.get(ident) if isinstance(notes, dict) else None
        return (*stats, note) if isinstance(note, str) and note.strip() else stats

    def find(self, event=None):
        if event and event.keysym in {"Return", "Up", "Down", "Escape"}:
            return
        query = search_text(self.search.get())
        self.results.clear()
        if query and self.search.get() != self.placeholder:
            if self.search_words is None:
                self.search_words = {}
                for ident in self.visible:
                    row = self.record(ident)
                    names = (ident, self.label(ident), row.get("name"), row.get("de"), *row.get("aliases", ()))
                    self.search_words[ident] = search_text(" ".join(name for name in names if name))
            for ident, words in self.search_words.items():
                if query in words:
                    self.results[f"{self.label(ident)} · {ident}"] = ident
                    if len(self.results) >= 80:
                        break
        self.search.configure(values=list(self.results))

    def find_selected(self, _event=None):
        entry = self.search.get().strip()
        ident = self.results.get(entry)
        if not ident:
            self.find()
            ident = entry if entry in self.visible else next(iter(self.results.values()), None)
        if ident:
            self.select(ident, focus=True)
        elif entry and entry != self.placeholder:
            self.title.configure(text=self.t("Keine passende Passive gefunden.", "No matching passive found."))

    def open_node(self, ident):
        """Focus a guide reference without editing the setup."""
        ident = str(ident)
        if ident not in self.nodes:
            return False
        paths = self.interface.setup.get("tree", {})
        if self.nodes[ident].get("asc"):
            if self.interface.setup.get("ascendancy") not in (None, "", self.nodes[ident]["asc"]):
                return False
            scope = "asc"
        else:
            choices = [s for s in SCOPES[:3] if ident in map(str, paths.get(s, ()))]
            scope = self.scope if self.scope in choices else next(iter(choices), "main")
        if scope != self.scope:
            self.change_scope(scope)
        if ident not in self.visible:
            return False
        self.select(ident, focus=True)
        return True

    def reset_view(self):
        self.fit_nodes(self.visible)

    def fit_allocations(self):
        active = self.routes.owned & self.visible.keys()
        if len(active) > 1:
            self.fit_nodes(active)
        else:
            self.focus_root()

    def fit_nodes(self, nodes):
        if nodes:
            xs, ys = ([self.visible[i][k] for i in nodes] for k in ("x", "y"))
            self.center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            self.fit_on_draw = (max(xs) - min(xs), max(ys) - min(ys))
        self.schedule_draw()

    def focus_root(self):
        if self.routes.root in self.visible:
            self.select(self.routes.root, focus=True)
        else:
            self.reset_view()

    def scale(self, change, point=None):
        self.hide_tip()
        self.fit_on_draw = None
        before = self.zoom
        self.zoom = min(.82, max(.006, self.zoom * change))
        if point:
            x, y = point
            self.center = (self.center[0] + (x - self.canvas.winfo_width() / 2) * (1 / before - 1 / self.zoom),
                           self.center[1] + (y - self.canvas.winfo_height() / 2) * (1 / before - 1 / self.zoom))
        self.schedule_draw()
        return "break"

    def wheel(self, event):
        up = event.num == 4 or getattr(event, "delta", 0) > 0
        return self.scale(1.24 if up else 1 / 1.24, (event.x, event.y))

    def shift(self, dx, dy):
        self.hide_tip()
        self.center = (self.center[0] + dx * 85 / self.zoom, self.center[1] + dy * 85 / self.zoom)
        self.schedule_draw()
        return "break"

    def start(self, event):
        self.canvas.focus_set()
        self.hide_tip()
        self.press, self.motion = (event.x, event.y), False

    def pan(self, event):
        if self.press:
            dx, dy = event.x - self.press[0], event.y - self.press[1]
            if self.motion or abs(dx) + abs(dy) >= 4:
                self.center = self.center[0] - dx / self.zoom, self.center[1] - dy / self.zoom
                self.press, self.motion = (event.x, event.y), True
                self.schedule_draw()

    def stop(self, event):
        if self.press and not self.motion:
            ident = self.hit(event.x, event.y)
            if ident:
                self.select(ident)
        self.press = None

    def hit(self, x, y):
        nearest, best = None, float("inf")
        x -= self.scene_offset[0]
        y -= self.scene_offset[1]
        for ident, a, b, radius in self.hit_cells.get((x // CELL, y // CELL), ()):
            distance = (x - a) ** 2 + (y - b) ** 2
            if distance < best and distance <= radius ** 2:
                nearest, best = ident, distance
        return nearest

    def select(self, ident, *, focus=False):
        self.hide_tip()
        self.selected = ident
        if focus:
            self.center = self.visible[ident]["x"], self.visible[ident]["y"]
            self.fit_on_draw = None
            self.zoom = max(.21 if self.scope != "asc" else .31, self.zoom)
        self.show_details()
        self.schedule_draw()

    def toggle(self):
        if not self.selected or str(self.allocate["state"]) == "disabled":
            return
        previous = self.snapshot()
        if self.selected in self.routes.active:
            changed = self.routes.refund(self.selected)
        else:
            changed = self.routes.allocate(self.selected)
        if changed:
            self.record_edit(previous)

    def snapshot(self):
        setup = self.interface.setup
        return {k: deepcopy(setup[k]) for k in ("tree", "treeOrder", "treeOptions") if k in setup}

    def record_edit(self, previous):
        self.history.append(previous)
        del self.history[:-20]
        self.after_edit()

    def choose_attribute(self, _event=None):
        ident = self.selected
        choices = self.visible.get(ident, {}).get("choices")
        index = self.attribute.current()
        if not choices or ident not in self.routes.owned or index < 0 or index > len(choices):
            return
        previous = self.snapshot()
        setup = self.interface.setup
        if not isinstance(setup.get("treeOptions"), dict):
            setup["treeOptions"] = {}
        if index:
            setup["treeOptions"][ident] = str(choices[index - 1]["id"])
        else:
            setup["treeOptions"].pop(ident, None)
        self.record_edit(previous)

    def undo_edit(self):
        if self.history:
            previous = self.history.pop()
            for key in ("tree", "treeOrder", "treeOptions"):
                if key in previous:
                    self.interface.setup[key] = previous[key]
                else:
                    self.interface.setup.pop(key, None)
            self.after_edit()

    def after_edit(self):
        self.hide_tip()
        self.routes = TreeRoutes(self.tree_data, self.interface.setup, self.scope)
        self.records.clear()
        self.search_words = None
        self.show_details()
        self.schedule_draw()

    def show_details(self):
        active = self.routes.active
        root = self.routes.root
        ident = self.selected
        choices = self.visible.get(ident, {}).get("choices")
        if choices and ident in self.routes.owned:
            names = [ATTRIBUTES_DE.get(row["name"], row["name"]) if self.interface.language == "de" else row["name"]
                     for row in choices]
            options = self.interface.setup.get("treeOptions")
            selected = options.get(ident) if isinstance(options, dict) else None
            self.attribute.configure(values=[self.t("Attribut wählen", "Choose attribute"), *names])
            self.attribute.current(next((n for n, row in enumerate(choices, 1) if str(row["id"]) == str(selected)), 0))
            self.attribute.pack(side="right", before=self.title, padx=(4, 0))
        else:
            self.attribute.pack_forget()
        action = self.t("Weg zuweisen", "Allocate path")
        color = PREVIEW
        enabled = False
        count = len(active)
        scope = f"{self.scope_names[self.scope]} · {count} " + self.t("zugewiesen", "allocated")
        if ident:
            subtitle = self.t(*KIND.get(self.visible[ident].get("kind"), KIND["small"]))
            title = f"{self.label(ident)} · {subtitle}     |     {scope}"
            lines = list(self.effects(ident))
        else:
            title, lines = scope, []
        if not root:
            lines.insert(0, self.t("Wähle oben eine Aszendenz, um hier Punkte zu vergeben.",
                                  "Choose an ascendancy above to allocate points here.") if self.scope == "asc"
                         else self.t("Wähle oben eine Klasse für den Startpunkt deines Builds.",
                                     "Choose a class above to set your build’s starting point."))
        elif ident in active and ident != root:
            refunds = self.routes.refunds(ident)
            n = sum(map(len, refunds.values()))
            action = self.t(f"{n} zurücknehmen", f"Refund {n}")
            color, enabled = "#e8ab96", True
            if n > 1:
                lines.insert(0, self.t(f"Dieser Zweig verliert seine Verbindung ({n} Knoten).",
                                       f"This branch loses its connection ({n} nodes)."))
        elif ident and ident not in self.routes.owned:
            steps = self.routes.steps(ident)
            if steps:
                n = len(steps)
                action = self.t(f"Weg zuweisen (+{n})", f"Allocate path (+{n})")
                enabled = len(self.routes.active) + n <= 300
                if not enabled:
                    lines.insert(0, self.t("Das Dateiformat erlaubt 300 Knoten pro Set.", "File limit: 300 nodes per set."))
            else:
                lines.insert(0, self.t("Für diese Klasse und Punkteauswahl ist kein Weg verfügbar.",
                                       "No path is available with this class and allocation."))
        elif ident in self.routes.owned and ident != root:
            lines.insert(0, self.t("Bereits im gemeinsamen Baum zugewiesen.", "Already allocated in the shared tree."))
        if not lines:
            lines.append(self.t("Wähle einen Zielknoten für die Wegvorschau. Ziehen verschiebt die Karte.",
                                "Select a target to preview its path. Drag to move the map."))
        self.title.configure(text=title)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("end", "\n".join(lines))
        self.details.configure(state="disabled")
        self.allocate.configure(text=action, state="normal" if enabled else "disabled",
                                bg=color if enabled else self.theme.control,
                                fg=SURFACE, activebackground="#fff1c5", activeforeground=SURFACE,
                                disabledforeground=self.theme.text)
        self.undo.configure(state="normal" if self.history else "disabled")

    def pointer(self, event):
        if self.press:
            return
        ident = self.hit(event.x, event.y)
        if ident == self.hover:
            return
        self.hide_tip()
        if ident:
            self.hover = ident
            self.tip_job = self.canvas.after(150, lambda: self.show_tip(ident, event.x, event.y))

    def hide_tip(self, _event=None):
        if self.tip_job is not None:
            self.canvas.after_cancel(self.tip_job)
            self.tip_job = None
        self.hover = None
        self.canvas.delete("tip")

    def show_tip(self, ident, x, y):
        self.tip_job = None
        if self.hover != ident or self.press:
            return
        c = self.canvas
        width = max(80, min(300, c.winfo_width() - 28))
        tx, ty = x + 16, y + 14
        title = c.create_text(tx, ty, text=self.label(ident), anchor="nw", fill=GOLD, width=width,
                              font=(self.interface.app.ui_family, 10, "bold"), tags="tip")
        steps = self.routes.steps(ident)
        lines = list(self.effects(ident))
        if steps:
            n = len(steps)
            lines.insert(0, self.t(f"Kürzester Weg · +{n} Punkte", f"Shortest path · +{n} points"))
        elif ident in self.routes.owned:
            lines.insert(0, self.t("Zugewiesen", "Allocated") if ident != self.routes.root else self.t("Startpunkt", "Class start"))
        if lines:
            c.create_text(tx, c.bbox(title)[3] + 3, anchor="nw", width=width, text="\n".join(lines),
                          fill=self.theme.text, font=(self.interface.app.ui_family, 9), tags="tip")
        left, top, right, bottom = c.bbox("tip")
        frame = c.create_rectangle(left - 8, top - 5, right + 8, bottom + 6, outline="#927d55", fill="#161a1a", tags="tip")
        c.tag_lower(frame, title)
        box = c.bbox("tip")
        c.move("tip", max(3 - box[0], min(0, c.winfo_width() - box[2] - 3)),
               max(3 - box[1], min(0, c.winfo_height() - box[3] - 3)))

    def schedule_draw(self, _event=None):
        if self.draw_job is None:
            self.draw_job = self.canvas.after_idle(self.draw)

    def draw(self):
        self.draw_job = None
        canvas = self.canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 5 or height < 5:
            return
        self.hide_tip()
        if self.fit_on_draw is not None:
            sx, sy = self.fit_on_draw
            self.zoom = max(.006, min(.35, max(10, width - 44) / max(240, sx), max(10, height - 44) / max(240, sy)))
            self.fit_on_draw = None
        zoom = self.zoom
        key = (zoom, self.routes, self.selected)
        if key == self.scene_key:
            original_width, original_height = self.scene_size
            sx = (self.scene_center[0] - self.center[0]) * zoom + (width - original_width) / 2
            sy = (self.scene_center[1] - self.center[1]) * zoom + (height - original_height) / 2
            # Resizing and panning both translate the original scene. Refill only
            # when an edge of the new viewport would expose uncached map content.
            exposed = max(sx, sy, width - original_width - sx, height - original_height - sy)
            if self.whole_scene or exposed <= PAN_MARGIN:
                old_x, old_y = self.scene_offset
                if (sx, sy) != (old_x, old_y):
                    canvas.move("map", sx - old_x, sy - old_y)
                self.scene_offset = (sx, sy)
                return
        self.scene_key = key
        self.scene_size = width, height
        self.scene_center = self.center
        self.scene_offset = (0., 0.)
        self.whole_scene = True
        canvas.delete("map")
        self.images.clear()
        dx, dy = width / 2 - self.center[0] * zoom, height / 2 - self.center[1] * zoom
        route = self.routes.route(self.selected)
        preview = set(route)
        preview_edges = {tuple(sorted(edge)) for edge in zip(route, route[1:])}
        owned, active = self.routes.owned, self.routes.active
        color = COLORS[self.scope]
        coords = {i: (n["x"] * zoom + dx, n["y"] * zoom + dy) for i, n in self.visible.items()}
        if self.routes.root in coords and zoom >= .08:
            x, y = coords[self.routes.root]
            margin = 112 + PAN_MARGIN
            if -margin <= x <= width + margin and -margin <= y <= height + margin:
                if self.scope == "asc":
                    ref = self.tree_data.get("ascArt", {}).get(self.interface.setup.get("ascendancy"))
                else:
                    ref = self.tree_data["classes"].get(self.interface.setup.get("className"), {}).get("image")
                portrait = build_icon(canvas, ref, 224)
                if portrait is not None:
                    self.images["portrait"] = portrait
                    canvas.create_image(x, y, image=portrait, tags="map")
            else:
                self.whole_scene = False
        curves = _curves()
        edge_margin = 45 + PAN_MARGIN
        for edge in self.visible_edges:
            first, second = edge
            x, y = coords[first]
            a, b = coords[second]
            if (max(x, a) < -edge_margin or min(x, a) > width + edge_margin or
                    max(y, b) < -edge_margin or min(y, b) > height + edge_margin):
                self.whole_scene = False
                continue
            line_color, weight = "#49483e", 1
            if edge in preview_edges:
                line_color, weight = PREVIEW, 3
            elif first in owned and second in owned:
                line_color, weight = (color if first in active or second in active else GOLD), 2
            if edge in curves and zoom > .035:
                cx, cy = curves[edge]
                # A Tk quadratic spline passes halfway toward its control point at t=.5.
                mx, my = cx * zoom + dx, cy * zoom + dy
                canvas.create_line(x, y, 2 * mx - (x + a) / 2, 2 * my - (y + b) / 2, a, b,
                                   smooth=True, splinesteps=8, fill=line_color, width=weight, tags="map")
            else:
                canvas.create_line(x, y, a, b, fill=line_color, width=weight, tags="map")
        cells = defaultdict(list)
        node_margin = 52 + PAN_MARGIN
        for ident, (x, y) in coords.items():
            if x < -node_margin or x > width + node_margin or y < -node_margin or y > height + node_margin:
                self.whole_scene = False
                continue
            row = self.visible[ident]
            kind = row.get("kind", "small")
            radius = max(2, min(27, zoom * RADII.get(kind, 31)))
            near = any(link in owned for link in row["links"]) and self.routes.available(ident)
            ring = color if ident in active or ident == self.routes.root else GOLD if ident in owned else PREVIEW if ident in preview else "#a99872" if near else "#756b57"
            draw_radius = radius if radius >= 4 else max(3, radius) if ident in owned or ident in preview else radius
            canvas.create_oval(x - draw_radius, y - draw_radius, x + draw_radius, y + draw_radius,
                               fill=ring if radius < 5 else "#232723", outline=ring, tags="map")
            if radius >= 5:
                self.draw_art(ident, x, y, radius, kind, near)
            if ident == self.selected or ident in preview:
                pad = 4 if ident == self.selected else 2
                radius += pad
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                                   outline="#fff0be" if ident == self.selected else PREVIEW, width=2, tags="map")
            if (ident == self.routes.root or (not self.routes.root and ident in self.start_names)) and zoom >= .04:
                canvas.create_text(x, y + radius + 6, anchor="n", text=self.label(ident), fill=GOLD,
                                   font=(self.interface.app.ui_family, 9, "bold"), tags="map")
            hit_radius = max(5, radius + 3)
            for col in range(int((x - hit_radius) // CELL), int((x + hit_radius) // CELL) + 1):
                for line in range(int((y - hit_radius) // CELL), int((y + hit_radius) // CELL) + 1):
                    cells[col, line].append((ident, x, y, hit_radius))
        self.hit_cells = cells

    def draw_art(self, ident, x, y, radius, kind, near):
        row = self.visible[ident]
        icon = self.record(ident).get("atlasIcon", -1)
        frames = row.get("frames") or self.tree_data.get("frames", {}).get(FRAME_KIND.get(kind))
        layers = [(icon, 2 * radius)]
        if frames and radius >= 7:
            index = 2 if ident in self.routes.owned else 1 if near else 0
            layers.append((frames[index], 2.5 * radius))
        for index, diameter in layers:
            if index < 0:
                continue
            size = min(SIZES, key=lambda s: abs(s - diameter))
            key = index, size
            if key not in self.images:
                self.images[key] = build_icon(self.canvas, f"tree/{index}", size)
            image = self.images[key]
            if image is not None:
                self.canvas.create_image(x, y, image=image, tags="map")
