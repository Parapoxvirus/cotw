"""Weekly change monitoring: the committed Wikidata/Commons caches vs. the live state (step 5).

``python -m cotw check-wikidata`` fetches everything the database took from Wikidata and
Commons with the same fetchers that built the caches, diffs it against the committed caches
(the last accepted snapshot, not the YAML database) and opens one Gitea issue per deviation.
Nothing is applied: ``python -m cotw accept-wikidata <fingerprint>`` accepts one deviation,
an entry in ``data/overrides/monitoring.yaml`` rejects it. Rules: ``docs/MONITORING.md``.

Every network read happens before the first write, so a failed fetch fails the run without
opening issues.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from . import flags, wikidata
from .paths import COUNTRIES, OVERRIDES

# Vandalism damping: a value whose item (or Commons file) changed less than this long ago is
# left for the next weekly run.
DAMPING = timedelta(hours=72)
# Capital coordinates: moves below this distance are float noise or a refined point.
COORD_TOLERANCE_KM = 1.0
MONITORING_OVERRIDES = OVERRIDES / "monitoring.yaml"
LABEL = "wikidata"
DEFAULT_MAX_ISSUES = 20
FINGERPRINT_RE = re.compile(r"<!-- cotw-monitor fingerprint=([0-9a-f]{16}) -->")
SUMMARY_MARKER = "<!-- cotw-monitor summary -->"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"


# --- snapshots ----------------------------------------------------------------------------------


@dataclass
class Snapshot:
    """Everything compared, in the shape of the caches. ``commons`` is keyed by file name."""

    countries: dict  # iso2 → [{qid, iso3, label_en, label_de}]  (countries.json)
    iso_codes: dict  # code → [qid]                              (iso-codes.json)
    capitals: dict  # country qid → [P36 records]                (capitals.json)
    coords: dict  # capital qid → [lat, lon]                   (capitals.json + places.json)
    status: dict  # qid → {P576: [...], P582: [...]}           (status.json)
    sitelinks: dict  # qid → {en, de}                             (sitelinks.json)
    p41: dict  # qid → [P41 statements]                     (flags.json)
    commons: dict  # file → {title, license, sha1, page}        (data/derived/flags.yaml)


def _coords_index(capitals: dict, places: dict) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for recs in list(capitals.values()) + list(places.values()):
        for r in recs:
            if r.get("coord"):
                out.setdefault(r["qid"], list(r["coord"]))
    return out


def load_baseline() -> Snapshot:
    capitals = wikidata.load_capitals()
    manifest = flags.load_manifest()
    return Snapshot(
        countries=wikidata.load_countries(),
        iso_codes=wikidata.load_iso_codes(),
        capitals=capitals,
        coords=_coords_index(capitals, wikidata.load_places()),
        status=wikidata.load_status(),
        sitelinks=wikidata.load_sitelinks(),
        p41=flags.load_p41(),
        commons={r["file"]: {k: r.get(k) for k in ("title", "license", "sha1", "page")} | {"title": r["file"]} for r in manifest.values()},
    )


def capital_qids(entries: dict) -> list[str]:
    return sorted({c["wikidata"] for e in entries.values() for c in e["capitals"] if c.get("wikidata")}, key=lambda q: int(q[1:]))


def fetch_live(entries: dict, baseline: Snapshot) -> Snapshot:
    """The live state, fetched with the same code that wrote the caches (network)."""
    qids = sorted({e["wikidata"] for e in entries.values()}, key=lambda q: int(q[1:]))
    p41 = flags.fetch_p41(qids)
    files = set(baseline.commons)
    for q, statements in p41.items():
        chosen, _ = flags.select_file(statements)
        if chosen:
            files.add(chosen)
    return Snapshot(
        countries=wikidata.fetch_countries(sorted(e["iso2"] for e in entries.values())),
        iso_codes=wikidata.fetch_iso_codes(),
        capitals=wikidata.fetch_capitals(qids),
        coords=wikidata.fetch_coords(capital_qids(entries)),
        status=wikidata.fetch_status(qids),
        sitelinks=wikidata.fetch_sitelinks(qids),
        p41=p41,
        commons=flags.fetch_imageinfo(sorted(files)),
    )


# --- deviations ---------------------------------------------------------------------------------


@dataclass
class Deviation:
    subject: str  # what changed: a COTW id, "File:<name>" or "P297:<code>" (part of the fingerprint)
    field: str  # stable field key (part of the fingerprint)
    old: Any
    new: Any  # machine value (part of the fingerprint)
    kind: str  # iso3 | code-lost | code-shared | code-new | capitals | coord | status | sitelink | flag-file | flag-revision | flag-license
    item: str  # Wikidata QID or "File:<name>" whose history the damping looks at
    prop: str  # "P36", "P297", "P576|P582", "sitelinks/dewiki", "file", …
    entries: list[str] = field(default_factory=list)  # affected COTW ids
    title: str = ""
    old_text: str = ""
    new_text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    impact: str = ""
    patches: list[tuple[str, str]] = field(default_factory=list)  # (cache attribute, key) updated on accept
    alert: bool = False  # a flag that is no longer free: must stand out

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.subject, self.field, self.new)


def fingerprint(subject: str, fld: str, new: Any) -> str:
    """Stable id of one deviation: entry + field + new value. The same change on every run gives
    the same fingerprint; a further change of the value gives a new one."""
    raw = json.dumps([subject, fld, new], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _fmt(value) -> str:
    if value is None or value == [] or value == {}:
        return "none"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_fmt(v)}" for k, v in value.items())
    return str(value)


def _wd(q: str) -> tuple[str, str]:
    return (f"Wikidata {q}", f"https://www.wikidata.org/wiki/{q}")


def _history(q: str) -> tuple[str, str]:
    return (f"{q} history (revision diffs)", f"https://www.wikidata.org/w/index.php?title={q}&action=history")


def _name(entry: dict) -> str:
    return f"{entry['id']} {entry['name']['en']}"


def km(a, b) -> float:
    """Great-circle distance between two ``[lat, lon]`` points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _labels(*snapshots: Snapshot) -> dict[str, str]:
    out: dict[str, str] = {}
    for snap in snapshots:
        for recs in snap.capitals.values():
            for r in recs:
                if r.get("label_en"):
                    out.setdefault(r["qid"], r["label_en"])
    return out


def _current_capitals(records: list[dict]) -> list[str]:
    """Which places count: non-deprecated P36 statements without an end time, with their role."""
    current = {
        r["qid"] + (f" role={r['role_qid']}" if r.get("role_qid") else "")
        for r in records
        if not r["rank"].rsplit("#", 1)[-1].startswith("deprecated") and not r.get("end")
    }
    return sorted(current, key=lambda s: (int(s.split()[0][1:]), s))


def _capitals_text(values: list[str], labels: dict[str, str]) -> str:
    out = []
    for v in values:
        q, _, role = v.partition(" ")
        out.append(f"{labels.get(q, q)} ({q}{', ' + role if role else ''})")
    return ", ".join(out) or "none"


def diff(entries: dict, base: Snapshot, live: Snapshot, overrides: dict | None = None, manifest: dict | None = None) -> list[Deviation]:
    """All deviations of ``live`` from ``base`` that matter for the deck, minus decided overrides.

    ``entries``: COTW id → entry. ``overrides``: ``{"capitals": …, "flags": …}`` as in
    ``data/overrides/``; ``manifest``: ``data/derived/flags.yaml`` (defaults: the committed files)."""
    overrides = overrides if overrides is not None else load_domain_overrides()
    manifest = manifest if manifest is not None else flags.load_manifest()
    cap_ov = overrides.get("capitals") or {}
    flag_ov = overrides.get("flags") or {}
    labels = _labels(live, base)
    out: list[Deviation] = []
    by_iso2 = {e["iso2"]: e for e in entries.values()}

    for cid, e in sorted(entries.items()):
        q = e["wikidata"]
        name = _name(e)

        # ISO 3166-1 alpha-3 (P298) of the entry's own item.
        b = next((r for r in base.countries.get(e["iso2"], []) if r["qid"] == q), None)
        l = next((r for r in live.countries.get(e["iso2"], []) if r["qid"] == q), None)
        if b and l and b.get("iso3") != l.get("iso3"):
            out.append(Deviation(
                cid, "iso3", b.get("iso3"), l.get("iso3"), "iso3", q, "P298", [cid],
                title=f"{name}: ISO 3166-1 alpha-3 changed",
                links=[_wd(q), _history(q)],
                impact=f"The ISO code cards and the `iso3` field (database: {e['iso3']}).",
                patches=[("countries", e["iso2"])],
            ))

        # Capitals (P36): which places count, with their role qualifiers.
        if q in base.capitals or q in live.capitals:
            bc, lc = _current_capitals(base.capitals.get(q, [])), _current_capitals(live.capitals.get(q, []))
            if bc != lc:
                out.append(Deviation(
                    cid, "capitals", bc, lc, "capitals", q, "P36", [cid],
                    title=f"{name}: capitals (P36) changed",
                    old_text=_capitals_text(bc, labels), new_text=_capitals_text(lc, labels),
                    links=[_wd(q), _history(q)],
                    impact="Capital cards and fields, capital markers on map 2 (`build-maps "
                    f"{cid}`), if the database follows. Database: "
                    + ", ".join(f"{c['name']['en']} ({c.get('wikidata')})" for c in e["capitals"]) + ".",
                    patches=[("capitals", q)],
                ))

        # Capital coordinates (P625) of the capitals the database uses.
        for cap in e["capitals"]:
            cq = cap.get("wikidata")
            ov = (cap_ov.get(e["iso2"]) or {}).get(cap["name"]["en"]) or {}
            if not cq or ov.get("lat") is not None or cq not in base.coords:
                continue  # coordinates fixed by an override, or never taken from Wikidata
            old, new = base.coords[cq], live.coords.get(cq)
            if new is not None and km(old, new) <= COORD_TOLERANCE_KM:
                continue
            new_v = [round(new[0], 4), round(new[1], 4)] if new else None
            moved = f" (moved {km(old, new):.1f} km)" if new else ""
            out.append(Deviation(
                cid, f"capital {cq} coordinates", [round(old[0], 4), round(old[1], 4)], new_v, "coord", cq, "P625", [cid],
                title=f"{name}: coordinates of {cap['name']['en']} changed",
                new_text=(f"{new_v[0]}, {new_v[1]}{moved}" if new_v else "no coordinates"),
                links=[_wd(cq), _history(cq)],
                impact=f"Capital marker on map 2 (`build-maps {cid}`); `lat`/`lon` of {cap['name']['en']} in the database.",
                patches=[("coords", cq)],
            ))

        # The entry's own status: dissolved (P576) / end time (P582).
        bs, ls = base.status.get(q, {}), live.status.get(q, {})
        if {k: v for k, v in bs.items() if v} != {k: v for k, v in ls.items() if v}:
            out.append(Deviation(
                cid, "status", bs, ls, "status", q, "P576|P582", [cid],
                title=f"{name}: dissolved/end time (P576/P582) changed",
                links=[_wd(q), _history(q)],
                impact=f"Possibly the entry itself (status `{e['status']}`): retire or keep. Entries are never deleted, COTW ids are frozen (DECISIONS A1).",
                patches=[("status", q)],
            ))

        # EN/DE Wikipedia sitelinks.
        for lang, site in wikidata.WIKIS.items():
            old, new = base.sitelinks.get(q, {}).get(lang), live.sitelinks.get(q, {}).get(lang)
            if old != new and q in live.sitelinks:
                out.append(Deviation(
                    cid, f"wikipedia.{lang}", old, new, "sitelink", q, f"sitelinks/{site}", [cid],
                    title=f"{name}: {lang.upper()} Wikipedia article changed",
                    links=[_wd(q), _history(q)] + ([(f"{site} article", wikidata.wikipedia_url(lang, new))] if new else []),
                    impact=f"The Wikipedia link on the {lang.upper()} cards (`wikipedia.{lang}`: {e['wikipedia'].get(lang, 'none')}).",
                    patches=[("sitelinks", q)],
                ))

        # Flag selection (P41), unless an override fixes the file.
        if not (flag_ov.get(cid) or {}).get("file"):
            old_file, _ = flags.select_file(base.p41.get(q, []))
            new_file, reason = flags.select_file(live.p41.get(q, []))
            if old_file != new_file:
                info = live.commons.get(new_file or "", {})
                lic = info.get("license")
                nonfree = bool(new_file) and not flags.license_allowed(lic)
                out.append(Deviation(
                    cid, "flag file", old_file, new_file or reason, "flag-file", q, "P41", [cid],
                    title=("NON-FREE " if nonfree else "") + f"{name}: flag file (P41) changed",
                    new_text=(f"{new_file} (license: {lic or 'unknown'})" if new_file else f"no unambiguous file: {reason}"),
                    links=[_wd(q), _history(q)] + ([("Commons file page", info["page"])] if info.get("page") else []),
                    impact=f"The flag `media/cotw-{cid}-flag.svg` and the flag cards (`fetch-flags`)."
                    + (" The new file is not public domain/CC0: it cannot ship without an override or a different file." if nonfree else ""),
                    patches=[("p41", q)],
                    alert=nonfree,
                ))

    # Commons: a new revision or a changed license of a file in use (one deviation per file).
    users: dict[str, list[str]] = {}
    for cid, rec in sorted(manifest.items()):
        if cid in entries:
            users.setdefault(rec["file"], []).append(cid)
    for file, cids in sorted(users.items()):
        old, new = base.commons.get(file, {}), live.commons.get(file)
        who = ", ".join(_name(entries[c]) for c in cids)
        page = (new or {}).get("page") or old.get("page")
        links = [("Commons file page", page), ("Commons file history", f"https://commons.wikimedia.org/w/index.php?title=File:{urllib.parse.quote(file.replace(' ', '_'))}&action=history")]
        if not new or new.get("missing"):
            out.append(Deviation(
                f"File:{file}", "flag revision", old.get("sha1"), None, "flag-revision", f"File:{file}", "file", cids,
                title=f"Flag file deleted or renamed on Commons: {file}", new_text="file missing on Commons",
                links=links, impact=f"The flag of {who}: `fetch-flags` fails until P41 or an override points to another file.",
            ))
            continue
        if new.get("sha1") != old.get("sha1"):
            out.append(Deviation(
                f"File:{file}", "flag revision", old.get("sha1"), new.get("sha1"), "flag-revision", f"File:{file}", "file", cids,
                title=f"New revision of the flag file {file}",
                old_text=f"sha1 {old.get('sha1')}", new_text=f"sha1 {new.get('sha1')}",
                links=links, impact=f"The flag SVG of {who} and their flag cards (`fetch-flags`). Check the new drawing on the file history page first.",
            ))
        if new.get("license") != old.get("license"):
            lic = new.get("license")
            accepted = any((flag_ov.get(c) or {}).get("license") == lic for c in cids)
            nonfree = not flags.license_allowed(lic) and not accepted
            out.append(Deviation(
                f"File:{file}", "flag license", old.get("license"), lic, "flag-license", f"File:{file}", "file", cids,
                title=("NON-FREE " if nonfree else "") + f"License of the flag file {file} changed",
                links=links,
                impact=f"The flag of {who}."
                + (" The file is no longer public domain/CC0: it must be replaced (another file via `data/overrides/flags.yaml`) or explicitly accepted with a license override and reason." if nonfree else ""),
                alert=nonfree,
            ))

    # Scope drift: items gaining or losing an ISO 3166-1 alpha-2 code (P297).
    if base.iso_codes:
        for code in sorted(set(base.iso_codes) | set(live.iso_codes)):
            b, l = set(base.iso_codes.get(code, [])), set(live.iso_codes.get(code, []))
            if b == l:
                continue
            added, removed = sorted(l - b, key=lambda q: int(q[1:])), sorted(b - l, key=lambda q: int(q[1:]))
            entry = by_iso2.get(code)
            if entry and entry["wikidata"] in removed:
                q = entry["wikidata"]
                out.append(Deviation(
                    entry["id"], "iso2", code, None, "code-lost", q, "P297", [entry["id"]],
                    title=f"{_name(entry)}: item {q} no longer carries ISO code {code}",
                    new_text=f"P297 {code} now on: {_fmt(sorted(l, key=lambda x: int(x[1:])))}",
                    links=[_wd(q), _history(q)],
                    impact="Scope: the entry may be up for retirement. Entries are never deleted automatically; COTW ids are frozen (DECISIONS A1).",
                    patches=[("iso_codes", code), ("countries", code)],
                ))
            elif entry and added:
                out.append(Deviation(
                    entry["id"], f"P297 {code} holders", sorted(b, key=lambda q: int(q[1:])), sorted(l, key=lambda q: int(q[1:])), "code-shared", added[0], "P297", [entry["id"]],
                    title=f"{_name(entry)}: ISO code {code} now also on {', '.join(added)}",
                    links=[_wd(q) for q in added] + [_history(added[0])],
                    impact=f"Probably none (the database uses {entry['wikidata']}); if the entry should move to the new item, `data/overrides/wikidata.yaml` decides.",
                    patches=[("iso_codes", code), ("countries", code)],
                ))
            elif not entry and added:
                out.append(Deviation(
                    f"P297:{code}", f"P297 {code}", sorted(b, key=lambda q: int(q[1:])), sorted(l, key=lambda q: int(q[1:])), "code-new", added[0], "P297", [],
                    title=f"New ISO 3166-1 code {code} on {', '.join(added)}: new entry candidate",
                    links=[_wd(q) for q in added] + [_history(added[0])],
                    impact="Scope: a candidate for a new entry (next free COTW id, `data/ids.yaml`). Nothing happens unless decided.",
                    patches=[("iso_codes", code)],
                ))

    for d in out:
        d.old_text = d.old_text or _fmt(d.old)
        d.new_text = d.new_text or _fmt(d.new)
    return out


def load_domain_overrides() -> dict:
    cap = yaml.safe_load((OVERRIDES / "capitals.yaml").read_text(encoding="utf-8")) or {}
    return {"capitals": cap.get("capitals") or {}, "flags": flags.load_overrides()}


def load_rejections(path: Path = MONITORING_OVERRIDES) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): v for k, v in (data.get("rejected") or {}).items()}


def suppress(devs: list[Deviation], rejections: dict) -> tuple[list[Deviation], list[Deviation]]:
    """``(kept, rejected)``: deviations whose fingerprint is rejected in monitoring.yaml are dropped."""
    kept = [d for d in devs if d.fingerprint not in rejections]
    return kept, [d for d in devs if d.fingerprint in rejections]


def order(devs: list[Deviation]) -> list[Deviation]:
    """Non-free flags first (the flood cap must never hide them), then by subject and field."""
    return sorted(devs, key=lambda d: (not d.alert, d.subject, d.field))


# --- vandalism damping --------------------------------------------------------------------------


def _get_json(url: str, params: dict) -> dict:
    return flags._get(url, params).json()


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def wikidata_modified(qids: list[str], get=_get_json) -> dict[str, datetime]:
    out = {}
    for chunk in wikidata._chunks(sorted(set(qids)), 50):
        data = get(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(chunk), "props": "info", "format": "json"})
        for q, ent in data.get("entities", {}).items():
            if ent.get("modified"):
                out[q] = _ts(ent["modified"])
    return out


def entity_at(qid: str, before: datetime | None, get=_get_json) -> dict | None:
    """The item's JSON at its newest revision at or before ``before`` (``None``: current)."""
    params = {
        "action": "query", "prop": "revisions", "titles": qid, "rvlimit": "1", "rvprop": "ids|timestamp|content",
        "rvslots": "main", "format": "json", "formatversion": "2",
    }
    if before is not None:
        params |= {"rvstart": before.strftime("%Y-%m-%dT%H:%M:%SZ"), "rvdir": "older"}
    pages = get(WIKIDATA_API, params).get("query", {}).get("pages", [])
    revs = (pages[0].get("revisions") if pages else None) or []
    return json.loads(revs[0]["slots"]["main"]["content"]) if revs else None


def entity_part(entity: dict | None, prop: str):
    """The part of an item a deviation depends on: claims of one or more properties, or a sitelink."""
    if entity is None:
        return None
    if prop.startswith("sitelinks/"):
        return (entity.get("sitelinks") or {}).get(prop.split("/", 1)[1], {}).get("title")
    claims = entity.get("claims") or {}
    return {p: claims.get(p, []) for p in prop.split("|")}


def commons_touched(files: list[str], get=_get_json) -> dict[str, datetime]:
    """Latest change per Commons file: page edit (license templates) or file upload."""
    out: dict[str, datetime] = {}
    for chunk in wikidata._chunks(sorted(set(files)), 50):
        data = get(flags.COMMONS_API, {
            "action": "query", "titles": "|".join(f"File:{f}" for f in chunk), "prop": "revisions|imageinfo",
            "rvprop": "timestamp", "iiprop": "timestamp", "format": "json", "formatversion": "2", "redirects": "1",
        })["query"]
        redirects = {r["to"]: r["from"] for r in data.get("redirects", [])}
        for page in data.get("pages", []):
            stamps = [r["timestamp"] for r in page.get("revisions") or []] + [i["timestamp"] for i in page.get("imageinfo") or []]
            if stamps:
                title = redirects.get(page["title"], page["title"])
                out[title.removeprefix("File:")] = max(_ts(s) for s in stamps)
    return out


def damp(devs: list[Deviation], now: datetime, get=_get_json) -> tuple[list[Deviation], list[Deviation]]:
    """``(kept, damped)``. A deviation is damped when the part it depends on changed within
    ``DAMPING``: the item was edited in the window *and* the relevant claims/sitelink differ
    between the last revision before the window and now. Commons files are damped when the page
    or file changed in the window. Damped deviations come back on the next run."""
    cutoff = now - DAMPING
    items = sorted({d.item for d in devs if not d.item.startswith("File:")})
    files = sorted({d.item.removeprefix("File:") for d in devs if d.item.startswith("File:")})
    modified = wikidata_modified(items, get) if items else {}
    touched = commons_touched(files, get) if files else {}
    before: dict[str, dict | None] = {}
    current: dict[str, dict | None] = {}
    kept, damped = [], []
    for d in devs:
        if d.item.startswith("File:"):
            recent = touched.get(d.item.removeprefix("File:"), cutoff) > cutoff
        elif modified.get(d.item, cutoff) <= cutoff:
            recent = False
        else:
            if d.item not in before:
                before[d.item] = entity_at(d.item, cutoff, get)
                current[d.item] = entity_at(d.item, None, get)
            recent = entity_part(before[d.item], d.prop) != entity_part(current[d.item], d.prop)
        (damped if recent else kept).append(d)
    return kept, damped


# --- issues -------------------------------------------------------------------------------------


def accept_steps(d: Deviation) -> list[str]:
    fp = d.fingerprint
    ids = " ".join(d.entries)
    steps = {
        "iso3": [f"python -m cotw accept-wikidata {fp}  # updates the cache and `iso3` in the entry"],
        "coord": [f"python -m cotw accept-wikidata {fp}  # updates the caches and `lat`/`lon` in the entry", f"python -m cotw build-maps {ids}"],
        "sitelink": [f"python -m cotw accept-wikidata {fp}  # updates the cache and the `wikipedia` link"],
        "capitals": [f"python -m cotw accept-wikidata {fp}  # updates the cache only", "edit `capitals` in the entry by hand if the deck should follow", f"python -m cotw build-maps {ids}"],
        "status": [f"python -m cotw accept-wikidata {fp}  # updates the cache only", "decide on the entry (`status`, retire); never delete it"],
        "code-lost": [f"python -m cotw accept-wikidata {fp}  # updates the caches only", "decide on the entry; never delete it (frozen ids)"],
        "code-shared": [f"python -m cotw accept-wikidata {fp}  # updates the caches only", "if the entry should use the new item: `data/overrides/wikidata.yaml`"],
        "code-new": [f"python -m cotw accept-wikidata {fp}  # updates the cache only", "a new entry needs a YAML file, the next free id in `data/ids.yaml`, maps and a flag"],
        "flag-file": [f"python -m cotw accept-wikidata {fp}  # updates data/wikidata/flags.json", "python -m cotw fetch-flags --offline-wikidata"],
        "flag-revision": ["python -m cotw fetch-flags --offline-wikidata"],
        "flag-license": ["python -m cotw fetch-flags --offline-wikidata  # fails for a non-free license until an override decides"],
    }[d.kind]
    return steps + ["python -m cotw validate", "python -m pytest  # includes the EN/DE coexistence import test", "python -m cotw build-deck"]


def _safe(text: str) -> str:
    """Upstream text (labels, file names) must not smuggle HTML comments such as a fake fingerprint."""
    return text.replace("<", "&lt;")


def render_issue(d: Deviation) -> tuple[str, str]:
    subject = ", ".join(d.entries) or d.subject
    lines = []
    if d.alert:
        lines += ["> [!WARNING]", "> **Non-free flag.** This file is no longer public domain/CC0 and must not ship as is.", ""]
    lines += [
        f"**Entry:** {subject}" + (f" (`{d.subject}`)" if d.subject not in d.entries else ""),
        f"**Field:** {d.field}",
        f"**Old:** {_safe(d.old_text)}",
        f"**New:** {_safe(d.new_text)}",
        "",
        "**Links:** " + " · ".join(f"[{label}]({url})" for label, url in d.links),
        "",
        f"**What would change in the deck:** {d.impact}",
        "",
        "**Accept** (run locally, then commit):",
        "```sh",
        *accept_steps(d),
        "```",
        "",
        "**Reject:** add this to `data/overrides/monitoring.yaml`, commit, and close this issue:",
        "```yaml",
        "rejected:",
        f"  '{d.fingerprint}':",
        f"    subject: '{d.subject}'",
        f"    field: {d.field}",
        "    reason: <why the deck keeps the old value>",
        "```",
        "",
        "Found by the weekly Wikidata check (`python -m cotw check-wikidata`, docs/MONITORING.md). Nothing was applied.",
        "",
        f"<!-- cotw-monitor fingerprint={d.fingerprint} -->",
    ]
    return d.title, "\n".join(lines)


def render_summary(overflow: list[Deviation], cap: int) -> tuple[str, str]:
    lines = [
        f"The weekly Wikidata check found more new deviations than the per-run cap of {cap}.",
        "These are not filed yet; each later run files the next batch (and updates this issue).",
        "",
        "| Entry | Field | Old | New | Fingerprint |",
        "|---|---|---|---|---|",
    ]
    for d in overflow:
        cells = [", ".join(d.entries) or d.subject, d.field, _safe(d.old_text), _safe(d.new_text), f"`{d.fingerprint}`"]
        lines.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    lines += ["", SUMMARY_MARKER]
    return f"Wikidata check: {len(overflow)} more deviations waiting", "\n".join(lines)


class Gitea:
    """The few Gitea API calls the monitor needs. The token is sent, never printed."""

    def __init__(self, url: str, repo: str, token: str):
        self.base = url.rstrip("/") + "/api/v1"
        self.repo = repo
        self._token = token

    def _req(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"token {self._token}", "Content-Type": "application/json", "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            hint = " (token lacks the permission: see docs/MONITORING.md, Token)" if exc.code in (401, 403) else ""
            raise RuntimeError(f"Gitea {method} {path}: HTTP {exc.code}{hint} {exc.read().decode('utf-8', 'replace')[:300]}") from None

    def repository(self) -> dict:
        return self._req("GET", f"/repos/{self.repo}")

    def issues(self) -> list[dict]:
        """Every issue, open and closed (dedupe must see decided ones too)."""
        out, page = [], 1
        while True:
            batch = self._req("GET", f"/repos/{self.repo}/issues", {"state": "all", "type": "issues", "limit": 50, "page": page})
            out += batch
            if len(batch) < 50:
                return out
            page += 1

    def label_id(self, name: str) -> int:
        for label in self._req("GET", f"/repos/{self.repo}/labels", {"limit": 50}):
            if label["name"] == name:
                return label["id"]
        raise RuntimeError(f"label {name!r} does not exist in {self.repo}")

    def create_issue(self, title: str, body: str, labels: list[int]) -> dict:
        return self._req("POST", f"/repos/{self.repo}/issues", body={"title": title, "body": body, "labels": labels})

    def edit_issue(self, number: int, **fields) -> dict:
        return self._req("PATCH", f"/repos/{self.repo}/issues/{number}", body=fields)


def known_fingerprints(issues: list[dict]) -> set[str]:
    return {fp for i in issues for fp in FINGERPRINT_RE.findall(i.get("body") or "")}


def file_issues(devs: list[Deviation], client, max_issues: int = DEFAULT_MAX_ISSUES, log=print) -> dict:
    """Open one issue per new deviation (up to ``max_issues``), the rest go into one summary issue."""
    existing = client.issues()
    known = known_fingerprints(existing)
    fresh = [d for d in order(devs) if d.fingerprint not in known]
    filed, overflow = fresh[:max_issues], fresh[max_issues:]
    label = client.label_id(LABEL) if fresh else None
    for d in filed:
        title, body = render_issue(d)
        issue = client.create_issue(title, body, [label])
        log(f"filed #{issue.get('number')}: {title}")
    summaries = [i for i in existing if SUMMARY_MARKER in (i.get("body") or "") and i.get("state") == "open"]
    if overflow:
        title, body = render_summary(overflow, max_issues)
        if summaries:
            client.edit_issue(summaries[0]["number"], title=title, body=body)
            log(f"updated summary #{summaries[0]['number']}: {len(overflow)} waiting")
        else:
            issue = client.create_issue(title, body, [label])
            log(f"filed summary #{issue.get('number')}: {len(overflow)} waiting")
    else:
        for s in summaries:
            client.edit_issue(s["number"], body="All deviations are filed as issues.\n\n" + SUMMARY_MARKER, state="closed")
            log(f"closed summary #{s['number']}")
    return {"known": len(devs) - len(fresh), "filed": len(filed), "overflow": len(overflow)}


# --- commands -----------------------------------------------------------------------------------


def load_entries() -> dict:
    from . import schema

    return {e["id"]: e for e in schema.load_all(COUNTRIES).values()}


def collect(now: datetime | None = None, log=print) -> tuple[list[Deviation], dict]:
    """Fetch, diff, suppress, damp (network). Returns ``(deviations, report)``."""
    now = now or datetime.now(timezone.utc)
    entries = load_entries()
    base = load_baseline()
    live = fetch_live(entries, base)
    devs = diff(entries, base, live)
    devs, rejected = suppress(devs, load_rejections())
    devs, damped = damp(devs, now)
    for d in damped:
        log(f"damped (changed < {DAMPING.total_seconds() / 3600:.0f} h ago, next run): {d.title}")
    return order(devs), {"rejected": len(rejected), "damped": len(damped), "live": live}


def gitea_config(url: str | None, repo: str | None) -> tuple[str | None, str | None, str | None]:
    url = url or os.environ.get("GITHUB_SERVER_URL") or os.environ.get("GITEA_SERVER_URL")
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    return url, repo, os.environ.get("COTW_MONITOR_TOKEN") or None


def check(dry_run: bool, max_issues: int, url: str | None = None, repo: str | None = None, log=print) -> int:
    url, repo, token = gitea_config(url, repo)
    if not dry_run and not (url and repo and token):
        log("no Gitea URL/repository/COTW_MONITOR_TOKEN: dry run")
        dry_run = True
    devs, report = collect(log=log)
    client = Gitea(url, repo, token) if url and repo and token else None
    known: set[str] = set()
    if client:  # read-only: shows what is filed already, before anything is written
        perms = client.repository().get("permissions") or {}
        log("token permissions on the repository: " + ", ".join(f"{k}={v}" for k, v in sorted(perms.items())))
        known = known_fingerprints(client.issues())
    log(f"{len(devs)} deviations ({report['rejected']} rejected via overrides, {report['damped']} damped)")
    if dry_run:
        fresh = [d for d in devs if d.fingerprint not in known]
        for i, d in enumerate(fresh):
            tag = "would file" if i < max_issues else "summary"
            log(f"[{tag}] {d.fingerprint} {d.title}: {d.old_text} -> {d.new_text}")
        for d in devs:
            if d.fingerprint in known:
                log(f"[filed already] {d.fingerprint} {d.title}")
        log(f"dry run: {min(len(fresh), max_issues)} issues + {'1 summary' if len(fresh) > max_issues else 'no summary'} would be written, nothing touched")
        return 0
    result = file_issues(devs, client, max_issues, log)
    log(f"{result['filed']} filed, {result['known']} filed before, {result['overflow']} in the summary")
    return 0


def accept(fp: str, log=print) -> int:
    """Accept one deviation: update just its keys in the caches (plus the database field for the
    mechanical kinds), then print the remaining steps. Other pending deviations stay pending."""
    from .importer import dump_entry
    from .paths import WIKIDATA

    devs, report = collect(log=lambda *_: None)
    d = next((x for x in devs if x.fingerprint == fp), None)
    if d is None:
        log(f"{fp}: not a current deviation (accepted already, rejected, damped, or the value changed again)")
        return 1
    live: Snapshot = report["live"]
    files = {
        "countries": WIKIDATA / "countries.json", "iso_codes": WIKIDATA / "iso-codes.json", "capitals": WIKIDATA / "capitals.json",
        "status": WIKIDATA / "status.json", "sitelinks": WIKIDATA / "sitelinks.json", "p41": WIKIDATA / "flags.json",
    }
    for attr, key in d.patches:
        if attr == "coords":  # coordinates live inside the capitals and places records
            for name in ("capitals.json", "places.json"):
                path = WIKIDATA / name
                data = json.loads(path.read_text(encoding="utf-8"))
                for recs in data.values():
                    for r in recs:
                        if r["qid"] == key:
                            r["coord"] = live.coords.get(key)
                wikidata.dump(path, data)
            log(f"updated data/wikidata/capitals.json, places.json [{key} coordinates]")
            continue
        path = files[attr]
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        value = getattr(live, attr).get(key)
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        wikidata.dump(path, dict(sorted(data.items())))
        log(f"updated {path.relative_to(path.parents[2])} [{key}]")

    from . import schema

    paths = {e["id"]: p for p, e in schema.load_all(COUNTRIES).items()}
    for cid in d.entries if d.kind in ("iso3", "coord", "sitelink") else []:
        path = paths[cid]
        entry = yaml.safe_load(path.read_text(encoding="utf-8"))
        if d.kind == "iso3" and d.new:
            entry["iso3"] = d.new
        elif d.kind == "coord" and d.new:
            for cap in entry["capitals"]:
                if cap.get("wikidata") == d.item:
                    cap["lat"], cap["lon"] = round(d.new[0], 5), round(d.new[1], 5)
        elif d.kind == "sitelink":
            lang = d.field.split(".", 1)[1]
            if lang == "de":
                entry["wikipedia"] = wikidata.wikipedia_links(entry["wikipedia"]["en"], live.sitelinks.get(entry["wikidata"]))
            elif d.new:
                entry["wikipedia"]["en"] = wikidata.wikipedia_url("en", d.new)
        path.write_text(dump_entry(entry), encoding="utf-8")
        log(f"updated {path.relative_to(path.parents[2])}")
    log("next:")
    for step in accept_steps(d)[1:] if d.patches else accept_steps(d):
        log(f"  {step}")
    return 0
