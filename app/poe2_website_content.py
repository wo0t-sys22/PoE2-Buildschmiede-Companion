"""Content exchange with buildschmiede.de: one set of rules for export, website and Companion.

The contract is described in Doku/SCHNITTSTELLE_WEBSITE.md with JSON schemas in Doku/schemas/.
Packages the Companion loads from the website:

- buildschmiede.lexicon.v1  short glossary entries with a link to the full article,
- buildschmiede.builds.v1   published builds with their leveling stages.

Downloads run in the background. A package is used only after it passed validation;
otherwise the last valid copy in the user data folder stays in use. Bundled content
always works offline.
"""

from __future__ import annotations

from contextlib import closing
from http.client import HTTPConnection, HTTPException, HTTPSConnection
import json
import logging
import os
from pathlib import Path
import re
from threading import Lock, Thread
from urllib.parse import urlsplit

from poe2_build_editorial import BUILD_TOPICS, PHASE_TOPICS
from poe2_overlay_version import BUILD_LABEL

API_BASE = "https://buildschmiede.de/wp-json/buildschmiede/v1/companion"
BUILD_PLANNER_URL = "https://buildschmiede.de/buildplaner/"
PACKAGES = {"lexicon": "buildschmiede.lexicon.v1", "builds": "buildschmiede.builds.v1"}
MAX_BYTES = 2_000_000
TIMEOUT = 8
LANGUAGES = ("de", "hybrid", "en")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TERM_ID = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
WEBSITE_HOSTS = ("buildschmiede.de",)
LIMITS = {"entries": 5000, "aliases": 30, "title": 120, "summary": 400, "builds": 200, "stages": 20, "lines": 30, "line": 600}


class ContentError(ValueError):
    """A package does not follow the contract."""


def _text(value, field, limit, *, required=True):
    if value is None and not required:
        return
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise ContentError(f"{field}: Text fehlt oder ist länger als {limit} Zeichen.")


def _localized(value, field, limit, *, required=True, needs=("de",)):
    """Texts per language. `needs` lists the languages that must be present; any other may be missing."""
    if value is None and not required:
        return
    if not isinstance(value, dict) or not value or set(value) - set(LANGUAGES):
        raise ContentError(f"{field}: Erwartet ein Objekt mit de, hybrid und/oder en.")
    for language in LANGUAGES:
        _text(value.get(language), f"{field}.{language}", limit, required=language in needs)


def _strings(value, field, count, limit):
    if not isinstance(value, list) or len(value) > count:
        raise ContentError(f"{field}: Erwartet höchstens {count} Einträge.")
    for index, item in enumerate(value):
        _text(item, f"{field}[{index}]", limit)


def _unique(ids, field):
    if len(set(ids)) != len(ids):
        raise ContentError(f"{field}: IDs sind nicht eindeutig.")


def website_url(value, field):
    url = urlsplit(value) if isinstance(value, str) else None
    host = (url.hostname or "") if url else ""
    if not url or url.scheme != "https" or not any(host == name or host.endswith("." + name) for name in WEBSITE_HOSTS):
        raise ContentError(f"{field}: Nur https-Links auf buildschmiede.de sind erlaubt.")


def source_url(value, field):
    url = urlsplit(value) if isinstance(value, str) else None
    if not url or url.scheme not in ("https", "http") or not url.hostname:
        raise ContentError(f"{field}: Ungültiger Quellenlink.")


def _envelope(data, schema):
    if not isinstance(data, dict) or data.get("schema") != schema:
        raise ContentError(f"Schema {schema} erwartet.")
    source = data.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("revision"), str) or not source["revision"]:
        raise ContentError("source.revision fehlt.")


# Lexicon ------------------------------------------------------------------------------------

def validate_lexicon(data):
    _envelope(data, PACKAGES["lexicon"])
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) > LIMITS["entries"]:
        raise ContentError(f"entries: Erwartet eine Liste mit höchstens {LIMITS['entries']} Einträgen.")
    for index, entry in enumerate(entries):
        field = f"entries[{index}]"
        if not isinstance(entry, dict) or not TERM_ID.fullmatch(str(entry.get("id", ""))):
            raise ContentError(f"{field}.id: Stabile ID wie mechanic.spirit erwartet.")
        _localized(entry.get("title"), f"{field}.title", LIMITS["title"])
        _localized(entry.get("summary"), f"{field}.summary", LIMITS["summary"], required=False, needs=())
        if entry.get("url") is not None:
            website_url(entry["url"], f"{field}.url")
        if entry.get("aliases") is not None:
            _strings(entry["aliases"], f"{field}.aliases", LIMITS["aliases"], LIMITS["title"])
    _unique([entry["id"] for entry in entries], "entries")
    return data


def lexicon_index(data):
    """Validated package -> {id: entry} for the lookup."""
    return {entry["id"]: entry for entry in (data or {}).get("entries", ())}


def localized_text(value, language):
    """Requested language; hybrid falls back to English; then German, then English."""
    if not value:
        return ""
    return (value.get(language) or (value.get("en") if language == "hybrid" else "")
            or value.get("de") or value.get("en") or "")


# Builds -------------------------------------------------------------------------------------

STAGE_FIELDS = ("id", "min_level", "label", "quick", "next", "skills", "passives", "craft", "sources", "loadout",
                "names", "editorial")
PASSIVE_PATHS = ("main", "weaponSet1", "weaponSet2", "ascendancy")
EDITOR_FORMAT = "buildschmiede-editor"
EDITOR_PATHS = {"main": "main", "I": "weaponSet1", "II": "weaponSet2", "asc": "ascendancy"}
# The 18.6 public catalog predates className. Only these published guide IDs have a known class.
LEGACY_BUILD_CLASSES = {"whirling-assault": "Monk", "twister-spirit-walker": "Huntress",
                        "varashta-archon": "Sorceress", "tactician-supporting-fire": "Mercenary"}


def _editorial(record, path, topics):
    if "editorial" not in record:
        return
    notes = record["editorial"]
    if not isinstance(notes, dict):
        raise ContentError(f"{path}.editorial: Objekt erwartet.")
    for topic in topics.keys() & notes.keys():
        localized = notes[topic]
        if not isinstance(localized, dict) or set(localized) - set(LANGUAGES):
            raise ContentError(f"{path}.editorial.{topic}: Sprachfassungen de, hybrid und/oder en erwartet.")
        for lang, lines in localized.items():
            _strings(lines, f"{path}.editorial.{topic}.{lang}", LIMITS["lines"], LIMITS["line"])


def validate_editor_export(data):
    """Validate the editable Website Build Editor v1 file before any local write."""
    if not isinstance(data, dict) or data.get("format") != EDITOR_FORMAT or type(data.get("version")) is not int or data["version"] != 1:
        raise ContentError("Buildschmiede Build Editor JSON (Version 1) erwartet.")
    build = data.get("build")
    if not isinstance(build, dict):
        raise ContentError("build: Build fehlt.")
    _text(build.get("name"), "build.name", LIMITS["title"])
    _text(build.get("id"), "build.id", 160, required=False)

    def setup(value, field):
        if not isinstance(value, dict):
            raise ContentError(f"{field}: Setup fehlt.")
        for key in ("className", "ascendancy"):
            _text(value.get(key), f"{field}.{key}", LIMITS["title"], required=False)
        for name, gem in _records(value.get("gems", []), f"{field}.gems", 64):
            _text(gem.get("id"), f"{name}.id", 240)
            sockets = gem.get("sockets", [])
            if not isinstance(sockets, list) or len(sockets) > 5:
                raise ContentError(f"{name}.sockets: Höchstens fünf Sockel erwartet.")
            for socket in sockets:
                if socket in (None, ""):
                    continue
                _text(socket.get("id") if isinstance(socket, dict) else socket, f"{name}.sockets.id", 240)
        gear = value.get("gear", {})
        if not isinstance(gear, dict) or len(gear) > 64:
            raise ContentError(f"{field}.gear: Höchstens 64 Slots erwartet.")
        for key, item in gear.items():
            _text(key, f"{field}.gear.slot", 48)
            if not isinstance(item, dict):
                raise ContentError(f"{field}.gear.{key}: Ausrüstung erwartet.")
            for prop in ("base", "unique", "item", "sourceName", "goal", "mod"):
                _text(item.get(prop), f"{field}.gear.{key}.{prop}", LIMITS["line"], required=False)
            if item.get("sourceText") is not None and not isinstance(item["sourceText"], str):
                raise ContentError(f"{field}.gear.{key}.sourceText: Gegenstandstext erwartet.")
            if item.get("editedImport") is not None and not isinstance(item["editedImport"], bool):
                raise ContentError(f"{field}.gear.{key}.editedImport: Wahrheitswert erwartet.")
            hints = item.get("sourceAffixes")
            if hints is not None and (not isinstance(hints, dict) or any(
                    not isinstance(line, str) or not re.fullmatch(r"[0-9]{1,8}", line)
                    or not isinstance(ref, list) or len(ref) != 2 or not all(isinstance(part, str) and part for part in ref)
                    for line, ref in hints.items())):
                raise ContentError(f"{field}.gear.{key}.sourceAffixes: Affixfamilie und Rang je Textzeile erwartet.")
        tree = value.get("tree", {})
        if not isinstance(tree, dict):
            raise ContentError(f"{field}.tree: Passivbaum erwartet.")
        for key in EDITOR_PATHS:
            nodes = tree.get(key, [])
            if not isinstance(nodes, list) or len(nodes) > 300:
                raise ContentError(f"{field}.tree.{key}: Höchstens 300 Knoten erwartet.")
            for node in nodes:
                _text(str(node) if type(node) is int else node, f"{field}.tree.{key}", 32)

    setup(build, "build")
    _editorial(build, "build", BUILD_TOPICS)
    ids = []
    for field, phase in _records(build.get("phases", []), "build.phases", 500):
        _text(phase.get("id"), f"{field}.id", 160)
        ids.append(phase["id"])
        _text(phase.get("name"), f"{field}.name", LIMITS["title"])
        _text(phase.get("range"), f"{field}.range", LIMITS["title"], required=False)
        if "names" in phase:
            _localized(phase["names"], f"{field}.names", LIMITS["title"], needs=())
        _editorial(phase, field, PHASE_TOPICS)
        setup(phase.get("setup"), field)
    _unique(ids, "build.phases")
    return build


def _records(value, field, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ContentError(f"{field}: Erwartet eine Liste mit höchstens {limit} Einträgen.")
    for index, record in enumerate(value):
        name = f"{field}[{index}]"
        if not isinstance(record, dict):
            raise ContentError(f"{name}: Erwartet ein Objekt.")
        yield name, record


def _asset_ref(record, field):
    if not isinstance(record, dict) or not (record.get("id") or record.get("name")):
        raise ContentError(f"{field}: ID oder Name fehlt.")
    for key in ("id", "name"):
        if key in record:
            _text(record[key], f"{field}.{key}", 240)


def validate_loadout(loadout, field):
    """Validate public read-only Planner data. Return whether it contains displayable entries."""
    if not isinstance(loadout, dict):
        raise ContentError(f"{field}: Erwartet ein Objekt.")
    for name, group in _records(loadout.get("gems", []), f"{field}.gems", 32):
        _asset_ref(group.get("skill"), f"{name}.skill")
        for path, support in _records(group.get("supports", []), f"{name}.supports", 5):
            _asset_ref(support, path)
        if "sockets" in group:
            for path, socket in _records(group["sockets"], f"{name}.sockets", 5):
                _asset_ref(socket, path)
                if socket.get("kind", "support") not in ("skill", "support"):
                    raise ContentError(f"{path}.kind: skill oder support erwartet.")
    slots = []
    for name, entry in _records(loadout.get("items", []), f"{field}.items", 64):
        _text(entry.get("slot"), f"{name}.slot", 48)
        slots.append(entry["slot"])
        if "item" in entry:
            _asset_ref(entry["item"], f"{name}.item")
        if not (entry.get("item") or entry.get("goal") or entry.get("base") or entry.get("mod")):
            raise ContentError(f"{name}: Gegenstand oder Ausrüstungsziel fehlt.")
        for key in ("goal", "base", "mod"):
            if key in entry:
                _text(entry[key], f"{name}.{key}", LIMITS["line"])
    _unique(slots, f"{field}.items")
    passives = loadout.get("passives", {})
    if not isinstance(passives, dict):
        raise ContentError(f"{field}.passives: Erwartet ein Objekt.")
    for key in PASSIVE_PATHS:
        for name, node in _records(passives.get(key, []), f"{field}.passives.{key}", 300):
            _asset_ref(node, name)
            if "note" in node:
                _text(node["note"], f"{name}.note", LIMITS["line"])
    if "treeUrl" in loadout:
        website_url(loadout["treeUrl"], f"{field}.treeUrl")
    return bool(loadout.get("gems") or slots or any(passives.get(key) for key in PASSIVE_PATHS))


def validate_stages(stages, field="stages"):
    if not isinstance(stages, list) or not stages or len(stages) > LIMITS["stages"]:
        raise ContentError(f"{field}: Erwartet 1 bis {LIMITS['stages']} Stufen.")
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict) or not SLUG.fullmatch(str(stage.get("id", ""))):
            raise ContentError(f"{field}[{index}].id: Kleingeschriebene ID wie act-1 erwartet.")
    _unique([stage["id"] for stage in stages], field)
    levels = [stage.get("min_level") for stage in stages]
    if (levels[0] != 1 or any(type(level) is not int or not 1 <= level <= 100 for level in levels)
            or levels != sorted(set(levels))):
        raise ContentError(f"{field}: min_level beginnt bei 1 und steigt streng an.")
    for index, stage in enumerate(stages):
        name = f"{field}[{index}]"
        has_loadout = "loadout" in stage and validate_loadout(stage["loadout"], f"{name}.loadout")
        _text(stage.get("label"), f"{name}.label", LIMITS["line"])
        if "names" in stage:
            _localized(stage["names"], f"{name}.names", LIMITS["title"], needs=())
        _editorial(stage, name, PHASE_TOPICS)
        _text(stage.get("next"), f"{name}.next", LIMITS["line"], required="next" in stage or not has_loadout)
        _text(stage.get("quick"), f"{name}.quick", LIMITS["line"], required=False)
        for key in ("skills", "passives", "craft", "sources"):
            if key in stage:
                _strings(stage[key], f"{name}.{key}", LIMITS["lines"], LIMITS["line"])


def validate_builds(data):
    _envelope(data, PACKAGES["builds"])
    builds, sources = data.get("builds"), data.get("sources", {})
    if not isinstance(builds, list) or len(builds) > LIMITS["builds"]:
        raise ContentError(f"builds: Erwartet eine Liste mit höchstens {LIMITS['builds']} Builds.")
    if not isinstance(sources, dict):
        raise ContentError("sources: Erwartet ein Objekt.")
    for key, source in sources.items():
        if not isinstance(source, dict):
            raise ContentError(f"sources.{key}: Erwartet label und url.")
        _text(source.get("label"), f"sources.{key}.label", LIMITS["title"])
        source_url(source.get("url"), f"sources.{key}.url")
    for index, build in enumerate(builds):
        field = f"builds[{index}]"
        if not isinstance(build, dict) or not SLUG.fullmatch(str(build.get("id", ""))):
            raise ContentError(f"{field}.id: Kleingeschriebene ID wie mein-stormweaver erwartet.")
        for key in ("name", "author"):
            _text(build.get(key), f"{field}.{key}", LIMITS["title"])
        _text(build.get("className"), f"{field}.className", LIMITS["title"], required=False)
        _editorial(build, field, BUILD_TOPICS)
        leveling = build.get("leveling")
        if not isinstance(leveling, dict):
            raise ContentError(f"{field}.leveling: Leveling-Modul fehlt.")
        validate_stages(leveling.get("stages"), f"{field}.leveling.stages")
        refs = [*build.get("sources", []), *(ref for stage in leveling["stages"] for ref in stage.get("sources", []))]
        _strings(build.get("sources", []), f"{field}.sources", LIMITS["lines"], LIMITS["title"])
        missing = sorted(set(refs) - set(sources))
        if missing:
            raise ContentError(f"{field}: Unbekannte Quellen {missing}.")
        glossary = build.get("glossary", {})
        if not isinstance(glossary, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in glossary.items()):
            raise ContentError(f"{field}.glossary: Erwartet Begriff → Erklärung.")
    _unique([build["id"] for build in builds], "builds")
    return data


def companion_builds(data):
    """Validated catalog -> builds in the Companion's own format plus their source table."""
    builds = []
    for build in (data or {}).get("builds", ()):
        stages = [{key: stage[key] for key in STAGE_FIELDS if key in stage} for stage in build["leveling"]["stages"]]
        builds.append({"id": build["id"], "name": build["name"], "author": build["author"],
                       "className": build.get("className") or LEGACY_BUILD_CLASSES.get(build["id"], ""),
                       "sources": list(build.get("sources", [])), "glossary": dict(build.get("glossary", {})),
                       **({"editorial": build["editorial"]} if "editorial" in build else {}),
                       "stages": stages, "origin": "website"})
    return builds, dict((data or {}).get("sources", {}))


def merge_builds(companion, catalog):
    """Add website builds and apply published loadouts to matching bundled stages."""
    if not catalog:
        return []
    builds, sources = companion_builds(catalog)
    known = {build["id"]: build for build in companion.get("builds", [])}
    added = [build for build in builds if build["id"] not in known]
    for build in builds:
        local = known.get(build["id"])
        if local is None:
            continue
        loadouts = {stage["id"]: stage["loadout"] for stage in build["stages"] if stage.get("loadout")}
        for stage in local["stages"]:
            if stage["id"] in loadouts:
                stage["loadout"] = loadouts[stage["id"]]
    table = companion.setdefault("sources", {})
    for key, source in sources.items():
        table.setdefault(key, source)
    for build in added:
        build["sources"] = [ref for ref in build["sources"] if ref in table]
        for stage in build["stages"]:
            if "sources" in stage:
                stage["sources"] = [ref for ref in stage["sources"] if ref in table]
    companion.setdefault("builds", []).extend(added)
    return [build["id"] for build in added]


VALIDATORS = {"lexicon": validate_lexicon, "builds": validate_builds}


# Download and cache -------------------------------------------------------------------------

def api_base():
    """The website API. POE2_WEBSITE_API may point to a test system (https, or http on localhost)."""
    base = os.environ.get("POE2_WEBSITE_API", "").rstrip("/") or API_BASE
    url = urlsplit(base)
    local = url.hostname in ("127.0.0.1", "localhost")
    if url.scheme != "https" and not (url.scheme == "http" and local):
        raise ContentError("POE2_WEBSITE_API muss https verwenden (http nur für localhost).")
    return base


def fetch(name, base=None):
    """GET one package. Returns the parsed JSON or raises OSError/ContentError."""
    url = urlsplit(f"{base or api_base()}/{name}")
    connection_type = HTTPSConnection if url.scheme == "https" else HTTPConnection
    with closing(connection_type(url.hostname, url.port, timeout=TIMEOUT)) as connection:
        request_path = url.path + ("?" + url.query if url.query else "")
        connection.request("GET", request_path, headers={"Accept": "application/json",
                                                     "User-Agent": f"PoE2-Companion/{BUILD_LABEL}"})
        response = connection.getresponse()
        body = response.read(MAX_BYTES + 1)
    if response.status != 200:
        raise ContentError(f"HTTP {response.status}")
    if len(body) > MAX_BYTES:
        raise ContentError("Antwort ist zu groß.")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ContentError("Antwort ist kein gültiges JSON.") from error


class WebsiteContent:
    """Validated website packages with a cached copy in the user data folder."""

    def __init__(self, directory: Path):
        self.folder = directory / "website"
        self.lock = Lock()
        self.packages = {}
        self.status = {}
        for name in PACKAGES:
            path = self.folder / f"{name}.json"
            try:
                self.packages[name] = VALIDATORS[name](json.loads(path.read_text(encoding="utf-8")))
                self.status[name] = ("cached", self.packages[name]["source"]["revision"])
            except FileNotFoundError:
                self.status[name] = ("bundled", "")
            except (OSError, ValueError) as error:
                logging.warning("Website-Inhalt %s im Cache ungültig, wird ignoriert: %s", name, error)
                self.status[name] = ("bundled", "")

    def get(self, name):
        with self.lock:
            return self.packages.get(name)

    def refresh(self, names=tuple(PACKAGES), base=None):
        """Download, validate and store each package; keep the last valid copy on any failure."""
        for name in names:
            try:
                data = VALIDATORS[name](fetch(name, base))
            except (OSError, HTTPException, ContentError) as error:
                with self.lock:
                    kept = self.packages.get(name)
                    self.status[name] = ("cached", kept["source"]["revision"]) if kept else ("bundled", "")
                logging.info("Website-Inhalt %s nicht aktualisiert (%s), behalte %s.", name, error,
                             "den letzten gültigen Stand" if kept else "die gebündelten Daten")
                continue
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / f"{name}.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(path)
            with self.lock:
                self.packages[name] = data
                self.status[name] = ("current", data["source"]["revision"])

    def refresh_in_background(self, on_done=None):
        def work():
            self.refresh()
            if on_done:
                on_done()
        thread = Thread(target=work, name="website-content", daemon=True)
        thread.start()
        return thread
