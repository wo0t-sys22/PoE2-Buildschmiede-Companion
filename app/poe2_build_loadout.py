"""Structured, read-only view of the planner data attached to a leveling stage."""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType


SLOT_LABELS = {
    "main1": ("Haupthand I", "Mainhand I"), "off1": ("Nebenhand I", "Offhand I"),
    "main2": ("Haupthand II", "Mainhand II"), "off2": ("Nebenhand II", "Offhand II"),
    "helm": ("Helm", "Helmet"), "amulet": ("Amulett", "Amulet"), "body": ("Körperrüstung", "Body Armour"),
    "gloves": ("Handschuhe", "Gloves"), "ring1": ("Ring I", "Ring I"), "belt": ("Gürtel", "Belt"),
    "ring2": ("Ring II", "Ring II"), "boots": ("Stiefel", "Boots"),
    "flask1": ("Fläschchen I", "Flask I"), "flask2": ("Fläschchen II", "Flask II"),
    "charm1": ("Phiole I", "Charm I"), "charm2": ("Phiole II", "Charm II"), "charm3": ("Phiole III", "Charm III"),
}
SLOTS = tuple(SLOT_LABELS)
EDITOR_PHASE_PATHS = {"main": "main", "I": "weaponSet1", "II": "weaponSet2", "asc": "ascendancy"}
CATALOGUES = {"skill": "skills", "support": "supports", "item": "items", "passive": "nodes"}


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    kind: str
    icon: str = ""
    record: Mapping | None = None
    note: str = ""


@dataclass(frozen=True)
class GemGroup:
    skill: Asset
    sockets: tuple[Asset, ...]

    @property
    def supports(self):
        return tuple(gem for gem in self.sockets if gem.kind == "support")


@dataclass(frozen=True)
class ItemSlot:
    slot: str
    item: Asset | None
    goal: str = ""
    base: str = ""
    mod: str = ""
    imported_gear: Mapping | None = None


@dataclass(frozen=True)
class PassivePath:
    key: str
    nodes: tuple[Asset, ...]


@dataclass(frozen=True)
class StageLoadout:
    gems: tuple[GemGroup, ...] = ()
    items: tuple[ItemSlot, ...] = ()
    passives: tuple[PassivePath, ...] = ()
    tree_url: str = ""

    def __bool__(self):
        return bool(self.gems or self.items or self.passives or self.tree_url)


def slot_label(slot, language):
    if slot in SLOT_LABELS:
        return SLOT_LABELS[slot][language != "de"]
    if slot in ("lifeFlask", "manaFlask"):
        labels = ("Lebensfläschchen", "Life flask") if slot == "lifeFlask" else ("Manafläschchen", "Mana flask")
        return labels[language != "de"]
    if slot.startswith("jewel-") or slot.startswith("jewel") and slot[5:].isdigit():
        title = "Juwel" if language == "de" else "Jewel"
        return f"{title} · {slot[5:].lstrip('-')}"
    return slot


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _sequence(value):
    return value if isinstance(value, (list, tuple)) else ()


def _text(value):
    return value if isinstance(value, str) else ""


@lru_cache(maxsize=len(CATALOGUES))
def _asset_index(kind):
    # Keep this dependency lazy so content validation can use the wire constants.
    from poe2_lexicon import catalogue
    from poe2_overlay_lookup import search_text

    data = catalogue().get(CATALOGUES[kind], {})
    rows = ((_text(row.get("id")) or row["name"], row) for row in data) if kind == "item" else data.items()
    ids, aliases = {}, {}
    for ident, row in rows:
        for key in {ident, row.get("gameId")} - {None, ""}:
            ids[key] = None if key in ids else (ident, row)
        names = _sequence(row.get("aliases"))
        if not row.get("variantLabel"):
            names = (row.get("name"), row.get("de"), *names)
        for key in {search_text(name) for name in names if isinstance(name, str) and name} - {""}:
            aliases[key] = None if key in aliases else (ident, row)
    return ids, aliases


def resolve_asset(kind, ref, language):
    from poe2_overlay_lookup import search_text

    ref = _mapping(ref)
    ident, name, note = (_text(ref.get(key)) for key in ("id", "name", "note"))
    if not ident and not name:
        return None
    ids, aliases = _asset_index(kind)
    # Explicit IDs remain authoritative even when two catalogued assets share a name.
    match = ids.get(ident) if ident else aliases.get(search_text(name))
    if match is None:
        return Asset(ident, name or ident, kind, note=note)
    ident, row = match
    label = _text(row.get("de" if language == "de" else "name")) or name or row.get("name") or ident
    icon = row.get("icon") or row.get("imageLocal") or row.get("image") or ""
    return Asset(ident, label, kind, icon, MappingProxyType(row), note)


def stage_loadout(stage, language):
    """Resolve published references for display and preserve unknown names or IDs verbatim."""
    loadout = _mapping(_mapping(stage).get("loadout"))
    groups = []
    for raw in _sequence(loadout.get("gems")):
        raw = _mapping(raw)
        if skill := resolve_asset("skill", raw.get("skill"), language):
            sockets = []
            for ref in _sequence(raw.get("sockets", raw.get("supports"))):
                kind = "skill" if _mapping(ref).get("kind") == "skill" else "support"
                if asset := resolve_asset(kind, ref, language):
                    sockets.append(asset)
            groups.append(GemGroup(skill, tuple(sockets)))

    items = []
    gear = _mapping(_mapping(stage).get("plannerGear"))
    for raw in _sequence(loadout.get("items")):
        raw = _mapping(raw)
        if slot := _text(raw.get("slot")):
            items.append(ItemSlot(slot, resolve_asset("item", raw.get("item"), language),
                                  _text(raw.get("goal")), _text(raw.get("base")), _text(raw.get("mod")),
                                  _mapping(gear.get(slot)) or None))

    paths = []
    passives = _mapping(loadout.get("passives"))
    for key in EDITOR_PHASE_PATHS.values():
        nodes = tuple(asset for ref in _sequence(passives.get(key)) if (asset := resolve_asset("passive", ref, language)))
        if nodes:
            paths.append(PassivePath(key, nodes))
    return StageLoadout(tuple(groups), tuple(items), tuple(paths), _text(loadout.get("treeUrl")))


def _editor_ref(ident, labels, note=""):
    row = labels.get(ident)
    name = _text(row.get("name")) if isinstance(row, Mapping) else _text(row[0]) if _sequence(row) else ""
    result = {"id": ident}
    if name:
        result["name"] = name
    if note := _text(note):
        result["note"] = note
    return result


def loadout_from_editor_phase(phase, editor_catalog=None):
    """Adapt an explicitly supplied legacy WordPress phase without inferring build assignments."""
    phase = _mapping(phase)
    catalog = _mapping(editor_catalog)
    skills, supports, nodes = (_mapping(catalog.get(key)) for key in ("skills", "supports", "nodes"))
    gems = []
    for raw in _sequence(phase.get("gems")):
        raw = _mapping(raw)
        if ident := _text(raw.get("id")):
            sockets = []
            for socket in _sequence(raw.get("sockets")):
                entry = _mapping(socket)
                if socket_id := _text(entry.get("id")) or _text(socket):
                    active = entry.get("kind") == "skill"
                    ref = _editor_ref(socket_id, skills if active else supports)
                    sockets.append({**ref, "kind": "skill"} if active else ref)
            group = {"skill": _editor_ref(ident, skills), "supports": [ref for ref in sockets if "kind" not in ref]}
            if len(group["supports"]) != len(sockets):
                group["sockets"] = sockets
            gems.append(group)

    gear = _mapping(phase.get("gear"))
    items = []
    for slot in dict.fromkeys((*SLOTS, *gear)):
        entry = _mapping(gear.get(slot))
        values = {key: entry[key] for key in ("goal", "base", "mod") if _text(entry.get(key))}
        if ident := _text(entry.get("item")):
            values["item"] = {"id": ident}
        if _text(slot) and values:
            items.append({"slot": slot, **values})

    tree, notes = (_mapping(phase.get(key)) for key in ("tree", "notes"))
    passives = {}
    for source, target in EDITOR_PHASE_PATHS.items():
        refs = [_editor_ref(ident, nodes, notes.get(ident)) for ident in _sequence(tree.get(source)) if _text(ident)]
        if refs:
            passives[target] = refs

    return {key: value for key, value in (("gems", gems), ("items", items), ("passives", passives)) if value}
