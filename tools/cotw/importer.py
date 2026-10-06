"""One-time import: v3 spreadsheet + Wikidata cache + Natural Earth adjacency → YAML entries.

Also writes ``docs/data-changes.md``, the list of every deviation from the spreadsheet.
After the import the YAML files are the database; the importer stays re-runnable (it is
deterministic) but is not part of the normal workflow. The v3 spreadsheet itself is not in
the repository; ``python -m cotw import-v3 <csv>`` takes the export as an argument.

The importer stays EN/DE on purpose: it reads the historical two-language v3 source. Further
languages are added to the YAML database directly (``cotw.languages``, docs/DECK.md).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import ids as ids_mod
from . import naturalearth, wikidata
from .paths import COUNTRIES, DOCS, OVERRIDES
from .source import SourceCapital, SourceEntry, parse_source

CHANGES_FILE = DOCS / "data-changes.md"

# Spreadsheet capital labels (EN) that encode a role. Anything else is a free-text note.
LABEL_ROLES = {
    "capital": "capital",
    "seat of government": "seat_of_government",
    "seat of government, to be made capital at a later point": "seat_of_government",
    "executive": "executive",
    "legislative": "legislative",
    "judicial": "judicial",
    "de jure": "de_jure",
    "de facto": "de_facto",
    "proclaimed": "proclaimed",
}
LABEL_FIXES = {"disputet": "disputed"}  # spreadsheet typos, EN


@dataclass
class Change:
    entry: str  # "CH Switzerland"
    field: str
    old: str
    new: str
    source: str


@dataclass
class Report:
    changes: list[Change] = field(default_factory=list)
    checks: list[Change] = field(default_factory=list)  # Wikidata discrepancies, not applied

    def change(self, entry: SourceEntry, fld: str, old, new, source: str) -> None:
        self.changes.append(Change(f"{entry.iso2} {entry.name_en}", fld, _fmt(old), _fmt(new), source))

    def check(self, entry: SourceEntry, fld: str, ours, theirs, source: str) -> None:
        self.checks.append(Change(f"{entry.iso2} {entry.name_en}", fld, _fmt(ours), _fmt(theirs), source))


def _fmt(v) -> str:
    if v is None or v == "" or v == []:
        return "—"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s.casefold()).strip()
    return re.sub(r"\bst\b", "saint", s)


def _text(en: str, de: str) -> dict:
    return {"en": en, "de": de}


def _text_opt(en: str, de: str) -> dict | None:
    """Optional text map: empty languages are omitted, ``None`` when nothing is left."""
    out = {k: v for k, v in (("en", en), ("de", de)) if v}
    return out or None


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _check_keys(data, path)
    return data


def _check_keys(node, path: Path) -> None:
    """ISO codes as mapping keys must be quoted: bare ``NO`` is a YAML boolean."""
    if isinstance(node, dict):
        for k, v in node.items():
            if not isinstance(k, str):
                raise SystemExit(f"{path}: key {k!r} is not a string (quote ISO codes like 'NO')")
            _check_keys(v, path)
    elif isinstance(node, list):
        for v in node:
            _check_keys(v, path)


# --- Wikidata -----------------------------------------------------------------------------


def resolve_qids(entries: list[SourceEntry], countries: dict, overrides: dict) -> dict[str, str]:
    qids = {}
    for e in entries:
        ov = overrides.get("country", {}).get(e.iso2)
        if ov:
            qids[e.iso2] = ov["qid"]
        elif countries.get(e.iso2):
            qids[e.iso2] = countries[e.iso2][0]["qid"]
        else:
            raise SystemExit(f"{e.iso2}: no Wikidata item with P297 and no override")
    return qids


def current_capitals(records: list[dict]) -> list[dict]:
    return [r for r in records if r["rank"] != "deprecated" and not r["end"]]


def match_capital(name_en: str, candidates: list[dict]) -> dict | None:
    wants = [_norm(alt) for alt in name_en.split(" / ")]  # Ouagadougou / Wagadugu
    for want in wants:
        for r in candidates:
            if r["label_en"] and _norm(r["label_en"]) == want:
                return r
    for want in wants:
        for r in candidates:  # Yaren → Yaren District, Sri Jayawardenepura → … Kotte
            have = _norm(r["label_en"])
            if have and (have.startswith(want + " ") or want.startswith(have + " ")):
                return r
    return None


def lookup_place(name: str, places: dict, accept_countries: set[str]) -> dict | None:
    candidates = places.get(name) or []
    for r in candidates:
        if r["country"] in accept_countries:
            return r
    return None


# --- entries ------------------------------------------------------------------------------


def _capital_role(cap: SourceCapital, entry: SourceEntry, report: Report) -> tuple[str, dict | None]:
    label_en = LABEL_FIXES.get(cap.label_en, cap.label_en)
    if label_en != cap.label_en:
        report.change(entry, f"capital {cap.name_en}: label.en", cap.label_en, label_en, "typo")
    role = LABEL_ROLES.get(label_en.casefold(), "capital")
    return role, _text_opt(label_en, cap.label_de)


def build_entry(
    e: SourceEntry,
    cid: str,
    id_of: dict[str, str],
    qid: str,
    qids: dict[str, str],
    wd_countries: dict,
    wd_capitals: dict,
    wd_places: dict,
    cap_overrides: dict,
    renames: dict,
    coords_index: dict[str, tuple[float, float]],
    borders: list[str],
    report: Report,
) -> dict:
    # name label: the parent ISO code / "disputed" are derivable from dependency_of / status.
    label_en, label_de = e.name_label_en, e.name_label_de
    parent = None
    if e.status == "dependency":
        parent = label_en
        if parent not in id_of:
            raise SystemExit(f"{e.iso2}: dependency of unknown {parent!r}")
        label_en = label_de = ""
    elif e.status == "disputed":
        label_en = label_de = ""
    # (dropping the derivable labels is documented once under "systematic changes")

    if e.name_en != e.raw["EN Country"]:
        report.change(e, "name.en", repr(e.raw["EN Country"]), repr(e.name_en), "whitespace")

    # Wikidata plausibility on names (report only).
    wd = next((r for r in wd_countries.get(e.iso2, []) if r["qid"] == qid), None)
    if wd:
        alts = {_norm(a) for a in re.split(r" / ", e.name_en)} | {_norm(e.name_en)}
        alts |= {_norm(re.sub(r", The$", "", a)) for a in list(alts)}
        if wd["label_en"] and _norm(wd["label_en"]) not in alts:
            report.check(e, "name.en", e.name_en, wd["label_en"], f"Wikidata {qid} label")
        alts_de = {_norm(a) for a in re.split(r" / ", e.name_de)}
        if wd["label_de"] and _norm(wd["label_de"]) not in alts_de:
            report.check(e, "name.de", e.name_de, wd["label_de"], f"Wikidata {qid} label")
        if wd["iso3"] and wd["iso3"] != e.iso3:
            report.check(e, "iso3", e.iso3, wd["iso3"], f"Wikidata {qid} P298")

    # Capitals: spreadsheet decides which; Wikidata supplies QID + coordinates.
    accept = {qid}
    if parent:
        accept.add(qids[parent])
    wd_current = current_capitals(wd_capitals.get(qid, []))
    capitals = []
    matched_qids = set()
    for i in (2, 3):
        if not e.raw[f"EN Capital {i}"] and e.raw[f"DE Hauptstadt {i}"]:
            report.change(e, f"capital {i}", f"DE-only row {e.raw[f'DE Hauptstadt {i}']!r}", f"label.de of capital 1", "misplaced cell")
    for cap in e.capitals:
        rename = renames.get(e.iso2, {}).get(cap.name_en)
        if rename:
            report.change(e, f"capital {cap.name_en}: name.en", cap.name_en, rename["en"], rename["reason"].strip())
            cap = SourceCapital(rename["en"], cap.name_de, cap.label_en, cap.label_de)
        role, label = _capital_role(cap, e, report)
        rec = match_capital(cap.name_en, wd_current) or match_capital(cap.name_en, wd_capitals.get(qid, []))
        cap_qid, coord, src = None, None, None
        ov = cap_overrides.get(e.iso2, {}).get(cap.name_en)
        if ov:
            cap_qid, coord, src = ov["wikidata"], (ov.get("lat"), ov.get("lon")), f"override: {ov['reason']}"
            if coord == (None, None):
                coord = None
        elif rec:
            cap_qid, coord, src = rec["qid"], rec["coord"], "Wikidata P36"
        else:
            place = lookup_place(cap.name_en, wd_places, accept)
            if place:
                cap_qid, coord, src = place["qid"], place["coord"], "Wikidata label lookup"
        if cap_qid is None:
            raise SystemExit(f"{e.iso2}: capital {cap.name_en!r} not found in Wikidata caches; add an override")
        if coord is None and cap_qid:
            # QID known (override) but no coordinates given: try the caches for that QID.
            coord = coords_index.get(cap_qid)
        matched_qids.add(cap_qid)
        item = {"name": _text(cap.name_en, cap.name_de)}
        if label:
            item["label"] = label
        item["role"] = role
        item["wikidata"] = cap_qid
        if coord:
            item["lat"], item["lon"] = round(coord[0], 5), round(coord[1], 5)
        capitals.append(item)
        if rec and rec["end"]:
            report.check(e, f"capital {cap.name_en}: status", role, f"ended {rec['end'][:10]}", f"Wikidata {qid} P36 end time (P582)")
        if rec and rec["label_en"] and _norm(rec["label_en"]) != _norm(cap.name_en):
            report.check(e, f"capital {cap.name_en}: name.en", cap.name_en, rec["label_en"], f"Wikidata {cap_qid} label")
        if rec and rec["label_de"] and _norm(rec["label_de"]) != _norm(cap.name_de):
            report.check(e, f"capital {cap.name_en}: name.de", cap.name_de, rec["label_de"], f"Wikidata {cap_qid} label")
    extra = [r["label_en"] or r["qid"] for r in wd_current if r["qid"] not in matched_qids]
    if extra:
        report.check(e, "capitals", [c.name_en for c in e.capitals], extra, f"Wikidata {qid} P36 lists additionally")
    if not e.capitals:
        raise SystemExit(f"{e.iso2}: no capital in the spreadsheet")

    # Borders (COTW ids), computed from Natural Earth ± overrides; diff vs. spreadsheet.
    src_b = sorted(e.borders)
    if src_b != sorted(borders):
        report.change(e, "borders", src_b, sorted(borders), "Natural Earth land adjacency (see below)")

    # (region renames are documented once under "systematic changes")

    out: dict = {
        "id": cid,
        "iso2": e.iso2,
        "iso3": e.iso3,
        "wikidata": qid,
        "status": e.status,
    }
    if parent:
        out["dependency_of"] = id_of[parent]
    out["name"] = _text(e.name_en, e.name_de)
    if _text_opt(label_en, label_de):
        out["name_label"] = _text_opt(label_en, label_de)
    formal = {}
    if e.formal_en:
        formal["en"] = e.formal_en
    if e.formal_de:
        formal["de"] = e.formal_de
    if formal:
        out["formal_name"] = formal
    out["capitals"] = capitals
    out["borders"] = sorted(id_of[b] for b in borders)
    out["regions"] = list(e.regions)
    out["wikipedia"] = {"en": e.wikipedia_en}
    return out


def final_borders(entries: list[SourceEntry], ne: dict, overrides: dict, report: Report) -> dict[str, list[str]]:
    adjacency = {e.iso2: set(ne["borders"].get(e.iso2, [])) for e in entries}
    for item in overrides.get("add", []):
        a, b = item["pair"]
        adjacency[a].add(b)
        adjacency[b].add(a)
    for item in overrides.get("remove", []):
        a, b = item["pair"]
        adjacency[a].discard(b)
        adjacency[b].discard(a)
    return {k: sorted(v) for k, v in adjacency.items()}


# --- output -------------------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    if data.isdigit():  # COTW ids: always quoted, so no YAML 1.2 parser reads '039' as 39
        style = "'"
    elif len(data) > 100:
        style = ">"
    else:
        style = None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


def dump_entry(entry: dict) -> str:
    return yaml.dump(entry, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)


def write_entries(entries: dict[str, dict], ledger: dict[str, dict], directory: Path = COUNTRIES) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.yaml"):
        old.unlink()
    for cid, entry in entries.items():
        path = directory / f"{cid}-{ledger[cid]['slug']}.yaml"
        path.write_text(dump_entry(entry), encoding="utf-8")


def write_changes(report: Report, ne: dict, border_overrides: dict, path: Path = CHANGES_FILE) -> None:
    lines = [
        "# Data changes: spreadsheet → database",
        "",
        "Generated by `python -m cotw import-v3`. Every deviation of `data/countries/` from",
        "the v3 spreadsheet (`cotw v3.csv`), with its source. Do not edit by hand.",
        "",
        "## Systematic changes",
        "",
        "| What | Old | New |",
        "|---|---|---|",
        "| Status values | `Souvereign Country` / `Dependency` / `Disputed` | `sovereign` / `dependency` / `disputed` |",
        "| Region names | spreadsheet spelling (`East Africa`, `West Asia`, …) | UN M49 names as in `tags.txt` (`Eastern Africa`, `Western Asia`, …) |",
        "| Country label of dependencies | parent ISO code (`FR`, `GB`, …) | dropped, derivable from `dependency_of` |",
        "| Country label of disputed entries | `disputed` / `umstritten` | dropped, derivable from `status` |",
        "| Long form | `EN Long From` / `DE Langform` | `formal_name.{en,de}`, empty cells omitted |",
        "| Capital labels | free text | `role` (machine-readable) + `label.{en,de}` (display text, unchanged) |",
        "| Borders | ISO-2 codes B1–B14 | COTW ids, recomputed from Natural Earth land adjacency |",
        "| Capitals | names only | + Wikidata QID and coordinates |",
        "",
        "## Per-entry changes (applied)",
        "",
        "| Entry | Field | Old | New | Source |",
        "|---|---|---|---|---|",
    ]
    for c in report.changes:
        lines.append(f"| {c.entry} | {c.field} | {_cell(c.old)} | {_cell(c.new)} | {_cell(c.source)} |")
    lines += [
        "",
        "## Natural Earth reconciliation",
        "",
        f"Source: {ne['source']}. Map units without an ISO code were folded into the entry that",
        "controls them de facto:",
        "",
    ]
    for gu, info in ne["folded"].items():
        lines.append(f"- `{gu}` → {info['into']}: {info['reason']}")
    lines += ["", "Ignored map units (no entry of their own, no effect on any border): " + ", ".join(ne["ignored"]) + ".", ""]
    if border_overrides.get("add") or border_overrides.get("remove"):
        lines += ["Manual overrides of the computed adjacency (`data/overrides/borders.yaml`):", ""]
        for item in border_overrides.get("add", []):
            lines.append(f"- add {item['pair'][0]}–{item['pair'][1]}: {item['reason'].strip()}")
        for item in border_overrides.get("remove", []):
            lines.append(f"- remove {item['pair'][0]}–{item['pair'][1]}: {item['reason'].strip()}")
        lines.append("")
    lines += [
        "## Wikidata discrepancies (not applied, for review)",
        "",
        "Wikidata says something else than the spreadsheet. The spreadsheet value was kept;",
        "each row is a candidate for a manual decision (then add an override or edit the YAML).",
        "",
        "| Entry | Field | Database | Wikidata | Source |",
        "|---|---|---|---|---|",
    ]
    for c in report.checks:
        lines.append(f"| {c.entry} | {c.field} | {_cell(c.old)} | {_cell(c.new)} | {_cell(c.source)} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def run(source_csv: Path) -> None:
    entries = parse_source(source_csv)
    wd_countries = wikidata.load_countries()
    wd_capitals = wikidata.load_capitals()
    wd_places = wikidata.load_places()
    wd_overrides = _load_yaml(OVERRIDES / "wikidata.yaml")
    cap_yaml = _load_yaml(OVERRIDES / "capitals.yaml")
    cap_overrides = cap_yaml.get("capitals") or {}
    renames = cap_yaml.get("renames") or {}
    coords_index = {
        r["qid"]: tuple(r["coord"])
        for recs in list(wd_capitals.values()) + list(wd_places.values())
        for r in recs
        if r.get("coord")
    }
    border_overrides = _load_yaml(OVERRIDES / "borders.yaml")
    ne = naturalearth.load()
    report = Report()

    qids = resolve_qids(entries, wd_countries, wd_overrides)
    ledger = ids_mod.load()
    id_of = ids_mod.assign(entries, qids, ledger)
    ids_mod.save(ledger)

    borders = final_borders(entries, ne, border_overrides, report)
    built: dict[str, dict] = {}
    for e in entries:
        cid = id_of[e.iso2]
        built[cid] = build_entry(
            e, cid, id_of, qids[e.iso2], qids, wd_countries, wd_capitals, wd_places,
            cap_overrides, renames, coords_index, borders[e.iso2], report,
        )
    sitelinks = wikidata.load_sitelinks()
    for cid, entry in built.items():
        entry["wikipedia"] = wikidata.wikipedia_links(entry["wikipedia"]["en"], sitelinks.get(entry["wikidata"]))
    write_entries(dict(sorted(built.items())), ledger)
    write_changes(report, ne, border_overrides)
    print(f"wrote {len(built)} entries, {len(report.changes)} changes, {len(report.checks)} checks")
