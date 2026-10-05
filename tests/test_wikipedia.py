"""wikipedia.de from the Wikidata sitelinks (roadmap step 4)."""

from __future__ import annotations

from cotw import wikidata

# Items without a German article: the DE deck links the English one. Listed in the PR.
NO_DEWIKI = {"215"}  # Svalbard and Jan Mayen


def test_german_links_match_the_sitelinks_cache(by_id):
    sitelinks = wikidata.load_sitelinks()
    missing = set()
    for cid, e in by_id.items():
        title = sitelinks.get(e["wikidata"], {}).get("de")
        if title is None:
            missing.add(cid)
            assert "de" not in e["wikipedia"], cid
        else:
            assert e["wikipedia"]["de"] == wikidata.wikipedia_url("de", title), cid
    assert missing == NO_DEWIKI


def test_german_links_point_to_dewiki(by_id):
    for cid, e in by_id.items():
        if "de" in e["wikipedia"]:
            assert e["wikipedia"]["de"].startswith("https://de.wikipedia.org/wiki/"), cid
    assert by_id["217"]["wikipedia"]["de"] == "https://de.wikipedia.org/wiki/Schweiz"
    assert by_id["014"]["wikipedia"]["de"] == "https://de.wikipedia.org/wiki/Österreich"


def test_polish_links_match_the_sitelinks_cache(by_id):
    sitelinks = wikidata.load_sitelinks()
    for cid, e in by_id.items():
        title = sitelinks.get(e["wikidata"], {}).get("pl")
        assert title, cid
        assert e["wikipedia"]["pl"] == wikidata.wikipedia_url("pl", title), cid
    assert by_id["177"]["wikipedia"]["pl"] == "https://pl.wikipedia.org/wiki/Polska"


def test_url_style():
    assert wikidata.wikipedia_url("de", "São Tomé und Príncipe") == "https://de.wikipedia.org/wiki/São_Tomé_und_Príncipe"
    assert wikidata.wikipedia_url("en", "What?#&") == "https://en.wikipedia.org/wiki/What%3F%23%26"


def test_links_normalize_the_english_url():
    links = wikidata.wikipedia_links(
        "https://en.wikipedia.org/wiki/S%C3%A3o_Tom%C3%A9_and_Pr%C3%Adncipe", {"de": "São Tomé und Príncipe"}
    )
    assert links == {
        "en": "https://en.wikipedia.org/wiki/São_Tomé_and_Príncipe",
        "de": "https://de.wikipedia.org/wiki/São_Tomé_und_Príncipe",
    }
    kept = wikidata.wikipedia_links(
        "https://en.wikipedia.org/wiki/Poland",
        {"de": "Polen"},
        keep={"en": "https://en.wikipedia.org/wiki/Poland", "pl": "https://pl.wikipedia.org/wiki/Polska"},
    )
    assert kept["pl"] == "https://pl.wikipedia.org/wiki/Polska"
    assert kept["de"] == "https://de.wikipedia.org/wiki/Polen"
    assert wikidata.wikipedia_links("https://en.wikipedia.org/wiki/Sierra Leone", {}) == {
        "en": "https://en.wikipedia.org/wiki/Sierra_Leone"
    }
