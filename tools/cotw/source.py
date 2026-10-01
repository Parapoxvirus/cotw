"""Parser for the v3 spreadsheet export (``cotw v3.csv``, not in the repository).

The CSV is the read-only input of the one-time import. Everything the pipeline needs is
read here once, cleaned (stray whitespace, typos in the header) and returned as plain
dataclasses; the Flag/Map/Globe/Borders/Tags columns are Excel formulas and are ignored.
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


STATUS_MAP = {
    "Souvereign Country": "sovereign",  # sic, spreadsheet typo
    "Dependency": "dependency",
    "Disputed": "disputed",
}

# Spreadsheet region names → UN M49 names as used in ``data/tags.txt``.
REGION_MAP = {
    "North Africa": "Northern Africa",
    "East Africa": "Eastern Africa",
    "Central Africa": "Middle Africa",
    "West Africa": "Western Africa",
    "West Asia": "Western Asia",
    "South Asia": "Southern Asia",
    "Southeast Asia": "South-eastern Asia",
}

# Header typos in the CSV, normalized so the rest of the code can use one spelling.
HEADER_FIXES = {"En Capital 3": "EN Capital 3", "EN Long From": "EN Long Form"}


@dataclass(frozen=True)
class SourceCapital:
    name_en: str
    name_de: str
    label_en: str
    label_de: str


@dataclass(frozen=True)
class SourceEntry:
    iso2: str
    iso3: str
    name_en: str
    name_de: str
    name_label_en: str
    name_label_de: str
    formal_en: str
    formal_de: str
    capitals: tuple[SourceCapital, ...]
    borders: tuple[str, ...]  # ISO-2 codes, as listed in B1–B14
    regions: tuple[str, ...]  # M49 names, outermost first
    status: str  # sovereign | dependency | disputed
    wikipedia_en: str
    raw: dict[str, str] = field(repr=False, compare=False, hash=False, default_factory=dict)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        rows = []
        for row in reader:
            fixed = {HEADER_FIXES.get(k, k): _clean(v) for k, v in row.items() if k is not None}
            rows.append(fixed)
    return rows


def parse_source(path: Path) -> list[SourceEntry]:
    entries = []
    for row in _read_rows(path):
        if not row.get("ISO-2"):
            continue
        capitals = []
        for i in (1, 2, 3):
            en = row[f"EN Capital {i}"]
            de = row[f"DE Hauptstadt {i}"]
            if not en and not de:
                continue
            if not en and capitals and not capitals[-1].label_de:
                # "unbewohnt" in "DE Hauptstadt 2" is the DE label of capital 1, not a capital.
                prev = capitals[-1]
                capitals[-1] = SourceCapital(prev.name_en, prev.name_de, prev.label_en, de)
                continue
            capitals.append(
                SourceCapital(
                    name_en=en,
                    name_de=de or en,
                    label_en=row[f"EN Capital {i} Label"],
                    label_de=row[f"DE Hauptstadt {i} Label"],
                )
            )
        borders = tuple(row[f"B{i}"] for i in range(1, 15) if row[f"B{i}"])
        regions = tuple(
            REGION_MAP.get(row[k], row[k]) for k in ("Region 1", "Region 2", "Region 3") if row[k]
        )
        entries.append(
            SourceEntry(
                iso2=row["ISO-2"],
                iso3=row["ISO-3"],
                name_en=row["EN Country"],
                name_de=row["DE Land"],
                name_label_en=row["EN Country Label"],
                name_label_de=row["DE Land Label"],
                formal_en=row["EN Long Form"],
                formal_de=row["DE Langform"],
                capitals=tuple(capitals),
                borders=borders,
                regions=regions,
                status=STATUS_MAP[row["Status"]],
                wikipedia_en=row["EN Wiki URL"],
                raw=row,
            )
        )
    return entries


def sort_key(name: str) -> str:
    """Accent-insensitive, case-insensitive key: ``Åland`` sorts under A, not after Z."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def slugify(name: str) -> str:
    """File-name slug from the EN name: first alternative before `` / ``, ``, The`` dropped."""
    first = name.split(" / ")[0]
    if first.endswith(", The"):
        first = first[: -len(", The")]
    key = sort_key(first).replace("’", "").replace("'", "")
    out = []
    for c in key:
        out.append(c if c.isalnum() else "-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")
