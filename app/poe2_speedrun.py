"""Local real-time campaign splits and personal bests for the six-act campaign."""

from datetime import datetime
from math import isfinite
import re


SEGMENTS = tuple(f"act{act}" for act in range(1, 7))
AREA_SEGMENT = re.compile(r"g([1-6])_", re.IGNORECASE)


def area_segment(area_id):
    match = AREA_SEGMENT.match(area_id)
    if match:
        return f"act{match[1]}"
    return None


def elapsed(clock, now):
    seconds = clock["runSeconds"]
    if clock["status"] == "live":
        seconds += max(0, now - clock["runStartedAt"])
    return seconds


def event_time(log_time, start, now):
    """Use the fresh Client.txt event time, at the log's one-second resolution."""
    try:
        timestamp = datetime.strptime(log_time, "%Y/%m/%d %H:%M:%S").timestamp()
    except (ValueError, OSError, OverflowError):
        return now
    if timestamp < int(start):
        return None
    return max(start, min(timestamp, now))


def _time(value):
    return value if type(value) in (int, float) and 0 <= value < 10**9 and isfinite(value) else None


def _splits(items):
    if not isinstance(items, dict):
        return {}
    return {key: {"seconds": item["seconds"], "total": item["total"]}
            for key, item in items.items() if key in SEGMENTS and isinstance(item, dict)
            and _time(item.get("seconds")) is not None and _time(item.get("total")) is not None}


def read_speedrun(state):
    """Read the optional extension to older race state files."""
    data = state.get("speedrun")
    if not isinstance(data, dict) or data.get("schema") != 1:
        return {"schema": 1, "bestSegments": {}}
    best = data.get("bestSegments")
    result = {"schema": 1, "bestSegments": {}}
    if isinstance(best, dict):
        result["bestSegments"] = {key: value for key, value in best.items()
                                  if key in SEGMENTS and _time(value) is not None}
    attempt = data.get("attempt")
    if isinstance(attempt, dict) and attempt.get("segment") in (*SEGMENTS, None):
        result["attempt"] = {"segment": attempt.get("segment"), "segmentStart": _time(attempt.get("segmentStart")) or 0,
                             "splits": _splits(attempt.get("splits")), "eligible": attempt.get("eligible") is True,
                             "finished": attempt.get("finished") is True}
    personal = data.get("personalBest")
    if isinstance(personal, dict) and _time(personal.get("total")) is not None:
        splits = _splits(personal.get("splits"))
        if splits.keys() == set(SEGMENTS):
            result["personalBest"] = {"total": personal["total"], "splits": splits}
    return result


def start_attempt(data, segment, at_start, seconds=0):
    attempt = {"segment": segment, "segmentStart": seconds, "splits": {},
               "eligible": seconds == 0 and (at_start or segment is None), "finished": False}
    data["attempt"] = attempt
    return attempt


def _complete_segment(data, attempt, seconds):
    segment = attempt["segment"]
    duration = round(seconds - attempt["segmentStart"], 2)
    if duration <= 0:
        attempt["eligible"] = False
        return
    attempt["splits"][segment] = {"seconds": duration, "total": round(seconds, 2)}
    if attempt["eligible"]:
        best = data["bestSegments"]
        best[segment] = min(duration, best.get(segment, duration))


def advance(data, attempt, segment, at_start, seconds):
    """Record each forward boundary once. Missing a boundary makes it a practice run."""
    current = attempt["segment"]
    if current is None:
        attempt["segment"] = segment
        if not at_start:
            attempt.update(eligible=False, segmentStart=seconds)
    elif SEGMENTS.index(segment) > SEGMENTS.index(current):
        if SEGMENTS.index(segment) == SEGMENTS.index(current) + 1:
            _complete_segment(data, attempt, seconds)
        else:
            attempt["eligible"] = False
        attempt.update(segment=segment, segmentStart=seconds)


def finish(data, attempt, seconds, *, confirmed):
    attempt["eligible"] = attempt["eligible"] and confirmed
    if attempt["segment"] is not None:
        _complete_segment(data, attempt, seconds)
    attempt["finished"] = True
    best = data.get("personalBest")
    if attempt["eligible"] and attempt["splits"].keys() == set(SEGMENTS):
        total = round(seconds, 2)
        if best is None or total < best["total"]:
            data["personalBest"] = {"total": total, "splits": dict(attempt["splits"])}


def snapshot(data, clock, now, *, auto_splits):
    attempt = data.get("attempt", {})
    personal = data.get("personalBest", {})
    best = data["bestSegments"]
    active = attempt.get("segment")
    seconds = elapsed(clock, now)
    status = "ready"
    if attempt.get("finished"):
        status = "finished"
    elif clock["status"] == "live":
        status = "running"
    elif attempt or seconds:
        status = "paused"
    rows = []
    last_delta = None
    for segment in SEGMENTS:
        row = {"id": segment, "status": "pending", "seconds": None, "total": None,
               "best": best.get(segment), "delta": None}
        split = attempt.get("splits", {}).get(segment)
        if split is not None:
            comparison = personal.get("splits", {}).get(segment)
            delta = round(split["total"] - comparison["total"], 2) if comparison else None
            row.update(split, status="done", delta=delta)
            last_delta = delta
        elif active == segment and status != "finished":
            row.update(status="active", seconds=max(0, seconds - attempt["segmentStart"]))
        rows.append(row)
    return {"status": status, "elapsed": seconds, "rows": rows, "personalBest": personal.get("total"),
            "sumOfBest": sum(best.values()) if best.keys() == set(SEGMENTS) else None,
            "eligible": attempt.get("eligible", True), "autoSplits": auto_splits,
            "canFinish": status in ("running", "paused"), "lastDelta": last_delta}
