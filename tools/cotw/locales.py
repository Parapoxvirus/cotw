"""The curated locale list ``data/locales.yaml``: wanted languages and their sources.

Each entry names a BCP 47 locale (``pt-BR``) with its Wikipedia (site ID and article URL
prefix) and its Wikidata label languages in fallback order. A locale is listed here before its
module exists; the list is a wish list, not the published decks (those are ``cotw.languages``,
and the registry accepts only a module whose code is listed). The sources of a published
locale come from here: ``wikidata.wikipedia_url``, the sitelinks and the Wikidata labels.

``problems`` checks the raw file and returns a list of problems like ``schema.validate_entry``;
``python -m cotw validate`` reports them. ``LOCALES``, ``TAGS`` and ``get`` load the file on
first use and raise ``ValueError`` if it has problems. Whether a tag is not just well-formed
but valid (registered subtags, canonical form) is a test with ``langcodes`` (dev extra only),
not a runtime check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from .paths import LOCALES_FILE

# language(-Script)?-REGION, canonical case; REGION is ISO 3166-1 alpha-2 or UN M49.
TAG_SHAPE = re.compile(r"[a-z]{2,3}(?:-[A-Z][a-z]{3})?-(?:[A-Z]{2}|[0-9]{3})")
WIKI_SHAPE = re.compile(r"[a-z][a-z_]*wiki")
WIKIPEDIA_SHAPE = re.compile(r"https://([a-z][a-z-]*)\.wikipedia\.org/(?:[a-z-]+/)+")
WIKIDATA_LANGUAGE_SHAPE = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]+)*")
FIELDS = ("tag", "endonym", "english", "wiki", "wikipedia", "wikidata", "naming_source")
REQUIRED = FIELDS[:-1]
SOURCE_FIELDS = ("title", "publisher", "url")


@dataclass(frozen=True)
class NamingSource:
    title: str
    publisher: str
    url: str


@dataclass(frozen=True)
class Locale:
    tag: str  # BCP 47, canonical case
    endonym: str
    english: str
    wiki: str  # Wikidata site ID of the Wikipedia (``ptwiki``)
    wikipedia: str  # article URL prefix, ``https://…/``
    wikidata: tuple[str, ...]  # label languages, fallback order
    naming_source: NamingSource | None = None


def read(path: Path | None = None):
    return yaml.safe_load((path or LOCALES_FILE).read_text(encoding="utf-8"))


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() == value != ""


def _check_entry(entry, where: str) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{where}: must be a mapping"]
    problems = [f"{where}: unknown field {key!r}" for key in entry if key not in FIELDS]
    problems += [f"{where}: missing {key}" for key in REQUIRED if key not in entry]
    tag = entry.get("tag")
    if "tag" in entry and not (isinstance(tag, str) and TAG_SHAPE.fullmatch(tag)):
        problems.append(f"{where}: tag {tag!r} must be language(-Script)?-REGION in canonical case")
    for key in ("endonym", "english"):
        if key in entry and not _text(entry[key]):
            problems.append(f"{where}: {key} must be a non-empty string")
    wiki, url = entry.get("wiki"), entry.get("wikipedia")
    if "wiki" in entry and not (isinstance(wiki, str) and WIKI_SHAPE.fullmatch(wiki)):
        problems.append(f"{where}: wiki {wiki!r} must be a Wikidata site ID (ptwiki)")
    m = WIKIPEDIA_SHAPE.fullmatch(url) if isinstance(url, str) else None
    if "wikipedia" in entry and not m:
        problems.append(f"{where}: wikipedia {url!r} must be https://<site>.wikipedia.org/…/")
    elif m and isinstance(wiki, str) and wiki != m.group(1).replace("-", "_") + "wiki":
        problems.append(f"{where}: wikipedia {url!r} is not the site of wiki {wiki!r}")
    codes = entry.get("wikidata")
    if "wikidata" in entry:
        if not (isinstance(codes, list) and codes):
            problems.append(f"{where}: wikidata must be a non-empty list of label languages")
        else:
            bad = [c for c in codes if not (isinstance(c, str) and WIKIDATA_LANGUAGE_SHAPE.fullmatch(c))]
            if bad:
                problems.append(f"{where}: wikidata {bad!r} are not Wikidata language codes (pt-br)")
            if len(set(map(str, codes))) != len(codes):
                problems.append(f"{where}: wikidata lists a language twice")
    source = entry.get("naming_source")
    if "naming_source" in entry:
        if not isinstance(source, dict):
            problems.append(f"{where}: naming_source must be a mapping of {SOURCE_FIELDS}")
        else:
            problems += [f"{where}: naming_source: unknown field {k!r}" for k in source if k not in SOURCE_FIELDS]
            problems += [
                f"{where}: naming_source.{k} must be a non-empty string" for k in SOURCE_FIELDS if not _text(source.get(k))
            ]
            if _text(source.get("url")) and not source["url"].startswith("https://"):
                problems.append(f"{where}: naming_source.url must start with https://")
    return problems


def problems(raw, name: str = "data/locales.yaml") -> list[str]:
    """Every problem of the raw file content (the parsed YAML), empty if it is valid."""
    if not isinstance(raw, list) or not raw:
        return [f"{name}: must be a non-empty list of locales"]
    found: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        tag = entry.get("tag") if isinstance(entry, dict) else None
        where = f"{name}: {tag}" if isinstance(tag, str) else f"{name}: [{i}]"
        found += _check_entry(entry, where)
        if isinstance(tag, str):
            # Tags are case-insensitive (RFC 5646): ``de-ch`` duplicates ``de-CH``.
            if tag.lower() in seen:
                found.append(f"{where}: duplicate tag")
            seen.add(tag.lower())
    return found


def parse(raw, name: str = "data/locales.yaml") -> dict[str, Locale]:
    """The locales by tag, in file order; ``ValueError`` listing every problem otherwise."""
    found = problems(raw, name)
    if found:
        raise ValueError("\n".join(found))
    locales = {}
    for entry in raw:
        source = entry.get("naming_source")
        locales[entry["tag"]] = Locale(
            **{k: entry[k] for k in REQUIRED if k != "wikidata"},
            wikidata=tuple(entry["wikidata"]),
            naming_source=NamingSource(**source) if source else None,
        )
    return locales


@cache
def _load() -> dict[str, Locale]:
    return parse(read())


def get(tag: str) -> Locale:
    return _load()[tag]


def __getattr__(name: str):
    # LOCALES and TAGS load on first use, so that a broken file still lets ``validate`` report it.
    if name == "LOCALES":
        return _load()
    if name == "TAGS":
        return tuple(_load())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
