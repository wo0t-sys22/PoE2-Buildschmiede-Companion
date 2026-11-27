"""Link to the Buildschmiede feedback form in the active language."""

from urllib.parse import urlencode

from poe2_overlay_version import VERSION


def feedback_url(language):
    query = urlencode({"sprache": language, "quelle": "companion", "version": VERSION})
    return f"https://buildschmiede.de/feedback/?{query}"
