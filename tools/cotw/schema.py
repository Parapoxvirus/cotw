"""Schema of a country entry (``data/countries/<id>-<slug>.yaml``), see ``docs/SCHEMA.md``.

``validate_entry`` checks one file in isolation, ``validate_all`` the cross-entry rules
(unique IDs/codes, symmetric borders, dependency targets). Both return a list of problems;
the tests and ``python -m cotw validate`` assert that it is empty.

The required languages are the registered ones (``cotw.languages``): every text map needs each
of them, and no other. An optional map (``name_label``, ``formal_name``, ``capitals[].label``) is
either absent or complete. Texts use the typographic apostrophe ’, never a straight ``'``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import languages
from .paths import COUNTRIES
from .wikidata import wikipedia_url

STATUSES = ("sovereign", "dependency", "disputed")
ROLES = (
    "capital",
    "seat_of_government",
    "executive",
    "legislative",
    "judicial",
    "de_jure",
    "de_facto",
    "proclaimed",
)
FIELD_ORDER = (
    "id",
    "iso2",
    "iso3",
    "wikidata",
    "status",
    "dependency_of",
    "name",
    "name_label",
    "formal_name",
    "capitals",
    "borders",
    "regions",
    "wikipedia",
)
ID_RE = re.compile(r"^\d{3}$")
ISO2_RE = re.compile(r"^[A-Z]{2}$")
ISO3_RE = re.compile(r"^[A-Z]{3}$")
QID_RE = re.compile(r"^Q\d+$")
FILE_RE = re.compile(r"^(\d{3})-([a-z0-9-]+)\.yaml$")


def load_entry(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_all(directory: Path = COUNTRIES) -> dict[Path, dict]:
    return {p: load_entry(p) for p in sorted(directory.glob("*.yaml"))}


def _check_text_map(value, where: str, problems: list[str], required: bool = True) -> None:
    if value is None:
        if required:
            problems.append(f"{where}: missing")
        return
    if not isinstance(value, dict):
        problems.append(f"{where}: must be a mapping of language → text")
        return
    for lang in languages.LANGUAGES:
        if (required or value) and not value.get(lang):
            problems.append(f"{where}.{lang}: missing" + ("" if required else " (present in other languages)"))
    for lang, text in value.items():
        if lang not in languages.LANGUAGES:
            problems.append(f"{where}.{lang}: not a registered language {languages.LANGUAGES}")
        elif not isinstance(text, str) or not text.strip():
            problems.append(f"{where}.{lang}: must be a non-empty string")
        elif text != text.strip():
            problems.append(f"{where}.{lang}: leading/trailing whitespace")
        elif "'" in text:
            problems.append(f"{where}.{lang}: straight apostrophe ' (use ’)")


def validate_entry(
    entry: dict, path: Path | None = None, exceptions: dict | None = None, sitelinks: dict | None = None
) -> list[str]:
    """``sitelinks`` (``data/wikidata/sitelinks.json``): when given, every non-base language's
    ``wikipedia`` link must be the item's article in that language, and absent without one."""
    problems: list[str] = []
    name = path.name if path else entry.get("id", "?")
    exceptions = exceptions or {}

    for key in entry:
        if key not in FIELD_ORDER:
            problems.append(f"{name}: unknown field {key!r}")
    if list(entry) != [k for k in FIELD_ORDER if k in entry]:
        problems.append(f"{name}: fields out of canonical order")

    cid = entry.get("id")
    if not isinstance(cid, str) or not ID_RE.match(cid):
        problems.append(f"{name}: id must be a 3-digit string, got {cid!r}")
    if path is not None:
        m = FILE_RE.match(path.name)
        if not m:
            problems.append(f"{name}: file name must be <id>-<slug>.yaml")
        elif m.group(1) != cid:
            problems.append(f"{name}: file name id {m.group(1)} ≠ id {cid}")

    if not ISO2_RE.match(str(entry.get("iso2"))):
        problems.append(f"{name}: iso2 must be two uppercase letters")
    if not ISO3_RE.match(str(entry.get("iso3"))):
        problems.append(f"{name}: iso3 must be three uppercase letters")
    if not QID_RE.match(str(entry.get("wikidata"))):
        problems.append(f"{name}: wikidata must be a QID")

    status = entry.get("status")
    if status not in STATUSES:
        problems.append(f"{name}: status must be one of {STATUSES}, got {status!r}")
    dep = entry.get("dependency_of")
    if status == "dependency":
        if not isinstance(dep, str) or not ID_RE.match(dep):
            problems.append(f"{name}: dependency needs dependency_of (COTW id)")
    elif dep is not None:
        problems.append(f"{name}: dependency_of only allowed for dependencies")

    _check_text_map(entry.get("name"), f"{name}: name", problems)
    _check_text_map(entry.get("name_label"), f"{name}: name_label", problems, required=False)
    _check_text_map(entry.get("formal_name"), f"{name}: formal_name", problems, required=False)

    capitals = entry.get("capitals")
    if not isinstance(capitals, list) or not capitals:
        problems.append(f"{name}: capitals must be a non-empty list")
        capitals = []
    has_coords = False
    for i, cap in enumerate(capitals):
        where = f"{name}: capitals[{i}]"
        if not isinstance(cap, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        for key in cap:
            if key not in ("name", "label", "role", "wikidata", "lat", "lon"):
                problems.append(f"{where}: unknown field {key!r}")
        _check_text_map(cap.get("name"), f"{where}.name", problems)
        _check_text_map(cap.get("label"), f"{where}.label", problems, required=False)
        if cap.get("role") not in ROLES:
            problems.append(f"{where}.role: must be one of {ROLES}, got {cap.get('role')!r}")
        if cap.get("wikidata") is not None and not QID_RE.match(str(cap["wikidata"])):
            problems.append(f"{where}.wikidata: must be a QID")
        lat, lon = cap.get("lat"), cap.get("lon")
        if (lat is None) != (lon is None):
            problems.append(f"{where}: lat and lon must be given together")
        if lat is not None:
            if not isinstance(lat, (int, float)) or not -90 <= lat <= 90:
                problems.append(f"{where}.lat: out of range")
            if not isinstance(lon, (int, float)) or not -180 <= lon <= 180:
                problems.append(f"{where}.lon: out of range")
            has_coords = True
    if capitals and not has_coords and cid not in exceptions.get("no_capital_coordinates", {}):
        problems.append(f"{name}: no capital with coordinates (and no documented exception)")

    borders = entry.get("borders")
    if not isinstance(borders, list):
        problems.append(f"{name}: borders must be a list (may be empty)")
    else:
        for b in borders:
            if not isinstance(b, str) or not ID_RE.match(b):
                problems.append(f"{name}: border {b!r} must be a COTW id")
        if borders != sorted(borders) or len(set(borders)) != len(borders):
            problems.append(f"{name}: borders must be sorted and unique")
        if cid in borders:
            problems.append(f"{name}: entry borders itself")

    regions = entry.get("regions")
    if not isinstance(regions, list) or not regions or not all(isinstance(r, str) and r for r in regions):
        problems.append(f"{name}: regions must be a non-empty list of names (outermost first)")

    wiki = entry.get("wikipedia")
    base = languages.BASE
    if not isinstance(wiki, dict) or not str(wiki.get(base, "")).startswith(f"https://{base}.wikipedia.org/wiki/"):
        problems.append(f"{name}: wikipedia.{base} must be a URL on {base}.wikipedia.org")
    elif isinstance(wiki, dict):
        for lang, url in wiki.items():
            if lang not in languages.LANGUAGES:
                problems.append(f"{name}: wikipedia.{lang}: not a registered language {languages.LANGUAGES}")
            elif not isinstance(url, str) or not url.startswith(f"https://{lang}.wikipedia.org/wiki/"):
                problems.append(f"{name}: wikipedia.{lang} must be a {lang}.wikipedia.org URL")
            elif any(ch.isspace() for ch in url):
                problems.append(f"{name}: wikipedia.{lang} contains whitespace")
        if sitelinks is not None:
            titles = sitelinks.get(entry.get("wikidata"), {})
            for lang in languages.LANGUAGES:
                if lang == base:
                    continue  # chosen in the database, not taken from the sitelinks
                if lang in titles and wiki.get(lang) != wikipedia_url(lang, titles[lang]):
                    problems.append(f"{name}: wikipedia.{lang} must be {wikipedia_url(lang, titles[lang])} (sitelinks.json)")
                elif lang not in titles and lang in wiki:
                    problems.append(f"{name}: wikipedia.{lang} without a sitelink in sitelinks.json (the deck falls back to {base})")
    return problems


def validate_all(entries: dict[Path, dict], regions_taxonomy: set[tuple[str, ...]] | None = None) -> list[str]:
    problems: list[str] = []
    by_id: dict[str, dict] = {}
    for path, e in entries.items():
        cid = e.get("id")
        if cid in by_id:
            problems.append(f"{path.name}: duplicate id {cid}")
        by_id[cid] = e
    for field in ("iso2", "iso3", "wikidata"):
        seen: dict[str, str] = {}
        for e in entries.values():
            v = e.get(field)
            if v in seen:
                problems.append(f"duplicate {field} {v!r} in {seen[v]} and {e.get('id')}")
            seen[v] = e.get("id")
    slugs = [p.name[4:-5] for p in entries]
    if len(set(slugs)) != len(slugs):
        problems.append("duplicate slugs in file names")
    for e in entries.values():
        cid = e.get("id")
        for b in e.get("borders") or []:
            if b not in by_id:
                problems.append(f"{cid}: border {b} does not exist")
            elif cid not in (by_id[b].get("borders") or []):
                problems.append(f"{cid}: borders {b} but {b} does not border {cid}")
        dep = e.get("dependency_of")
        if dep is not None:
            if dep not in by_id:
                problems.append(f"{cid}: dependency_of {dep} does not exist")
            elif by_id[dep].get("status") != "sovereign":
                problems.append(f"{cid}: dependency_of {dep} is not sovereign")
        if regions_taxonomy is not None and tuple(e.get("regions") or ()) not in regions_taxonomy:
            problems.append(f"{cid}: regions {e.get('regions')} not in the M49 taxonomy")
    return problems


# Tag segments where a hyphen is part of the M49 name, not a space.
HYPHENATED_TAGS = {"Sub-Saharan-Africa": "Sub-Saharan Africa", "South-eastern-Asia": "South-eastern Asia"}


def tag_to_name(segment: str) -> str:
    return HYPHENATED_TAGS.get(segment, segment.replace("-", " "))


def load_regions_taxonomy(tags_file: Path) -> set[tuple[str, ...]]:
    """``COTW::Africa::Sub-Saharan-Africa::Eastern-Africa`` → ``("Africa", "Sub-Saharan Africa", "Eastern Africa")``."""
    out = set()
    for line in tags_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("COTW::"):
            continue
        parts = tuple(tag_to_name(p) for p in line.split("::")[1:])
        out.add(parts)
        for i in range(1, len(parts)):  # every prefix is a valid (coarser) assignment
            out.add(parts[:i])
    return out
