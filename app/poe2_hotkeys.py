"""Guide shortcut names and parsing of the configurable timer keys.

Platform neutral: the parsed bindings use the Windows modifier flags and
virtual-key codes, which a future non-Windows backend translates itself.
"""

from __future__ import annotations

import re


HUD_HOTKEYS = {1: ("HUD anzeigen / verbergen", "F8"), 2: ("HUD bearbeiten", "F9"),
               3: ("Overlay beenden", "F10"), 4: ("Bedienung zurückholen", "Strg+Umschalt+F9"),
               5: ("Start / Pause / Weiter", "F6"), 6: ("Timer zurücksetzen", "F7"),
                 7: ("Boss-Zeit Start / Stopp", "F4")}


def timer_bindings(values, translate=str):
    bindings = {}
    used = set()
    modifiers = {"ALT": 1, "CTRL": 2, "STRG": 2, "SHIFT": 4, "UMSCHALT": 4, "WIN": 8}
    for action in HUD_HOTKEYS:
        text = values.get(action, "").strip().upper()
        if not text:
            continue
        *prefix, name = [piece.strip() for piece in text.split("+")]
        if any(piece not in modifiers for piece in prefix):
            raise ValueError(translate("Unbekannte Kombination: {key}").format(key=text))
        flags = 0
        for piece in prefix:
            flags |= modifiers[piece]
        if re.fullmatch(r"F(?:[1-9]|1[0-9]|2[0-4])", name):
            key = 0x6F + int(name[1:])
        elif flags and re.fullmatch(r"[A-Z0-9]", name):
            key = ord(name)
        else:
            raise ValueError(translate("Ungültige Taste {key}. Nutze z. B. F6 oder Strg+Alt+R.").format(key=text))
        binding = flags, key
        if binding in used:
            raise ValueError(translate("{key} ist im Guide bereits belegt.").format(key=text))
        used.add(binding)
        bindings[action] = binding
    return bindings
