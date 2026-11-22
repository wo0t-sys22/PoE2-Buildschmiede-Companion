"""Resolve player-facing gem names in offline build-guide prose."""

from collections import defaultdict
from functools import lru_cache
import re

from poe2_lexicon import catalogue, public_name
from poe2_lexicon_explain import node_copy
from poe2_r18_features import PALETTE, TERM_CATALOG, term_key, term_labels, term_pattern


# These are grammatical forms in running text, not separate gems.
INFLECTIONS = {
    "SummonSkeletalSnipersPlayer": {
        "de": ("Skelettschützen",),
    },
    "GasArrowPlayer": {
        "de": ("Gaspfeile", "Gaspfeilen"),
        "en": ("Gas Arrows",),
    },
}


def equipped_gem_ids(stage):
    ids = set()
    for group in stage.get("loadout", {}).get("gems", ()):
        for ref in (group.get("skill"), *group.get("sockets", group.get("supports", ()))):
            if isinstance(ref, dict) and ref.get("id"):
                ids.add(ref["id"])
    return ids


def gem_record(ident):
    data = catalogue()
    return data["skills"].get(ident) or data["supports"].get(ident)


def gem_entry(ident, language):
    row = gem_record(ident)
    if not row:
        return None
    title = (row.get("de") if language == "de" else None) or row["name"]
    facet = "support" if ident in catalogue()["supports"] else "skill"
    summary, _ = node_copy(row, facet, ident, language)
    return title, summary


def gem_color(ident):
    return PALETTE["support" if ident in catalogue()["supports"] else "gem"]


@lru_cache(maxsize=3)
def _names(language):
    names = defaultdict(set)
    for kind in ("skills", "supports"):
        for ident, row in catalogue()[kind].items():
            variants = [row["name"], *row.get("aliases", ()), *INFLECTIONS.get(ident, {}).get("en", ())]
            if language != "en":
                variants.extend((row.get("de"), *INFLECTIONS.get(ident, {}).get("de", ())))
            if row["name"].startswith("Skeletal "):
                variants.append(row["name"] + "s")
                if language != "en" and (german := row.get("de")):
                    variants.extend((german + "n", german.replace("-", ""), german.replace("-", "") + "n"))
            for variant in variants:
                if not public_name(variant, ident):
                    continue
                key = term_key(variant)
                names[key].add(ident)
                # A tierless reference may resolve to the tier equipped in this phase.
                stem = re.sub(r" (?:i{1,3}|iv|v)$", "", key)
                names[stem].add(ident)
    for term in TERM_CATALOG.values():
        if term.get("role") not in ("gem", "support"):
            continue
        labels = [*term.get("aliases", ()), *term.get("routeAliases", ()), *term_labels(term, "en")]
        if language != "en":
            labels.extend(term_labels(term, "de"))
        candidates = {ident for label in labels for ident in names.get(term_key(label), ())}
        if len(candidates) == 1:
            for label in labels:
                names[term_key(label)].update(candidates)
    return names, term_pattern(tuple(names))


def gem_spans(text, language, preferred=()):
    """Yield (start, end, ID). Only phase context may resolve duplicate names or tiers."""
    names, pattern = _names(language)
    for match in pattern.finditer(text):
        name = match[0]
        candidates = names[term_key(name)]
        scoped = candidates.intersection(preferred)
        choices = scoped or candidates
        # Lowercase single-word names are frequently verbs ("support", "unleash", "rake").
        if len(choices) == 1 and (not name.islower() or " " in name or scoped):
            yield match.start(), match.end(), next(iter(choices))

