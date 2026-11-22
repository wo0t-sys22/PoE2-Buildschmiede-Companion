"""In-game view for the R18 checklist."""

from poe2_r18_features import GUIDE, context_tips, localized
from poe2_language import checklist_text, boss_text, ui_text

def show_checklist(window, state, zone, clues, bosses, checks, integrated=None):
    panel = window.route_rows
    language = window.app.language
    english = language == "en"
    run = checks["character"] or ("Active run" if english else "Aktiver Run")
    if integrated is None:
        window.pack_message(panel, ("Checklist · " if english else "Checkliste · ") + run, tone="gold", points=11)
    curated = GUIDE.get("areaChecklists", {})
    entries = next((curated[c["id"]] for c in clues if c["id"] in curated), None)
    if entries is not None:
        tasks = [(row["id"], checklist_text(row["id"], language) or localized(row["title"])) for row in entries]
    else:
        tasks = [(tip["scope"] + ":" + tip["id"], localized(tip["title"], language))
                 for tip in context_tips(zone) if tip["scope"] != "tip"]
        tasks.extend(("route:" + clue["id"], clue["cue"]) for clue in clues
                     if clue.get("mandatory") or "permanent" in clue.get("kind", "").lower())
        tasks.extend(("boss:" + boss["id"], ("Defeat " + boss["name"] if english else boss_text(boss, language)["name"] + " besiegen")) for boss in bosses if boss.get("required"))
    if integrated is not None:
        tasks = [(key, label) for key, label in tasks if key not in integrated]
        if tasks:
            window.section_row("Checkliste", heading=True, tone="quest")
            for ident, label in tasks:
                window.section_row(label, task=ident, term_colors=window.route_term_colors(bosses))
        return
    if not tasks:
        window.pack_message(panel, ui_text("Für dieses Gebiet sind keine Aufgaben hinterlegt.", language), tone="muted", points=10)
    for ident, label in tasks:
        done = checks["checked"].get(ident, False)
        button = window.small_button(panel, "", lambda ident=ident, done=done: window.app.check_item(ident, not done))
        colors = window.route_term_colors(bosses)
        if ident in {"route:a1-red-vale-obelisks", "boss:rust-king"}:
            colors.update(dict.fromkeys(("Rune", "Runen", "runes"), GUIDE["palette"]["quest"]))
        colors["✓"] = GUIDE["palette"]["quest"]
        row = window.pack_message(button, ("✓  " if done else "□  ") + label, term_colors=colors)
        row.configure(bg=button.cget("background"), cursor="hand2")
        row.bind("<ButtonRelease-1>", lambda event, button=button: button.invoke()
                 if 0 <= event.x < event.widget.winfo_width() and 0 <= event.y < event.widget.winfo_height() else None)
        button.pack(fill="x", padx=4, pady=2)
