"""Links from boss and area names in guide texts to their boss guide or area page.

A name links when the HUD has a page for it: a boss from the companion data or an area in the
campaign index. Every spelling counts that the term catalogue knows for the same boss or area,
so inflected forms like "den Aufgedunsenen Müller" or "zum Lichtfall-Lager" link as well.
"""

from __future__ import annotations

from poe2_language import CATALOG, LANGUAGES, boss_text
from poe2_r18_features import TERM_CATALOG, term_key, term_labels, term_matches

ARTICLES = ("the ", "der ", "die ", "das ")


def bare(name):
    key = term_key(name).strip()
    for article in ARTICLES:
        key = key.removeprefix(article)
    return key


def _term_names(term):
    labels = [label for language in LANGUAGES for label in term_labels(term, language)]
    return [*labels, *term.get("aliases", ()), *term.get("routeAliases", ())]


def _with_term_names(names, roles):
    """Add the catalogue spellings of every term that shares a name with this boss or area."""
    keys = {bare(name) for name in names}
    found = set(names)
    for term in TERM_CATALOG.values():
        if term.get("role") in roles:
            spellings = _term_names(term)
            if keys & {bare(name) for name in spellings}:
                found.update(spellings)
    return found


def link_index(bosses, areas):
    """{term_key(name): ("boss", boss_id) | ("area", area_key)}.

    bosses: companion boss records. areas: {area_key: (act, ...)} for areas the HUD can show.
    Boss names win over area names of the same spelling.
    """
    index = {}
    catalog = CATALOG.get("areas", {})
    for key in areas:
        entry = catalog.get(key, {})
        names = {key, *(entry.get(language) for language in LANGUAGES if isinstance(entry.get(language), str))}
        for name in _with_term_names(names, {"blue", "info"}):
            if len(bare(name)) > 3:
                index.setdefault(bare(name), ("area", key))
    short_names = {}
    for boss in bosses:
        # Boss search aliases also hold zone names, so only the displayed names count here.
        names = {boss_text(boss, language)["name"] for language in LANGUAGES}
        for name in _with_term_names(names, {"gold"}):
            if len(bare(name)) > 3:
                index[bare(name)] = ("boss", boss["id"])
            # "Der Aufgedunsene Müller" also links without its article
            if term_key(name) != bare(name):
                index[term_key(name)] = ("boss", boss["id"])
            # "Tavakai" for "Tavakai, the Chieftain", unless two bosses share it (Jamanra)
            short = bare(name.split(",")[0])
            if short != bare(name) and len(short) > 3:
                short_names.setdefault(short, set()).add(boss["id"])
    for name, owners in short_names.items():
        if len(owners) == 1 and name not in index:
            index[name] = ("boss", owners.pop())
    return index


def link_spans(text, index, skip=()):
    """(start, end, target) of every linked name in text; targets in skip stay plain.

    Names are proper nouns, so a match without a capital letter ("on the riverbank") stays plain.
    """
    return [(start, end, target) for start, end, target in term_matches(text, index)
            if target not in skip and any(char.isupper() for char in text[start:end])]
