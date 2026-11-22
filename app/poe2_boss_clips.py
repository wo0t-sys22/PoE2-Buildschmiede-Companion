"""Download optional, language-independent Boss Guide clips."""

from contextlib import closing
from hashlib import sha256
from http.client import HTTPConnection, HTTPSConnection
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from poe2_website_content import API_BASE, ContentError, TIMEOUT, fetch


STAGING_API = "https://buildschmiede.de/grissom/index.php?rest_route=/buildschmiede/v1/companion"
SCHEMA = "buildschmiede.clips.v1"
CLIP_ID = re.compile(r"boss:[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*")
MAX_CLIP_BYTES = 128 * 1024 * 1024


def clip_id(boss, attack):
    return f"boss:{boss['id']}:{attack['id']}" if attack.get("id") else None


def validate_clips(data, base):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("clips"), list):
        raise ContentError("Ungültiges Clip-Verzeichnis.")
    source = data.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("revision"), str) or not source["revision"]:
        raise ContentError("Standskennung des Clip-Verzeichnisses fehlt.")
    origin = urlsplit(base)
    clips = {}
    for item in data["clips"]:
        if not isinstance(item, dict):
            raise ContentError("Ungültiger Clip-Eintrag.")
        key, act = item.get("id"), item.get("act")
        size, revision, address = item.get("bytes"), item.get("revision"), item.get("url")
        url = urlsplit(address) if isinstance(address, str) else urlsplit("")
        if (not isinstance(key, str) or not CLIP_ID.fullmatch(key) or key in clips
                or not isinstance(act, str) or not act or len(act) > 32
                or type(size) is not int or not 0 < size <= MAX_CLIP_BYTES
                or not isinstance(revision, str) or not revision or len(revision) > 128
                or url.scheme != origin.scheme or url.netloc != origin.netloc
                or url.username is not None or not url.path.lower().endswith(".mp4") or url.fragment
                or url.scheme not in {"https", "http"}
                or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1"})):
            raise ContentError("Ungültige Clip-ID, Dateigröße oder Medienadresse.")
        clips[key] = item
    return clips


def _download(item, target):
    url = urlsplit(item["url"])
    connection_type = HTTPSConnection if url.scheme == "https" else HTTPConnection
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with closing(connection_type(url.hostname, url.port, timeout=TIMEOUT)) as connection:
            path = url.path + ("?" + url.query if url.query else "")
            connection.request("GET", path, headers={"Accept": "video/mp4"})
            response = connection.getresponse()
            if response.status != 200:
                raise ContentError(f"HTTP {response.status}")
            remaining = item["bytes"]
            first = response.read(min(64 * 1024, remaining + 1))
            if first[4:8] != b"ftyp":
                raise ContentError("Antwort enthält keine MP4-Datei.")
            with NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
                temporary = Path(stream.name)
                chunk = first
                while chunk:
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ContentError("Die MP4-Datei ist größer als angekündigt.")
                    stream.write(chunk)
                    chunk = response.read(min(64 * 1024, remaining + 1))
            if remaining:
                raise ContentError("Die MP4-Datei wurde nicht vollständig geladen.")
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class BossClipStore:
    def __init__(self, directory, staging=False):
        self.folder = Path(directory) / "boss-clips" / ("staging" if staging else "website")
        self.base = os.environ.get("POE2_CLIPS_API") or (STAGING_API if staging else API_BASE)
        self.catalogue = {}
        try:
            self.catalogue = validate_clips(json.loads(self.index.read_text(encoding="utf-8")), self.base)
        except (OSError, ValueError):
            pass

    @property
    def index(self):
        return self.folder / "clips.json"

    def refresh(self):
        payload = fetch("clips", self.base.rstrip("/"))
        catalogue = validate_clips(payload, self.base)
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.folder, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False)
            temporary.replace(self.index)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.catalogue = catalogue

    def path(self, item):
        prefix = sha256(item["id"].encode()).hexdigest()[:20]
        revision = sha256(item["revision"].encode()).hexdigest()[:20]
        return self.folder / f"{prefix}-{revision}.mp4"

    def have(self, item):
        try:
            return self.path(item).stat().st_size == item["bytes"]
        except OSError:
            return False

    def playable(self, key):
        item = self.catalogue.get(key)
        current = self.path(item) if item else None
        if current and self.have(item):
            return current
        prefix = sha256(key.encode()).hexdigest()[:20]
        versions = (path for path in self.folder.glob(prefix + "-*.mp4") if path != current and path.is_file())
        return max(versions, default=None, key=lambda path: path.stat().st_mtime)

    def missing(self, act):
        return [item for item in self.catalogue.values() if item["act"] == act and not self.have(item)]

    def download(self, items):
        count = 0
        for item in items:
            if not self.have(item):
                _download(item, self.path(item))
                count += 1
        return count
