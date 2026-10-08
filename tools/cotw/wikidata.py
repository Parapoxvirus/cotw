"""Wikidata enrichment: QIDs, labels, capitals with roles and coordinates.

``fetch_all`` talks to the SPARQL endpoint and writes JSON caches under ``data/wikidata/``.
The caches are committed, so the import and the tests never need the network; refresh them
with ``python -m cotw fetch-wikidata``.

Labels and Wikipedia sitelinks are fetched for every registered locale (``cotw.languages``),
as ``label_<code>`` (``label_de-CH``) in the cache records and ``{code: title}`` in the
sitelinks. The sources of a locale come from ``data/locales.yaml``: its Wikipedia (``wiki``,
the article URL prefix ``wikipedia``) and its Wikidata label languages in fallback order
(``wikidata``: ``[de-ch, de]``). A locale's label is the first value along that chain.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import languages, locales
from .paths import WIKIDATA

SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = os.environ.get(
    "COTW_USER_AGENT", "cotw-build/1.0 (https://github.com/Parapoxvirus/cotw)"
)
COUNTRIES_CACHE = WIKIDATA / "countries.json"
CAPITALS_CACHE = WIKIDATA / "capitals.json"
PLACES_CACHE = WIKIDATA / "places.json"

# Wikidata labels (P3831 "object has role" / P518 "applies to part") → COTW capital roles.
ROLE_QIDS = {
    "Q1901835": "seat_of_government",
    "Q35798": "executive",
    "Q11204": "legislative",
    "Q105985": "judicial",
    "Q712144": "de_facto",
    "Q132555": "de_jure",
}


def _sparql(query: str, retries: int = 4) -> list[dict]:
    import requests  # optional dependency, only for fetching

    for attempt in range(retries):
        try:
            resp = requests.get(
                SPARQL_URL,
                params={"query": query},
                headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
                timeout=180,
            )
        except requests.exceptions.Timeout:
            time.sleep(10 * (attempt + 1))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(10 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()["results"]["bindings"]
    raise RuntimeError(f"SPARQL failed after {retries} attempts")


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _val(binding: dict, key: str) -> str | None:
    return binding[key]["value"] if key in binding else None


def _point(wkt: str | None) -> tuple[float, float] | None:
    """``Point(lon lat)`` → ``(lat, lon)``."""
    if not wkt or not wkt.startswith("Point("):
        return None
    lon, lat = wkt[6:-1].split()
    return float(lat), float(lon)


def chain(code: str) -> tuple[str, ...]:
    """A locale's Wikidata label languages in fallback order (``de-CH`` → ``("de-ch", "de")``)."""
    return locales.get(code).wikidata


def label_languages(codes=None) -> list[str]:
    """The Wikidata label languages of the locales' chains (default: every registered locale),
    each once, in registry and chain order (``["en", "de-ch", "de"]``)."""
    return list(dict.fromkeys(lang for code in codes or languages.LANGUAGES for lang in chain(code)))


def resolve(values: dict[str, str | None], code: str) -> str | None:
    """A locale's label from the labels per Wikidata language: the first non-null along its chain."""
    return next((values[lang] for lang in chain(code) if values.get(lang)), None)


def _var(code: str) -> str:
    """SPARQL variable of a locale's label: ``de-CH`` → ``label_de_CH`` (``-`` is not allowed)."""
    return "label_" + code.replace("-", "_")


def _label_vars() -> str:
    return " ".join(f"?{_var(code)}" for code in languages.LANGUAGES)


def _label_optionals(codes) -> str:
    """Per locale one OPTIONAL label per chain language, bound to the first one found."""
    lines = []
    for code in codes:
        var, langs = _var(code), chain(code)
        parts = [f"?{var}_{i}" for i in range(len(langs))]
        lines += [f'          OPTIONAL {{ ?item rdfs:label {v} FILTER(LANG({v}) = "{lang}") }}' for v, lang in zip(parts, langs)]
        lines.append(f"          BIND(COALESCE({', '.join(parts)}) AS ?{var})")
    return "\n".join(lines)


def _chunks(items: list[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_countries(iso2_codes: list[str]) -> dict:
    """All items carrying one of the ISO-2 codes (P297). Ambiguities are kept, resolved later."""
    out: dict[str, list[dict]] = {}
    for chunk in _chunks(sorted(iso2_codes), 25):
        values = " ".join(f'"{c}"' for c in chunk)
        query = f"""
        SELECT ?iso ?item ?iso3 {_label_vars()} WHERE {{
          VALUES ?iso {{ {values} }}
          ?item wdt:P297 ?iso .
          OPTIONAL {{ ?item wdt:P298 ?iso3 }}
{_label_optionals(languages.LANGUAGES)}
        }}"""
        for b in _sparql(query):
            iso = _val(b, "iso")
            rec = {
                "qid": _qid(_val(b, "item")),
                "iso3": _val(b, "iso3"),
                **{f"label_{code}": _val(b, _var(code)) for code in languages.LANGUAGES},
            }
            bucket = out.setdefault(iso, [])
            # Several optional values may multiply rows; keep one record per QID, first wins.
            if not any(r["qid"] == rec["qid"] for r in bucket):
                bucket.append(rec)
    return {k: sorted(v, key=lambda r: int(r["qid"][1:])) for k, v in sorted(out.items())}


def fetch_capitals(qids: list[str]) -> dict:
    """P36 statements per country: capital QID, labels, coordinates, rank, dates, role."""
    out: dict[str, list[dict]] = {}
    for chunk in _chunks(sorted(qids), 25):
        values = " ".join(f"wd:{q}" for q in chunk)
        query = f"""
        SELECT ?item ?cap ?coord ?rank ?start ?end ?role ?part WHERE {{
          VALUES ?item {{ {values} }}
          ?item p:P36 ?st . ?st ps:P36 ?cap . ?st wikibase:rank ?rank .
          OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }}
          OPTIONAL {{ ?st pq:P3831 ?role }} OPTIONAL {{ ?st pq:P518 ?part }}
          OPTIONAL {{ ?cap wdt:P625 ?coord }}
        }}"""
        for b in _sparql(query):
            item = _qid(_val(b, "item"))
            role_qid = _qid(_val(b, "role")) if _val(b, "role") else None
            part_qid = _qid(_val(b, "part")) if _val(b, "part") else None
            rec = {
                "qid": _qid(_val(b, "cap")),
                **{f"label_{code}": None for code in languages.LANGUAGES},
                "coord": _point(_val(b, "coord")),
                "rank": _qid(_val(b, "rank")).lower().replace("rank", ""),
                "start": _val(b, "start"),
                "end": _val(b, "end"),
                "role": ROLE_QIDS.get(role_qid or part_qid or "", None),
                "role_qid": role_qid or part_qid,
            }
            bucket = out.setdefault(item, [])
            if rec not in bucket:
                bucket.append(rec)
    result = {k: sorted(v, key=lambda r: (int(r["qid"][1:]), r["start"] or "")) for k, v in sorted(out.items())}
    labels = fetch_labels(sorted({r["qid"] for recs in result.values() for r in recs}))
    for recs in result.values():
        for r in recs:
            for code, label in labels.get(r["qid"], {}).items():
                r[f"label_{code}"] = label
    return result


def fetch_labels(qids: list[str]) -> dict[str, dict[str, str | None]]:
    """Labels in every registered locale via the label service (cheap even for hundreds of
    items): ``{qid: {code: label or None}}``. The base locale's chain goes to the label service
    as its language list, the others are resolved like ``_label_optionals``."""
    base, others = languages.BASE, [c for c in languages.LANGUAGES if c != languages.BASE]
    out: dict[str, dict[str, str | None]] = {}
    for chunk in _chunks(qids, 150):
        values = " ".join(f"wd:{q}" for q in chunk)
        query = f"""
        SELECT ?item {_label_vars()} WHERE {{
          VALUES ?item {{ {values} }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{",".join(chain(base))}". ?item rdfs:label ?{_var(base)} }}
{_label_optionals(others)}
        }}"""
        for b in _sparql(query):
            q = _qid(_val(b, "item"))
            labels = {code: _val(b, _var(code)) for code in languages.LANGUAGES}
            if labels[base] == q:  # label service falls back to the QID when no base label exists
                labels[base] = None
            out[q] = labels
    missing = [q for q in qids if (out.get(q) or {}).get(base) is None]
    if missing:  # second opinion from the entity API (WDQS may lag behind edits)
        out.update(fetch_labels_api(missing))
    return out


def fetch_label_values(qids: list[str], langs: list[str]) -> dict[str, dict[str, str | None]]:
    """Labels per Wikidata language from the entity API: ``{qid: {lang: label or None}}``."""
    import requests

    out = {}
    for chunk in _chunks(qids, 50):
        resp = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "labels",
                "languages": "|".join(langs),
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=60,
        )
        resp.raise_for_status()
        for q, ent in resp.json().get("entities", {}).items():
            labels = ent.get("labels", {})
            out[q] = {lang: labels.get(lang, {}).get("value") for lang in langs}
    return out


def fetch_labels_api(qids: list[str]) -> dict[str, dict[str, str | None]]:
    """Like ``fetch_labels``, from the entity API: ``{qid: {code: label or None}}``."""
    values = fetch_label_values(qids, label_languages())
    return {q: {code: resolve(v, code) for code in languages.LANGUAGES} for q, v in values.items()}


def fetch_places(labels: list[str]) -> dict:
    """Fallback lookup for capitals not linked via P36: items by exact base label with coordinates.

    The records carry the labels of the other locales (``label_<code>``); the base label (the
    first language of the base locale's chain) is the key."""
    out: dict[str, list[dict]] = {}
    for chunk in _chunks(sorted(set(labels)), 25):
        values = " ".join(f"{json.dumps(l)}@{chain(languages.BASE)[0]}" for l in chunk)
        query = f"""
        SELECT ?label ?item ?coord ?country WHERE {{
          VALUES ?label {{ {values} }}
          ?item rdfs:label ?label .
          ?item wdt:P625 ?coord .
          ?item wdt:P17 ?country .
        }}"""
        for b in _sparql(query):
            label = _val(b, "label")
            rec = {
                "qid": _qid(_val(b, "item")),
                **{f"label_{code}": None for code in languages.LANGUAGES if code != languages.BASE},
                "coord": _point(_val(b, "coord")),
                "country": _qid(_val(b, "country")),
            }
            bucket = out.setdefault(label, [])
            if rec not in bucket:
                bucket.append(rec)
    result = {k: sorted(v, key=lambda r: int(r["qid"][1:])) for k, v in sorted(out.items())}
    labels = fetch_labels(sorted({r["qid"] for recs in result.values() for r in recs}))
    for recs in result.values():
        for r in recs:
            for code, label in labels.get(r["qid"], {}).items():
                if code != languages.BASE:
                    r[f"label_{code}"] = label
    return result


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_countries() -> dict:
    return _load(COUNTRIES_CACHE)


def load_capitals() -> dict:
    return _load(CAPITALS_CACHE)


def load_places() -> dict:
    return _load(PLACES_CACHE) if PLACES_CACHE.exists() else {}


def dump(path: Path, data: dict) -> None:
    _dump(path, data)


SITELINKS_CACHE = WIKIDATA / "sitelinks.json"


def wikis() -> dict[str, str]:
    """Locale → Wikidata site ID of its Wikipedia, in registry order (``{"en-US": "enwiki", …}``).
    Sister locales may share a Wikipedia (``de-CH``, ``de-DE``: ``dewiki``)."""
    return {code: locales.get(code).wiki for code in languages.LANGUAGES}


def fetch_sitelinks(qids: list[str]) -> dict:
    """Wikipedia article titles per item and locale (``{qid: {"en-US": title, "de-CH": title}}``)."""
    sites = wikis()
    import requests

    out: dict[str, dict[str, str]] = {}
    for chunk in _chunks(sorted(set(qids), key=lambda q: int(q[1:])), 50):
        resp = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "sitelinks",
                "sitefilter": "|".join(dict.fromkeys(sites.values())),
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=60,
        )
        resp.raise_for_status()
        for q, ent in resp.json().get("entities", {}).items():
            links = ent.get("sitelinks", {})
            out[q] = {lang: links[site]["title"] for lang, site in sites.items() if site in links}
    return dict(sorted(out.items(), key=lambda kv: int(kv[0][1:])))


def load_sitelinks() -> dict:
    return _load(SITELINKS_CACHE) if SITELINKS_CACHE.exists() else {}


def wikipedia_url(locale: str, title: str) -> str:
    """Article URL in the style of the database: the locale's URL prefix (data/locales.yaml),
    spaces as ``_``, letters unescaped."""
    path = title.replace(" ", "_")
    for ch in "%?#\"&":
        path = path.replace(ch, f"%{ord(ch):02X}")
    return locales.get(locale).wikipedia + path


def wikipedia_links(en_url: str, sitelinks: dict | None) -> dict[str, str]:
    """``wikipedia`` map of an entry: the base locale's as chosen in the database (normalized),
    every other registered locale from its sitelink (``dewiki``, …).

    No key for a locale whose Wikipedia has no article on the item; the deck then falls back
    to the base locale's.
    """
    from urllib.parse import unquote

    base = languages.BASE
    prefix = locales.get(base).wikipedia
    out = {base: wikipedia_url(base, unquote(en_url[len(prefix):])) if en_url.startswith(prefix) else en_url}
    for code in languages.LANGUAGES:
        if code != base and sitelinks and sitelinks.get(code):
            out[code] = wikipedia_url(code, sitelinks[code])
    return out


# --- change monitoring baselines (step 5, docs/MONITORING.md) -----------------------------------

STATUS_CACHE = WIKIDATA / "status.json"
ISO_CODES_CACHE = WIKIDATA / "iso-codes.json"


def fetch_status(qids: list[str]) -> dict:
    """Dissolved (P576) and end time (P582) per item; items without either are left out."""
    out: dict[str, dict[str, list[str]]] = {}
    for chunk in _chunks(sorted(set(qids), key=lambda q: int(q[1:])), 50):
        values = " ".join(f"wd:{q}" for q in chunk)
        query = f"""
        SELECT ?item ?dissolved ?end WHERE {{
          VALUES ?item {{ {values} }}
          {{ ?item wdt:P576 ?dissolved }} UNION {{ ?item wdt:P582 ?end }}
        }}"""
        for b in _sparql(query):
            rec = out.setdefault(_qid(_val(b, "item")), {"P576": [], "P582": []})
            for prop, key in (("P576", "dissolved"), ("P582", "end")):
                value = _val(b, key)
                if value and value not in rec[prop]:
                    rec[prop].append(value)
    return {q: {p: sorted(v) for p, v in rec.items()} for q, rec in sorted(out.items(), key=lambda kv: int(kv[0][1:]))}


def fetch_iso_codes() -> dict:
    """Every item carrying an ISO 3166-1 alpha-2 code (P297, best rank): ``{code: [qid, …]}``.

    The baseline for scope drift: a code appearing (new entry candidate) or an entry's item
    losing its code (entry to retire)."""
    out: dict[str, list[str]] = {}
    for b in _sparql("SELECT ?item ?code WHERE { ?item wdt:P297 ?code }"):
        bucket = out.setdefault(_val(b, "code"), [])
        q = _qid(_val(b, "item"))
        if q not in bucket:
            bucket.append(q)
    return {k: sorted(v, key=lambda q: int(q[1:])) for k, v in sorted(out.items())}


def fetch_coords(qids: list[str]) -> dict[str, list[float]]:
    """Coordinates (P625, best rank) per item as ``[lat, lon]``; the first value when there are several."""
    out: dict[str, list[float]] = {}
    for chunk in _chunks(sorted(set(qids), key=lambda q: int(q[1:])), 50):
        values = " ".join(f"wd:{q}" for q in chunk)
        query = f"SELECT ?item ?coord WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P625 ?coord }}"
        found: dict[str, list[tuple[float, float]]] = {}
        for b in _sparql(query):
            point = _point(_val(b, "coord"))
            if point:
                found.setdefault(_qid(_val(b, "item")), []).append(point)
        for q, points in found.items():
            out[q] = list(sorted(points)[0])
    return dict(sorted(out.items(), key=lambda kv: int(kv[0][1:])))


def load_status() -> dict:
    return _load(STATUS_CACHE) if STATUS_CACHE.exists() else {}


def load_iso_codes() -> dict:
    return _load(ISO_CODES_CACHE) if ISO_CODES_CACHE.exists() else {}
