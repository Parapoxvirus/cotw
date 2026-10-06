"""The language-neutral structure of every package: field keys and card types.

Everything that differs per language (identities, names, UI texts) lives in one module per
language in ``cotw.languages``.
"""

from __future__ import annotations

# Field keys in note-type order. The first field is the sort field (the country name).
FIELD_KEYS = (
    "country",
    "country_label",
    "formal_name",
    "capital_1",
    "capital_1_label",
    "capital_2",
    "capital_2_label",
    "capital_3",
    "capital_3_label",
    "iso2",
    "iso3",
    "flag",
    "map_1",
    "map_2",
    "locator",
    "borders",
    "wikipedia",
    "dependency_of",
    "status",
)

# Card types in template order (DECISIONS D). ``asked`` is the "?" on the front and the
# highlighted answer on the back; ``shown`` is the prompt.
CARD_TYPES = (
    {"key": "country-capital", "asked": "capital", "shown": "country", "extra": False},
    {"key": "country-flag", "asked": "flag", "shown": "country", "extra": False},
    {"key": "capital-country", "asked": "country", "shown": "capital", "extra": False},
    {"key": "flag-country", "asked": "country", "shown": "flag", "extra": False},
    {"key": "map-country", "asked": "country", "shown": "maps", "extra": False},
    {"key": "code-country", "asked": "country", "shown": "iso", "extra": True},
    {"key": "country-code", "asked": "iso", "shown": "country", "extra": True},
    {"key": "country-borders", "asked": "borders", "shown": "country", "extra": True},
    {"key": "borders-country", "asked": "country", "shown": "borders", "extra": True},
    {"key": "country-map", "asked": "maps", "shown": "country", "extra": True},
)
