"""Project shared website data onto the native catalogues while preserving game mechanics and stable IDs."""
from copy import deepcopy
from poe2_shared_catalogs import CATALOG_FILES, native_icons

LEXICON, CURRENCY, TRANSLATIONS = CATALOG_FILES

def current(name):
    from poe2_shared_content import SHARED
    return SHARED.current(name)

def native_ref(row, previous=None):
    icon=row.get("icon")
    if icon and previous and icon==previous.get("icon"):
        return row.get("imageLocal") or native_icons().get(icon,"")
    return native_icons().get(icon,"") or row.get("imageLocal","")

def currency_rows(offline):
    from poe2_shared_content import bundled
    defaults={r["currencyId"]:r for r in bundled(CURRENCY)["items"]}
    old={r["currencyId"]:r for r in offline}
    rows=[]
    for incoming in current(CURRENCY)["items"]:
        ident=incoming["currencyId"]
        row={**old.get(ident,{}),**deepcopy(incoming),"kind":"currency"}
        row["imageLocal"]=native_ref(row,defaults.get(ident))
        rows.append(row)
    return rows

def localized_game_rows(data,supplement):
    """Match English source, stable ID and numeric effects before applying German data."""
    from poe2_passive_de import passive_records, effect_numbers
    groups=[(data["skills"].items(),supplement.get("skills",{})),
            (data["supports"].items(),supplement.get("supports",{})),
            (passive_records(data),supplement.get("passives",{}))]
    for rows,records in groups:
        for ident,row in rows:
            record=records.get(ident,{})
            if not record or row["name"]!=record["name"]:
                continue
            for field in ("de","tagsDe","familyDe"):
                if record.get(field):
                    row[field]=record[field]
            original=row.get("stats",[])
            translated=record.get("statsDe",[])
            if original and translated and original==record.get("stats") and effect_numbers(original)==effect_numbers(translated):
                row["statsDe"]=translated
            source=record.get("description",{})
            current_desc=row.get("description",{})
            if source.get("en") and source["en"]==current_desc.get("en"):
                row["description"]={**current_desc,**{k:v for k,v in source.items() if k in ("de","hybrid") and v}}
    for mod in data["mods"]:
        pair=supplement.get("affixNames",{}).get(mod["id"])
        if pair and mod["name"]==pair[0]:
            mod["de"]=pair[1]
        original=mod.get("stats",[])
        if original and all(line in supplement.get("statLines",{}) for line in original):
            translated=[supplement["statLines"][line] for line in original]
            if effect_numbers(original)==effect_numbers(translated):
                mod["statsDe"]=translated
    for item in data["items"]:
        if item.get("kind")=="currency":
            continue
        ident=item.get("gameId") or ("unique:"+item["name"] if item.get("kind")=="unique" else "")
        pair=supplement.get("items",{}).get(ident)
        if pair and pair[0]==item["name"]: item["de"]=pair[1]

def local_editorial_changes(name, dataset):
    """Only an explicit local import wins over an older optional website feed."""
    from poe2_shared_content import SHARED, bundled
    if not (SHARED.directory/name).is_file(): return {}
    original={r["id"]:r for r in bundled(name)["entries"]}
    return {r["id"]:{k:v for k,v in r.items() if original.get(r["id"],{}).get(k)!=v}
            for r in dataset["entries"] if r!=original.get(r["id"])}

