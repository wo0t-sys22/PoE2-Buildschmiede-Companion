"""Responsive native cards for the gear and gems of a published build stage."""

import tkinter as tk
from urllib.parse import urlsplit
import webbrowser

from poe2_build_art import build_icon, gem_icon, item_art_ref
from poe2_build_items import item_card, item_rarity, rarity_color, render_item_card
from poe2_build_loadout import slot_label
from poe2_language import display_label
from poe2_lexicon import GERMAN_ITEM_TYPES
from poe2_overlay_controls import FlowRow
from poe2_website_content import localized_text


SKILL_COLOR = "#7ad8c7"
SUPPORT_COLOR = "#c5d9c9"


def _wrapping(widget, window, inset):
    def fit(event):
        length = max(20, event.width - window.layout.px(inset))
        if widget.winfo_pixels(widget.cget("wraplength")) != length:
            widget.configure(wraplength=length)

    widget.bind("<Configure>", fit, add="+")


def _message(window, parent, text, *, tone="text", points=10):
    if text:
        window.pack_message(parent, text, tone=tone, points=points, padding=2)


def _gem_information(asset, language):
    record = asset.record or {}
    tags = (record.get("tagsDe") if language == "de" else None) or record.get("tags")
    weapon = record.get("weapon") or ""
    if weapon and language == "de":
        weapon = ", ".join(GERMAN_ITEM_TYPES.get(part.strip(), part.strip()) for part in weapon.split(","))
    lines = tuple(dict.fromkeys(filter(None, (asset.note, localized_text(record.get("description"), language), weapon))))
    return lines, tuple(tag.strip() for tag in (tags or "").split(",") if tag.strip())


def _gem_tooltip(window, widget, gem):
    summary = localized_text((gem.record or {}).get("description"), window.app.language) or gem.note
    if summary:
        target = ("gem", gem.id) if gem.record else None
        entry = (gem.name, summary, target) if target else (gem.name, summary)
        widget.detail_at_point = lambda x, y: (target or gem.name, entry)
        window.app.term_tips.register(widget)


def _gem_detail(window, parent, gem, lines, tags):
    px = window.layout.px
    bg = parent.guide_card_color
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x", pady=(px(3), px(2)))
    row.columnconfigure(1, weight=1)
    icon = tk.Label(row, bg=bg, bd=0)
    art = build_icon(icon, gem.icon, size=px(24))
    icon.image = art or gem_icon(icon, "", size=px(24))
    icon.configure(image=icon.image)
    icon.grid(row=0, column=0, sticky="nw", padx=(0, px(3)))
    _gem_tooltip(window, icon, gem)
    body = tk.Frame(row, bg=bg)
    body.guide_card_color = bg
    body.grid(row=0, column=1, sticky="ew")
    if art is None:
        _message(window, body, gem.name, tone="gold", points=9)
    for line in lines:
        _message(window, body, line)
    if tags:
        band = tk.Frame(body, bg=window.theme.field_color, highlightbackground=window.theme.edge,
                        highlightthickness=px(1))
        band.guide_card_color = window.theme.field_color
        band.pack(fill="x", pady=(px(2), 0))
        window.pack_message(band, "  ·  ".join(tags), body_color=window.theme.accent,
                            font=window.ui_font(9), points=9, padding=1)


def _gem_header(window, parent, group):
    language = window.app.language
    skill = group.skill
    entries = []
    for gem in (skill, *group.sockets):
        lines, tags = _gem_information(gem, language)
        if lines or tags:
            entries.append((gem, lines, tags))
    bg = parent.guide_card_color
    title = skill.name

    if entries:
        details = tk.Frame(parent, bg=bg)
        details.guide_card_color = bg

        def toggle():
            if details.winfo_manager():
                details.pack_forget()
                header.configure(text=f"▸ {title}")
            else:
                if not details.winfo_children():
                    for gem, lines, tags in entries:
                        _gem_detail(window, details, gem, lines, tags)
                details.pack(fill="x", pady=(window.layout.px(4), 0))
                header.configure(text=f"▾ {title}")
            window._refit_route()
            window._schedule_targets()

        header = window.small_button(parent, f"▸ {title}", toggle)
        header.configure(relief="flat", overrelief="flat", bd=0, highlightthickness=0, activebackground=bg,
                         activeforeground=SKILL_COLOR)
    else:
        header = tk.Label(parent, text=title)
    header.configure(anchor="w", justify="left", bg=bg, fg=SKILL_COLOR, font=window.ui_font(11, "bold"))
    image = gem_icon(header, skill.icon, size=window.layout.px(28))
    header.configure(image=image, compound="left", padx=window.layout.px(4))
    header.image = image
    header.pack(fill="x")
    _wrapping(header, window, 38)
    _gem_tooltip(window, header, skill)


def render_gems(window, parent, groups):
    theme = window.theme
    px = window.layout.px
    for group in groups:
        tile = tk.Frame(parent, bg=theme.control, padx=px(6), pady=px(4),
                        highlightbackground=theme.edge, highlightthickness=px(1))
        tile.guide_card_color = theme.control
        tile.pack(fill="x", pady=(0, px(4)))
        _gem_header(window, tile, group)
        if group.sockets:
            has_skill = any(gem.kind == "skill" for gem in group.sockets)
            labels = ("Eingesetzte Gemmen", "Socketed Gems", "Socketed gems") if has_skill else (
                "Unterstützungen", "Supports", "Supports")
            support_label = display_label(labels, window.app.language)
            _message(window, tile, support_label, tone="muted", points=9)
            supports = FlowRow(tile, bg=theme.control, gap=px(4))
            supports.pack(fill="x", pady=(px(4), 0))

            def fit_badges(event):
                wrap = max(px(24), min(px(245), event.width - px(34)))
                for badge in event.widget.winfo_children():
                    if badge.winfo_pixels(badge.cget("wraplength")) != wrap:
                        badge.configure(wraplength=wrap)

            supports.bind("<Configure>", fit_badges, add="+")
            for gem in group.sockets:
                skill = gem.kind == "skill"
                prefix = display_label(("Fertigkeit", "Skill", "Skill"), window.app.language) + " · " if skill else ""
                badge = tk.Label(supports, text=prefix + gem.name, bg=theme.field_color, fg=SKILL_COLOR if skill else SUPPORT_COLOR,
                                 font=window.ui_font(9), padx=px(4), anchor="w", justify="left", wraplength=px(245))
                image = gem_icon(badge, gem.icon, size=px(18))
                badge.configure(image=image, compound="left")
                badge.image = image
                _gem_tooltip(window, badge, gem)


def _item_caption(slot):
    return slot.item.name if slot.item else slot.goal or slot.base or slot.mod


def _gear_record(slot):
    if slot.imported_gear is not None:
        return slot.imported_gear
    gear = {"goal": slot.goal, "mod": slot.mod, "base": slot.base}
    if slot.item:
        gear["overlayRef"] = {"id": slot.item.id, "name": (slot.item.record or {}).get("name") or slot.item.name,
                              "note": slot.item.note}
    return gear


def render_items(window, parent, slots, selected, on_select):
    slots = tuple(slot for slot in slots if _item_caption(slot))
    if not slots:
        return
    theme = window.theme
    px = window.layout.px
    language = window.app.language
    grid = tk.Frame(parent, bg=parent.guide_card_color)
    grid.pack(fill="x", pady=(0, px(4)))
    grid.columnconfigure((0, 1), weight=1, uniform="equipment-slot")
    details = tk.Frame(grid, bg=parent.guide_card_color)
    details.guide_card_color = parent.guide_card_color
    buttons = {}
    slot_index = {slot.slot: slot for slot in slots}

    def show(key):
        nonlocal selected
        selected = key
        for button, color, _row in buttons.values():
            button.configure(bg=theme.control, fg=color)
        for child in details.winfo_children():
            child.destroy()
        if key in slot_index:
            button, _, row = buttons[key]
            button.configure(bg=theme.selection_color, fg=theme.selection_text)
            _render_item_details(window, details, slot_index[key], language)
            details.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, px(6)))
        else:
            details.grid_remove()

    def select(key):
        key = "" if key == selected else key
        on_select(key)
        show(key)
        window._refit_route()
        window._schedule_targets()

    for index, slot in enumerate(slots):
        caption = _item_caption(slot)
        if len(caption) > 64:
            caption = caption[:61].rstrip() + "…"
        text = "\n".join(filter(None, (slot_label(slot.slot, language), caption)))
        gear = _gear_record(slot)
        color = rarity_color(item_rarity(gear, slot.item.record if slot.item else None)) if slot.item else theme.text
        button = window.small_button(grid, text, lambda key=slot.slot: select(key))
        button.configure(fg=color, anchor="w", justify="left", padx=px(6), width=1, wraplength=px(110))
        ref = item_art_ref((slot.item.record or {}).get("name") or slot.item.name, slot.base) if slot.item else ""
        image = build_icon(button, ref or (slot.item.icon if slot.item else ""), size=px(30))
        if image:
            button.configure(image=image, compound="left")
            button.image = image
        row, column = divmod(index, 2)
        span = 2 if column == 0 and index == len(slots) - 1 else 1
        button.grid(row=2 * row, column=column, columnspan=span, sticky="nsew",
                    padx=(0, px(4)) if column == 0 and span == 1 else 0,
                    pady=(0, px(4)))
        _wrapping(button, window, 48 if image else 20)
        buttons[slot.slot] = button, color, 2 * row
    show(selected)


def _render_item_details(window, parent, slot, language):
    gear = _gear_record(slot)
    card = item_card(gear, language, show_targets=True)
    render_item_card(parent, card, window.theme, px=window.layout.px, font=window.ui_font,
                     gear=gear, language=language, app=window.app).pack(fill="x")


def render_tree_link(window, parent, url):
    try:
        target = urlsplit(url)
    except ValueError:
        return
    if target.scheme != "https" or target.hostname != "buildschmiede.de":
        return
    en = window.app.language == "en"
    label = "Open tree on the website" if en else "Baum auf der Website öffnen"
    window.small_button(parent, label, lambda: webbrowser.open(url)).pack(anchor="w", pady=(2, 4))
