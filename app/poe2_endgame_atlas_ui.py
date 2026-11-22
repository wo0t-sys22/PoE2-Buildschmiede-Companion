"""Compact Tk guide for the bundled Endgame & Atlas data."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk
import webbrowser
from poe2_overlay_controls import FlowRow, ScrollArrows
from poe2_hud_icons import hud_icon
from poe2_language import area_label, ui_text
from poe2_r18_features import PALETTE, TIERS, hud_check_id, item_spans
from poe2_regex import LIMIT, query_length


def atlas_text(data, value, language):
    return data.get("localized_text", {}).get(language, {}).get(value, value)


class EndgamePanel(tk.Frame):
    def __init__(self, parent, path: Path, palette: dict, ui_font: str, title_font: str,
                 make_font=None, on_view_change=None, fit_height=None,
                 get_language=None, on_check=None, term_tips=None):
        super().__init__(parent, bg=palette["bg"], bd=0, highlightthickness=0)
        self.path = path
        self.palette = palette
        self.ui_font = ui_font
        self.title_font = title_font
        self.make_font = make_font or (lambda family, points, weight="normal": (family, points, weight))
        self.fit_job = None
        self.on_view_change = on_view_change
        self.fit_height = fit_height
        self.get_language = get_language or (lambda: "hybrid")
        self.on_check = on_check
        self.term_tips = term_tips
        self.boss_terms = []
        self.checklist = None
        self.rendered_language = None
        self.mode = "veteran"
        self.tab = "progression"
        self.encounter = None
        self.stage_index = 0
        self.slot_index = 0
        self.build_index = 0
        self.layer_index = 0
        self.craft_view = "steps"
        self.tablet_view = "presets"
        self.tablet_index = 0
        self.preset_index = 0
        self.regex_index = 0
        self.page = 0
        self.lower_tiers = False
        self.details = False
        self.farming_open = False
        self.data = None
        self.rendered_mode = None
        self._build_ui()

    def _build_ui(self):
        self.nav = FlowRow(self, bg=self.palette["bg"], distribute=True)
        self.nav.pack(fill="x", padx=7, pady=(7, 2))
        self.selectors = tk.Frame(self, bg=self.palette["bg"])
        self.selectors.pack(fill="x", padx=7, pady=(0, 5))
        display = tk.Frame(self, bg=self.palette["bg"])
        display.pack(fill="both", expand=True, padx=7, pady=(0, 4))
        self.text = tk.Text(
            display, bg=self.palette["bg"], fg=self.palette["text"], font=self.make_font(self.ui_font, 9),
            relief="flat", bd=0, highlightthickness=0, takefocus=False, wrap="word",
            width=1, height=1, padx=4, pady=2, spacing3=3, cursor="arrow",
        )
        self.text.tag_configure("heading", foreground=self.palette["gold"], font=self.make_font(self.title_font, 11, "bold"))
        self.text.tag_configure("value", foreground=self.palette["info"], font=self.make_font(self.ui_font, 9, "bold"))
        self.text.tag_configure("muted", foreground=self.palette["muted"], font=self.make_font(self.ui_font, 8))
        self.text.tag_configure("warning", foreground=self.palette["danger"])
        self.text.tag_configure("response", foreground=self.palette["success"], font=self.make_font(self.ui_font, 9, "bold"))
        self.text.tag_configure("decision", foreground=self.palette["gold"], font=self.make_font(self.ui_font, 9, "bold"))
        self.text.tag_configure("list", lmargin2=14)
        self.text.tag_configure("boss_term", underline=True)
        if self.term_tips:
            self.text.term_at_point = self._boss_term_at
        for kind, color in PALETTE.items():
            self.text.tag_configure("item_" + kind, foreground=color)
        self.text.bindtags((str(self.text), str(self.winfo_toplevel()), "all"))
        self.text.pack(side="left", fill="both", expand=True)
        self.scrollbar = ScrollArrows(display, self.text, self.palette["control"], self.palette["gold"])
        self.text.configure(yscrollcommand=self._scroll_extent, state="disabled")
        self.controls = tk.Frame(self, bg=self.palette["bg"])
        self.controls.pack(side="bottom", before=display, fill="x", padx=7, pady=(0, 5))

    def apply_theme(self, theme, *, surface, body_family, heading_family, control_family, info, success, danger):
        self.palette.update(edge=theme.edge, text=theme.text, control=theme.control, active=theme.active,
                            gold=theme.accent, info=info, success=success, danger=danger)
        self.ui_font = control_family
        self.title_font = heading_family
        treatment = theme.treatment
        self.text.configure(bg=surface, fg=theme.text,
                            highlightthickness=treatment.card_border, highlightbackground=theme.edge,
                            padx=10, pady=8, font=self.make_font(body_family, 9))
        self.text.tag_configure("heading", font=self.make_font(heading_family, 11, "bold"))
        for tag in ("value", "decision"):
            self.text.tag_configure(tag, font=self.make_font(body_family, 9, "bold"))
        self.text.tag_configure("muted", font=self.make_font(body_family, 8))
        for tag in ("heading", "decision"):
            self.text.tag_configure(tag, foreground=theme.accent)
        self.text.tag_configure("value", foreground=info)
        self.text.tag_configure("warning", foreground=danger)
        self.text.tag_configure("response", foreground=success, font=self.make_font(body_family, 9, "bold"))
        self.scrollbar.colors(theme.control, theme.accent)
        self.invalidate()

    def display(self, mode: str, checklist=None):
        checklist_changed = checklist != self.checklist
        self.checklist = checklist
        if mode != self.rendered_mode or self.get_language() != self.rendered_language:
            self.mode = mode
            self.render()
        elif checklist_changed:
            self.render(scroll=self.text.yview()[0])

    def _button(self, parent, label, command, active=False, disabled=False):
        if parent is self.controls:
            parent = self.control_buttons
        button = tk.Button(
            parent, text=self._text(label), command=command, bd=0, padx=7, pady=4, cursor="hand2",
            font=self.make_font(self.ui_font, 8, "bold"),
            fg=self.palette["gold"] if active else self.palette["text"],
            bg=self.palette.get("active", "#313032") if active else self.palette["control"],
            activebackground=self.palette.get("active", "#313032"), activeforeground=self.palette["gold"],
            disabledforeground=self.palette["muted"], highlightthickness=1,
            highlightbackground=self.palette["edge"],
            state="disabled" if disabled else "normal",
        )
        if isinstance(parent, FlowRow):
            parent.reflow()
        else:
            button.pack(side="left", padx=(0, 4))
        return button

    def _set(self, field, value):
        setattr(self, field, value)
        self.page = 0
        self.details = False
        self.farming_open = False
        self.render()

    def _choice_buttons(self, parent, field, choices):
        for value, label in choices:
            self._button(parent, label, lambda value=value: self._set(field, value), getattr(self, field) == value)

    def _dropdown(self, label, field, names, parent=None, *, index=None, on_change=None):
        parent = self.selectors if parent is None else parent
        cell = tk.Frame(parent, bg=self.palette["bg"])
        tk.Label(cell, text=self._text(label), anchor="w", fg=self.palette["muted"], bg=self.palette["bg"],
                 font=self.make_font(self.ui_font, 8)).pack(fill="x")
        box = ttk.Combobox(cell, values=[self._text(name) for name in names], width=14, state="readonly", style="Atlas.TCombobox",
                           font=self.make_font(self.ui_font, 9))
        box.current(getattr(self, field) if index is None else index)
        box.pack(fill="x")
        change = on_change or (lambda value: self._set(field, value))
        box.bind("<<ComboboxSelected>>", lambda event: change(box.current()))
        if isinstance(parent, FlowRow):
            parent.reflow()
        else:
            cell.pack(fill="x")

    def _text(self, value):
        return atlas_text(self.data or {}, value, self.get_language())

    def _line(self, value="", tag=None, *, task=None, label="", label_tag="decision", checkable=True):
        base_tag = tag or ()
        if label:
            self.text.insert("end", label + " · ", label_tag)
        start_index = self.text.index("end-1c") if self.tab == "boss" and self.term_tips else None
        if checkable and self.checklist is not None and self.tab != "boss" and value and tag != "heading":
            task = task or hud_check_id("atlas", self.tab, value)
            done = self.checklist["checked"].get(task, False)
            size = max(12, self.make_font(self.ui_font, 8).metrics("linespace"))
            icon = hud_icon(self.text, "checked" if done else "checkbox", size, self.palette["gold"])
            check = tk.Button(self.text, image=icon, command=lambda: self.on_check(task, not done),
                              bg=self.text.cget("bg"), activebackground=self.palette["active"],
                              bd=0, padx=0, pady=0, highlightthickness=0, cursor="hand2")
            check.icon = icon
            self.text.window_create("end-1c linestart", window=check, align="center", padx=2)
        value = self._text(value)
        if tag and tag.startswith("item_"):
            self.text.insert("end", value, base_tag)
        else:
            last = 0
            for start, end, role in item_spans(value):
                self.text.insert("end", value[last:start], base_tag)
                self.text.insert("end", value[start:end], f"item_{role}")
                last = end
            self.text.insert("end", value[last:], base_tag)
        self.text.insert("end", "\n", base_tag)
        if start_index and self.term_tips.enabled:
            for start, end in self.term_tips.spans(value):
                left = self.text.index(f"{start_index}+{start}c")
                right = self.text.index(f"{start_index}+{end}c")
                self.boss_terms.append((left, right, value[start:end]))
                self.text.tag_add("boss_term", left, right)
            if self.boss_terms:
                self.term_tips.register(self.text)

    def _boss_term_at(self, x, y):
        if not self.boss_terms:
            return None
        index = self.text.index(f"@{x},{y}")
        box = self.text.bbox(index)
        if box and box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]:
            return next((phrase for start, end, phrase in self.boss_terms
                         if self.text.compare(start, "<=", index) and self.text.compare(index, "<", end)), None)

    def _list(self, lines, ordered=False):
        for index, line in enumerate(lines, start=1):
            prefix = f"{index}. " if ordered else "•  "
            self._line(prefix + self._text(line), "list", task=hud_check_id("atlas", self.tab, prefix + line))

    def _toggle_details(self):
        self.details = not self.details
        self.render()

    def _detail_button(self, label):
        self._button(self.controls, "Back" if self.details else label, self._toggle_details, self.details)

    def _toggle_farming(self):
        self.farming_open = not self.farming_open
        self.render()

    def _farming(self, farming):
        self._line("Base farming & iLvl breakpoints", "heading")
        self._line(farming["rule"])
        for row in farming["breakpoints"]:
            self.text.insert("end", f'iLvl {row["min_ilvl"]} · ', "value")
            self._line(row["unlocks"])
            self._line(f'{self._text("Regular maps")} · {self._text(row["standard"])}', "muted", checkable=False)
            if row.get("irradiated"):
                self._line(f'{self._text("Irradiated")} · {self._text(row["irradiated"])}', "muted", checkable=False)
        self._line(farming["drop_note"], "muted")
        self._line(farming["early_note"], "muted")

    def _change_page(self, delta):
        self.page += delta
        self.render()

    def _pager(self, count, page_size):
        pages = (count + page_size - 1) // page_size
        if pages <= 1:
            return
        self._button(self.controls, "Previous", lambda: self._change_page(-1), disabled=self.page == 0)
        tk.Label(self.control_buttons, text=f'{self._text("Page")} {self.page + 1} / {pages}', fg=self.palette["muted"],
                 bg=self.palette["bg"], font=self.make_font(self.ui_font, 8))
        self.control_buttons.reflow()
        self._button(self.controls, "Next", lambda: self._change_page(1), disabled=self.page + 1 >= pages)

    def _website_sections(self, placement):
        language = self.get_language()
        for entry in self.data.get("website_sections", []):
            if entry["placement"] == placement:
                self._line(entry["title"][language], "heading")
                body = entry.get("compact", entry["body"]) if self.mode == "veteran" else entry["body"]
                for index, line in enumerate(body[language]):
                    self._line("•  " + line, "list", task=hud_check_id("atlas-reference", entry["id"], index))

    def _web_guide(self, anchor=""):
        language = self.get_language()
        url = f"https://buildschmiede.de/endgame-atlas/?sprache={language}{anchor}"
        self._button(self.controls, "Web guide ↗", lambda: webbrowser.open(url))

    def _progression(self):
        progression = self.data["progression"]
        stages = progression["stages"]
        self._dropdown("Waystone progression", "stage_index", [stage["label"] for stage in stages])
        stage = stages[self.stage_index]
        if self.farming_open:
            self._farming(progression["farming"])
            self._button(self.controls, "Back", self._toggle_farming, active=True)
            return

        if self.encounter:
            label = "Area boss guide" if self.get_language() == "en" else "Boss-Guide für dieses Gebiet"
            self._button(self.controls, label, lambda: self._set("tab", "boss"))

        if not self.details and self.stage_index == 0:
            self._website_sections("atlas-entry")
        self._website_sections("progression")
        quick = stage.get("quick")
        if self.details:
            self._website_sections("atlas-details")
            self._line("Atlas milestones & Map Device", "heading")
            self._list(stage["milestones"], ordered=True)
            slots = " · ".join(f'{row["waystone_mods"]} → {row["slots"]}' for row in progression["tablet_slots"])
            self._line(slots, "value", label=self._text("Waystone mods → Tablet slots"), checkable=False)
            self._line(progression["city_bonus"])
            self._line(progression["note"], "muted")
            if quick:
                self._list(stage[self.mode])
        else:
            for name, value in stage["checkpoints"].items():
                self._line(self._text(value), "value", label=self._text(name), checkable=False)
            if not quick:
                self._list(stage[self.mode])
            elif self.mode == "basis":
                self._list(quick["basis"])
            else:
                for label, tip in quick["veteran"].items():
                    self._line(tip, label=self._text(label), label_tag="warning" if label == "Reroll" else "decision")
            if quick:
                self._line(quick["farm"], label=self._text("Farm"), label_tag="value")
            if progression.get("farming"):
                self._button(self.controls, "Base farming & iLvl", self._toggle_farming)
        self._detail_button("Atlas milestones & Map Device")
        self._web_guide()

    def _toggle_tiers(self):
        self._set("lower_tiers", not self.lower_tiers)

    def _crafting(self, affix_only=False):
        self._web_guide("#guide-crafting")
        if not affix_only:
            self._website_sections("crafting")
        data = self.data["crafting"]
        if not affix_only:
            nav = FlowRow(self.selectors, bg=self.palette["bg"])
            nav.pack(fill="x")
            self._choice_buttons(nav, "craft_view", [
                ("steps", "Crafting Steps"), ("layers", "Special Layers"),
            ])
        fields = FlowRow(self.selectors, bg=self.palette["bg"])
        fields.pack(fill="x", pady=(5, 0))
        if not affix_only and self.craft_view == "layers":
            layers = data["special_layers"]
            self._dropdown("Crafting layer", "layer_index", [item["label"] for item in layers], parent=fields)
            layer = layers[self.layer_index]
            self._line(layer["label"], "heading")
            self._line(layer[self.mode])
            if self.details:
                for example in layer["examples"]:
                    self._line(example["label"], "value")
                    self._line(example["text"])
            self._detail_button("Examples & eligible items")
            return
        slots, builds = data["slots"], data["builds"]
        self._dropdown("Item slot", "slot_index", [item["label"] for item in slots], parent=fields)
        self._dropdown("Build", "build_index", ["All builds"] + [item["label"] for item in builds], parent=fields)
        slot = slots[self.slot_index]
        if not affix_only and self.craft_view == "steps":
            self._line(f'{self._text(slot["label"])} · {self._text("Crafting Steps")}', "heading")
            self._list(slot[self.mode + "_craft"], ordered=True)
            return
        build = builds[self.build_index - 1] if self.build_index else None
        groups = set(build.get("affix_groups", [build["id"]])) if build else set()
        rows = []
        for mod in data["affixes"]:
            if slot["id"] not in mod["slots"] or groups and mod["builds"] and not groups.intersection(mod["builds"]):
                continue
            for group in TIERS.get(mod["id"], []):
                rows.append((mod, group))
        self._website_sections("affixes")
        self._line(data["tier_note"], "muted", checkable=False)
        if build:
            self._line(build["priorities"], "muted")
        if not rows:
            self._line("No curated base affixes for this selection.")
        for mod, group in rows[self.page * 3:(self.page + 1) * 3]:
            self._line(f'{self._text(mod["label"])} · {self._text(mod["side"])}', "item_mod", checkable=False)
            self._line(" / ".join(self._text(source["label"]) for source in group["sources"]) + (
                " · " + self._text(group["restriction"]) if group.get("restriction") else ""), "muted", checkable=False)
            for tier in (group["rows"] if self.lower_tiers else group["rows"][:1]):
                game = f'T{tier["game_tier"]}' if tier.get("game_tier") else self._text("Unverified")
                self._line(f'#{tier["rank"]} · {self._text("In-game tier")} {game} · iLvl {tier["ilvl"]}', "muted", checkable=False)
                self._line(tier["roll"], "item_mod", checkable=False)
            if group.get("count", 3) in (1, 2):
                self._line(f'{group["count"]} {self._text("tiers in pool")}', "muted", checkable=False)
        self._button(self.controls, "Top 3", self._toggle_tiers, self.lower_tiers)
        self._pager(len(rows), 3)

    def _copy(self, pattern, button):
        try:
            self.clipboard_clear()
            self.clipboard_append(pattern)
            button.configure(text=self._text("Copied!"), fg=self.palette["success"])
        except tk.TclError:
            button.configure(text=self._text("Copy failed"), fg=self.palette["danger"])
        self.after(1600, lambda: button.configure(text=self._text("Copy"), fg=self.palette["text"]) if button.winfo_exists() else None)

    def _regexes(self, data):
        entries = data["regexes"]
        self._dropdown("Farming goal", "regex_index", [item["label"] for item in entries])
        item = entries[self.regex_index]
        german = self.get_language() == "de"
        pattern = item.get("pattern_de", "") if german else item["pattern"]
        self._line(item["label"], "heading")
        self._line(item["tooltip"], "warning" if item.get("danger") else None, checkable=False)
        self._line("German game client" if german else "English game client", "muted", checkable=False)
        self._line(pattern, "value", checkable=False)
        self._line("Copy a search and paste it into the stash. Read the full modifier lines before opening a map.", checkable=False)
        button = self._button(self.controls, "Copy", lambda: self._copy(pattern, button),
                              disabled=not pattern or query_length(pattern) > LIMIT)
        self._web_guide("#farming-regex")

    def _tablets(self):
        data = self.data["tablets"]
        nav = FlowRow(self.selectors, bg=self.palette["bg"])
        nav.pack(fill="x")
        self._choice_buttons(nav, "tablet_view", [
            ("presets", "Presets"), ("rolls", "Tablet Affixes"), ("regex", "Stash RegEx"),
        ])
        if self.tablet_view == "regex":
            self._regexes(data)
            return
        self._web_guide("#farming-regex")
        fields = FlowRow(self.selectors, bg=self.palette["bg"])
        fields.pack(fill="x", pady=(5, 0))
        if self.tablet_view == "rolls":
            types = data["types"]
            self._dropdown("Tablet type", "tablet_index", [item["label"] for item in types], parent=fields)
            tablet = types[self.tablet_index]
            pool = next((item for item in types if item["id"] == tablet.get("shared_type")), tablet)
            self._line(tablet["tip"], "muted")
            for mod in pool["affixes"][self.page * 4:(self.page + 1) * 4]:
                self._line(mod["roll"], "value", label=self._text(mod["rank"]), checkable=False)
                self._line(f'{self._text(mod["side"])} · Max. {mod["max_roll"]}', "muted", checkable=False)
                if mod["note"]:
                    self._line(mod["note"], "muted")
            self._pager(len(pool["affixes"]), 4)
            return
        presets = data["presets"]
        self._dropdown("Farming preset", "preset_index", [item["label"] for item in presets], parent=fields)
        if self.details:
            self._line("Tablet crafting", "heading")
            self._list(data["crafting"][self.mode], ordered=True)
            self._line(data["crafting"]["caveat"], "warning")
        else:
            self._website_sections("tablets")
            preset = presets[self.preset_index]
            self._line(preset["setup"], "value")
            self._list(preset[self.mode])
            all_affixes = {mod["id"]: mod for item in data["types"] for mod in item["affixes"]}
            summary = " · ".join(self._text(all_affixes[id_]["label"]) for id_ in preset["priorities"])
            self._line(summary, "muted", checkable=False)
        self._detail_button("Tablet crafting")

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") == 1 and all(key in data for key in ("progression", "crafting", "tablets")):
                self.data = data
        except (OSError, ValueError, AttributeError):
            self.data = None

    def invalidate(self):
        self.rendered_mode = None

    def set_encounter(self, encounter):
        if encounter != self.encounter:
            self.encounter = encounter
            if not encounter and self.tab == "boss":
                self.tab = "progression"
            self.invalidate()

    def _boss(self):
        if not self.encounter:
            self.tab = "progression"
            self._progression()
            return
        language = self.get_language()
        label = "← Back to Atlas" if language == "en" else "← Zurück zum Atlas"
        self._button(self.selectors, label, lambda: self._set("tab", "progression"))
        translation = self.encounter.get("de", {}) if language == "hybrid" else self.encounter.get(language, {})
        if language == "hybrid":
            translation = {key: value for key, value in translation.items() if key != "name"}
        boss = {**self.encounter, **translation}
        self._line(boss["name"], "heading")
        self._line(ui_text("Angriffe & Phasen", language), "warning")
        self._line(boss["cue"], label=ui_text("Signal", language))
        self._line(boss["response"], label=ui_text("Reaktion", language), label_tag="response")
        if boss.get("window"):
            self._line(boss["window"], label=ui_text("Konter", language), label_tag="response")
        self._line()
        self._line(ui_text("Fundort", language), "heading")
        for zone in boss["areas"]:
            url = boss.get("areaUrl")
            if url:
                if language == "de":
                    url = url.replace("poe2db.tw/us/", "poe2db.tw/de/")
                self._button(self.controls, area_label(zone, language) + " ↗",
                             lambda url=url: webbrowser.open(url)).configure(fg=self.palette["gold"])
            else:
                self._line(area_label(zone, language))
        self._button(self.controls, ui_text("Quellen", language),
                     lambda: webbrowser.open(boss["source"])).configure(fg=self.palette["muted"])

    def _scroll_extent(self, first, last):
        self.scrollbar.extent(first, last)
        if self.on_view_change:
            self.on_view_change()
        if self.fit_job is None:
            self.fit_job = self.after_idle(self._fit)

    def _fit(self):
        self.fit_job = None
        if not self.winfo_ismapped():
            return
        if self.fit_height:
            pixels = self.text.count("1.0", "end", "ypixels")
            if pixels:
                # Measure the controls independently of the current viewport height. During a
                # resize, the toplevel and its packed children can report different layout passes.
                chrome = self.winfo_rooty() - self.winfo_toplevel().winfo_rooty()
                controls = (self.nav, self.selectors, self.controls)
                chrome += sum(widget.winfo_reqheight() for widget in controls)
                for widget in (*controls, self.text.master):
                    padding = widget.pack_info()["pady"]
                    chrome += sum(padding) if isinstance(padding, tuple) else 2 * int(padding)
                text_padding = int(self.text.cget("pady")) + int(self.text.cget("highlightthickness"))
                self.fit_height(chrome + pixels[0] + 2 * text_padding + 5)

    def render(self, *, scroll=0):
        self.rendered_mode = self.mode
        self.rendered_language = self.get_language()
        for parent in (self.nav, self.selectors, self.controls):
            for child in parent.winfo_children():
                child.destroy()
        self.control_buttons = FlowRow(self.controls, bg=self.palette["bg"])
        self.control_buttons.pack(fill="x")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.boss_terms.clear()
        if self.data is None:
            self._load()
        if self.data is None:
            self._line("Atlas data could not be loaded.", "warning")
            self._button(self.controls, "Retry", self.render)
        else:
            views = [
                ("progression", "✥"), ("crafting", "⚒"),
                ("tablets", "▤"),
            ]
            if self.data.get("website_navigation"):
                views = [(entry["id"], entry["title"][self.rendered_language])
                         for entry in self.data["website_navigation"]]
            self._choice_buttons(self.nav, "tab", views)
            {
                "progression": self._progression, "crafting": self._crafting,
                "affixes": lambda: self._crafting(affix_only=True),
                "tablets": self._tablets, "boss": self._boss,
            }[self.tab]()
        self.text.delete("end-2c", "end-1c")
        self.text.configure(state="disabled")
        self.text.yview_moveto(scroll)
