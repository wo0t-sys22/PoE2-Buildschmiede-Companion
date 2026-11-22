"""Gold costs and the inline calculator used by the HUD."""

import tkinter as tk

from poe2_overlay_controls import FlowRow
from poe2_r18_features import bundled, localized


RESPEC = bundled("poe2_respec.json")


def respec_cost(level, passive, ascendancy):
    per_passive = RESPEC["goldPerLevel"][level - 1]
    per_ascendancy = per_passive * RESPEC["ascendancyMultiplier"]
    return per_passive, per_ascendancy, passive * per_passive + ascendancy * per_ascendancy


def render_respec(window, parent, level):
    language = window.app.language
    english = language == "en"
    theme = window.theme
    px = window.layout.px
    bg = parent.cget("background")
    fields = RESPEC["fields"]
    overrides = window.app.respec_values
    values = {field["id"]: overrides.get(field["id"], level if field["id"] == "level" else field["default"])
              for field in fields}

    title = localized(RESPEC["title"], language)
    window.pack_message(parent, title, tone="gold")
    controls = FlowRow(parent, bg=bg, gap=px(6), distribute=True)
    controls.pack(fill="x", padx=px(4), pady=(0, px(4)))

    total_text = tk.StringVar(parent)
    rate_text = tk.StringVar(parent)

    def refresh():
        passive, ascendancy, total = (f"{amount:,}" for amount in respec_cost(**values))
        if not english:
            passive, ascendancy, total = (amount.replace(",", ".") for amount in (passive, ascendancy, total))
        total_text.set(f"{'Total' if english else 'Gesamt'} · {total} Gold")
        rate_text.set(f"{passive} / {ascendancy} Gold" +
                      (" per passive / ascendancy point" if english else " pro Passiv- / Aszendenzpunkt"))

    for field in fields:
        key, low, high = field["id"], field["min"], field["max"]
        caption = localized(field["label"], language)
        cell = tk.Frame(controls, bg=bg)
        tk.Label(cell, text=caption, bg=bg, fg=theme.text, font=window.ui_font(9),
                 anchor="w", padx=0).pack(fill="x")
        row = tk.Frame(cell, bg=bg)
        row.pack(fill="x")
        number = tk.StringVar(cell, str(values[key]))

        def set_value(value, key=key, low=low, high=high, number=number):
            value = max(low, min(high, int(value)))
            values[key] = overrides[key] = value
            number.set(str(value))
            refresh()

        def edit(key=key, low=low, high=high, caption=caption, set_value=set_value, cell=cell):
            def valid(value):
                return value.isascii() and value.isdecimal() and len(value) <= len(str(high)) and low <= int(value) <= high

            def apply(value):
                set_value(value)
                if not cell.winfo_exists():
                    window.refresh_guide()

            window._open_input_dialog(f"{caption} ({low}–{high})", str(values[key]), apply,
                                      "Apply" if english else "Übernehmen", validate=valid, width=18)

        window.small_button(row, "−", lambda key=key, change=set_value: change(values[key] - 1)).pack(side="left")
        window.small_button(row, "+", lambda key=key, change=set_value: change(values[key] + 1)).pack(side="right")
        button = window.small_button(row, "", edit)
        button.configure(textvariable=number, width=3)
        button.pack(side="left", fill="x", expand=True)

    tk.Label(parent, textvariable=total_text, bg=bg, fg=theme.accent, font=window.title_font(12, "bold"),
             anchor="w", padx=px(4)).pack(fill="x")
    rates = tk.Label(parent, textvariable=rate_text, bg=bg, fg=theme.text, font=window.ui_font(9),
                     justify="left", anchor="w", padx=px(4))
    rates.bind("<Configure>", lambda event: rates.configure(wraplength=max(1, event.width - px(8))))
    rates.pack(fill="x")
    refresh()
