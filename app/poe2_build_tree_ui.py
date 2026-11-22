"""Read-only rendering of the planner's published passive tree geometry."""

from collections import defaultdict
from functools import lru_cache
import tkinter as tk

from poe2_build_art import build_icon
from poe2_build_tree_routes import node_effective_record
from poe2_language import display_label
from poe2_lexicon import NODE_KINDS, catalogue, display_stats
from poe2_overlay_controls import FlowRow


PATH_LABELS = {
    "main": ("Gemeinsam", "Gemeinsam", "Shared"),
    "weaponSet1": ("Waffenset I", "Weapon Set I", "Weapon Set I"),
    "weaponSet2": ("Waffenset II", "Weapon Set II", "Weapon Set II"),
    "ascendancy": ("Aszendenz", "Ascendancy", "Ascendancy"),
}
TREE_SURFACE = "#1c211e"
EXTRA_KINDS = {
    "attribute": ("Attribute", "Attribute", "Attributes"),
    "root": ("Startpunkte", "Startpunkte", "Starting points"),
    "other": ("Weitere", "Weitere", "Other"),
}
KINDS = ("keystone", "notable", "socket", "attribute", "small", "root", "other")


@lru_cache(maxsize=1)
def _geometry():
    nodes = catalogue().get("plannerTree", {}).get("nodes", {})
    # The archive records reciprocal links. Normalize once, including one-way input.
    endpoints = {tuple(sorted((ident, other))) for ident, point in nodes.items()
                 for other in point.get("links", ()) if other in nodes and other != ident}
    return nodes, tuple(sorted(endpoints))


def render_passive_tree(window, parent, paths, setup=None):
    """Return the interactive map when the published references have coordinates."""
    nodes, edges = _geometry()
    available = {path.key: tuple(node for node in path.nodes if node.id in nodes)
                 for path in paths if path.key in PATH_LABELS}
    available = {key: allocation for key, allocation in available.items() if allocation}
    if not available:
        return None
    return _PassiveTree(window, parent, nodes, edges, available, setup or {})


def _node_detail(ident, asset, language, setup):
    record = node_effective_record(ident, setup)
    if not record.get("name") and asset:
        record = asset.record or {}
    name = ((record.get("de") if language == "de" else None) or record.get("name")
            or (asset.name if asset else ident))
    stats = display_stats(record.get("stats", ()), language,
                          german=record.get("statsDe", ()), hybrid=record.get("statsHybrid", ()))
    lines = [*stats]
    if asset and asset.note:
        lines.append(asset.note)
    if not lines:
        lines.append("No stat values recorded." if language == "en" else "Keine Werte hinterlegt.")
    icon = record.get("atlasIcon", -1)
    return name, "\n".join(lines), None, f"tree/{icon}" if icon >= 0 else ""


def _groups(nodes):
    groups = defaultdict(list)
    geometry = catalogue()["plannerTree"]["nodes"]
    for number, node in enumerate(nodes, 1):
        kind = (node.record or {}).get("type")
        tree_kind = geometry.get(node.id, {}).get("kind")
        if tree_kind in {"attribute", "root"}:
            kind = tree_kind
        groups[kind if kind in KINDS else "other"].append((number, node))
    return [(kind, groups[kind]) for kind in KINDS if kind in groups]


def _disclosure(window, parent, label, populate):
    """Populate on first opening so an imported 100-point tree stays cheap to display."""
    px = window.layout.px
    section = tk.Frame(parent, bg=parent.cget("bg"))
    section.pack(fill="x", pady=(0, px(2)))
    body = tk.Frame(section, bg=section.cget("bg"), padx=px(6))
    populated = False

    def toggle():
        nonlocal populated
        if body.winfo_manager():
            body.pack_forget()
            button.configure(text="▸ " + label)
        else:
            if not populated:
                populate(body)
                populated = True
            body.pack(fill="x")
            button.configure(text="▾ " + label)
        window._refit_route()
        window._schedule_targets()

    button = window.small_button(section, "▸ " + label, toggle)
    button.configure(anchor="w", justify="left", padx=px(6), fg=window.theme.accent)
    button.pack(fill="x")


def render_passive_list(window, parent, paths, view=None, setup=None):
    if not paths:
        return
    language = window.app.language
    px = window.layout.px
    open_row = None

    def populate_rows(body, path, rows):
        nonlocal open_row
        for number, node in rows:
            entry = _node_detail(node.id, node, language, setup or {})
            name, summary = entry[:2]
            row = tk.Frame(body, bg=body.cget("bg"))
            row.pack(fill="x")

            def select(row=row, ident=node.id, summary=summary):
                nonlocal open_row
                previous = open_row
                if previous:
                    previous.destroy()
                    open_row = None
                if previous is not None and previous.master is row:
                    window._refit_route()
                    window._schedule_targets()
                    return
                if view:
                    view.locate(path.key, ident)
                open_row = tk.Label(row, text=summary, justify="left", anchor="w", padx=px(8), pady=px(3),
                                    font=window.ui_font(10), bg=window.theme.control, fg=window.theme.text)
                open_row.pack(fill="x")
                open_row.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(px(24), e.width - px(20))))
                window._refit_route()
                window._schedule_targets()

            button = window.small_button(row, f"{number} · {name}", select)
            button.configure(anchor="w", justify="left", bd=0, relief="flat", highlightthickness=0,
                             bg=body.cget("bg"), font=window.ui_font(10), padx=px(4), pady=px(1))
            button.pack(fill="x")
            button.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(px(24), e.width - px(12))))
            button.detail_at_point = lambda x, y, ident=node.id, entry=entry: (ident, entry)
            window.app.term_tips.register(button)

    def populate(body):
        for path in paths:
            scope = display_label(PATH_LABELS[path.key], language)
            tk.Label(body, text=scope, anchor="w", bg=body.cget("bg"), fg=window.theme.text,
                     font=window.ui_font(10, "bold")).pack(fill="x", pady=(px(4), px(1)))
            for kind, rows in _groups(path.nodes):
                labels = NODE_KINDS[kind] if kind in NODE_KINDS else EXTRA_KINDS[kind]
                title = f"{display_label(labels, language)} · {len(rows)}"
                _disclosure(window, body, title, lambda group, p=path, r=rows: populate_rows(group, p, r))

    total = sum(len(path.nodes) for path in paths)
    label = "Allocated nodes" if language == "en" else "Zugewiesene Knoten"
    _disclosure(window, parent, f"{label} · {total}", populate)


class _PassiveTree:
    def __init__(self, window, parent, nodes, edges, paths, setup):
        self.window = window
        self.language = window.app.language
        self.px = window.layout.px
        self.nodes = nodes
        self.edges = edges
        self.paths = paths
        self.setup = setup
        self.path_key = next(iter(paths))
        self.selected = 0
        self.inspected = None
        self.center = None
        self.zoom = 1.0
        self.scale = 1.0
        self.hits = {}
        self.images = []
        self.gesture = None
        self.redraw_job = None
        self.drag_delta = (0, 0)
        self.path_buttons = {}
        bg = parent.guide_card_color

        if len(paths) > 1:
            scopes = FlowRow(parent, bg=bg, gap=self.px(4))
            scopes.pack(fill="x", padx=self.px(3), pady=(0, self.px(4)))
            for key in paths:
                label = display_label(PATH_LABELS[key], self.language)
                self.path_buttons[key] = window.small_button(scopes, label, lambda key=key: self._choose(key))

        self.canvas = tk.Canvas(parent, bg=TREE_SURFACE, width=1, height=self.px(184), bd=0,
                                highlightthickness=1, highlightbackground=window.theme.edge,
                                highlightcolor=window.theme.accent, cursor="fleur", takefocus=True)
        self.canvas.pack(fill="x", padx=self.px(3))
        self.canvas.bind("<Configure>", self.draw)
        self.canvas.bind("<Destroy>", lambda event: self._cancel_redraw())
        self.canvas.overlay_pointer = self._pointer
        for event, phase in (("<ButtonPress-1>", "press"), ("<B1-Motion>", "motion"), ("<ButtonRelease-1>", "release")):
            self.canvas.bind(event, lambda e, phase=phase: self._pointer(phase, e))
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            self.canvas.bind(f"<{key}>", lambda e, dx=dx, dy=dy: self._key_pan(dx, dy))
        self.canvas.detail_at_point = self._hover
        self.window.app.term_tips.register(self.canvas)
        english = self.language == "en"
        hint = "Drag to pan · Hover over nodes for stats" if english else "Zum Verschieben ziehen · Maus über Knoten für Werte"
        gesture_hint = tk.Label(parent, text=hint, anchor="w", justify="left", bg=bg,
                                fg=window.theme.text, font=window.ui_font(9))
        gesture_hint.pack(fill="x", padx=self.px(4))
        gesture_hint.bind("<Configure>", lambda e: gesture_hint.configure(wraplength=max(1, e.width - self.px(6))))
        self.caption = tk.Label(parent, bg=bg, fg=window.theme.text, font=window.ui_font(10),
                                anchor="w", justify="left", padx=self.px(3))
        self.caption.pack(fill="x", padx=self.px(3), pady=(self.px(4), 0))
        self.caption.bind("<Configure>", lambda event: self.caption.configure(wraplength=max(1, event.width - self.px(6))))

        controls = FlowRow(parent, bg=bg, gap=self.px(4))
        controls.pack(fill="x", padx=self.px(3), pady=(self.px(3), self.px(4)))
        self.previous = window.small_button(controls, "Previous" if english else "Zurück", lambda: self._move(-1))
        self.following = window.small_button(controls, "Next node" if english else "Nächster Knoten", lambda: self._move(1))
        window.small_button(controls, "−", lambda: self._scale(1 / 1.5))
        window.small_button(controls, "+", lambda: self._scale(1.5))
        window.small_button(controls, "Overview" if english else "Übersicht", self._overview)
        self._update_selection()

    def _choose(self, key):
        self.path_key = key
        self.selected = 0
        self.inspected = None
        self._overview()
        self._update_selection()

    def _overview(self):
        self.zoom = 1.0
        self.center = None
        self.draw()

    def _move(self, offset):
        path = self.paths[self.path_key]
        self.selected = min(len(path) - 1, max(0, self.selected + offset))
        self.inspected = None
        point = self.nodes[path[self.selected].id]
        self.center = point["x"], point["y"]
        self._update_selection()
        self.draw()

    def _scale(self, factor):
        self.zoom = min(32, max(.5, self.zoom * factor))
        self.draw()

    @property
    def focused_id(self):
        return self.inspected or self.paths[self.path_key][self.selected].id

    def locate(self, key, ident):
        if ident not in self.nodes or key not in self.paths:
            return
        self.path_key = key
        self.selected = next(i for i, node in enumerate(self.paths[key]) if node.id == ident)
        self.zoom = max(2, self.zoom)
        self._move(0)

    def _asset(self, ident):
        path = self.paths[self.path_key]
        if self.path_key.startswith("weaponSet"):
            path += self.paths.get("main", ())
        return next((node for node in path if node.id == ident), None)

    def _nearest(self, x, y):
        candidates = self.canvas.find_overlapping(x - self.px(4), y - self.px(4), x + self.px(4), y + self.px(4))
        return min((self.hits[item] for item in candidates if item in self.hits),
                   key=lambda hit: (hit[1] - x) ** 2 + (hit[2] - y) ** 2, default=(None,))[0]

    def _hover(self, x, y):
        if self.gesture is None and (ident := self._nearest(x, y)):
            return ident, _node_detail(ident, self._asset(ident), self.language, self.setup)

    def _key_pan(self, dx, dy):
        if self.window.app.click_through:
            return
        if self.center:
            x, y = self.center
            self.center = x + dx * self.px(40) / self.scale, y + dy * self.px(40) / self.scale
            self.draw()
        return "break"

    def _cancel_redraw(self):
        if self.redraw_job is not None:
            self.canvas.after_cancel(self.redraw_job)
            self.redraw_job = None

    def _pointer(self, phase, event):
        canvas = self.canvas
        x, y = event.x_root - canvas.winfo_rootx(), event.y_root - canvas.winfo_rooty()
        if phase == "press":
            # Transparent edit mode forwards the click from a non-activating native
            # target. Only an intentional press in edit mode transfers keyboard focus.
            if not self.window.app.click_through:
                canvas.focus_force()
            self.gesture = (x, y, x, y, False)
            self.window.app.term_tips.hide()
            return
        if self.gesture is None or self.center is None:
            return
        x0, y0, last_x, last_y, dragged = self.gesture
        dragged = dragged or max(abs(x - x0), abs(y - y0)) >= self.px(3)
        if dragged:
            dx, dy = x - last_x, y - last_y
            cx, cy = self.center
            self.center = cx - dx / self.scale, cy - dy / self.scale
            canvas.move("all", dx, dy)
            self.drag_delta = self.drag_delta[0] + dx, self.drag_delta[1] + dy
            self.gesture = (x0, y0, x, y, True)
            # Shift existing Tk objects immediately. Refill the overscan after larger moves.
            if max(map(abs, self.drag_delta)) > self.px(35) and self.redraw_job is None:
                self.redraw_job = canvas.after(45, self.draw)
        if phase == "release":
            self.gesture = None
            if not dragged and (ident := self._nearest(x, y)):
                self.inspected = ident
                for index, node in enumerate(self.paths[self.path_key]):
                    if node.id == ident:
                        self.selected = index
                        self.inspected = None
                        break
                self._update_selection()
            self.draw()

    def _update_selection(self):
        theme = self.window.theme
        for key, button in self.path_buttons.items():
            active = key == self.path_key
            button.configure(bg=theme.selection_color if active else theme.control,
                             fg=theme.selection_text if active else theme.text)
        path = self.paths[self.path_key]
        self.previous.configure(state="normal" if self.selected else "disabled")
        self.following.configure(state="normal" if self.selected + 1 < len(path) else "disabled")
        ident = self.focused_id
        name, summary = _node_detail(ident, self._asset(ident), self.language, self.setup)[:2]
        status = f"{self.selected + 1}/{len(path)}"
        if self.inspected:
            status = "Not allocated" if self.language == "en" else "Nicht zugewiesen"
            if self._asset(ident):
                status = display_label(PATH_LABELS["main"], self.language)
        self.caption.configure(text=f"{status} · {name}\n{summary}")
        self.window._schedule_targets()

    def draw(self, event=None):
        self._cancel_redraw()
        self.drag_delta = (0, 0)
        canvas = self.canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        path = self.paths[self.path_key]
        picked = {node.id for node in path}
        shared = {node.id for node in self.paths.get("main", ())} if self.path_key.startswith("weaponSet") else set()
        focused = self.focused_id
        x_coords = [self.nodes[ident]["x"] for ident in picked]
        y_coords = [self.nodes[ident]["y"] for ident in picked]
        if self.center is None:
            self.center = (min(x_coords) + max(x_coords)) / 2, (min(y_coords) + max(y_coords)) / 2
        center_x, center_y = self.center
        margin = self.px(26)
        scale = max(.01, min((width - margin) / max(700, max(x_coords) - min(x_coords)),
                             (height - margin) / max(700, max(y_coords) - min(y_coords)))) * self.zoom
        self.scale = scale
        branches = {self.nodes[ident].get("asc") for ident in picked}
        positions = {ident: ((point["x"] - center_x) * scale + width / 2,
                             (point["y"] - center_y) * scale + height / 2)
                     for ident, point in self.nodes.items() if point.get("asc") in branches}

        canvas.delete("all")
        self.hits.clear()
        self.images.clear()
        pad = self.px(40)
        for first, second in self.edges:
            p1, p2 = positions.get(first), positions.get(second)
            if not p1 or not p2:
                continue
            x1, y1 = p1
            x2, y2 = p2
            if max(x1, x2) < -pad or min(x1, x2) > width + pad or max(y1, y2) < -pad or min(y1, y2) > height + pad:
                continue
            active = first in picked and second in picked
            inherited = (first in shared or first in picked) and (second in shared or second in picked)
            colour = "#dbbd7e" if active else "#8b774c" if inherited else "#414840"
            canvas.create_line(x1, y1, x2, y2, fill=colour, width=2 if active else 1)
        detailed = self.zoom >= 2 and scale * 120 >= self.px(14)
        for ident, (x, y) in positions.items():
            if not (-pad <= x <= width + pad and -pad <= y <= height + pad):
                continue
            if ident in picked:
                radius, fill, outline = self.px(4), "#e8cc8b", "#9b7943"
            elif ident in shared:
                radius, fill, outline = self.px(3), "#a18151", "#615036"
            else:
                radius, fill, outline = self.px(2), "#627269", TREE_SURFACE
            image = None
            if detailed:
                icon = node_effective_record(ident, self.setup).get("atlasIcon", -1)
                if icon >= 0:
                    important = self.nodes[ident].get("kind") in {"notable", "jewel", "keystone"}
                    image = build_icon(canvas, f"tree/{icon}", self.px(20 if important else 14))
                if image:
                    radius = image.width() // 2 + self.px(1)
            item = canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=fill, outline=outline)
            self.hits[item] = (ident, x, y)
            if image:
                self.images.append(image)
                self.hits[canvas.create_image(x, y, image=image)] = (ident, x, y)
        x, y = positions[focused]
        radius = self.px(13 if detailed else 7)
        canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline="#fff2c6", width=2)
