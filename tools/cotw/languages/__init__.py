"""The language registry: one module per deck language (``en.py``, ``de.py``, …).

Each module exports ``LANGUAGE``, a ``Language`` with everything that differs between the
packages: identities, names, field and template names, UI and help texts, region names and the
grammar of "dependency of …". Adding a language is a new module here plus the names in the
data (docs/DECK.md, "Identities"); nothing outside this package names a language.

The modules are discovered, not listed. The order is fixed: the base language ``en`` first,
then the others by code. Everything derived from the registry (the build order, the globe's
name maps) follows it.
"""

from __future__ import annotations

import hashlib
import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field

# The base language: the database's reference names, the Wikipedia fallback, the AnkiWeb
# fallback for a language without its own listing.
BASE = "en"
ID_KINDS = ("notetype", "deck", "deck-extras")
OFFSET_STEP = 50_000  # id_offset: one block of note/card IDs per language


def derive_id(code: str, kind: str) -> int:
    """The rule the frozen ``notetype_id`` / ``deck_id`` / ``extras_deck_id`` were derived with.

    The IDs are written into each module as constants, never computed at build time: Anki
    matches note types by ID, and a changed ID installs a second note type next to the old one.
    A test checks the constants against this rule."""
    if kind not in ID_KINDS:
        raise ValueError(f"unknown ID kind {kind!r}")
    digest = hashlib.sha256(f"cotw:{code}:{kind}".encode()).digest()[:4]
    return (int.from_bytes(digest, "big") >> 1) | 1 << 30


def _bare(name: str) -> str:
    return name


@dataclass(frozen=True)
class Language:
    code: str  # ISO 639-1, also the Wikipedia subdomain and the key in the data's text maps
    wiki: str  # Wikidata site ID of the Wikipedia (``enwiki``)
    notetype_id: int
    deck_id: int
    extras_deck_id: int
    id_offset: int  # first note/card ID = epoch * 1000 + id_offset (unique per language)
    notetype: str
    deck: str
    extras: str
    tag_root: str
    status_tags: dict[str, str]  # status → tag segment
    fields: dict[str, str]  # field key (deck.lang.FIELD_KEYS) → field name
    templates: dict[str, str]  # card type key (deck.lang.CARD_TYPES) → template name
    dependency_of: str  # "dependency of {}", filled with ``object_form(parent name)``
    comments: dict[str, str]  # section comments in the card templates (Anki's template editor)
    status_disputed: str
    ui: dict[str, str]
    help: str  # placeholders: {infographic} {infographic_filtered} {ankiweb} {contact}
    description: str  # placeholders: {count} {citation} {manifest} {font_license} {icons_license}
    extras_description: str
    regions: dict[str, str]  # M49 region name (EN, data/tags.txt) → display name in tags
    # The parent's name after ``dependency_of``: article, case. Gets the first alternative of
    # the name (``United States, The``), returns it as it reads inside the sentence.
    object_form: Callable[[str], str] = field(default=_bare)
    ankiweb: str | None = None  # AnkiWeb listing; None: the base language's listing


def discover() -> dict[str, Language]:
    """Every ``LANGUAGE`` in the package's modules, base language first, then by code."""
    found: dict[str, Language] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        language = importlib.import_module(f"{__name__}.{info.name}").LANGUAGE
        if language.code != info.name:
            raise ValueError(f"languages/{info.name}.py defines code {language.code!r}")
        found[language.code] = language
    if BASE not in found:
        raise ValueError(f"no module for the base language {BASE!r}")
    return {code: found[code] for code in sorted(found, key=lambda c: (c != BASE, c))}


REGISTRY: dict[str, Language] = discover()
LANGUAGES: tuple[str, ...] = tuple(REGISTRY)


def get(code: str) -> Language:
    return REGISTRY[code]

