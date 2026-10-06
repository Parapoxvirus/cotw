"""Unit tests for the schema validator and the import helpers (no data files needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cotw import languages, schema
from cotw.importer import dump_entry
from cotw.source import slugify, sort_key


def _text(text: str) -> dict:
    return dict.fromkeys(languages.LANGUAGES, text)


def _entry(**overrides) -> dict:
    base = {
        "id": "001",
        "iso2": "XA",
        "iso3": "XAA",
        "wikidata": "Q1",
        "status": "sovereign",
        "name": _text("Musterland"),
        "formal_name": {**_text("Republic of Musterland"), "de": "Republik Musterland"},
        "capitals": [
            {
                "name": _text("Musterhausen"),
                "role": "capital",
                "wikidata": "Q2",
                "lat": 47.5,
                "lon": 8.6,
            }
        ],
        "borders": [],
        "regions": ["Europe", "Western Europe"],
        "wikipedia": {"en": "https://en.wikipedia.org/wiki/Musterland"},
    }
    base.update(overrides)
    return {k: base[k] for k in schema.FIELD_ORDER if k in base}


def test_valid_entry_has_no_problems():
    assert schema.validate_entry(_entry(), Path("001-musterland.yaml")) == []


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"id": 1}, "3-digit"),
        ({"iso2": "xa"}, "iso2"),
        ({"status": "country"}, "status"),
        ({"dependency_of": "002"}, "dependency_of only"),
        ({"name": {"en": "Only English"}}, "name.de"),
        ({"capitals": []}, "non-empty"),
        ({"borders": ["002", "001"]}, "sorted"),
        ({"borders": ["001"]}, "itself"),
        ({"regions": []}, "regions"),
        ({"wikipedia": {"en": "http://example.com"}}, "wikipedia"),
        ({"wikipedia": {"en": "https://en.wikipedia.org/wiki/Musterland", "de": "https://en.wikipedia.org/wiki/Musterland"}}, "wikipedia.de"),
        ({"wikipedia": {"en": "https://en.wikipedia.org/wiki/Muster land"}}, "whitespace"),
        ({"name": {**_text("Musterland"), "xx": "Musterland"}}, "name.xx: not a registered language"),
        ({"formal_name": {"xx": "Musterland"}}, "formal_name.xx: not a registered language"),
        ({"wikipedia": {"en": "https://en.wikipedia.org/wiki/Musterland", "xx": "https://xx.wikipedia.org/wiki/M"}},
         "wikipedia.xx: not a registered language"),
    ],
)
def test_invalid_entries(override, fragment):
    problems = schema.validate_entry(_entry(**override), Path("001-musterland.yaml"))
    assert any(fragment in p for p in problems), problems


@pytest.mark.parametrize("code", languages.LANGUAGES)
def test_every_registered_language_is_required(code):
    name = {k: v for k, v in _text("Musterland").items() if k != code}
    capital = dict(_entry()["capitals"][0], name={k: v for k, v in _text("Musterhausen").items() if k != code})
    problems = schema.validate_entry(_entry(name=name, capitals=[capital]), Path("001-musterland.yaml"))
    assert f"001-musterland.yaml: name.{code}: missing" in problems
    assert f"001-musterland.yaml: capitals[0].name.{code}: missing" in problems



@pytest.mark.parametrize("code", languages.LANGUAGES)
def test_optional_map_present_needs_every_language(code):
    """``name_label``, ``formal_name`` and ``capitals[].label``: absent, or in every language."""
    partial = {k: v for k, v in _text("note").items() if k != code}
    capital = dict(_entry()["capitals"][0], label=partial)
    problems = schema.validate_entry(_entry(name_label=partial, formal_name=partial, capitals=[capital]))
    for where in ("name_label", "formal_name", "capitals[0].label"):
        assert f"001: {where}.{code}: missing (present in other languages)" in problems
    complete = dict(_entry()["capitals"][0], label=_text("note"))
    assert schema.validate_entry(_entry(name_label=_text("note"), capitals=[complete])) == []
    no_formal = {k: v for k, v in _entry().items() if k != "formal_name"}
    assert schema.validate_entry(no_formal) == []


def test_straight_apostrophe_is_rejected():
    e = _entry(formal_name={**_text("The People's Republic of Musterland"), "de": "Volksrepublik Musterland"})
    apostrophe = [f"001: formal_name.{code}: straight apostrophe ' (use ’)" for code in languages.LANGUAGES if code != "de"]
    assert schema.validate_entry(e) == apostrophe
    capital = dict(_entry()["capitals"][0], name=_text("Nukuʻalofa"), label=_text("Côte d’Ivoire"))
    assert schema.validate_entry(_entry(name=_text("People’s Musterland"), capitals=[capital])) == []

def test_dependency_needs_parent():
    problems = schema.validate_entry(_entry(status="dependency"), Path("001-musterland.yaml"))
    assert any("dependency_of" in p for p in problems)


def test_capital_without_coordinates_needs_exception():
    cap = {"name": _text("Nirgendwo"), "role": "capital", "wikidata": "Q3"}
    e = _entry(capitals=[cap])
    assert any("coordinates" in p for p in schema.validate_entry(e))
    assert schema.validate_entry(e, exceptions={"no_capital_coordinates": {"001": "test"}}) == []


def test_file_name_must_match_id():
    problems = schema.validate_entry(_entry(), Path("002-musterland.yaml"))
    assert any("file name" in p for p in problems)


def test_cross_rules_detect_asymmetric_borders_and_bad_parent():
    a = _entry(id="001", borders=["002"])
    b = _entry(id="002", iso2="XB", iso3="XBB", wikidata="Q9", status="dependency", dependency_of="003")
    problems = schema.validate_all({Path("001-a.yaml"): a, Path("002-b.yaml"): b})
    assert any("does not border" in p for p in problems)
    assert any("dependency_of 003 does not exist" in p for p in problems)


def test_umlaut_round_trip(tmp_path):
    e = _entry(name={"en": "Austria", "de": "Österreich"}, formal_name={"en": "Côte d’Ivoire", "de": "Großherzogtum Müsterlingen"})
    text = dump_entry(e)
    assert "Österreich" in text and "Côte d’Ivoire" in text and "Großherzogtum" in text
    path = tmp_path / "001-austria.yaml"
    path.write_text(text, encoding="utf-8")
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == e


def test_sort_key_and_slug():
    assert sort_key("Åland") < sort_key("Albania") < sort_key("Zimbabwe")
    assert slugify("Côte d’Ivoire / Ivory Coast, The") == "cote-divoire"
    assert slugify("United States, The") == "united-states"
    assert slugify("São Tomé and Príncipe") == "sao-tome-and-principe"


def test_regions_taxonomy_keeps_real_hyphens(tmp_path):
    tags = tmp_path / "tags.txt"
    tags.write_text("COTW::Africa::Sub-Saharan-Africa::Eastern-Africa\nCOTW::Asia::South-eastern-Asia\n", encoding="utf-8")
    tax = schema.load_regions_taxonomy(tags)
    assert ("Africa", "Sub-Saharan Africa", "Eastern Africa") in tax
    assert ("Asia", "South-eastern Asia") in tax
    assert ("Africa",) in tax
