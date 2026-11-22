"""Phase-specific guide copy, with links into the editable setup."""

from collections import Counter
from dataclasses import dataclass
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog, ttk
from urllib.parse import quote
from uuid import uuid4

from poe2_build_editorial import BUILD_TOPICS, PHASE_TOPICS, editorial_lines, phase_label, reference_parts
from poe2_build_loadout import SLOTS, slot_label
from poe2_build_import_interface import phase_setup
from poe2_build_terms import gem_color, gem_entry, gem_spans
from poe2_r18_features import ITEM_COLORS, term_key, term_matches
from poe2_website_content import LIMITS


TOPICS = {
    "overview": ("Überblick", "Overview"),
    "general": ("Spielweise", "Playstyle"),
    "why": ("Mechanik", "Mechanics"),
    "quests": ("Questwahl", "Quests"),
    "gems": ("Fertigkeiten", "Skills"),
    "gear": ("Ausrüstung", "Gear"),
    "tree": ("Passivbaum", "Passive tree"),
}
TAB_TOPICS = ("gear", "gems", "tree")
BLOCK_TOPICS = {
    "gems": "gems", "gemPriority": "gems", "rotation": "gems",
    "gear": "gear", "itemPriority": "gear", "crafting": "gear",
    "tree": "tree", "asc": "tree",
}


@dataclass
class GuideField:
    owner: dict
    path: tuple
    heading: str
    value: str
    lines: bool = False

    def write(self, value):
        parent = self.owner
        for key in self.path[:-1]:
            if isinstance(parent, dict) and not isinstance(parent.get(key), (dict, list)):
                parent[key] = {}
            parent = parent[key]
        value = value.strip()
        parent[self.path[-1]] = [line.strip() for line in value.splitlines() if line.strip()] if self.lines else value


def guide_fields(phase, topic, text):
    """Retain the source of every paragraph, including published HUD guides."""
    fields = []

    def add(path, heading, value, *, lines=False):
        if lines and isinstance(value, list):
            value = "\n".join(row for row in value if isinstance(row, str))
        if isinstance(value, str) and value.strip():
            fields.append(GuideField(phase, path, heading, value, lines))

    label = text(*TOPICS[topic])
    if topic == "general":
        add(("note",), label, phase.get("note"))
    hints = phase.get("guideHints")
    if topic != "general" and isinstance(hints, dict):
        add(("guideHints", topic), label, hints.get(topic), lines=True)
    original = phase.get("overlayStage")
    if isinstance(original, dict):
        for key, group, heading in (("quick", "general", label), ("next", "general", text(*PHASE_TOPICS["next"])),
                                    ("playstyle", "general", label), ("nextSteps", "general", text(*PHASE_TOPICS["next"])),
                                    ("why", "why", label), ("quests", "quests", label),
                                    ("skills", "gems", label), ("craft", "gear", label), ("passives", "tree", label)):
            if group == topic:
                add(("overlayStage", key), heading, original.get(key), lines=key not in ("quick", "next"))
    guide = phase.get("guideText")
    if isinstance(guide, dict):
        for key, value in guide.items():
            if BLOCK_TOPICS.get(key, "general") == topic:
                add(("guideText", key), label, value)
        blocks = guide.get("blocks")
        for index, block in enumerate(blocks if isinstance(blocks, list) else ()):
            if not isinstance(block, dict):
                continue
            if BLOCK_TOPICS.get(str(block.get("placement") or block.get("type")), "general") == topic:
                title = block.get("title")
                add(("guideText", "blocks", index, "text"), title if isinstance(title, str) and title else label,
                    block.get("text"))
    if not fields:
        path = ("note",) if topic == "general" else ("guideHints", topic)
        fields.append(GuideField(phase, path, label, "", topic != "general"))
    return fields


def reader_fields(build, phase, topic, text, language):
    """Display all sources for this topic; localized edits go into the chosen language only."""
    if topic == "overview":
        owner, keys, labels = build, BUILD_TOPICS, BUILD_TOPICS
    else:
        owner = phase
        keys = ("next", "playstyle") if topic == "general" else (topic,)
        labels = PHASE_TOPICS
    fields = [GuideField(owner, ("editorial", key, language), text(*labels[key]),
                         "\n".join(editorial_lines(owner, key, language)), lines=True) for key in keys]
    if topic != "overview":
        fields.extend(field for field in guide_fields(phase, topic, text) if field.value)
    return fields


@dataclass(frozen=True)
class GuideLink:
    kind: str
    target: str | int
    name: str
    aliases: tuple = ()


def guide_links(phase, setup, data, language, fields=()):
    """Use the website's item:, gem:, group: and node: namespaces."""
    links = {}

    def gem(ident, fallback=""):
        if not isinstance(ident, str) or not ident:
            return
        row = data["skills"].get(ident) or data["supports"].get(ident) or {}
        name = (row.get("de") if language == "de" else None) or row.get("name") or fallback
        if name:
            names = tuple(x for x in (row.get("name"), row.get("de")) if isinstance(x, str))
            links[f"gem:{ident}"] = GuideLink("gem", ident, name, names)

    counts = Counter()
    for index, group in enumerate(setup.get("gems", [])):
        ident = group["id"]
        ref = group.get("overlayRef")
        gem(ident, ref.get("name", "") if isinstance(ref, dict) else "")
        link = links.get(f"gem:{ident}")
        if link:
            key = f"group:{ident}-{counts[ident]}"
            links[key] = GuideLink("group", index, f"{link.name} · Setup {index + 1}")
        counts[ident] += 1
        for socket in group.get("sockets", []):
            gem(socket.get("id") if isinstance(socket, dict) else socket)
    extra = phase.get("gemReferences")
    for row in extra if isinstance(extra, list) else ():
        if isinstance(row, dict):
            gem(row.get("id"))
    for slot in dict.fromkeys((*SLOTS, *setup.get("gear", {}))):
        item = setup.get("gear", {}).get(slot, {})
        ref = item.get("overlayRef")
        name = next((item[key] for key in ("sourceName", "unique", "item", "base") if item.get(key)), None)
        name = name or (ref.get("name") if isinstance(ref, dict) else "")
        label = slot_label(slot, language)
        links[f"item:{slot}"] = GuideLink("item", slot, f"{label} · {name}" if name else label, (name,) if name else ())
    node_paths = list(setup.get("tree", {}).values())
    explicit_nodes = []
    for field in fields:
        for _, ref, _ in reference_parts(field.value):
            kind, _, ident = ref.partition(":")
            if kind == "gem":
                gem(ident)
            elif kind == "node":
                explicit_nodes.append(ident)
    for path in [*node_paths, explicit_nodes]:
        if not isinstance(path, list):
            continue
        for node in path:
            ident = str(node)
            row = data["nodes"].get(ident, {})
            name = (row.get("de") if language == "de" else None) or row.get("name")
            if name:
                links[f"node:{ident}"] = GuideLink("node", ident, name)
    return links


def linked_segments(value, links, language=None):
    """Resolve authored targets first, then whole catalogue and equipped-item names."""
    aliases = {}
    for key, link in links.items():
        if language and link.kind == "gem":
            continue
        for name in link.aliases:
            if isinstance(name, str) and len(name.strip()) >= 3:
                alias = term_key(name)
                aliases[alias] = key if aliases.get(alias, key) == key else None
    aliases = {name: key for name, key in aliases.items() if key}
    for part, key, token in reference_parts(value):
        if token:
            yield part, key if key in links else None
            continue
        matches = list(term_matches(part, aliases))
        if language:
            preferred = {link.target for link in links.values() if link.kind == "gem" and link.aliases}
            matches.extend((start, end, f"gem:{ident}") for start, end, ident in gem_spans(part, language, preferred))
        offset = 0
        for start, end, target in sorted(matches, key=lambda hit: (hit[0], -hit[1])):
            if start < offset:
                continue
            if start > offset:
                yield part[offset:start], None
            yield part[start:end], target
            offset = end
        if offset < len(part):
            yield part[offset:], None


class BuildImportGuideMixin:
    def make_phases(self, page):
        self.guide_topic = "general"
        self.guide_resize_job = None
        self.guide_reader_width = 0
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)
        rail = ttk.Frame(page)
        rail.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        ttk.Label(rail, text=self.text("Phasen", "Phases")).pack(anchor="w", pady=(0, 4))
        ttk.Button(rail, text=self.text("+ Phase aus Setup", "+ Phase from setup"),
                   command=self.add_phase).pack(fill="x", pady=(0, 6))
        self.phases = self.listbox(rail, height=5)
        self.phases.configure(width=19, activestyle="none")
        self.phases.bind("<<ListboxSelect>>", self.open_phase)
        controls = ttk.Frame(rail)
        controls.pack(fill="x", pady=(6, 0))
        self.phase_actions = ttk.Menubutton(controls, text=self.text("Phase verwalten ▾", "Manage phase ▾"))
        self.phase_actions.pack(fill="x")
        self.phase_menu = menu = tk.Menu(self.phase_actions, tearoff=False, bg=self.theme.control, fg=self.theme.text)
        self.phase_actions.configure(menu=menu)
        for label, action in ((("Umbenennen", "Rename"), self.rename_phase),
                              (("Nach oben", "Move up"), lambda: self.move_phase(-1)),
                              (("Nach unten", "Move down"), lambda: self.move_phase(1)),
                              (("Phase entfernen", "Remove phase"), self.remove_phase)):
            menu.add_command(label=self.text(*label), command=action)
        self.guide_page = right = ttk.Frame(page)
        right.grid(row=0, column=1, sticky="nsew")
        self.guide_title = tk.Label(right, anchor="w", bg=self.theme.panel, fg=self.theme.accent,
                                    font=(self.app.ui_family, 14, "bold"))
        self.guide_title.pack(fill="x", pady=(0, 8))
        self.guide_topics = ttk.Frame(right)
        self.guide_topics.pack(fill="x", pady=(0, 6))
        self.guide_buttons = {}
        for index, (topic, labels) in enumerate(TOPICS.items()):
            button = tk.Button(self.guide_topics, text=self.text(*labels), relief="flat", bd=0, padx=6, pady=4,
                               command=lambda key=topic: self.select_guide_topic(key))
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=(0, 3), pady=(0, 2))
            self.guide_buttons[topic] = button
        self.guide_box = box = ttk.Frame(right)
        box.pack(fill="x")
        self.guide_reader = reader = tk.Text(box, wrap="word", borderwidth=0, padx=10, pady=8, height=5, width=1,
                                              font=(self.app.ui_family, 11), cursor="arrow", highlightthickness=0,
                                              takefocus=True)
        self.guide_scroll = ttk.Scrollbar(box, command=reader.yview)
        reader.configure(yscrollcommand=self.guide_scroll.set)
        reader.pack(fill="both", expand=True)
        reader.tag_configure("heading", foreground=self.theme.accent, spacing1=3, spacing3=3,
                             font=(self.app.ui_family, 11, "bold"))
        reader.tag_configure("strengths", foreground="#a0ee7d")
        reader.tag_configure("weaknesses", foreground="#ffbdb0")
        reader.tag_configure("link", underline=True, foreground=self.theme.accent)
        reader.tag_configure("focused", background=self.theme.selection_color, foreground=self.theme.selection_text)
        reader.tag_bind("link", "<Button-1>", self.follow_guide_reference)
        reader.tag_bind("link", "<Enter>", lambda _: reader.configure(cursor="hand2"))
        reader.tag_bind("link", "<Leave>", lambda _: reader.configure(cursor="arrow"))
        reader.bind("<Tab>", lambda _: self.step_guide_reference(1))
        reader.bind("<Shift-Tab>", lambda _: self.step_guide_reference(-1))
        if reader.tk.call("tk", "windowingsystem") == "x11":
            reader.bind("<ISO_Left_Tab>", lambda _: self.step_guide_reference(-1))
        reader.bind("<Return>", lambda _: self.follow_guide_reference())
        reader.bind("<FocusOut>", lambda _: reader.tag_remove("focused", "1.0", "end"))
        self.guide_actions = bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(8, 0))
        self.guide_edit = ttk.Button(bar, command=self.edit_guide_field)
        self.guide_edit.pack(side="left")
        self.guide_open = ttk.Button(bar, command=self.open_guide_topic)
        self.guide_open.pack(side="right")
        self.guide_setup = ttk.Frame(right)
        self.guide_setup_links = []
        for tab in range(3):
            button = ttk.Button(self.guide_setup, command=lambda tab=tab: self.tabs.select(tab))
            self.guide_setup_links.append(button)
        right.bind("<Configure>", self.schedule_guide_height)
        reader.bind("<Configure>", self.guide_reader_resized)
        reader.bind("<Destroy>", self.cancel_guide_resize)

    def cancel_guide_resize(self, _event=None):
        if self.guide_resize_job is not None:
            self.guide_reader.after_cancel(self.guide_resize_job)
            self.guide_resize_job = None

    def guide_reader_resized(self, event):
        if event.width != self.guide_reader_width:
            self.guide_reader_width = event.width
            self.schedule_guide_height()

    def schedule_guide_height(self, _event=None):
        if self.guide_resize_job is None:
            self.guide_resize_job = self.guide_reader.after_idle(self.fit_guide_height)

    def fit_guide_height(self):
        self.guide_resize_job = None
        reader = self.guide_reader
        if reader.winfo_width() < 3 or self.guide_page.winfo_height() < 10:
            return
        line_height = tkfont.Font(root=reader, font=reader.cget("font")).metrics("linespace")
        usable = self.guide_page.winfo_height() - self.guide_box.winfo_y() - self.guide_actions.winfo_reqheight() - 36
        if self.guide_setup.winfo_manager():
            usable -= self.guide_setup.winfo_reqheight() + 12
        # Include heading spacing. Use display lines so wrapping tracks the actual window width.
        lines = (reader.count("1.0", "end", "displaylines") or (1,))[0]
        headings = len(reader.tag_ranges("heading")) // 2
        required = lines + (headings * 6 + line_height - 1) // line_height
        capacity = max(2, usable // max(1, line_height))
        if required > capacity and not self.guide_scroll.winfo_manager():
            self.guide_scroll.pack(side="right", fill="y", before=reader)
        elif required <= capacity and self.guide_scroll.winfo_manager():
            # Extra horizontal space can only reduce wrapping when the scrollbar disappears.
            self.guide_scroll.pack_forget()
        desired = max(2, min(required, capacity))
        if int(reader.cget("height")) != desired:
            reader.configure(height=desired)

    def show_phase_shortcuts(self, phase, topic):
        for button in self.guide_setup_links:
            button.pack_forget()
        self.guide_setup.pack_forget()
        if not phase or topic not in ("general", "overview", "why", "quests"):
            return
        gear = sum(bool(item) for item in self.setup.get("gear", {}).values())
        gems = len(self.setup.get("gems", []))
        nodes = len({str(ident) for path in self.setup.get("tree", {}).values() for ident in path})
        labels = ((gear, self.text("Ausrüstung", "Gear")), (gems, self.text("Fertigkeiten", "Skills")),
                  (nodes, self.text("Passivpunkte", "Passive nodes")))
        for button, (count, label) in zip(self.guide_setup_links, labels):
            if count:
                button.configure(text=f"{label} · {count} →")
                button.pack(side="left", padx=(0, 3))
        if gear or gems or nodes:
            self.guide_setup.pack(fill="x", pady=(8, 0))

    def phase_fields(self, default=None):
        name = simpledialog.askstring(self.text("Guide-Phase", "Guide phase"), self.text("Name der Phase", "Phase name"),
                                      initialvalue=((default or {}).get("names", {}).get(self.language)
                                                    or (default or {}).get("name", "")), parent=self.window)
        if not name or not name.strip():
            return None
        span = simpledialog.askstring(self.text("Guide-Phase", "Guide phase"),
                                      self.text("Stufenbereich (optional)", "Level range (optional)"),
                                      initialvalue=(default or {}).get("range", ""), parent=self.window)
        return (name.strip(), span.strip()) if span is not None else None

    def add_phase(self):
        phases = self.build["phases"]
        if len(phases) < 100 and (fields := self.phase_fields()):
            phases.append({"id": uuid4().hex, "name": fields[0], "range": fields[1], "setup": phase_setup(self.setup)})
            self.phase = len(phases) - 1
            self.remember_phase()
            self.refresh()

    def open_phase(self, _event=None):
        selected = self.phases.curselection()
        if selected and selected[0] != self.phase:
            self.phase_picker.current(selected[0] + 1)
            self.pick_phase()

    def rename_phase(self):
        if self.phase < 0:
            return
        phase = self.build["phases"][self.phase]
        if fields := self.phase_fields(phase):
            if phase.get("names"):
                phase["names"][self.language] = fields[0]
            else:
                phase["name"] = fields[0]
            if phase.get("range", "") != fields[1]:
                phase.pop("min_level", None)
                phase["range"] = fields[1]
            self.refresh()

    def remove_phase(self):
        if self.phase >= 0 and messagebox.askyesno(self.text("Phase entfernen", "Remove phase"),
                self.text("Diese Phase mit ihrem Setup und ihren Hinweisen entfernen?",
                          "Remove this phase with its setup and notes?"), parent=self.window):
            phases = self.build["phases"]
            phases.pop(self.phase)
            self.phase = min(self.phase, len(phases) - 1)
            self.remember_phase()
            self.refresh()

    def move_phase(self, offset):
        phases = self.build["phases"]
        target = self.phase + offset
        if self.phase >= 0 and 0 <= target < len(phases):
            phases[self.phase], phases[target] = phases[target], phases[self.phase]
            self.phase = target
            self.remember_phase()
            self.refresh()

    def refresh_phases(self):
        rows = [phase_label(row, self.language) for row in self.build["phases"]]
        self.replace_rows(self.phases, rows, max(0, self.phase))
        if self.phase < 0:
            self.phases.selection_clear(0, "end")
        self.phase_actions.configure(state="normal" if self.phase >= 0 else "disabled")
        self.phase_menu.entryconfigure(1, state="normal" if self.phase > 0 else "disabled")
        self.phase_menu.entryconfigure(2, state="normal" if self.phase < len(rows) - 1 else "disabled")
        self.select_guide_topic(self.guide_topic)

    def guide_excerpt(self, tab_index):
        if tab_index not in range(len(TAB_TOPICS)) or self.phase < 0:
            return ""
        fields = reader_fields(self.build, self.build["phases"][self.phase], TAB_TOPICS[tab_index],
                               self.text, self.language)
        value = next((field.value for field in fields if field.value), "")
        return "".join(label for label, _, _ in reference_parts(value)).split("\n", 1)[0]

    def show_guide_topic(self, tab_index):
        self.tabs.select(3)
        self.select_guide_topic(TAB_TOPICS[tab_index])

    def open_guide_topic(self):
        if self.guide_topic in TAB_TOPICS:
            self.tabs.select(TAB_TOPICS.index(self.guide_topic))

    def follow_guide_reference(self, event=None):
        reader = self.guide_reader
        index = f"@{event.x},{event.y}" if event else reader.tag_nextrange("focused", "1.0")
        if not event and index:
            index = index[0]
        if index:
            ref = next((self.guide_targets[tag] for tag in reader.tag_names(index) if tag in self.guide_targets), None)
            if ref:
                self.open_guide_target(ref.kind, ref.target)
        return "break"

    def guide_tooltip_at(self, x, y):
        """Resolve only visible glyphs, including when the pointer is beside a wrapped line."""
        reader = self.guide_reader
        if not reader.winfo_viewable():
            return None
        rx, ry = x - reader.winfo_rootx(), y - reader.winfo_rooty()
        if not (0 <= rx < reader.winfo_width() and 0 <= ry < reader.winfo_height()):
            return None
        if reader.winfo_containing(x, y) is not reader:
            return None
        index = reader.index(f"@{rx},{ry}")
        box = reader.bbox(index)
        if box and box[0] <= rx < box[0] + box[2] and box[1] <= ry < box[1] + box[3]:
            for tag in reader.tag_names(index):
                if tag in self.guide_tooltips:
                    return reader, tag, self.guide_tooltips[tag], None
        return None

    def step_guide_reference(self, step):
        reader = self.guide_reader
        current = reader.tag_nextrange("focused", "1.0")
        reader.tag_remove("focused", "1.0", "end")
        span = (reader.tag_nextrange("link", current[1] if current else "1.0") if step > 0 else
                reader.tag_prevrange("link", current[0] if current else "end"))
        if span:
            reader.tag_add("focused", *span)
            reader.see(span[0])
        else:
            neighbour = reader.tk_focusNext() if step > 0 else reader.tk_focusPrev()
            if neighbour:
                neighbour.focus_set()
        return "break"

    def select_guide_topic(self, topic):
        self.guide_topic = topic
        reader = self.guide_reader
        reader.configure(state="normal")
        reader.delete("1.0", "end")
        for tag in reader.tag_names():
            if tag.startswith(("ref-", "tip-")):
                reader.tag_delete(tag)
        for key, button in self.guide_buttons.items():
            selected = key == topic
            button.configure(bg=self.theme.selection_color if selected else self.theme.control,
                             fg=self.theme.selection_text if selected else self.theme.text,
                             activebackground=self.theme.selection_color, activeforeground=self.theme.selection_text)
        is_phase = self.phase >= 0
        phase = self.build["phases"][self.phase] if is_phase else {}
        title = self.build.get("name") if topic == "overview" else phase_label(phase, self.language)
        self.guide_title.configure(text=title or self.text("Aktuelles Setup", "Current setup"))
        self.guide_fields = reader_fields(self.build, phase, topic, self.text, self.language)
        links = guide_links(phase, self.setup, self.data, self.language, self.guide_fields)
        self.guide_links = links
        self.guide_targets = {}
        self.guide_tooltips = {}
        active_tags = {}
        tip_tags = {}

        def plain(label):
            tipper = getattr(self.app, "term_tips", None)
            start = reader.index("end-1c")
            reader.insert("end", label, ())
            for a, b, color in term_matches(label, ITEM_COLORS):
                tag = f"color-{color}"
                reader.tag_configure(tag, foreground=color)
                reader.tag_add(tag, f"{start}+{a}c", f"{start}+{b}c")
            for a, b in tipper.spans(label) if tipper else ():
                entry = tipper.lookup(label[a:b])
                if entry:
                    if entry not in tip_tags:
                        tag = tip_tags[entry] = f"tip-{len(tip_tags)}"
                        self.guide_tooltips[tag] = entry
                        reader.tag_configure(tag, underline=True)
                    reader.tag_add(tip_tags[entry], f"{start}+{a}c", f"{start}+{b}c")

        def insert(label, key=None):
            if key and key.startswith("gem:") and key not in links:
                ident = key[4:]
                entry = gem_entry(ident, self.language)
                if entry:
                    links[key] = GuideLink("gem", ident, entry[0])
            if key not in links:
                plain(label)
                return
            if key not in active_tags:
                tag = active_tags[key] = f"ref-{len(active_tags)}"
                ref = self.guide_targets[tag] = links[key]
                if ref.kind == "gem":
                    entry = gem_entry(ref.target, self.language)
                    if entry:
                        self.guide_tooltips[tag] = entry
                        reader.tag_configure(tag, foreground=gem_color(ref.target))
            reader.insert("end", label, ("link", active_tags[key]))

        visible = [field for field in self.guide_fields if field.value]
        if visible:
            for index, field in enumerate(visible):
                if index:
                    reader.insert("end", "\n\n")
                if len(visible) > 1 or topic == "overview":
                    role = field.path[1] if topic == "overview" else None
                    sign = {"strengths": "+  ", "weaknesses": "−  "}.get(role, "")
                    reader.insert("end", sign + field.heading + "\n", ("heading", role) if sign else ("heading",))
                for label, key in linked_segments(field.value, links, self.language):
                    insert(label, key)
        elif topic == "overview":
            reader.insert("end", self.text("Welche Idee steckt hinter dem Build? Ergänze hier seine Stärken und Schwächen.",
                                           "What makes the build work? Add its strengths and weaknesses here."))
        elif is_phase:
            reader.insert("end", self.text("Für diese Phase gibt es hier noch keinen Hinweis.",
                                           "There is no note for this part of the phase yet."))
        else:
            reader.insert("end", self.text("Wähle eine Phase oder erstelle eine aus deinem aktuellen Setup.",
                                           "Select a phase or create one from your current setup."))
        references = phase.get("gemReferences")
        extra = [(f"gem:{row.get('id')}", row.get("label")) for row in references if isinstance(row, dict)
                 and f"gem:{row.get('id')}" in links] if topic == "gems" and isinstance(references, list) else []
        if extra:
            reader.insert("end", "\n\n")
            reader.insert("end", self.text("Im Guide empfohlen", "Recommended in this guide") + "\n", "heading")
            for index, (key, hint) in enumerate(extra):
                if index:
                    reader.insert("end", "\n")
                insert(links[key].name, key)
                if isinstance(hint, str) and hint.strip():
                    for label, linked in linked_segments(f"  ·  {hint}", links, self.language):
                        insert(label, linked)
        reader.tag_raise("focused")
        reader.configure(state="disabled")
        self.guide_edit.configure(state="normal" if is_phase or topic == "overview" else "disabled",
                                  text=self.text("Hinweis bearbeiten", "Edit note") if visible else
                                       self.text("+ Hinweis", "+ Add note"))
        if topic in TAB_TOPICS:
            self.guide_open.configure(text=self.text(*{"gear": ("Inventar öffnen →", "Open inventory →"),
                "gems": ("Fertigkeiten öffnen →", "Open skills →"), "tree": ("Baum öffnen →", "Open tree →")}[topic]))
            self.guide_open.pack(side="right")
        else:
            self.guide_open.pack_forget()
        self.show_phase_shortcuts(phase, topic)
        self.schedule_guide_height()

    def save_phase_notes(self):
        # Edits are committed in the modal editor before the interface can change phase or save.
        pass

    def edit_guide_field(self):
        if self.phase < 0 and self.guide_topic != "overview":
            return
        dialog = tk.Toplevel(self.window)
        dialog.transient(self.window)
        dialog.title(self.text("Hinweis bearbeiten", "Edit note"))
        pane = ttk.Frame(dialog, padding=12)
        pane.pack(fill="both", expand=True)
        fields = self.guide_fields
        choice = ttk.Combobox(pane, values=[f"{i + 1} · {f.heading}" for i, f in enumerate(fields)], state="readonly")
        first = next((index for index, field in enumerate(fields) if field.value), 0)
        choice.current(first)
        if len(fields) > 1:
            choice.pack(fill="x", pady=(0, 6))
        advice = ttk.Label(pane)
        advice.pack(fill="x", pady=(0, 3))
        box = tk.Text(pane, width=55, height=9, wrap="word", undo=True, padx=7, pady=6)
        box.pack(fill="both", expand=True)
        box.tag_configure("ref", foreground=self.theme.accent, underline=True)
        bar = ttk.Frame(pane)
        bar.pack(fill="x", pady=(8, 4))
        links = self.guide_links
        keys = sorted(links, key=lambda key: links[key].name.casefold())
        picker = ttk.Combobox(bar, values=[links[k].name for k in keys], state="readonly", width=20)
        picker.set(self.text("Verweis wählen", "Choose reference"))
        picker.pack(side="left", fill="x", expand=True)
        tokens = {}
        drafts = [field.value for field in fields]
        active = first

        def insert_reference(at, label, key, raw):
            tag = f"token-{len(tokens)}"
            tokens[tag] = (label, key, raw)
            box.insert(at, label, ("ref", tag))

        def render():
            tokens.clear()
            box.delete("1.0", "end")
            field = fields[active]
            if field.path[0] == "editorial":
                lang = {"de": self.text("Deutsch", "German"), "en": self.text("Englisch", "English"),
                        "hybrid": "Hybrid"}[self.language]
                advice.configure(text=lang + " · " + self.text("Ein Hinweis pro Zeile", "One note per line"))
            else:
                advice.configure(text=self.text("Importierter Originaltext", "Imported original text"))
            for label, key, raw in reference_parts(drafts[active]):
                if raw:
                    insert_reference("end", label, key, raw)
                else:
                    box.insert("end", label, ())
            box.edit_reset()

        def content():
            result = []
            for kind, value, index in box.dump("1.0", "end-1c", text=True):
                tag = next((tag for tag in box.tag_names(index) if tag in tokens), "")
                if tag:
                    old_label, key, raw = tokens[tag]
                    value = raw if value == old_label else f"[[{quote(key, safe='')}|{quote(value, safe='')}]]"
                result.append(value)
            return "".join(result)

        def select(_event):
            nonlocal active
            drafts[active] = content()
            active = choice.current()
            render()

        def attach():
            if 0 <= picker.current() < len(keys):
                key = keys[picker.current()]
                label = links[key].name
                insert_reference("insert", label, key, f"[[{quote(key, safe='')}|{quote(label, safe='')}]]")
                box.focus_set()

        def apply():
            drafts[active] = content()
            for field, value in zip(fields, drafts):
                if field.path[0] == "editorial" and value != field.value:
                    rows = [row.strip() for row in value.splitlines() if row.strip()]
                    if len(rows) > LIMITS["lines"] or any(len(row) > LIMITS["line"] for row in rows):
                        maximum, length = LIMITS["lines"], LIMITS["line"]
                        messagebox.showerror(field.heading, self.text(
                            f"Pro Abschnitt sind bis zu {maximum} Hinweise mit je {length} Zeichen möglich.",
                            f"Each section accepts up to {maximum} notes of {length} characters each."), parent=dialog)
                        return
            for field, value in zip(fields, drafts):
                if value != field.value:
                    field.write(value)
            dialog.destroy()
            self.select_guide_topic(self.guide_topic)

        choice.bind("<<ComboboxSelected>>", select)
        ttk.Button(bar, text=self.text("Einfügen", "Insert"), command=attach).pack(side="left", padx=(5, 0))
        end = ttk.Frame(pane)
        end.pack(fill="x", pady=(4, 0))
        ttk.Button(end, text=self.text("Übernehmen", "Apply"), command=apply).pack(side="right")
        ttk.Button(end, text=self.text("Abbrechen", "Cancel"), command=dialog.destroy).pack(side="right", padx=5)
        self.apply_palette(pane)
        render()
        dialog.grab_set()
        box.focus_set()
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.bind("<Control-Return>", lambda _: apply())
