"""Localized, optional build and phase notes shared by the offline HUD and editor."""

from difflib import SequenceMatcher
import re
from urllib.parse import unquote


BUILD_TOPICS = {
    "overview": ("Build-Idee", "Build overview"),
    "strengths": ("Stärken", "Strengths"),
    "weaknesses": ("Schwächen", "Weaknesses"),
}
WEBSITE_TOPICS = {"overview": "guideIntro", "strengths": "strengths", "weaknesses": "weaknesses"}
PHASE_TOPICS = {
    "next": ("Als Nächstes", "Up next"),
    "playstyle": ("So spielst du", "How to play"),
    "why": ("So funktioniert es", "How it works"),
    "quests": ("Questentscheidungen", "Quest choices"),
    "gems": ("Fertigkeiten", "Skills"),
    "gear": ("Ausrüstung", "Gear"),
    "tree": ("Passivbaum", "Passive tree"),
}
LANG_ORDER = {
    "de": ("de", "hybrid", "en"), "hybrid": ("hybrid", "de", "en"), "en": ("en", "hybrid", "de"),
}
_REFERENCE = re.compile(r"\[\[([^|\]\n]+)\|([^\]\n]*)\]\]")


def reference_parts(text):
    """Yield visible text, reference ID and original token for lossless editing."""
    offset = 0
    for match in _REFERENCE.finditer(text):
        if match.start() > offset:
            yield text[offset:match.start()], "", ""
        yield unquote(match[2]), unquote(match[1]), match[0]
        offset = match.end()
    if offset < len(text):
        yield text[offset:], "", ""


def plain_guide_text(value):
    return _REFERENCE.sub(lambda match: unquote(match[2]), value).strip() if isinstance(value, str) else ""


def editorial_lines(owner, key, language):
    value = owner.get("editorial", {}).get(key, {})
    original = owner.get(WEBSITE_TOPICS.get(key))
    if isinstance(original, str) and original.strip() and not value.get(language):
        return [line.strip() for line in original.splitlines() if line.strip()]
    for lang in LANG_ORDER[language]:
        lines = value.get(lang, [])
        if lines:
            return lines
    return []


def website_export(build, language):
    """Add the reader fields understood by Build Editor 1.7.4 to an export copy."""
    result = dict(build)
    mirrored = []
    for key, flat in WEBSITE_TOPICS.items():
        if isinstance(build.get(flat), str) and build[flat].strip():
            continue  # Keep independent original website copy, including its original language.
        lines = editorial_lines(build, key, language)
        if lines:
            result[flat] = "\n".join(plain_guide_text(line) for line in lines)
            mirrored.append(key)
    if mirrored:
        result["websiteEditorialProjection"] = {"language": language, "topics": mirrored}
    return result


def read_website_export(build, max_lines, max_length):
    """Consume mirrors generated on export; fold subsequent website edits into their language."""
    marker = build.get("websiteEditorialProjection")
    if not isinstance(marker, dict) or not isinstance(marker.get("language"), str):
        return build
    if marker["language"] not in LANG_ORDER or not isinstance(marker.get("topics"), list):
        return build
    language = marker["language"]
    for key, flat in WEBSITE_TOPICS.items():
        localized = build.get("editorial", {}).get(key)
        original = build.get(flat)
        if key not in marker["topics"] or not isinstance(localized, dict) or not isinstance(original, str):
            continue
        expected = next((localized[lang] for lang in LANG_ORDER[language] if localized.get(lang)), [])
        rendered = [plain_guide_text(line) for line in expected]
        if original == "\n".join(rendered):
            del build[flat]
            continue
        rows = [line.strip() for line in original.splitlines() if line.strip()]
        if len(rows) <= max_lines and all(len(line) <= max_length for line in rows):
            # An edit to one line in the website form should preserve references on the other lines.
            for match in SequenceMatcher(None, rendered, rows, autojunk=False).get_matching_blocks():
                rows[match.b:match.b + match.size] = expected[match.a:match.a + match.size]
            localized[language] = rows
            del build[flat]
        else:
            localized.pop(language, None)  # Keep the complete free-text original for older, long-form guides.
    del build["websiteEditorialProjection"]
    return build


def phase_label(phase, language):
    names = phase.get("names", {})
    name = next((names[lang] for lang in LANG_ORDER[language] if names.get(lang)), None)
    name = name or phase.get("name") or phase.get("label", "")
    return " · ".join(filter(None, (name, phase.get("range"))))


def stage_view(stage, language, *, keep_references=False):
    """Project at read time, so language switches never rewrite a saved plan."""
    result = dict(stage)
    if "names" in stage:
        result["label"] = phase_label(stage, language)
    for source, field in (("next", "nextSteps"), ("playstyle", "playstyle"), ("why", "why"), ("quests", "quests"),
                          ("gems", "skills"), ("gear", "craft"), ("tree", "passives")):
        values = list(editorial_lines(stage, source, language))
        if field in ("nextSteps", "playstyle"):
            legacy = stage.get("next" if field == "nextSteps" else "quick")
            if legacy:
                values.append(legacy)
            values.extend(stage.get(field, ()))
        else:
            values.extend(stage.get(field, ()))
        unique = {}
        for line in values:
            plain = plain_guide_text(line)
            if plain:
                unique.setdefault(plain, line if keep_references else plain)
        result[field] = list(unique.values())
    result["next"] = next(iter(result["nextSteps"]), "")
    result["quick"] = next(iter(result["playstyle"]), "")
    return result
