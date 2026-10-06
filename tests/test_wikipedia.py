"""wikipedia.<lang> from the Wikidata sitelinks (roadmap step 4), for every registered language."""

from __future__ import annotations

import pytest

from cotw import languages, schema, wikidata

OTHERS = [code for code in languages.LANGUAGES if code != languages.BASE]

# Items without a German article: the DE deck links the English one. Listed in the PR.
NO_DEWIKI = {"215"}  # Svalbard and Jan Mayen


@pytest.mark.parametrize("code", OTHERS)
def test_links_match_the_sitelinks_cache(by_id, code):
    sitelinks = wikidata.load_sitelinks()
    for cid, e in by_id.items():
        title = sitelinks.get(e["wikidata"], {}).get(code)
        if title is None:
            assert code not in e["wikipedia"], cid
        else:
            assert e["wikipedia"][code] == wikidata.wikipedia_url(code, title), cid
            assert e["wikipedia"][code].startswith(f"https://{code}.wikipedia.org/wiki/"), cid


def test_german_articles(by_id):
    sitelinks = wikidata.load_sitelinks()
    assert {cid for cid, e in by_id.items() if "de" not in sitelinks.get(e["wikidata"], {})} == NO_DEWIKI
    assert by_id["217"]["wikipedia"]["de"] == "https://de.wikipedia.org/wiki/Schweiz"
    assert by_id["014"]["wikipedia"]["de"] == "https://de.wikipedia.org/wiki/Österreich"


def test_url_style():
    assert wikidata.wikipedia_url("de", "São Tomé und Príncipe") == "https://de.wikipedia.org/wiki/São_Tomé_und_Príncipe"
    assert wikidata.wikipedia_url("en", "What?#&") == "https://en.wikipedia.org/wiki/What%3F%23%26"


def test_validate_checks_the_links_against_the_sitelinks(by_id):
    ch = by_id["217"]
    sitelinks = {ch["wikidata"]: {"en": "Switzerland", "de": "Schweiz"}}
    assert schema.validate_entry(ch, sitelinks=sitelinks) == []
    moved = {ch["wikidata"]: {"en": "Switzerland", "de": "Schweiz (Land)"}}
    assert any("wikipedia.de must be https://de.wikipedia.org/wiki/Schweiz_(Land)" in p
               for p in schema.validate_entry(ch, sitelinks=moved))
    gone = {ch["wikidata"]: {"en": "Switzerland"}}
    assert any("wikipedia.de without a sitelink" in p for p in schema.validate_entry(ch, sitelinks=gone))
    missing = dict(ch, wikipedia={"en": ch["wikipedia"]["en"]})
    assert any("wikipedia.de must be" in p for p in schema.validate_entry(missing, sitelinks=sitelinks))


def test_links_normalize_the_english_url():
    links = wikidata.wikipedia_links(
        "https://en.wikipedia.org/wiki/S%C3%A3o_Tom%C3%A9_and_Pr%C3%Adncipe", {"de": "São Tomé und Príncipe"}
    )
    assert links == {
        "en": "https://en.wikipedia.org/wiki/São_Tomé_and_Príncipe",
        "de": "https://de.wikipedia.org/wiki/São_Tomé_und_Príncipe",
    }
    assert wikidata.wikipedia_links("https://en.wikipedia.org/wiki/Sierra Leone", {}) == {
        "en": "https://en.wikipedia.org/wiki/Sierra_Leone"
    }
