from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4
import errno
import json
import logging
import math
import mimetypes
import os
import re
import socket
import sys
import threading
import time

import poe2_speedrun as speedrun
from poe2_overlay_version import APP_NAME, BUILD, BUILD_LABEL, SERVER_NAME
from poe2_shared_content import FILES as SHARED_FILES, MAX_BYTES as SHARED_LIMIT, RESOURCES as SHARED_RESOURCES, SHARED, project, retired_campaign_record
from poe2_language import CATALOG
from poe2_r18_features import Checklists, HUBS, PALETTE, hub_kind


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "poe2_race_state.json"
CAMPAIGN_TIPS_FILE = BASE_DIR / "poe2_campaign_tips.json"
COMPANION_FILE = BASE_DIR / "poe2_campaign_companion.json"
ENDGAME_ATLAS_FILE = BASE_DIR / "poe2_endgame_atlas.json"
BOSS_ARENAS_FILE = BASE_DIR / "poe2_boss_arenas.json"
LOCATION_CONFIG_FILE = BASE_DIR / "poe2_location_settings.json"
GUIDE_CONFIG_FILE = BASE_DIR / "poe2_guide_settings.json"
STEAM_APP_ID = "2694490"  # Path of Exile 2 on Steam
STATE_LOCK = threading.Lock()
LOCATION_LOCK = threading.Lock()
CONFIG_LOCK = threading.Lock()
GUIDE_LOCK = threading.Lock()
PORT = 8765
WEB_DIR = BASE_DIR / "web"
WEB_IMAGES = {
    "images/buildschmiede-hud.png", "images/buildschmiede-lockup.png",
    "images/buildschmiede-mark.png",
}
CHECKLISTS = Checklists(BASE_DIR / "poe2_checklists.json")
WEB_FILES = {
    "poe2_obs_overlay.html", "poe2_campaign_route.js",
    "poe2_campaign_companion.js", "poe2_campaign_companion.css", "poe2_campaign_companion.json",
    "poe2_endgame_atlas.js", "poe2_endgame_atlas.css", "poe2_endgame_atlas.json",
    "poe2_overlay_tracker.css", "PoE2_Kampagnen_Guide.md",
    "poe2_campaign_tips.json", "poe2_boss_arenas.json", "poe2_race_state.json",
}


def load_guide_data(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _zone_key(zone):
    name = zone.strip().lower().replace("’", "'")
    return name[4:] if name.startswith("the ") else name


def clue_content(clue):
    return {key: value for key, value in clue.items() if key != "source"}


CAMPAIGN_TIPS = load_guide_data(CAMPAIGN_TIPS_FILE)
CLIENT_AREA_IDS = CAMPAIGN_TIPS.get("clientAreaIds", {})
_AREA_NAMES = {_zone_key(name): name for name in CLIENT_AREA_IDS.values()}
SPEEDRUN_AREAS = {_zone_key(name): segment for ident, name in CLIENT_AREA_IDS.items()
                  if (segment := speedrun.area_segment(ident))}
LOCALIZED_AREAS = {
    _zone_key(row["de"]): _AREA_NAMES[key]
    for key, row in CATALOG.get("areas", {}).items() if key in _AREA_NAMES and row.get("de")
}
COMPANION = project(COMPANION_FILE.name,load_guide_data(COMPANION_FILE))
GUIDE_BUILD_IDS = tuple(build["id"] for build in COMPANION.get("builds", []))
CAMPAIGN_BOSSES = {boss["id"]: boss for boss in COMPANION.get("bosses", [])}
GUIDE_CHOICES = {"mode": ("basis", "veteran"), "build": GUIDE_BUILD_IDS}
BUNDLED_CLUES = {clue["id"]: clue for clue in CAMPAIGN_TIPS.get("clues", [])}
BUNDLED_CLUE_CONTENT = {clue_id: clue_content(clue) for clue_id, clue in BUNDLED_CLUES.items()}
# Older exports can lack highlights and still have the previous source labels.
BUNDLED_CLUES_WITHOUT_HIGHLIGHT = {
    clue_id: {key: value for key, value in clue.items() if key != "highlight"}
    for clue_id, clue in BUNDLED_CLUE_CONTENT.items()
}
PREVIOUS_CLUES = [clue_content(clue) for clue in CAMPAIGN_TIPS.get("previousClues", [])]
CAMPAIGN_ZONES = {
    _zone_key(name)
    for clue in BUNDLED_CLUES.values()
    for name in clue.get("zoneMatch", [clue["zone"]])
}
ENDGAME_HUB = "ziggurat refuge"
BOSS_ARENAS = {
    _zone_key(area): boss
    for boss in load_guide_data(BOSS_ARENAS_FILE).get("arenas", [])
    for area in boss["areas"]
}
CAMPAIGN_ZONES.update(key for key, boss in BOSS_ARENAS.items() if boss["phase"] == "campaign")
CAMPAIGN_ZONES.update(key for key, kind in HUBS.items() if kind in ("clearfell", "town"))
MAP_SCENES = {
    _zone_key(name) for name in load_guide_data(ENDGAME_ATLAS_FILE).get("map_scene_names", [])
} - CAMPAIGN_ZONES
AREA_GENERATED = re.compile(r'\bGenerating level (\d+) area "([^"]+)"')
MAP_AREA_ID = re.compile(r"map(?!hideout)[a-z0-9_]{2,}", re.IGNORECASE)
SCENE_SOURCE = re.compile(r"(?:^|\]\s+)\[SCENE\] Set Source \[([^\]]+)\]\s*$")
ENTERED_AREA = re.compile(r"(?:^|\]\s+(?::\s*)?)You have entered (.+)$")
CLIENT_MESSAGE = re.compile(r"\[(?:INFO|DEBUG|WARN|ERROR) Client (\d+)\]\s+(.*)$")
LEVEL_UP = re.compile(
    r": (\w+) \([^)]+\) (?:is now level (\d{1,3})|hat Stufe (\d{1,3}) erreicht)\.?"
)
SESSION_START = re.compile(r"Async connecting to \S+\.login\.pathofexile2?\.com:\d+|Abnormal disconnect:.*")
XP_RED_THRESHOLD = .75


@dataclass(frozen=True)
class AreaEvent:
    zone: str
    log_time: str
    kind: str
    level: int | None = None
    area_id: str = ""


def experience_multiplier(character_level, area_level):
    # ExileDB's campaign measurements for PoE2 0.5.5.
    safe_difference = 3 + character_level // 16
    effective_difference = max(0, abs(character_level - area_level) - safe_difference)
    base = character_level + 5
    return max(.01, (base / (base + effective_difference ** 2.5)) ** 1.3)


def campaign_level_check(zone, area_level, character_level):
    check = {"characterLevel": character_level}
    if not zone or hub_kind(zone) or _zone_key(zone) not in CAMPAIGN_ZONES or character_level == 100:
        return check
    check["areaLevel"] = area_level
    if character_level is not None and area_level is not None:
        multiplier = experience_multiplier(character_level, area_level)
        check.update(
            xpMultiplier=multiplier,
            status="in_range" if multiplier == 1 else "under" if character_level < area_level else "over",
            severity="red" if multiplier <= XP_RED_THRESHOLD else "amber" if multiplier < 1 else "green",
        )
    return check


def custom_route_clues(clues):
    if not isinstance(clues, list):
        return []
    result = []
    for clue in clues:
        if not isinstance(clue, dict):
            continue
        clue_id = clue.get("id")
        content = clue_content(clue)
        if isinstance(clue_id, str) and (
            content == BUNDLED_CLUE_CONTENT.get(clue_id)
            or content == BUNDLED_CLUES_WITHOUT_HIGHLIGHT.get(clue_id)
            or content in PREVIOUS_CLUES
        ):
            continue
        result.append(clue)
    return result


def _read_guide_settings():
    try:
        saved = load_guide_data(GUIDE_CONFIG_FILE)
    except UnicodeError:
        saved = {}
    return {
        key: saved[key] if saved.get(key) in choices else (choices[0] if choices else "")
        for key, choices in GUIDE_CHOICES.items()
    }


def register_builds(build_ids):
    """Accept website builds (buildschmiede.builds.v1) as valid guide choices."""
    with GUIDE_LOCK:
        GUIDE_CHOICES["build"] = tuple(dict.fromkeys((*GUIDE_CHOICES["build"], *build_ids)))


def guide_preferences():
    with GUIDE_LOCK:
        settings = _read_guide_settings()
    return {"guideMode": settings["mode"], "guideBuild": settings["build"]}


def load_guide_mode():
    return guide_preferences()["guideMode"]


def save_guide_setting(key, value):
    if value not in GUIDE_CHOICES[key]:
        raise ValueError("Ungültige Guide-Einstellung.")
    with GUIDE_LOCK:
        settings = _read_guide_settings()
        settings[key] = value
        temporary = GUIDE_CONFIG_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings) + "\n", encoding="utf-8")
        temporary.replace(GUIDE_CONFIG_FILE)
    return value


def save_guide_mode(mode):
    return save_guide_setting("mode", mode)


def route_clues(state):
    saved = [clue for clue in custom_route_clues(state.get("routeClues")) if not retired_campaign_record(clue)]
    saved_ids = {clue["id"] for clue in saved if isinstance(clue.get("id"), str)}
    return saved + [clue for ident, clue in BUNDLED_CLUES.items() if ident not in saved_ids]


def load_state():
    with STATE_LOCK:
        state = load_guide_data(STATE_FILE)
        with LOCATION_LOCK:
            atlas_location = LOCATION["atlasLocation"]
            live_zone = LOCATION["zone"] if LOCATION["enabled"] else ""
            manual_level = LOCATION["manual_level"]
            automatic_level = LOCATION["character_level"] if LOCATION["enabled"] else None
            level_check = campaign_level_check(
                live_zone if not atlas_location["kind"] else "", LOCATION["area_level"], manual_level or automatic_level,
            )
            level_check["manualLevel"] = manual_level
    if live_zone:
        if not isinstance(state.get("progress"), dict):
            state["progress"] = {}
        state["progress"]["currentAct"] = live_zone
    elif isinstance(state.get("progress"), dict):
        saved_zone = state["progress"].get("currentAct")
        if isinstance(saved_zone, str) and _zone_key(saved_zone) in LOCALIZED_AREAS:
            state["progress"]["currentAct"] = LOCALIZED_AREAS[_zone_key(saved_zone)]
    state["routeClues"] = route_clues(state)
    state.update(guide_preferences())
    state["atlasLocation"] = atlas_location
    state["levelCheck"] = level_check
    state["bossEncounter"] = BOSS_ARENAS.get(_zone_key(live_zone))
    return state


def _write_state(state):
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE_FILE)


def _seconds(value):
    try:
        seconds = float(value)
        return max(0, seconds) if math.isfinite(seconds) else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def timer_snapshot(state):
    meta = state.get("meta")
    progress = state.get("progress")
    meta = meta if isinstance(meta, dict) else {}
    progress = progress if isinstance(progress, dict) else {}
    started = _seconds(meta.get("runStartedAt"))
    return {
        "status": "live" if meta.get("status") == "live" and started else "prep",
        "runStartedAt": started or None,
        "runSeconds": _seconds(progress.get("runSeconds")),
    }


def _put_timer(state, clock):
    for key in ("meta", "progress"):
        if not isinstance(state.get(key), dict):
            state[key] = {}
    meta, progress = state["meta"], state["progress"]
    meta["status"] = clock["status"]
    meta["runStartedAt"] = clock["runStartedAt"]
    progress["runSeconds"] = clock["runSeconds"]


def speedrun_snapshot(state=None, now=None):
    if state is None:
        with STATE_LOCK:
            state = load_guide_data(STATE_FILE)
    status = get_location_status()
    return speedrun.snapshot(speedrun.read_speedrun(state), timer_snapshot(state), time.time() if now is None else now,
                             auto_splits=status["enabled"] and status["status"] in {"waiting", "last_log_entry", "detected"}
                             and bool(status["resolved_path"]))


def _speedrun_segment(zone, area_id):
    return speedrun.area_segment(area_id) or SPEEDRUN_AREAS.get(_zone_key(zone))


def _speedrun_start_zone(zone, area_id):
    return area_id.casefold() == "g1_1" or _zone_key(zone) == "riverbank"


def run_timer(action, now=None):
    if action not in ("toggle", "reset", "finish"):
        raise ValueError("Unbekannte Timer-Aktion.")
    now = time.time() if now is None else now
    with STATE_LOCK:
        state = load_guide_data(STATE_FILE)
        clock = timer_snapshot(state)
        data = speedrun.read_speedrun(state)
        attempt = data.get("attempt")
        if action == "reset":
            clock = {"status": "prep", "runStartedAt": None, "runSeconds": 0}
            data.pop("attempt", None)
        elif action == "finish":
            if not attempt and (clock["status"] == "live" or clock["runSeconds"]):
                attempt = speedrun.start_attempt(data, None, False, clock["runSeconds"])
            if attempt and not attempt["finished"]:
                seconds = speedrun.elapsed(clock, now)
                speedrun.finish(data, attempt, seconds, confirmed=False)
                clock.update(status="prep", runStartedAt=None, runSeconds=seconds)
        elif clock["status"] == "live":
            seconds = speedrun.elapsed(clock, now)
            if not attempt:
                attempt = speedrun.start_attempt(data, None, False, seconds)
            attempt["eligible"] = False
            clock.update(status="prep", runStartedAt=None, runSeconds=seconds)
        else:
            if not attempt or attempt["finished"]:
                if attempt and attempt["finished"]:
                    clock["runSeconds"] = 0
                location = get_location_status()
                known = location["enabled"] and location["status"] in {"last_log_entry", "detected"}
                zone = location["zone"] if known else ""
                area_id = location.get("area_id", "") if known else ""
                at_start = _speedrun_start_zone(zone, area_id)
                segment = _speedrun_segment(zone, area_id) if at_start or clock["runSeconds"] else None
                speedrun.start_attempt(data, segment, at_start, clock["runSeconds"])
            clock.update(status="live", runStartedAt=now)
        state["speedrun"] = data
        _put_timer(state, clock)
        _write_state(state)
    return clock


def save_state(payload, *, keep_timer=False):
    saved = dict(payload)
    saved.pop("guideMode", None)
    saved.pop("guideBuild", None)
    saved.pop("atlasLocation", None)
    saved.pop("bossEncounter", None)
    saved.pop("speedrun", None)
    if "routeClues" in saved:
        saved["routeClues"] = custom_route_clues(saved["routeClues"])
    with STATE_LOCK:
        previous = load_guide_data(STATE_FILE)
        if keep_timer:
            _put_timer(saved, timer_snapshot(previous))
        if "speedrun" in previous:
            data = speedrun.read_speedrun(previous)
            if not keep_timer:
                data.pop("attempt", None)
            saved["speedrun"] = data
        with LOCATION_LOCK:
            live_zone = LOCATION["zone"] if LOCATION["enabled"] else ""
        if live_zone:
            progress = saved.get("progress")
            if not isinstance(progress, dict):
                progress = {}
                saved["progress"] = progress
            else:
                progress = dict(progress)
                saved["progress"] = progress
            progress["currentAct"] = live_zone
        _write_state(saved)


def load_location_config():
    defaults = {"enabled": True, "client_log_path": ""}
    try:
        values = json.loads(LOCATION_CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(values, dict):
            defaults["enabled"] = bool(values.get("enabled", defaults["enabled"]))
            defaults["client_log_path"] = str(values.get("client_log_path", "")).strip()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return defaults


LOCATION_CONFIG = load_location_config()
LOCATION = {
    "enabled": LOCATION_CONFIG["enabled"],
    "client_log_path": LOCATION_CONFIG["client_log_path"],
    "status": "searching",
    "zone": "",
    "message": "PoE2-Installationspfad wird gesucht.",
    "resolved_path": "",
    "last_log_time": "",
    "area_level": None,
    "character_level": None,
    "manual_level": None,
    "atlasLocation": {"kind": "", "entry": ""},
}


def get_location_config():
    with CONFIG_LOCK:
        return dict(LOCATION_CONFIG)


def set_location_config(payload):
    settings = {
        "enabled": bool(payload.get("enabled", True)),
        "client_log_path": str(payload.get("client_log_path", "")).strip().strip('"'),
    }
    temporary = LOCATION_CONFIG_FILE.with_suffix(".tmp")
    serialized = json.dumps(settings, ensure_ascii=False, indent=2)
    with CONFIG_LOCK, LOCATION_LOCK:
        temporary.write_text(serialized + "\n", encoding="utf-8")
        temporary.replace(LOCATION_CONFIG_FILE)
        LOCATION_CONFIG.clear()
        LOCATION_CONFIG.update(settings)
        LOCATION["enabled"] = settings["enabled"]
        LOCATION["client_log_path"] = settings["client_log_path"]
        LOCATION["status"] = "searching" if settings["enabled"] else "disabled"
        LOCATION["message"] = "Suche nach dem Spiel-Log." if settings["enabled"] else "Gebietserkennung ist ausgeschaltet."
        LOCATION["resolved_path"] = ""
        LOCATION["zone"] = ""
        LOCATION.update(last_log_time="", area_level=None, character_level=None)
        LOCATION["atlasLocation"] = {"kind": "", "entry": ""}


def set_manual_character_level(level):
    if level is not None and (type(level) is not int or not 1 <= level <= 100):
        raise ValueError("Level must be an integer from 1 to 100.")
    with LOCATION_LOCK:
        LOCATION["manual_level"] = level


def _steam_paths():
    paths = []
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            raw, _ = winreg.QueryValueEx(key, "SteamPath")
            winreg.CloseKey(key)
            if raw:
                paths.append(Path(str(raw).replace("/", "\\")))
        except (ImportError, OSError):
            pass
        program_files = os.environ.get("ProgramFiles(x86)")
        if program_files:
            paths.append(Path(program_files) / "Steam")
    else:
        home = Path.home()
        paths.extend([
            home / ".steam" / "steam",
            home / ".steam" / "root",
            home / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",  # Flatpak
            home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",  # Snap
        ])

    libraries = list(paths)
    for steam_path in paths:
        folders_file = steam_path / "steamapps" / "libraryfolders.vdf"
        try:
            contents = folders_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in re.findall(r'"path"\s+"([^"]+)"', contents):
            library_path = raw.replace("\\\\", "\\")
            libraries.append(Path(library_path))

    unique = []
    seen = set()
    for path in libraries:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def find_client_log(settings):
    if not settings.get("enabled", True):
        return None
    manual_value = settings.get("client_log_path", "")
    if manual_value:
        manual = Path(os.path.expandvars(manual_value)).expanduser()
        if manual.is_file():
            return manual

    candidates = []
    for library in _steam_paths():
        steamapps = library / "steamapps"
        manifest = steamapps / f"appmanifest_{STEAM_APP_ID}.acf"
        install_dir = "Path of Exile 2"
        try:
            contents = manifest.read_text(encoding="utf-8", errors="replace")
            match = re.search(r'"installdir"\s+"([^"]+)"', contents, re.IGNORECASE)
            if match:
                install_dir = match.group(1)
        except OSError:
            pass
        candidates.append(steamapps / "common" / install_dir / "logs" / "Client.txt")
        candidates.append(steamapps / "common" / "Path of Exile 2" / "logs" / "Client.txt")

    if sys.platform == "win32":
        for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
            root = os.environ.get(env_name)
            if root:
                candidates.append(Path(root) / "Grinding Gear Games" / "Path of Exile 2" / "logs" / "Client.txt")
    else:
        candidates.append(Path.home() / "Games" / "Path of Exile 2" / "logs" / "Client.txt")

    seen = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _read_client_events(lines, pending_area, previous, client_pid, character_level, *, area_events=None):
    latest = None
    endgame_entered = False
    character_updated = False
    session_changed = False
    for line in lines:
        client = CLIENT_MESSAGE.search(line)
        message = line
        if client:
            pid, message = client.groups()
            if pid != client_pid or SESSION_START.fullmatch(message):
                session_changed = session_changed or client_pid is not None
                client_pid = pid
                character_level = None
                pending_area = None
                latest = previous = AreaEvent("", "", "")
                endgame_entered = False
                character_updated = False
            level_up = LEVEL_UP.fullmatch(message)
            if level_up:
                level = int(level_up[2] or level_up[3])
                if 1 <= level <= 100:
                    character_level = level
                    character_updated = True
                continue
        generated = AREA_GENERATED.match(message)
        if generated:
            pending_area = (int(generated.group(1)), generated.group(2))
            continue
        if message.startswith("[ENGINE] Loading state active: FALSE"):
            pending_area = None
            continue
        entered = ENTERED_AREA.search(line)
        scene = SCENE_SOURCE.search(line)
        if entered:
            zone = entered.group(1).strip()
            if zone.endswith("."):
                zone = zone[:-1].rstrip()
            zone = LOCALIZED_AREAS.get(_zone_key(zone), zone)
        elif scene:
            zone = scene.group(1).strip()
            key = _zone_key(zone)
            if key in {"", "(null)", "(unknown)", "atlas"}:
                continue
            if pending_area:
                zone = CLIENT_AREA_IDS.get(pending_area[1], zone)
            zone = LOCALIZED_AREAS.get(_zone_key(zone), zone)
            key = _zone_key(zone)
            if pending_area is None and not hub_kind(zone) and key not in CAMPAIGN_ZONES and key not in MAP_SCENES and key not in BOSS_ARENAS and key != ENDGAME_HUB:
                continue
        else:
            continue
        if zone:
            timestamp = re.match(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", line)
            key = _zone_key(zone)
            same_zone = previous is not None and key == _zone_key(previous.zone)
            if key == ENDGAME_HUB:
                kind = "hub"
            elif BOSS_ARENAS.get(key, {}).get("phase") == "endgame":
                kind = "map"
            elif pending_area is not None:
                level, area_id = pending_area
                is_map = MAP_AREA_ID.fullmatch(area_id) or key in MAP_SCENES
                kind = "map" if level >= 65 and is_map else ""
            else:
                kind = previous.kind if same_zone else "map" if key in MAP_SCENES else ""
            if kind and (pending_area is not None or not same_zone):
                endgame_entered = True
            area_level = previous.level if same_zone and pending_area is None else None
            event_area_id = previous.area_id if same_zone and pending_area is None else ""
            if pending_area is not None:
                level, area_id = pending_area
                mapped = CLIENT_AREA_IDS.get(area_id)
                if (not mapped or _zone_key(mapped) == key) and 1 <= level <= 100:
                    area_level = level
                    event_area_id = area_id
            latest = previous = AreaEvent(zone, timestamp.group(1) if timestamp else "", kind, area_level, event_area_id)
            if area_events is not None:
                area_events.append(latest)
            pending_area = None
    return latest, pending_area, endgame_entered, client_pid, character_level, character_updated, session_changed


def _set_watched_location(settings, **values):
    with LOCATION_LOCK:
        if any(LOCATION[key] != value for key, value in settings.items()):
            return False
        LOCATION.update(values)
        return True


def _advance_speedrun(state, events, now):
    clock = timer_snapshot(state)
    if clock["status"] != "live" or not events:
        return
    data = speedrun.read_speedrun(state)
    attempt = data.get("attempt")
    if not attempt:
        # An older state file can contain a running clock without a recorded route.
        attempt = speedrun.start_attempt(data, None, False, clock["runSeconds"])
        attempt["eligible"] = False
    for event in events:
        when = speedrun.event_time(event.log_time, clock["runStartedAt"], now)
        if when is None:
            continue
        seconds = speedrun.elapsed(clock, when)
        if event.kind == "hub" and attempt["segment"] == speedrun.SEGMENTS[-1]:
            speedrun.finish(data, attempt, seconds, confirmed=True)
            _put_timer(state, {"status": "prep", "runStartedAt": None, "runSeconds": seconds})
            break
        if not event.kind and (segment := _speedrun_segment(event.zone, event.area_id)):
            speedrun.advance(data, attempt, segment, _speedrun_start_zone(event.zone, event.area_id), seconds)
    state["speedrun"] = data


def _record_zone(settings, path, event, status, endgame_entered, level_values, *, area_events=None):
    with STATE_LOCK:
        with LOCATION_LOCK:
            if any(LOCATION[key] != value for key, value in settings.items()) or LOCATION["resolved_path"] != str(path):
                return
            entry = uuid4().hex if endgame_entered else LOCATION["atlasLocation"]["entry"]
            LOCATION.update(
                status=status,
                zone=event.zone,
                area_id=event.area_id,
                last_log_time=event.log_time,
                area_level=event.level,
                **level_values,
                atlasLocation={"kind": event.kind, "entry": entry},
                message={
                    "detected": "Gebietswechsel automatisch erkannt.",
                    "last_log_entry": "Letzter Log-Ort; wird beim nächsten Gebietswechsel aktualisiert.",
                    "waiting": "Spiel-Log gefunden. Warte auf einen Gebietswechsel.",
                }[status],
            )
        if not event.zone:
            return
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return
        if not isinstance(state, dict):
            return
        progress = state.setdefault("progress", {})
        if not isinstance(progress, dict):
            progress = {}
            state["progress"] = progress
        progress["currentAct"] = event.zone
        _advance_speedrun(state, area_events, time.time())
        _write_state(state)


def _watch_client_log(stop):
    active_path = None
    offset = 0
    identity = None
    pending_line = b""
    pending_area = None
    previous = None
    client_pid = character_level = None
    while not stop.is_set():
        settings = get_location_config()
        if not settings.get("enabled", True):
            active_path = None
            _set_watched_location(settings, status="disabled", message="Gebietserkennung ist ausgeschaltet.", resolved_path="")
            stop.wait(1.5)
            continue

        path = find_client_log(settings)
        if path is None:
            active_path = None
            status = "manual_missing" if settings.get("client_log_path") else "not_found"
            message = "Der eingetragene Client.txt-Pfad wurde nicht gefunden." if status == "manual_missing" else "PoE2-Client.txt wurde nicht gefunden. Pfad eintragen oder PoE2-Installation prüfen."
            _set_watched_location(settings, status=status, message=message, resolved_path="", zone="", last_log_time="",
                                  atlasLocation={"kind": "", "entry": ""}, area_level=None, character_level=None)
            stop.wait(1)
            continue

        try:
            stat_result = path.stat()
            current_identity = (stat_result.st_dev, stat_result.st_ino)
            is_new_log = (
                path != active_path or current_identity != identity or stat_result.st_size < offset
                or get_location_status()["resolved_path"] != str(path)
            )
            if is_new_log:
                # An established log changed or was replaced. A manual level belongs to the previous session.
                clear_level = {"manual_level": None} if active_path is not None else {}
                active_path = path
                identity = current_identity
                offset = max(0, stat_result.st_size - 2 * 1024 * 1024)
                pending_line = b""
                pending_area = None
                previous = None
                client_pid = character_level = None
                if not _set_watched_location(
                    settings,
                    status="waiting",
                    resolved_path=str(path),
                    zone="",
                    last_log_time="",
                    area_level=None,
                    character_level=None,
                    **clear_level,
                    atlasLocation={"kind": "", "entry": ""},
                    message="Spiel-Log gefunden. Warte auf einen Gebietswechsel.",
                ):
                    active_path = None
                    continue
            with path.open("rb") as stream:
                stream.seek(offset)
                if is_new_log and offset:
                    stream.readline()
                appended = stream.read()
                offset = stream.tell()
            if appended:
                complete, _, pending_line = (pending_line + appended).rpartition(b"\n")
                lines = complete.decode("utf-8", errors="replace").splitlines()
                area_events = None if is_new_log else []
                latest, pending_area, endgame_entered, client_pid, character_level, level_updated, session_changed = (
                    _read_client_events(lines, pending_area, previous, client_pid, character_level, area_events=area_events)
                )
                level_values = {"character_level": character_level}
                if not is_new_log and (level_updated or session_changed):
                    level_values["manual_level"] = None
                if latest:
                    previous = latest
                    status = ("last_log_entry" if is_new_log else "detected") if latest.zone else "waiting"
                    should_switch = bool(latest.kind) if is_new_log else endgame_entered
                    _record_zone(settings, path, latest, status, should_switch, level_values, area_events=area_events)
                elif level_updated:
                    _set_watched_location(settings, **level_values)
        except OSError:
            active_path = None
            _set_watched_location(settings, status="read_error", message="Auf Client.txt konnte nicht zugegriffen werden.",
                                  resolved_path="", zone="", last_log_time="", atlasLocation={"kind": "", "entry": ""},
                                  area_level=None, character_level=None)
        stop.wait(.7)


def get_location_status():
    with LOCATION_LOCK:
        return dict(LOCATION)


def character_name(state):
    meta = state.get("meta")
    name = meta.get("character") if isinstance(meta, dict) else None
    return name.strip()[:80] if isinstance(name, str) else ""


def checklist_snapshot(state=None):
    return CHECKLISTS.get(character_name(load_state() if state is None else state))


def change_checklist(payload):
    with STATE_LOCK:
        return CHECKLISTS.update(character_name(load_guide_data(STATE_FILE)), payload)


def _finite(value, low, high, *, whole=False):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Ungültiger Run-Wert.")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high or (whole and not number.is_integer()):
        raise ValueError("Ungültiger Run-Wert.")
    return int(number) if whole else number


def _text(value, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Text erwartet.")
    return value.strip()[:limit]


def edit_progress(payload):
    with STATE_LOCK:
        state = load_guide_data(STATE_FILE)
        meta, progress = state.setdefault("meta", {}), state.setdefault("progress", {})
        for key, limit in (("character", 80), ("mode", 60)):
            if key in payload:
                meta[key] = _text(payload[key], limit)
        if "nextAction" in payload:
            progress["nextAction"] = _text(payload["nextAction"], 500)
        for key, ranges in {"level": (1, 100, True), "xpPercent": (0, 100, False),
                            "deaths": (0, 100000, True), "mapTier": (1, 20, True)}.items():
            if key in payload:
                a, b, whole = ranges
                progress[key] = _finite(payload[key], a, b, whole=whole)
        if "runSeconds" in payload and timer_snapshot(state)["status"] != "live":
            progress["runSeconds"] = _finite(payload["runSeconds"], 0, 10_000_000)
        with LOCATION_LOCK:
            live_zone = LOCATION["zone"] if LOCATION["enabled"] else ""
        if "currentAct" in payload or live_zone:
            progress["currentAct"] = live_zone or _text(payload["currentAct"], 160)
        meta["lastSaved"] = int(time.time())
        _write_state(state)


def record_split(payload):
    ident = _text(payload.get("checkpointId"), 100)
    with STATE_LOCK:
        state = load_guide_data(STATE_FILE)
        if not any(item["id"] == ident for item in state.get("checkpoints", [])):
            raise ValueError("Checkpoint unbekannt.")
        clock = timer_snapshot(state)
        seconds = _finite(payload.get("seconds"), 0, 10_000_000)
        if seconds is None:
            seconds = clock["runSeconds"]
            if clock["status"] == "live":
                seconds += max(0, time.time() - clock["runStartedAt"])
        progress = state.get("progress", {})
        row = {"checkpointId": ident, "seconds": round(seconds, 2),
               "level": _finite(payload.get("level", progress.get("level")), 1, 100, whole=True),
               "deaths": _finite(payload.get("deaths", progress.get("deaths")), 0, 100000, whole=True),
               "note": _text(payload.get("note"), 500), "created": datetime.now(timezone.utc).isoformat()}
        state.setdefault("checkpointRuns", []).append(row)
        _write_state(state)
        return row


class RaceHandler(BaseHTTPRequestHandler):
    server_version = SERVER_NAME

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path or "/"
        if path == "/api/build":
            self.send_json({"name": APP_NAME, "build": BUILD, "version": BUILD_LABEL})
            return
        if path == "/api/shared-data":
            name = parse_qs(urlparse(self.path).query).get("file", [""])[0]
            try:
                self.send_json(SHARED.export(name))
            except (ValueError,OSError) as error:
                self.send_json({"error":str(error)},400)
            return
        if path == "/api/state":
            self.send_json(load_state())
            return
        if path == "/api/session":
            state = load_state()
            location = get_location_status()
            summary = {key: location[key] for key in ("enabled", "zone", "status", "last_log_time", "atlasLocation", "client_log_path")}
            self.send_json({"state": state, "location": summary, "timer": timer_snapshot(state),
                            "checklist": checklist_snapshot(state)})
            return
        if path == "/api/checklist":
            self.send_json(checklist_snapshot())
            return
        if path == "/api/location":
            self.send_json({**get_location_status(), **guide_preferences()})
            return
        if path == "/api/timer":
            with STATE_LOCK:
                clock = timer_snapshot(load_guide_data(STATE_FILE))
            self.send_json(clock)
            return
        if path == "/api/guide-mode":
            self.send_json({"mode": load_guide_mode()})
            return

        relative = path.lstrip("/")
        file_path = (WEB_DIR / relative).resolve()
        if path == "/race-overlay.html":
            file_path = WEB_DIR / "overlay.html"
        elif path == "/overlay.html":
            file_path = BASE_DIR / "poe2_obs_overlay.html"
        elif relative in WEB_IMAGES and file_path == WEB_DIR / relative:
            pass
        elif relative in WEB_FILES or file_path.parent != WEB_DIR or not file_path.is_file():
            file_path = (BASE_DIR / relative).resolve()
            is_asset = file_path.parent == BASE_DIR / "assets" and file_path.suffix in {".png", ".webp"}
            if not is_asset and relative not in WEB_FILES:
                self.send_error(404, "File not found")
                return

        try:
            data = file_path.read_bytes()
            if relative in SHARED_RESOURCES:
                data = json.dumps(project(relative,json.loads(data)),ensure_ascii=False).encode("utf-8")
        except OSError:
            self.send_error(404, "File not found")
            return

        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        request = urlparse(self.path)
        path = request.path
        writes = {"/api/checklist", "/api/progress", "/api/split", "/api/timer", "/api/guide-mode",
                  "/api/guide-build", "/api/location", "/api/state", "/api/shared-data"}
        if path not in writes:
            self.send_error(404, "Unknown endpoint")
            return
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.send_error(403)
            return
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
            self.send_error(403)
            return
        if path == "/api/shared-data":
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            if origin not in (None, f"http://{host}") or self.headers.get_content_type() != "application/json":
                self.send_error(403)
                return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= (SHARED_LIMIT + 4096 if path == "/api/shared-data" else 5 * 1024 * 1024):
                raise ValueError("Ungültige Datengröße.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Eingabe muss ein JSON-Objekt sein.")
            if path == "/api/shared-data":
                name=payload.get("file")
                if name not in SHARED_FILES:
                    raise ValueError("Unbekannte Austauschdatei.")
                if "revision" in payload and not isinstance(payload["revision"],str):
                    raise ValueError("Ungültige Vorschau.")
                self.send_json(SHARED.transfer(name, payload.get("document"), payload.get("revision")))
            elif path == "/api/checklist":
                self.send_json(change_checklist(payload))
            elif path == "/api/progress":
                edit_progress(payload)
                self.send_json({"ok": True})
            elif path == "/api/split":
                self.send_json(record_split(payload))
            elif path == "/api/timer":
                self.send_json(run_timer(payload.get("action")))
            elif path in ("/api/guide-mode", "/api/guide-build"):
                key = path.rsplit("-", 1)[-1]
                self.send_json({key: save_guide_setting(key, payload.get(key))})
            elif path == "/api/location":
                set_location_config(payload)
                self.send_json({"ok": True, "location": get_location_status()})
            else:
                for key in ("meta", "progress"):
                    if not isinstance(payload.setdefault(key, {}), dict):
                        raise ValueError(f"{key} muss ein JSON-Objekt sein.")
                payload["meta"]["lastSaved"] = int(time.time())
                save_state(payload, keep_timer=parse_qs(request.query).get("restore_timer") != ["1"])
                self.send_json({"ok": True})
        except (TypeError, ValueError, OSError) as error:
            self.send_json({"ok": False, "error": str(error)}, 400)

    def log_message(self, format_string, *args):
        logging.debug(format_string, *args)


def configure_storage(directory):
    global STATE_FILE, GUIDE_CONFIG_FILE, LOCATION_CONFIG_FILE
    directory.mkdir(parents=True, exist_ok=True)
    STATE_FILE = directory / STATE_FILE.name
    GUIDE_CONFIG_FILE = directory / GUIDE_CONFIG_FILE.name
    LOCATION_CONFIG_FILE = directory / LOCATION_CONFIG_FILE.name
    CHECKLISTS.configure(directory)
    if not STATE_FILE.exists():
        STATE_FILE.write_bytes((BASE_DIR / STATE_FILE.name).read_bytes())
    settings = load_location_config()
    with CONFIG_LOCK, LOCATION_LOCK:
        LOCATION_CONFIG.update(settings)
        LOCATION.update(settings, manual_level=None)


class GuideServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def start(self):
        self.stop_watch = threading.Event()
        self.watcher = threading.Thread(target=_watch_client_log, args=(self.stop_watch,), daemon=True)
        self.worker = threading.Thread(target=self.serve_forever, daemon=True)
        self.watcher.start()
        self.worker.start()

    def stop(self):
        if hasattr(self, "worker"):
            self.stop_watch.set()
            self.shutdown()
            self.watcher.join(timeout=2)
        self.server_close()


def start_local_server(directory, port=PORT, *, allow_alternate_port=False):
    try:
        http = GuideServer(("127.0.0.1", port), RaceHandler)
    except OSError as error:
        if not allow_alternate_port or not port or (
            error.errno not in (errno.EADDRINUSE, 10013, 10048)
            and getattr(error, "winerror", None) not in (10013, 10048)
        ):
            raise
        http = GuideServer(("127.0.0.1", 0), RaceHandler)
        logging.info("Port %s ist belegt. Der Guide nutzt Port %s.", port, http.server_port)
    try:
        configure_storage(directory)
        http.start()
    except BaseException:
        http.server_close()
        raise
    return http


if __name__ == "__main__":
    http = start_local_server(BASE_DIR, allow_alternate_port=True)
    print(f"PoE2 Ingame Guide läuft auf http://127.0.0.1:{http.server_port}/race-overlay.html")
    try:
        http.worker.join()
    except KeyboardInterrupt:
        pass
    finally:
        http.stop()
