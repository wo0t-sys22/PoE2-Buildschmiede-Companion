"""Local WordPress/Companion exchange. Published JSON and personal run state live separately."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import RLock
import sys

from plattform import data_dir
from poe2_shared_catalogs import CATALOG_FILES, check_catalog_refs, merge_catalog, validate_catalog


APP = Path(__file__).resolve().parent
CAMPAIGN, BOSSES, TERMS = "campaign.live.v2.json", "bosses.json", "terms.json"
FILES = (CAMPAIGN, BOSSES, TERMS, *CATALOG_FILES)
LANGS = ("de", "hybrid", "en")
MODES = ("basis", "veteran")
MAX_BYTES = 16_000_000
LISTS = {CAMPAIGN: ("pages", "towns"), BOSSES: ("bosses",), TERMS: ()}
MAPS = {CAMPAIGN: ("terms",), BOSSES: ("languages", "sources"), TERMS: ("terms", "areaAliases")}
ROLES = set(json.loads((APP / "web/poe2_r18_guide.json").read_bytes())["palette"]) | {"blue", "gold", "info", "optional", "gameplay"}
STYLE = json.loads((APP / "web/companion-section-style.json").read_bytes())
HEADINGS = {key: heading for heading, key in STYLE["headings"].items()}
RETIRED_CHAPTER = re.compile(r"\b(?:interludes?|zwischenspiele?n?|zwischenakte?n?)\b", re.IGNORECASE)


def need(test, message):
    if not test:
        raise ValueError(message)


def records(rows, field="id"):
    need(isinstance(rows, list), "Eine Liste mit Datensätzen fehlt.")
    out = {}
    for row in rows:
        key = row.get(field) if isinstance(row, dict) else None
        need(isinstance(key, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,181}", key) and key not in out,
             f"Fehlende, ungültige oder doppelte ID: {key}")
        out[key] = row
    return out


def localized(value):
    return isinstance(value, dict) and all(isinstance(value.get(lang), str) for lang in LANGS)


def strings(value):
    return isinstance(value, list) and all(isinstance(s, str) for s in value)


def validate_term_refs(text, refs, terms, *, context=""):
    """Validate the author’s explicit choices against one localized line."""
    from poe2_r18_features import term_key, term_matches

    prefix = f"{context}: " if context else ""
    need(isinstance(refs, dict), prefix + "Ungültige Begriffsreferenzen.")
    for phrase, ident in refs.items():
        need(isinstance(phrase, str) and bool(phrase.strip()), prefix + "Leere Begriffsreferenz.")
        need(isinstance(ident, str) and ident in terms,
             f"{prefix}Unbekannte Begriffs-ID {ident!r} für {phrase!r}.")
    aliases = {term_key(phrase): ident for phrase, ident in refs.items()}
    matched = {text[start:end]: ident for start, end, ident in term_matches(text, aliases)}
    for phrase, ident in refs.items():
        need(matched.get(phrase) == ident,
             f"{prefix}{phrase!r} muss eine ganze, nicht überlappende Textstelle markieren.")


def campaign_term_ref_fields(pages):
    for page in pages:
        for mode in MODES:
            for section in page["layouts"][mode]:
                for row in section["rows"]:
                    for lang, refs in row.get("termRefs", {}).items():
                        yield (page["id"], mode, section["id"], row["id"], lang), (row["text"][lang], refs)


def validate(name, doc):
    need(name in FILES and isinstance(doc, dict), "Unbekannter Dateityp.")
    if name in CATALOG_FILES:
        validate_catalog(name,doc)
        return
    for field in MAPS[name]:
        need(isinstance(doc.get(field), dict), f"Objekt erwartet: {field}.")
    for field in LISTS[name]:
        records(doc.get(field))
    if name == TERMS:
        need(type(doc.get("schemaVersion")) is int and doc["schemaVersion"] == 1, "terms.json Version 1 erwartet.")
        for key, term in doc["terms"].items():
            need(isinstance(term, dict) and term.get("role") in ROLES, f"Ungültige Farbrolle: {key}")
            for field in ("aliases", "routeAliases"):
                need(strings(term.get(field, [])), f"Ungültige Aliasse: {key}")
            if "labels" in term:
                need(localized(term["labels"]), f"Übersetzungen fehlen: {key}")
            need(isinstance(term.get("templateLabels", {}), dict) and
                 all(localized(v) for v in term.get("templateLabels", {}).values()), f"Ungültige Vorlage: {key}")
            if "templateKey" in term:
                need(isinstance(term["templateKey"], str) and localized(term.get("labels")), f"Vorlage fehlt: {key}")
        for key, aliases in doc["areaAliases"].items():
            need(isinstance(aliases, dict) and all(isinstance(v, str) for v in aliases.values()), f"Gebietsaliase: {key}")
    elif name == BOSSES:
        need(doc.get("schema") == "buildschmiede.bosses.v1", "Bosskatalog v1 erwartet.")
        for boss in doc["bosses"]:
            need(all(isinstance(boss.get(k), str) for k in ("name", "zone")) and strings(boss.get("aliases", [])),
                 f"Bossname, Gebiet oder Aliasse fehlen: {boss['id']}")
            for attack in records(boss.get("attacks", [])).values():
                need(all(isinstance(attack.get(k), str) for k in ("name","tell","answer")), "Angriffstext fehlt.")
        for record in doc["languages"].values():
            need(isinstance(record,dict), "Bossübersetzung fehlt.")
            for lang in LANGS:
                value=record.get(lang,{})
                need(isinstance(value,dict) and isinstance(value.get("attacks",[]),list) and
                     all(isinstance(a,dict) for a in value.get("attacks",[])), "Ungültige Angriffsübersetzung.")
        for source in doc["sources"].values():
            need(isinstance(source,dict) and isinstance(source.get("url"),str) and
                 isinstance(source.get("label"),str), "Ungültige Bossquelle.")
    else:
        need(doc.get("schema") == "buildschmiede.campaign.live.v2", "Kampagnenformat live.v2 erwartet.")
        need(isinstance(doc.get("source"),dict) and isinstance(doc.get("assets"),dict) and
             strings(doc["assets"].get("images",[])), "Exportquelle oder Bildverzeichnis fehlt.")
        for page in doc["pages"]:
            need(strings(page.get("zones")) and bool(page["zones"]) and isinstance(page.get("act"),str) and
                 isinstance(page.get("layouts"),dict) and isinstance(page.get("aliases",{}),dict) and
                 all(strings(values) for values in page.get("aliases",{}).values()), f"Gebiet ist unvollständig: {page['id']}")
            if "template" in page:
                need(type(page["template"]) is bool and localized(page.get("title")),
                     f"Gebietsvorlage ist unvollständig: {page['id']}")
            for mode in MODES:
                for section in records(page["layouts"].get(mode)).values():
                    need(section["id"] in HEADINGS and section.get("tone") in STYLE["tones"] and
                         localized(section.get("title")), f"Unbekannter Abschnitt: {section['id']}")
                    if "image" in section:
                        image=section["image"]
                        need(isinstance(image,dict) and isinstance(image.get("asset"),str) and
                             re.fullmatch(r"images/[A-Za-z0-9_.-]+\.(?:png|webp|gif|jpg)",image["asset"]),
                             "Ungültiger Bildpfad.")
                    for row in records(section.get("rows")).values():
                        need(localized(row.get("text")), f"Sprachfassungen fehlen: {row['id']}")
                        for field in ("termRefs", "accents"):
                            mapping=row.get(field,{})
                            need(isinstance(mapping,dict) and all(lang in LANGS and isinstance(v,dict) and
                                 all(isinstance(s,str) for s in v.values()) for lang,v in mapping.items()), f"Ungültige {field}.")
        for town in doc["towns"]:
            need(strings(town.get("zones")) and isinstance(town.get("act"),str), "Unvollständige Stadt.")
            for tip in (*records(town.get("defaults")).values(), *records(town.get("more")).values()):
                need(isinstance(tip.get("layouts"),dict) and all(localized(tip["layouts"].get(m)) for m in MODES),
                     "Ein Stadttipp enthält nicht alle Ansichten.")


def merged(name, base, incoming):
    if name in CATALOG_FILES:
        return merge_catalog(name,base,incoming)
    validate(name, incoming)
    if name == BOSSES:
        # Older native exports do not carry the website-only presentation fields.
        incoming=deepcopy(incoming)
        previous=records(base["bosses"])
        for row in incoming["bosses"]:
            old=previous.get(row["id"],{})
            if "website" in old:
                row.setdefault("website",old["website"])
        for ident,languages in incoming["languages"].items():
            old=base["languages"].get(ident,{})
            for lang in LANGS:
                if isinstance(old.get(lang),dict) and "website" in old[lang]:
                    languages.setdefault(lang,{}).setdefault("website",old[lang]["website"])
    result = {**base, **incoming}
    changed = 0
    for field in (*LISTS[name], *MAPS[name]):
        old, new = base[field], incoming[field]
        is_list = field in LISTS[name]
        if is_list:
            old, new = records(old), records(new)
        changed += sum(row != old.get(key) for key, row in new.items())
        combined = {**old, **new}
        result[field] = list(combined.values()) if is_list else combined
    if name == CAMPAIGN:
        result["source"] = {**result["source"], "selection":"all"}
        result["assets"] = {**result["assets"], "images":list(dict.fromkeys(
            base["assets"].get("images", []) + incoming["assets"].get("images", [])))}
    return result, changed


@lru_cache(maxsize=len(FILES))
def bundled(name):
    need(name in FILES, "Unbekannte Datei.")
    return json.loads((APP / "shared-data" / name).read_bytes())


@lru_cache(maxsize=2*len(FILES))
def saved_document(name, path, modified, size):
    """A committed file is replaced atomically. Cache its parsed, validated revision."""
    need(size<=MAX_BYTES,"Datei ist zu groß.")
    value=json.loads(path.read_bytes())
    validate(name,value)
    return value


def retired_campaign_record(row):
    """Identify old campaign records in imports and legacy route clues."""
    ident = str(row.get("id", ""))
    return (ident.startswith("i-") or RETIRED_CHAPTER.search(str(row.get("act", ""))) is not None
            or (ident == "a4-tavakai" and any(RETIRED_CHAPTER.search(str(row.get(key, "")))
                for key in ("cue", "instruction", "target", "highlight", "note", "veteranText"))))


def active_campaign_page(page, base):
    if page["id"] not in ("a4-kingsmarch", "a4-tavakai"):
        return page
    layouts = {}
    for mode in MODES:
        current = base["layouts"][mode]
        updated_rows = {row["id"]: row for section in current for row in section["rows"]}
        sections = []
        for section in page["layouts"][mode]:
            rows = []
            for row in section["rows"]:
                if row["id"] == "run:a4-town-interludes":
                    continue
                if row["id"] == "route:a4-tavakai" and any(RETIRED_CHAPTER.search(row["text"][lang]) for lang in LANGS):
                    row = updated_rows.get(row["id"], row)
                rows.append(row)
            sections.append({**section, "rows": rows})
        layouts[mode] = sections
    return {**page, "layouts": layouts}


def active_document(name, doc):
    if name == CAMPAIGN:
        base_pages = records(bundled(CAMPAIGN)["pages"])
        pages = [active_campaign_page(page, base_pages.get(page["id"])) for page in doc["pages"]
                 if not retired_campaign_record(page)]
        return {**doc, "pages": pages, "towns": [town for town in doc["towns"] if not retired_campaign_record(town)]}
    if name == BOSSES:
        bosses = [boss for boss in doc["bosses"] if not retired_campaign_record(boss)]
        retired = [boss for boss in doc["bosses"] if retired_campaign_record(boss)]
        retired_ids = {boss["id"] for boss in retired}
        languages = {key: values for key, values in doc["languages"].items() if key not in retired_ids}
        for index, boss in enumerate(bosses):
            if boss["id"] == "tavakai" and RETIRED_CHAPTER.search(str(boss.get("reward", ""))):
                base = next(row for row in bundled(BOSSES)["bosses"] if row["id"] == "tavakai")
                bosses[index] = {**boss, "reward": base["reward"], "sources": [source for source in boss.get("sources", [])
                                                                                if not RETIRED_CHAPTER.search(str(source))]}
        tavakai = languages.get("tavakai", {})
        if tavakai:
            base_languages = bundled(BOSSES)["languages"]["tavakai"]
            languages["tavakai"] = {language: {**values, "reward": base_languages[language]["reward"]}
                                     if language in LANGS and RETIRED_CHAPTER.search(str(values.get("reward", "")))
                                     else values for language, values in tavakai.items()}
        used_sources = {source for boss in bosses for source in boss.get("sources", [])}
        retired_sources = {source for boss in retired for source in boss.get("sources", [])}
        sources = {key: source for key, source in doc["sources"].items()
                   if key in used_sources or (key not in retired_sources and
                                              not RETIRED_CHAPTER.search(source["label"] + " " + source["url"]))}
        return {**doc, "bosses": bosses, "languages": languages, "sources": sources}
    return doc


class Exchange:
    def __init__(self, directory):
        self.directory = directory
        self.lock = RLock()

    def current(self, name):
        return self.current_with_source(name)[0]

    def current_with_source(self, name, *, include_retired=False):
        """Return the current document, its path and IDs of bundled supplement pages."""
        need(name in FILES, "Unbekannte Datei.")
        path = self.directory / name
        try:
            stat=path.stat()
            saved = saved_document(name,path,stat.st_mtime_ns,stat.st_size)
            if not include_retired:
                saved = active_document(name, saved)
            if name == CAMPAIGN:
                known = records(saved["pages"])
                added = [p for p in bundled(name)["pages"] if p.get("template") and p["id"] not in known]
                if added:
                    return {**saved, "pages": [*saved["pages"], *added]}, path, frozenset(p["id"] for p in added)
            return saved, path, frozenset()
        except FileNotFoundError:
            pass
        except (ValueError,TypeError,OSError,RecursionError) as error:
            logging.warning("%s konnte nicht geladen werden. Der mitgelieferte Stand ist aktiv: %s",name,error)
        return bundled(name), APP / "shared-data" / name, frozenset()

    def export(self, name):
        with self.lock:
            doc = self.current(name)
            if name == CAMPAIGN:
                return {**doc, "terms":self.current(TERMS)["terms"]}
            return doc

    def transfer(self, name, incoming, expected=None):
        with self.lock:
            base = self.current_with_source(name, include_retired=True)[0]
            if name == CAMPAIGN:
                base = {**base, "terms": self.current(TERMS)["terms"]}
            result, changed = merged(name, base, incoming)
            if name in ("lexicon.v1.json","currency.v1.json"):
                lexicon=result if name=="lexicon.v1.json" else self.current("lexicon.v1.json")
                currencies=result if name=="currency.v1.json" else self.current("currency.v1.json")
                check_catalog_refs(lexicon,currencies)
            if name in (CAMPAIGN, TERMS):
                terms = result if name == TERMS else self.current(TERMS)
                campaign = result if name == CAMPAIGN else self.current(CAMPAIGN)
                for aliases in terms["areaAliases"].values():
                    need(all(ref in terms["terms"] for ref in aliases.values()), "Unbekannte Begriffs-ID in areaAliases.")
                previous = dict(campaign_term_ref_fields(base["pages"])) if name == CAMPAIGN else {}
                for location, (text, refs) in campaign_term_ref_fields(campaign["pages"]):
                    if name == CAMPAIGN and previous.get(location) != (text, refs):
                        validate_term_refs(text, refs, terms["terms"], context=" / ".join(location))
                    else:
                        need(all(ref in terms["terms"] for ref in refs.values()),
                             f"{location[0]}: Begriffs-ID fehlt. Zuerst terms.json importieren.")
                if name == CAMPAIGN:
                    result["terms"] = terms["terms"]
            # The preview token binds both the previous content and the selected new file.
            content = json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
            need(len(content) <= MAX_BYTES, "Der gemeinsame Datenbestand überschreitet 16 MB.")
            revision = hashlib.sha256(json.dumps(base,ensure_ascii=False,sort_keys=True).encode()+b"\0"+content).hexdigest()
            if expected is not None:
                need(expected == revision, "Stand oder Datei hat sich geändert. Vorschau erneut öffnen.")
                if base != result:
                    self.directory.mkdir(parents=True,exist_ok=True)
                    with NamedTemporaryFile(dir=self.directory,delete=False) as stream:
                        temp=Path(stream.name)
                        try:
                            stream.write(content)
                        except BaseException:
                            stream.close()
                            temp.unlink(missing_ok=True)
                            raise
                    try:
                        temp.replace(self.directory/name)
                        saved_document.cache_clear()
                    finally:
                        temp.unlink(missing_ok=True)
            return {"revision":revision,"changed":changed,"modified":base!=result}


SHARED = Exchange(data_dir(APP,getattr(sys,"frozen",False)) / "shared-data")


def native_page(page, previous):
    """The HUD and its editor use a detailed sections list and a compact steps list."""
    result = {**previous, "sections":[], "steps":[], "sharedSections":{}}
    if page.get("template"):
        result["template"] = True
        result["title"] = page["title"]
    else:
        result.pop("template", None)
        result.pop("title", None)
    # Old landmark/optionalStops data stays in the original source and outside this projection.
    for key in ("landmarks","optionalStops"):
        result.pop(key,None)
    headings = {}
    for mode in MODES:
        result["sharedSections"][mode]=[]
        for section in page["layouts"][mode]:
            heading = HEADINGS[section["id"]]
            meta = {key:value for key,value in section.items() if key != "rows"}
            result["sharedSections"][mode].append(meta)
            if heading not in headings:
                native = {"heading":heading, "tone":section["tone"], "lines":[]}
                headings[heading] = native
                result["sections"].append(native)
            native = headings[heading]
            if mode == "basis" and section.get("image"):
                native["image"]=section["image"]["asset"].split("/")[-1]
            for row in section["rows"]:
                line = {**{k:v for k,v in row.items() if k!="text"}, **row["text"]}
                if mode == "basis":
                    native["lines"].append(line)
                else:
                    result["steps"].append({**line, "section":heading})
    return result


def apply_campaign(catalog, doc, page_ids, town_ids):
    for page in doc["pages"]:
        if page["id"] not in page_ids:
            continue
        layouts=catalog.setdefault("areaLayouts",{})
        layouts[page["id"]] = native_page(page,layouts.get(page["id"],{}))
        catalog.setdefault("sharedAreas",{})[page["id"]]={"act":page["act"], "zones":page["zones"], "aliases":page.get("aliases",{})}
        for zone in page["zones"]:
            if page.get("template"):
                catalog.setdefault("areas", {})[zone] = page["title"]
            aliases=page.get("aliases",{}).get(zone,[])
            for label in (zone,*aliases):
                catalog.setdefault("sharedZones",{})[label.strip().casefold().replace("’","'").removeprefix("the ")]=page["id"]
    for town in doc["towns"]:
        if town["id"] not in town_ids:
            continue
        tips=catalog.setdefault("townTipPool",{})
        module={**catalog.setdefault("townTips",{}).get(town["id"],{}), "act":town["act"],
                "zones":[zone.strip().casefold().removeprefix("the ") for zone in town["zones"]]}
        for field in ("defaults","more"):
            module[field]=[t["id"] for t in town[field]]
            tips.update({t["id"]:t["layouts"] for t in town[field]})
        catalog["townTips"][town["id"]]=module
    return catalog


def sections_for_mode(layout, mode):
    """Keep per-layout ordering while allowing a local editor to add a section."""
    if not layout.get("sharedSections"):
        return [(section,{}) for section in layout["sections"]]
    by_id = {STYLE["headings"][s["heading"]]:s for s in layout["sections"]}
    metadata={s["id"]:s for s in layout.get("sharedSections",{}).get(mode,[])}
    ordered=[i for i in metadata if i in by_id]+[i for i in by_id if i not in metadata]
    return [(by_id[i],metadata.get(i,{})) for i in ordered]


def campaign_section_rows(layout, mode):
    for section, meta in sections_for_mode(layout, mode):
        rows = section["lines"] if mode == "basis" else [
            step for step in layout["steps"] if step.get("section") == section["heading"]
        ]
        yield section, meta, rows


RESOURCES = {"terms.json":TERMS,"poe2_campaign_companion.json":BOSSES,
             "poe2_boss_languages.json":BOSSES,"poe2_language_pilot.json":CAMPAIGN}


def project(name, native, store=SHARED, *, layout_sources=None):
    if name not in RESOURCES:
        return native
    key=RESOURCES[name]
    if key == CAMPAIGN and layout_sources is not None:
        doc, source, supplemented = store.current_with_source(key)
    else:
        doc = store.current(key)
    if key==TERMS:
        return {**native, **doc}
    if key==BOSSES:
        if name=="poe2_boss_languages.json":
            return {**native, **doc["languages"]}
        old=records(native["bosses"])
        for row in doc["bosses"]:
            old[row["id"]]={"required":False,"attacks":[],"sources":[],"quick":"","window":"","prep":"",
                            "reward":"","plan":"","build_tips":{}, **old.get(row["id"],{}), **row}
        return {**native,"bosses":list(old.values()), "sources":{**native.get("sources",{}),**doc["sources"]}}
    template=bundled(CAMPAIGN)
    def changed(field):
        old=records(template[field])
        return {row["id"] for row in doc[field] if old.get(row["id"])!=row}
    # These three detailed layouts contain the reviewed WordPress edits in the initial merged release.
    reviewed={"a1-clearfell-exit","a1-devourer","a1-grelwood-river"}
    templates = {page["id"] for page in doc["pages"] if page.get("template")}
    page_ids = reviewed | templates | changed("pages")
    if layout_sources is not None:
        layout_sources.update(dict.fromkeys(native.get("areaLayouts", {}), APP / "web" / name))
        for page in doc["pages"]:
            ident = page["id"]
            if ident in page_ids:
                layout_sources[ident] = APP / "shared-data" / CAMPAIGN if ident in supplemented else source
    return apply_campaign(native, doc, page_ids, changed("towns"))
