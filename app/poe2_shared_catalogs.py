"""Validation and stable-ID imports for the three shared catalogue files."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re

CATALOG_FILES = ("lexicon.v1.json", "currency.v1.json", "game-translations.de.v1.json")
LEXICON, CURRENCY, TRANSLATIONS = CATALOG_FILES
_ROW_ID = re.compile(r"[a-z0-9][a-zA-Z0-9_.:-]{0,180}")
_LANGS = {"de", "en", "hybrid"}


def _require(condition, field):
    if not condition:
        raise ValueError(f"Ungültiger Wert für {field}.")


def _mapping(value, field):
    _require(isinstance(value, dict) and all(isinstance(k, str) for k in value), field)
    return value


def _texts(value, field, min_length=0):
    _require(isinstance(value, list) and len(value) >= min_length and all(isinstance(v, str) for v in value), field)


def _localized(value, field):
    values = _mapping(value, field)
    _require(values.keys() <= _LANGS and all(isinstance(v, str) for v in values.values()), field)


@lru_cache(maxsize=1)
def native_icons():
    with gzip.open(Path(__file__).with_name("poe2_shared_icon_refs.json.gz"), "rt", encoding="utf-8") as source:
        return json.load(source)


def _icon(row, field):
    icon = row.get("icon")
    if icon not in (None, ""):
        _require(isinstance(icon, str) and re.fullmatch(r"shared-art/[a-z0-9_/-]+\.(?:png|webp)", icon)
                 and icon in native_icons(), field)


def _records(rows, key):
    _require(isinstance(rows, list), key)
    result = {}
    for row in rows:
        _mapping(row, key)
        ident = row.get(key)
        _require(isinstance(ident, str) and _ROW_ID.fullmatch(ident) and ident not in result, key)
        result[ident] = row
    return result


def _lexicon(doc):
    # The existing REST reader owns its base format, trusted article URLs and text limits.
    from poe2_website_content import validate_lexicon
    validate_lexicon(doc)
    slugs = set()
    for ident, row in _records(doc.get("entries"), "id").items():
        _require(isinstance(row.get("role"), str), f"{ident}.role")
        if "currencyId" in row:
            ref = row["currencyId"]
            _require(isinstance(ref, str) and ref.startswith("currency."), f"{ident}.currencyId")
        if "slug" in row:
            slug = row["slug"]
            _require(isinstance(slug, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
                     and slug not in slugs, f"{ident}.slug")
            slugs.add(slug)
        if "article" in row:
            _require(isinstance(row["article"], list), f"{ident}.article")
            for paragraph in row["article"]:
                _localized(paragraph, f"{ident}.article")
        if "tooltipSummary" in row:
            _localized(row["tooltipSummary"], f"{ident}.tooltipSummary")
        if "links" in row:
            _require(isinstance(row["links"], list), f"{ident}.links")
            for link in row["links"]:
                _require(isinstance(link, dict) and isinstance(link.get("url"), str), f"{ident}.links")
                if "label" in link and not isinstance(link["label"], str):
                    _localized(link.get("label"), f"{ident}.links.label")
        _icon(row, f"{ident}.icon")


def _currency(doc):
    _require(doc.get("schema") == "buildschmiede.currency.v1", "schema")
    for ident, row in _records(doc.get("items"), "currencyId").items():
        _require(isinstance(row.get("name"), str), f"{ident}.name")
        for field in ("de", "kind", "currencyFamily", "gameId", "imageLocal", "image", "source", "sourceDe", "type"):
            if field in row:
                _require(isinstance(row[field], str), f"{ident}.{field}")
        for field in ("visible", "referenceOnly"):
            if field in row:
                _require(type(row[field]) is bool, f"{ident}.{field}")
        for field in ("tags", "aliases", "gameIds"):
            if field in row:
                _texts(row[field], f"{ident}.{field}")
        for field in ("description", "summary"):
            if field in row:
                _localized(row[field], f"{ident}.{field}")
        for lang, lines in _mapping(row.get("practice", {}), f"{ident}.practice").items():
            _texts(lines, f"{ident}.practice.{lang}")
        for slot, effect in _mapping(row.get("socketEffects", {}), f"{ident}.socketEffects").items():
            for field, lines in _mapping(effect, f"{ident}.{slot}").items():
                if field == "bound":
                    _require(type(lines) is bool, f"{ident}.{slot}.bound")
                else:
                    _texts(lines, f"{ident}.{slot}.{field}")
        _icon(row, f"{ident}.icon")


def _translations(doc):
    _require(type(doc.get("version")) is int and doc["version"] == 1, "version")
    _require({"items", "affixNames", "statLines"} <= doc.keys(), "items, affixNames, statLines")
    for group, rows in doc.items():
        if group == "version":
            continue
        for ident, value in _mapping(rows, group).items():
            field = f"{group}.{ident}"
            if group in ("ascendancies", "missingItemIds", "statLines", "tagLabels", "tradePatterns"):
                _require(isinstance(value, str), field)
            elif group in ("affixNames", "corrections", "itemDescriptions", "items", "supportedBy"):
                # Original game reader accesses description[2] (English + German + metadata ID).
                minimum = 3 if group == "itemDescriptions" else 0 if group == "supportedBy" else 2
                _texts(value, field, minimum)
            elif group == "joinedMods":
                _require(isinstance(value, list) and len(value) == 2, field)
                for lines in value:
                    _texts(lines, field)
            elif group in ("skills", "supports", "granted", "passives"):
                _mapping(value, field)
                _require(all(isinstance(value.get(k), str) for k in ("name", "de")), field)
                for key in ("stats", "statsDe", "groups", "aliases"):
                    if key in value:
                        _texts(value[key], f"{field}.{key}")
                for key in ("tagsDe", "familyDe", "source", "iconFromPassive", "iconFromSkill"):
                    if key in value:
                        _require(isinstance(value[key], str), f"{field}.{key}")
                if "description" in value or group == "granted":
                    _localized(value.get("description"), f"{field}.description")
                    if group == "granted":
                        _require("de" in value["description"], f"{field}.description.de")


def validate_catalog(name, doc):
    _mapping(doc, name)
    validators = {LEXICON: _lexicon, CURRENCY: _currency, TRANSLATIONS: _translations}
    _require(name in validators, "Dateiname")
    validators[name](doc)
    return doc


def check_catalog_refs(lexicon, currency):
    ids = _records(currency.get("items"), "currencyId")
    for row in lexicon.get("entries", []):
        if "currencyId" in row:
            _require(isinstance(row["currencyId"], str) and row["currencyId"] in ids, f"{row.get('id')}.currencyId")


def merge_catalog(name, base, incoming):
    validate_catalog(name, incoming)
    result = deepcopy(incoming)
    changed = 0
    if name == TRANSLATIONS:
        for group in dict.fromkeys((*base, *incoming)):
            if group == "version":
                continue
            old, new = base.get(group, {}), incoming.get(group, {})
            changed += sum(k not in old or old[k] != v for k, v in new.items())
            result[group] = deepcopy({**old, **new})
        for key in result.get("granted", {}):
            _require(key in result.get("supportedBy", {}), f"supportedBy.{key}")
    else:
        field, key = ("entries", "id") if name == LEXICON else ("items", "currencyId")
        old, new = _records(base.get(field), key), _records(incoming[field], key)
        changed = sum(k not in old or old[k] != v for k, v in new.items())
        result[field] = deepcopy(list({**old, **new}.values()))
        if name == LEXICON and result[field] != base[field]:
            encoded = json.dumps(result[field], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            # Match JSON_UNESCAPED_UNICODE without JSON_UNESCAPED_LINE_TERMINATORS.
            encoded = encoded.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            result["source"]["revision"] = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
    validate_catalog(name, result)
    return result, changed
