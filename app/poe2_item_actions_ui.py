"""Shared clipboard and Trade controls for item cards."""

import tkinter as tk
from tkinter import ttk
import webbrowser

from poe2_build_art import build_icon
from poe2_build_items import _display_line, rarity_color
from poe2_item_actions import (item_clipboard_text, minimum_roll, trade_item, trade_league_name,
                               trade_leagues, trade_url)
from poe2_overlay_controls import AutoHideScrollbar, BrassSlider, FlowRow


def render_item_actions(parent, gear, theme, language, px, app=None, *, card=None):
    def text(de, en):
        return en if language == "en" else de

    clipboard_text = item_clipboard_text(gear)
    listing = trade_item(gear)
    if not clipboard_text and listing is None:
        return None

    actions = FlowRow(parent, bg=theme.control, gap=px(4))
    field = getattr(theme, "field_color", theme.control)
    active = getattr(theme, "active", theme.control)

    def button(label, command):
        return tk.Button(actions, text=label, command=command, bg=field, fg=theme.text, bd=0, pady=px(3),
                         activebackground=active, activeforeground=theme.text, relief="flat",
                         highlightthickness=1, highlightbackground=theme.control, highlightcolor=theme.accent,
                         cursor="hand2", padx=px(8))

    if clipboard_text:
        copy_label = text("Item kopieren", "Copy item")
        notice = None

        def reset_caption():
            nonlocal notice
            notice = None
            copied.config(text=copy_label)
            actions.reflow()

        def copy():
            nonlocal notice
            try:
                actions.clipboard_clear()
                actions.clipboard_append(clipboard_text)
            except tk.TclError:
                copied.config(text=text("Kopieren fehlgeschlagen", "Copy failed"))
            else:
                copied.config(text=text("Für PoB kopiert", "Copied for PoB"))
            actions.reflow()
            if notice:
                copied.after_cancel(notice)
            notice = copied.after(1400, reset_caption)

        copied = button(copy_label, copy)
        copied.bind("<Destroy>", lambda _: copied.after_cancel(notice) if notice else None)
    if listing:
        def open_dialog():
            guide = getattr(app, "current", None)
            if getattr(guide, "window", None) is not parent.winfo_toplevel():
                guide = None
            existing = guide.lookup_dialog if guide else getattr(actions, "trade_dialog", None)
            if existing and existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
            actions.trade_dialog = TradeDialog(parent, listing, theme, language, px, app, card, guide=guide).window

        button(text("Handel …", "Trade …"), open_dialog)
    actions.reflow()
    return actions


class TradeDialog:
    def __init__(self, parent, listing, theme, language, px, app, card, *, guide=None):
        self.listing = listing
        self.theme = theme
        self.language = language
        self.px = px
        self.app = app
        self.field = getattr(theme, "field_color", theme.control)
        self.active = getattr(theme, "active", theme.control)
        self.edge = getattr(theme, "edge", self.field)
        self.panel = getattr(theme, "panel", theme.control)
        self.family = getattr(app, "ui_family", "Segoe UI")
        self.rolls = 80
        self.filter_rows = []
        self.previous_league = trade_league_name(getattr(app, "prefs", {}).get("item_trade_league"))
        self.league_job = None

        owner = parent.winfo_toplevel()
        window = self.window = tk.Toplevel(parent)
        window.withdraw()
        window.title(self.text("Ähnliches Item finden", "Find a similar item"))
        # A transient with a hidden owner stays hidden, also during isolated UI tests.
        if owner.winfo_viewable():
            window.transient(owner)
        if guide:
            window.attributes("-topmost", True)
        window.bind("<Escape>", lambda _: window.destroy())
        window.configure(bg=self.panel)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)
        self._styles()
        self._item_header(card)
        self._scope()
        self._filters()
        self._footer()
        self._refresh_filters()
        self._show(owner)
        if guide:
            guide.track_lookup_dialog(window)
            self.league_field.focus_force()
        else:
            self.league_field.focus_set()
        self.league_field.selection_range(0, tk.END)

    def text(self, de, en):
        return en if self.language == "en" else de

    def _styles(self):
        theme, px = self.theme, self.px
        style = ttk.Style(self.window)
        bevel = dict(bordercolor=self.edge, lightcolor=self.field, darkcolor=self.field)
        field = "Trade.TCombobox"
        style.configure(field, fieldbackground=self.field, background=self.field, foreground=theme.text,
                        arrowcolor=theme.accent, insertcolor=theme.text, selectbackground=self.active,
                        selectforeground=theme.text, padding=(px(8), px(5)), **bevel)
        style.map(field, fieldbackground=[("focus", self.field)], bordercolor=[("focus", theme.accent)])
        chip = "Trade.TRadiobutton"
        style.layout(chip, [("Button.border", {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.focus", {"sticky": "nswe", "children": [("Button.label", {"sticky": "nswe"})]})
            ]})
        ]})])
        style.configure(chip, background=self.field, foreground=theme.text, padding=(px(9), px(5)),
                        anchor="center", focuscolor=theme.accent, focusthickness=1, **bevel)
        style.map(chip, background=[("selected", self.active), ("active", self.active)],
                  foreground=[("selected", theme.accent)], bordercolor=[("selected", theme.accent)])

        action = "Trade.TButton"
        emphasis = getattr(theme, "selection_color", theme.accent)
        action_text = getattr(theme, "selection_text", "#141210")
        style.configure(action, background=emphasis, foreground=action_text,
                        bordercolor=emphasis, lightcolor=emphasis, darkcolor=emphasis,
                        focuscolor=action_text, focusthickness=1, padding=(px(13), px(7)),
                        font=(self.family, 10, "bold"))
        style.map(action, background=[("pressed", theme.accent), ("active", theme.accent)],
                  foreground=[("!disabled", action_text)])

        style.configure("Trade.Vertical.TScrollbar", troughcolor=self.panel, background=self.field,
                        arrowcolor=theme.accent, gripcount=0, **bevel)

    def _label(self, parent, text="", *, color=None, points=10, bold=False):
        return tk.Label(parent, text=text, anchor="w", justify="left", bg=parent.cget("bg"),
                        fg=color or self.theme.text, bd=0, padx=0, pady=0,
                        font=(self.family, points, "bold" if bold else "normal"))

    def _item_header(self, card):
        px, theme = self.px, self.theme
        hero = tk.Frame(self.window, bg=theme.control, highlightbackground=self.edge,
                        highlightthickness=px(1), padx=px(12), pady=px(10))
        hero.grid(row=0, column=0, sticky="ew", padx=px(16), pady=(px(14), px(10)))
        tk.Frame(hero, bg=theme.accent, width=px(2)).pack(side="left", fill="y", padx=(0, px(10)))
        image = build_icon(hero, card.icon, px(44)) if card and card.icon else None
        if image:
            picture = tk.Label(hero, bg=theme.control, image=image, bd=0)
            picture.image = image
            picture.pack(side="left", padx=(0, px(10)))
        title = card.title if card and card.title else self.listing.title
        base = card.base if card else self.listing.base
        rarity = card.rarity_label if card else ""
        labels = tk.Frame(hero, bg=theme.control)
        labels.pack(side="left", fill="x", expand=True)
        heading = self._label(labels, title, color=rarity_color(card.rarity) if card else theme.accent,
                              points=15, bold=True)
        heading.pack(fill="x")
        subtitle = " · ".join(part for part in (base if base != title else "", rarity) if part)
        if subtitle:
            self._label(labels, subtitle, points=9).pack(fill="x", pady=(px(2), 0))
        labels.bind("<Configure>", lambda event: heading.configure(wraplength=max(1, event.width)))

    def _scope(self):
        px, listing = self.px, self.listing
        available, pending = trade_leagues.snapshot(refresh=True)
        default = "Standard" if "Standard" in available else available[0]
        self.league = tk.StringVar(self.window, trade_league_name(listing.league) or self.previous_league or default)
        self.exact = tk.BooleanVar(self.window, True)
        scope = tk.Frame(self.window, bg=self.panel)
        scope.grid(row=1, column=0, sticky="ew", padx=px(16), pady=(0, px(12)))
        scope.columnconfigure(0, weight=1)
        self._label(scope, self.text("Liga", "League"), bold=True).grid(row=0, column=0, sticky="w")
        self.league_field = ttk.Combobox(scope, textvariable=self.league, values=self._league_choices(available), width=17,
                                         style="Trade.TCombobox")
        dropdown = scope.tk.call("ttk::combobox::PopdownWindow", self.league_field)
        scope.tk.call(dropdown + ".f.l", "configure", "-background", self.field, "-foreground", self.theme.text,
                      "-selectbackground", self.active, "-selectforeground", self.theme.text,
                      "-highlightthickness", 0, "-borderwidth", 0)
        self.league_field.grid(row=1, column=0, sticky="ew", pady=(px(4), 0))
        self.league_field.bind("<Return>", lambda _: self._open_trade())
        if pending:
            self.league_job = self.window.after(150, self._update_league_choices)
            self.window.bind("<Destroy>", self._stop_league_update, add="+")
        if listing.category and not listing.unique:
            search = tk.Frame(scope, bg=self.panel)
            search.grid(row=0, column=1, rowspan=2, sticky="nsw", padx=(px(14), 0))
            self._label(search, self.text("Suchbereich", "Match"), bold=True).pack(anchor="w")
            options = tk.Frame(search, bg=self.panel)
            options.pack(fill="x", pady=(px(4), 0))
            for exact, name in ((True, self.text("Gleiche Basis", "Same base")),
                                (False, self.text("Gleiche Klasse", "Same class"))):
                ttk.Radiobutton(options, text=name, variable=self.exact, value=exact,
                                style="Trade.TRadiobutton").pack(side="left", padx=(0, px(3)))

    def _league_choices(self, available):
        saved = (self.listing.league, self.previous_league, self.league.get())
        names = [name for value in saved if (name := trade_league_name(value))]
        return tuple(dict.fromkeys((*available, *names)))

    def _update_league_choices(self):
        available, pending = trade_leagues.snapshot()
        self.league_job = self.window.after(150, self._update_league_choices) if pending else None
        if not pending:
            self.league_field.configure(values=self._league_choices(available))

    def _stop_league_update(self, event):
        if event.widget is self.window and self.league_job is not None:
            self.window.after_cancel(self.league_job)
            self.league_job = None

    def _filters(self):
        theme, px = self.theme, self.px
        block = tk.Frame(self.window, bg=self.panel)
        block.grid(row=2, column=0, sticky="nsew", padx=px(16), pady=(0, px(12)))
        block.columnconfigure(0, weight=1)
        block.rowconfigure(1, weight=1)
        heading = tk.Frame(block, bg=self.panel)
        heading.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(5)))
        self._label(heading, self.text("Suchfilter", "Filters"), bold=True).pack(side="left")
        self.count = self._label(heading, color=theme.accent, points=9)
        self.count.pack(side="right")
        canvas = self.canvas = tk.Canvas(block, bg=self.panel, width=1, height=1, bd=0,
                                         highlightthickness=0, yscrollincrement=px(22))
        canvas.grid(row=1, column=0, sticky="nsew")
        scroll = AutoHideScrollbar(block, orient="vertical", command=canvas.yview,
                                   style="Trade.Vertical.TScrollbar")
        scroll.grid(row=1, column=1, sticky="ns", padx=(px(4), 0))
        canvas.configure(yscrollcommand=scroll.set)
        options = self.options = tk.Frame(canvas, bg=self.panel)
        self.contents = canvas.create_window(0, 0, window=options, anchor="nw")
        options.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: self._resize_filters(event.width))
        self.window.bind("<MouseWheel>", lambda e: self._scroll(e, -1 if e.delta > 0 else 1))
        self.window.bind("<Button-4>", lambda e: self._scroll(e, -1))
        self.window.bind("<Button-5>", lambda e: self._scroll(e, 1))

        properties = [row for row in self.listing.filters if row.group == "equipment"]
        totals = [row for row in self.listing.filters if row.id.startswith("pseudo.")]
        modifiers = [row for row in self.listing.filters if row.group != "equipment" and not row.id.startswith("pseudo.")]
        groups = [(title, rows) for title, rows in zip(
            (self.text("Eigenschaften", "Properties"), self.text("Gesamtwerte", "Totals"),
             self.text("Modifikatoren", "Modifiers")), (properties, totals, modifiers)) if rows]
        for title, rows in groups:
            if len(groups) > 1:
                self._label(options, title, color=theme.accent, points=9, bold=True).pack(fill="x", pady=(px(5), px(3)))
            for row in rows:
                self._filter_row(options, row)

        if not groups:
            self._label(options, self.text("Suche nach diesem Item ohne Modifikatorfilter.",
                                           "Search for this item without modifier filters."), points=9).pack(fill="x")
        if self.listing.unmatched:
            count = self.listing.unmatched
            self.unmatched = self._label(options, self.text(
                f"{count} Mod-Zeilen ohne eindeutigen Handelsfilter." if count != 1 else
                "Eine Mod-Zeile hat keinen eindeutigen Handelsfilter.",
                f"{count} modifier lines have no unambiguous trade filter." if count != 1 else
                "One modifier line has no unambiguous trade filter."), points=9)
            self.unmatched.pack(fill="x", pady=(px(5), 0))

    def _filter_row(self, parent, row):
        theme, px = self.theme, self.px
        variable = tk.BooleanVar(self.window, row.selected)
        tile = tk.Frame(parent, bg=theme.control, padx=px(4), pady=px(2))
        tile.pack(fill="x", pady=(0, px(3)))
        tile.columnconfigure(0, weight=1)
        text = row.text.removesuffix(" (augmented)") if row.group == "equipment" else row.text
        toggle = tk.Checkbutton(tile, text=_display_line(text, self.language), variable=variable,
                                command=self._refresh_filters, bg=theme.control, fg=theme.text,
                                font=(self.family, 10), activebackground=self.active, activeforeground=theme.text,
                                selectcolor=self.field, highlightthickness=1, highlightbackground=theme.control,
                                highlightcolor=theme.accent, bd=0, anchor="w", justify="left", pady=px(2),
                                padx=px(4), cursor="hand2")
        toggle.grid(row=0, column=0, sticky="ew")
        minimum = self._label(tile, color=theme.accent, points=9, bold=True)
        minimum.configure(anchor="e")
        minimum.grid(row=0, column=1, sticky="e", padx=(px(4), px(5)))
        self.filter_rows.append((row, variable, toggle, minimum))

    def _resize_filters(self, width):
        px = self.px
        self.canvas.itemconfigure(self.contents, width=width)
        for row, _, toggle, _ in self.filter_rows:
            toggle.configure(wraplength=max(px(60), width - px(84 if row.value else 42)))
        if hasattr(self, "unmatched"):
            self.unmatched.configure(wraplength=width)

    def _scroll(self, event, direction):
        if event.widget is self.league_field:
            return
        self.canvas.yview_scroll(direction, "units")
        return "break"

    def _footer(self):
        px, theme = self.px, self.theme
        footer = tk.Frame(self.window, bg=theme.control, highlightbackground=self.edge, highlightthickness=px(1),
                          padx=px(12), pady=px(8))
        footer.grid(row=3, column=0, sticky="ew", padx=px(16), pady=(0, px(14)))
        if any(row.value for row in self.listing.filters):
            summary = tk.Frame(footer, bg=theme.control)
            summary.pack(fill="x")
            self._label(summary, self.text("Mindestwerte", "Minimum rolls"), bold=True).pack(side="left")
            self.percentage = self._label(summary, color=theme.accent, bold=True)
            self.percentage.pack(side="right", padx=(px(8), 0))
            slider = BrassSlider(footer, 0, 100, self.rolls, self._set_rolls, px)
            slider.configure(bg=theme.control, highlightbackground=theme.control, highlightcolor=theme.accent)
            slider.colors = (self.edge, self.field, theme.accent, self.active, theme.accent, theme.text)
            slider.thumb = getattr(getattr(theme, "treatment", None), "slider_thumb", "diamond")
            slider.pack(fill="x", pady=(0, px(4)))
        self.status = self._label(footer, color=theme.accent, points=9)
        ttk.Button(footer, text=self.text("Im Handel suchen ↗", "Search on Trade ↗"),
                   style="Trade.TButton", command=self._open_trade).pack(anchor="e")

    def _set_rolls(self, value):
        self.rolls = value
        self._refresh_filters()

    def _refresh_filters(self):
        checked = self._selected_filters()
        if self.filter_rows:
            self.count.configure(text=self.text(f"{len(checked)} von {len(self.filter_rows)} aktiv",
                                                f"{len(checked)} of {len(self.filter_rows)} selected"))
        if hasattr(self, "percentage"):
            self.percentage.configure(text=self.text(f"{self.rolls} % der Itemwerte", f"{self.rolls}% of item values"))
        for row, _, _, label in self.filter_rows:
            value = minimum_roll(row.value, self.rolls) if row.id in checked and "|" not in row.id else None
            unit = "%" if row.value and row.value + "%" in row.text else ""
            label.configure(text=f"≥ {value:g}{unit}" if value is not None else "")

    def _selected_filters(self):
        return {row.id for row, variable, _, _ in self.filter_rows if variable.get()}

    def _show(self, owner):
        window, px = self.window, self.px
        native = getattr(self.app, "native", None)
        x, y = owner.winfo_rootx(), owner.winfo_rooty()
        w, h = owner.winfo_width(), owner.winfo_height()
        workarea = native.work_area(rect=(x, y, x + w, y + h)) if native else None
        left, top, right, bottom = workarea or (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
        width = min(px(536), max(1, right - left - px(20)))
        content_width = max(1, width - px(36))
        # Determine the requested height with wrapped rows, before mapping the window.
        self._resize_filters(content_width)
        window.update_idletasks()
        self.canvas.configure(height=min(px(265), self.options.winfo_reqheight()))
        window.update_idletasks()
        height = min(window.winfo_reqheight(), max(1, bottom - top - px(52)))
        x = min(max(left, x + (w - width) // 2), max(left, right - width - px(8)))
        y = min(max(top, y + (h - height) // 2), max(top, bottom - height - px(40)))
        window.geometry(f"{width}x{height}{x:+d}{y:+d}")
        window.minsize(min(px(405), width), min(px(305), height))
        window.deiconify()
        if native:
            window.update_idletasks()
            native.style_dialog(window, palette=(self.edge, self.panel, self.theme.text))

    def _open_trade(self):
        try:
            uri = trade_url(self.listing, self.league.get(), self._selected_filters(), self.rolls,
                            exact_base=self.exact.get())
        except ValueError:
            self._show_status(self.text("Gib den Namen deiner Liga ein.", "Enter the name of your league."))
            self.league_field.focus_set()
            return
        try:
            opened = webbrowser.open(uri)
        except webbrowser.Error:
            opened = False
        if not opened:
            self._show_status(self.text("Der Browser konnte nicht geöffnet werden.", "Could not open the browser."))
            return
        self.status.pack_forget()
        if hasattr(self.app, "save_preferences") and self.previous_league != self.league.get().strip():
            try:
                self.app.save_preferences(item_trade_league=self.league.get().strip())
            except OSError:
                self._show_status(self.text("Die Liga konnte nicht gespeichert werden.", "Could not save the league."))
            else:
                self.previous_league = self.league.get().strip()

    def _show_status(self, text):
        self.status.configure(text=text, wraplength=max(1, self.window.winfo_width() - self.px(55)))
        self.status.pack(fill="x", side="top", pady=(self.px(4), 0))
