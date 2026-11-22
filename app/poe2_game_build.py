"""Convert GGG's public PoE2 .build contract into editable, offline planner setups."""

from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re

from poe2_build_import_interface import FILE_LIMIT, blank_setup, new_plan
from poe2_lexicon import catalogue
from poe2_website_content import ContentError, source_url


GAME_SLOTS = {"Weapon1": "main1", "Weapon2": "main2", "Offhand1": "off1", "Offhand2": "off2",
              "BodyArmour1": "body", "Helm1": "helm", "Boots1": "boots", "Gloves1": "gloves",
              "Amulet1": "amulet", "Ring1": "ring1", "Ring2": "ring2", "Ring3": "ring3", "Belt1": "belt"}
MARKUP = re.compile(r"<(?:[rbiusml]|red|orange|yellow|green|blue|indigo|violet|black|white|grey|bronze|silver|gold|unique|rgb\([\d, ]+\))>\{|[{}]", re.I)


@lru_cache(maxsize=1)
def interchange_ids():
    with gzip.open(Path(__file__).with_name("poe2_interchange_ids.json.gz"), "rt", encoding="utf-8") as stream:
        return json.load(stream)


@lru_cache(maxsize=1)
def catalogue_gem_ids():
    return {row["gameId"].rsplit("/", 1)[-1]: key for kind in ("skills", "supports")
            for key, row in catalogue()[kind].items() if row.get("gameId")}


def gem_id(value):
    """Resolve both the PoB alias and the in-game base item ID, preserving unrecognized references."""
    if value.startswith(("Metadata/Items/Gem/", "Metadata/Items/Gems/")):
        short = value.rsplit("/", 1)[-1]
        return catalogue_gem_ids().get(short) or interchange_ids()["gems"].get(short, value)
    return value


def plain_hint(value):
    if not isinstance(value, str):
        raise ContentError("additional_text: Text erwartet.")
    chunks, stack, start = [], [], 0
    for match in MARKUP.finditer(value):
        chunks.append(value[start:match.start()])
        token = match[0]
        if token == "}":
            if not stack or not stack.pop():
                chunks.append(token)
        else:
            markup = token != "{"
            stack.append(markup)
            if not markup:
                chunks.append(token)
        start = match.end()
    return ("".join(chunks) + value[start:]).strip()


def _interval(row):
    value = row.get("level_interval", [1, 100])
    if type(value) is int:
        value = [value, value]
    if (not isinstance(value, list) or len(value) != 2 or any(type(v) is not int for v in value)
            or not 0 <= value[0] <= value[1] <= 100):
        raise ContentError("level_interval: Stufenbereich zwischen 0 und 100 erwartet.")
    return max(1, value[0]), max(1, value[1])


def _rows(data, field, limit, level=None):
    values = data.get(field, [])
    if not isinstance(values, list) or len(values) > limit:
        raise ContentError(f"{field}: Höchstens {limit} Einträge erwartet.")
    ident = "inventory_id" if field == "inventory_slots" else "id"
    for row in values:
        if isinstance(row, str) and ident == "id":
            row = {"id": row}
        if not isinstance(row, dict) or not isinstance(row.get(ident), str) or not 0 < len(row[ident]) <= 240:
            raise ContentError(f"{field}: Gültige Spiel-ID erwartet.")
        start, end = _interval(row)
        if level is None or start <= level <= end:
            yield row


def _gem(row):
    source = row["id"]
    ident = gem_id(source)
    gem = {"id": ident}
    note = plain_hint(row.get("additional_text", ""))
    if ident.startswith("Metadata/") or note:
        fallback = re.sub(r"^(SkillGem|SupportGem)", "", source.rsplit("/", 1)[-1])
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", fallback)
        gem["overlayRef"] = {"id": ident, "name": name, **({"note": note} if note else {})}
    if "level_interval" in row:
        gem["levelInterval"] = row["level_interval"]
    return gem


def _inventory_slot(row):
    key = row["inventory_id"]
    x, y = row.get("slot_x", 0), row.get("slot_y", 0)
    if any(type(i) is not int or not 0 <= i <= 255 for i in (x, y)):
        raise ContentError(f"{key}: Ungültige Slot-Koordinaten.")
    if key in ("Flask1", "Charm1") and not y:
        return ("flask" if key == "Flask1" else "charm") + str(x + 1)
    return GAME_SLOTS.get(key, key) if not (x or y) else f"{key}-{x}-{y}"


@lru_cache(maxsize=1)
def _item_names():
    return {name: row for row in catalogue()["items"] for name in (row["name"], row.get("de")) if name}


def _item(row):
    unique = row.get("unique_name", "")
    if not isinstance(unique, str):
        raise ContentError("unique_name: Name erwartet.")
    gear = {"unique": unique, "sourceName": unique} if unique else {}
    text = plain_hint(row.get("additional_text", ""))
    lines = text.splitlines()
    if lines and (record := _item_names().get(lines[0].strip())):
        name = record["name"]
        gear["sourceName"] = unique or name
        gear["base"] = record.get("base") or name
        if record.get("kind") == "unique":
            gear["unique"] = name
        if len(lines) > 1:
            gear["sourceText"] = "\n".join([name, *(re.sub(r"^\s*\d+[.)]\s+", "", s) for s in lines[1:])])
    elif text:
        # Game slot annotations are free prose, and need not identify an item.
        gear["goal"] = text[:600]
        if len(text) > 600:
            gear["overlayRef"] = {"name": unique or row["inventory_id"], "note": text}
    if "level_interval" in row:
        gear["levelInterval"] = row["level_interval"]
    return gear


def game_setup(data, level=100):
    setup = blank_setup()
    asc = data.get("ascendancy", "")
    if not isinstance(asc, str):
        raise ContentError("ascendancy: Spiel-ID erwartet.")
    ids = interchange_ids()
    setup["className"], setup["ascendancy"] = ids["ascendancies"].get(asc, ("", asc))
    geometry = catalogue()["plannerTree"]
    roots = {c.get("root") for c in geometry["classes"].values()} | set(geometry["ascRoots"].values())
    for row in _rows(data, "passives", 1200, level):
        ident = ids["passives"].get(row["id"])
        if ident in roots:
            continue
        if ident not in geometry["nodes"]:
            unresolved = setup.setdefault("unresolvedGamePassives", [])
            if row["id"] not in unresolved:
                unresolved.append(row["id"])
            continue
        scope = row.get("weapon_set", 0)
        if type(scope) is not int or scope not in (0, 1, 2):
            raise ContentError("weapon_set: 0, 1 oder 2 erwartet.")
        path = "asc" if geometry["nodes"].get(ident, {}).get("asc") else ("main", "I", "II")[scope]
        if ident not in setup["tree"][path]:
            setup["tree"][path].append(ident)
        if note := plain_hint(row.get("additional_text", "")):
            setup.setdefault("treeNotes", {})[ident] = note
    for row in _rows(data, "skills", 128, level):
        gem = _gem(row)
        gem["sockets"] = [_gem(s) for s in _rows(row, "support_skills", 64, level)]
        for socket in gem["sockets"]:
            if socket["id"] in catalogue()["skills"]:
                socket["kind"] = "skill"
        if len(gem["sockets"]) > 5:
            raise ContentError(f"{gem['id']}: Mehr als fünf gleichzeitig empfohlene Supports.")
        setup["gems"].append(gem)
    for row in _rows(data, "inventory_slots", 256, level):
        slot = _inventory_slot(row)
        # Multiple recommendations can cover the same slot. Preserve the alternatives explicitly.
        gear = _item(row)
        if gear and slot in setup["gear"]:
            setup["gear"][slot].setdefault("alternatives", []).append(gear)
        elif gear:
            setup["gear"][slot] = gear
    return setup


def game_plan(data, name=None):
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ContentError(".build: Build-Name fehlt.")
    build = new_plan(name or data["name"].strip())
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    build.update(id="game-" + hashlib.sha256(raw).hexdigest()[:24], sourceGameBuild=data)
    if isinstance(data.get("author"), str):
        build["author"] = data["author"]
    if data.get("link"):
        link = data["link"]
        source_url(link, "link")
        build.update(sources=["original"], overlaySources={"original": {"url": link, "label": data["name"]}})
    if description := plain_hint(data.get("description", "")):
        build["guideIntro"] = description
    starts = {1}
    skills = list(_rows(data, "skills", 128))
    for rows in (_rows(data, "passives", 1200), _rows(data, "inventory_slots", 256), skills,
                 (support for skill in skills for support in _rows(skill, "support_skills", 64))):
        for row in rows:
            start, end = _interval(row)
            starts.add(start)
            if end < 100:
                starts.add(end + 1)
    size = len(raw)
    levels = sorted(starts)
    for index, level in enumerate(levels):
        setup = game_setup(data, level)
        size += len(json.dumps(setup, ensure_ascii=False).encode())
        if size > FILE_LIMIT:
            raise ContentError("Die aufbereiteten Phasen überschreiten 8 MB.")
        if index == 0:
            build.update(setup)
        if len(levels) > 1:
            end = levels[index + 1] - 1 if index + 1 < len(levels) else 100
            build["phases"].append({"id": f"level-{level}", "name": f"Level {level}" if level == end else f"Level {level}–{end}",
                                    "min_level": level, "setup": setup})
    return build
