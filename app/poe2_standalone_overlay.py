"""PoE2 Ingame Guide with a shared HUD for campaign, builds, Atlas, and search."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
import webbrowser
from threading import Thread
from typing import NamedTuple

import server
from poe2_affix_ui import AffixBrowser, render_affix_tip, render_affix_tool
from poe2_crafting_helper import CraftingHelperState, render_craft_helper
from poe2_build_editorial import stage_view
from poe2_build_terms import equipped_gem_ids
from poe2_build_import_interface import BuildImportStore, bundled_plans, guide_build, import_plans
from poe2_companion_ui import CompanionPanel, load_companion
from poe2_shared_content import campaign_section_rows, sections_for_mode
from poe2_boss_clips import BossClipStore
from poe2_endgame_atlas_ui import EndgamePanel
from poe2_experience import EXPERIENCE_LEVELS, default_guide_mode, experience_allows, saved_experience
from poe2_feedback import open_feedback
from poe2_gif import AnimatedGif, preview_size
from poe2_hud_icons import hud_icon
from poe2_overlay_controls import BackgroundMirror, BrassSlider, ClickTargets, FlowRow, InputRegion, ScrollArrows, SearchCategories
from poe2_overlay_layout import HUD_MIN_SIZE, HUD_SIZE, OverlayLayout
from poe2_overlay_lookup import (AFFIX_TIPS, CATEGORIES, FAQ_TOPICS, PAGE_SIZE, QUERY_LIMIT, construct_catalog,
                                 editorial_entries, find_entries, lookup_entries, make, published_terms)
from poe2_overlay_theme_art import CLASSIC, ThemeTreatment, mix_color, paint_header, paint_rule
from poe2_regex_ui import RegexState, render_regex
from poe2_speedrun import elapsed as timer_elapsed
from poe2_speedrun_hud import SpeedrunHUD
from poe2_lexicon import league_guides, merge_published_lexicon, web_url
from poe2_lexicon_ui import LexiconBrowser, render_lexicon
from poe2_overlay_version import APP_NAME, BUILD_LABEL, INSTALLED_BUILD
from poe2_r18_features import PALETTE, bundled, hud_check_id, hub_kind, item_spans
from poe2_r18_features import AREA_TERM_ALIASES, ITEM_COLORS, TERM_CATALOG, term_aliases, term_key, term_labels, term_matches
from poe2_language import LANGUAGES, CATALOG, ui_text, boss_text, display_label, guide_edit, guide_edit_roles
from poe2_r18_panel import show_checklist
from poe2_respec import render_respec
from poe2_hotkeys import HUD_HOTKEYS, timer_bindings
from poe2_website_content import WebsiteContent, merge_builds
from poe2_term_tooltip import TermTooltips
from poe2_term_links import link_index, link_spans
from plattform import IS_WINDOWS, create_native_overlay, data_dir, register_bundled_fonts, set_app_id


BASE_DIR = Path(__file__).resolve().parent
COMPANION_FILE = BASE_DIR / "poe2_campaign_companion.json"
ATLAS_FILE = BASE_DIR / "poe2_endgame_atlas.json"
BRAND_IMAGES = BASE_DIR / "web" / "images"
BRAND_URL = "https://buildschmiede.de/"
TITLE = APP_NAME
HUD_HEIGHT_LIMIT = "campaign_height_limit"
DATA_DIR = data_dir(BASE_DIR, INSTALLED_BUILD)
ERROR_LOG = DATA_DIR / "overlay_fehler.txt"
ERROR_LOG_LIMIT = 1_000_000
GOLD = "#e1c887"
TEXT = "#f7f2e8"
MUTED = "#d1c9ba"
PANEL_EDGE = "#81704d"
BUTTON_BG = "#1e1b17"
ACTIVE_BG = "#4a3c26"
INFO = "#87ecff"
QUEST = "#e4ce98"
OPTIONAL = "#b89378"
GUIDE_BLUE = "#8eb6ff"
SUCCESS = "#a0ee7d"
DANGER = "#ffbdb0"
HUD_COLLAPSED_RED = "#ff615b"
HUD_TABS = {
    "quest": ("Kampagne", "Campaign", None),
    "build": ("Build-Guide", "Build guide", "campaign_tools"),
    "lookup": ("Wissen", "Knowledge", None),
}
HUD_QUICK = {
    "lock": ("HUD verschieben", "Move HUD", None),
    "mode": ("Ansichtsmodus", "Guide mode", "campaign_tools"),
    "zoom_out": ("Zoom −", "Zoom −", None),
    "zoom_in": ("Zoom +", "Zoom +", None),
    "timer": ("Timer", "Timer", "timers"),
    "eye": ("HUD-Inhalte", "HUD content", None),
}
BOSS_MARKER = "#ff8278"
GAMEPLAY_TITLE = "#e0e6ed"
ROLE_COLORS = {**PALETTE, "info": INFO, "blue": GUIDE_BLUE, "gold": GOLD,
               "optional": OPTIONAL, "gameplay": GAMEPLAY_TITLE}
TRANSPARENT = "#010101"
PREVIEW_BG = "#181411"


class Theme(NamedTuple):
    panel: str
    edge: str
    text: str
    accent: str
    control: str
    active: str
    field: str = ""
    selection: str = ""
    selection_text: str = "#111214"
    treatment: ThemeTreatment = CLASSIC
    menu: str = ""

    @property
    def field_color(self):
        return self.field or self.active

    @property
    def selection_color(self):
        return self.selection or self.accent

    @property
    def menu_color(self):
        return self.menu or self.control


def companion_title(language):
    brand = "Buildforge" if language == "en" else "Buildschmiede"
    return f"{brand} Companion | PoE2"


DEFAULT_THEME = "Buildschmiede"

CARD_BACKGROUNDS = {
    "off": ("Aus", "Off"),
    "translucent": ("Halbtransparent", "Translucent"),
    "opaque": ("Deckend", "Opaque"),
}
MENU_BACKGROUNDS = {
    "opaque": CARD_BACKGROUNDS["opaque"],
    "translucent": CARD_BACKGROUNDS["translucent"],
    "off": ("Transparent", "Transparent"),
}
MENU_TRANSLUCENT_OPACITY = 0.46
CARD_TRANSLUCENT_OPACITY = 0.33

CARD_ACCENTS = {
    "headings": ("Nur Reiter", "Headings only"),
    "cards": ("Nur Kacheln", "Cards only"),
    "both": ("Reiter und Kacheln", "Headings and cards"),
    "off": ("Keine Abschnittsfarben", "No section colors"),
}
COLOR_INTENSITY = {
    "soft": ("Blass", "Soft"),
    "strong": ("Kräftig", "Vivid"),
}
SECTION_PALETTES = {
    "soft": {
        INFO: "#90b1d8", GUIDE_BLUE: "#a6bbda", SUCCESS: "#a0c9a7", QUEST: "#d4bf94",
        GOLD: "#d4bc94", OPTIONAL: "#b5a5c8", BOSS_MARKER: "#dc9891", DANGER: "#dda9a1",
    },
    "strong": {
        INFO: "#6da9ff", GUIDE_BLUE: "#a0c3ff", SUCCESS: "#56dc88", QUEST: "#f2cd69",
        GOLD: "#edc36b", OPTIONAL: "#c4a9f5", BOSS_MARKER: "#ff6e69", DANGER: "#ff907f",
    },
}
OVERLAY_SECTION_TONES = bundled("companion-section-style.json")["overlayTones"]

THEMES = {
    # Matched to buildschmiede.de: card #1a1d22, text #f0ede7, accent #dab568, border = 14 % white on the card.
    "Buildschmiede": Theme("#111214", "#3a3d41", "#f0ede7", "#dab568", "#1a1d22", "#3a2f1f", "#25282d", "#fff3b7",
                          "#231c11", menu="#111214"),
    "PoE2": Theme("#151515", PANEL_EDGE, TEXT, GOLD, BUTTON_BG, ACTIVE_BG),
    "Minimal": Theme(
        "#1a1c1a", "#555a54", "#f1f1eb", "#d5decf", "#222522", "#373c36", "#292d29", "#d5decf", "#202520",
        ThemeTreatment("minimal", ("Segoe UI",), ("Segoe UI Semibold", "Segoe UI"),
                       card_inset=5, card_padding=3, card_border=0, tab_padding=3, slider_thumb="dot"),
    ),
    "Cobalt": Theme(
        "#0e1928", "#395d7b", "#e7f1fb", "#90e0ff", "#14263c", "#204362", "#172d44", "#284c68", "#f4fcff",
        ThemeTreatment("precision", ("Segoe UI",), ("Bahnschrift", "Segoe UI"),
                       card_inset=9, button_relief="solid", slider_thumb="chamfer"),
    ),
    "Vaal": Theme(
        "#190f14", "#774637", "#f2e1cb", "#efbf7b", "#25141b", "#652b38", "#2f1a21", "#6e293b", "#ffe6bc",
        ThemeTreatment("temple", ("Segoe UI",), ("Cinzel", "Trajan Pro", "Constantia", "Georgia"),
                       card_inset=9, card_border=2, button_relief="ridge"),
    ),
    "Code": Theme(
        "#0c0c0c", "#3c5146", "#d9e2dc", "#86e1a1", "#111511", "#263b2b", "#121b14", "#76ca8d", "#101910",
        ThemeTreatment("terminal", ("Cascadia Mono", "Consolas", "Lucida Console"),
                       card_inset=7, card_padding=4, tab_padding=4, slider_thumb="block"),
    ),
    "Dark": Theme(
        "#000000", "#303236", "#e8e9ed", "#d7dbe3", "#000000", "#1b1d23", "#0b0c0f", "#272a31", "#f4f5f8",
        ThemeTreatment("oled", ("Segoe UI",), ("Segoe UI Semibold", "Segoe UI"),
                       card_inset=7, card_border=0, tab_padding=5, slider_thumb="bar"),
    ),
    "Scribe": Theme(
        "#211c16", "#5e4b37", "#f0e3cd", "#e4bb7c", "#2b231a", "#493823", "#32281e", "#59432a", "#fff0d5",
        ThemeTreatment("ledger", ("Cambria", "Georgia"), ("Palatino Linotype", "Georgia"),
                       card_inset=12, card_padding=6, button_relief="groove", slider_thumb="tally"),
    ),
}
THEME_APPEARANCE = {
    "Buildschmiede": ("translucent", "both", "strong"),
    "PoE2": ("off", "headings", "strong"),
    "Minimal": ("off", "off", "strong"),
    "Cobalt": ("translucent", "off", "strong"),
    "Vaal": ("translucent", "headings", "strong"),
    "Code": ("opaque", "headings", "strong"),
    "Dark": ("translucent", "off", "strong"),
    "Scribe": ("opaque", "headings", "strong"),
}


def theme_label(name, language):
    if name == DEFAULT_THEME:
        return name + (" (Default)" if language == "en" else " (Standard)")
    return name


class WelcomeSample(NamedTuple):
    language: str
    mode: str
    background: str
    accents: str
    theme_name: str
    intensity: str
    experience_level: str = "maps"


CAMPAIGN_ACTS = tuple(f"Act {act}" for act in range(1, 7))
LAYOUT_KINDS = {"Wegsignal", "Layoutregel", "Gebietseingang", "Hörhinweis", "Abstecher für Spirit"}
BOSS_KINDS = {"Optionaler Boss", "Boss-Check"}
MODE_LABELS = {"basis": "Ausführlich", "veteran": "Kompakt"}
PLACEHOLDER_GOALS = {"", "Route und Build vorbereiten"}


def zone_key(value):
    return str(value or "").strip().lower().replace("’", "'").removeprefix("the ")


def area_clues(state, zone):
    key = zone_key(zone)
    if not key:
        return []
    matches = []
    for clue in state.get("routeClues", ()):
        if clue.get("status") in {"skip", "blind"}:
            continue
        keys = [zone_key(name) for name in clue.get("zoneMatch") or [clue.get("zone")]]
        if clue.get("exactZone"):
            matched = key in keys
        else:
            matched = any(name and name in key for name in keys)
        if matched:
            matches.append(clue)
    return sorted(matches, key=lambda clue: not clue.get("mandatory"))


def campaign_layout_id(catalog, zone, matches):
    layouts = catalog.get("areaLayouts", {})
    return catalog.get("sharedZones", {}).get(zone_key(zone)) or next(
        (clue["id"] for clue in matches if clue["id"] in layouts), None
    )


def campaign_index(clues):
    names = {zone_key(name): name for name in server.CLIENT_AREA_IDS.values()}
    acts = {}
    for clue in clues:
        if not clue.get("zone") or clue.get("act") not in CAMPAIGN_ACTS:
            continue
        zone_names = [clue["zone"]] if clue.get("singleArea") else (clue.get("zoneMatch") or [clue["zone"]])
        for name in zone_names:
            key = zone_key(name)
            title = clue["zone"] if zone_key(clue["zone"]) == key else name.title()
            acts.setdefault(clue["act"], {})[key] = names.get(key, title)
    for area_id, name in server.CLIENT_AREA_IDS.items():
        if area_id.startswith("G") and area_id.lower().endswith("_town"):
            act = "Act " + area_id[1]
            if act in CAMPAIGN_ACTS:
                acts.setdefault(act, {}).setdefault(zone_key(name), name)
    for ident, shared in CATALOG.get("sharedAreas", {}).items():
        if CATALOG["areaLayouts"][ident].get("template") and shared["act"] in CAMPAIGN_ACTS:
            for name in shared["zones"]:
                acts.setdefault(shared["act"], {})[zone_key(name)] = name
    return {act: acts[act] for act in CAMPAIGN_ACTS if act in acts}


def quest_clues(matches):
    return [clue for clue in matches if clue.get("kind") not in LAYOUT_KINDS | BOSS_KINDS]


def reward_key(value):
    return "".join(str(value or "").lower().split())


def next_objective(progress, matches, bosses, checked):
    goal = progress.get("nextAction") or ""
    if goal not in PLACEHOLDER_GOALS:
        return goal
    objectives = [clue for clue in quest_clues(matches) if not checked.get('route:' + clue['id'])]
    primary = next((clue for clue in objectives if clue.get("mandatory")), None)
    if primary:
        return primary["cue"]
    required_boss = next((boss for boss in bosses if boss["required"] and not checked.get("boss:" + boss["id"])), None)
    if required_boss:
        return required_boss["name"] + " besiegen"
    if objectives:
        return objectives[0]["cue"]
    pending = next((clue for clue in matches if not checked.get("route:" + clue["id"])), None)
    if pending:
        return pending["cue"]
    return ""


def format_time(seconds):
    hours, rest = divmod(max(0, int(seconds or 0)), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


GUIDE_SECTIONS = ("Layout", "Quest", "Permanenter Bonus", "Optionale Ziele",
                  "Tipps", "Settings / Gameplay", "Boss-Guide")


class GuideWindow:
    def __init__(self, app, *, welcome_sample=None):
        self.welcome_sample = welcome_sample
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.withdraw()
        self.window.title(f"{TITLE} – Kampagne")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", app.close)
        if welcome_sample is None:
            for letter, action in (("B", app._open_build_import_interface), ("K", app._open_data_exchange)):
                for key in (letter, letter.lower()):
                    self.window.bind(f"<Control-Shift-Alt-KeyPress-{key}>", action)
        self.backdrop_states = {}
        self.backdrops = {}
        self.backdrop_job = None
        self.hud_bg = TRANSPARENT if app.color_key or app.mirrored_background else PREVIEW_BG
        self.window.configure(bg=self.hud_bg)
        self.layout = OverlayLayout(self.window, app.directory, app.native)
        self.guide_section = "quest"
        self.boss_return_section = self.guide_section
        self.last_content = None
        self.missing_layout_images = set()
        self.measuring = None
        self.resize_job = None
        self.feedback_job = None
        self.wheel_job = None
        self.wheel_remainder = 0
        self.area_name = ""
        self.content_hidden = False
        self.expanded_height = None
        self.lookup_choice = None
        self.lookup_category = "all"
        self.lookup_faq_topic = ""
        self.search_categories = None
        self.lexicon = LexiconBrowser()
        self.affix_browser = AffixBrowser()
        self.lookup_query = ""
        self.lookup_entry = None
        self.lookup_campaign_result = False
        self.lookup_page = 0
        self.lookup_dialog = None
        self.companion = CompanionPanel(self, app.companion)
        self.click_targets = None
        self._build()
        if welcome_sample is not None or not app.native:
            self.click_targets = None
        elif app.color_key:
            self.click_targets = ClickTargets(self)
        else:
            self.click_targets = InputRegion(self)
        self.background_shape = BackgroundMirror(self) if app.mirrored_background else None
        self.window.bind("<Configure>", self._configured, add="+")
        self.window.bind("<Map>", self._mapped, add="+")
        self.window.bind("<Unmap>", self._schedule_targets, add="+")
        self.window.bind("<ButtonRelease-1>", lambda event: self.layout.finish(), add="+")
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.window.bind(event, self.scroll_guide, add="+")

    zone_key = staticmethod(zone_key)

    @property
    def guide_mode(self):
        return self.welcome_sample.mode if self.welcome_sample else self.app.mode

    @property
    def display_language(self):
        return self.welcome_sample.language if self.welcome_sample else self.app.language

    def allows(self, feature):
        if self.welcome_sample:
            return experience_allows(self.welcome_sample.experience_level, feature)
        return self.app.allows(feature)

    def section_available(self, section):
        if section == "quest":
            return True
        if section == "build":
            return self.allows("campaign_tools")
        if section == "boss":
            return bool(self.companion.boss_id)
        return section == "lookup"

    def lookup_entry_available(self, entry):
        if not self.section_available("lookup") or not self.lookup_category_available(entry.category):
            return False
        if entry.category == "tools":
            if entry.target in {"affixes", "crafting-helper"}:
                return self.allows("crafting")
            return self.allows("endgame") or entry.target in ("respec", "build-planner-web")
        if entry.category == "tips" and isinstance(entry.target, str) and entry.target in AFFIX_TIPS:
            return self.allows("crafting")
        if entry.category == "faq" and not self.allows("campaign_tools"):
            return entry.target["topic"] in {"basics", "campaign"}
        return True

    def lookup_category_available(self, category):
        if not self.allows("campaign_tools"):
            return category in {"all", "campaign", "tips", "faq"}
        if category == "atlas":
            return self.allows("atlas")
        return category != "shortcuts" or self.allows("endgame")

    @property
    def showing_atlas(self):
        return self.guide_section == "lookup" and self.lookup_category == "atlas"

    @property
    def theme(self):
        return THEMES[self.welcome_sample.theme_name] if self.welcome_sample else self.app.theme

    def ui_font(self, points, weight="normal"):
        return self.layout.font(self.app.theme_font(theme=self.theme), points, weight)

    def title_font(self, points, weight="normal"):
        return self.layout.font(self.app.theme_font(theme=self.theme, heading=True), points, weight)

    def small_button(self, parent, label, action):
        return tk.Button(parent, text=label, command=action, font=self.ui_font(9, "bold"),
                         cursor="hand2", padx=6, pady=3, **self._button_colors())

    def _button_colors(self):
        theme = self.theme
        return dict(bg=theme.control, fg=theme.text, activebackground=theme.active, activeforeground=theme.accent,
                    bd=1, highlightthickness=1, highlightbackground=theme.edge, highlightcolor=theme.accent,
                    relief=theme.treatment.button_relief, overrelief="groove")

    def _theme_rule(self, parent, *, surface):
        canvas = tk.Canvas(parent, bg=surface, bd=0, highlightthickness=0, width=1, height=self.layout.px(7))
        theme = self.theme

        def draw(event):
            canvas.delete("all")
            paint_rule(canvas, theme._replace(edge=self.divider_color), event.width, event.height, self.layout.px)

        canvas.bind("<Configure>", draw)
        return canvas

    @property
    def divider_color(self):
        theme = self.theme
        return mix_color(theme.edge, theme.accent, 0.42)

    @property
    def color_intensity(self):
        return self.welcome_sample.intensity if self.welcome_sample else self.app.color_intensity

    def section_color(self, color):
        return SECTION_PALETTES[self.color_intensity].get(color, color)

    def guide_card(self, parent, tone="gold", *, header_action=None, neutral=False):
        theme = self.theme
        accent = {"quest": QUEST, "info": INFO, "optional": OPTIONAL, "success": SUCCESS,
                  "gameplay_title": GAMEPLAY_TITLE, "danger": BOSS_MARKER, "gold": theme.accent,
                  "gem": "#86d6ca" if self.color_intensity == "soft" else "#57e0c9"}.get(tone, GOLD)
        accent = self.section_color(accent)
        if self.color_intensity == "soft":
            accent = OVERLAY_SECTION_TONES.get(tone, accent)
        effects = self.welcome_sample.accents if self.welcome_sample else self.app.card_accents
        heading_color = accent if effects in {"headings", "both"} else theme.text
        tinted = not neutral and effects in {"cards", "both"} and self.card_background != "off"
        strong = self.color_intensity == "strong"
        backdrop_color = mix_color(theme.control, accent, 0.43 if strong else 0.25) if tinted else theme.control
        surface = theme.control if neutral else self.card_surface
        if tinted:
            if self.card_background == "opaque":
                surface = mix_color(theme.control, accent, 0.28 if strong else 0.16)
            elif not self.app.color_key:
                surface = self._translucent(backdrop_color, CARD_TRANSLUCENT_OPACITY)
        treatment = theme.treatment
        card = tk.Frame(parent, bg=surface, padx=self.layout.px(treatment.card_inset))
        card.guide_card = not neutral
        card.guide_backdrop_color = backdrop_color
        card.pack(fill="x")
        if tinted and strong:
            tk.Frame(card, bg=accent).place(x=0, y=0, relheight=1, width=self.layout.px(2), bordermode="ignore")
        heading_parent = tk.Frame(card, bg=surface) if header_action else card
        top_pad = max(0, self.layout.px(treatment.card_padding - 4))
        if header_action:
            heading_parent.pack(fill="x", pady=(top_pad, 0))
        button = self.small_button(heading_parent, "", lambda: None)
        button.configure(anchor="w", fg=heading_color, bg=surface, font=self.title_font(13, "bold"),
                         highlightthickness=0, bd=0, relief="flat", overrelief="flat", activebackground=surface,
                         activeforeground=heading_color)
        if header_action:
            label, callback = header_action
            action = self.small_button(heading_parent, "", callback)
            action.configure(textvariable=label, bg=surface, fg=theme.accent, activebackground=surface, bd=0,
                             padx=self.layout.px(4), highlightthickness=0, font=self.ui_font(9),
                             relief="flat", overrelief="flat")
            action.pack(side="right")
            button.pack(side="left", fill="x", expand=True)

            def fit_header(event):
                wrap = max(self.layout.px(32), event.width - action.winfo_reqwidth() - self.layout.px(16))
                if button.winfo_pixels(button.cget("wraplength")) != wrap:
                    button.configure(wraplength=wrap)

            heading_parent.bind("<Configure>", fit_header)
        else:
            button.pack(fill="x", pady=(top_pad, 0))
        rule = (tk.Frame(card, bg=self.divider_color, height=self.layout.px(2)) if treatment == CLASSIC
                else self._theme_rule(card, surface=surface))
        rule.pack(fill="x", padx=4, pady=(0, 4))
        body = tk.Frame(card, bg=surface)
        body.guide_card_color = surface
        body.pack(fill="x")
        tk.Frame(card, bg=surface, height=self.layout.px(treatment.card_padding)).pack(side="bottom", fill="x")
        return button, body

    def _drag_target(self, widget, operation):
        if self.welcome_sample:
            return
        widget.bind("<Button-1>", lambda event: self._begin_gesture(operation, event))
        widget.bind("<B1-Motion>", self._move_gesture)

    def _build(self):
        self.shell = tk.Frame(self.window, bg=self.hud_bg)
        self.shell.pack(fill="both", expand=True, padx=self.layout.px(6), pady=self.layout.px(5))
        self.shell.grid_columnconfigure(0, weight=1, minsize=1)
        self.shell.grid_rowconfigure(5, weight=1)

        self.header = tk.Canvas(self.shell, bg=self.theme.control, bd=0, highlightthickness=0, width=1, height=39)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.bind("<Configure>", self._draw_header)
        self._drag_target(self.header, "move")
        self.header_brand = tk.Button(self.header, text="Buildschmiede", command=lambda: webbrowser.open(BRAND_URL),
                                      cursor="hand2", relief="flat", bd=0, highlightthickness=0, padx=0, pady=0)
        self.quick_settings = quick = tk.Frame(self.shell, bg=self.theme.control)
        quick.grid(row=1, column=0, sticky="ew")
        self.lock_button = self.small_button(quick, "HUD position", self.app.toggle_click_mode)
        self.mode_button = self.small_button(quick, MODE_LABELS[self.guide_mode], self.app.toggle_mode)
        self.zoom_out_button = self.small_button(quick, "Zoom −", lambda: self.zoom(-10))
        self.zoom_in_button = self.small_button(quick, "Zoom +", lambda: self.zoom(10))
        self.timer_button = self.small_button(quick, "Speedrun-Timer",
                                              lambda: self.app.set_timer(not self.app.timer_visible))
        self.eye_button = self.small_button(quick, "HUD-Inhalte", self.toggle_content)
        quick.bind("<Configure>", self._style_quick_icons)

        self.navigation = tk.Frame(self.shell, bg=self.theme.edge)
        self.navigation.grid(row=2, column=0, sticky="ew", pady=(0, self.layout.px(5)))
        self.tabs = {}
        for view in HUD_TABS:
            self.tabs[view] = self.small_button(self.navigation, HUD_TABS[view][0],
                                                 lambda view=view: self.select_guide_section(view))
        self.options_button = self.small_button(self.shell, "Optionen", self.app.open_settings)
        self.quick_buttons = (self.lock_button, self.mode_button, self.zoom_out_button, self.zoom_in_button,
                              self.timer_button, self.eye_button)
        self.nav_dividers = [tk.Frame(self.navigation) for _ in range(len(self.tabs))]
        self.navigation.bind("<Configure>", self._style_nav_icons)
        self._style_chrome()

        self.telemetry = tk.Frame(self.shell, bg=self.hud_bg)
        self.telemetry.columnconfigure(0, weight=1)
        self.speedrun_clock = tk.Button(
            self.telemetry, bg=self.hud_bg, activebackground=self.hud_bg,
            fg=self.theme.accent, activeforeground=self.theme.accent, anchor="e",
            font=self.ui_font(9, "bold"), padx=4, pady=2, bd=0, highlightthickness=0,
            relief="flat", cursor="hand2", command=self.app.toggle_speedrun_details,
        )
        self.boss_metric = tk.Label(self.telemetry, bg=self.hud_bg, fg=self.theme.accent, anchor="e",
                                    font=self.ui_font(9, "bold"), padx=4, pady=2)
        self.level_status = tk.Label(self.telemetry, bg=self.hud_bg, anchor="w", width=1,
                                     font=self.ui_font(9, "bold"), padx=4, pady=2)
        self.feedback = tk.Label(self.shell, bg=self.theme.control, fg=self.theme.accent, font=self.ui_font(9), padx=5, pady=2)

        self.body = tk.Frame(self.shell, bg=self.hud_bg)
        self.body.grid(row=5, column=0, sticky="nsew")
        self.route = tk.Frame(self.body, bg=self.hud_bg)
        self.route.pack(fill="x")
        self.route_links = tk.Frame(self.body, bg=self.hud_bg)
        self.route_links.pack(fill="x")
        self.route_canvas = tk.Canvas(self.route, bg=self.hud_bg, bd=0, highlightthickness=0, width=1, height=1)
        self.route_scroll = ScrollArrows(self.body, self.route_canvas, self.theme.control, self.theme.accent, inset=0)
        self.route_canvas.pack(side="left", fill="both", expand=True)
        self.route_rows = tk.Frame(self.route_canvas, bg=self.hud_bg)
        self.route_window = self.route_canvas.create_window(0, 0, anchor="nw", window=self.route_rows)
        self.route_canvas.configure(yscrollcommand=self._route_scroll_extent)
        self.body.bind("<Configure>", self._refit_route)
        self.route_canvas.bind("<Configure>", self._refit_route)
        self.route_links.bind("<Configure>", self._refit_route)
        self.route_rows.bind("<Configure>", self._refit_route)
        self.atlas_controls = FlowRow(self.body, bg=self.hud_bg)
        self.atlas_back = self.small_button(self.atlas_controls, "", lambda: self._set_lookup("all"))
        self.endgame = EndgamePanel(
            self.body, ATLAS_FILE,
            {"bg": self.hud_bg, "edge": self.theme.edge, "text": self.theme.text, "muted": MUTED,
             "control": self.theme.control, "active": self.theme.active, "gold": self.theme.accent,
             "info": INFO, "success": SUCCESS, "danger": DANGER},
            self.app.ui_family, self.app.title_family, self.layout.font, self._schedule_targets,
            fit_height=self.fit_height,
            get_language=lambda: self.app.language, on_check=self.check_atlas_item, term_tips=self.app.term_tips,
            scale_pixels=self.layout.px,
        )
        self._style_endgame()

    def _style_chrome(self):
        px = self.layout.px
        self.shell.pack_configure(padx=px(6), pady=px(5))
        for widget in (self.header, self.quick_settings, self.navigation):
            widget.configure(bg=self.menu_surface)
        self.navigation.configure(pady=px(2))
        if self.navigation.winfo_manager():
            self.navigation.grid_configure(pady=(0, px(5)))
        for divider in self.nav_dividers:
            divider.configure(width=px(2), bg=self.divider_color)
        for button in (*self.quick_buttons, *self.tabs.values(), self.options_button):
            button.configure(**self._button_colors())
            button.configure(width=1, padx=0, pady=0, bd=0, highlightthickness=0, anchor="center",
                             relief="flat", overrelief="flat")
        self._layout_controls()
        self._style_tabs()

    def _nav_buttons(self):
        hidden = self.app.prefs.get("hidden_hud_tabs", ())
        visible = [(name, button) for name, button in self.tabs.items()
                   if self.section_available(name)
                   and (self.welcome_sample or name not in hidden)]
        visible.append(("settings", self.options_button))
        return visible

    def _visible_quick_buttons(self):
        if not self.welcome_sample and not self.app.prefs.get("hud_quick_visible", True):
            return ()
        hidden = () if self.welcome_sample else self.app.prefs.get("hidden_hud_quick", ())
        return tuple(button for (name, (_, _, feature)), button in zip(HUD_QUICK.items(), self.quick_buttons)
                     if name not in hidden and (feature is None or self.allows(feature)))

    def _layout_controls(self):
        for widget in (*self.quick_buttons, *self.tabs.values(), self.options_button, *self.nav_dividers):
            widget.grid_forget()
        for column in range(len(self.quick_buttons)):
            self.quick_settings.columnconfigure(column, weight=0, uniform="")
        quick_buttons = self._visible_quick_buttons()
        if quick_buttons:
            self.quick_settings.grid()
        else:
            self.quick_settings.grid_remove()
        for column, button in enumerate(quick_buttons):
            self.quick_settings.columnconfigure(column, weight=1, uniform="quick_settings")
            button.grid(in_=self.quick_settings, row=0, column=column, sticky="nsew")

        buttons = self._nav_buttons()
        if self.content_hidden or len(buttons) == 1:
            self.navigation.grid_remove()
            return
        self.options_button.place_forget()
        self.navigation.grid()
        for column in range(len(self.nav_dividers) + 1):
            self.navigation.columnconfigure(2 * column, weight=0, uniform="")
        minimal = not self.allows("campaign_tools")
        for column, (_, button) in enumerate(buttons):
            self.navigation.columnconfigure(2 * column, weight=1, uniform="" if minimal else "hud_tools")
            button.grid(in_=self.navigation, row=0, column=2 * column, sticky="nsew")
            if column:
                self.nav_dividers[column - 1].grid(row=0, column=2 * column - 1, sticky="ns")

    def refresh_experience(self):
        if not self.section_available(self.guide_section):
            self.guide_section = "quest"
        if not self.section_available("lookup") or not self.lookup_category_available(self.lookup_category):
            if self.lookup_dialog:
                self.lookup_dialog.destroy()
            self.lookup_category, self.lookup_query, self.lookup_choice = "all", "", None
            self.lookup_campaign_result, self.lookup_entry, self.lookup_page = False, None, 0
        elif self.lookup_entry and not self.lookup_entry_available(self.lookup_entry):
            self.lookup_entry, self.lookup_page = None, 0
        self._layout_controls()
        self._style_tabs()
        self._draw_header()
        self.refresh_guide()

    def _icon_pixels(self, size):
        return self.layout.px(size * self.layout.scale / 100)

    def _set_hud_icon(self, button, name, size, color):
        key = name, size, color
        if getattr(button, "hud_icon_key", None) != key:
            image = hud_icon(button, name, size, color)
            button.configure(image=image)
            button.hud_icon_key = key
            button.hud_icon = image

    def _style_nav_icons(self, event=None):
        theme = self.theme
        px = self.layout.px
        size = self._icon_pixels(23)
        buttons = self._nav_buttons()
        width = self.navigation.winfo_width()
        english = self.display_language == "en"
        labels = ({"quest": "Campaign" if english else "Kampagne"}
                  if not self.allows("campaign_tools") else {})
        font = self.ui_font(9, "bold")
        pad = px(3)
        if labels:
            texts = [labels[name] for name, _ in buttons if name in labels]
            reserved = (len(buttons) - 1) * px(2) + len(texts) * 2 * pad
            available = width - reserved
            for points in (8, 7, 6):
                if width <= 1 or sum(font.measure(text) for text in texts) <= available:
                    break
                font = self.ui_font(points, "bold")
        elif width > 1:
            tile_width = (width - (len(buttons) - 1) * px(2)) // len(buttons)
            size = max(1, min(size, tile_width - px(6)))
        height = max(px(25), size) + 2 * px(theme.treatment.tab_padding)
        self.navigation.rowconfigure(0, minsize=height)
        current = self.boss_return_section if self.guide_section == "boss" else self.guide_section
        for name, button in buttons:
            active = name == current
            color = theme.accent if active else theme.text
            background = theme.active if active and self.app.menu_background == "opaque" else self.menu_surface
            button.configure(bg=background, fg=color, activebackground=theme.active, activeforeground=theme.accent,
                             highlightthickness=1, highlightbackground=theme.accent if active else self.menu_surface,
                             highlightcolor=theme.text, takefocus=True)
            if name in labels:
                label = labels[name]
                button.hud_icon_key = None
                button.configure(text=label, image="", compound="none", width=0, height=0, padx=pad,
                                 font=font)
            else:
                self._set_hud_icon(button, "learn" if name == "lookup" else name, size, color)
                button.configure(width=1, height=height, padx=0)
            if self.welcome_sample:
                button.configure(state="disabled", disabledforeground=color, cursor="arrow")

    def _style_quick_icons(self, event=None):
        theme, px = self.theme, self.layout.px
        english = self.display_language == "en"
        compact = self.guide_mode == "veteran"
        locked = self.welcome_sample is not None or self.app.click_through
        size = min(self._icon_pixels(18), px(23))
        width = self.quick_settings.winfo_width()
        quick_count = len(self._visible_quick_buttons())
        if width > 1 and quick_count:
            size = min(size, max(1, width // quick_count - px(5)))
        height = max(px(27), size + px(6))
        controls = (
            ("locked" if locked else "unlocked", "HUD position", not locked, False),
            ("compact" if compact else "detailed",
             ("Compact" if compact else "Detailed") if english else MODE_LABELS[self.guide_mode], False, False),
            ("zoom_out", "Zoom −", False, self.layout.scale <= 80),
            ("zoom_in", "Zoom +", False, self.layout.scale >= 160),
            ("timer", "Speedrun-Timer", self.app.timer_visible, False),
            ("eye", "HUD content" if english else "HUD-Inhalte", False, False),
        )
        for button, (icon, label, active, disabled) in zip(self.quick_buttons, controls):
            color = HUD_COLLAPSED_RED if icon == "eye" and self.content_hidden else (
                theme.edge if disabled else theme.accent if active else theme.text)
            self._set_hud_icon(button, icon, size, color)
            background = theme.active if active and self.app.menu_background == "opaque" else self.menu_surface
            button.configure(text=label, height=height, fg=color, disabledforeground=color,
                             activeforeground=color, bg=background,
                             state="disabled" if disabled or self.welcome_sample else "normal")

    def _style_tabs(self):
        self._style_nav_icons()
        self._style_quick_icons()

    def apply_theme(self):
        theme = self.theme
        self._style_chrome()
        self.speedrun_clock.configure(fg=theme.accent, activeforeground=theme.accent, font=self.ui_font(9, "bold"))
        self.boss_metric.configure(fg=theme.accent, font=self.ui_font(9, "bold"))
        self.level_status.configure(font=self.ui_font(9, "bold"))
        self.feedback.configure(bg=theme.control, fg=theme.accent, font=self.ui_font(9))
        self.route_scroll.colors(theme.control, theme.accent)
        self._style_endgame()
        self._draw_header()
        self.refresh_guide()

    def _style_endgame(self):
        effects = self.welcome_sample.accents if self.welcome_sample else self.app.card_accents
        colors = {"progression": INFO, "quests": QUEST, "crafting": "#eaaf79", "affixes": OPTIONAL,
                  "tablets": SUCCESS, "boss": DANGER}
        self.endgame.apply_theme(self.theme, surface=self.card_surface,
                                 body_family=self.app.theme_font(theme=self.theme), heading_family=self.app.theme_font(theme=self.theme, heading=True),
                                 control_family=self.app.theme_font(theme=self.theme, fallback=self.app.ui_family),
                                 info=self.section_color(INFO), success=self.section_color(SUCCESS),
                                 danger=self.section_color(DANGER),
                                 tab_colors={tab: self.section_color(color) for tab, color in colors.items()},
                                 accents=effects in {"headings", "both"},
                                 tint_sections=effects in {"cards", "both"} and self.card_background != "off")

    def check_atlas_item(self, task, checked):
        if self.app.check_item(task, checked):
            self.update(self.app.state)

    @property
    def card_background(self):
        return self.welcome_sample.background if self.welcome_sample else self.app.card_background

    def _translucent(self, color, opacity):
        """Half-transparent surface without colour key: a key colour for the Linux mirror, else a mix."""
        if self.app.mirrored_background:
            return self.app.translucent_key(color, opacity)
        return mix_color(self.hud_bg, color, opacity)

    @property
    def menu_surface(self):
        if self.app.menu_background == "opaque":
            return self.theme.menu_color
        if self.app.menu_background == "translucent" and not self.app.color_key:
            return self._translucent(self.theme.menu_color, MENU_TRANSLUCENT_OPACITY)
        return self.hud_bg

    @property
    def card_surface(self):
        if self.card_background == "opaque":
            return self.theme.control
        if self.card_background == "translucent" and not self.app.color_key:
            # Without a colour key the Tk surface is opaque: the preview mixes the colour,
            # the Linux mirror turns a key colour into real partial transparency.
            return self._translucent(self.theme.control, CARD_TRANSLUCENT_OPACITY)
        return self.hud_bg

    def enter(self):
        if self.app.welcome is not None and not self.welcome_sample:
            return
        if self.background_shape and not self.background_shape.stopped:
            # Linux mirror: the picture comes from the ARGB mirror, the Tk window stays invisible.
            self.window.attributes("-alpha", 1/255)
        elif not self.app.color_key:
            self.window.attributes("-alpha", self.app.overlay_alpha()/255)
        self.window.deiconify()
        self.window.update_idletasks()
        self.layout.restore()
        self._apply_entry_click_mode()
        self._schedule_targets()
        self.update(self.app.state)

    def _apply_entry_click_mode(self):
        try:
            self.set_click_mode(self.app.click_through)
        except (OSError, tk.TclError):
            if not self.app.click_through:
                raise
            logging.exception("Spielmodus konnte nicht aktiviert werden.")
            self.app.click_through = False
            self.set_click_mode(False)
            self.flash("Bearbeiten · F9 zum Spielen")

    def leave(self):
        self._clear_wheel_target()
        self.layout.finish()
        if self.click_targets:
            self.click_targets.hide()
        if self.background_shape:
            self.background_shape.hide()
        if self.lookup_dialog:
            self.lookup_dialog.destroy()
        self.window.withdraw()
        self._hide_backdrops()

    def _hide_backdrops(self):
        for background, _ in self.backdrops.values():
            background.withdraw()
        self.backdrop_states.clear()

    def close(self):
        if self.lookup_dialog:
            self.lookup_dialog.destroy()
        self._clear_wheel_target()
        self.layout.finish()
        if self.click_targets:
            self.click_targets.hide()
        if self.background_shape:
            self.background_shape.close()
        for job in (self.resize_job, self.feedback_job, self.measuring, self.wheel_job, self.backdrop_job):
            if job:
                self.window.after_cancel(job)
        for background, _ in self.backdrops.values():
            background.destroy()
        self.window.destroy()

    def set_click_mode(self, enabled):
        if self.app.native:
            self.app.native.set_click_mode(self.window, enabled, alpha=self.app.overlay_alpha())
        if not enabled:
            self._clear_wheel_target()
        self.header.configure(cursor="arrow" if enabled else "fleur")
        try:
            self._sync_click_mode()
        except (OSError, tk.TclError):
            self.click_targets.hide()
            self.app.native.set_click_mode(self.window, False)
            self.header.configure(cursor="fleur")
            raise
        self._style_quick_icons()
        self._draw_header()
        self._schedule_targets()
        if self.app.settings_open():
            self.app.settings.lift()

    def _sync_click_mode(self):
        if self.click_targets and self.window.winfo_viewable():
            # Even with an opaque toolbar, guide controls may have a colour-key
            # background. Keep their hit areas available while moving the HUD.
            if self.app.color_key or self.app.click_through or self.app.menu_background != "opaque":
                self.click_targets.show()
            else:
                self.click_targets.hide()

    def _mapped(self, event):
        # On Windows Tk can replace the native wrapper when first mapping a
        # toplevel. Styles applied by enter() to the old handle do not survive.
        if (event.widget is self.window and self.app.color_key and not self.welcome_sample
                and self.app.current is self and self.app.visible and self.app.welcome is None):
            self._apply_entry_click_mode()
        self._schedule_targets()

    def flash(self, message):
        if self.content_hidden:
            return
        if self.feedback_job:
            self.window.after_cancel(self.feedback_job)
        self.feedback.configure(text=message)
        self.feedback.grid(row=4, column=0, sticky="w", pady=(0, 3))
        self.feedback_job = self.window.after(1800, self._clear_feedback)

    def _clear_feedback(self):
        self.feedback.grid_remove()
        self.feedback_job = None

    def _configured(self, event):
        self._schedule_targets()
        if event.widget is self.window and not self.resize_job:
            self.resize_job = self.window.after_idle(self._update_dpi)
            if self.search_categories is not None:
                self._refit_route()

    def sync_backdrop(self):
        try:
            self._draw_backdrop()
        finally:
            self.backdrop_job = None

    def _draw_backdrop(self):
        native = self.app.native
        if not self.app.color_key or not self.window.winfo_viewable():
            if self.backdrop_states:
                self._hide_backdrops()
            return

        origin_x, origin_y = self.window.winfo_rootx(), self.window.winfo_rooty()
        menu_rectangles = []
        card_rectangles = []

        def shade(widget, clip, rectangles, color):
            if widget.winfo_viewable():
                left, top, right, bottom = clip
                x1, y1, x2, y2 = ClickTargets._size(widget)
                x1, y1, x2, y2 = max(left, x1), max(top, y1), min(right, x2), min(bottom, y2)
                if x1 < x2 and y1 < y2:
                    rectangles.append((x1-origin_x, y1-origin_y, x2-origin_x, y2-origin_y, color))

        if self.app.menu_background == "translucent":
            clip = ClickTargets._size(self.window)
            for bar in (self.header, self.quick_settings, self.navigation):
                shade(bar, clip, menu_rectangles, self.theme.menu_color)
        if self.card_background == "translucent" and not self.content_hidden:
            viewport = self._scroll_widget()
            if viewport.winfo_viewable():
                clip = ClickTargets._size(viewport)
                if self.showing_atlas:
                    shade(viewport, clip, card_rectangles, self.theme.control)
                else:
                    for card in self.route_rows.winfo_children():
                        if getattr(card, "guide_card", False):
                            shade(card, clip, card_rectangles, card.guide_backdrop_color)

        target = native.hwnd(self.window)
        rect = native.positioned_at(target)
        if not rect:
            return
        self._paint_backdrop("menu", target, rect, menu_rectangles, MENU_TRANSLUCENT_OPACITY)
        self._paint_backdrop("cards", target, rect, card_rectangles, CARD_TRANSLUCENT_OPACITY)

    def _paint_backdrop(self, layer, target, rect, rectangles, opacity):
        backdrop = self.backdrops.get(layer)
        previous = self.backdrop_states.get(layer)
        if not rectangles:
            if previous is not None:
                backdrop[0].withdraw()
                self.backdrop_states.pop(layer)
            return

        native = self.app.native
        alpha = max(1, round(self.app.overlay_alpha() * opacity))
        state = (rect, alpha, rectangles)
        if previous == state and backdrop[0].winfo_viewable():
            return
        if backdrop is None:
            bg = tk.Toplevel(self.app.root, bg=TRANSPARENT)
            bg.withdraw()
            bg.overrideredirect(True)
            bg.attributes("-topmost", True)
            canvas = tk.Canvas(bg, bg=TRANSPARENT, bd=0, highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            self.backdrops[layer] = backdrop = (bg, canvas)
        bg, canvas = backdrop
        if previous is None or previous[2] != rectangles:
            canvas.delete("all")
            for x1, y1, x2, y2, color in rectangles:
                canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="")
        mapped = bg.winfo_viewable()
        if not mapped:
            bg.geometry(f"{rect[2]}x{rect[3]}+{rect[0]}+{rect[1]}")
            bg.deiconify()
            # Tk may replace the wrapper HWND when it first maps a toplevel.
            bg.update_idletasks()
            native.set_click_mode(bg, True, no_activate=True, alpha=alpha)
        elif previous is None or previous[1] != alpha:
            native.set_opacity(bg, alpha)
        if not mapped or previous is None or previous[0] != rect:
            native.stack_below(bg, target, rect)
        self.backdrop_states[layer] = state

    def _schedule_targets(self, event=None):
        translucent = self.card_background == "translucent" or self.app.menu_background == "translucent"
        if self.app.color_key and (translucent or self.backdrop_states) and self.backdrop_job is None:
            self.backdrop_job = self.window.after_idle(self.sync_backdrop)
        if self.click_targets:
            self.click_targets.schedule()
        if self.background_shape:
            self.background_shape.schedule()
        if self.app.native and self.wheel_job is None:
            self.wheel_job = self.window.after_idle(self._sync_wheel_target)

    def _scroll_widget(self):
        return self.endgame.text if self.showing_atlas else self.route_canvas

    def track_lookup_dialog(self, dialog):
        self.lookup_dialog = dialog

        def closed(event):
            if event.widget is dialog and self.lookup_dialog is dialog:
                self.lookup_dialog = None
                self._schedule_targets()

        def moved(event):
            if event.widget is dialog:
                self._schedule_targets()

        dialog.bind("<Destroy>", closed, add="+")
        dialog.bind("<Configure>", moved, add="+")
        self._schedule_targets()

    def _clear_wheel_target(self):
        self.wheel_remainder = 0
        if self.app.native:
            self.app.native.set_wheel_target(self, None)

    def _sync_wheel_target(self):
        self.wheel_job = None
        widget = self._scroll_widget()
        dialog = self.lookup_dialog or self.app.welcome or self.app.settings
        if (self.app.current is self and self.app.visible and self.app.click_through and
                widget.winfo_ismapped() and widget.yview() != (0.0, 1.0) and
                not self.window.tk.call("grab", "current", str(self.window))):
            x, y = widget.winfo_rootx(), widget.winfo_rooty()
            exclude = ClickTargets._size(dialog) if dialog and dialog.winfo_ismapped() else None
            self.app.native.set_wheel_target(self, (x, y, x + widget.winfo_width(), y + widget.winfo_height()), exclude)
        else:
            self._clear_wheel_target()

    def _update_dpi(self):
        self.resize_job = None
        if self.window.winfo_ismapped() and self.layout.sync_dpi():
            self._style_chrome()
            self._draw_header()
            self.refresh_guide()

    def _header_inset(self):
        decorated = self.theme.treatment.motif in {"precision", "temple", "terminal", "ledger"}
        return self.layout.px(18 if decorated else 7)

    def _header_min_points(self):
        # Keep a readable floor even when a large HUD zoom meets a narrow monitor.
        return min(10, 1000 // self.layout.scale)

    def _header_text(self):
        language = self.display_language
        fallback = display_label(CATEGORIES["campaign"], language)
        title = self.area_name or fallback
        return "> " + title if self.theme.treatment.motif == "terminal" else title

    def _draw_header(self, event=None):
        size = self.layout.px
        font = self.title_font(15, "bold")
        height = max(size(34), font.metrics("linespace") + size(10))
        title = self._header_text()
        theme = self.theme
        left = theme.treatment.motif in ("terminal", "ledger")
        width = self.header.winfo_width()
        if width <= 1:
            return
        inset = self._header_inset()
        mark = self.app.brand_mark(size(24))
        brand_width = mark.width() + size(4)
        self.header_brand.configure(image=mark, bg=self.menu_surface, activebackground=self.menu_surface)
        if self.welcome_sample:
            self.header_brand.configure(state="disabled", cursor="arrow")
        self.header_brand.place(x=inset, rely=0.5, anchor="w", width=brand_width, height=mark.height() + size(4))
        start = inset + brand_width + size(4)
        header_settings = self.content_hidden or len(self._nav_buttons()) == 1
        settings_width = height if header_settings else 0
        if header_settings:
            self._set_hud_icon(self.options_button, "settings", self._icon_pixels(18), theme.text)
            self.options_button.configure(bg=self.menu_surface)
            self.options_button.place(in_=self.header, relx=1, x=-inset, rely=0.5, anchor="e",
                                      width=settings_width, height=height - size(4))
        right = inset + settings_width + size(4)
        usable = width - (start + right if left else 2 * max(start, right))
        if int(self.header.cget("height")) != height:
            self.header.configure(height=height)
        for points in range(14, self._header_min_points() - 1, -1):
            if font.measure(title) <= usable:
                break
            font = self.title_font(points, "bold")
        if font.measure(title) > usable:
            ending = "…"
            while title and font.measure(title.rstrip() + ending) > usable:
                title = title[:-1]
            title = title.rstrip() + ending if font.measure(ending) <= usable else ""
        self.header.delete("all")
        if theme.treatment != CLASSIC:
            paint_header(self.header, theme._replace(control=self.menu_surface), width, height, size)
        self._ink(self.header, start if left else width / 2, height / 2, title, font, theme.accent,
                  anchor="w" if left else "center")

    @staticmethod
    def _ink(canvas, x, y, value, font, fg, *, anchor="nw", width=0):
        canvas.create_text(x, y + 1, text=value, font=font, fill="#100e0b", anchor=anchor,
                           width=width, tags="ink")
        canvas.create_text(x, y, text=value, font=font, fill=fg, anchor=anchor, width=width, tags="ink")

    def pack_message(self, parent, value, *, tone="text", points=11, padding=3, marker=False, highlight=None,
                     font=None, body_color=None, term_colors=None, manual_colors=None, check_state=None,
                     lead="", lead_tone="info", term_refs=None):
        palette = {"text": self.theme.text, "gold": self.theme.accent, "muted": MUTED, "info": INFO, "quest": QUEST, "optional": OPTIONAL,
                   "danger": DANGER, "success": SUCCESS, "gameplay": self.theme.text,
                   "gameplay_title": GAMEPLAY_TITLE}
        color = palette[tone]
        canvas = tk.Canvas(parent, bg=getattr(parent, "guide_card_color", self.hud_bg), bd=0, highlightthickness=0, width=1, height=1)
        if font is None:
            font = self.ui_font(points, "bold" if tone in {"gold", "danger", "info", "quest", "success"} else "normal")
            if tone in {"gold", "quest"}:
                font = self.title_font(points, "bold")
        prefix = lead + " · " if lead else ""
        lead_font = self.ui_font(points, "bold") if lead else font
        value = prefix + str(value)
        build_spans = []
        is_build = (self.guide_section == "build" or (self.guide_section == "lookup"
                    and getattr(self.lookup_entry, "category", None) == "builds"))
        if is_build:
            value, build_spans = self.app.term_tips.build_markup(value, getattr(self, "build_gem_ids", ()),
                                                                 getattr(self, "build_reference_context", ()))
        colors = {**ITEM_COLORS, **{term_key(term): shade for term, shade in (term_colors or {}).items()}}
        colors.update({term_key(phrase): shade for phrase, shade in (manual_colors or {}).items()})
        accents = list(term_matches(value, colors))
        if lead:
            accents.insert(0, (0, len(prefix), palette[lead_tone]))
        canvas.term_refs = {term_key(phrase): ident for phrase, ident in (term_refs or {}).items()}
        hover_terms = [] if is_build else self.app.term_tips.spans(value, canvas.term_refs)
        links = self.link_spans(value)
        if build_spans:
            # Authored gem labels can also be ordinary words in the campaign glossary.
            links = [(a, b, dest) for a, b, dest in links
                     if all(b <= start or a >= end for start, end, _, _ in build_spans)]
            links.extend((a, b, target) for a, b, target, _ in build_spans)
            accents = [(a, b, shade) for a, b, _, shade in build_spans if shade] + accents
            accents.extend((a, b, self.theme.accent) for a, b, _, shade in build_spans if not shade)
        if not self.allows("campaign_tools"):
            links = [(a, b, target) for a, b, target in links if target[0] in ("item", "boss")]
        highlights = highlight if isinstance(highlight, (list, tuple)) else [highlight]
        highlights = [word for word in highlights if word and word in value]
        for word in highlights:
            start = value.index(word)
            end = start + len(word)
            if not any(start < stop and end > begin for begin, stop, _ in accents):
                accents.append((start, end, color))

        default_ink = body_color or (self.theme.text if highlights else color)
        words = []
        if accents or hover_terms or links:
            for word in re.finditer(r"\S+", value):
                start, end = word.span()
                shades = [(max(a, start), min(b, end), shade) for a, b, shade in accents if a < end and b > start]
                cuts = {start, end}
                if is_build:
                    for a, b, _ in shades:
                        cuts.update((a, b))
                edges = sorted(cuts)
                parts = [(a, b, next((shade for left, right, shade in shades if left < b and right > a), default_ink))
                         for a, b in zip(edges, edges[1:])]
                destinations = [(a, b, destination) for a, b, destination in links if a < end and b > start]
                hover = next(((a, b) for a, b in hover_terms if a < end and b > start), None)
                words.append((start, end, parts, destinations, hover))

        def draw(event=None):
            width = canvas.winfo_width()
            if width <= 1:
                return
            size = self.layout.px
            line_x = size(30 if check_state is not None and marker else
                          26 if check_state is not None else 20 if marker else 4)
            line_y = size(padding)
            canvas.delete("ink")
            if check_state is not None:
                theme = self.theme
                x, side = size(5), size(14)
                y = line_y + max(0, (font.metrics("linespace") - side) // 2)
                outline = mix_color(theme.edge, theme.accent, 0.58)
                canvas.create_rectangle(x, y, x + side, y + side, width=max(1, size(1)),
                                        outline=outline, fill=theme.control,
                                        tags=("ink", "check_box"))
                if check_state:
                    canvas.create_line(x + size(3), y + size(7), x + size(6), y + size(10),
                                       x + size(11), y + size(4), width=max(1, size(1)),
                                       fill=theme.accent, capstyle="round", joinstyle="round",
                                       tags=("ink", "check_mark"))
            if marker:
                x = size(25 if check_state is not None else 8)
                y = line_y + font.metrics("linespace") / 2
                theme = self.theme
                bullet = GOLD if theme.treatment == CLASSIC else theme.accent
                marker_color = {"text": bullet, "gameplay": GAMEPLAY_TITLE}.get(tone, color)
                canvas.create_polygon(x-size(4), y, x, y-size(2), x+size(4), y, x, y+size(2),
                                      fill=self.section_color(marker_color), tags="ink")
            right = width - size(4)
            if accents or hover_terms or links:
                x, y = line_x, line_y
                boxes = []  # screen areas of highlighted terms for the glossary tooltips
                link_boxes = []
                for word_start, word_end, parts, destinations, hover in words:
                    span = value[word_start:word_end]
                    ink_font = lead_font if word_start < len(prefix) else font
                    advance = ink_font.measure(span)
                    if x > line_x and x + advance > right:
                        x = line_x
                        y += font.metrics("linespace")
                    for a, b, accent in parts:
                        left = x if a == word_start else x + ink_font.measure(value[word_start:a])
                        self._ink(canvas, left, y, value[a:b], ink_font, self.section_color(accent))
                    for start, end, target in destinations:
                        left = x + ink_font.measure(value[word_start:max(word_start, start)])
                        right_edge = x + ink_font.measure(value[word_start:min(word_end, end)])
                        bottom = y + font.metrics("linespace")
                        # extend over the space to the next word of the same name
                        if end > word_end:
                            right_edge += font.measure(" ")
                        link_boxes.append((left, y, right_edge, bottom, target))
                        if self.app.tooltips_enabled:
                            canvas.create_line(left, bottom - 1, right_edge, bottom - 1,
                                               fill=self.section_color(self.theme.accent),
                                               dash=(1, max(2, size(3))), tags=("ink", "link_underline"))
                        hover = None  # the link replaces the glossary tooltip on the same words
                    if hover:
                        start, end = hover
                        left = x + ink_font.measure(value[word_start:max(word_start, start)])
                        right_edge = x + ink_font.measure(value[word_start:min(word_end, end)])
                        bottom = y + font.metrics("linespace")
                        boxes.append((left, y, right_edge, bottom, value[start:end]))
                        if self.app.tooltips_enabled:
                            canvas.create_line(left, bottom - 1, right_edge, bottom - 1,
                                               fill=self.section_color(self.theme.accent),
                                               dash=(1, max(2, size(3))), tags=("ink", "term_underline"))
                    x += advance + font.measure(" ")
                canvas.term_boxes = boxes
                changed = build_spans and getattr(canvas, "link_boxes", ()) != link_boxes
                canvas.link_boxes = link_boxes
                if changed:
                    self._schedule_targets()
                if boxes or link_boxes:
                    self.app.term_tips.register(canvas)
            else:
                self._ink(canvas, line_x, line_y, value, font, self.section_color(body_color or color),
                          width=max(20, right - line_x))
            bounds = canvas.bbox("ink")
            if bounds:
                height = max(1, bounds[3] + size(padding))
                if height != canvas.winfo_pixels(canvas.cget("height")):
                    canvas.configure(height=height)

        canvas.bind("<Configure>", draw)
        if links:
            canvas.build_links = bool(build_spans)
            canvas.bind("<ButtonRelease-1>", lambda event: self.open_link_at(canvas, event))
            canvas.bind("<Motion>", lambda event: canvas.configure(
                cursor="hand2" if self.link_at(canvas, event) or getattr(canvas, "invoke", None) else ""))
        canvas.pack(fill="x")
        return canvas

    # Boss and area names in guide texts link to their page -----------------------------------

    def _link_data(self):
        clues = self.app.state.get("routeClues", ())
        bosses = self.companion.data.get("bosses", ()) if self.companion else ()
        key = (id(clues), len(clues), id(bosses))
        if getattr(self, "_link_cache", (None,))[0] != key:
            index = campaign_index(clues)
            areas = {area: act for act, places in index.items() for area in places}
            self._link_cache = (key, link_index(bosses, areas), areas)
        return self._link_cache[1], self._link_cache[2]

    def link_spans(self, value):
        try:
            index, _ = self._link_data()
        except (AttributeError, KeyError, TypeError):
            return []
        return link_spans(value, index, getattr(self, "link_skip", ()))

    @staticmethod
    def link_at(canvas, event):
        for left, top, right, bottom, target in getattr(canvas, "link_boxes", ()):
            if left <= event.x < right and top <= event.y < bottom:
                return target
        return None

    def link_title(self, target):
        kind, ident = target
        language = self.app.language
        if kind == "boss":
            boss = next((boss for boss in self.companion.data.get("bosses", ()) if boss["id"] == ident), None)
            return boss_text(boss, language)["name"] if boss else ident
        names = CATALOG.get("areas", {}).get(ident, {})
        return names.get(language) or (names.get("en") if language == "hybrid" else None) or ident.title()

    def open_link_at(self, canvas, event):
        target = self.link_at(canvas, event)
        if target is None:
            return False
        return self.open_link(target)

    def open_link(self, target):
        kind, ident = target
        if kind == "item":
            key, phase, slot = ident
            self.app.show_build_guide(key, phase, gear_slot=slot)
            return True
        if kind == "boss":
            boss = next((boss for boss in self.companion.data.get("bosses", ()) if boss["id"] == ident), None)
            if boss:
                self._show_boss(boss)
            return bool(boss)
        if not self.allows("campaign_tools"):
            return False
        if kind in ("gem", "term", "node"):
            entry = self.app.term_tips.build_lexicon_entry(target)
            if entry:
                self.guide_section = "lookup"
                self._style_tabs()
                self._set_lookup("lexicon", query="", entry=entry)
            return True
        act = self._link_data()[1].get(ident)
        if act:
            self.lookup_category, self.lookup_query, self.lookup_entry = "campaign", "", None
            self.lookup_campaign_result, self.lookup_page = False, 0
            self.lookup_choice = act, ident
            if self.guide_section == "lookup":
                self.refresh_guide()
            else:
                self.select_guide_section("lookup")
        return True

    def campaign_area_for_layout(self, ident):
        state = self.app.state
        index = campaign_index(state.get("routeClues", ()))
        for areas in index.values():
            for key, name in areas.items():
                if campaign_layout_id(CATALOG, name, area_clues(state, name)) == ident:
                    return key
        return None

    def pack_task(self, parent, value, task, *, on_checked=None, **options):
        if not task or not self.app.checklist_enabled:
            return self.pack_message(parent, value, **options)
        done = self.app.checklist["checked"].get(task, False)
        options.pop("marker", None)
        row = self.pack_message(parent, value, check_state=done, **options)
        row.configure(cursor="hand2", takefocus=True)

        def toggle():
            if self.app.check_item(task, not done):
                if on_checked:
                    on_checked(not done)
                self.update(self.app.state)

        row.invoke = toggle
        row.bind("<ButtonPress-1>", lambda event: row.focus_set())
        row.bind("<ButtonRelease-1>", lambda event: self.open_link_at(row, event) or (toggle()
                 if 0 <= event.x < row.winfo_width() and 0 <= event.y < row.winfo_height() else None))
        row.bind("<space>", lambda event: toggle())
        row.bind("<Return>", lambda event: toggle())
        return row

    def _begin_gesture(self, operation, event):
        if not self.app.click_through:
            self.layout.begin(operation, event)

    def _move_gesture(self, event):
        if not self.app.click_through:
            self.layout.move(event)

    def zoom(self, step):
        self.layout.zoom(step)
        self._style_chrome()
        self._draw_header()
        if self.content_hidden:
            self.window.update_idletasks()
            self.layout.collapsed_height = self.shell.winfo_reqheight() + self.layout.px(10)
            self.layout.place(self.layout.x, self.layout.y, self.layout.width, self.layout.collapsed_height)
        if self.app.settings_open():
            self.app.settings.sync_zoom(self)
        self.refresh_guide()

    def _refit_route(self, event=None):
        if not self.measuring:
            self.measuring = self.window.after_idle(self._flow_route)

    def _route_scroll_extent(self, first, last):
        if self.route.winfo_ismapped():
            self.route_scroll.extent(first, last)
        self._schedule_targets()

    def height_limit(self):
        layout = self.layout
        return layout.height_limit((layout.x, layout.y, layout.x+layout.width, layout.y+layout.height))

    def fit_height(self, wanted):
        layout = self.layout
        if self.content_hidden:
            return
        if not self.window.winfo_ismapped() or layout.gesture:
            return
        bottom = layout._work_area(layout.x, layout.y, layout.width, layout.height)[3]
        limit = min(self.height_limit(), self.app.prefs.get(HUD_HEIGHT_LIMIT, self.height_limit()))
        minimum = layout.px(HUD_MIN_SIZE[1] * layout.scale / 100)
        height = min(limit, max(minimum, min(int(wanted), bottom-layout.y)))
        if layout.height != height:
            layout.place(layout.x, layout.y, layout.width, height)

    def _flow_route(self):
        self.measuring = None
        if self.content_hidden or not self.route.winfo_ismapped():
            return
        width = self.route_canvas.winfo_width()
        height = self.body.winfo_height()
        if width <= 1 or height <= 1:
            return
        footer_buttons = self.route_links.winfo_children()
        arrow_width = self.route_scroll.winfo_reqwidth()
        for button in footer_buttons:
            if "wraplength" not in button.keys():
                continue
            wrap = max(1, width - arrow_width - self.layout.px(16))
            if button.winfo_pixels(button.cget("wraplength")) != wrap:
                button.configure(wraplength=wrap)
        self.route_canvas.itemconfigure(self.route_window, width=width)
        top = self.body.winfo_rooty() - self.window.winfo_rooty()
        if self.search_categories is not None:
            layout = self.layout
            bottom = layout._work_area(layout.x, layout.y, layout.width, layout.height)[3]
            limit = self.height_limit()
            usable = min(limit, self.app.prefs.get(HUD_HEIGHT_LIMIT, limit), bottom - layout.y)
            if layout.gesture and layout.gesture[0] == "resize":
                usable = min(usable, layout.height)
            self.search_categories.fit(width, usable - top)
        content_height = self.route_rows.winfo_reqheight()
        footer = self.route_links.winfo_reqheight()
        self.fit_height(top + self.layout.px(5) + footer + content_height)
        space = height - footer
        view_height = min(max(1, space), content_height)
        if self.route_canvas.winfo_pixels(self.route_canvas.cget("height")) != view_height:
            self.route_canvas.configure(height=view_height)
        tail = max(0, self.route_scroll.winfo_reqheight() + 3 - footer) if content_height > space else 0
        self.route_canvas.configure(scrollregion=(0, 0, width, content_height + tail))
        self._schedule_targets()

    def scroll_guide(self, event):
        delta = {4: 120, 5: -120}.get(getattr(event, "num", None), getattr(event, "delta", 0))
        self.scroll_by(delta)

    def scroll_by(self, delta):
        if self.content_hidden:
            return
        widget = self._scroll_widget()
        if not delta or widget.yview() == (0.0, 1.0):
            return
        total = self.wheel_remainder + delta
        steps, remainder = divmod(abs(total), 120)
        sign = 1 if total >= 0 else -1
        self.wheel_remainder = sign * remainder
        if steps:
            widget.yview_scroll(-sign * steps * (3 if widget is self.endgame.text else 1), "units")
        self._schedule_targets()

    def select_guide_section(self, section):
        if self.section_available(section) and section != self.guide_section:
            self.guide_section = section
            self._style_tabs()
            self.refresh_guide()

    def open_atlas_tab(self, tab, anchor=None):
        if not self.lookup_category_available("atlas"):
            return
        if self.endgame.tab != tab:
            self.endgame.page = 0
        if anchor and tab == "quests":
            self.endgame.select_quest_target(anchor)
        self.endgame.tab = tab
        self.endgame.details = False
        self.guide_section = "lookup"
        self._set_lookup("atlas", query="")

    def refresh_guide(self):
        self.last_content = None
        if self.showing_atlas:
            self.endgame.invalidate()
        self.update(self.app.state)

    def route_term_colors(self, bosses):
        colors = {term_key(boss_text(boss, self.app.language)["name"]): GOLD for boss in bosses}
        colors.update({name: ROLE_COLORS[TERM_CATALOG[ident]["role"]]
                       for name, ident in term_aliases(self.app.language).items()})
        return colors

    def _layout_image(self, parent, filename):
        try:
            original = tk.PhotoImage(master=parent, file=str(BRAND_IMAGES / filename))
        except tk.TclError as error:
            if filename not in self.missing_layout_images:
                logging.warning("Kampagnenbild %s konnte nicht geladen werden: %s", filename, error)
                self.missing_layout_images.add(filename)
            return
        self.missing_layout_images.discard(filename)
        label = tk.Label(parent, image=original, anchor="w",
                         bg=getattr(parent, "guide_card_color", self.hud_bg), bd=0, padx=0, pady=0)
        label.image = original

        def fit(event):
            scale = max(1, min(8, event.width * 8 // original.width()))
            if scale != getattr(label, "scale", 8):
                label.scale = scale
                label.image = original if scale == 8 else original.zoom(scale).subsample(8)
                label.configure(image=label.image)

        label.bind("<Configure>", fit)
        label.pack(fill="x", padx=4, pady=(2, 5))

    def editor_colors(self, row):
        return {phrase: ROLE_COLORS[role]
                for phrase, role in guide_edit_roles(row, self.app.language).items() if role in ROLE_COLORS}

    def editor_markup(self, row):
        return {"manual_colors": self.editor_colors(row),
                "term_refs": row.get("termRefs", {}).get(self.app.language, {})}

    def _route_rows(self, matches, bosses, goal, zone):
        short = self.guide_mode == "veteran"
        parent = self.route_rows
        language = self.app.language
        self.link_skip = {("area", zone_key(zone))}  # the page itself needs no link
        goal_clue = next((clue for clue in matches if clue.get("cue") == goal), None) if goal else None
        translations = CATALOG.get("routes", {})
        matches = [{**clue, **translations.get(clue["id"], {}).get(language, {})} for clue in matches]
        colors = self.route_term_colors(bosses)
        diagrams = CATALOG.get("areaLayouts", {})
        diagram_id = campaign_layout_id(CATALOG, zone, matches)
        diagram = diagrams.get(diagram_id, {})
        self.structured_guide = bool(diagram_id)
        self.integrated_tasks = set(diagram.get("removedChecks", {}).get(self.guide_mode, ()))
        zone_id = matches[0]["id"] if matches else zone_key(zone)
        towns = CATALOG.get("townTips", {})
        town = next((towns[clue["id"]] for clue in matches if clue["id"] in towns), None)
        if town is None:
            town = next((entry for entry in towns.values() if zone_key(zone) in entry["zones"]), None)
        checked = self.app.checklist["checked"]
        groups = []
        hidden = self.app.prefs.get("hidden_sections", [])
        removed_tips = "Tipps" in diagram.get("removedHeadings", {}).get(self.guide_mode, ())
        checklist_enabled = self.app.checklist_enabled
        visible = True
        context = (self.guide_section, zone_id, self.app.checklist.get("character"), self.app.checklist.get("runId"))
        if getattr(self, "review_context", None) != context:
            self.review_context = context
            self.review_sections = set()
            self.folded_sections = {"Tipps"} if town else set()
            if diagram.get("sharedSections"):
                self.folded_sections.update(s["heading"] for s,meta in sections_for_mode(diagram,self.guide_mode) if meta.get("collapsed"))
            self.town_tip_index = -1
            self.review_completed = False
        hide_completed = checklist_enabled and self.app.prefs.get("checklist_hide_completed", False)
        fold_completed = checklist_enabled and self.app.prefs.get("checklist_fold_completed", True)

        def toggle_section(ident, closed):
            if closed:
                self.folded_sections.discard(ident)
                self.review_sections.add(ident)
            else:
                self.review_sections.discard(ident)
                self.folded_sections.add(ident)
            self.update(self.app.state, force=True)

        def route_message(value, *, heading=False, task=None, boss_ref=None, section_label=None, **options):
            nonlocal visible
            step_id = task or ""
            if task:
                self.integrated_tasks.add(task)
            if heading:
                category = "Quest" if value == "Questbelohnungen" else value
                visible = category == "Checkliste" or category not in hidden
                if not visible:
                    return
                ident = value
                button, body = self.guide_card(parent, options.get("tone", "gold"))
                groups.append((ident, section_label or ui_text(value, language), button, body, []))
                return
            if not visible:
                return
            container = groups[-1][3] if groups else parent
            if task and checklist_enabled and groups:
                groups[-1][4].append(task)
            if value.startswith("Optional") and options.get("marker"):
                options["tone"] = "optional"
            font = self.title_font(13, "bold") if heading else self.ui_font(11)
            if language != "hybrid":
                value = ui_text(value, language)
                if not heading:
                    options.setdefault("term_colors", colors)
                    options.setdefault("body_color", self.theme.text)
            marker = ""
            boss_step = CATALOG.get("bossSteps", {}).get(step_id, {})
            boss_id = boss_ref or (step_id.removeprefix("boss:") if step_id.startswith("boss:") else boss_step.get("id"))
            if boss_id and boss_step.get("mode", self.guide_mode) == self.guide_mode:
                marker, shade = "⚔ BOSS", BOSS_MARKER
            elif step_id.endswith("-waypoint") or re.match(
                    r"^(?:(?:aktiviere den|activate(?: the)?) )?(?:wegpunkt|waypoint|waystone)\b", value, re.I):
                marker, shade = "◆", INFO
            if marker:
                value = marker + " · " + value if marker != "◆" else marker + "  " + value
                options.pop("marker", None)
                if self.app.card_accents in {"headings", "both"}:
                    options["manual_colors"] = {**(options.get("manual_colors") or {}), marker: shade}
            section_id, section_tasks = (groups[-1][0], groups[-1][4]) if groups else (None, [])

            def checked_row(done):
                if done and all(key == task or checked.get(key) for key in section_tasks):
                    self.review_sections.discard(section_id)

            self.pack_task(container, value, task, on_checked=checked_row, font=font, **options)

        def finish_sections():
            has_completed = False
            for ident, title, button, body, tasks in groups:
                complete = bool(tasks) and all(checked.get(key) for key in tasks)
                has_completed |= complete
                if not complete:
                    self.review_sections.discard(ident)
                auto_closed = fold_completed and complete and not self.review_completed and ident not in self.review_sections
                closed = ident in self.folded_sections or auto_closed
                button.configure(text=("▸ " if closed else "▾ ") + title,
                                 command=lambda i=ident, c=closed: toggle_section(i, c))
                if hide_completed and complete and not self.review_completed:
                    button.master.pack_forget()
                elif closed:
                    body.pack_forget()
            if hide_completed and (has_completed or self.review_completed):
                labels = ("Erledigte ausblenden", "Hide completed") if self.review_completed else (
                    "Erledigte anzeigen", "Show completed")
                def toggle_review():
                    self.review_completed = not self.review_completed
                    self.update(self.app.state, force=True)
                self.small_button(parent, labels[language == "en"], toggle_review).pack(anchor="w", pady=(4, 0))

        def route_field(clue, field, *, prefix="", task=None, **options):
            original = clue.get(field) or ""
            edit = guide_edit("routeEdits", clue["id"], field)
            route_message(prefix + edit.get(language, original), task=task or hud_check_id("route-field", clue["id"], field),
                          **self.editor_markup(edit), **options)

        def render_town_tips():
            if not town or removed_tips:
                return
            route_message("Tipps", tone="gameplay_title", heading=True)
            if not visible:
                return
            pool = CATALOG["townTipPool"]
            mode = "veteran" if short else "basis"
            def town_tip(tip_id):
                line = pool[tip_id][mode]
                route_message(line[language], task=hud_check_id("town-tip", tip_id), tone="gameplay_title", marker=True,
                              body_color=self.theme.text, term_colors=colors, **self.editor_markup(line))
            for tip_id in town["defaults"]:
                town_tip(tip_id)
            extras = town["more"]
            if not extras:
                return
            if checklist_enabled:
                groups[-1][4].extend(hud_check_id("town-tip", tip_id) for tip_id in extras)
            index = self.town_tip_index
            if index >= 0:
                parent = groups[-1][3]
                tk.Frame(parent, bg=self.theme.edge, height=1).pack(fill="x", padx=4, pady=(6, 2))
                route_message(ui_text("Zusatz-Tipp", language), tone="info", points=10)
                town_tip(extras[index])
            label = "Weitere Tipps" if index < 0 else "Nächster Tipp" if index < len(extras) - 1 else "Zusatz-Tipp schließen"
            def next_tip():
                self.town_tip_index = index + 1 if index < len(extras) - 1 else -1
                self.update(self.app.state, force=True)
            self.small_button(groups[-1][3], ui_text(label, language), next_tip).pack(anchor="w", padx=4, pady=4)

        self.render_town_tips = render_town_tips
        self.finish_sections = finish_sections
        self.section_row = route_message
        if not matches and hub_kind(zone) == "town" and not town:
            self.pack_task(parent, ui_text("Prüfe im Questlog, mit wem du im Lager sprechen sollst und in welches Gebiet es weitergeht.", language),
                           hud_check_id("town-questlog", zone_key(zone)))
            return
        colors.update({name: ROLE_COLORS[TERM_CATALOG[ident]["role"]]
                       for name, ident in AREA_TERM_ALIASES.get(diagram_id, {}).items()})
        if "sections" in diagram:
            for section, meta, lines in campaign_section_rows(diagram, self.guide_mode):
                image = (meta.get("image") or {}).get("asset","").split("/")[-1] if meta else (section.get("image") if not short else None)
                if lines or image or (diagram.get("template") and meta):
                    route_message(section["heading"], tone=meta.get("tone",section["tone"]), heading=True,
                                  section_label=meta.get("title",{}).get(language))
                    untracked = 0
                    for line in lines:
                        task = line.get("checkId")
                        paragraph = line.get("kind") == "paragraph"
                        if not task and not paragraph:
                            task = hud_check_id("area", diagram_id, section["heading"], untracked)
                            untracked += 1
                        route_message(line[language], task=task, boss_ref=line.get("bossId"), tone=meta.get("tone",section["tone"]), marker=not paragraph,
                                      body_color=self.theme.text, term_colors=colors,
                                      **self.editor_markup(line))
                    if image and visible:
                        self._layout_image(groups[-1][3], image)
            if diagram_id in {"a2-well", "a2-abyssal-depths"}:
                label = display_label(("Abgrund im Lexikon", "Abyss im Lexikon", "Abyss in the glossary"), language)
                target = "website.abyss"
                if self.lookup_category_available("lexicon") and target in self.app.website_lexicon():
                    action = lambda: self.open_link(("term", target))
                else:
                    url = web_url(language, "begriff-abyss", thema="league")
                    action = lambda: webbrowser.open(url)
                self.small_button(parent, label, action).pack(anchor="w", pady=4)
            if bosses:
                self._boss_guide_title()
                for boss in bosses:
                    self._boss_link(boss)
            return
        if diagram and diagram.get("landmarks"):
            def landmark_line(line, **options):
                route_message(line[language], body_color=self.theme.text, term_colors=colors,
                              **self.editor_markup(line), **options)

            if short:
                route_message("Layout", tone="info", heading=True)
                landmark_line(diagram["compact"], task="route:" + diagram_id, tone="info", marker=True)
                for index, stop in enumerate(diagram["landmarks"]):
                    landmark_line(stop["compact"], task=stop.get("checkId") or hud_check_id("landmark", diagram_id, index),
                                  tone="info", marker=True)
            else:
                route_message("Layout", tone="info", heading=True)
                landmark_line(diagram["text"], task="route:" + diagram_id, tone="info", marker=True)
                for index, stop in enumerate(diagram["landmarks"]):
                    landmark_line(stop["body"], task=stop.get("checkId") or hud_check_id("landmark", diagram_id, index),
                                  tone="info", marker=True)
                if visible:
                    self._layout_image(groups[-1][3], diagram["image"])
            route_message("Optionale Ziele", tone="optional", heading=True)
            for index, stop in enumerate(diagram["optionalStops"]):
                landmark_line(stop["compact" if short else "body"],
                              task=stop.get("checkId") or hud_check_id("landmark-optional", diagram_id, index),
                              tone="optional", marker=True)
            for boss in bosses:
                self._boss_link(boss)
            return
        if short:
            compact_groups = {}
            if diagram:
                compact_groups["Layout"] = [(diagram["compact"][language], hud_check_id("layout", diagram_id), "info", colors, {})]
            terms = colors
            for clue in matches:
                kind = clue.get("kind", "")
                tone = "quest"
                if kind in LAYOUT_KINDS or kind == "Fortschritt":
                    tone = "info"
                elif "permanent" in kind.lower():
                    tone = "success"
                elif kind in BOSS_KINDS:
                    tone = "gold"
                steps = clue.get("compactSteps")
                entry = "compact" if steps is None else "compactSteps"
                colors = terms
                if steps is None:
                    steps = [" → ".join(dict.fromkeys(filter(None, (clue.get("cue"), clue.get("target")))))]
                    cue = clue.get("cue")
                    if cue:
                        colors = {**terms, cue: {"info": INFO, "quest": GUIDE_BLUE, "success": SUCCESS, "gold": GOLD}[tone]}
                step_tasks = {
                    "a1-riverbank": (None, None, "route:a1-riverbank", "boss:miller"),
                    "a1-clearfell-exit": ("run:clearfell-waypoint", "run:clearfell-campsite", "run:devourer-support", None),
                    "a1-clearfell-beira": ("run:beira-reward",),
                }.get(clue["id"], ())
                for index, step in enumerate(steps):
                    if step:
                        task = step_tasks[index] if index < len(step_tasks) else None
                        heading = "Layout" if tone == "info" else "Quest"
                        if step.startswith("WASD"):
                            heading = "Settings / Gameplay"
                        elif task in ("run:clearfell-campsite", "run:devourer-support") or kind == "Optionaler Loot":
                            heading = "Optionale Ziele"
                        elif tone == "success":
                            heading = "Permanenter Bonus"
                        elif task == "route:a1-riverbank":
                            heading = "Questbelohnungen"
                        path = (entry,) if entry == "compact" else (entry, index)
                        edit = guide_edit("routeEdits", clue["id"], *path)
                        compact_groups.setdefault(heading, []).append(
                            (edit.get(language, step), task or hud_check_id("route-field", clue["id"], *path),
                             tone, colors, self.editor_markup(edit)))
            if not matches and goal:
                compact_groups.setdefault("Quest", []).append((goal, hud_check_id("goal", zone_id, goal), "quest", colors, {}))
            heading_tones = {"Layout": "info", "Optionale Ziele": "optional", "Permanenter Bonus": "success",
                             "Settings / Gameplay": "gameplay_title"}
            for heading, rows in compact_groups.items():
                route_message(heading, heading=True, tone=heading_tones.get(heading, "quest"))
                for step, task, tone, terms, markup in rows:
                    route_message(step, task=task, tone=tone, marker=True, body_color=self.theme.text,
                                  term_colors=terms, **markup)
            for boss in bosses:
                self._boss_link(boss)
            return

        exit_clue = next((clue for clue in matches if clue.get("mudBurrowTip")), None)
        if exit_clue:
            route_message("Layout", tone="info", heading=True)
            route_field(exit_clue, "instruction", task="run:clearfell-waypoint",
                          tone="info", marker=True, highlight=("The Mud Burrow", "The Grelwood"))

            for clue in matches:
                if clue.get("id") == "a1-clearfell-beira":
                    route_message("Permanenter Bonus", tone="success", heading=True)
                    route_field(clue, "instruction", task="run:beira-reward", tone="gold", marker=True, highlight="Beira of the Rotten Pack")
            route_message("Optionale Ziele", tone="optional", heading=True)
            route_field(exit_clue, "campsiteTip", task="run:clearfell-campsite", tone="optional", marker=True, body_color=self.theme.text, term_colors=colors)
            route_field(exit_clue, "mudBurrowTip", task="run:devourer-support", tone="optional", marker=True, body_color=self.theme.text, term_colors=colors)
            self._route_boss_links(bosses, set(), route_message)
            return

        gameplay = [clue for clue in matches if clue.get("gameplayTip")]
        if gameplay:
            route_message("Settings / Gameplay", tone="gameplay_title", heading=True)
            for clue in gameplay:
                route_field(clue, "gameplayTip", tone="gameplay", marker=True)
        quests = quest_clues(matches)
        layouts = [clue for clue in matches if clue.get("kind") in LAYOUT_KINDS]
        if not layouts and quests and quests[0].get("kind") == "Fortschritt":
            layouts = quests[:1]
        if layouts or diagram:
            route_message("Layout", tone="info", heading=True)
        if diagram and visible:
            route_message(diagram["text"][language], tone="info", marker=True,
                          task=hud_check_id("layout", diagram_id),
                          highlight=("Red Vale", "Roten Tal", "äußeren Ecken", "outer corner"))
            self._layout_image(groups[-1][3] if groups else parent, diagram["image"])
        for clue in layouts:
            field = "instruction" if clue.get("instruction") else "cue"
            route_field(clue, field, tone="info", marker=True, highlight=clue.get("highlight"))
            if clue.get("status") == "test":
                route_message("Je nach Kartenlayout", tone="muted")
        riverbank = any(clue.get("id") == "a1-riverbank" for clue in matches)
        if riverbank:
            route_message("Questbelohnungen", tone="quest", heading=True)
            route_message("Waffe und erster Gem", task="route:a1-riverbank", tone="quest", marker=True, body_color=self.theme.text, term_colors=colors)
            quests = [clue for clue in quests if clue.get("id") != "a1-riverbank"]
        elif goal or quests:
            route_message("Quest", tone="quest", heading=True)
        if goal and not riverbank:
            edit = guide_edit("routeEdits", goal_clue["id"], "cue") if goal_clue else {}
            task = (hud_check_id("route-field", goal_clue["id"], "cue") if goal_clue else
                    hud_check_id("goal", zone_id, goal))
            localized_goal = translations.get(goal_clue["id"], {}).get(language, {}).get("cue", goal) if goal_clue else goal
            route_message(edit.get(language, localized_goal), task=task, tone="quest", marker=True,
                          **self.editor_markup(edit))
        rewards = set()
        for clue in quests:
            permanent = "permanent" in clue.get("kind", "").lower()
            tone = "success" if permanent else "text"
            cue = clue.get("cue", "")
            instruction = clue.get("instruction") or cue
            if cue and cue != goal:
                route_field(clue, "cue", tone="success" if permanent else "quest")
            if clue not in layouts and instruction != goal:
                route_field(clue, "instruction" if clue.get("instruction") else "cue",
                            tone=tone, marker=True, highlight=clue.get("highlight"))
            target = clue.get("target") or ""
            reward = permanent or any(item_spans(target)) or clue.get("kind") == "Optionaler Loot"
            if target and (reward or clue not in layouts):
                prefix = ""
                if reward:
                    rewards.add(reward_key(target))
                    prefix = "Spätere Belohnung · " if clue.get("kind") == "Permanenter Bonus vorbereitet" else "Belohnung · "
                route_field(clue, "target", prefix=prefix, tone="success" if permanent else "muted")
        if not (goal or quests or bosses or layouts):
            self.pack_message(parent, "Starte PoE2 und betrete ein Gebiet.", tone="muted")
        self._route_boss_links(bosses, rewards, route_message)

    def _route_boss_links(self, bosses, rewards, route_message):
        manor_footer_shown = False
        for boss in bosses:
            if boss.get("id") in {"candlemass", "geonor"} and manor_footer_shown:
                pass
            elif boss.get("id") in {"miller", "beira", "rust-king", "ervig", "lachlann", "asinia", "draven", "crowbell", "executioner", "candlemass", "geonor", "king-mists"}:
                self._boss_guide_title()
                manor_footer_shown = boss.get("id") in {"candlemass", "geonor"}
            elif boss.get("reward") and reward_key(boss["reward"]) not in rewards:
                language = self.app.language
                label = {"drop": "Beute", "quest": "Questbelohnung", "nearby": "In der Nähe",
                         "progress": "Fortschritt"}.get(boss.get("rewardKind"), "Belohnung")
                localized = boss_text(boss, language)
                edit = guide_edit("bossEdits", boss["id"], "rewardText")
                route_message(ui_text(label, language) + " · " + edit.get(language, localized.get("rewardText") or localized["reward"]), tone="muted",
                              task=hud_check_id("boss-reward", boss["id"]),
                              **self.editor_markup(edit))
            self._boss_link(boss)

    def _boss_guide_title(self):
        font = self.ui_font(11)
        title = ui_text("↓ Detaillierter Boss-Guide", self.app.language)
        tk.Label(self.route_links, text=title, font=font, bg=self.hud_bg, fg=self.theme.text).pack(
            anchor="w", pady=(font.metrics("linespace"), 0))

    def _boss_link(self, boss):
        label = boss_text(boss, self.app.language)["name"]
        button = self.small_button(self.route_links, "⚔ BOSS · " + label, lambda: self._show_boss(boss))
        if self.app.card_accents in {"headings", "both"}:
            button.configure(fg=self.section_color(BOSS_MARKER))
        button.pack(anchor="w", pady=(3, 0))

    def _show_boss(self, boss, *, automatic=False):
        self.app.auto_campaign_boss = boss["id"] if automatic else ""
        if self.guide_section != "boss":
            self.boss_return_section = self.guide_section
        self.companion.boss_id = boss["id"]
        if self.guide_section == "boss":
            self.refresh_guide()
        else:
            self.select_guide_section("boss")

    def _close_boss(self):
        section = self.boss_return_section
        if not self.section_available(section):
            section = "quest"
        self.select_guide_section(section)

    def show_boss_area(self, boss):
        if not self.section_available("lookup") or boss["act"] not in CAMPAIGN_ACTS:
            return
        act = boss["act"]
        self.lookup_choice = act, zone_key(boss["zone"])
        self.lookup_campaign_result = True
        self.lookup_entry = None
        self.select_guide_section("lookup")

    def update(self, state, *, force=False):
        if self.window.winfo_ismapped():
            self.layout.enforce_width()
        progress = state.get("progress", {})
        zone = str(progress.get("currentAct", "") or "")
        title = CATALOG.get("areas", {}).get(zone.casefold().removeprefix("the "), {}).get(self.display_language, zone)
        if self.welcome_sample:
            title = "Buildforge · Preview" if self.display_language == "en" else "Buildschmiede · Vorschau"
        if title != self.area_name:
            self.area_name = title
            self._draw_header()
        level_check = state.get("levelCheck", {})
        if not self.welcome_sample:
            self._update_metrics(state, level_check)
        self._style_tabs()
        section = "welcome" if self.welcome_sample else self.guide_section
        lookup_route = section == "lookup" and (
            self.lookup_campaign_result or (self.lookup_category == "campaign" and not self.lookup_query)
        )
        if section == "lookup":
            index = campaign_index(state.get("routeClues", ()))
        if lookup_route:
            act, area = self.lookup_choice or ("", "")
            if area not in index.get(act, {}):
                fallback_act = next(iter(index))
                act, area = next(((act, zone_key(zone)) for act, areas in index.items() if zone_key(zone) in areas),
                                 (fallback_act, next(iter(index[fallback_act]))))
                self.lookup_choice = act, area
            zone = index[act][area]
        if section == "lookup" and self.showing_atlas:
            if not self.endgame.winfo_manager():
                self.route_scroll.place_forget()
                self.route.pack_forget()
                self.route_links.pack_forget()
                self.atlas_controls.pack(fill="x", padx=self.layout.px(6))
                self.endgame.pack(fill="both", expand=True)
                self.wheel_remainder = 0
            self.atlas_back.configure(text="← Categories" if self.app.language == "en" else "← Kategorien",
                                      **self._button_colors())
            self.atlas_controls.reflow()
            encounter = state.get("bossEncounter") or {}
            self.endgame.set_encounter(encounter if encounter.get("phase") == "endgame" else None)
            checks = self.app.checklist if self.app.checklist_enabled else None
            self.endgame.display(self.guide_mode, checks)
            self._schedule_targets()
            return
        if self.endgame.winfo_manager():
            self.atlas_controls.pack_forget()
            self.endgame.pack_forget()
            self.route.pack(fill="x")
            self.route_links.pack(fill="x")
            self.wheel_remainder = 0

        matches = area_clues(state, zone)
        bosses = self.companion.bosses_here(zone)
        checks = self.app.checklist
        tracked = checks["checked"] if self.app.checklist_enabled and section != "lookup" else {}
        goal = next_objective({} if section == "lookup" else progress, matches, bosses, tracked)
        level = level_check.get("characterLevel") or max(1, int(progress.get("level", 1) or 1))
        respec_level = min(100, max(1, level))
        showing_respec = section == "lookup" and self.lookup_entry and self.lookup_entry.target == "respec"
        build = self.companion.current_build() if section == "build" else None
        stage = self.companion.stage_for_level(build, level) if build else None
        key = (section, zone, self.guide_mode, self.app.language, goal, matches,
               (build["id"], stage["id"]) if build else None,
               self.companion.boss_id if section == "boss" else None,
               checks if self.app.checklist_enabled and (section in {"quest", "boss", "build"} or lookup_route)
               else None,
               (self.lookup_choice, self.lookup_category, self.lookup_query, self.lookup_entry, self.lookup_page,
                self.lookup_campaign_result)
               if section == "lookup" else None, self.welcome_sample,
               respec_level if showing_respec and "level" not in self.app.respec_values else None,
               id(self.app.website_lexicon()), self.app.tooltips_enabled)
        if force or key != self.last_content:
            scroll = self.route_canvas.yview()[0] if self.last_content and key[:3] == self.last_content[:3] else 0
            old_rows, old_links = self.route_rows, self.route_links
            self.search_categories = None
            self.route_rows = tk.Frame(self.route_canvas, bg=self.hud_bg)
            self.route_links = tk.Frame(self.body, bg=self.hud_bg)
            self.route_rows.bind("<Configure>", self._refit_route)
            self.route_links.bind("<Configure>", self._refit_route)
            if section == "welcome":
                self._render_welcome_sample()
            elif section in {"boss", "build"}:
                if section == "boss":
                    english = self.app.language == "en"
                    if self.boss_return_section == "lookup":
                        label = "← Back to search" if english else "← Zur Suche"
                    else:
                        label = "← Back" if english else "← Zurück"
                    self.small_button(self.route_rows, label, self._close_boss).pack(anchor="w", pady=(0, 4))
                self.companion.render(self.route_rows, section, self.guide_mode, level)
            elif section == "lookup" and not lookup_route:
                self._lookup_controls()
                self._render_lookup(state, index, respec_level)
            else:
                if lookup_route:
                    self._lookup_controls()
                    self._lookup_campaign(index, act, area)
                self._route_rows(matches, bosses, goal, zone)
                self.render_town_tips()
                if section == "quest" and self.app.checklist_enabled and not self.structured_guide:
                    show_checklist(self, state, zone, matches, bosses, checks, integrated=self.integrated_tasks)
                self.finish_sections()
                if zone:
                    client_id = next((ident for ident, name in server.CLIENT_AREA_IDS.items()
                                      if zone_key(name) == zone_key(zone)), None)
                    if client_id:
                        note = guide_edit("areaNotes", client_id, self.guide_mode)
                        text = note.get(self.app.language)
                        if text:
                            self.pack_task(self.route_rows, text, hud_check_id("area-note", client_id), marker=True,
                                           **self.editor_markup(note))
                links = self.route_links.winfo_children()
                if "Boss-Guide" in self.app.prefs.get("hidden_sections", []):
                    for child in links:
                        child.destroy()
                elif links:
                    tk.Frame(self.route_links, bg=self.divider_color, height=self.layout.px(2)).pack(
                        fill="x", before=links[0])
            self.route_canvas.itemconfigure(self.route_window, window=self.route_rows)
            if old_links.winfo_manager():
                self.route_links.pack(fill="x", before=old_links)
            old_links.destroy()
            old_rows.destroy()
            self.last_content = key
            self.route_canvas.yview_moveto(scroll)
            self.wheel_remainder = 0
            self._refit_route()
        self._schedule_targets()

    def _render_welcome_sample(self):
        language = self.display_language
        mode = self.guide_mode
        accents = self.welcome_sample.accents
        en, hybrid = language == "en", language == "hybrid"
        compact = mode == "veteran"
        waypoint = "Waypoint" if en or hybrid else "Wegpunkt"
        gem = "Uncut Skill Gem" if en or hybrid else "Ungeschnittene Fertigkeitengemme"
        examples = (
            ("Layout", "info", "◆", waypoint,
             "follow the area edge" if en else "Gebietsrand folgen",
             "Activate it, then follow the edge toward the exit." if en else
             "Aktiviere ihn und folge dann dem Gebietsrand zum Ausgang."),
            ("Permanenter Bonus", "success", "⚔ BOSS", "Beira",
             "+10 % Cold Resistance" if en else "+10 % Kältewiderstand",
             "Defeat Beira and use her quest item." if en else
             "Besiege Beira und benutze ihren Questgegenstand."),
            ("Questbelohnungen", "quest", "", "Renly", gem,
             "Talk to Renly to claim your quest reward." if en else
             "Sprich mit Renly, um die Questbelohnung abzuholen."),
            ("Optionale Ziele", "optional", "", "Mysteriöser Lagerplatz" if not (en or hybrid) else "Mysterious Campsite",
             gem, "Open the chest at the campsite when you pass it." if en else
             "Öffne die Truhe am Lagerplatz, wenn du vorbeikommst."),
        )
        for heading, tone, symbol, target, reward, hint in examples:
            button, body = self.guide_card(self.route_rows, tone)
            button.configure(text="▾ " + ui_text(heading, language), state="disabled",
                             disabledforeground=button.cget("fg"), cursor="arrow")
            lead = f"{symbol}  {target}" if symbol else target
            text = f"{lead} → {reward}" if compact else f"{lead} · {reward}. {hint}"
            colors = self.route_term_colors([])
            if accents in {"headings", "both"} and symbol:
                colors[symbol] = BOSS_MARKER if tone == "success" else INFO
            colors[target] = {"info": INFO, "success": GOLD, "quest": GUIDE_BLUE, "optional": INFO}[tone]
            if tone == "success":
                colors[reward] = SUCCESS
            self.pack_message(body, text, tone=tone, body_color=self.theme.text,
                              term_colors=colors, check_state=tone == "info")

    def _lookup_controls(self):
        language = self.app.language
        english = language == "en"
        parent = self.route_rows
        gap = self._icon_pixels(4)
        if self.lookup_entry and self.lookup_entry.target == "affixes":
            back = f'← {display_label(CATEGORIES["tools"], language)}'
            self.small_button(parent, back, lambda: self._set_lookup("tools", query="")).pack(
                anchor="w", pady=(0, gap))
            return
        if self.lookup_category == "lexicon" and self.lookup_entry and not self.lookup_campaign_result:
            return  # The article already provides its own back-to-list button.
        category = self.lookup_category
        first_steps = not self.allows("campaign_tools")
        actions = FlowRow(parent, bg=self.hud_bg, gap=gap, distribute=True)
        details = self.lookup_entry is not None or self.lookup_campaign_result
        if details or category != "all" or not first_steps:
            actions.pack(fill="x", pady=(0, gap))
        if details:
            self.small_button(actions, "← Back to list" if english else "← Zur Liste",
                              lambda: self._set_lookup(page=self.lookup_page))
            return
        if category == "constructs":
            self.small_button(actions, "← FAQ", lambda: self._set_lookup("faq", query=""))
        elif category == "faq" and self.lookup_faq_topic:
            self.small_button(actions, "← All questions" if english else "← Alle Fragen",
                              lambda: self._set_faq_topic(""))
        elif category == "faq" and first_steps:
            self.small_button(actions, "← " + display_label(CATEGORIES["tips"], language),
                              lambda: self._set_lookup("tips", query=""))
        elif category != "all":
            self.small_button(actions, "← Categories" if english else "← Kategorien",
                              lambda: self._set_lookup("all"))
        if category != "all" or not first_steps:
            search = self.small_button(actions, "Search" if english else "Suchen", self._open_lookup_dialog)
            self._set_hud_icon(search, "lookup", self._icon_pixels(13), self.theme.accent)
            search.configure(compound="left", anchor="w", bg=self.theme.field_color, padx=self.layout.px(6))
            query = self.lexicon.query if category == "lexicon" else self.lookup_query
            if query:
                query_row = tk.Frame(parent, bg=self.hud_bg)
                query_row.pack(fill="x", pady=(0, gap))
                self.small_button(query_row, "Clear" if english else "Leeren",
                                  lambda: self._set_lookup_query("")).pack(side="right")
                self.pack_message(query_row, query, tone="muted", points=10)
        if category != "all":
            return
        categories = {} if first_steps else {"all": ("Alles", "Alles", "All")}
        categories.update((key, names) for key, names in CATEGORIES.items()
                          if key != "constructs" and not (key == "faq" and first_steps)
                          and self.lookup_category_available(key))
        keys = list(categories)

        def choose(index):
            category = keys[index]
            if category == "lexicon" and self.lookup_query and not first_steps:
                self.lexicon.query, self.lexicon.base = self.lookup_query, None
                self.lexicon.group, self.lexicon.facet = "all", ""
            self._set_lookup(category, query="" if first_steps or category in {"tools", "atlas"} else None)

        self.search_categories = SearchCategories(parent, self,
            [display_label(names, language) for names in categories.values()],
            None if first_steps else keys.index(category), choose, "Category" if english else "Kategorie")
        self.search_categories.pack(fill="x", pady=(0, gap))

    def _set_lookup(self, category=None, *, query=None, entry=None, page=0):
        if not self.section_available("lookup"):
            return
        if category is not None and not self.lookup_category_available(category):
            return
        if entry is not None and not self.lookup_entry_available(entry):
            return
        if category is not None:
            if category != self.lookup_category:
                self.lookup_faq_topic = ""
            self.lookup_category = category
        if query is not None:
            self.lookup_query = query[:QUERY_LIMIT].strip()
        self.lookup_entry = entry
        if self.lookup_category != "lexicon" or entry is None:
            self.lexicon.outer_results = None
        self.lexicon.variant_page = 0
        self.lexicon.show_original = False
        self.lookup_campaign_result = False
        self.lookup_page = page
        self.refresh_guide()

    def _set_lookup_query(self, query):
        if self.lookup_category == "lexicon":
            self.lexicon.query = query[:QUERY_LIMIT].strip()
            if self.lexicon.query and self.lexicon.base is None:
                self.lexicon.group, self.lexicon.facet = "all", ""
            self._set_lookup()
        else:
            self._set_lookup(query=query)

    def _set_faq_topic(self, topic):
        self.lookup_faq_topic = topic
        self._set_lookup(query="")

    def _open_lookup_dialog(self):
        language = self.app.language
        title = ("Companion durchsuchen", "Companion durchsuchen", "Search the Companion")
        query = self.lookup_query
        if self.lookup_category == "lexicon":
            title = ("Lexikon durchsuchen", "Lexikon durchsuchen", "Search the lexicon")
            query = self.lexicon.query
        elif self.lookup_category == "faq":
            title = ("Fragen durchsuchen", "Fragen durchsuchen", "Search questions")
        self._open_input_dialog(display_label(title, language), query, self._set_lookup_query,
                                "Search" if language == "en" else "Suchen")

    def open_gif_viewer(self, clip, title):
        if self.lookup_dialog:
            self.lookup_dialog.lift()
            self.lookup_dialog.focus_force()
            return
        layout = self.layout
        left, top, right, bottom = layout._work_area(layout.x, layout.y, layout.width, layout.height)
        width, height = clip.screen.width(), clip.screen.height()
        limit = max(1, min(right - left - layout.px(40),
                           (bottom - top - layout.px(80)) * width // height))
        view_width, view_height = preview_size(width, height, limit, max_zoom=2)
        theme = self.theme
        dialog = tk.Toplevel(clip)
        dialog.withdraw()
        dialog.title(title)
        dialog.transient(self.window)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.configure(bg=theme.panel, padx=layout.px(8), pady=layout.px(8))
        content = tk.Frame(dialog, bg=theme.panel, width=view_width, height=view_height)
        content.pack()
        content.pack_propagate(False)
        AnimatedGif(content, clip.path, background=theme.panel, max_zoom=2).pack(fill="both", expand=True)

        self.track_lookup_dialog(dialog)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.update_idletasks()
        x = left + (right - left - dialog.winfo_reqwidth()) // 2
        y = top + (bottom - top - dialog.winfo_reqheight()) // 2
        dialog.geometry(f"{x:+d}{y:+d}")
        dialog.deiconify()
        if self.app.native:
            dialog.update_idletasks()
            self.app.native.style_dialog(dialog, palette=(theme.edge, theme.panel, theme.text))
        dialog.focus_force()
        self._schedule_targets()

    def _open_input_dialog(self, title, initial, on_submit, confirm, *, validate=None, width=31):
        if self.lookup_dialog:
            self.lookup_dialog.lift()
            self.lookup_dialog.focus_force()
            return
        english = self.app.language == "en"
        theme = self.theme
        dialog = tk.Toplevel(self.window)
        dialog.withdraw()
        dialog.title(title)
        dialog.transient(self.window)
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.configure(bg=theme.panel, padx=12, pady=10)
        tk.Label(dialog, text=title, bg=theme.panel, fg=theme.accent,
                 font=self.ui_font(11, "bold"), anchor="w").pack(fill="x")
        value = tk.StringVar(dialog, initial)
        entry = tk.Entry(dialog, textvariable=value, width=width, font=self.ui_font(11),
                         bg=theme.field_color, fg=theme.text, insertbackground=theme.text,
                         selectbackground=theme.selection_color, selectforeground=theme.selection_text)
        entry.pack(fill="x", pady=8)

        def submit(event=None):
            entered = value.get().strip()
            if validate and not validate(entered):
                dialog.bell()
                entry.focus_set()
                entry.selection_range(0, "end")
                return
            dialog.destroy()
            on_submit(entered)

        controls = tk.Frame(dialog, bg=theme.panel)
        controls.pack(fill="x")
        self.small_button(controls, confirm, submit).pack(side="left")
        self.small_button(controls, "Cancel" if english else "Abbrechen", dialog.destroy).pack(side="right")
        self.track_lookup_dialog(dialog)
        dialog.bind("<Return>", submit)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.update_idletasks()
        x = self.window.winfo_rootx() + (self.window.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.window.winfo_rooty() + self.layout.px(48)
        dialog.geometry(f"{x:+d}{y:+d}")
        dialog.deiconify()
        if self.app.native:
            dialog.update_idletasks()
            self.app.native.style_dialog(dialog, palette=(theme.edge, theme.panel, theme.text))
        entry.focus_force()
        entry.selection_range(0, "end")
        self._schedule_targets()

    def _lookup_campaign(self, index, act, area):
        language = self.app.language
        acts = list(index)

        def choose(act, area):
            self.lookup_choice = act, area
            self.refresh_guide()

        labels = [a if language == "en" else a.replace("Act ", "Akt ") for a in acts]
        self.companion._controls(self.route_rows, labels, acts.index(act),
                                 lambda i: choose(acts[i], next(iter(index[acts[i]]))))
        areas = list(index[act])
        names = [CATALOG.get("areas", {}).get(k, {}).get(language, index[act][k]) for k in areas]
        self.companion._controls(self.route_rows, names, areas.index(area), lambda i: choose(act, areas[i]))

    def _lookup_areas(self, state, index):
        language = self.app.language
        areas = CATALOG.get("areas", {})
        aliases = term_aliases(language)

        def guide_lines(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for row in value:
                    yield from guide_lines(row)
            elif isinstance(value, dict):
                for key, row in value.items():
                    if key not in {"termRefs", "accents"}:
                        yield from guide_lines(row)

        fields = ("cue", "instruction", "note", "target", "veteranText", "compactSteps", "gameplayTip",
                  "layoutSteps", "areaRewards", "campsiteTip", "mudBurrowTip")
        for act, places in index.items():
            for area, canonical in places.items():
                names = areas.get(area, {})
                term = TERM_CATALOG.get(aliases.get(term_key(canonical)), {})
                labels = term_labels(term, language)
                title = names.get(language, labels[0] if labels else canonical)
                content = []
                for clue in area_clues(state, canonical):
                    content.extend(guide_lines([clue.get(field) for field in fields]))
                    ident = clue["id"]
                    for source in ("routes", "routeEdits"):
                        content.extend(guide_lines(CATALOG.get(source, {}).get(ident, {})))
                translated_act = act.replace("Act ", "Akt ")
                yield act, area, title, (canonical, act, translated_act, *names.values(),
                                         *term.get("aliases", ()), *term.get("routeAliases", ())), content

    def _render_lookup(self, state, index, respec_level):
        language = self.app.language
        english = language == "en"
        parent = self.route_rows
        if self.lookup_category == "lexicon":
            render_lexicon(self, parent)
            return
        if self.lookup_entry:
            entry = self.lookup_entry
            if entry.target == "respec":
                render_respec(self, parent, respec_level)
                return
            if entry.target == "regex":
                render_regex(self, parent)
                return
            if entry.target == "affixes":
                render_affix_tool(self, parent)
                return
            if entry.target == "crafting-helper":
                render_craft_helper(self, parent)
                return
            self.pack_message(parent, entry.title, tone="gold")
            if entry.category == "tips" and entry.target in AFFIX_TIPS:
                render_affix_tip(self, parent, entry.target)
            elif entry.category == "builds":
                self.pack_message(parent, entry.target["author"], tone="muted", points=10)
                self.companion.planner_website_button(parent).pack(anchor="w", pady=4)
                self.small_button(parent, "Use in HUD" if english else "Im HUD verwenden",
                                  lambda: self.app.show_build_guide(entry.target["id"])).pack(anchor="w", pady=4)
                preview_stage = (self.companion.stage_for_level(entry.target, respec_level)
                                 if entry.target.get("stages") else {})
                self.build_gem_ids = equipped_gem_ids(preview_stage)
                self.build_reference_context = (entry.target["id"], preview_stage["id"]) if preview_stage else ()
                self.companion._build_overview(parent, ("lookup", entry.target["id"]), entry.target, language)
                for raw in entry.target.get("stages", ()):
                    stage = stage_view(raw, language, keep_references=True)
                    self.build_gem_ids = equipped_gem_ids(stage)
                    self.build_reference_context = (entry.target["id"], stage["id"])
                    body = self.companion._card(parent, ("lookup", entry.target["id"]), stage["id"],
                                                stage["label"], closed=True)
                    lines = [line for key in ("nextSteps", "playstyle", "why", "quests", "skills", "passives", "craft")
                             for line in stage[key]]
                    for line in dict.fromkeys(lines):
                        if line:
                            self.pack_message(body, line, marker=True)
            else:
                for line in entry.details[:1] if entry.category == "faq" else entry.details:
                    if line:
                        self.pack_message(parent, line)
                if entry.category == "faq":
                    self._faq_action(parent, entry.target)
                url = entry.url or (entry.target.get("url") if isinstance(entry.target, dict) else None)
                if url:
                    self.small_button(parent, "Read on buildschmiede.de" if english else "Auf buildschmiede.de lesen",
                                      lambda: webbrowser.open(url)).pack(anchor="w", pady=(4, 0))
                if entry.category == "faq":
                    patch = entry.target["patch"]
                    self.pack_message(parent, ("Game version" if english else "Spielstand") + " · " + patch,
                                      tone="muted", points=9)
            return
        if self.lookup_category == "all" and not self.allows("campaign_tools"):
            return
        if not self.lookup_query and self.lookup_category == "all":
            self.pack_message(parent, "Choose a category or search all local entries." if english else
                              "Wähle eine Kategorie oder durchsuche alle lokalen Einträge.")
            return
        if self.lookup_category == "tips" and not self.lookup_query:
            self.small_button(parent, display_label(CATEGORIES["faq"], language),
                              lambda: self._set_lookup("faq", query="")).pack(anchor="w", pady=4)
        if self.lookup_category == "constructs":
            overview = construct_catalog()
            if overview and not self.lookup_query:
                self.pack_message(parent, overview["hinweis_" + language])
        if self.lookup_category == "builds":
            actions = FlowRow(parent, bg=self.hud_bg, distribute=True)
            actions.pack(fill="x", pady=(0, 5))
            self.companion.planner_website_button(actions)
            self.small_button(actions, "Import build" if english else "Build importieren", self.app.import_build)
        hotkeys = [(self.app.keys.get(action) or ("Off" if english else "Aus"), ui_text(label, language),
                    (label, ui_text(label, "en"))) for action, (label, _) in HUD_HOTKEYS.items()]
        entries = lookup_entries(language, self._lookup_areas(state, index), self.companion.data, hotkeys, self.guide_mode,
                                 website=self.app.website_lexicon(), search_catalogue=self.lookup_category == "all")
        available = (entry for entry in entries if self.lookup_entry_available(entry))
        if self.lookup_category == "faq" and self.lookup_faq_topic:
            available = (entry for entry in available
                         if entry.category == "faq" and entry.target["topic"] == self.lookup_faq_topic)
        matches = find_entries(available, self.lookup_query, self.lookup_category)
        if not matches:
            self.pack_message(parent, "No results" if english else "Keine Treffer")
            return
        if self.lookup_category == "faq" and not self.lookup_query:
            if self.lookup_faq_topic:
                self.pack_message(parent, display_label(FAQ_TOPICS[self.lookup_faq_topic][0], language), tone="gold")
            else:
                self._render_faq_topics(parent, matches, language)
        start = self.lookup_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(matches))
        self.pack_message(parent, f"{start + 1}–{end} / {len(matches)}", tone="muted", points=10)
        for entry in matches[start:end]:
            title = entry.title
            if self.lookup_category == "all":
                title = display_label(CATEGORIES[entry.category], language) + " · " + title
            pick = lambda entry=entry: self._pick_lookup(entry)
            if entry.category == "shortcuts":
                button = self._lookup_shortcut_row(parent, entry.details[0], title, pick)
            else:
                button = self.small_button(parent, title, pick)
                button.configure(anchor="w", justify="left", wraplength=max(1, self.layout.width - self.layout.px(42)))
                button.bind("<Configure>", lambda event: event.widget.configure(wraplength=max(1, event.width - self.layout.px(30))))
            button.pack(fill="x", pady=(0, 2))
        pages = FlowRow(parent, bg=self.hud_bg)
        pages.pack(fill="x", pady=4)
        if start:
            self.small_button(pages, "Previous" if english else "Zurück", lambda: self._set_lookup(page=self.lookup_page - 1))
        if end < len(matches):
            self.small_button(pages, "Next" if english else "Weiter", lambda: self._set_lookup(page=self.lookup_page + 1))

    def _render_faq_topics(self, parent, entries, language):
        topics = {entry.target["topic"] for entry in entries}
        controls = FlowRow(parent, bg=self.hud_bg, gap=self.layout.px(4), distribute=True)
        controls.pack(fill="x", pady=(0, self.layout.px(6)))
        for topic, (names, icon, tone) in FAQ_TOPICS.items():
            if topic not in topics:
                continue
            label = display_label(names, language)
            button = self.small_button(controls, label, lambda topic=topic: self._set_faq_topic(topic))
            tone = self.section_color(tone)
            self._set_hud_icon(button, icon, self._icon_pixels(16), tone)
            button.configure(compound="left", anchor="w", justify="left", wraplength=self.layout.px(150),
                             bg=mix_color(self.theme.control, tone, 0.16), fg=tone, highlightbackground=tone)

    def _faq_action(self, parent, faq):
        language = self.app.language
        english = language == "en"
        target = faq["target"]
        dependency = target["dependency"]
        anchor = target["anchor"]
        if dependency == "constructs" and self.lookup_category_available("constructs"):
            self.small_button(parent, display_label(CATEGORIES["constructs"], language),
                              lambda: self._set_lookup("constructs", query="")).pack(anchor="w", pady=4)
        elif dependency == "atlas" and self.lookup_category_available("atlas"):
            self.small_button(parent, "Atlas quests" if english else "Atlas-Quests",
                              lambda: self.open_atlas_tab("quests", anchor)).pack(anchor="w", pady=4)
        elif target["path"].startswith("/lexikon/") and self.lookup_category_available("lexicon"):
            if dependency == "mechanics" and anchor == "lexikon-filter":
                def league_list():
                    self.lexicon.group, self.lexicon.facet = "league", ""
                    self.lexicon.query, self.lexicon.base = "", None
                    self._set_lookup("lexicon", query="")
                self.small_button(parent, "League mechanics" if english else "Liga-Mechaniken",
                                  league_list).pack(anchor="w", pady=4)
                return
            slug = anchor.removeprefix("begriff-")
            terms = self.app.website_lexicon()
            term = next((t for t in terms.values() if t.get("slug") == slug), None)
            if term:
                local = next(published_terms(language, {term["id"]: term}), None)
                if local:
                    self.small_button(parent, local.title,
                                      lambda: self._pick_lookup(local)).pack(anchor="w", pady=4)
        elif faq.get("build") and self.lookup_category_available("builds"):
            build = next((b for b in self.companion.data.get("builds", ()) if b["id"] == faq["build"]), None)
            if build:
                local = make("builds", build["name"], target=build)
                self.small_button(parent, build["name"],
                                  lambda: self._set_lookup("builds", query="", entry=local)).pack(anchor="w", pady=4)
        elif faq["id"] == "loot-craft-sell" and self.allows("crafting"):
            title = "Crafting Helper" if english else "Crafting-Helfer"
            self.small_button(parent, title,
                              lambda: self._pick_lookup(make("tools", title, "crafting-helper"))).pack(anchor="w", pady=4)

    def _lookup_shortcut_row(self, parent, key, title, action):
        button = self.small_button(parent, "", action)
        button.configure(padx=0, pady=0)
        button.columnconfigure(1, weight=1)
        theme = self.theme
        inset, gap = self.layout.px(8), self.layout.px(10)
        padding = self.layout.px(5)
        label_options = dict(bg=theme.control, anchor="nw", justify="left",
                             bd=0, padx=0, pady=0, cursor="hand2")
        binding = tk.Label(button, text=key, fg=theme.accent, font=self.ui_font(9, "bold"), **label_options)
        description = tk.Label(button, text=title, fg=theme.text, font=self.ui_font(9), **label_options)
        binding.grid(row=0, column=0, sticky="nw", padx=(inset, gap), pady=padding)
        description.grid(row=0, column=1, sticky="nw", padx=(0, inset), pady=padding)

        def click(event):
            if 0 <= event.x < event.widget.winfo_width() and 0 <= event.y < event.widget.winfo_height():
                button.invoke()

        for label in (binding, description):
            label.bind("<ButtonRelease-1>", click)

        def fit(width):
            available = max(3, width - 2 * inset - gap - 4)  # Button border and focus outline.
            key_width = max(1, min(available * 2 // 5, self.layout.px(170)))
            button.columnconfigure(0, minsize=inset + key_width + gap)
            binding.configure(wraplength=key_width)
            description.configure(wraplength=available - key_width)

        fit(self.layout.width - self.layout.px(42))
        button.bind("<Configure>", lambda event: fit(event.width))
        return button

    def _pick_lookup(self, entry):
        if not self.lookup_entry_available(entry):
            return
        if entry.category == "campaign":
            self.lookup_choice = entry.target
            self.lookup_campaign_result = True
            self.refresh_guide()
        elif entry.category == "boss":
            self._show_boss(entry.target)
        elif entry.target == "build-planner-web":
            self.companion.open_planner_website()
        elif entry.category == "tools":
            self._set_lookup("tools", query="", entry=entry)
        elif entry.category == "lexicon":
            if self.lookup_category == "all":
                self.lexicon.outer_results = self.lookup_query, self.lookup_page
            self._set_lookup("lexicon", entry=entry)
        else:
            self._set_lookup(entry=entry, page=self.lookup_page)

    def _update_metrics(self, state, level_check):
        if self.content_hidden:
            return
        clock_text = boss_text = ""
        if self.allows("timers"):
            if self.app.timer_visible:
                clock = server.timer_snapshot(state)
                marker = "▶" if clock["status"] == "live" else "Ⅱ"
                clock_text = f"{marker} {format_time(timer_elapsed(clock, time.time()))}"
            if self.app.boss_seconds is not None:
                seconds = time.monotonic() - self.app.boss_started if self.app.boss_started else self.app.boss_seconds
                boss_text = f"Boss {format_time(seconds)}"
        for column, (widget, text) in enumerate(((self.speedrun_clock, clock_text), (self.boss_metric, boss_text)), 1):
            if text:
                widget.configure(text=text)
                if not widget.winfo_manager():
                    widget.grid(row=0, column=column, sticky="e")
            elif widget.winfo_manager():
                widget.grid_remove()

        level = level_check.get("characterLevel")
        compare = not self.app.in_endgame and "areaLevel" in level_check
        show_level = (self.allows("campaign_tools") and self.app.prefs.get("level_visible", True)
                      and (compare or level is not None))
        if show_level:
            font = self.ui_font(9, "bold")
            reserved = sum(font.measure(text) + 8 for text in (clock_text, boss_text) if text)
            max_width = max(1, self.layout.width - reserved - 8)
            text, color = self._level_text(level_check, compare, max_width, font)
            self.level_status.configure(text=text, fg=color)
            if not self.level_status.winfo_manager():
                self.level_status.grid(row=0, column=0, sticky="ew")
        elif self.level_status.winfo_manager():
            self.level_status.grid_remove()

        if clock_text or boss_text or show_level:
            if not self.telemetry.winfo_manager():
                self.telemetry.grid(row=3, column=0, sticky="ew")
        elif self.telemetry.winfo_manager():
            self.telemetry.grid_remove()

    def _level_text(self, check, compare, max_width, font):
        level = check.get("characterLevel")
        level_label = "Stufe" if self.display_language == "de" else "Lv"
        prefix = f"{level_label} {level if level is not None else '—'}"
        if not compare:
            return prefix, self.theme.text
        en = self.app.language == "en"
        area = check["areaLevel"]
        area = area if area is not None else "—"
        base = f"{prefix} · {'Area' if en else 'Gebiet'} {area}"
        severity = check.get("severity")
        if not severity:
            if level is None:
                detail = "Waiting for level-up" if en else "Warte auf Level-up"
            else:
                detail = "Waiting for area level" if en else "Warte auf Gebietsstufe"
            text = f"{base} · {detail}"
            return (text if font.measure(text) <= max_width else base), self.theme.text

        names = {"in_range": ("Im Levelbereich", "In range"), "under": ("Unterlevelt", "Underleveled"),
                 "over": ("Überlevelt", "Overleveled")}
        colors = {"green": SUCCESS, "amber": QUEST, "red": HUD_COLLAPSED_RED}
        status = check["status"]
        xp = f"≈{check['xpMultiplier']:.0%} XP"
        text = f"{base} · {names[status][en]} · {xp}"
        if font.measure(text) > max_width:
            sign = {"in_range": "✓", "under": "↓", "over": "↑"}[status]
            text = f"{level}/{area} {sign} · {xp}"
        return text, colors[severity]

    def toggle_content(self):
        """Temporarily hide the navigation and content while keeping the quick controls."""
        self.content_hidden = not self.content_hidden
        if self.content_hidden:
            self.expanded_height = self.layout.height
            self.layout.expanded_height = self.expanded_height
            self.navigation.grid_remove()
            self.body.grid_remove()
            self.telemetry.grid_remove()
            self.feedback.grid_remove()
            self.shell.grid_rowconfigure(5, weight=0)
            self.options_button.grid_forget()
            self._draw_header()
            self.window.update_idletasks()
            self.layout.collapsed_height = self.shell.winfo_reqheight() + self.layout.px(10)
            self.layout.place(self.layout.x, self.layout.y, self.layout.width, self.layout.collapsed_height)
            self._clear_wheel_target()
        else:
            self.layout.collapsed_height = None
            self.shell.grid_rowconfigure(5, weight=1)
            self.options_button.place_forget()
            self._layout_controls()
            self._draw_header()
            self.body.grid()
            self.layout.place(self.layout.x, self.layout.y, self.layout.width, self.expanded_height or self.layout.height)
            self.update(self.app.state, force=True)
            if self.showing_atlas:
                self.endgame._fit()
        self._style_quick_icons()
        self._schedule_targets()
        self.app._refresh_speedrun_hud()


class StandaloneOverlay:
    def __init__(self, http, directory, native=None):
        self.http = http
        self.directory = directory
        self.native = native
        # Only a colour-key backend (Windows) can show the HUD background as see-through.
        self.color_key = bool(native and native.color_key)
        register_bundled_fonts(BASE_DIR / "fonts")
        # X11 window class for taskbars and .desktop matching (StartupWMClass).
        self.root = tk.Tk() if IS_WINDOWS else tk.Tk(className="PoE2-Companion")
        self.root.withdraw()
        if IS_WINDOWS:
            icon_path = str(BASE_DIR / "companion.ico")
            self.root.iconbitmap(default=icon_path)
            self.root.iconbitmap(icon_path)
        else:
            self.root.window_icon = tk.PhotoImage(master=self.root, file=str(BRAND_IMAGES / "buildschmiede-mark.png"))
            self.root.iconphoto(True, self.root.window_icon)
        self.brand_image = tk.PhotoImage(master=self.root, file=str(BRAND_IMAGES / "buildschmiede-hud.png"))
        self.brand_sizes = {}
        self.root.report_callback_exception = self.callback_error
        families = {family.lower(): family for family in tkfont.families(self.root)}
        self.font_families = families
        candidates = ("fontin", "constantia", "palatino linotype", "georgia", "p052", "liberation serif", "dejavu serif")
        default_family = tkfont.nametofont("TkDefaultFont", root=self.root).actual("family")
        self.ui_family = next((families[name] for name in candidates if name in families), default_family)
        self.title_family = families.get("fontin small caps", self.ui_family)
        self.brand_family = next((families[name] for name in ("cinzel", "trajan pro", "constantia", "georgia")
                                  if name in families), self.title_family)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.companion = load_companion(COMPANION_FILE)
        self.state = server.load_state()
        self.anonymous_checks = set()
        self.checklist = self.confirmed_checklist(server.checklist_snapshot(self.state))
        self.mode = self.state["guideMode"]
        self.build_id = self.state["guideBuild"]
        self.respec_values = {}
        self.regex_state = RegexState()
        self.crafting_helper = CraftingHelperState()
        self.current = None
        self.visible = False
        self.closed = False
        self.click_through = True
        self.in_endgame = False
        self.last_location = None
        self.auto_campaign_boss = ""
        self.hotkeys = queue.Queue()
        self.settings = None
        self.welcome = None
        self.appearance_save = None
        self.prefs_path = directory / "poe2_hud_preferences.json"
        self.prefs = server.load_guide_data(self.prefs_path)
        self.experience_level = saved_experience(self.prefs)
        self.boss_clips = BossClipStore(directory, self.clip_staging)
        self.clip_job = False
        if self.prefs.get("card_background") == "glass":
            self.prefs["card_background"] = "translucent"
        self.prefs.pop("level_warnings", None)
        name = self.prefs.get("theme")
        self.theme_name = "PoE2" if name == "Default" else (
            name if isinstance(name, str) and name in THEMES else DEFAULT_THEME)
        self.theme = THEMES[self.theme_name]
        self.style_theme()
        self.checklist_enabled = self.prefs.get("checklist_enabled", "Checkliste" not in self.prefs.get("hidden_sections", []))
        language = self.prefs.get("language")
        self.language = language if isinstance(language, str) and language in LANGUAGES else "hybrid"
        self.timer_visible = self.prefs.get("timer") is True
        self.speedrun_details_open = False
        self.speedrun_hud = None
        self.auto_boss = self.prefs.get("auto_boss", True) is True
        self.boss_started = None
        self.boss_seconds = None
        saved_keys = self.prefs.get("hotkeys")
        saved_keys = saved_keys if isinstance(saved_keys, dict) else {}
        self.keys = {action: str(saved_keys.get(str(action), default)) for action, (_, default) in HUD_HOTKEYS.items()}
        try:
            bindings = timer_bindings(self.keys)
        except ValueError:
            self.keys = {action: default for action, (_, default) in HUD_HOTKEYS.items()}
            bindings = timer_bindings(self.keys)
        self.website = WebsiteContent(directory)
        self.build_import_store = BuildImportStore(directory)
        self.build_import_interface = None
        self._lexicon_snapshot = (None, None)
        self.term_tips = TermTooltips(self)
        if self.website_enabled:
            # Website builds from the last valid download; new downloads apply on the next start.
            added = merge_builds(self.companion, self.website.get("builds"))
            if added:
                server.register_builds(added)
        self.bundled_plans = bundled_plans()
        for key, plan in self.bundled_plans.items():
            self._register_editor_build(key, plan)
        for key in self.build_import_store.plans:
            self.update_imported_build(key)
        self.state.update(server.guide_preferences())
        self.build_id = self.state["guideBuild"]
        self.current = GuideWindow(self)
        self.current.update(self.state)
        self._follow_location()
        if self.native:
            self.native.configure_hotkeys(self._active_bindings(bindings))
            self.native.start_hotkeys(self.hotkeys)
        self.hotkey_job = self.root.after(35, self.poll_hotkeys)
        self.update_job = self.root.after(500, self.update)

    @property
    def website_enabled(self):
        return self.prefs.get("website_content", True) is True

    def allows(self, feature):
        return experience_allows(self.experience_level, feature)

    def _active_bindings(self, bindings):
        return bindings if self.allows("timers") else {key: value for key, value in bindings.items() if key <= 4}

    def apply_experience(self, level):
        previous_staging = self.clip_staging
        self.experience_level = level
        if self.clip_staging != previous_staging:
            self.boss_clips = BossClipStore(self.directory, self.clip_staging)
        if not self.allows("campaign_tools"):
            self.auto_campaign_boss = ""
            self.term_tips.hide()
        self.current.refresh_experience()
        self._refresh_speedrun_hud()
        if self.native:
            self.native.configure_hotkeys(self._active_bindings(timer_bindings(self.keys)))

    @property
    def clip_staging(self):
        return self.allows("experimental") and self.prefs.get("boss_clips_staging") is True

    def set_experience(self, level):
        if level not in EXPERIENCE_LEVELS or level == self.experience_level:
            return
        old_mode = server.load_guide_mode()
        try:
            mode = server.save_guide_mode(default_guide_mode(level))
            try:
                self.save_preferences(experience_level=level)
            except OSError:
                server.save_guide_mode(old_mode)
                raise
        except (OSError, ValueError):
            logging.exception("Funktionsumfang konnte nicht gespeichert werden.")
            self.current.flash("Could not save the experience setting." if self.language == "en"
                               else "Der Funktionsumfang konnte nicht gespeichert werden.")
            return
        settings_open = self.settings_open()
        if settings_open:
            self.settings.destroy()
        self.mode = mode
        self.apply_experience(level)
        self.sync_state()
        if settings_open:
            self.open_settings()

    def run_clip_job(self, action, complete):
        if self.clip_job:
            return False
        self.clip_job = True
        result = queue.Queue(maxsize=1)

        def work():
            try:
                result.put((True, action()))
            except Exception as error:
                logging.exception("Boss-Clips konnten nicht geladen werden.")
                result.put((False, str(error)))

        def poll():
            try:
                ok, value = result.get_nowait()
            except queue.Empty:
                self.root.after(100, poll)
                return
            self.clip_job = False
            if self.current:
                self.current.refresh_guide()
            complete(ok, value)

        Thread(target=work, name="boss-clips", daemon=True).start()
        self.root.after(100, poll)
        return True

    def website_lexicon(self):
        live = self.website.get("lexicon") if self.website_enabled else None
        source, index = self._lexicon_snapshot
        if live is not source or index is None:
            index = merge_published_lexicon(live)
            self._lexicon_snapshot = (live, index)
        return index

    def set_website_enabled(self, enabled):
        self.save_preferences(website_content=enabled)
        if enabled:
            self.website.refresh_in_background()
        else:
            self.term_tips.hide()

    @property
    def can_mirror_background(self):
        """Linux backend: the HUD can be shown see-through through an ARGB mirror window."""
        return bool(self.native and getattr(self.native, "transparent_background", False))

    @property
    def mirrored_background(self):
        # POE2_SHAPE=0 is the emergency switch if the see-through HUD misbehaves on a desktop.
        return (self.can_mirror_background and self.prefs.get("linux_transparent", True) is True
                and os.environ.get("POE2_SHAPE", "1") != "0")

    def translucent_key(self, color, opacity):
        """Key colour (#02xxxx, never 0xFF) the Linux mirror turns into `color` at `opacity`."""
        keys = self.__dict__.setdefault("_translucent_keys", {})
        entry = (color.lower(), round(opacity * 255))
        if entry not in keys:
            index = len(keys) + 1
            keys[entry] = f"#02{index // 250 + 1:02x}{index % 250 + 1:02x}"
        return keys[entry]

    def translucent_colors(self):
        """{(r, g, b) key: ((r, g, b) colour, alpha)} for BackgroundMirror."""
        rgb = lambda value: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        return {rgb(key): (rgb(color), alpha)
                for (color, alpha), key in self.__dict__.get("_translucent_keys", {}).items()}

    def set_mirrored_background(self, enabled):
        self.save_preferences(linux_transparent=enabled)
        self.current.flash("Wirkt nach dem Neustart" if self.language != "en" else "Applies after restart")

    @property
    def tooltips_enabled(self):
        return self.prefs.get("term_tooltips", True) is True

    def set_tooltips_enabled(self, enabled):
        self.save_preferences(term_tooltips=enabled)
        if not enabled:
            self.term_tips.hide()

    def website_status(self):
        en = self.language == "en"
        names = {"lexicon": ("Lexikon", "Glossary"), "builds": ("Builds", "Builds")}
        states = {"current": ("aktuell", "current"), "cached": ("letzter Stand", "last download"),
                  "bundled": ("mitgelieferte Daten", "bundled data")}
        lines = []
        for key, label in names.items():
            state, revision = self.website.status.get(key, ("bundled", ""))
            text = f"{label[en]}: {states[state][en]}"
            digest = revision.removeprefix("sha256:")[:12] if revision.startswith("sha256:") else revision
            lines.append(text + (f" · {digest}" if digest else ""))
        return "\n".join(lines)

    def brand_mark(self, pixels):
        factor = max(1, round(self.brand_image.width() / pixels))
        if factor not in self.brand_sizes:
            self.brand_sizes[factor] = self.brand_image.subsample(factor)
        return self.brand_sizes[factor]

    def _open_taskbar_window(self):
        root = self.root
        root.title(f"Buildschmiede Companion {BUILD_LABEL}")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", root.iconify)
        root.configure(bg=PREVIEW_BG)
        mark = tk.PhotoImage(master=root, file=str(BRAND_IMAGES / "buildschmiede-lockup.png"))
        root.brand_wordmark = mark.subsample(4)
        tk.Label(root, image=root.brand_wordmark, bg=PREVIEW_BG).pack(padx=20, pady=(16, 8))
        controls = tk.Frame(root, bg=PREVIEW_BG)
        controls.pack(padx=12, pady=(0, 12))
        actions = [
            ("HUD anzeigen", "Show HUD", self.recover),
            ("Willkommen", "Welcome", self.open_welcome),
            ("Optionen", "Settings", self.open_settings),
            ("Beenden", "Quit", self.close),
        ]
        for german, english, action in actions:
            button = tk.Button(controls, command=action, cursor="hand2", bg=PREVIEW_BG, fg=TEXT,
                               activebackground=ACTIVE_BG, activeforeground=TEXT, bd=0, padx=7, pady=4)
            button.configure(text=english if self.language == "en" else german)
            button.pack(side="left")
        root.iconify()

    def callback_error(self, kind, value, trace):
        logging.error("Fehler im Overlay", exc_info=(kind, value, trace))
        if self.current:
            self.current.flash("Fehler im Overlay · Details in Optionen.")

    @property
    def api_base(self):
        return f"http://127.0.0.1:{self.http.server_port}"

    def _open_data_exchange(self, _event):
        query = f"?lang={self.language}&mode={self.mode}"
        try:
            webbrowser.open(self.api_base + "/datenaustausch.html" + query)
        except (OSError, webbrowser.Error):
            logging.exception("Datenaustausch konnte nicht geöffnet werden.")
        return "break"

    def open_module(self, module):
        if module == "settings":
            self.open_settings()
            return
        if module == "builds" and self.current.section_available("build"):
            self.current._layout_controls()
            self.current.select_guide_section("build")
        else:
            self.current.select_guide_section("quest")
        if not self.visible:
            self.toggle_visibility()

    def theme_font(self, *, heading=False, fallback="Segoe UI", theme=None):
        treatment = (theme or self.theme).treatment
        families = treatment.heading_fonts + treatment.body_fonts if heading else treatment.body_fonts
        return next((self.font_families[name.lower()] for name in families if name.lower() in self.font_families), fallback)

    def style_theme(self):
        theme = self.theme
        style = ttk.Style(self.root)
        field = theme.field_color
        selected = theme.selection_color
        selected_text = theme.selection_text
        for name, inset in (("Atlas.TCombobox", (8, 5)), ("Guide.TCombobox", (12, 8))):
            style.configure(name, fieldbackground=field, foreground=theme.text, background=field,
                            arrowcolor=theme.accent, bordercolor=theme.edge, lightcolor=field,
                            darkcolor=field, arrowsize=15, padding=inset,
                            selectbackground=selected, selectforeground=selected_text)
            style.map(name, fieldbackground=[("readonly", field)], foreground=[("readonly", theme.text)],
                      bordercolor=[("focus", theme.accent), ("active", theme.accent)])
        for key, color in (("background", field), ("foreground", theme.text),
                           ("selectBackground", selected), ("selectForeground", selected_text)):
            self.root.option_add("*TCombobox*Listbox." + key, color)

        # Tk creates the listbox lazily and caches it, including across theme switches.
        def update_popdowns(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Combobox):
                    listbox = str(child) + ".popdown.f.l"
                    if child.tk.getboolean(child.tk.call("winfo", "exists", listbox)):
                        child.tk.call(listbox, "configure", "-background", field, "-foreground", theme.text,
                                      "-selectbackground", selected, "-selectforeground", selected_text)
                update_popdowns(child)
        update_popdowns(self.root)

    def set_theme(self, name):
        if name not in THEMES or name == self.theme_name:
            return
        background, accents, intensity = THEME_APPEARANCE[name]
        self.save_preferences(theme=name, card_background=background, card_accents=accents, color_intensity=intensity)
        self.theme_name = name
        self.theme = THEMES[name]
        self.style_theme()
        self.current.apply_theme()
        self._refresh_speedrun_hud()

    def _follow_location(self):
        status = server.get_location_status()
        zone = status.get("zone", "")
        location = status.get("atlasLocation", {})
        kind = location.get("kind")
        key = (zone_key(zone), kind, location.get("entry"))
        if key == self.last_location:
            return
        self.last_location = key
        hub = hub_kind(zone)
        if hub == "ziggurat" or (not hub and kind):
            self.in_endgame = True
        elif hub == "hideout":
            pass
        elif hub or key[0] in server.CAMPAIGN_ZONES:
            self.in_endgame = False
        else:
            return
        encounter = self.state.get("bossEncounter") if self.auto_boss and self.allows("campaign_tools") else None
        guide = self.current
        if self.in_endgame:
            self._close_auto_boss()
            if not hub and encounter and encounter["phase"] == "endgame" and (
                    "lookup" not in self.prefs.get("hidden_hud_tabs", ())):
                guide.open_atlas_tab("boss")
            return
        if not hub and encounter and encounter["phase"] == "campaign" and guide.guide_section != "lookup":
            guide._show_boss(encounter, automatic=True)
        else:
            self._close_auto_boss()

    def _close_auto_boss(self):
        if self.auto_campaign_boss:
            guide = self.current
            if guide.guide_section == "boss" and guide.companion.boss_id == self.auto_campaign_boss:
                guide._close_boss()
            self.auto_campaign_boss = ""

    def confirmed_checklist(self, snapshot):
        if snapshot["character"] or snapshot["runId"] != "initial":
            return snapshot
        # The unnamed initial run is shared by unidentified characters across launches.
        return {**snapshot, "checked": {key: True for key in snapshot["checked"]
                                        if key in self.anonymous_checks or key.startswith("setup:")}}

    def check_item(self, ident, checked):
        if not self.checklist_enabled:
            return
        try:
            snapshot = server.change_checklist({"id": ident, "checked": checked,
                                                      "character": self.checklist["character"],
                                                      "runId": self.checklist["runId"]})
        except (OSError, ValueError):
            self.current.flash("Checkliste konnte nicht gespeichert werden.")
            return False
        if not snapshot["character"] and snapshot["runId"] == "initial":
            if checked:
                self.anonymous_checks.add(ident)
            else:
                self.anonymous_checks.discard(ident)
        self.checklist = self.confirmed_checklist(snapshot)
        return True

    def start_checklist_run(self, dialog):
        english = self.language == "en"
        title = "New run checklist" if english else "Neue Run-Checkliste"
        message = ("Start a new checklist for the active character? The previous run stays saved." if english else
                   "Eine neue Checkliste für den aktiven Charakter starten? Der bisherige Run bleibt gespeichert.")
        if not messagebox.askyesno(title, message, parent=dialog):
            return
        try:
            self.checklist = server.change_checklist({"action": "new", "character": self.checklist["character"],
                                                       "runId": self.checklist["runId"]})
        except (OSError, ValueError):
            messagebox.showerror(title, "Could not start a new checklist." if english else
                                 "Die neue Checkliste konnte nicht gestartet werden.", parent=dialog)
            return
        self.anonymous_checks.clear()
        self.current.refresh_guide()

    def toggle_mode(self):
        self.mode = "veteran" if self.mode == "basis" else "basis"
        self.current.update(self.state)

    def set_checklist_enabled(self, enabled):
        self.save_preferences(checklist_enabled=enabled)
        self.checklist_enabled = enabled
        if self.settings_open():
            self.settings.sync_checklist()
        self.current.refresh_guide()

    def set_section_visible(self, name, enabled):
        hidden = set(self.prefs.get("hidden_sections", []))
        hidden.difference_update(("Checkliste", "Questbelohnungen"))
        if enabled:
            hidden.discard(name)
        else:
            hidden.add(name)
        self.save_preferences(hidden_sections=sorted(hidden), checklist_enabled=self.checklist_enabled)
        self.current.refresh_guide()

    def set_mode(self, mode):
        self.mode = server.save_guide_mode(mode)
        if self.settings and self.settings.winfo_exists() and hasattr(self, "settings_mode"):
            self.settings_mode.set(self.mode)
        self.sync_state()
        self.current.refresh_guide()

    def select_build(self, build_id):
        try:
            self.build_id = server.save_guide_setting("build", build_id)
        except (OSError, ValueError):
            logging.exception("Build-Auswahl konnte nicht gespeichert werden.")
            self.current.flash("Build-Auswahl konnte nicht gespeichert werden.")
        self.sync_state()
        self.current.refresh_guide()

    def update_imported_build(self, key):
        self._register_editor_build(key, self.build_import_store.plans[key])

    def _open_build_import_interface(self, _event):
        if not self.allows("campaign_tools"):
            return "break"
        from poe2_build_import_interface_ui import BuildImportInterfaceWindow

        if self.build_import_interface is None or not self.build_import_interface.window.winfo_exists():
            self.build_import_interface = BuildImportInterfaceWindow(self)
        window = self.build_import_interface.window
        window.deiconify()
        window.lift()
        window.focus_force()
        return "break"
        if self.current:
            if self.current.lookup_entry and self.current.lookup_entry.category == "builds":
                self.current.lookup_entry = None
            self.current.refresh_guide()

    def _register_editor_build(self, key, plan):
        build = guide_build(key, plan)
        builds = self.companion.setdefault("builds", [])
        index = next((i for i, row in enumerate(builds) if row["id"] == key), len(builds))
        builds[index:index + 1] = [build]
        sources = plan.get("overlaySources", {})
        stages = [build, *build["stages"]]
        for stage in stages:
            verified = []
            for ident in stage["sources"]:
                source = sources.get(ident.removeprefix(f"{key}:")) if isinstance(sources, dict) else None
                if isinstance(source, dict) and all(isinstance(source.get(field), str) for field in ("url", "label")):
                    if source["url"].startswith(("https://", "http://")):
                        self.companion.setdefault("sources", {})[ident] = source
                        verified.append(ident)
            stage["sources"] = verified
        server.register_builds((key,))

    def show_build_guide(self, key, phase_id=None, *, gear_slot=None):
        if not self.allows("campaign_tools"):
            return
        self.select_build(key)
        self.open_module("builds")
        panel = self.current.companion
        stage = phase_id or ""
        if gear_slot and stage:
            context = ("build", key, stage)
            panel.gear_selection[context] = gear_slot
            panel.card_folds[(*context, "craft")] = False
        if panel.stage_id != stage or (gear_slot and stage):
            panel._pick_stage(stage)

    def import_build(self):
        if not self.allows("campaign_tools"):
            return
        parent = self.current.window
        english = self.language == "en"
        title = "Import build" if english else "Build importieren"
        path = filedialog.askopenfilename(
            parent=parent, title=title,
            filetypes=[("Build files" if english else "Build-Dateien", "*.json *.build *.zip *.xml *.pob *.pob2 *.txt"),
                       ("All files" if english else "Alle Dateien", "*")],
        )
        if not path:
            return

        first = None
        try:
            for plan in import_plans(path):
                key = next((key for key, saved in self.build_import_store.plans.items() if saved == plan), None)
                if key is None:
                    key = self.build_import_store.save(plan)
                self._register_editor_build(key, self.build_import_store.plans[key])
                first = first or key
        except (OSError, ValueError) as error:
            messagebox.showerror(title, str(error), parent=parent)
        if first:
            self.show_build_guide(first)

    def sync_state(self):
        previous_default = self.state["guideMode"]
        self.state = server.load_state()
        self.checklist = self.confirmed_checklist(server.checklist_snapshot(self.state))
        if self.state["guideMode"] != previous_default:
            self.mode = self.state["guideMode"]
            if self.settings and self.settings.winfo_exists() and hasattr(self, "settings_mode"):
                self.settings_mode.set(self.mode)
        self.build_id = self.state.get("guideBuild", self.build_id)
        self._follow_location()
        self.current.update(self.state)
        self._refresh_speedrun_hud()
        if self.settings_open() and hasattr(self.settings, "refresh_manual_level"):
            self.settings.refresh_manual_level()

    def update(self):
        self.update_job = None
        try:
            self.sync_state()
        finally:
            if not self.closed:
                self.update_job = self.root.after(500, self.update)

    def poll_hotkeys(self):
        self.hotkey_job = None
        try:
            if self.native and self.native.recovery_requested():
                self.recover()
            while True:
                action = self.hotkeys.get_nowait()
                if isinstance(action, tuple):
                    owner, delta = action
                    if self.visible and self.click_through and owner is self.current:
                        owner.scroll_by(delta)
                elif action == 1:
                    self.toggle_visibility()
                elif action == 2:
                    self.toggle_click_mode()
                elif action == 3:
                    self.close()
                    return
                elif action == 4:
                    self.recover()
                elif action == 5 and self.allows("timers"):
                    self.control_timer("toggle")
                elif action == 6 and self.allows("timers"):
                    self.control_timer("reset")
                elif action == 7 and self.allows("timers"):
                    self.control_boss_timer()
        except queue.Empty:
            pass
        except (OSError, tk.TclError):
            logging.exception("Overlay-Tastenkürzel fehlgeschlagen.")
        if not self.closed:
            self.hotkey_job = self.root.after(35, self.poll_hotkeys)

    def toggle_click_mode(self):
        self.set_click_mode(not self.click_through)

    def set_click_mode(self, enabled):
        old_mode = self.click_through
        self.click_through = enabled
        try:
            if self.visible:
                self.current.set_click_mode(enabled)
                if not enabled and self.color_key and not self.settings_open() and not self.current.lookup_dialog:
                    self.current.window.focus_force()
        except (OSError, tk.TclError):
            self.click_through = old_mode
            self.current._style_quick_icons()
            logging.exception("Klickmodus konnte nicht gesetzt werden. Vorgabe: %s", enabled)
            self.current.flash("F9 nicht übernommen · Strg+Umschalt+F9 setzt Bedienung zurück.")
            return
        if self.speedrun_hud is not None and self.speedrun_hud.visible:
            self.speedrun_hud._sync_click_mode()
        labels = ("HUD gesperrt", "HUD locked") if enabled else ("HUD verschiebbar", "HUD movable")
        self.current.flash(labels[self.language == "en"])

    def toggle_visibility(self):
        if self.visible:
            self.current.leave()
            self.visible = False
        else:
            self.visible = True
            self.current.enter()
        self._refresh_speedrun_hud()

    def recover(self):
        self.current.leave()
        self.click_through = False
        self.visible = True
        self.current.enter()
        if self.speedrun_hud is not None and self.speedrun_hud.visible:
            self.speedrun_hud._sync_click_mode()
        self._refresh_speedrun_hud()
        self.current.flash("Bedienbar")

    @property
    def card_accents(self):
        value = self.prefs.get("card_accents")
        return value if isinstance(value, str) and value in CARD_ACCENTS else THEME_APPEARANCE[self.theme_name][1]

    @property
    def card_background(self):
        value = self.prefs.get("card_background")
        return value if isinstance(value, str) and value in CARD_BACKGROUNDS else THEME_APPEARANCE[self.theme_name][0]

    @property
    def menu_background(self):
        value = self.prefs.get("menu_background")
        return value if isinstance(value, str) and value in MENU_BACKGROUNDS else "opaque"

    @property
    def color_intensity(self):
        value = self.prefs.get("color_intensity")
        return value if isinstance(value, str) and value in COLOR_INTENSITY else THEME_APPEARANCE[self.theme_name][2]

    def overlay_alpha(self):
        return max(26, round(255 * (1 - self.prefs.get("transparency", 0) / 100)))

    def settings_open(self):
        return self.settings is not None and self.settings.winfo_exists()

    @property
    def show_welcome_on_start(self):
        return (self.prefs.get("welcome_setup_completed") is not True
                or self.prefs.get("show_welcome_on_start") is True)

    def open_welcome(self, *, on_done=None):
        if self.welcome is not None:
            self.welcome.lift()
            self.welcome.focus_force()
            return
        if self.settings_open():
            self.settings.destroy()
        guide = self.current
        layout = guide.layout
        bounds = layout._work_area(layout.x, layout.y, layout.width, layout.height)
        theme = self.theme
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        self.welcome = dialog
        first_use = not self.prefs_path.is_file()
        language = tk.StringVar(dialog, value="hybrid" if first_use else self.language)
        experience = tk.StringVar(dialog, value=self.experience_level)
        mode = tk.StringVar(dialog, value=default_guide_mode(experience.get()) if first_use else self.mode)
        theme_name = tk.StringVar(dialog, value=self.theme_name)
        background = tk.StringVar(dialog, value=self.card_background)
        accent = tk.StringVar(dialog, value=self.card_accents)
        intensity = tk.StringVar(dialog, value=self.color_intensity)
        customize = tk.BooleanVar(dialog, value=False)
        current_level = self.state.get("levelCheck", {}).get("characterLevel")
        character = tk.StringVar(dialog, value="existing" if current_level and current_level > 1 else "new")
        character_level = tk.StringVar(dialog, value=str(current_level) if current_level else "")
        level_error = tk.StringVar(dialog)
        preview = None

        def sample():
            return WelcomeSample(language.get(), mode.get(), background.get(), accent.get(),
                                 theme_name.get(), intensity.get(), experience.get())
        dismiss_next = tk.BooleanVar(dialog, value=self.prefs.get("show_welcome_on_start") is not True)
        font = (self.theme_font(), 10)

        def tr(de, en):
            return en if language.get() == "en" else de

        def forget(event):
            if event.widget is dialog:
                self.welcome = None
                if preview is not None:
                    preview.close()
                if not self.closed:
                    if self.visible:
                        self.current.enter()
                        self._refresh_speedrun_hud()
                    if on_done is not None:
                        self.root.after_idle(on_done)

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.bind("<Destroy>", forget)
        dialog.bind("<Configure>", lambda event: self.current._schedule_targets()
                    if event.widget is dialog and self.current else None)
        dialog.configure(bg=theme.edge, padx=1, pady=1)
        viewport = tk.Canvas(dialog, bg=theme.panel, bd=0, highlightthickness=0)
        viewport.pack(fill="both", expand=True)
        content_padding = layout.px(14)
        content = tk.Frame(viewport, bg=theme.panel, padx=content_padding, pady=13)
        sheet = viewport.create_window(0, 0, window=content, anchor="nw")
        footer = tk.Frame(dialog, bg=theme.panel, padx=18, pady=12)
        footer.pack(fill="x")
        left, top, right, bottom = bounds
        gap = layout.px(20)
        available_width, available_height = right - left, bottom - top
        beside = available_width >= layout.px(880)
        preview_reserve = layout.px(310) + gap if beside else 0
        width = min(layout.px(690), available_width - preview_reserve - 2 * gap)
        columns_fit = 3 if width >= layout.px(560) else 2 if width >= layout.px(385) else 1

        title = tk.Label(content, bg=theme.panel, fg=theme.accent,
                         image=self.brand_mark(layout.px(36)), compound="left", padx=5,
                         font=(self.theme_font(heading=True, fallback=self.brand_family), 18), anchor="w",
                         justify="left", wraplength=max(1, width - layout.px(36)))
        title.pack(fill="x", pady=(0, 7))
        headings = {}
        cards = {}
        card_rows = []

        def keep_visible(widget):
            bounds = viewport.bbox(sheet)
            if bounds is None:
                return
            top = widget.winfo_rooty() - content.winfo_rooty()
            bottom = top + widget.winfo_height()
            height = viewport.winfo_height()
            visible_top = viewport.canvasy(0)
            if top < visible_top or bottom > visible_top + height:
                target = min(top, bottom - height) if top >= visible_top else top
                viewport.yview_moveto(max(0, target) / max(1, bounds[3]))

        def two_line_width(title, measure):
            words = title.split()
            return min(max(measure(" ".join(words[:i])), measure(" ".join(words[i:])))
                       for i in range(1, len(words) + 1))

        def group(parent, key, variable, values, *, columns=None):
            heading_font = (self.theme_font(heading=True), 11, "bold")
            heading = tk.Label(parent, bg=theme.panel, fg=theme.text, font=heading_font, anchor="w")
            heading.pack(fill="x", pady=(8, 4))
            headings[key] = heading
            row = tk.Frame(parent, bg=theme.panel)
            row.pack(fill="x")
            columns = min(columns or columns_fit, len(values))
            card_gap, card_padding = layout.px(3), layout.px(9)
            text_inset = card_gap + card_padding + layout.px(6)
            card_font = heading_font
            card_space = width - 2 * content_padding
            if key == "experience":
                card_padding = layout.px(6)
                text_inset = card_gap + card_padding + 2
                button_inset = layout.px(8)
                if columns > 1:
                    title_space = card_space // columns - 2 * text_inset - button_inset
                    for points in (11, 10):
                        card_font = (heading_font[0], points, "bold")
                        measure = tkfont.Font(root=dialog, font=card_font).measure
                        title_width = max(two_line_width(title, measure) for labels in EXPERIENCE_LEVELS.values()
                                          for title in labels[:2])
                        marker_width = measure("✓") + 2 * layout.px(2)
                        if title_width + marker_width <= title_space:
                            break
                    else:
                        columns = 1
                        card_font = heading_font
            wrap = max(1, card_space // columns - 2 * text_inset)
            values = tuple(values)
            for col in range(columns):
                row.columnconfigure(col, weight=1, uniform=key)
            for i, value in enumerate(values):
                frame = tk.Frame(row, bd=0, highlightthickness=1, padx=card_padding, pady=layout.px(8))
                frame.grid(row=i // columns, column=i % columns, sticky="nsew", padx=card_gap, pady=layout.px(3))
                frame.columnconfigure(0, weight=1)
                def select(value=value):
                    if key == "experience" and variable.get() != value:
                        mode.set(default_guide_mode(value))
                    variable.set(value)
                    refresh()
                button = tk.Button(frame, command=select, font=card_font,
                                   anchor="nw", justify="left", wraplength=wrap, padx=0, pady=0,
                                   bd=0, highlightthickness=1, relief="flat", cursor="hand2")
                button.grid(row=0, column=0, sticky="new")
                button.bind("<FocusIn>", lambda event, frame=frame: keep_visible(frame))
                marker = None
                if key == "experience":
                    marker = tk.Label(frame, text="✓", font=card_font, bd=0,
                                      padx=layout.px(2), pady=1, cursor="hand2")
                    marker_width = marker.winfo_reqwidth()
                    frame.columnconfigure(1, minsize=marker_width)
                    button.configure(wraplength=max(1, wrap - marker_width - button_inset))
                    marker.grid(row=0, column=1, sticky="ne")
                    marker.bind("<Button-1>", lambda event, select=select: select())
                body_wrap = max(1, wrap - 4) if marker else wrap
                description = tk.Label(frame, font=font, anchor="nw", justify="left", wraplength=body_wrap,
                                       padx=1, pady=0, cursor="hand2")
                description.grid(row=1, column=0, columnspan=2 if marker else 1,
                                 sticky="new", pady=(layout.px(2 if marker else 4), 0))
                description.bind("<Button-1>", lambda event, select=select: select())
                frame.bind("<Button-1>", lambda event, select=select: select())
                cards[key, value] = (variable, frame, button, description, marker)
            if columns > 1:
                for i in range(0, len(values), columns):
                    card_rows.append([cards[key, value][2] for value in values[i:i + columns]])

        introduction = tk.Label(content, bg=theme.panel, fg=theme.text, font=font, justify="left",
                                anchor="w", wraplength=width-layout.px(46))
        introduction.pack(fill="x", pady=(0, 3))
        group(content, "language", language, ("de", "en", "hybrid"),
              columns=3 if width >= layout.px(440) else None)
        group(content, "experience", experience, EXPERIENCE_LEVELS, columns=2)
        advanced = tk.Frame(content, bg=theme.panel)
        options_visible = tk.BooleanVar(dialog, value=False)
        def toggle_options():
            options_visible.set(not options_visible.get())
            refresh()
            resize_sheet()
            keep_visible(advanced if options_visible.get() else options_button)
        options_button = tk.Button(content, command=toggle_options, anchor="w", font=font,
                                   bg=theme.control, fg=theme.accent, activebackground=theme.active,
                                   activeforeground=theme.text, padx=9, pady=5, relief="flat", cursor="hand2")
        options_button.pack(fill="x", pady=(9, 2))
        group(advanced, "character", character, ("new", "existing"))
        level_panel = tk.Frame(advanced, bg=theme.panel)
        level_label = tk.Label(level_panel, bg=theme.panel, fg=theme.text, font=font)
        level_label.grid(row=0, column=0, sticky="w", padx=(3, 9))
        level_entry = tk.Entry(level_panel, textvariable=character_level, width=6, justify="center",
                               bg=theme.field_color, fg=theme.text, insertbackground=theme.text,
                               selectbackground=theme.selection_color, selectforeground=theme.selection_text,
                               relief="flat", highlightthickness=1, highlightbackground=theme.edge,
                               highlightcolor=theme.accent)
        level_entry.grid(row=0, column=1, sticky="w")
        level_hint = tk.Label(level_panel, bg=theme.panel, fg=theme.text, font=font,
                              justify="left", wraplength=width-layout.px(46))
        level_hint.grid(row=1, column=0, columnspan=2, sticky="w", padx=3)
        tk.Label(level_panel, bg=theme.panel, fg=DANGER, font=font, textvariable=level_error,
                 wraplength=width-layout.px(46)).grid(row=2, column=0, columnspan=2, sticky="w", padx=3)
        group(advanced, "mode", mode, ("veteran", "basis"))
        hint = tk.Label(advanced, bg=theme.panel, fg=theme.accent, font=font,
                        anchor="w", justify="left", wraplength=width-layout.px(46))
        hint.pack(fill="x", pady=(4, 0))
        appearance = tk.Frame(advanced, bg=theme.panel)
        appearance.pack(fill="x", pady=(12, 0))
        appearance_summary = tk.Label(appearance, bg=theme.panel, fg=theme.accent,
                                      font=(self.theme_font(heading=True), 11, "bold"), anchor="w")
        appearance_summary.pack(fill="x")
        appearance_fields = tk.Frame(appearance, bg=theme.panel)
        appearance_fields.columnconfigure(1, weight=1)

        def toggle_appearance():
            customize.set(not customize.get())
            refresh()
            if customize.get():
                def show_fields():
                    dialog.update_idletasks()
                    box = viewport.bbox(sheet)
                    bottom = appearance.winfo_y() + appearance.winfo_height()
                    visible = viewport.winfo_height()
                    if box and bottom > viewport.canvasy(visible):
                        viewport.yview_moveto(max(0, bottom - visible + 8) / max(1, box[3]))
                dialog.after_idle(show_fields)

        appearance_button = tk.Button(appearance, command=toggle_appearance, bg=theme.control, fg=theme.text,
                                      activebackground=theme.active, activeforeground=theme.accent, font=font,
                                      padx=9, pady=4, bd=0, relief=theme.treatment.button_relief, cursor="hand2")
        appearance_button.pack(anchor="w", pady=(4, 0))
        choices = []
        for label_text, variable, entries in (
            (("Theme", "Theme"), theme_name, THEMES),
            (("Kachelhintergrund", "Card background"), background, CARD_BACKGROUNDS),
            (("Abschnittsfarben", "Section colors"), accent, CARD_ACCENTS),
            (("Farbstärke", "Color intensity"), intensity, COLOR_INTENSITY),
        ):
            row = len(choices)
            label = tk.Label(appearance_fields, bg=theme.panel, fg=theme.text, font=font,
                             anchor="w", justify="left", wraplength=width // 3)
            label.grid(row=row, column=0, sticky="ew", padx=(0, 10), pady=3)
            box = ttk.Combobox(appearance_fields, style="Guide.TCombobox", state="readonly", width=14, font=font)
            box.grid(row=row, column=1, sticky="ew", pady=3)
            choices.append((label, label_text, box, variable, entries))

            def choose(event, box=box, variable=variable, entries=entries):
                index = box.current()
                if index < 0:
                    return
                selected = list(entries)[index]
                if variable == theme_name and selected != theme_name.get():
                    default_background, default_accents, default_intensity = THEME_APPEARANCE[selected]
                    background.set(default_background)
                    accent.set(default_accents)
                    intensity.set(default_intensity)
                variable.set(selected)
                refresh()

            box.bind("<<ComboboxSelected>>", choose)
        checkbox = tk.Checkbutton(footer, variable=dismiss_next, bg=theme.panel, fg=theme.text,
                                  activebackground=theme.panel, activeforeground=theme.text,
                                  selectcolor=theme.control, font=font, anchor="w")
        checkbox.pack(side="left")

        def save():
            level = 1
            if character.get() == "existing":
                raw = character_level.get().strip()
                if not (1 <= len(raw) <= 3 and raw.isdecimal() and 1 <= int(raw) <= 100):
                    level_error.set(tr("Gib ein ganzes Level von 1 bis 100 ein.", "Enter a whole level from 1 to 100."))
                    level_entry.focus_set()
                    return
                level = int(raw)
            changed_mode = False
            try:
                old_mode = server.load_guide_mode()
                if mode.get() != old_mode:
                    server.save_guide_mode(mode.get())
                    changed_mode = True
                self.save_preferences(language=language.get(), theme=theme_name.get(),
                                      experience_level=experience.get(),
                                      card_background=background.get(), card_accents=accent.get(),
                                      color_intensity=intensity.get(), show_welcome_on_start=not dismiss_next.get(),
                                      welcome_setup_completed=True)
            except (OSError, ValueError) as error:
                if changed_mode:
                    try:
                        server.save_guide_mode(old_mode)
                    except (OSError, ValueError):
                        logging.exception("Ansichtsmodus konnte nicht zurückgesetzt werden.")
                messagebox.showerror(title.cget("text"), str(error), parent=dialog)
                return
            self.language, self.mode = language.get(), mode.get()
            self.theme_name = theme_name.get()
            self.theme = THEMES[self.theme_name]
            self.style_theme()
            self.apply_experience(experience.get())
            if level != current_level and (current_level is not None or level > 1
                                           or not self.state.get("levelCheck", {}).get("characterLevel")):
                server.set_manual_character_level(level)
            self.sync_state()
            self.current.apply_theme()
            dialog.destroy()

        confirm = tk.Button(footer, command=save, bg=theme.selection_color, fg=theme.selection_text,
                            activebackground=theme.accent, activeforeground=theme.selection_text,
                            font=(self.theme_font(), 11, "bold"), padx=14, pady=4,
                            relief=theme.treatment.button_relief, bd=0)
        confirm.pack(side="right")
        level_entry.bind("<Return>", lambda event: save())
        arrows = ScrollArrows(viewport, viewport, theme.control, theme.accent)
        viewport.configure(yscrollcommand=arrows.extent)
        dialog.bind("<MouseWheel>", lambda event: viewport.yview_scroll(-int(event.delta/120), "units"))
        dialog.bind("<Button-4>", lambda event: viewport.yview_scroll(-1, "units"))
        dialog.bind("<Button-5>", lambda event: viewport.yview_scroll(1, "units"))
        def refresh():
            title.configure(text=tr("Willkommen bei Buildschmiede", "Welcome to Buildforge"))
            dialog.title(companion_title(language.get()))
            headings["language"].configure(text="Sprache wählen · Choose your language")
            headings["experience"].configure(text=tr("Was kennst du schon aus Path of Exile 2?",
                                                     "What are you familiar with in Path of Exile 2?"))
            headings["mode"].configure(text=tr("Ansichtsmodus", "Guide view"))
            headings["character"].configure(text=tr("Mit welchem Charakter spielst du?", "Which character are you playing?"))
            level_label.configure(text=tr("Aktuelles Charakterlevel", "Current character level"))
            level_hint.configure(text=tr("Das nächste erkannte Level-up aktualisiert die Anzeige.",
                                         "The next detected level-up updates the display."))
            level_error.set("")
            if character.get() == "existing":
                level_panel.pack(fill="x", pady=(5, 0), before=headings["mode"])
            else:
                level_panel.pack_forget()
            introduction.configure(text=tr(
                "Wähle, welche Hilfe zu deinem Spiel passt. Die Auswahl kannst du später in den Optionen ändern.",
                "Choose the help that suits the way you play. You can change it later in Options."))
            if options_visible.get():
                advanced.pack(fill="x")
                options_button.configure(text=tr("▾ Charakter und Anzeige", "▾ Character and display"))
            else:
                advanced.pack_forget()
                options_button.configure(text=tr("▸ Charakter und Anzeige anpassen", "▸ Customize character and display"))
            labels = {
                ("character", "new"): (tr("Neuer Charakter", "New character"),
                                        tr("Start auf Level 1.", "Start at level 1.")),
                ("character", "existing"): (tr("Bestehender Charakter", "Existing character"),
                                             tr("Für Kampagne und Endgame.", "For campaign and endgame.")),
                ("language", "de"): ("Deutsch", "Deutsche Texte und Spielbegriffe."),
                ("language", "en"): ("English", "English text and game terms."),
                ("language", "hybrid"): ("Hybrid", "Deutsche Texte, englische Spielbegriffe."),
                ("mode", "veteran"): (tr("Kompakt", "Compact"),
                    tr("Kurze Stichpunkte mit den nächsten Schritten.",
                       "Short prompts with the next steps.")),
                ("mode", "basis"): (tr("Ausführlich", "Detailed"),
                    tr("Mehr Kontext zu Wegen, Zielen und Entscheidungen.",
                       "More context for routes, objectives, and decisions.")),
            }
            labels.update({("experience", value): (tr(de, en), tr(description_de, description_en))
                           for value, (de, en, description_de, description_en) in EXPERIENCE_LEVELS.items()})
            for key, (variable, frame, button, description, marker) in cards.items():
                selected = variable.get() == key[1]
                shade = theme.active if selected else theme.control
                frame.configure(bg=shade, highlightbackground=theme.accent if selected else theme.edge)
                button.configure(text=("✓ " if selected and marker is None else "") + labels[key][0],
                                 bg=shade, fg=theme.accent,
                                 activebackground=theme.active, activeforeground=theme.text,
                                 highlightbackground=shade, highlightcolor=theme.accent)
                if marker is not None:
                    marker.configure(text="✓" if selected else "", bg=shade, fg=theme.accent)
                description.configure(text=labels[key][1], bg=shade, fg=theme.text)
            for row in card_rows:
                height = max(button.winfo_reqheight() for button in row)
                for button in row:
                    button.master.rowconfigure(0, minsize=height)
            hint.configure(text=tr("Einzelne Abschnitte kannst du in den Optionen vollständig ausblenden.",
                                   "You can hide individual sections entirely in Options.") if mode.get() == "veteran" else "")
            appearance_summary.configure(text=theme_label(theme_name.get(), language.get()))
            appearance_button.configure(text=tr("Theme-Optionen schließen", "Hide theme options") if customize.get()
                                        else tr("Theme anpassen", "Customize theme"))
            if customize.get():
                appearance_fields.pack(fill="x", pady=(6, 0))
            else:
                appearance_fields.pack_forget()
            for label, texts, box, variable, entries in choices:
                label.configure(text=tr(*texts))
                box.configure(values=[theme_label(name, language.get()) for name in entries] if variable == theme_name
                              else [tr(*pair) for pair in entries.values()])
                box.current(list(entries).index(variable.get()))
            checkbox.configure(text=tr("Beim nächsten Start nicht mehr anzeigen", "Don't show again at startup"))
            confirm.configure(text=tr("Losspielen", "Start playing") if on_done is not None
                              else tr("Speichern", "Save"))
            if preview is not None:
                previous_theme = preview.theme
                previous_experience = preview.welcome_sample.experience_level
                preview.welcome_sample = sample()
                if preview.theme != previous_theme or previous_experience != experience.get():
                    preview.apply_theme()
                else:
                    preview.update(self.state, force=True)

        viewport.itemconfigure(sheet, width=width)
        refresh()
        dialog.update_idletasks()
        preview_height = min(layout.px(525), available_height - 2 * gap) if beside else (
            min(layout.px(260), available_height // 4))
        reserved = 0 if beside else preview_height + gap
        max_height = available_height - footer.winfo_reqheight() - layout.px(85) - reserved
        height = min(content.winfo_reqheight(), max_height)
        viewport.configure(width=width, height=max(1, height))
        def update_region(event=None):
            box = viewport.bbox(sheet)
            if box:
                extra = arrows.winfo_reqheight() + 4 if box[3] > viewport.winfo_height() else 0
                viewport.configure(scrollregion=(0, 0, box[2], box[3] + extra))
        def resize_sheet():
            dialog.update_idletasks()
            viewport.configure(height=max(1, min(content.winfo_reqheight(), max_height)))
            dialog.update_idletasks()
            y = max(top + gap, min(dialog.winfo_y(), bottom - gap - dialog.winfo_reqheight() - reserved))
            dialog.geometry(f"+{dialog.winfo_x()}+{y}")
            if not beside and preview is not None:
                preview.layout.place(preview_x, y + dialog.winfo_reqheight() + gap, preview_width, preview_height)
        content.bind("<Configure>", update_region)
        viewport.bind("<Configure>", update_region)
        dialog.update_idletasks()
        guide.leave()
        self._refresh_speedrun_hud()
        preview = GuideWindow(self, welcome_sample=sample())
        preview.layout.dpi = layout.dpi
        preview.layout._resize_fonts()
        for button in (*preview.tabs.values(), preview.mode_button, preview.eye_button,
                       preview.lock_button, preview.options_button):
            button.configure(state="disabled", disabledforeground=button.cget("fg"), cursor="arrow")
        dialog_width, dialog_height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        preview_width = min(layout.width, preview.layout._width_limit(left, right),
                            available_width - dialog_width - 3 * gap if beside else available_width - 2 * gap)
        if beside:
            preview_x = left + (available_width - preview_width - gap - dialog_width) // 2
            dialog_x = preview_x + preview_width + gap
            dialog_y = top + (available_height - dialog_height) // 2
            preview_y = max(top + gap, min(dialog_y, bottom - preview_height - gap))
        else:
            dialog_x = left + (available_width - dialog_width) // 2
            preview_x = left + (available_width - preview_width) // 2
            dialog_y = top + (available_height - dialog_height - preview_height - gap) // 2
            preview_y = dialog_y + dialog_height + gap
        preview.window.deiconify()
        preview.window.update_idletasks()
        preview.layout.place(preview_x, preview_y, preview_width, preview_height)
        if self.native:
            preview.set_click_mode(True)
        preview.window.update_idletasks()
        preview.apply_theme()
        dialog.geometry(f"+{dialog_x}+{dialog_y}")
        dialog.deiconify()
        if self.native:
            dialog.update_idletasks()
            self.native.style_dialog(dialog, palette=(theme.edge, theme.panel, theme.text))
        dialog.lift()
        confirm.focus_set()

    def open_settings(self):
        if self.welcome is not None:
            self.welcome.lift()
            return
        if self.current.lookup_dialog:
            self.current.lookup_dialog.destroy()
        if self.settings_open():
            self.settings.lift()
            self.settings.focus_force()
            return
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        self.settings = dialog
        style = ttk.Style(dialog)
        guide = self.current
        layout = guide.layout
        px = layout.px
        bounds = layout._work_area(layout.x, layout.y, layout.width, layout.height)
        fit_job = None
        guide._clear_wheel_target()

        def restore_inputs(event):
            if event.widget is dialog:
                if fit_job is not None:
                    dialog.after_cancel(fit_job)
                self.settings = None
                if not self.closed and self.visible and self.current is guide:
                    guide._sync_click_mode()
                    guide._schedule_targets()
        dialog.bind("<Destroy>", restore_inputs)
        dialog.bind("<Configure>", lambda event: guide._schedule_targets() if event.widget is dialog else None)
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        labels = []
        def caption(text):
            variable = tk.StringVar(dialog)
            labels.append((variable, text))
            return variable

        def update_labels():
            tr = lambda value: ui_text(value, self.language)
            name = "Settings" if self.language == "en" else "Optionen"
            dialog.title(f"{name} · Buildschmiede Companion")
            for variable, value in labels:
                variable.set(value(tr) if callable(value) else tr(value))
            for controls in (page_nav, tabs_visibility, quick_visibility, welcome_actions):
                controls.reflow()
            dialog.refresh_manual_level()

        if guide.window.winfo_viewable():
            dialog.transient(guide.window)
        dialog.attributes("-topmost", True)
        dialog.resizable(True, True)
        dialog.configure(bg=PANEL_EDGE, padx=1, pady=1)
        viewport = tk.Canvas(dialog, bg=BUTTON_BG, bd=0, highlightthickness=0)
        bar = tk.Frame(dialog, padx=px(14), pady=px(8))
        bar.pack(fill="x")
        trim = tk.Canvas(dialog, bd=0, highlightthickness=0, height=guide.layout.px(8))

        def draw_trim(event=None):
            trim.delete("all")
            paint_rule(trim, self.theme, trim.winfo_width(), trim.winfo_height(), guide.layout.px)

        trim.bind("<Configure>", draw_trim)
        bar.columnconfigure(1, weight=1)
        mark = tk.Label(bar, image=self.brand_mark(px(28)), bd=0)
        mark.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, px(9)))
        title = tk.Label(bar, textvariable=caption(lambda _: companion_title(self.language)),
                         anchor="w", justify="left", bd=0, padx=0, pady=0)
        title.grid(row=0, column=1, sticky="ew")
        title.bind("<Configure>", lambda event: title.configure(wraplength=max(1, event.width)))
        version = tk.Label(bar, text=f"{BUILD_LABEL}  ·  Port {self.http.server_port}", anchor="w", bd=0)
        version.grid(row=1, column=1, sticky="w", pady=(px(1), 0))
        finish_button = tk.Button(bar, textvariable=caption(
            lambda _: "Quit Companion" if self.language == "en" else "Companion beenden"),
            command=self.close, cursor="hand2", padx=px(9), pady=px(4))
        finish_button.grid(row=0, column=2, rowspan=2, sticky="e", padx=(px(10), 0))
        footer = tk.Frame(dialog, padx=px(10), pady=px(6))
        footer.pack(side="bottom", fill="x")
        viewport.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(dialog, orient="vertical", command=viewport.yview, style="Settings.Vertical.TScrollbar")

        def sync_scroll(first, last):
            scroll.set(first, last)
            if float(first) > 0 or float(last) < 1:
                if not scroll.winfo_manager():
                    scroll.place(in_=viewport, relx=1, x=-px(2), rely=0.02, relheight=0.96, anchor="ne")
                    scroll.lift()
            elif scroll.winfo_manager():
                scroll.place_forget()

        viewport.configure(yscrollcommand=sync_scroll)
        sheet = tk.Frame(viewport, padx=px(12), pady=px(8))
        experience_keys = tuple(EXPERIENCE_LEVELS)
        experience_index = experience_keys.index(self.experience_level)
        campaign_options = self.allows("campaign_tools")
        clip_options = self.allows("endgame")
        timer_options = self.allows("timers")
        experimental_options = self.allows("experimental")
        pairs = []
        footer_buttons = []
        hotkey_rows = []
        column_count = None
        action_columns = None
        gap = layout.px(7)  # space between option cards
        row_gap = layout.px(1)  # vertical space between rows inside a card
        indent = layout.px(22)  # dependent options below their switch
        inline_buttons = []

        def pair():
            row = tk.Frame(frame)
            row.pack(fill="x", pady=(0, gap))
            return row

        def group(parent, label):
            panel = tk.LabelFrame(parent, labelanchor="nw")
            panel.configure(labelwidget=tk.Label(panel, textvariable=caption(label), anchor="w"))
            return panel

        settings_pages = {}
        page_buttons = {}
        available_pages = {
            "general": ("Allgemein", "General"),
            "hud": ("HUD & Anzeige", "HUD & Display"),
            "campaign": ("Kampagne", "Campaign"),
            "website": ("Website & Clips", "Website & Clips"),
            "hotkeys": ("Tastenkürzel", "Shortcuts"),
        }
        if not campaign_options:
            available_pages.pop("website")
        page_nav = FlowRow(dialog, bg=self.theme.panel, gap=gap, distribute=True)
        page_nav.pack(before=viewport, fill="x", padx=px(12), pady=(gap, px(2)))
        active_page = None

        def style_tab(button, selected):
            theme = self.theme
            button.configure(bg=theme.active if selected else theme.control,
                             fg=theme.accent if selected else theme.text,
                             activebackground=theme.active, activeforeground=theme.accent,
                             highlightbackground=theme.accent if selected else theme.edge,
                             highlightcolor=theme.text)

        def select_page(key):
            nonlocal active_page
            if active_page is not None:
                settings_pages[active_page].pack_forget()
            active_page = key
            for name, button in page_buttons.items():
                style_tab(button, name == active_page)
            settings_pages[key].pack(fill="x")
            viewport.yview_moveto(0)
            queue_fit()

        for key, (de, en) in available_pages.items():
            settings_pages[key] = tk.Frame(sheet)
            page_buttons[key] = tk.Button(page_nav, cursor="hand2", padx=px(8), pady=px(5),
                                          textvariable=caption(lambda _, de=de, en=en: en if self.language == "en" else de),
                                          command=lambda key=key: select_page(key))
        frame = settings_pages["general"]

        def detail_group(label, available=True):
            panel = group(frame, label)
            if available:
                panel.pack(fill="x", pady=(0, gap))
            return panel

        def inline_button(parent, **options):
            button = tk.Button(parent, cursor="hand2", **options)
            inline_buttons.append(button)
            return button

        page = viewport.create_window(0, 0, anchor="nw", window=sheet)

        def fit_page():
            nonlocal fit_job
            fit_job = None
            chrome = sum(widget.winfo_reqheight() for widget in (bar, page_nav, footer))
            chrome += trim.winfo_reqheight() if trim.winfo_manager() else 0
            top = max(bounds[1], dialog.winfo_rooty()) if dialog.winfo_ismapped() else bounds[1]
            available = max(px(90), bounds[3] - top - chrome - px(30))
            height = min(sheet.winfo_reqheight(), available)
            if int(viewport.cget("height")) != height:
                viewport.configure(height=height)

        def queue_fit():
            nonlocal fit_job
            if fit_job is None:
                fit_job = viewport.after_idle(fit_page)

        def update_region(event=None):
            box = viewport.bbox(page)
            if box:
                visible_height = viewport.winfo_height()
                viewport.configure(scrollregion=(0, 0, box[2], max(box[3], visible_height)))
                if box[3] <= visible_height:
                    viewport.yview_moveto(0)
            if event is not None and event.widget is sheet:
                queue_fit()

        def arrange_actions(width):
            nonlocal action_columns
            side_padding = 2 * (int(footer.cget("padx")) + int(footer.cget("highlightthickness")))
            button_width = max(button.winfo_reqwidth() for button in footer_buttons) + 8
            columns = max(1, min(len(footer_buttons), (width - side_padding) // button_width))
            if columns == action_columns:
                return
            action_columns = columns
            single_row = columns == len(footer_buttons)
            for col in range(len(footer_buttons)):
                expanding = col == columns - 1 if single_row else col < columns
                footer.columnconfigure(col, weight=int(expanding),
                                       uniform="actions" if col < columns and not single_row else "")
            for i, button in enumerate(footer_buttons):
                row, column = divmod(i, columns)
                span = columns - column if button is feedback_button else 1
                anchor = ("e" if button is feedback_button else "w") if single_row else "nsew"
                button.grid(row=row, column=column, columnspan=span, sticky=anchor, padx=px(3), pady=px(1))

        def arrange(width):
            nonlocal column_count
            if width <= 1:
                return
            wide = width >= layout.px(670)
            columns = 4 if wide else 2
            if columns != column_count:
                column_count = columns
                for left, right in pairs:
                    row = left.master
                    row.columnconfigure(0, weight=1, uniform="settings" if wide else "")
                    row.columnconfigure(1, weight=int(wide), uniform="settings" if wide else "")
                    left.grid(row=0, column=0, sticky="nsew", padx=(0, gap // 2 if wide else 0))
                    right.grid(row=0 if wide else 1, column=1 if wide else 0, sticky="nsew",
                               padx=(gap // 2 if wide else 0, 0), pady=(0 if wide else gap, 0))
                hotkey_split = (len(hotkey_rows) + 1) // 2 if wide else len(hotkey_rows)
                for i, (label, entry) in enumerate(hotkey_rows):
                    row, column = i % hotkey_split, (i // hotkey_split) * 2
                    label.grid(row=row, column=column, sticky="w", padx=(layout.px(18) if column else 0, layout.px(10)),
                               pady=row_gap)
                    entry.grid(row=row, column=column+1, sticky="ew", pady=row_gap, ipady=layout.px(2))
                keys.columnconfigure(3, weight=int(wide))
                hotkey_hint.grid(row=hotkey_split, column=0, columnspan=columns, sticky="w", pady=(layout.px(6), 0))
                hotkey_save.grid(row=hotkey_split + 1, column=0, columnspan=columns, sticky="e",
                                 pady=(gap, row_gap))
            arrange_actions(width)
            viewport.itemconfigure(page, width=max(1, width - px(4)))
            update_region()
        sheet.bind("<Configure>", update_region)
        viewport.configure(yscrollincrement=layout.px(24))

        def scroll_options(steps):
            first, last = viewport.yview()
            if (steps < 0 and first > 0) or (steps > 0 and last < 1):
                viewport.yview_scroll(steps, "units")

        dialog.bind("<MouseWheel>", lambda event: scroll_options(-int(event.delta / 120)))
        dialog.bind("<Button-4>", lambda event: scroll_options(-1))
        dialog.bind("<Button-5>", lambda event: scroll_options(1))
        experience = group(frame, lambda _: "Feature profile" if self.language == "en" else "Funktionsumfang")
        experience.pack(fill="x", pady=(0, gap))
        experience_box = ttk.Combobox(experience, style="Settings.Guide.TCombobox", state="readonly", width=24)
        experience_box.pack(fill="x")

        def update_experience_choices():
            experience_box.configure(values=[labels[self.language == "en"] for labels in EXPERIENCE_LEVELS.values()])
            experience_box.current(experience_index)

        def select_experience(event):
            index = experience_box.current()
            if index >= 0 and index != experience_index:
                self.set_experience(experience_keys[index])

        update_experience_choices()
        experience_box.bind("<<ComboboxSelected>>", select_experience)
        experience_description = tk.Label(experience, justify="left", anchor="w",
                                          textvariable=caption(lambda _: EXPERIENCE_LEVELS[self.experience_level][
                                              2 + (self.language == "en")]))
        experience_description.pack(fill="x", pady=(layout.px(5), row_gap))
        experience_description.bind("<Configure>", lambda event: experience_description.configure(
            wraplength=event.width) if event.width > 1 else None)

        frame = settings_pages["hud"]
        hud_controls = detail_group(lambda _: "HUD bars" if self.language == "en" else "HUD-Leisten")
        quick_visible = tk.BooleanVar(dialog, self.prefs.get("hud_quick_visible", True))
        hud_visibility_buttons = []
        style.layout("Settings.TCheckbutton", [("Button.border", {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "w"})
            ]})
        ]})])
        style.layout("Settings.TRadiobutton", style.layout("Settings.TCheckbutton"))

        def press_toggle(event):
            # Keep the normal ttk release and keyboard bindings without drawing focus on mouse clicks.
            button = event.widget
            if button.instate(("!disabled",)):
                if dialog.focus_get() == button:
                    dialog.focus_set()
                button.state(("pressed",))
            return "break"

        def visibility_options(container, items, preference):
            icons = {"lookup": "learn", "lock": "locked", "mode": "detailed"}
            for key, (de, en, feature) in items.items():
                if feature is not None and not self.allows(feature):
                    continue
                names = ("zoom_out", "zoom_in") if key == "zoom_out" else (key,)
                checked = tk.BooleanVar(dialog, any(name not in self.prefs.get(preference, ()) for name in names))
                button = ttk.Checkbutton(
                    container, style="Settings.TCheckbutton", variable=checked, compound="left",
                    textvariable=caption(lambda _, de=de, en=en: en if self.language == "en" else de),
                    command=lambda names=names, checked=checked: self.set_hud_visibility(
                        preference, names=names, visible=checked.get()))
                hud_visibility_buttons.append((button, icons.get(key, key)))
            container.reflow()

        tabs_visibility = FlowRow(hud_controls, bg=self.theme.control, gap=layout.px(4))
        tabs_visibility.pack(fill="x", pady=(0, gap))
        visibility_options(tabs_visibility, HUD_TABS, "hidden_hud_tabs")

        def toggle_quick_bar():
            self.set_hud_visibility("hud_quick_visible", visible=quick_visible.get())
            if quick_visible.get():
                quick_visibility.pack(fill="x", pady=(0, row_gap))
            else:
                quick_visibility.pack_forget()

        ttk.Checkbutton(hud_controls, style="Settings.TCheckbutton", variable=quick_visible,
                        textvariable=caption(lambda _: "Show quick settings" if self.language == "en"
                                             else "Schnelleinstellungen anzeigen"),
                        command=toggle_quick_bar).pack(anchor="w", pady=row_gap)
        quick_visibility = FlowRow(hud_controls, bg=self.theme.control, gap=layout.px(4))
        if quick_visible.get():
            quick_visibility.pack(fill="x", pady=(0, row_gap))
        quick_options = {key: labels for key, labels in HUD_QUICK.items() if key != "zoom_in"}
        quick_options["zoom_out"] = ("Zoom", "Zoom", None)
        visibility_options(quick_visibility, quick_options, "hidden_hud_quick")

        display = detail_group("Anzeige")
        rect = self.native.display_bounds(guide.window) if self.native else layout._screen()
        resolution = tk.Label(display, text=f"{rect[2]-rect[0]} × {rect[3]-rect[1]}   ·   {layout.dpi} DPI")
        resolution.grid(row=0, columnspan=3, sticky="w", pady=(0, layout.px(4)))
        def adjust(key, value):
            value = int(float(value))
            if key == "zoom":
                guide.zoom(value - layout.scale)
            elif key == "height":
                self.save_preferences(**{HUD_HEIGHT_LIMIT: value})
                if guide.showing_atlas:
                    guide.endgame._fit()
                else:
                    guide._refit_route()
            elif key == "width":
                layout.place(layout.x, layout.y, value, layout.height)
                layout.save()
            else:
                self.prefs[key] = value
                if self.appearance_save:
                    self.root.after_cancel(self.appearance_save)
                self.appearance_save = self.root.after(220, self.flush_appearance)
                if self.native:
                    if key == "transparency":
                        self.native.set_opacity(guide.window, self.overlay_alpha())
                else:
                    guide.window.attributes("-alpha", self.overlay_alpha()/255)
                if self.speedrun_hud is not None:
                    self.speedrun_hud.apply_opacity()
                guide._schedule_targets()
        bounds = layout._work_area(layout.x, layout.y, layout.width, layout.height)
        sliders = [("Transparenz", "transparency", 0, 90, self.prefs.get("transparency", 0)),
                   ("Zoom", "zoom", 80, 160, layout.scale),
                   ("Breite", "width", min(layout.width, layout.px(HUD_MIN_SIZE[0] * layout.scale / 100)), layout._width_limit(bounds[0], bounds[2]), layout.width),
                   ("Maximale Höhe", "height", min(guide.height_limit(), layout.px(HUD_MIN_SIZE[1] * layout.scale / 100)), guide.height_limit(),
                    min(guide.height_limit(), self.prefs.get(HUD_HEIGHT_LIMIT, guide.height_limit())))]
        for row, (label, key, low, high, initial) in enumerate(sliders, 1):
            tk.Label(display, textvariable=caption(label)).grid(row=row, column=0, sticky="w")
            unit = " px" if key in ("width", "height") else "%"
            number = tk.StringVar(display, value=f"{initial}{unit}")
            def change(value, key=key, unit=unit, number=number):
                adjust(key, value)
                actual = layout.width if key == "width" else value
                number.set(f"{actual}{unit}")
            slider = BrassSlider(display, low, high, initial, change, layout.px)
            slider.configure(height=layout.px(22))
            slider.grid(row=row, column=1, sticky="ew", padx=14, pady=row_gap)
            tk.Label(display, textvariable=number, width=7, anchor="e").grid(row=row, column=2)
            if key == "zoom":
                def sync_zoom(window, slider=slider, number=number):
                    if window is guide:
                        slider.set(layout.scale, notify=False)
                        number.set(f"{layout.scale}%")
                dialog.sync_zoom = sync_zoom
        tk.Label(display, textvariable=caption(lambda _: "Card background" if self.language == "en" else "Kachelhintergrund")).grid(
            row=len(sliders)+1, column=0, sticky="w")
        cards = ttk.Combobox(display, style="Settings.Guide.TCombobox", state="readonly", width=16)
        cards.grid(row=len(sliders)+1, column=1, columnspan=2, sticky="ew", padx=(14, 0), pady=row_gap)

        def update_card_choices():
            cards.configure(values=[label[self.language == "en"] for label in CARD_BACKGROUNDS.values()])
            cards.current(list(CARD_BACKGROUNDS).index(self.card_background))

        def select_card_background(event):
            index = cards.current()
            if index >= 0:
                self.save_preferences(card_background=list(CARD_BACKGROUNDS)[index])
                guide.apply_theme()

        update_card_choices()
        cards.bind("<<ComboboxSelected>>", select_card_background)
        tk.Label(display, textvariable=caption(lambda _: "Section colors" if self.language == "en" else "Abschnittsfarben")).grid(
            row=len(sliders)+2, column=0, sticky="w")
        accent_box = ttk.Combobox(display, style="Settings.Guide.TCombobox", state="readonly", width=16)
        accent_box.grid(row=len(sliders)+2, column=1, columnspan=2, sticky="ew", padx=(14, 0), pady=row_gap)

        def update_accent_choices():
            accent_box.configure(values=[label[self.language == "en"] for label in CARD_ACCENTS.values()])
            accent_box.current(list(CARD_ACCENTS).index(self.card_accents))

        def select_card_accent(event):
            index = accent_box.current()
            if index >= 0:
                self.save_preferences(card_accents=list(CARD_ACCENTS)[index])
                guide.refresh_guide()

        update_accent_choices()
        accent_box.bind("<<ComboboxSelected>>", select_card_accent)
        tk.Label(display, textvariable=caption(lambda _: "Color intensity" if self.language == "en" else "Farbstärke")).grid(
            row=len(sliders)+3, column=0, sticky="w")
        intensity_choices = tk.Frame(display)
        intensity_choices.grid(row=len(sliders)+3, column=1, columnspan=2, sticky="ew", padx=(14, 0), pady=row_gap)
        intensity_value = tk.StringVar(dialog, value=self.color_intensity)

        def select_intensity():
            self.save_preferences(color_intensity=intensity_value.get())
            guide.apply_theme()

        for key, names in COLOR_INTENSITY.items():
            ttk.Radiobutton(intensity_choices, style="Settings.TRadiobutton", value=key, variable=intensity_value,
                            textvariable=caption(lambda _, names=names: names[self.language == "en"]),
                            command=select_intensity).pack(side="left", padx=(0, px(4)))
        tk.Label(display, textvariable=caption(lambda _: "Menu background" if self.language == "en" else "Menüleisten-Hintergrund")).grid(
            row=len(sliders)+4, column=0, sticky="w")
        menu_choices = ttk.Combobox(display, style="Settings.Guide.TCombobox", state="readonly", width=16)
        menu_choices.grid(row=len(sliders)+4, column=1, columnspan=2, sticky="ew", padx=(14, 0), pady=row_gap)

        def update_menu_choices():
            menu_choices.configure(values=[label[self.language == "en"] for label in MENU_BACKGROUNDS.values()])
            menu_choices.current(list(MENU_BACKGROUNDS).index(self.menu_background))

        def select_menu_background(event):
            self.save_preferences(menu_background=list(MENU_BACKGROUNDS)[menu_choices.current()])
            guide._style_chrome()
            guide._draw_header()
            guide._sync_click_mode()
            guide._schedule_targets()

        update_menu_choices()
        menu_choices.bind("<<ComboboxSelected>>", select_menu_background)
        if experimental_options and self.can_mirror_background:
            shaped = tk.BooleanVar(dialog, self.prefs.get("linux_transparent", True) is True)
            ttk.Checkbutton(display, style="Settings.TCheckbutton", variable=shaped,
                            textvariable=caption(lambda _: "See-through background (after restart)" if self.language == "en"
                                                 else "Durchsichtiger Hintergrund (nach Neustart)"),
                            command=lambda: self.set_mirrored_background(shaped.get())).grid(
                                row=len(sliders)+5, column=0, columnspan=3, sticky="w", pady=row_gap)
        if not campaign_options:
            for widget in display.grid_slaves():
                if int(widget.grid_info()["row"]) > len(sliders):
                    widget.grid_remove()
        display.columnconfigure(1, weight=1)
        frame = settings_pages["general"]
        appearance = pair()
        themes = group(appearance, "Themes")
        theme_box = ttk.Combobox(themes, style="Settings.Guide.TCombobox", state="readonly", width=16)

        def update_theme_choices():
            theme_box.configure(values=[theme_label(name, self.language) for name in THEMES])
            theme_box.current(list(THEMES).index(self.theme_name))

        update_theme_choices()
        theme_box.pack(side="left", padx=(0, px(9)), fill="x", expand=True)
        swatches = tk.Canvas(themes, height=px(17), width=px(75), bg="#151515",
                             highlightthickness=0, bd=0)
        swatches.pack(side="left")
        guide_choices = pair()
        startup = group(guide_choices, lambda _: "Startup" if self.language == "en" else "Beim Start")
        language_card = group(appearance, lambda _: "Language" if self.language == "en" else "Sprache")
        if campaign_options:
            pairs.append((themes, language_card))
        else:
            language_card.pack(fill="x")
            startup.pack(fill="x")
        language_box = ttk.Combobox(language_card, style="Settings.Guide.TCombobox", width=16,
                                    values=list(LANGUAGES.values()), state="readonly")
        language_box.set(LANGUAGES[self.language])
        language_box.pack(fill="x")
        def select_language(event):
            self.set_language(list(LANGUAGES)[language_box.current()])
            update_labels()
            update_experience_choices()
            update_theme_choices()
            update_card_choices()
            update_menu_choices()
            update_accent_choices()
            clip_status.set("")
            update_clip_rows()
            dialog.after_idle(lambda: arrange_actions(footer.winfo_width()))
        language_box.bind("<<ComboboxSelected>>", select_language)
        mode_box = group(guide_choices, lambda _: "Default view" if self.language == "en" else "Standardansicht")
        if campaign_options:
            pairs.append((startup, mode_box))
        mode_value = tk.StringVar(dialog, value=self.state["guideMode"])
        self.settings_mode = mode_value
        for key, label in MODE_LABELS.items():
            ttk.Radiobutton(mode_box, style="Settings.TRadiobutton", textvariable=caption(label),
                            variable=mode_value, value=key, command=lambda key=key: self.set_mode(key)).pack(
                                side="left", anchor="n", padx=(0, px(4)))
        frame = settings_pages["campaign"]
        checklist = detail_group(lambda _: "Checklist" if self.language == "en" else "Checkliste", campaign_options)
        checking = tk.BooleanVar(dialog, self.checklist_enabled)
        options = []

        def sync_checklist():
            checking.set(self.checklist_enabled)
            for option in options:
                option.state(["!disabled"] if checking.get() else ["disabled"])

        dialog.sync_checklist = sync_checklist
        ttk.Checkbutton(checklist, style="Settings.TCheckbutton", variable=checking,
                        textvariable=caption(lambda _: "Enable checklist" if self.language == "en" else "Checkliste aktivieren"),
                        command=lambda: self.set_checklist_enabled(checking.get())).pack(anchor="w", pady=row_gap)
        for key, default, german, english in (
                ("checklist_fold_completed", True, "Abgeschlossene Abschnitte automatisch einklappen", "Auto-collapse completed sections"),
                ("checklist_hide_completed", False, "Abgeschlossene Abschnitte automatisch ausblenden", "Auto-hide completed sections")):
            variable = tk.BooleanVar(dialog, self.prefs.get(key, default))
            def set_behavior(key=key, variable=variable):
                self.save_preferences(**{key: variable.get()})
                guide.refresh_guide()
            option = ttk.Checkbutton(checklist, style="Settings.TCheckbutton", variable=variable,
                                     textvariable=caption(lambda _, de=german, en=english: en if self.language == "en" else de),
                                     command=set_behavior)
            option.pack(anchor="w", padx=(indent, 0), pady=row_gap)
            if not checking.get():
                option.state(["disabled"])
            options.append(option)

        inline_button(checklist, command=lambda: self.start_checklist_run(dialog), textvariable=caption(
            lambda _: "New run checklist" if self.language == "en" else "Neue Run-Checkliste")).pack(
                anchor="w", pady=(layout.px(6), row_gap))

        sections = detail_group("Gebietsabschnitte", campaign_options)
        sections.columnconfigure((0, 1), weight=1)
        for index, name in enumerate(GUIDE_SECTIONS):
            enabled = tk.BooleanVar(dialog, name not in self.prefs.get("hidden_sections", []))
            label = "Quests und Questbelohnungen" if name == "Quest" else name
            option = ttk.Checkbutton(sections, style="Settings.TCheckbutton", textvariable=caption(label), variable=enabled,
                                    command=lambda n=name, v=enabled: self.set_section_visible(n, v.get()))
            option.variable = enabled
            option.grid(row=index//2, column=index%2, sticky="w", padx=(0, layout.px(12)), pady=row_gap)
        boss = tk.BooleanVar(dialog, self.auto_boss)
        ttk.Checkbutton(sections, style="Settings.TCheckbutton", variable=boss,
                        textvariable=caption("Boss-Guide in bekannten Boss-Gebieten automatisch öffnen"),
                        command=lambda: self.set_auto_boss(boss.get())).grid(
                            row=(len(GUIDE_SECTIONS)+1)//2, column=0, columnspan=2, sticky="w",
                            pady=(layout.px(5), row_gap))

        location = detail_group(lambda _: "Area detection" if self.language == "en" else "Gebietserkennung")
        location.columnconfigure(0, weight=1)
        tk.Label(location, textvariable=caption(server.get_location_status().get("message", "")),
                 wraplength=layout.px(270), justify="left", anchor="w").grid(row=0, column=0, sticky="ew", pady=row_gap)
        inline_button(location, textvariable=caption("Client.txt wählen"), command=self.pick_client_log).grid(
            row=0, column=1, sticky="e", padx=(gap, 0))

        frame = settings_pages.get("website") or tk.Frame(sheet)
        website = detail_group(lambda _: "Website content" if self.language == "en" else "Website-Inhalte", campaign_options)
        website.columnconfigure(0, weight=1)
        website_on = tk.BooleanVar(dialog, self.website_enabled)
        ttk.Checkbutton(website, style="Settings.TCheckbutton", variable=website_on,
                        textvariable=caption(lambda _: "Load glossary and builds from buildschmiede.de" if self.language == "en"
                                             else "Lexikon und Builds von buildschmiede.de laden"),
                        command=lambda: self.set_website_enabled(website_on.get())).grid(
                            row=0, column=0, sticky="w", pady=row_gap)
        tooltips_on = tk.BooleanVar(dialog, self.tooltips_enabled)
        ttk.Checkbutton(website, style="Settings.TCheckbutton", variable=tooltips_on,
                        textvariable=caption(lambda _: "Explain highlighted terms on hover" if self.language == "en"
                                             else "Hervorgehobene Begriffe beim Überfahren erklären"),
                        command=lambda: self.set_tooltips_enabled(tooltips_on.get())).grid(
                            row=1, column=0, sticky="w", padx=(indent, 0), pady=row_gap)
        tk.Label(website, textvariable=caption(lambda _: self.website_status()), justify="left", anchor="w").grid(
            row=2, column=0, sticky="w", pady=row_gap)
        tk.Label(website, textvariable=caption(lambda _: "New builds appear after the next start." if self.language == "en"
                                               else "Neue Builds erscheinen nach dem nächsten Start."),
                 justify="left", anchor="w").grid(row=3, column=0, sticky="w", pady=row_gap)

        clips = detail_group(lambda _: "Boss clips" if self.language == "en" else "Boss-Clips", clip_options)
        clips_staging = tk.BooleanVar(dialog, self.prefs.get("boss_clips_staging", False))
        clip_status = tk.StringVar(dialog)

        def clip_text(de, en):
            return en if self.language == "en" else de

        def update_clip_rows():
            for child in clip_rows.winfo_children():
                child.destroy()
            store = self.boss_clips
            acts = sorted({item["act"] for item in store.catalogue.values()})
            for act in acts:
                pending = store.missing(act)
                total = sum(item["act"] == act for item in store.catalogue.values())
                size = sum(item["bytes"] for item in pending)
                megabytes = f"{size / 1_000_000:.1f}".replace(".", clip_text(",", "."))
                label = clip_text(act.replace("Act ", "Akt "), act)
                if pending:
                    label = clip_text(f"{label} herunterladen", f"Download {label}")
                    label += f" · {len(pending)}/{total} · {megabytes} MB"
                    button = self.current.small_button(
                        clip_rows, label, lambda store=store, pending=pending: download_clips(store, pending))
                else:
                    label += " · " + clip_text("offline bereit", "available offline")
                    button = self.current.small_button(clip_rows, label, lambda: None)
                    button.configure(state="disabled")
                button.pack(fill="x", pady=row_gap)

        def finish_clips(ok, count):
            if not clips.winfo_exists():
                return
            if ok:
                status = (clip_text("Clip-Liste geladen.", "Clip list loaded.") if count is None else
                          clip_text(f"{count} Clips jetzt offline verfügbar.", f"{count} clips now available offline."))
                if count is None and not self.boss_clips.catalogue:
                    status = clip_text("Für diese Website sind keine Clips zugeordnet.", "No clips are assigned on this site yet.")
            elif count == "HTTP 401":
                status = clip_text("Diese Website verlangt eine Anmeldung. Lokale Clips sind verfügbar.",
                                   "This website requires sign-in. Local clips are available.")
            else:
                status = clip_text("Abruf fehlgeschlagen. Gespeicherte Clips bleiben verfügbar.",
                                   "Could not load clips. Saved clips are still available.")
            clip_status.set(status)
            update_clip_rows()

        def refresh_clip_list():
            if self.run_clip_job(self.boss_clips.refresh, finish_clips):
                clip_status.set(clip_text("Clip-Liste wird geladen …", "Loading clip list …"))

        def select_clip_source():
            if self.clip_job:
                clips_staging.set(self.prefs.get("boss_clips_staging", False))
                return
            staging = clips_staging.get()
            self.save_preferences(boss_clips_staging=staging)
            self.boss_clips = BossClipStore(self.directory, staging)
            self.current.refresh_guide()
            update_clip_rows()
            refresh_clip_list()

        def download_clips(store, items):
            if self.run_clip_job(lambda: store.download(items), finish_clips):
                clip_status.set(clip_text("Clips werden heruntergeladen …", "Downloading clips …"))

        if experimental_options:
            ttk.Checkbutton(clips, style="Settings.TCheckbutton", variable=clips_staging,
                            textvariable=caption(lambda _: clip_text("Testumgebung verwenden", "Use staging website")),
                            command=select_clip_source).pack(anchor="w", pady=row_gap)
        inline_button(clips, textvariable=caption(lambda _: clip_text("Clip-Liste laden", "Load clip list")),
                      command=refresh_clip_list).pack(anchor="w", pady=row_gap)
        tk.Label(clips, textvariable=clip_status, justify="left", anchor="w",
                 wraplength=layout.px(300)).pack(anchor="w", pady=row_gap)
        clip_rows = tk.Frame(clips)
        clip_rows.pack(fill="x")
        update_clip_rows()

        frame = settings_pages["hud"]
        level_box = detail_group(lambda _: "Level display" if self.language == "en" else "Levelanzeige", campaign_options)
        level_box.columnconfigure(0, weight=1)
        level_visible = tk.BooleanVar(dialog, self.prefs.get("level_visible", True))
        ttk.Checkbutton(level_box, style="Settings.TCheckbutton", variable=level_visible,
                        textvariable=caption(lambda _: "Show level and XP efficiency" if self.language == "en"
                                             else "Level und XP-Ausbeute anzeigen"),
                        command=lambda: self.set_level_visible(level_visible.get())).grid(row=0, column=0, sticky="w",
                                                                                           pady=row_gap)

        manual_panel = tk.Frame(level_box)
        manual_level = tk.StringVar(dialog)
        manual_feedback = tk.StringVar(dialog)
        current_level_text = tk.StringVar(dialog)

        def refresh_manual_level():
            check = self.state.get("levelCheck", {})
            value = check.get("characterLevel")
            en = self.language == "en"
            if value is None:
                text = "No level detected yet" if en else "Level noch unbekannt"
            else:
                source = ("manual" if en else "manuell") if check.get("manualLevel") else ("automatic" if en else "automatisch")
                text = f"{'Current level' if en else 'Aktuelles Level'} {value} ({source})"
            if current_level_text.get() != text:
                current_level_text.set(text)

        dialog.refresh_manual_level = refresh_manual_level
        manual_entry = tk.Entry(manual_panel, textvariable=manual_level, width=6, justify="center")
        manual_entry.grid(row=0, column=0, padx=(0, 6), ipady=layout.px(2))
        def apply_manual_level(event=None):
            raw = manual_level.get().strip()
            if not (1 <= len(raw) <= 3 and raw.isdecimal() and 1 <= int(raw) <= 100):
                manual_feedback.set("Enter a level from 1 to 100." if self.language == "en"
                                    else "Gib ein Level von 1 bis 100 ein.")
                return
            manual_feedback.set("")
            self.set_manual_level(int(raw))

        def clear_manual_level():
            manual_level.set("")
            manual_feedback.set("")
            self.set_manual_level(None)

        inline_button(manual_panel, textvariable=caption(lambda _: "Apply level" if self.language == "en" else "Level übernehmen"),
                      command=apply_manual_level).grid(row=0, column=1, padx=(0, 6))
        inline_button(manual_panel, textvariable=caption(lambda _: "Automatic" if self.language == "en" else "Automatisch"),
                      command=clear_manual_level).grid(row=0, column=2)
        tk.Label(manual_panel, textvariable=caption(lambda _: "The next detected level-up takes over."
                                                   if self.language == "en" else "Das nächste erkannte Level-up übernimmt automatisch."),
                 anchor="w", justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        tk.Label(manual_panel, textvariable=current_level_text, anchor="w").grid(row=2, column=0, columnspan=3, sticky="w")
        tk.Label(manual_panel, textvariable=manual_feedback, anchor="w").grid(row=3, column=0, columnspan=3, sticky="w")
        manual_entry.bind("<Return>", apply_manual_level)

        def toggle_manual_panel():
            if manual_panel.winfo_manager():
                manual_panel.grid_remove()
            else:
                check = self.state.get("levelCheck", {})
                current_level = check.get("characterLevel")
                manual_level.set("" if current_level is None else str(current_level))
                manual_feedback.set("")
                manual_panel.grid(row=2, column=0, columnspan=2, sticky="e", pady=(4, 0))
                manual_entry.focus_set()
                manual_entry.selection_range(0, "end")

        inline_button(level_box, textvariable=caption(lambda _: "Set level manually" if self.language == "en"
                                                       else "Level manuell einstellen"),
                      command=toggle_manual_panel).grid(row=0, column=1, sticky="e", padx=(gap, 0))

        dialog.timer_visible = timer = tk.BooleanVar(dialog, self.timer_visible)
        if timer_options:
            ttk.Checkbutton(level_box, style="Settings.TCheckbutton", variable=timer,
                            textvariable=caption(lambda _: "Show speedrun timer" if self.language == "en"
                                                 else "Speedrun-Timer anzeigen"),
                            command=lambda: self.set_timer(timer.get())).grid(row=1, column=0, sticky="w", pady=row_gap)
        show_welcome = tk.BooleanVar(dialog, self.show_welcome_on_start)
        welcome_actions = FlowRow(startup, bg=self.theme.control, gap=px(7))
        welcome_actions.pack(fill="x")
        ttk.Checkbutton(welcome_actions, variable=show_welcome, style="Settings.TCheckbutton",
                        textvariable=caption(lambda _: "Show welcome" if self.language == "en" else "Willkommen anzeigen"),
                        command=lambda: self.save_preferences(show_welcome_on_start=show_welcome.get(),
                                                               welcome_setup_completed=True))
        inline_button(welcome_actions, command=self.open_welcome,
                      textvariable=caption(lambda _: "Open now" if self.language == "en" else "Jetzt öffnen"))
        frame = settings_pages["hotkeys"]
        keys = detail_group("Hotkeys")
        fields = {}
        for action, (label, _) in HUD_HOTKEYS.items():
            entry = tk.Entry(keys, width=11)
            entry.insert(0, self.keys[action])
            if action <= 4 or timer_options:
                hotkey_rows.append((tk.Label(keys, textvariable=caption(label)), entry))
            fields[action] = entry
        keys.columnconfigure(1, weight=1)
        hotkey_hint = tk.Label(keys, textvariable=caption("Beispiele  F6 · F7 · Strg+Alt+R  |  leer = aus"), anchor="w")
        hotkey_save = inline_button(keys, textvariable=caption("Hotkeys speichern"),
                                    command=lambda: self.save_hotkeys(fields))
        if experimental_options:
            footer_buttons.append(tk.Button(footer, textvariable=caption(
                lambda _: "Error log" if self.language == "en" else "Fehlerprotokoll"),
                command=lambda: webbrowser.open(ERROR_LOG.as_uri()), padx=px(9), pady=px(4)))
        footer_buttons.append(tk.Button(footer, textvariable=caption(
            lambda _: "Reset settings" if self.language == "en" else "Einstellungen zurücksetzen"),
            command=self.reset_options, padx=px(9), pady=px(4)))
        feedback_button = tk.Button(footer, command=self.open_feedback, cursor="hand2", padx=px(9), pady=px(4),
                                    textvariable=caption(lambda _: "Send feedback" if self.language == "en"
                                                         else "Feedback geben"))
        footer_buttons.append(feedback_button)

        def style_panel(widget, surface, family):
            theme = self.theme
            treatment = theme.treatment
            for child in widget.winfo_children():
                child_surface = theme.control if isinstance(child, tk.LabelFrame) else surface
                if isinstance(child, BrassSlider):
                    child.apply_theme(theme._replace(panel=surface))
                if isinstance(child, (tk.Label, tk.LabelFrame, tk.Radiobutton, tk.Checkbutton, tk.Scale, tk.Button)):
                    child.configure(bg=child_surface, fg=theme.text, font=(family, 10))
                if isinstance(child, tk.Frame):
                    child.configure(bg=surface)
                if isinstance(child, tk.LabelFrame):
                    # One outline per card; the title sits inside the card instead of on a border line.
                    child.configure(bd=0, relief="flat",
                                    highlightthickness=max(1, treatment.card_border),
                                    highlightbackground=theme.edge, highlightcolor=theme.edge,
                                    padx=px(11), pady=px(5))
                if isinstance(child, tk.Button):
                    child.configure(relief="flat", bd=0, bg=theme.control, highlightthickness=1,
                                    highlightbackground=theme.edge, highlightcolor=theme.accent, takefocus=True)
                if isinstance(child, (tk.Button, tk.Checkbutton)):
                    child.configure(activebackground=theme.active, activeforeground=theme.text)
                if isinstance(child, (tk.Checkbutton, tk.Radiobutton)):
                    child.configure(selectcolor=PREVIEW_BG)
                if isinstance(child, (ttk.Checkbutton, ttk.Radiobutton)):
                    child.bind("<ButtonPress-1>", press_toggle)
                if type(child) is tk.Entry:
                    child.configure(bg=theme.field_color,
                                    fg=theme.text, insertbackground=theme.text, font=(family, 10),
                                    relief="flat", bd=0, highlightthickness=1,
                                    highlightbackground=theme.edge, highlightcolor=theme.accent)
                style_panel(child, child_surface, family)
        def color_settings(event=None):
            if event is not None and theme_box.current() >= 0:
                self.set_theme(list(THEMES)[theme_box.current()])
                update_card_choices()
                update_accent_choices()
                intensity_value.set(self.color_intensity)
            theme = self.theme
            family = self.theme_font()
            heading_family = self.theme_font(heading=True)
            treatment = theme.treatment
            surface = theme.control
            toggle_background = [("disabled", theme.control), ("selected", theme.active), ("active", theme.field_color)]
            disabled_text = mix_color(theme.text, theme.control, 0.55)
            for kind in ("Settings.TCheckbutton", "Settings.TRadiobutton"):
                style.configure(kind, background=theme.control, foreground=theme.text,
                                bordercolor=theme.edge, lightcolor=theme.control, darkcolor=theme.control,
                                font=(family, 10),
                                padding=(px(8), px(4)))
                style.map(kind, background=toggle_background, lightcolor=toggle_background, darkcolor=toggle_background,
                          foreground=[("disabled", disabled_text), ("selected", theme.accent)],
                          bordercolor=[("disabled", theme.edge), ("focus", theme.text), ("selected", theme.accent)],
                          relief=[("pressed", "sunken"), ("selected", "sunken"), ("!selected", "flat")])
            for button, icon in hud_visibility_buttons:
                normal, selected = (hud_icon(button, icon, px(15), color) for color in (theme.text, theme.accent))
                button.hud_icons = (normal, selected)
                button.configure(image=(normal, "selected", selected))
            tabs_visibility.reflow()
            quick_visibility.reflow()
            style.configure("Settings.Guide.TCombobox", padding=(px(8), px(4)), arrowsize=px(13))
            style.configure("Settings.Vertical.TScrollbar", troughcolor=theme.panel, background=theme.field_color,
                            bordercolor=theme.edge, lightcolor=theme.field_color, darkcolor=theme.field_color,
                            arrowcolor=theme.accent, arrowsize=px(10), width=px(10), gripcount=0)
            for box in (experience_box, cards, menu_choices, accent_box, theme_box, language_box):
                box.configure(font=(family, 10))
            dialog.configure(bg=theme.panel)
            shade = mix_color(theme.panel, "#000000", 0.24)
            muted = mix_color(theme.text, theme.panel, 0.24)
            bar.configure(bg=shade, highlightthickness=1, highlightbackground=theme.edge)
            mark.configure(bg=shade)
            title.configure(bg=shade, fg=theme.accent, font=(heading_family, 13, "bold"))
            if treatment == CLASSIC:
                trim.pack_forget()
            else:
                trim.configure(bg=shade)
                trim.pack(after=bar, fill="x")
                draw_trim()
            version.configure(bg=shade, fg=muted, font=(family, 9))
            footer.configure(bg=shade, highlightbackground=theme.edge, highlightthickness=1)
            finish_button.configure(bg=theme.control, fg=muted, activebackground=theme.active,
                                    activeforeground=theme.text, relief="flat", bd=0, highlightthickness=1,
                                    font=(family, 9),
                                    highlightbackground=theme.edge, highlightcolor=theme.accent)
            sheet.configure(bg=theme.panel)
            viewport.configure(bg=theme.panel)
            manual_panel.configure(bg=surface)
            swatches.configure(bg=surface)
            swatches.delete("all")
            swatch = theme.edge if treatment == CLASSIC else theme.accent
            for i, shade in enumerate((theme.panel, swatch, theme.text)):
                x = i * px(25)
                swatches.create_rectangle(x+1, 1, x+px(22), px(16), fill=shade, outline=theme.edge)
            style_panel(sheet, theme.panel, family)
            experience_description.configure(fg=muted)
            page_nav.configure(bg=theme.panel)
            style_panel(page_nav, theme.panel, family)
            style_panel(footer, theme.panel, family)
            feedback_button.configure(bg=theme.field_color, highlightbackground=theme.accent,
                                      highlightcolor=theme.text, takefocus=True)
            for button in inline_buttons:
                button.configure(bg=theme.field_color, fg=theme.text, padx=layout.px(10), pady=layout.px(2),
                                 highlightthickness=1, highlightbackground=theme.edge, highlightcolor=theme.accent)
            hotkey_save.configure(padx=px(12), pady=px(4))
            style_tab(hotkey_save, True)
            for key, button in page_buttons.items():
                style_tab(button, key == active_page)
            for panel in (experience, hud_controls, display, themes, language_card, mode_box, checklist, sections,
                          location, website, clips, level_box, startup, keys):
                dialog.nametowidget(str(panel.cget("labelwidget"))).configure(
                    bg=surface, fg=theme.accent, font=(heading_family, 10, "bold"), padx=px(9), pady=px(2))
            queue_fit()
            if event is not None:
                dialog.after_idle(lambda: arrange_actions(footer.winfo_width()))
                if self.native:
                    self.native.style_dialog(dialog, palette=(theme.edge, theme.panel, theme.text))
        theme_box.bind("<<ComboboxSelected>>", color_settings)
        select_page("general")
        color_settings()
        update_labels()
        left, top, right, bottom = bounds
        width = min(px(748 if campaign_options else 560), right - left - px(24))
        arrange(width)
        dialog.minsize(min(width, px(540)), min(bottom - top, px(300)))
        dialog.maxsize(right - left - px(16), bottom - top - px(40))
        viewport.configure(width=max(1, width))
        viewport.bind("<Configure>", lambda event: arrange(event.width))
        page_nav.bind("<Configure>", lambda _: queue_fit(), add="+")
        footer.bind("<Configure>", lambda _: queue_fit())
        dialog.update_idletasks()
        x = (left + right - dialog.winfo_reqwidth()) // 2
        y = (top + bottom - min(bottom - top, max(px(590), dialog.winfo_reqheight()))) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.deiconify()
        dialog.update_idletasks()
        if self.native:
            theme = self.theme
            self.native.style_dialog(dialog, palette=(theme.edge, theme.panel, theme.text))
        dialog.lift()
        dialog.focus_force()
        guide._schedule_targets()

    def open_feedback(self):
        parent = self.settings if self.settings_open() else self.current.window
        open_feedback(parent, self.language, self.theme, self.theme_font(), self.native)

    def pick_client_log(self):
        path = filedialog.askopenfilename(parent=self.settings, title=ui_text("PoE2-Spiel-Log auswählen", self.language),
                                          filetypes=[(ui_text("PoE2-Log", self.language), "Client.txt"), (ui_text("Textdateien", self.language), "*.txt")])
        if path:
            server.set_location_config({"enabled": True, "client_log_path": path})
            self.settings.destroy()
            self.current.flash(ui_text("Spiel-Log gespeichert.", self.language))

    def set_language(self, language):
        if language in LANGUAGES and language != self.language:
            self.save_preferences(language=language)
            self.language = language
            guide = self.current
            selected = guide.lookup_entry
            guide.lookup_entry = None
            if selected and selected.category in ("faq", "constructs"):
                guide.lookup_entry = next((entry for entry in editorial_entries(language)
                                           if entry.category == selected.category
                                           and entry.target["id"] == selected.target["id"]), None)
            elif selected and selected.category == "tips" and selected.url:
                guide.lookup_entry = next((entry for entry in editorial_entries(language)
                                           if entry.category == "tips" and entry.target == selected.target), None)
            elif selected and selected.category == "lexicon" and selected.target["group"] == "terms":
                ident = selected.target["row"]["id"]
                if ident in league_guides():
                    term = self.website_lexicon().get(ident)
                    if term:
                        guide.lookup_entry = next(published_terms(language, {ident: term}), None)
            guide._draw_header()
            guide._style_nav_icons()
            guide.update(self.state)
            self._refresh_speedrun_hud()

    def set_timer(self, enabled):
        self.save_preferences(timer=enabled)
        self.timer_visible = enabled
        if not enabled:
            self.speedrun_details_open = False
        if self.settings_open():
            self.settings.timer_visible.set(enabled)
        self.current.update(self.state)
        self._refresh_speedrun_hud()

    def toggle_speedrun_details(self):
        self.set_speedrun_details(not self.speedrun_details_open)

    def set_speedrun_details(self, enabled):
        self.speedrun_details_open = enabled and self.timer_visible and self.allows("timers")
        self._refresh_speedrun_hud()

    def _refresh_speedrun_hud(self):
        visible = (self.visible and self.speedrun_details_open and self.timer_visible and self.allows("timers")
                   and not self.current.content_hidden and self.welcome is None)
        if not visible:
            if self.speedrun_hud is not None:
                self.speedrun_hud.hide()
            return
        if self.speedrun_hud is None:
            self.speedrun_hud = SpeedrunHUD(self)
        self.speedrun_hud.refresh(server.speedrun_snapshot(self.state))
        self.speedrun_hud.show()

    def set_level_visible(self, enabled):
        self.save_preferences(level_visible=enabled)
        self.current.update(self.state)

    def set_manual_level(self, level):
        server.set_manual_character_level(level)
        self.sync_state()

    def set_auto_boss(self, enabled):
        self.save_preferences(auto_boss=enabled)
        self.auto_boss = enabled

    def set_hud_visibility(self, key, *, names=(), visible):
        if not names:
            self.save_preferences(**{key: visible})
        else:
            hidden = set(self.prefs.get(key, ()))
            if visible:
                hidden.difference_update(names)
            else:
                hidden.update(names)
            self.save_preferences(**{key: sorted(hidden)})
        guide = self.current
        tabs = [name for name, _ in guide._nav_buttons() if name in guide.tabs]
        if tabs and guide.guide_section in guide.tabs and guide.guide_section not in tabs:
            guide.guide_section = tabs[0]
        if guide.content_hidden and guide.eye_button not in guide._visible_quick_buttons():
            guide.toggle_content()
        guide._layout_controls()
        guide._style_tabs()
        guide._draw_header()
        guide.refresh_guide()

    def save_preferences(self, **changes):
        prefs = self.prefs | changes
        temporary = self.prefs_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(prefs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.prefs_path)
        self.prefs = prefs

    def flush_appearance(self):
        self.appearance_save = None
        self.save_preferences()

    def reset_options(self):
        self.settings.destroy()
        self.set_theme(DEFAULT_THEME)
        background, accents, intensity = THEME_APPEARANCE[DEFAULT_THEME]
        self.keys = {action: default for action, (_, default) in HUD_HOTKEYS.items()}
        self.prefs.pop(HUD_HEIGHT_LIMIT, None)
        self.prefs.pop("endgame_height_limit", None)
        self.prefs.pop("background_blur", None)
        self.prefs.pop("menu_background", None)
        self.save_preferences(hotkeys=self.keys, language="hybrid", hidden_sections=[], checklist_enabled=True,
                              auto_boss=True, timer=False, level_visible=True, transparency=0,
                              card_background=background, card_accents=accents, color_intensity=intensity,
                              checklist_fold_completed=True, checklist_hide_completed=False,
                              hidden_hud_tabs=[], hidden_hud_quick=[], hud_quick_visible=True)
        self.language, self.checklist_enabled, self.auto_boss, self.timer_visible = "hybrid", True, True, False
        self.speedrun_details_open = False
        if self.native:
            self.native.configure_hotkeys(self._active_bindings(timer_bindings(self.keys)))
        guide, layout = self.current, self.current.layout
        layout.scale = 100
        layout._resize_fonts()
        layout.place(layout.x, layout.y, layout.px(HUD_SIZE[0]), layout.px(HUD_SIZE[1]))
        guide.apply_theme()
        guide._schedule_targets()
        if self.native:
            self.native.set_opacity(guide.window, 255)
        else:
            guide.window.attributes("-alpha", 1)
        layout.save()
        self.set_mode(default_guide_mode(self.experience_level))
        self.open_settings()

    def save_hotkeys(self, fields):
        keys = {action: entry.get().strip() for action, entry in fields.items()}
        try:
            bindings = timer_bindings(keys, lambda text: ui_text(text, self.language))
            self.save_preferences(hotkeys=keys)
        except (OSError, ValueError) as error:
            messagebox.showerror(ui_text("Hotkeys", self.language), str(error), parent=self.settings)
            return
        self.keys = keys
        if self.native:
            self.native.configure_hotkeys(self._active_bindings(bindings))
        self.current.refresh_guide()
        self.current.flash(ui_text("Hotkeys gespeichert", self.language))

    def control_timer(self, action):
        clock = server.run_timer(action)
        if not self.timer_visible:
            self.set_timer(True)
        self.sync_state()
        if action == "reset":
            labels = ("Timer zurückgesetzt", "Timer reset")
        elif action == "finish":
            labels = ("Lauf beendet", "Run finished")
        elif clock["status"] == "live":
            labels = ("Timer läuft", "Timer running")
        else:
            labels = ("Timer pausiert", "Timer paused")
        self.current.flash(labels[self.language == "en"])

    def control_boss_timer(self):
        if self.boss_started is None:
            self.boss_started = time.monotonic()
            self.boss_seconds = 0
            self.current.flash("Boss-Zeit läuft")
        else:
            self.boss_seconds = time.monotonic() - self.boss_started
            self.boss_started = None
            self.current.flash(f"Boss-Zeit {format_time(self.boss_seconds)}")
        self.current.update(self.state)

    def close(self):
        if self.closed:
            return
        if self.build_import_interface is not None and self.build_import_interface.window.winfo_exists():
            self.build_import_interface.close()
            if self.build_import_interface.window.winfo_exists():
                return
        self.closed = True
        self.term_tips.stop()
        if self.speedrun_hud is not None:
            self.speedrun_hud.close()
        if self.welcome is not None:
            self.welcome.destroy()
        if self.appearance_save:
            self.root.after_cancel(self.appearance_save)
            self.flush_appearance()
        for job in (self.hotkey_job, self.update_job):
            if job:
                self.root.after_cancel(job)
        self.current.close()
        self.root.destroy()

    def finish_startup(self):
        if self.closed:
            return
        if not self.visible:
            self.toggle_visibility()
        if IS_WINDOWS:
            self._open_taskbar_window()
        if self.website_enabled:
            self.website.refresh_in_background()
        self.term_tips.start()

    def run(self):
        if self.show_welcome_on_start:
            self.root.after_idle(lambda: self.open_welcome(on_done=self.finish_startup))
        else:
            self.root.after_idle(self.finish_startup)
        self.root.mainloop()


def _rotate_log(path, limit=ERROR_LOG_LIMIT):
    """Keep one previous log as <name>.alt.txt once the log exceeds the limit."""
    try:
        if path.stat().st_size > limit:
            os.replace(path, path.with_name(f"{path.stem}.alt{path.suffix}"))
    except OSError:
        # Missing log, or the previous guide still holds it open: keep appending.
        pass


def main():
    log = ERROR_LOG
    native = None
    http = None
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        set_app_id()
        _rotate_log(log)
        logging.basicConfig(filename=log, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
        native = create_native_overlay()
        if native and not native.claim():
            return 0
        http = server.start_local_server(DATA_DIR, port=server.PORT, allow_alternate_port=True)
        overlay = StandaloneOverlay(http, DATA_DIR, native)
        logging.info("PoE2 Ingame Guide %s gestartet.", BUILD_LABEL)
        overlay.run()
        return 0
    except Exception as error:
        logging.exception("PoE2 Ingame Guide konnte nicht starten.")
        messagebox.showerror(f"{TITLE} · {BUILD_LABEL}", f"{error}\n\nDiagnose: {log}")
        return 1
    finally:
        if http:
            http.stop()
        if native:
            native.close()


if __name__ == "__main__":
    raise SystemExit(main())
