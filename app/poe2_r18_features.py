"""R18 guide data and checklist shared by the Windows overlay and local browser."""
from __future__ import annotations

import json
from functools import lru_cache
from hashlib import blake2s
from pathlib import Path
import re
from poe2_shared_content import project
from threading import RLock
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def bundled(name):
    for directory in (BASE_DIR / "web", BASE_DIR.parent.parent / "dist"):
        path = directory / name
        if path.is_file():
            return project(name, read_json(path))
    return {}


GUIDE = bundled("poe2_r18_guide.json")
TIERS = bundled("poe2_r18_tiers.json").get("affixes", {})
PALETTE = GUIDE.get("palette", {})
TERM_DATA = bundled("terms.json")
TERM_CATALOG = TERM_DATA.get("terms", {})
AREA_TERM_ALIASES = TERM_DATA.get("areaAliases", {})


def area_key(name):
    return str(name or "").strip().lower().replace("’", "'").removeprefix("the ")


HUBS = {area_key(name): kind for kind, names in GUIDE.get("hubs", {}).items() for name in names}
def term_key(text):
    return text.lower().replace("’", "'")


@lru_cache(maxsize=64)
def term_pattern(aliases):
    if not aliases:
        return None
    variants = (re.escape(term).replace("'", "['’]") for term in sorted(aliases, key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + "|".join(variants) + r")(?!\w)", re.IGNORECASE)


def term_matches(text, aliases):
    pattern = term_pattern(tuple(aliases))
    if pattern:
        for match in pattern.finditer(text):
            key = term_key(match[0])
            if key in aliases:
                yield match.start(), match.end(), aliases[key]


def template_labels(entry):
    if "templateKey" in entry:
        return {entry["templateKey"]: entry["labels"]}
    return entry.get("templateLabels", {})


def term_labels(entry, language):
    if "templateLabels" in entry:
        return tuple(labels[language] for labels in entry["templateLabels"].values())
    label = entry.get("labels", {}).get(language)
    return (label,) if label else ()


@lru_cache(maxsize=4)
def term_aliases(language=None):
    aliases = {term_key(name): ident for ident, term in TERM_CATALOG.items() for name in term.get("aliases", ())}
    if language:
        for ident, term in TERM_CATALOG.items():
            for name in (*term.get("routeAliases", ()), *term_labels(term, language)):
                aliases[term_key(name)] = ident
    return aliases


ITEM_COLORS = {name: PALETTE.get(TERM_CATALOG[ident]["role"], PALETTE["normal"]) for name, ident in term_aliases().items()}


def item_spans(text):
    for start, end, ident in term_matches(text, term_aliases()):
        yield start, end, TERM_CATALOG[ident]["role"]


def text_term_refs(text, language, area=None, explicit=None):
    aliases = {**term_aliases(language), **AREA_TERM_ALIASES.get(area, {})}
    aliases.update({term_key(phrase): ident for phrase, ident in (explicit or {}).items()})
    return {text[start:end]: ident for start, end, ident in term_matches(text, aliases)}


def hub_kind(zone):
    key = area_key(zone)
    if key in HUBS:
        return HUBS[key]
    if re.search(r"\b(?:hideout|versteck)\b", key):
        return "hideout"
    return ""


def context_tips(zone):
    hub = hub_kind(zone)
    key = area_key(zone)
    if key == "clearfell" and not hub:
        key = "clearfell zone"
    return [tip for tip in GUIDE.get("tips", []) if key in tip["at"] or hub and hub in tip["at"]]


def localized(row, lang="de"):
    return row.get(lang, row.get("de", ""))


CHECK_KEY = re.compile(r"(?:route|boss|run|setup):[a-zA-Z0-9_.-]{1,100}")
SETUP_KEYS = {f'setup:{tip["id"]}' for tip in GUIDE.get("tips", []) if tip["scope"] == "setup"}

def hud_check_id(*parts):
    identity = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "run:hud-" + blake2s(identity, digest_size=12).hexdigest()


class Checklists:
    def __init__(self, path):
        self.path = path
        self.lock = RLock()

    def configure(self, directory):
        with self.lock:
            self.path = directory / self.path.name

    def _snapshot(self, data, character):
        profiles = data.get("profiles", {})
        user = profiles.get(character.casefold(), {}) if isinstance(profiles, dict) else {}
        user = user if isinstance(user, dict) else {}
        active = user.get("active") or "initial"
        runs = user.get("runs", {})
        checked = runs.get(active, {}) if isinstance(runs, dict) else {}
        saved_setup = data.get("setup", {})
        return {
            "character": character, "runId": active,
            "checked": {
                **{key: True for key, value in (checked.items() if isinstance(checked, dict) else ())
                   if value is True and CHECK_KEY.fullmatch(key) and not key.startswith(("run:section-", "setup:"))},
                **{key: True for key, value in (saved_setup.items() if isinstance(saved_setup, dict) else ())
                   if value is True and key in SETUP_KEYS},
            },
        }

    def get(self, character):
        with self.lock:
            return self._snapshot(read_json(self.path), character)

    def update(self, character, payload):
        with self.lock:
            data = read_json(self.path)
            current = self._snapshot(data, character)
            if payload.get("runId") != current["runId"] or payload.get("character") != character:
                raise ValueError("Die aktive Checkliste hat gewechselt.")
            profiles = data.get("profiles")
            if not isinstance(profiles, dict):
                profiles = data["profiles"] = {}
            user = profiles.setdefault(character.casefold(), {"active": current["runId"], "runs": {}})
            if not isinstance(user, dict):
                user = profiles[character.casefold()] = {"active": current["runId"], "runs": {}}
            if not isinstance(user.get("runs"), dict):
                user["runs"] = {}
            if payload.get("action") == "new":
                new_id = uuid4().hex
                user["active"] = new_id
                user["runs"][new_id] = {}
            else:
                key = payload.get("id")
                checked = payload.get("checked")
                if not isinstance(key, str) or not CHECK_KEY.fullmatch(key) or type(checked) is not bool:
                    raise ValueError("Ungültiger Checklisten-Eintrag.")
                if key.startswith("setup:"):
                    if key not in SETUP_KEYS:
                        raise ValueError("Einrichtungspunkt unbekannt.")
                    target = data.get("setup")
                    if not isinstance(target, dict):
                        target = data["setup"] = {}
                else:
                    target = user["runs"].setdefault(current["runId"], {})
                    if not isinstance(target, dict):
                        target = user["runs"][current["runId"]] = {}
                if checked:
                    target[key] = True
                else:
                    target.pop(key, None)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.path)
            return self._snapshot(data, character)
