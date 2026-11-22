"""Campaign boss and build views for the standalone overlay."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from shutil import which
import tkinter as tk
from tkinter import ttk
import webbrowser

from poe2_boss_clips import clip_id
from poe2_build_editorial import BUILD_TOPICS, PHASE_TOPICS, editorial_lines, phase_label, stage_view
from poe2_build_loadout import stage_loadout
from poe2_build_loadout_ui import render_gems, render_items, render_tree_link
from poe2_build_terms import equipped_gem_ids
from poe2_build_tree_ui import render_passive_list, render_passive_tree
from poe2_clip_player import ClipPreview
from poe2_gif import AnimatedGif
from poe2_language import BOSS_LANGUAGES, area_label, boss_text, display_label, guide_edit, ui_text
from poe2_shared_content import project
from poe2_overlay_controls import FlowRow
from poe2_r18_features import GUIDE, hud_check_id
from poe2_website_content import BUILD_PLANNER_URL


GUIDE_IMAGES = Path(__file__).resolve().parent / "web" / "images"


def load_companion(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") == 2 and isinstance(data["bosses"], list):
            return project(path.name, data)
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return {}


class CompanionPanel:
    def __init__(self, overlay, data):
        self.overlay = overlay
        self.data = data
        self.boss_id = ""
        self.build_id = ""
        self.stage_id = ""
        self.expanded = False
        self.context = None
        self.card_folds = {}
        self.gear_selection = {}
        self.visible_animations = set()

    def bosses_here(self, zone):
        key = self.overlay.zone_key(zone)
        return [
            boss for boss in self.data.get("bosses", [])
            if key and key in [self.overlay.zone_key(name) for name in [boss["zone"], *boss.get("aliases", [])]]
        ]

    def _row(self, parent, text, *, tone="text", points=11, marker=False, manual_colors=None, task=None):
        if text:
            return self.overlay.pack_task(parent, ui_text(text, self.overlay.app.language), task, tone=tone,
                                             points=points, padding=3, marker=marker,
                                             body_color=self.overlay.app.theme.text if marker else None,
                                             manual_colors=manual_colors)

    def _card(self, parent, context, key, title, *, tone="gold", closed=False, pinned=False, header_action=None):
        title = ui_text(title, self.overlay.app.language)
        header, body = self.overlay.guide_card(parent, tone, header_action=header_action)
        if pinned:
            header.configure(text=title, cursor="", state="disabled", disabledforeground=header.cget("fg"))
            return body
        identity = (*context, key)

        def set_fold(folded):
            header.configure(text=("▸ " if folded else "▾ ") + title, command=lambda: toggle(folded))
            if folded:
                body.pack_forget()
            else:
                body.pack(fill="x")

        def toggle(folded):
            self.card_folds[identity] = not folded
            set_fold(not folded)
            self.overlay._refit_route()
            self.overlay._schedule_targets()

        set_fold(self.card_folds.get(identity, closed))
        return body

    def _source_card(self, parent, context, sources):
        available = [code for code in sources if code in self.data["sources"]]
        if available:
            body = self._card(parent, context, "sources", "Quellen", tone="gameplay_title", closed=True)
            footer = FlowRow(body, bg=body.guide_card_color)
            footer.pack(fill="x")
            self._sources(footer, available)

    def _sources(self, parent, sources):
        for code in sources:
            source = self.data["sources"].get(code)
            if source:
                self.overlay.small_button(parent, source["label"], lambda url=source["url"]: webbrowser.open(url))
        parent.reflow()

    def _controls(self, parent, values, current, on_change, *, gap=6):
        options = ttk.Combobox(
            parent, values=values, state="readonly", width=18,
            font=self.overlay.ui_font(9), style="Atlas.TCombobox",
        )
        options.current(current)
        options.pack(fill="x", pady=(0, gap))
        options.bind("<<ComboboxSelected>>", lambda event: on_change(options.current()))

    def _toggle(self, parent):
        label = "Kurzansicht" if self.expanded else "Details anzeigen"
        self.overlay.small_button(parent, ui_text(label, self.overlay.app.language), self._flip).pack(anchor="w", pady=(4, 0))

    def _attack_animation(self, parent, filename, title):
        path = GUIDE_IMAGES / filename
        if not path.is_file():
            logging.warning("Boss-Animation fehlt: %s", filename)
            return
        english = self.overlay.app.language == "en"
        show_label = "Show clip" if english else "Clip einblenden"
        hide_label = "Hide clip" if english else "Clip ausblenden"
        zoom_label = "Enlarge" if english else "Vergrößern"
        controls = FlowRow(parent, bg=parent.guide_card_color)
        controls.pack(fill="x", padx=4, pady=(3, 2))
        clip = None

        def preview():
            nonlocal clip
            if clip is None:
                try:
                    # Fill the card width; clips are 480 px wide, so this stretches by at most 1.5.
                    clip = AnimatedGif(parent, path, background=parent.guide_card_color, max_stretch=1.5)
                except (OSError, ValueError, tk.TclError) as error:
                    self.visible_animations.discard(filename)
                    logging.warning("Boss-Animation %s konnte nicht geladen werden: %s", filename, error)
                    self.overlay.flash("Could not load the clip." if english else "Clip konnte nicht geladen werden.")
            return clip

        def show_clip():
            if image := preview():
                image.pack(after=controls, fill="x", padx=4, pady=(2, 4))
                self.visible_animations.add(filename)
                toggle_button.configure(text=hide_label)

        def enlarge():
            if image := preview():
                self.overlay.open_gif_viewer(image, title)

        def toggle_clip():
            if filename in self.visible_animations:
                self.visible_animations.remove(filename)
                clip.pack_forget()
                toggle_button.configure(text=show_label)
            else:
                show_clip()
            controls.reflow()
            self.overlay._refit_route()
            self.overlay._schedule_targets()

        toggle_button = self.overlay.small_button(controls, show_label, toggle_clip)
        self.overlay.small_button(controls, zoom_label, enlarge)
        if filename in self.visible_animations:
            show_clip()
        controls.reflow()

    def _video_actions(self, parent, boss, attack):
        key = clip_id(boss, attack)
        if not key:
            return
        app = self.overlay.app
        if not hasattr(app, "boss_clips"):
            return
        store = app.boss_clips
        item = store.catalogue.get(key)
        file = store.playable(key)
        if not file and attack.get("pilot_video"):
            candidate = GUIDE_IMAGES / attack["pilot_video"]
            file = candidate if candidate.is_file() else None
        en = app.language == "en"
        if file:
            controls = FlowRow(parent, bg=parent.guide_card_color)
            controls.pack(fill="x", padx=4, pady=(3, 2))

            def play():
                if not webbrowser.open(file.resolve().as_uri()):
                    self.overlay.flash("Could not open the MP4." if en else "MP4 konnte nicht geöffnet werden.")

            if executable := which("ffmpeg"):
                preview = None
                play_label = "Play in HUD" if en else "Im HUD abspielen"
                stop_label = "Stop preview" if en else "Wiedergabe stoppen"

                def toggle_preview():
                    nonlocal preview
                    if preview is not None:
                        preview.destroy()
                        preview = None
                        preview_button.configure(text=play_label)
                    else:
                        try:
                            width = min(1280, max(2, parent.winfo_width() - 8))
                            preview = ClipPreview(parent, executable, file, width, parent.guide_card_color)
                        except OSError:
                            play()
                            return
                        preview.pack(fill="x", after=controls, padx=4, pady=(0, 6))
                        preview.bind("<Unmap>", lambda event: preview.destroy() if preview is not None else None, add="+")
                        preview.bind("<Destroy>", lambda event: reset_preview(), add="+")
                        preview_button.configure(text=stop_label)
                    self.overlay._refit_route()
                    self.overlay._schedule_targets()

                def reset_preview():
                    nonlocal preview
                    preview = None
                    if preview_button.winfo_exists():
                        preview_button.configure(text=play_label)

                preview_button = self.overlay.small_button(controls, play_label, toggle_preview)
            self.overlay.small_button(controls, "Open in browser" if en else "Im Browser öffnen", play)
            controls.reflow()
        elif item and self.overlay.allows("endgame"):
            def download():
                self.overlay.flash("Downloading clip …" if en else "Clip wird geladen …")
                app.run_clip_job(lambda: store.download([item]), lambda ok, _:
                                 self.overlay.flash(
                                     ("Clip ready" if en else "Clip bereit") if ok else
                                     ("Download failed" if en else "Download fehlgeschlagen")))

            label = "Download clip" if en else "Clip herunterladen"
            self.overlay.small_button(parent, label, download).pack(anchor="e", padx=4, pady=(0, 6))

    def _flip(self):
        self.expanded = not self.expanded
        self.overlay.refresh_guide()

    def render(self, parent, section, mode, level):
        if not self.data:
            self._row(parent, "Guide-Daten konnten nicht geladen werden.")
            return
        context = (section, self.boss_id) if section == "boss" else (section,)
        if self.context != context:
            self.context = context
            self.expanded = False
        if section == "boss":
            self._render_boss(parent, mode)
        else:
            self._render_build(parent, mode, level)

    def _render_boss(self, parent, mode):
        language = self.overlay.app.language
        tr = lambda text: ui_text(text, language)
        boss = next((row for row in self.data["bosses"] if row["id"] == self.boss_id), None)
        if boss is None:
            self._row(parent, "This boss guide is unavailable." if language == "en" else
                      "Dieser Boss-Guide ist nicht verfügbar.", tone="muted")
            return
        boss = boss_text(boss, language)
        kind = tr("Pflichtboss") if boss["required"] else tr("Optionaler Boss")
        context = ("boss", boss["id"])
        boss_tone = "danger" if self.overlay.app.card_accents in {"headings", "both"} else "text"
        self._row(parent, "⚔ BOSS · " + boss["name"], tone=boss_tone, points=15)
        self._row(parent, kind, tone="muted", points=10)
        if language != "hybrid" and language not in BOSS_LANGUAGES.get(boss["id"], {}):
            self._row(parent, tr("Hybridtext · Übersetzung ausstehend"), tone="muted", points=9)

        terms = self.overlay.route_term_colors([boss])

        def line(parent, path, original, *, label="", role="quest", **options):
            edit = guide_edit("bossEdits", boss["id"], *path)
            text = edit.get(language, original)
            if text:
                self.overlay.pack_message(parent, text, lead=tr(label) if label else "", lead_tone=role,
                                          term_colors=terms, manual_colors=self.overlay.editor_colors(edit),
                                          **options)

        if mode == "basis" or self.expanded:
            def has_field(key):
                return bool(guide_edit("bossEdits", boss["id"], key).get(language, boss.get(key)))

            if has_field("prep"):
                body = self._card(parent, context, "prep", "Vor dem Kampf", tone="gameplay_title")
                line(body, ("prep",), boss.get("prep"))
            if has_field("plan") or has_field("window"):
                body = self._card(parent, context, "plan", "Kampftaktik", tone="info")
                line(body, ("plan",), boss.get("plan"))
                line(body, ("window",), boss.get("window"), label="Konter", role="success")
            if boss.get("attacks"):
                body = self._card(parent, context, "attacks", "Angriffe & Phasen", tone="danger")
                phase = None
                for index, attack in enumerate(boss["attacks"]):
                    if attack.get("phase") != phase:
                        phase = attack.get("phase")
                        if phase:
                            self._row(body, phase, tone="quest")
                    line(body, ("attacks", index, "name"), attack["name"], tone="danger", padding=5)
                    line(body, ("attacks", index, "tell"), attack["tell"], label="Signal")
                    line(body, ("attacks", index, "answer"), attack["answer"],
                         label="Reaktion", role="success")
                    if filename := attack.get("animation"):
                        self._attack_animation(body, filename, attack["name"])
                    else:
                        self._video_actions(body, boss, attack)
        else:
            body = self._card(parent, context, "quick", "Kampf auf einen Blick", tone="info")
            if boss.get("compactSteps"):
                for index, step in enumerate(boss["compactSteps"]):
                    line(body, ("compactSteps", index), step, marker=True)
            else:
                line(body, ("quick",), boss.get("quick"), marker=True)
        if mode == "veteran":
            self._toggle(parent)
        kind = boss.get("rewardKind", "reward")
        title = {"none": "Fundort", "progress": "Fundort & Fortschritt", "nearby": "Fundort"}.get(kind, "Fundort & Belohnung")
        body = self._card(parent, context, "reward", title, tone="quest")
        location = area_label(boss["zone"], language)
        if self.overlay.section_available("lookup"):
            link = self.overlay.small_button(body, location + "  →", lambda: self.overlay.show_boss_area(boss))
            link.configure(anchor="w")
            link.pack(anchor="w", padx=4, pady=(3, 4))
        else:
            self._row(body, location)
        labels = {"drop": "Beute", "quest": "Questbelohnung", "progress": "Fortschritt", "nearby": "In der Nähe"}
        if kind != "none":
            line(body, ("rewardText",), boss.get("rewardText") or boss.get("reward"), label=labels.get(kind, "Belohnung"))
        line(body, ("afterFight",), boss.get("afterFight"), label="Nach dem Sieg")
        if mode == "basis" or self.expanded:
            self._source_card(parent, context, boss.get("sources", []))

    def available_builds(self):
        builds = self.data.get("builds", [])
        if self.overlay.allows("campaign_tools"):
            return builds
        imported = self.overlay.app.build_import_store.plans
        return [build for build in builds if build["id"] in imported]

    def current_build(self, builds=None):
        if builds is None:
            builds = self.available_builds()
        return next((build for build in builds if build["id"] == self.overlay.app.build_id),
                    builds[0] if builds else None)

    @staticmethod
    def auto_stage(build, level):
        stages = build["stages"]
        eligible = (row for row in reversed(stages) if row["min_level"] <= min(level, 100))
        return max(eligible, key=lambda row: row["min_level"], default=min(stages, key=lambda row: row["min_level"]))

    def stage_for_level(self, build, level):
        stages = build["stages"]
        if self.build_id == build["id"] and self.stage_id:
            selected = next((row for row in stages if row["id"] == self.stage_id), None)
            if selected is not None:
                return selected
        return self.auto_stage(build, level)

    def _set_overview_hidden(self, build_id, hidden):
        hidden_ids = set(self.overlay.app.prefs.get("hidden_build_overviews", ()))
        if hidden:
            hidden_ids.add(build_id)
        else:
            hidden_ids.discard(build_id)
            self.card_folds[("build", build_id, "overview")] = False
        self.overlay.app.save_preferences(hidden_build_overviews=sorted(hidden_ids))
        self.overlay.refresh_guide()

    def _build_overview(self, parent, context, build, language):
        parts = {key: editorial_lines(build, key, language) for key in BUILD_TOPICS}
        if not any(parts.values()):
            return
        english = language == "en"
        action = None
        if context[0] == "build":
            label = "Hide" if english else "Ausblenden"
            action = (label, label, lambda: self._set_overview_hidden(build["id"], True))
        body = self._card(parent, context, "overview", "Build overview" if english else "Build-Überblick",
                          tone="info", closed=True, header_action=action)
        for line in parts["overview"]:
            self._row(body, line)
        for key, glyph, tone in (("strengths", "+", "success"), ("weaknesses", "−", "danger")):
            if not parts[key]:
                continue
            group = tk.Frame(body, bg=body.guide_card_color)
            group.pack(fill="x", padx=self.overlay.layout.px(4), pady=(self.overlay.layout.px(5), 0))
            tk.Frame(group, bg=self.overlay.divider_color, width=self.overlay.layout.px(2)).pack(side="left", fill="y")
            content = tk.Frame(group, bg=body.guide_card_color)
            content.guide_card_color = body.guide_card_color
            content.pack(side="left", fill="x", expand=True, padx=self.overlay.layout.px(3))
            self._row(content, f"{glyph}  {BUILD_TOPICS[key][english]}", tone=tone)
            for line in parts[key]:
                self._row(content, line)

    def open_planner_website(self):
        window = self.overlay
        try:
            if webbrowser.open(BUILD_PLANNER_URL):
                return
        except webbrowser.Error:
            pass
        window.flash("Could not open the browser." if window.app.language == "en"
                     else "Der Browser konnte nicht geöffnet werden.")

    def planner_website_button(self, parent):
        window = self.overlay
        label = "Open web planner ↗" if window.app.language == "en" else "Web-Planer öffnen ↗"
        button = window.small_button(parent, label, self.open_planner_website)
        button.configure(fg=window.theme.accent, highlightbackground=window.theme.accent)
        return button

    def _render_build(self, parent, mode, level):
        builds = self.available_builds()
        build = self.current_build(builds)
        if not build:
            self._row(parent, "Build-Daten konnten nicht geladen werden.")
            return
        if self.build_id != build["id"]:
            self.build_id = build["id"]
            self.stage_id = ""
            self.expanded = False
        stages = build["stages"]
        if self.stage_id and not any(row["id"] == self.stage_id for row in stages):
            self.stage_id = ""
        selected = self.stage_for_level(build, level)
        language = self.overlay.app.language
        english = language == "en"
        stage = stage_view(selected, language, keep_references=True)
        self.overlay.build_reference_context = (build["id"], stage["id"])
        self.overlay.build_gem_ids = equipped_gem_ids(stage)
        gap = self.overlay.layout.px(3)
        build_labels = [" · ".join(filter(None, (row["name"], row.get("author")))) for row in builds]
        hidden_overview = build["id"] in self.overlay.app.prefs.get("hidden_build_overviews", ())
        picker = parent
        if hidden_overview and any(editorial_lines(build, key, language) for key in BUILD_TOPICS):
            picker = tk.Frame(parent, bg=self.overlay.hud_bg)
            picker.pack(fill="x")
            restore = self.overlay.small_button(picker, "Show overview" if english else "Überblick einblenden",
                                                lambda: self._set_overview_hidden(build["id"], False))
            restore.pack(side="right", padx=(gap, 0), pady=(0, gap))
        self._controls(picker, build_labels, builds.index(build),
                       lambda index: self.overlay.app.select_build(builds[index]["id"]), gap=gap)
        if not hidden_overview:
            self._build_overview(parent, ("build", build["id"]), build, language)
        automatic = self.auto_stage(build, level)
        auto_mode = "Auto" if automatic["min_level"] <= min(level, 100) else ("Preview" if english else "Vorschau")
        auto_label = phase_label(automatic, language)
        self._controls(parent, [f"{auto_mode} · {auto_label}", *(phase_label(row, language) for row in stages)],
                       0 if not self.stage_id else stages.index(selected) + 1,
                       lambda index: self._pick_stage(stages[index - 1]["id"] if index else ""), gap=gap)
        if self.overlay.allows("campaign_tools"):
            self.planner_website_button(parent).pack(anchor="w", pady=(0, gap))
        context = ("build", build["id"], stage["id"])
        compact = mode == "veteran"
        quick = stage.get("quick")
        craft = stage.get("craft", [])
        next_step = stage.get("next") or (craft[0] if craft else None)
        if next_step:
            action_key = "quick" if next_step == quick else "next"
            body = self._card(parent, context, action_key, "Als Nächstes", tone="success", pinned=True)
            self._row(body, next_step, marker=True, task=hud_check_id(*context, action_key))
            for index, line in enumerate(stage["nextSteps"][1:], 1):
                self._row(body, line, marker=True, task=hud_check_id(*context, action_key, index))
        playstyle = [line for line in stage["playstyle"] if line != next_step]
        if playstyle:
            body = self._card(parent, context, "quick", "Spielweise", closed=compact and bool(next_step))
            for line in playstyle:
                self._row(body, line)
        for key, tone in (("why", "info"), ("quests", "quest")):
            if stage[key]:
                body = self._card(parent, context, key, PHASE_TOPICS[key][english], tone=tone, closed=True)
                for index, line in enumerate(stage[key]):
                    self._row(body, line, marker=key == "quests",
                              task=hud_check_id(*context, key, index) if key == "quests" else None)

        upgrades = [row for row in GUIDE.get("upgrades", [])
                    if row["scope"] == build["id"] and row.get("stage") == stage["id"]]
        loadout = stage_loadout(stage, language)
        sections = (
            ("skills", ("Fertigkeiten & Supports", "Skills & Supports", "Skills & supports"), loadout.gems),
            ("craft", ("Ausrüstung & Crafting", "Gear & Crafting", "Gear & crafting"), loadout.items),
            ("passives", ("Passivbaum & Aszendenz", "Passives & Ascendancy", "Passives & ascendancy"), loadout.passives),
        )
        section_tones = {"skills": "gem", "craft": "quest", "passives": "optional"}
        for key, labels, structured in sections:
            lines = list(dict.fromkeys(stage.get(key, [])))
            tree_url = loadout.tree_url if key == "passives" else ""
            if key == "craft":
                lines = [line for line in lines if line != next_step]
            if lines or structured or tree_url or (key == "craft" and upgrades):
                body = self._build_loadout_card(parent, context, key, display_label(labels, language),
                                                section_tones[key], compact, structured, tree_url, stage.get("passiveSetup"))
                for line in lines:
                    self._row(body, line)
                if key == "craft":
                    for index, upgrade in enumerate(upgrades):
                        self._row(body, upgrade["title"].get(language, upgrade["title"]["de"]), tone="gold", points=10)
                        self._row(body, upgrade["body"].get(language, upgrade["body"]["de"]),
                                  task=hud_check_id(*context, "upgrade", index))

        if build.get("glossary"):
            body = self._card(parent, context, "glossary", "Begriffe erklären", closed=True)
            for term, meaning in build["glossary"].items():
                self._row(body, term, tone="gold")
                self._row(body, meaning)
        self._source_card(parent, context, stage.get("sources", build.get("sources", [])))

    def _build_loadout_card(self, parent, context, key, title, tone, closed, structured, tree_url, passive_setup):
        window = self.overlay
        body = self._card(parent, context, key, title, tone=tone, closed=closed)
        if key == "skills":
            render_gems(window, body, structured)
        elif key == "craft":
            def select(slot):
                self.gear_selection[context] = slot

            render_items(window, body, structured, self.gear_selection.get(context, ""), select)
        else:
            view = render_passive_tree(window, body, structured, passive_setup) if structured else None
            render_passive_list(window, body, structured, view, passive_setup)
            if tree_url and not view:
                render_tree_link(window, body, tree_url)
        return body

    def _pick_stage(self, stage_id):
        self.stage_id = stage_id
        self.expanded = False
        self.overlay.refresh_guide()
