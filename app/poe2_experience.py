"""Labels and feature availability for the Companion's experience choices."""

EXPERIENCE_LEVELS = {
    "first_steps": (
        "Ich bin neu in PoE 2", "I’m new to PoE 2",
        "Kampagne, Gebietsauswahl und Tipps. Weniger Buttons, Menüs und Erklärungen machen den Einstieg leichter.",
        "Campaign, area selection and tips. Fewer buttons, menus and explanations make it easier to start.",
    ),
    "campaign": (
        "Die ersten Schritte sind mir vertraut.", "I know how to get started.",
        "Einstieg plus Builds, Boss-Guides, Lexikon, Atlas und Crafting. Guides starten ausführlich.",
        "Beginner features plus builds, boss guides, the lexicon, Atlas and crafting. Guides start in detailed view.",
    ),
    "maps": (
        "Ich kenne auch die tieferen Spielmechaniken.", "I know the deeper game mechanics too.",
        "Alle bisherigen Funktionen plus weitere Werkzeuge. Guides starten kompakt.",
        "Previous features plus more tools. Guides start in compact view.",
    ),
    "experimental": (
        "Ich öffne zuerst PoB und dann das Spiel.", "I open PoB before I launch the game.",
        "Experimentelle Funktionen und zusätzliche Optionen. Für den Einstieg derzeit nicht empfohlen.",
        "Experimental features and extra settings. Currently not recommended for new players.",
    ),
}

_RANK = {key: i for i, key in enumerate(EXPERIENCE_LEVELS)}
_FEATURES = {
    "campaign_tools": "campaign",
    "atlas": "campaign",
    "crafting": "campaign",
    "endgame": "maps",
    "timers": "maps",
    "experimental": "experimental",
}


def saved_experience(prefs):
    default = "maps" if prefs.get("welcome_setup_completed") is True else "first_steps"
    value = prefs.get("experience_level")
    return value if isinstance(value, str) and value in EXPERIENCE_LEVELS else default


def experience_allows(level, feature):
    return _RANK[level] >= _RANK[_FEATURES[feature]]


def default_guide_mode(level):
    return "veteran" if experience_allows(level, "endgame") else "basis"
