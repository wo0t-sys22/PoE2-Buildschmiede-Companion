"""Build identification shared by the starter, overlay and local server."""

from contextlib import closing
from http.client import HTTPConnection, HTTPException
import json
import sys


APP_NAME = "PoE2 Ingame Guide"
BUILD = 227
INSTALLED_BUILD = getattr(sys, "frozen", False)
VERSION = "0.24.0"
BUILD_LABEL = f"v.{VERSION}"
SERVER_NAME = "PoE2RaceControl/1.0"


def running_guide_build(port):
    """Return a known Guide's build, 0 for the previous unversioned server."""
    try:
        with closing(HTTPConnection("127.0.0.1", port, timeout=.25)) as server:
            server.request("GET", "/api/build")
            response = server.getresponse()
            if response.getheader("Server", "").split(" ", 1)[0] != SERVER_NAME:
                return None
            if response.status == 404:
                return 0
            if response.status == 200:
                info = json.loads(response.read(4096))
                if isinstance(info, dict) and info.get("name") == APP_NAME and type(info.get("build")) is int:
                    return info["build"]
    except (OSError, HTTPException, ValueError):
        pass
    return None
