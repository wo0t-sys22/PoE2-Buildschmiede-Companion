"""Offline language preview. Content IDs and saved run state are language-neutral."""
from poe2_r18_features import TERM_CATALOG, bundled, template_labels

LANGUAGES = {"hybrid": "Hybrid", "de": "Deutsch", "en": "English"}
LABEL_INDEX = {"de": 0, "hybrid": 1, "en": 2}
CATALOG = bundled("poe2_language_pilot.json")
BOSS_LANGUAGES = bundled("poe2_boss_languages.json")
CHECKLIST_TERMS = {key: labels for term in TERM_CATALOG.values() for key, labels in template_labels(term).items()}


def _area_key(zone):
    return zone.strip().casefold().replace("’", "'").removeprefix("the ")


TERM_AREA_LABELS = {
    _area_key(term["labels"]["en"]): term["labels"]
    for term in TERM_CATALOG.values() if term.get("labels", {}).get("en") and term["role"] in {"blue", "info"}
}


def checklist_text(ident, language):
    template = CATALOG.get("checklist", {}).get(ident, {}).get(language)
    if template is None:
        return None
    return template.format_map({key: row[language] for key, row in CHECKLIST_TERMS.items()})


def ui_text(text, language):
    return CATALOG.get("ui", {}).get(text, {}).get(language, text)


def area_label(zone, language):
    key = _area_key(zone)
    return (CATALOG.get("areas", {}).get(key, {}).get(language)
            or TERM_AREA_LABELS.get(key, {}).get(language)
            or zone)


def display_label(labels, language):
    """Select a label from a (German, hybrid, English) tuple."""
    return labels[LABEL_INDEX[language]]


def guide_edit(collection, ident, *path):
    key = "/".join(map(str, path))
    return CATALOG.get(collection, {}).get(ident, {}).get(key, {})


def guide_edit_roles(row, language):
    roles = {phrase: TERM_CATALOG[ident]["role"]
             for phrase, ident in row.get("termRefs", {}).get(language, {}).items()
             if ident in TERM_CATALOG}
    roles.update(row.get("accents", {}).get(language, {}))
    return roles


def boss_text(boss, language):
    fields = BOSS_LANGUAGES.get(boss["id"], {}).get(language, {})
    if not fields:
        return boss
    localized = {**boss, **fields}
    if "attacks" in fields:
        attacks = boss.get("attacks", ())
        localized["attacks"] = [
            {**attacks[index], **attack} if index < len(attacks) else attack
            for index, attack in enumerate(fields["attacks"])
        ]
    return localized
