"""Bounded local readers for Path of Building 2 and game planner variant archives."""

import base64
import binascii
import hashlib
import io
import json
import re
from xml.etree import ElementTree as ET
import zipfile
import zlib

from poe2_build_items import RARITIES, RARITY_HEADER, canonical_base
from poe2_build_import_interface import FILE_LIMIT, new_plan
from poe2_game_build import game_plan, gem_id, interchange_ids
from poe2_lexicon import catalogue
from poe2_website_content import ContentError


POB_SLOTS = {"Weapon 1": "main1", "Weapon 2": "off1", "Weapon 1 Swap": "main2", "Weapon 2 Swap": "off2",
             "Helmet": "helm", "Body Armour": "body", "Gloves": "gloves", "Boots": "boots",
             "Amulet": "amulet", "Belt": "belt", **{f"{kind} {i}": f"{kind.lower()}{i}"
             for kind, count in (("Ring", 3), ("Flask", 2), ("Charm", 3)) for i in range(1, count + 1)}}


def game_archive(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()
                       and entry.filename.lower().endswith(".build") and "__MACOSX/" not in entry.filename]
            if not entries or len(entries) > 100 or sum(e.file_size for e in entries) > FILE_LIMIT:
                raise ContentError("ZIP: 1 bis 100 .build-Dateien mit zusammen höchstens 8 MB erwartet.")
            plans, expanded, converted = [], 0, 0
            for entry in entries:
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ContentError("ZIP: Nicht unterstützte Kompression.")
                with archive.open(entry) as source:
                    content = source.read(FILE_LIMIT - expanded + 1)
                expanded += len(content)
                if expanded > FILE_LIMIT:
                    raise ContentError("ZIP: Die enthaltenen Daten überschreiten 8 MB.")
                try:
                    plan = game_plan(json.loads(content))
                    converted += len(json.dumps(plan, ensure_ascii=False).encode())
                    if converted > FILE_LIMIT * 4:
                        raise ContentError("Die aufbereiteten Varianten überschreiten zusammen 32 MB.")
                    plans.append(plan)
                except (ValueError, RecursionError) as error:
                    raise ContentError(f"{entry.filename}: {error}") from error
            return plans
    except (zipfile.BadZipFile, EOFError, RuntimeError, zlib.error) as error:
        raise ContentError("Das ZIP-Archiv ist beschädigt oder verschlüsselt.") from error


def pob_code(code):
    if len(code) > FILE_LIMIT:
        raise ContentError("Der PoB2-Code überschreitet 8 MB.")
    try:
        compact = b"".join(code.encode("ascii").split())
        packed = base64.b64decode(compact + b"=" * (-len(compact) % 4), altchars=b"-_", validate=True)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(packed, FILE_LIMIT + 1)
        if len(raw) > FILE_LIMIT or not inflater.eof or inflater.unused_data:
            raise ValueError
    except (UnicodeError, ValueError, binascii.Error, zlib.error) as error:
        raise ContentError("Einen vollständigen PoB2-Exportcode einfügen. Ein Freigabelink enthält keine Build-Daten.") from error
    return raw


def _number(value, default, low, high):
    return int(value) if value and re.fullmatch(r"[0-9]{1,3}", value) and low <= int(value) <= high else default


def _selected(parent, tag, key):
    choices = parent.findall(tag)
    if not choices:
        return parent
    return next((choice for i, choice in enumerate(choices, 1)
                 if choice.get("id", str(i)) == parent.get(key, "1")), choices[0])


def _pob_gem(element):
    effect, item = element.get("skillId", ""), element.get("gemId", "")
    ident = effect or gem_id(item) or element.get("nameSpec", "")
    known = catalogue()
    if ident not in known["skills"] and ident not in known["supports"] and item:
        ident = gem_id(item)
    if not ident:
        return None
    result = {"id": ident, "level": _number(element.get("level"), 1, 1, 40),
              "quality": _number(element.get("quality"), 0, 0, 100)}
    if element.get("nameSpec"):
        result["overlayRef"] = {"id": ident, "name": element.get("nameSpec")}
    if ident in known["skills"]:
        kind = "skill"
    elif ident in known["supports"] or "Support" in item or ident.startswith("Support"):
        kind = "support"
    else:
        kind = "skill"
    return kind, result


def _pob_skills(element):
    gems = []
    for skill in _selected(element, "SkillSet", "activeSkillSet").findall("Skill"):
        if skill.get("enabled") == "false":
            continue
        groups = [record for gem in skill.findall("Gem")
                  if gem.get("enabled") != "false" and (record := _pob_gem(gem))]
        active = next((i for i, (kind, _) in enumerate(groups) if kind == "skill"), None)
        if active is None:
            continue
        _, primary = groups.pop(active)
        primary["sockets"] = [{"kind": kind, **gem} for kind, gem in groups]
        if skill.get("label"):
            primary["label"] = skill.get("label")
        gems.append(primary)
    return gems


def _pob_item(element):
    raw = element.text or ""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    start = next((i for i, line in enumerate(lines) if RARITY_HEADER.match(line)), None)
    if start is None or start + 1 >= len(lines):
        return {"sourceName": lines[0], "sourceText": raw} if lines else {}
    declared = lines[start].partition(":")[2].strip().casefold()
    rarity = next((key for key, (de, en, _) in RARITIES.items() if declared in (de.casefold(), en.casefold())), declared)
    name = lines[start + 1]
    base = lines[start + 2] if rarity in ("unique", "rare", "relic") and start + 2 < len(lines) else name
    gear = {"sourceName": name, "base": canonical_base(base), "sourceText": raw, "rarity": rarity}
    if rarity in ("unique", "relic"):
        gear["unique"] = name
    return gear


def _node_ids(element, field="nodes"):
    values = element.get(field, "").split(",")
    if len(values) > 2000:
        raise ContentError("PoB2: Zu viele Baumknoten.")
    return list(dict.fromkeys(i.strip() for i in values if re.fullmatch(r"[0-9]{1,10}", i.strip())))


def _pob_tree(build, spec, items):
    geometry = catalogue()["plannerTree"]
    roots = {c.get("root") for c in geometry["classes"].values()} | set(geometry["ascRoots"].values())
    missing = set()

    def known_nodes(element):
        for node in _node_ids(element):
            if node in roots:
                continue
            if node in geometry["nodes"]:
                yield node
            else:
                missing.add(node)

    weapons = []
    for tag, path in (("WeaponSet1", "I"), ("WeaponSet2", "II")):
        if (weapon := spec.find(tag)) is not None:
            build["tree"][path] = list(known_nodes(weapon))
        weapons.extend(build["tree"][path])
    for node in known_nodes(spec):
        if node not in weapons:
            path = "asc" if geometry["nodes"].get(node, {}).get("asc") else "main"
            build["tree"][path].append(node)
    if missing:
        build["unresolvedGamePassives"] = sorted(missing)
    if (override := spec.find("Overrides/AttributeOverride")) is not None:
        for field, name in (("strNodes", "Strength"), ("dexNodes", "Dexterity"), ("intNodes", "Intelligence")):
            for node in _node_ids(override, field):
                choice = next((c for c in geometry["nodes"].get(node, {}).get("choices", []) if c["name"] == name), None)
                if choice:
                    build.setdefault("treeOptions", {})[node] = str(choice["id"])
    for socket in spec.findall("Sockets/Socket"):
        jewel = items.get(socket.get("itemId"))
        if jewel and socket.get("nodeId"):
            build.setdefault("treeJewels", {})[socket.get("nodeId")] = jewel
            build.setdefault("treeNotes", {})[socket.get("nodeId")] = jewel["sourceName"]
    if spec.get("treeVersion"):
        build["sourceTreeVersion"] = spec.get("treeVersion")


def pob_plan(raw, name=""):
    if len(raw) > FILE_LIMIT:
        raise ContentError("Die PoB2-Datei überschreitet 8 MB.")
    try:
        # A single, decoded representation makes XML declarations and the DTD check unambiguous.
        xml = raw.decode("utf-8-sig")
        if "\x00" in xml or re.search(r"<!\s*(DOCTYPE|ENTITY)\b", xml, re.I):
            raise ContentError("PoB2: UTF-8-XML ohne DTD erwartet.")
        root = ET.fromstring(xml)
    except (ET.ParseError, UnicodeError) as error:
        raise ContentError("Die PoB2-XML-Datei ist unlesbar.") from error
    if root.tag != "PathOfBuilding2" or (info := root.find("Build")) is None:
        raise ContentError("Ein Path-of-Building-2-Export mit Build-Sektion wird benötigt.")
    class_name, asc = info.get("className", ""), info.get("ascendClassName", "")
    level = _number(info.get("level"), 1, 1, 100)
    build = new_plan(name or f"{asc if asc and asc != 'None' else class_name or 'PoB2'} · Level {level}")
    build.update(id="pob2-" + hashlib.sha256(raw).hexdigest()[:24], className=class_name,
                 ascendancy=asc if asc != "None" else "", sourceLevel=level, importFormat="pob2-active")
    items = {}
    if (element := root.find("Items")) is not None:
        items = {item.get("id"): gear for item in element.findall("Item") if item.get("id") and (gear := _pob_item(item))}
        for slot in _selected(element, "ItemSet", "activeItemSet").findall("Slot"):
            if (gear := items.get(slot.get("itemId"))) and (key := slot.get("name")):
                build["gear"][POB_SLOTS.get(key, key)] = {**gear, **({"goal": slot.get("note")} if slot.get("note") else {})}
    if (element := root.find("Skills")) is not None:
        build["gems"] = _pob_skills(element)
    if (element := root.find("Tree")) is not None:
        spec = _selected(element, "Spec", "activeSpec")
        if (internal := spec.get("ascendancyInternalId")) in interchange_ids()["ascendancies"]:
            build["className"], build["ascendancy"] = interchange_ids()["ascendancies"][internal]
        _pob_tree(build, spec, items)
    if notes := (root.findtext("Notes") or "").strip():
        build["guideIntro"] = re.sub(r"\^(?:x[\da-fA-F]{6}|\d)", "", notes)
    return build
