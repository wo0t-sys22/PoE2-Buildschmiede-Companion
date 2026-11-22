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


class Exchange:
    def __init__(self, directory):
        self.directory = directory
        self.lock = RLock()

    def current(self, name):
        need(name in FILES, "Unbekannte Datei.")
        path = self.directory / name
        try:
            stat=path.stat()
            saved = saved_document(name,path,stat.st_mtime_ns,stat.st_size)
            if name == CAMPAIGN:
                known = records(saved["pages"])
                added = [p for p in bundled(name)["pages"] if p.get("template") and p["id"] not in known]
                if added:
                    return {**saved, "pages": [*saved["pages"], *added]}
            return saved
        except FileNotFoundError:
            pass
        except (ValueError,TypeError,OSError,RecursionError) as error:
            logging.warning("%s konnte nicht geladen werden. Der mitgelieferte Stand ist aktiv: %s",name,error)
        return bundled(name)

    def export(self, name):
        with self.lock:
            doc = self.current(name)
            if name == CAMPAIGN:
                return {**doc, "terms":self.current(TERMS)["terms"]}
            return doc

    def transfer(self, name, incoming, expected=None):
        with self.lock:
            base = self.export(name)
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
                for page in campaign["pages"]:
                    for sections in page["layouts"].values():
                        for section in sections:
                            for row in section["rows"]:
                                for mapping in row.get("termRefs",{}).values():
                                    need(all(ref in terms["terms"] for ref in mapping.values()),
                                         f"{page['id']}: Begriffs-ID fehlt. Zuerst terms.json importieren.")
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


def editor_layouts(old, layout, catalog):
    """Return the same canonical page with the edited native rows and stable check IDs."""
    layouts={}
    for mode in MODES:
        result=[]
        prior=records(old["layouts"][mode])
        for section, meta in sections_for_mode(layout, mode):
            heading=section["heading"]
            ident=STYLE["headings"][heading]
            prev=prior.get(ident,{})
            native=section["lines"] if mode=="basis" else [s for s in layout["steps"] if s["section"]==heading]
            rows=[]
            for index,row in enumerate(native):
                key=row.get("id") or row.get("checkId") or f"{ident}.{index}"
                wire={k:row[k] for k in ("checkId","kind","termRefs","accents","bossId") if k in row}
                boss=catalog.get("bossSteps",{}).get(row.get("checkId"),{})
                if boss and boss.get("mode",mode)==mode:
                    wire.setdefault("bossId",boss["id"])
                rows.append({**wire,"id":key,"text":{lang:row[lang] for lang in LANGS}})
            wire={**prev,**meta,"id":ident,"tone":meta.get("tone",section["tone"]),
                  "collapsed":meta.get("collapsed",False),"rows":rows,
                  "title":meta.get("title") or prev.get("title") or
                          {l:catalog.get("ui",{}).get(heading,{}).get(l,heading) for l in LANGS}}
            if mode=="basis":
                wire.pop("image",None)
                if image:=section.get("image"):
                    wire["image"]={"asset":"images/"+image,"position":"after_rows"}
            if rows or wire.get("image") or (old.get("template") and ident in prior):
                result.append(wire)
        layouts[mode]=result
    return {**old,"layouts":layouts}


def save_shared_edit(collection, ident, record, catalog, store=SHARED):
    """Shared structured pages and town-tip edits use the same atomic local document as file import."""
    if collection not in ("areaLayouts","townTipPool"):
        return False
    from poe2_campaign_structure import structured_layout
    with store.lock:
        doc=store.export(CAMPAIGN)
        incoming={**doc,"pages":[],"towns":[]}
        if collection=="areaLayouts":
            prior=records(doc["pages"]).get(ident)
            if prior:
                incoming["pages"]=[editor_layouts(prior,structured_layout(deepcopy(record),ident),catalog)]
        else:
            for town in doc["towns"]:
                if any(tip["id"]==ident for field in ("defaults","more") for tip in town[field]):
                    updated=deepcopy(town)
                    for field in ("defaults","more"):
                        for tip in updated[field]:
                            if tip["id"]==ident:
                                tip["layouts"]=record
                    incoming["towns"].append(updated)
        if not incoming["pages"] and not incoming["towns"]:
            return False
        digest=hashlib.sha256(json.dumps([incoming["pages"],incoming["towns"]],sort_keys=True).encode()).hexdigest()
        incoming["source"]={**doc["source"],"revision":"local-"+digest[:16]}
        revision=store.transfer(CAMPAIGN,incoming)["revision"]
        store.transfer(CAMPAIGN,incoming,revision)
        return True


RESOURCES = {"terms.json":TERMS,"poe2_campaign_companion.json":BOSSES,
             "poe2_boss_languages.json":BOSSES,"poe2_language_pilot.json":CAMPAIGN}


def project(name, native, store=SHARED):
    if name not in RESOURCES:
        return native
    key=RESOURCES[name]
    doc=store.current(key)
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
    return apply_campaign(native,doc,reviewed | templates | changed("pages"),changed("towns"))
