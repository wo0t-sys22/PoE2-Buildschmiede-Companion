"""Apply German labels without changing game IDs or the English import vocabulary."""

import gzip
import json
from pathlib import Path
import re


TIER = re.compile(r" (?:I|II|III|IV|V)$")
_DIGITS = r"\d+(?:[.,]\d+)?"
_ROLL = rf"(?:\([+-]?{_DIGITS}\s*[-–—]\s*[+-]?{_DIGITS}\)|{_DIGITS})"
ROLLS = (re.compile(_ROLL), re.compile(rf"[+-]?{_ROLL}"))
# These records appeared as links in the site's support list without gem details.
# Keys are the PoE2DB page slugs (https://poe2db.tw/de/<slug>).
UNUSED = {"de": "PoE2DB führt diese Unterstützung als unbenutzten Spieldatensatz. Eine spielbare Wirkung ist dort nicht bestätigt.",
          "en": "PoE2DB marks this support as unused. Its effect in play is unconfirmed."}
SUPPORT_NOTES = {
    "Overabundance_III": {
        "de": "Verdoppelt das Maximum einer unterstützten Fertigkeit. Bei jeder Nutzung triffst du dich selbst mit einem zufälligen Fluch. Dauerhafte Fertigkeiten sind ausgenommen.",
        "en": "Doubles a supported skill’s limit. Each use curses you at random. Persistent skills are ineligible."},
    "Empowered_Sparks_II": {
        "de": "Erzeugst du mit der unterstützten Fertigkeit eine Energie-Ladung, lösen deine nächsten drei Angriffe Funkenprojektile aus.",
        "en": "When the supported skill generates a Power Charge, your next three attacks release Spark projectiles."},
    "Ricochet_III": {
        "de": "Deine Projektile durchbohren alle Ziele. Zusätzliche Projektile erhöhen stattdessen die Zahl der Verkettungen beim Abprallen von Gelände.",
        "en": "Your projectiles pierce every target. Additional projectiles instead grant extra chains from terrain."},
    "Atziris_Call": UNUSED,
    "Dreamers_Knell": UNUSED,
}


def translate_rolls(line, patterns):
    """Fill a verified trade matcher, preserving the sign and both ends of item rolls."""
    if "#" not in line and (result := patterns.get(line.casefold())):
        return result
    if "#" in line:
        return ""
    for regex in ROLLS:
        template = patterns.get(regex.sub("#", line).casefold())
        if template:
            values = iter(match[0].replace(".", ",") for match in regex.finditer(line))
            return re.sub("#", lambda _: next(values), template)
    return ""


def inverted_stat(en, de):
    # Two website templates accidentally reused their negative adjective for both directions.
    return (en.endswith((" increased Armour, Evasion and Energy Shield", " increased Spirit Reservation Efficiency"))
            and "% verringerte" in de)


def apply_game_de(data, supplement=None):
    if supplement is None:
        with gzip.open(Path(__file__).with_name("poe2_game_de.json.gz"), "rt", encoding="utf-8") as stream:
            supplement = json.load(stream)
    for row in data["items"]:
        if not row.get("gameId") and "kind" not in row and row["name"] in supplement["missingItemIds"]:
            row["gameId"] = supplement["missingItemIds"][row["name"]]
        key = row.get("gameId") or ("unique:" + row["name"] if row.get("kind") == "unique" else "")
        pair = supplement["items"].get(key)
        if pair and pair[0] == row["name"] and not row.get("de"):
            row["de"] = pair[1]
        desc = supplement["itemDescriptions"].get(row["name"])
        if desc and (not row.get("gameId") or row["gameId"] == desc[0]):
            existing = row.setdefault("description", {})
            if not existing.get("en") or existing["en"] == desc[1]:
                for lang, value in (("en", desc[1]), ("de", desc[2]), ("hybrid", desc[2])):
                    if not existing.get(lang):
                        existing[lang] = value

    translations = data.setdefault("plannerStatTranslations", {})
    data["ascendancyLabelsDe"] = supplement["ascendancies"]
    tag_labels = data["affixUi"]["tagLabels"]
    for tag, german in supplement["tagLabels"].items():
        labels = tag_labels.setdefault(tag, {})
        if not labels.get("de") or labels["de"].casefold() == tag.replace("_", " ").casefold():
            labels["de"] = german
    kelari = data["skills"].get("KelariDeceptionVarashta", {})
    if kelari.get("tags") == "Command, AoE, Physical, Duration" and not kelari.get("tagsDe"):
        kelari["tagsDe"] = "Befehl, Wirkungsbereich, Physisch, Dauer"
    translations.update(supplement["statLines"])
    data["germanRollPatterns"] = supplement["tradePatterns"]
    for row in data["mods"]:
        pair = supplement["affixNames"].get(row["id"])
        if pair and pair[0] == row["name"] and not row.get("de"):
            row["de"] = pair[1]
        if row.get("statsDe") and len(row["stats"]) == len(row["statsDe"]):
            for i, en in enumerate(row["stats"]):
                corrected = supplement["corrections"].get(en)
                if corrected and row["statsDe"][i] == corrected[0]:
                    row["statsDe"][i] = corrected[1]
                elif row["statsDe"][i] == en and translations.get(en):
                    row["statsDe"][i] = translations[en]
        if row["stats"] and not row.get("statsDe") and all(translations.get(line) and translations[line] != line for line in row["stats"]):
            row["statsDe"] = [translations[line] for line in row["stats"]]
        elif not row.get("statsDe"):
            joined = supplement["joinedMods"].get(row["id"])
            if joined and joined[0] == row["stats"]:
                row["statsDe"] = joined[1]

    for ident, row in data.get("supports", {}).items():
        if ident == "SupportRearmPlayerTwo" and row["name"] == "Rearm II" and row.get("de") == "Wiederbewaffnung I":
            # Both PoE2DB locales identify this as RearmSupportTwo, but the German
            # game label repeats rank I. Keep both ranks distinguishable in the picker.
            row["de"] = "Wiederbewaffnung II"
        # A legacy guide referenced a granted skill in a support slot under its skill ID.
        skill = data["skills"].get(ident, {})
        if skill and skill["name"] == row["name"]:
            for key in ("de", "description", "icon"):
                if key in skill and not row.get(key):
                    row[key] = skill[key].copy() if isinstance(skill[key], dict) else skill[key]
        note = SUPPORT_NOTES.get(ident)
        if note and row.get("source", "").endswith("/" + ident):
            description = row.setdefault("description", {})
            for language, text in {**note, "hybrid": note["de"]}.items():
                if not description.get(language):
                    description[language] = text
        if row.get("de") and row.get("family") == TIER.sub("", row["name"]):
            row["familyDe"] = TIER.sub("", row["de"])
    for ident, row in supplement["granted"].items():
        if ident not in data["skills"]:
            row["description"].setdefault("hybrid", row["description"]["de"])
            data["skills"][ident] = row
            data["skillSupports"].setdefault(ident, supplement["supportedBy"][ident])
        # Resolve a granted skill's art against stable source IDs each patch.
        # New catalogues may already supply a dedicated skill icon.
        skill = data["skills"][ident]
        if not skill.get("icon"):
            node = data.get("plannerTree", {}).get("nodes", {}).get(row.get("iconFromPassive"), {})
            shared = data["skills"].get(row.get("iconFromSkill"), {})
            if node.get("icon", -1) >= 0:
                skill["icon"] = f"tree/{node['icon']}"
            elif shared.get("icon"):
                skill["icon"] = shared["icon"]
