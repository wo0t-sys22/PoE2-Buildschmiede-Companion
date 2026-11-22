"""Editable build files and their projections into the HUD's build guide."""

from copy import deepcopy
import json
import logging
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from uuid import uuid4

from poe2_build_editorial import WEBSITE_TOPICS, plain_guide_text, read_website_export, website_export
from poe2_website_content import (ContentError, EDITOR_FORMAT, EDITOR_PATHS, LEGACY_BUILD_CLASSES, LIMITS, PACKAGES,
                                  companion_builds, validate_builds, validate_editor_export)


FILE_LIMIT = 8_000_000
LOCAL_ID = re.compile(r"(?:build-import|planner)-[0-9a-f]{32}")
LEVEL = re.compile(r"(?:^\s*(\d{1,3})(?:\s*[-–—]|\s*$)|\b(?:level|stufe|lvl\.?)\s*(\d{1,3})\b)", re.I)


def blank_setup():
    return {"className": "", "ascendancy": "", "gear": {}, "gems": [],
            "tree": {key: [] for key in EDITOR_PATHS}}


def new_plan(name=""):
    return {"id": uuid4().hex, "name": name, "phases": [], **blank_setup()}


def phase_setup(build):
    keys = (*blank_setup(), "treeOptions", "treeNotes", "treeOrder", "questBudget", "notablePriority", "overlayPassives")
    return {key: deepcopy(build[key]) for key in keys if key in build}


def editor_file(build):
    return {"format": EDITOR_FORMAT, "version": 1, "build": build}


def _read_bytes(path):
    with path.open("rb") as source:
        raw = source.read(FILE_LIMIT + 1)
    if len(raw) > FILE_LIMIT:
        raise ContentError("Die Datei ist größer als 8 MB.")
    return raw


def _json(raw):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise ContentError("Die Datei enthält kein lesbares JSON.") from error


def _read(path):
    return _json(_read_bytes(path))


def plan_from_guide(build, sources):
    """Create an independent editor draft from a visible HUD guide and its cited sources."""
    def ident(ref):
        return ref.get("id") or ref["name"]

    plan = new_plan(build["name"])
    plan["className"] = build.get("className") or LEGACY_BUILD_CLASSES.get(build.get("id"), "")
    plan.update(author=build["author"], glossary=build["glossary"], sources=build["sources"])
    plan.update({key: build[key] for key in ("editorial", *WEBSITE_TOPICS.values()) if key in build})
    for stage in build["stages"]:
        data, setup = stage.get("loadout", {}), blank_setup()
        setup["className"] = plan["className"]
        setup["gems"] = [{"id": ident(group["skill"]), "overlayRef": group["skill"],
                          "sockets": [{"id": ident(ref), "overlayRef": ref,
                                       **({"kind": "skill"} if ref.get("kind") == "skill" else {})}
                                      for ref in group.get("sockets", group.get("supports", []))]}
                         for group in data.get("gems", [])]
        setup["gear"] = {row["slot"]: {**{k: row[k] for k in ("base", "goal", "mod") if k in row},
                                      **({"overlayRef": row["item"]} if "item" in row else {})}
                         for row in data.get("items", [])}
        setup["tree"] = {key: [ident(ref) for ref in data.get("passives", {}).get(value, [])]
                         for key, value in EDITOR_PATHS.items()}
        setup["overlayPassives"] = {ident(ref): ref for path in data.get("passives", {}).values()
                                    if isinstance(path, list) for ref in path
                                    if isinstance(ref, dict) and (ref.get("id") or ref.get("name"))}
        phase = {"id": stage["id"], "name": stage.get("name") or stage["label"], "min_level": stage["min_level"],
                 "setup": setup, "overlayStage": stage}
        phase.update({key: stage[key] for key in ("names", "range", "editorial") if key in stage})
        plan["phases"].append(phase)
    cited = {key for part in (build, *build["stages"]) for key in part.get("sources", [])}
    plan["overlaySources"] = {key: sources[key] for key in cited if key in sources}
    return deepcopy(plan)


def bundled_plans(directory=None):
    """Read editable guides shipped with this release; each file uses the import contract."""
    directory = directory if directory is not None else Path(__file__).parent / "guides"
    plans = {}
    for path in sorted(directory.glob("*.json")):
        try:
            plan = validate_editor_export(_read(path))
            key = plan.get("id")
            if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) or key in plans:
                raise ContentError("Eindeutige Build-ID erwartet.")
            plans[key] = plan
        except (OSError, ValueError):
            logging.exception("Gebündelter Guide %s konnte nicht geladen werden.", path.name)
    return plans


def import_plans(path):
    from poe2_build_interchange import game_archive, pob_code, pob_plan
    from poe2_game_build import game_plan

    path = Path(path)
    raw = _read_bytes(path)
    prefix = raw.removeprefix(b"\xef\xbb\xbf").lstrip()[:1]
    suffix = path.suffix.lower()
    if suffix == ".zip" or raw.startswith(b"PK\x03\x04"):
        return [validate_editor_export(editor_file(plan)) for plan in game_archive(raw)]
    if suffix == ".xml" or prefix == b"<":
        return [validate_editor_export(editor_file(pob_plan(raw, path.stem)))]
    if suffix in (".txt", ".pob", ".pob2") and prefix not in (b"{", b"["):
        try:
            code = raw.decode("utf-8-sig")
        except UnicodeError as error:
            raise ContentError("PoB2: Textdatei erwartet.") from error
        return [validate_editor_export(editor_file(pob_plan(pob_code(code), path.stem)))]
    data = _json(raw)
    if suffix == ".build" or (isinstance(data, dict) and "name" in data and
                               any(key in data for key in ("passives", "skills", "inventory_slots", "ascendancy"))):
        return [validate_editor_export(editor_file(game_plan(data)))]
    if isinstance(data, dict) and data.get("schema") == PACKAGES["builds"]:
        builds, sources = companion_builds(validate_builds(data))
        if not builds:
            raise ContentError("Der Katalog enthält keine Builds.")
        return [{**plan_from_guide(build, sources), "id": build["id"]} for build in builds]
    return [read_website_export(validate_editor_export(data), LIMITS["lines"], LIMITS["line"])]


def export_plan(build, path, website_language=None):
    """Write the editable website contract atomically, including all source and language fields."""
    path = Path(path)
    data = editor_file(website_export(build, website_language) if website_language else build)
    validate_editor_export(data)
    content = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    if len(content) > FILE_LIMIT:
        raise ContentError("Der Plan ist größer als 8 MB.")
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class BuildImportStore:
    def __init__(self, directory):
        self.directory = directory / "build-import-interface"
        self.plans = {}
        # Keep old IDs valid so saved HUD build selections still resolve after an update.
        for folder in (directory / "build-planner", self.directory):
            for file in sorted(folder.glob("*.json")):
                if LOCAL_ID.fullmatch(file.stem):
                    try:
                        self.plans[file.stem] = validate_editor_export(_read(file))
                    except (OSError, ContentError):
                        logging.exception("Build %s konnte nicht geladen werden.", file.name)

    def save(self, build, key=None):
        key = key or f"build-import-{uuid4().hex}"
        if not LOCAL_ID.fullmatch(key):
            raise ValueError("Ungültige lokale Plan-ID.")
        self.directory.mkdir(parents=True, exist_ok=True)
        export_plan(build, self.directory / f"{key}.json")
        self.plans[key] = deepcopy(build)
        return key


def _string(value):
    return value if isinstance(value, str) else ""


def _ref(value):
    return value if isinstance(value, dict) else {}


def _loadout(setup, original):
    gems = []
    for gem in setup.get("gems", []):
        sockets = []
        for socket in gem.get("sockets", []):
            value = {"id": socket} if isinstance(socket, str) else _ref(socket)
            if value.get("id"):
                ref = _ref(value.get("overlayRef")) or {"id": value["id"]}
                sockets.append({**ref, "kind": "skill"} if value.get("kind") == "skill" else ref)
        supports = [ref for ref in sockets if ref.get("kind") != "skill"]
        group = {"skill": _ref(gem.get("overlayRef")) or {"id": gem["id"]}, "supports": supports}
        if len(sockets) != len(supports):
            group["sockets"] = sockets
        gems.append(group)
    items = []
    for slot, gear in setup.get("gear", {}).items():
        name = next((_string(gear.get(k)) for k in ("sourceName", "unique", "item", "base") if gear.get(k)), "")
        row = {k: gear[k] for k in ("base", "goal", "mod") if gear.get(k)}
        if item := _ref(gear.get("overlayRef")) or ({"name": name} if name else None):
            row["item"] = item
        if row:
            items.append({"slot": slot, **row})
    passives = {}
    for raw, key in EDITOR_PATHS.items():
        refs = []
        for value in setup.get("tree", {}).get(raw, []):
            node = str(value)
            ref = _ref(_ref(setup.get("overlayPassives")).get(node)) or {"id": node}
            note = _string(_ref(setup.get("treeNotes")).get(node))
            refs.append({**ref, **({"note": note} if note else {})})
        if refs:
            passives[key] = refs
    result = {"gems": gems, "items": items, "passives": passives}
    if original.get("treeUrl"):
        result["treeUrl"] = original["treeUrl"]
    return result


def _guide_text(stage, phase):
    plain = plain_guide_text

    for key in ("next", "quick"):
        if key in stage:
            stage[key] = plain(stage[key])
    for key in ("skills", "craft", "passives", "nextSteps", "playstyle", "why", "quests"):
        if key in stage:
            stage[key] = [plain(line) for line in stage[key]]
    lines = [line.strip() for line in plain(phase.get("note")).splitlines() if line.strip()]
    if len(lines) > 1:
        stage.setdefault("quick", lines[0])
    if lines:
        stage.setdefault("next", "\n".join(lines[1:] or lines))
    hints = _ref(phase.get("guideHints"))
    for group, field in (("gems", "skills"), ("gear", "craft"), ("tree", "passives")):
        if isinstance(hints.get(group), list):
            stage.setdefault(field, []).extend(plain(line) for line in hints[group] if isinstance(line, str) and line.strip())
    text = _ref(phase.get("guideText"))
    blocks = text.get("blocks")
    placements = {"gems": "skills", "gemPriority": "skills", "rotation": "skills", "gear": "craft", "itemPriority": "craft",
                  "crafting": "craft", "tree": "passives", "asc": "passives"}
    for block in [*({"type": key, "text": value} for key, value in text.items() if isinstance(value, str)),
                  *(blocks if isinstance(blocks, list) else ())]:
        block = _ref(block)
        body = plain(block.get("text"))
        if body:
            field = placements.get(_string(block.get("placement") or block.get("type")))
            if field:
                stage.setdefault(field, []).append(body)
            elif not stage.get("quick"):
                stage["quick"] = body
            else:
                stage.setdefault("notes", []).append(body)


def guide_build(key, build):
    stages = []
    for index, phase in enumerate(build.get("phases") or [{"id": "setup", "name": build["name"], "setup": build}]):
        original = deepcopy(_ref(phase.get("overlayStage")))
        stage = {k: original[k] for k in ("quick", "next") if isinstance(original.get(k), str)}
        for field in ("skills", "craft", "passives", "sources", "nextSteps", "playstyle", "why", "quests"):
            if isinstance(original.get(field), list):
                stage[field] = [value for value in original[field] if isinstance(value, str)]
        phase_range = _string(phase.get("range"))
        match = LEVEL.search(phase_range)
        minimum = phase.get("min_level")
        if type(minimum) is not int:
            minimum = int(next(value for value in match.groups() if value)) if match else (
                1 if index == 0 and not phase_range else 101)
        stage.update(id=phase["id"], label=" · ".join(filter(None, (phase["name"], phase_range))),
                     min_level=minimum if 1 <= minimum <= 100 else 101,
                     loadout=_loadout(phase["setup"], _ref(original.get("loadout"))))
        if "names" in phase:
            stage.update(name=phase["name"], names=deepcopy(phase["names"]), range=phase_range)
        if "editorial" in phase:
            stage["editorial"] = deepcopy(phase["editorial"])
        # Only the internal HUD projection carries the editor's imported rolls and socketed items.
        # Keep the published read-only build catalogue's references in their original format.
        stage["plannerGear"] = _ref(phase["setup"].get("gear"))
        stage["passiveSetup"] = {key: phase["setup"][key] for key in ("className", "ascendancy", "treeOptions")
                                 if key in phase["setup"]}
        _guide_text(stage, phase)
        if index == 0 and (intro := _string(build.get("guideIntro"))):
            stage.setdefault("quick", intro)
        if notes := stage.pop("notes", []):
            stage.setdefault("playstyle", []).extend(notes)
        cited = phase.get("sources", stage.get("sources", build.get("sources", [])))
        stage["sources"] = [f"{key}:{ref}" for ref in cited if isinstance(ref, str)] if isinstance(cited, list) else []
        stages.append(stage)
    return {"id": key, "name": build["name"], "author": _string(build.get("author")) or "", "origin": "build-import",
            "sources": [f"{key}:{ref}" for ref in build.get("sources", []) if isinstance(ref, str)]
            if isinstance(build.get("sources"), list) else [],
            "glossary": {key: value for key, value in _ref(build.get("glossary")).items() if isinstance(value, str)},
            **{field: deepcopy(build[field]) for field in ("editorial", *WEBSITE_TOPICS.values()) if field in build},
            "stages": stages}
