"""Shared localized descriptions and practice notes for Lexicon details and previews."""

from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import re

from poe2_lexicon import GERMAN_ITEM_TYPES, catalogue, lexicon_practice, lexicon_prose


# Whole phrases only: translate game vocabulary while leaving the German sentence intact.
HYBRID_TERMS = {
    "Sphäre der Umwandlung": "Orb of Transmutation", "Sphäre der Verstärkung": "Orb of Augmentation",
    "Sphäre der Möglichkeiten": "Orb of Chance", "Sphäre der Extraktion": "Orb of Extraction",
    "Sphäre der Auslöschung": "Orb of Annulment", "Vaal-Sphäre": "Vaal Orb",
    "Königliche Sphäre": "Regal Orb", "Göttliche Sphäre": "Divine Orb", "Erhabene Sphäre": "Exalted Orb",
    "Chaossphäre": "Chaos Orb", "Handwerkersphäre": "Artificer's Orb",
    "Hinekoras Schloss": "Hinekora's Lock", "Spiegel von Kalandra": "Mirror of Kalandra",
    "Perfekte Essenz": "Perfect Essence", "Korrumpierte Essenz": "Corrupted Essence",
    "Brennenden Monolithen": "Burning Monolith", "Brennende Monolith": "Burning Monolith",
    "Eiserne Zitadelle": "Iron Citadel", "Eisernen Zitadelle": "Iron Citadel",
    "Kupferne Zitadelle": "Copper Citadel", "Kupfernen Zitadelle": "Copper Citadel",
    "Steinerne Zitadelle": "Stone Citadel", "Steinernen Zitadelle": "Stone Citadel",
    "Brunnen der Seelen": "Well of Souls", "Prüfung der Sekhemas": "Trial of the Sekhemas",
    "Prüfung des Chaos": "Trial of Chaos", "Verwertungsbank": "Salvage Bench",
    "Währungstausch": "Currency Exchange", "Kartenapparat": "Map Device",
    "Waffenset-Passivpunkte": "Weapon Set Passive Points", "Waffenset I": "Weapon Set I",
    "Waffenset II": "Weapon Set II", "Gegenstandsstufe": "Item Level", "Gemmenstufe": "Gem Level",
    "Augmentationssockel": "Augment Socket", "Augmentationsfassung": "Augment Socket",
    "Unterstützungssockel": "Support Socket",
    "Unterstützungsgemmen": "Support Gems", "Unterstützungsgemme": "Support Gem",
    "Fertigkeitsgemme": "Skill Gem", "Fertigkeitsgemmen": "Skill Gems",
    "Entweihter Modifikator": "Desecrated Modifier", "entweihten Modifikator": "Desecrated Modifier",
    "Seelenkerne": "Soul Cores", "Seelenkern": "Soul Core", "Wegsteine": "Waystones", "Wegstein": "Waystone",
    "Sturmglocke": "Tempest Bell", "Wirbelnder Schlag": "Whirling Slash", "Wirbelnden Schlag": "Whirling Slash",
    "Unterstützendes Feuer": "Supporting Fire", "Unterstützungsfeuer": "Supporting Fire",
    "Energie-Ladungen": "Power Charges", "Energie-Ladung": "Power Charge",
    "Raserei-Ladungen": "Frenzy Charges", "Raserei-Ladung": "Frenzy Charge",
    "Widerstands-Ladungen": "Endurance Charges", "Widerstands-Ladung": "Endurance Charge",
    "Energieschild": "Energy Shield", "Ehrenwiderstand": "Honour Resistance",
    "Rüstungsbruch": "Armour Break", "vollständig gebrochene Rüstung": "Fully Broken Armour",
    "Kältewiderstand": "Cold Resistance", "Blitzwiderstand": "Lightning Resistance",
    "Feuerwiderstand": "Fire Resistance", "Chaoswiderstand": "Chaos Resistance",
    "Elementarwiderstände": "Elemental Resistances", "Elementarresistenzen": "Elemental Resistances",
    "Bewegungsgeschwindigkeit": "Movement Speed", "Zaubergeschwindigkeit": "Cast Speed",
    "Angriffsgeschwindigkeit": "Attack Speed", "Treffgenauigkeit": "Accuracy",
    "Abklingzeiterholung": "Cooldown Recovery", "Abklingzeit": "Cooldown",
    "Lebensraub": "Life Leech", "Manaraub": "Mana Leech", "Wirkungsbereich": "Area of Effect",
    "Chaos-Schaden über Zeit": "Chaos Damage over Time", "Schaden über Zeit": "Damage over Time",
    "Elektrokution": "Electrocution", "Unterkühlen": "Chill", "Aszendenzpunkte": "Ascendancy Points",
    "Aszendenz": "Ascendancy", "Phiolen": "Charms", "Phiole": "Charm",
    "Entweihung": "Desecration", "Rüstungsspalter": "Armour Break", "verbundenen Bonus": "Bonded-Bonus",
    "Ursprungsturm": "Origin Tower", "Kern des Ursprungs": "Origin Core",
    "Wiege des Ursprungs": "Origin Cradle", "Funken des Ursprungs": "Origin Spark",
    "Gefallenen Stern": "Fallen Star", "Verisium-Amboss": "Verisium Anvil",
    "Verdorrten Weide": "Withered Willow", "Simulakrum-Splitter": "Simulacrum Splinters",
    "Simulakrum": "Simulacrum", "Genesis-Baum": "Genesis Tree", "Uralte Augmentation": "Ancient Augment",
    "Wille": "Spirit", "Einflößung": "Instilling", "Vorzeichen": "Omen",
    "Präfixe": "Prefixes", "Präfix": "Prefix", "Suffixe": "Suffixes", "Suffix": "Suffix",
}
_MARKUP = re.compile(r"\[([^\[\]\n]+)\|([^\[\]\n]+)\]")


@lru_cache(maxsize=1)
def _hybrid_vocabulary():
    data = catalogue()
    candidates = defaultdict(set)
    records = (*currencies().values(), *data["skills"].values(), *data["supports"].values())
    for row in records:
        original, german = row["name"], row.get("de") or ""
        if row.get("referenceOnly") or not german or original.casefold() == german.casefold():
            continue
        if " " in german or german.casefold().endswith(("rune", "sphäre", "gemme", "seelenkern")):
            candidates[german.casefold()].add(original)
    table = {k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}
    table.update((k.casefold(), v) for k, v in HYBRID_TERMS.items())
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(map(re.escape, sorted(table, key=len, reverse=True))) + r")(?!\w)",
        re.IGNORECASE,
    )
    return table, pattern


def localized_copy(values, language):
    value = lexicon_prose(values, language).replace(r"\n", "\n").strip()
    value = _MARKUP.sub(r"\2", value)
    if value and language == "hybrid":
        table, pattern = _hybrid_vocabulary()
        value = pattern.sub(lambda match: table.get(match[0].casefold(), match[0]), value)
    return value


def line(de, en, language):
    return localized_copy({"de": de, "en": en}, language)


@lru_cache(maxsize=1)
def currencies():
    return {r["currencyId"]: r for r in catalogue()["items"] if r.get("kind") == "currency"}


@lru_cache(maxsize=1)
def currency_names():
    return {r["name"].casefold(): r for r in currencies().values()}


@lru_cache(maxsize=1)
def augments():
    result = json.loads(Path(__file__).with_name("poe2_lexicon_augments.json").read_text(encoding="utf-8"))
    for ident, row in currencies().items():
        if "socketEffects" in row:
            result[ident] = row["socketEffects"]
    return result


CURRENCY_RULES = {
    "Runes": ("Diese Rune belegt eine Augmentationsfassung. Ihr Effekt hängt vom Zielgegenstand ab.",
              "This rune fills an augment socket. The effect depends on the item it goes into.",
              "Vergleiche den Effekt für deinen Slot. Auf Rüstung kann dieselbe Rune eine andere Aufgabe haben als in der Waffe. Prüfe auch den verbundenen Bonus.",
              "Compare the effect for your slot. The same rune can serve a different purpose on armour and on a weapon. Check the Bonded bonus as well."),
    "Soul Cores": ("Ein Seelenkern ist eine Einlage für die angegebene Ausrüstungsklasse.",
                   "A Soul Core is an augment for the item classes it lists.",
                   "Prüfe den Effekt für das konkrete Ausrüstungsteil und ob die Einlage fassungsgebunden ist. Plane den Gewinn gegenüber einer Rune, die du dafür ersetzen würdest.",
                   "Check the effect for the intended item and whether the augment is socket-bound. Compare it with the rune you would replace."),
    "Idols": ("Dieses Idol gehört zu den Augmentationen.",
              "This Idol belongs to the augment catalogue.",
              "Prüfe die konkrete Gegenstandsklasse und ob der Effekt zu deinem Build passt. Halte den vorgesehenen Platz für den Vergleich mit Rune oder Seelenkern frei.",
              "Check the required equipment class and whether its effect fits your build. Keep the slot open while comparing it with a rune or Soul Core."),
    "Essences": ("Diese Essenz garantiert einen bestimmten Modifikator auf einem geeigneten Gegenstand.",
                 "This Essence guarantees a specific modifier on an eligible item.",
                 "Suche die Zielklasse in der Effektliste. Normale Essenzen bauen geeignete magische Gegenstände aus; bei Perfekten oder Korrumpierten Essenzen kann ein vorhandener Wert verloren gehen.",
                 "Find your item class in the effect list. Ordinary Essences upgrade eligible magic gear; Perfect or Corrupted Essences can remove an existing modifier."),
    "Uncut Gems": ("Eine ungeschnittene Gemme wird im Gravurfenster in eine nutzbare Gemme umgesetzt.",
                   "An uncut gem is used in the engraving screen to make a usable gem.",
                   "Prüfe im Gravurfenster Stufe und Auswahl. Vergleiche die Anforderungen des gewünschten Skills mit deiner Ausrüstung, bevor du die Gemme verbrauchst.",
                   "Check the grade and selection in the engraving screen. Compare the intended skill's requirements with your gear before spending the gem."),
    "Abyss": ("Dieser Gegenstand ist dem Abgrund zugeordnet.", "This item is associated with Abyss.",
              "Plane Entweihung und Entschleierung zusammen. Bei einem Knochen zählt zuerst die zulässige Gegenstandsklasse, bei einem Vorzeichen der genaue Auslöser.",
              "Plan Desecration and the reveal together. For a bone, start with the eligible item class; for an Omen, start with the exact trigger."),
    "Expedition": ("Dieser Gegenstand gehört zur Expedition.", "This item belongs to Expedition.",
                   "Prüfe, ob er Ausrüstung verändert, eine Begegnung vorbereitet oder als Material dient. Bei einem Craft mit zufälliger Entfernung bewerte zuerst die Werte, die verloren gehen dürfen.",
                   "Check whether it alters gear, prepares an encounter or serves as a material. For a craft with random removal, first identify which rolls you can afford to lose."),
    "Ritual": ("Dieser Gegenstand gehört zum Ritual.", "This item belongs to Ritual.",
               "Bei einer Belohnung im Ritual prüfe den Tribut vor einem Neuwurf. Stelle einen wichtigen Fund bei Bedarf zurück, wenn diese Möglichkeit angeboten wird.",
               "For a reward offered in Ritual, check your Tribute before rerolling. If deferral is available, use it to preserve an important reward you cannot yet afford."),
    "Delirium": ("Dieser Gegenstand gehört zum Delirium.", "This item belongs to Delirium.",
                 "Vergleiche vor dem Einsatz das angegebene Ziel. Die Einflößung am Amulett und ein Craft an einem Juwel nutzen verschiedene Gegenstände.",
                 "Check the listed target before spending it. Instilling an amulet and crafting a jewel use different items."),
    "Breach": ("Dieser Gegenstand gehört zum Riss.", "This item belongs to Breach.",
               "Prüfe im Atlas und am Genesis-Baum, welcher Gegenstand für den nächsten Schritt gebraucht wird. Ein Zwischenmaterial ist noch kein direkter Begegnungszugang.",
               "Check the Atlas and Genesis Tree for the next component. An intermediate material does not open the encounter directly."),
    "Atziri's Temple": ("Dieser Gegenstand gehört zu Atziris Tempel.", "This item belongs to Atziri's Temple.",
                        "Lies vor dem Einsatz den genauen Zieltyp und ob Korruption oder Zerstörung möglich ist. Setze bei einem riskanten Schritt eine entbehrliche Basis ein.",
                        "Read the exact target and whether corruption or destruction is possible. Use an expendable base for a risky step."),
    "Fragments": ("Ein Fragment oder Schlüssel im Endspielkatalog.", "A fragment or key in the endgame catalogue.",
                  "Gleiche den Namen mit dem verlangten Zugang im Atlas oder am Begegnungseingang ab. Verbrauche ihn erst, wenn du den zugehörigen Versuch spielen möchtest.",
                  "Match its name to the entry requirement on the Atlas or at the encounter. Spend it when you are ready to attempt the associated content."),
}


def currency_copy(row, language):
    shared_summary=lexicon_prose(row.get("summary"),language)
    shared_practice=row.get("practice",{}).get(language)
    if shared_summary and isinstance(shared_practice,list):
        return shared_summary,tuple(shared_practice)
    note = lexicon_practice()["currency"].get(row["currencyId"], {})
    description = localized_copy(row.get("description"), language) or localized_copy(note.get("summary"), language)
    family = row.get("currencyFamily")
    if row.get("referenceOnly"):
        summary = ("Dieser Gegenstand ist in den Referenzdaten erfasst. Seine Verfügbarkeit im aktuellen Spiel ist offen.",
                   "This item is recorded in reference data. Its availability in the current game is unconfirmed.")
        practice = ("Prüfe die Verfügbarkeit vor der Planung eines Builds oder Crafts. Ein Eintrag im Katalog belegt keinen Fundort.",
                    "Confirm availability before planning a build or craft. A catalogue entry does not establish a drop source.")
    elif family in CURRENCY_RULES:
        de, en, tip_de, tip_en = CURRENCY_RULES[family]
        summary, practice = (de, en), (tip_de, tip_en)
    else:
        summary = ("Eine Währung aus dem Gegenstandskatalog von Path of Exile 2.", "A currency item in the Path of Exile 2 item catalogue.")
        practice = ("Prüfe Seltenheit und Gegenstandsklasse des Ziels vor dem Verbrauch. Vergleiche das mögliche Ergebnis mit dem nächsten Schritt deines Crafts.",
                    "Before spending it, check the target's rarity and class. Compare the possible result with your next crafting step.")

    original = row.get("description", {}).get("en", "")
    if original.startswith("While this item is active") and not row.get("referenceOnly"):
        practice = ("Aktiviere das Vorzeichen im Inventar unmittelbar vor dem geplanten Auslöser. Prüfe vorher, welches Ereignis es verbraucht und welche Wirkung danach noch zufällig bleibt.",
                    "Activate the Omen in your inventory immediately before the intended trigger. Check what consumes it and which part of the result remains random.")
    text = tuple(localized_copy(p, language) for p in note.get("article", ())) or (line(*practice, language),)
    return description or line(*summary, language), text


NODE_RULES = {
    "skill": ("Eine aktive Fertigkeit. Die Detailwerte nennen Voraussetzungen und Spielwerte.",
              "An active skill. Its details list the requirements and game stats."),
    "support": ("Eine Unterstützungsgemme verändert eine kompatible Fertigkeit.",
                "A support gem changes a compatible skill.",
                "Vergleiche im Fertigkeitsfenster den unterstützten Skill vor und nach dem Einsetzen. Prüfe den Auslöser, die Kosten und ob der Effekt im Bosskampf verfügbar ist.",
                "Compare the supported skill before and after socketing. Check the trigger, costs and whether the effect is available in a boss fight."),
    "small": ("Ein kleiner Knoten im Passivbaum. Konkrete Effekte stehen in den Spielwerten, soweit sie erfasst sind.",
              "A small passive node. Its game stats list specific effects where recorded.",
              "Prüfe die Kosten des Pfads bis zum nächsten wichtigen Knoten. Ein kleiner Bonus kann den Weg sinnvoll machen, wenn er eine Anforderung abdeckt.",
              "Compare the points needed to reach the next important node. A small bonus can make the route worthwhile if it covers a requirement."),
    "notable": ("Eine bedeutende Fertigkeit im Passivbaum.", "A notable passive in the tree.",
                "Vergleiche die tatsächlich nutzbaren Werte mit den Punkten auf dem Weg dorthin. Berücksichtige Bedingungen wie verwendete Waffe oder aktiven Zustand.",
                "Compare the stats you can use with the passive points needed to reach them. Account for conditions such as the weapon used or an active state."),
    "keystone": ("Eine Schlüsselfertigkeit, die eine Spielregel verändert.", "A keystone that changes a game rule.",
                 "Lies den gesamten Effekt samt Einschränkung. Teste die Umstellung am vorgesehenen Setup, bevor du weitere Punkte oder Ausrüstung darauf festlegst.",
                 "Read the full effect and its restrictions. Test the change in the intended setup before spending more points or gearing around it."),
    "socket": ("Eine Fassung im Passivbaum für ein passendes Juwel.", "A passive tree socket for a compatible jewel.",
               "Vergleiche den Juwelenbonus mit den Punkten auf dem Weg zur Fassung. Bei einem Juwel mit Radius prüfe die Zielknoten in genau dieser Position.",
               "Compare the jewel's benefit with the points needed to reach the socket. If the jewel has a radius, inspect the nodes around that exact position."),
}


def node_copy(row, facet, ident, language):
    de, en, *practice = NODE_RULES[facet]
    description = localized_copy(row.get("description"), language) or line(de, en, language)
    note = lexicon_practice()["nodes"].get(ident, {})
    paragraphs = tuple(filter(None, (localized_copy(p, language) for p in note.get("article", ()))))
    if paragraphs or facet == "skill":
        return description, paragraphs
    tip_de, tip_en = practice
    if facet == "support" and "unused" in row.get("description", {}).get("en", "").casefold():
        tip_de = "Die Spielbarkeit dieses Datensatzes ist offen. Plane damit erst, wenn der Client die Gemme und einen nutzbaren Effekt anzeigt."
        tip_en = "Availability is unconfirmed. Plan around it only after the game client shows a usable gem and effect."
    elif facet in ("small", "notable"):
        effects = " ".join(row.get("stats", ())).casefold()
        if " recently" in effects or " while " in effects or " if you " in effects:
            tip_de = "Prüfe, wie oft die Bedingung in deiner Rotation tatsächlich erfüllt ist. Vergleiche den Knoten mit einem dauerhaft wirksamen Bonus, falls der Auslöser am Boss selten vorkommt."
            tip_en = "Check how often your rotation really meets the condition. Compare the node with an always-on bonus if the trigger rarely happens on bosses."
        elif "resistance" in effects:
            tip_de = "Prüfe den tatsächlichen Widerstand vor und nach der Verteilung. Wenn ein Ringtausch den Wert bereits abdeckt, können die Punkte eine andere Lücke im Build schließen."
            tip_en = "Check the actual resistance before and after allocation. If a ring swap covers it already, the points can solve another gap in the build."
        elif any(word in effects for word in ("strength", "dexterity", "intelligence", "all attributes")):
            tip_de = "Rechne die Anforderung deiner nächsten Gemmenstufe oder Ausrüstung mit ein. Prüfe nach einem Schmuckwechsel, ob du den Knoten dafür weiterhin brauchst."
            tip_en = "Account for the requirements of your next gem level or gear upgrade. After changing jewellery, check whether you still need the node."
    return description, (line(tip_de, tip_en, language),)


def entry_copy(entry, language):
    """A summary and any practical paragraphs for a visible Lexicon result."""
    target = entry.target
    group, row = target["group"], target.get("row", {})
    if group == "terms":
        summary = term_summary(row, language)
        paragraphs = tuple(filter(None, (localized_copy(p, language) for p in row.get("article", ()))))
        return summary, paragraphs or (line(
            "Prüfe, wo dir der Begriff im Spiel begegnet. Der zugehörige Gegenstand, Skill oder Gebietsabschnitt liefert den konkreten Kontext.",
            "Check where the term appears in game. The associated item, skill or area entry gives its concrete context.", language),)
    if group == "nodes":
        return node_copy(row, target["facet"], target["ident"], language)
    if group == "items":
        if target["facet"] == "currency":
            summary, paragraphs = currency_copy(row, language)
            article = target.get("article", {})
            notes = tuple(filter(None, (localized_copy(p, language) for p in article.get("article", ()))))
            return summary, paragraphs if language in row.get("practice",{}) else (notes or paragraphs)
        return item_copy(row, target["facet"], language)
    return modifier_copy(target, language)


def term_summary(row, language):
    if linked := currencies().get(row.get("currencyId")):
        if active := lexicon_prose(linked.get("summary"),language) or lexicon_prose(linked.get("description"),language):
            return active
    if tooltip := lexicon_prose(row.get("tooltipSummary"), language):
        return tooltip
    if row.get("topic") == "currency" and (item := currency_names().get(row["title"].get("en", "").casefold())):
        actual = localized_copy(item.get("description"), language)
        if actual:
            return actual
    return localized_copy(row.get("summary"), language) or line(
        "Ein Begriff aus dem Buildschmiede-Lexikon.", "A term from the Buildschmiede Lexicon.", language)


def item_copy(row, facet, language):
    kind = row.get("item", {}).get("type") or ""
    base_de = GERMAN_ITEM_TYPES.get(kind, "")
    if facet == "waystone":
        summary = (f"Wegstein der Stufe {row['mapTier']} für den Kartenapparat.",
                   f"Tier {row['mapTier']} Waystone for the Map Device.")
        tip = (f"Die erfasste Basis-Gebietsstufe ist {row['areaLevel']}. Prüfe am Atlas-Knoten das endgültige Level und die Modifikatoren vor dem Start.",
               f"The recorded base area level is {row['areaLevel']}. Check the final level and modifiers on the Atlas node before opening the map.")
    elif facet == "tablet":
        summary = ("Eine Tafel für den Einsatz am Kartenapparat.", "A tablet for use at the Map Device.")
        tip = ("Prüfe beim Einlegen, welche Begegnung und welche Modifikatoren für die Karte angezeigt werden. Wähle eine Kombination, die dein Build sicher abschließen kann.",
               "When inserting it, inspect the encounter and modifiers shown for the map. Choose a combination your build can reliably finish.")
    elif facet == "unique":
        summary = ("Ein einzigartiger Gegenstand mit eigenem Satz an Modifikatoren.",
                   "A unique item with its own set of modifiers.")
        tip = ("Vergleiche den besonderen Effekt und seine Auslöser mit deiner tatsächlichen Rotation. Prüfe beim Wechsel, welche Werte dein seltener Gegenstand bisher abgedeckt hat.",
               "Compare the special effect and its triggers with your actual rotation. Before swapping, check which stats your rare item currently covers.")
        if row.get("variants"):
            tip = ("Vergleiche vor dem Kauf die Variante am konkreten Angebot. Ein starker Wert im Katalog kann zu einer anderen Version desselben Gegenstands gehören.",
                   "Compare the actual listing before buying. A strong roll in the catalogue can belong to a different variant of the same item.")
    else:
        label = kind if language == "hybrid" else base_de
        summary = (f"Diese Ausrüstungsbasis gehört zur Kategorie {label}." if label else "Diese Ausrüstungsbasis hat eigene Grundwerte und Anforderungen.",
                   f"This equipment base belongs to the {kind} class." if kind else "This equipment base has its own base stats and requirements.")
        if kind in ("Amulet", "Ring", "Belt", "Quiver", "Jewel"):
            tip = ("Vergleiche den impliziten Wert mit einer anderen Basis im selben Slot. Wähle die Basis, deren Grundeffekt deine Ausrüstung ergänzt, bevor du explizite Affixe einplanst.",
                   "Compare its implicit with another base in the same slot. Choose a base whose natural property complements your gear before planning explicit affixes.")
        elif kind == "Flask" or kind == "Charm":
            tip = ("Vergleiche Ladungen, Verbrauch und Dauer. Prüfe in einem langen Einzelzielkampf, wie oft das Ausrüstungsteil tatsächlich einsatzbereit ist.",
                   "Compare charges, charge cost and duration. In a long single-target fight, check how often it is actually available.")
        elif row.get("type") in ("body", "helmet", "boots", "gloves", "shield", "focus"):
            tip = ("Vergleiche Grundverteidigung und Attributsanforderung vor dem Craft. Unter „Passende Affixe“ siehst du, welche Modifikatoren für diese Basis infrage kommen.",
                   "Compare base defences and attribute requirements before crafting. Applicable affixes shows which modifiers are available on this base.")
        else:
            tip = ("Prüfe die Waffenanforderung des genutzten Skills und vergleiche Schaden oder Zauberwerte mit deiner aktuellen Basis. Die Grundwerte wirken sich auf mehrere mögliche Crafts aus.",
                   "Check the weapon requirement of the skill you use and compare damage or caster stats with your current base. These base properties carry through to several possible crafts.")
    return localized_copy(row.get("description"), language) or line(*summary, language), (line(*tip, language),)


def modifier_copy(target, language):
    rows = target["rows"]
    if target["group"] == "pools":
        minimum = min(row[1] for row in rows)
        summary = (f"Dieser Eintrag aus der Modifikatorliste enthält {len(rows)} erfasste Variante(n) ab Gegenstandsstufe {minimum}.",
                   f"This mod pool entry has {len(rows)} recorded variant(s) from item level {minimum}.")
        practice = ("Prüfe die Gegenstandsstufe der gewünschten Variante. Das Rollgewicht hilft beim Vergleich innerhalb desselben Pools. Die Werte sind keine unmittelbaren Prozentchancen.",
                    "Check the item level of the desired variant. Roll weights help compare entries in the same pool. These numbers are not direct percentages.")
    else:
        minimum = min(row["level"] for row in rows)
        side = target["facet"]
        summary = ({"Prefix": "Präfix", "Suffix": "Suffix"}.get(side, "Modifikator") + f" mit erfassten Varianten ab Gegenstandsstufe {minimum}.",
                   (side if side != "Other" else "Modifier") + f" with recorded variants from item level {minimum}.")
        practice = ("Prüfe am Ziel den passenden freien Platz und ob die Stufe für deinen gewünschten Wurf reicht. Zwei Zahlenzeilen können zu demselben Affix gehören.",
                    "Check for the relevant open slot and whether the item level is high enough for the roll you want. Two stat lines can belong to one affix.") if side != "Other" else (
                    "Prüfe den angegebenen Ursprung. Ein impliziter, einzigartiger oder Begegnungsmodifikator kann besondere Bedingungen haben und ist nicht automatisch ein normaler Crafting-Wurf.",
                    "Check the listed source. An implicit, unique or encounter modifier can have special conditions and is not automatically available as an ordinary crafting roll.")
    return line(*summary, language), (line(*practice, language),)
