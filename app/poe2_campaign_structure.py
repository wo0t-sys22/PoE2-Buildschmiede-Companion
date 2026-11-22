"""Structural edits for the two variants of an area guide."""

from uuid import uuid4

from poe2_language import LANGUAGES
from poe2_r18_features import bundled, hud_check_id, text_term_refs


HEADING_TONES = bundled("companion-section-style.json")["headingTones"]
MODES = ("basis", "veteran")


def structured_layout(record, area):
    if "sections" in record:
        for section_index, section in enumerate(record["sections"]):
            for mode in MODES:
                source = (enumerate(section["lines"]) if mode == "basis" else
                          ((i, row) for i, row in enumerate(record["steps"]) if row["section"] == section["heading"]))
                untracked = 0
                for i, row in source:
                    if row.get("kind") == "paragraph" or row.get("checkId"):
                        continue
                    path = f"sections.{section_index}.lines.{i}" if mode == "basis" else f"steps.{i}"
                    row.setdefault("id", path)
                    row["checkId"] = hud_check_id("area", area, section["heading"], untracked)
                    untracked += 1
        return record
    if "landmarks" not in record:
        raise ValueError("Dieses Gebiet hat kein strukturiertes Layout.")

    layout = {"sections": [], "steps": []}
    for heading, group in (("Layout", "landmarks"), ("Optionale Ziele", "optionalStops")):
        section = {"heading": heading, "tone": HEADING_TONES[heading], "lines": []}
        layout["sections"].append(section)
        if group == "landmarks":
            section["image"] = record["image"]
            section["lines"].append({**record["text"], "checkId": "route:" + area})
            layout["steps"].append({**record["compact"], "checkId": "route:" + area, "section": heading})
        for i, stop in enumerate(record[group]):
            key = stop.get("checkId") or hud_check_id(
                "landmark" if group == "landmarks" else "landmark-optional", area, i)
            for field, target in (("body", section["lines"]), ("compact", layout["steps"])):
                row = dict(stop[field])
                if not stop.get("checkId"):
                    row["id"] = f"{group}.{i}.{field}"
                row["checkId"] = key
                if field == "compact":
                    row["section"] = heading
                target.append(row)
    return layout


def change_layout(record, area, payload):
    action, mode, heading = (payload.get(key) for key in ("action", "mode", "heading"))
    if (action not in ("addSection", "addRow", "removeSection", "removeRow") or mode not in MODES
            or not isinstance(heading, str) or heading not in HEADING_TONES):
        raise ValueError("Ungültige Layout-Änderung.")
    layout = structured_layout(record, area)
    sections = layout["sections"]
    section = next((row for row in sections if row["heading"] == heading), None)

    def rows_for(variant):
        if section is None:
            return []
        return section["lines"] if variant == "basis" else [
            row for row in layout["steps"] if row["section"] == heading]

    def visible_in(variant):
        return bool(section and (layout.get("template") or rows_for(variant)
                                or (variant == "basis" and section.get("image"))))

    if action.startswith("add"):
        if visible_in(mode) != (action == "addRow"):
            raise ValueError("Der Abschnitt passt nicht zur gewählten Ansicht. Lade die Seite neu.")
        variants = payload.get("variants")
        if not isinstance(variants, dict) or mode not in variants or not variants.keys() <= set(MODES):
            raise ValueError("Ungültige Ansichtsvarianten.")
        kind = payload.get("kind")
        if kind not in ("checklist", "paragraph"):
            raise ValueError("Ungültiger Eintragstyp.")
        if section is None:
            section = {"heading": heading, "tone": HEADING_TONES[heading], "lines": []}
            sections.append(section)
        identity = uuid4().hex
        for variant in variants:
            values = variants[variant]
            if not isinstance(values, dict) or values.keys() != LANGUAGES.keys() or any(
                not isinstance(value, str) or not 0 < len(value.strip()) <= 4000 for value in values.values()
            ):
                raise ValueError("Gib in jeder Sprache einen Text mit 1 bis 4000 Zeichen ein.")
            row = {lang: value.strip() for lang, value in values.items()}
            row["termRefs"] = {lang: text_term_refs(row[lang], lang, area) for lang in LANGUAGES}
            if kind == "checklist":
                row["checkId"] = "run:editor-" + identity
            else:
                row.update(id="editor-" + identity, kind="paragraph")
            if variant == "basis":
                section["lines"].append(row)
            else:
                layout["steps"].append({**row, "section": heading})
            removed = layout.get("removedHeadings", {}).get(variant, [])
            if heading in removed:
                removed.remove(heading)
    else:
        if not visible_in(mode):
            raise ValueError("Dieser Abschnitt ist in der gewählten Ansicht nicht vorhanden.")
        rows = rows_for(mode)
        if action == "removeRow":
            index = payload.get("index")
            if type(index) is not int or not 0 <= index < len(rows):
                raise ValueError("Ungültige Textposition.")
            rows = [rows[index]]
        removed_rows = {id(row) for row in rows}
        target, key = (section, "lines") if mode == "basis" else (layout, "steps")
        target[key] = [row for row in target[key] if id(row) not in removed_rows]
        for row in rows:
            if key := row.get("checkId"):
                removed = layout.setdefault("removedChecks", {}).setdefault(mode, [])
                if key not in removed:
                    removed.append(key)
        if action == "removeSection":
            if mode == "basis":
                section.pop("image", None)
            if heading == "Tipps":
                layout.setdefault("removedHeadings", {}).setdefault(mode, []).append(heading)
        if not any(visible_in(variant) for variant in MODES):
            sections.remove(section)
    layout["structureVersion"] = uuid4().hex
    return layout
