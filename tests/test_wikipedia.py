"""wikipedia.<lang> from the Wikidata sitelinks (roadmap step 4), for every registered language."""

from __future__ import annotations

import pytest

from cotw import languages, locales, schema, wikidata

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
            assert e["wikipedia"][code].startswith(locales.get(code).wikipedia), cid


def test_german_articles(by_id):
    sitelinks = wikidata.load_sitelinks()
    assert {cid for cid, e in by_id.items() if "de-CH" not in sitelinks.get(e["wikidata"], {})} == NO_DEWIKI
    assert by_id["217"]["wikipedia"]["de-CH"] == "https://de.wikipedia.org/wiki/Schweiz"
    assert by_id["014"]["wikipedia"]["de-CH"] == "https://de.wikipedia.org/wiki/Österreich"


def test_portuguese_articles(by_id):
    sitelinks = wikidata.load_sitelinks()
    assert all("pt-BR" in sitelinks.get(e["wikidata"], {}) for e in by_id.values())
    assert by_id["217"]["wikipedia"]["pt-BR"] == "https://pt.wikipedia.org/wiki/Suíça"
    assert by_id["031"]["wikipedia"]["pt-BR"] == "https://pt.wikipedia.org/wiki/Brasil"


def test_url_style():
    assert wikidata.wikipedia_url("de-CH", "São Tomé und Príncipe") == "https://de.wikipedia.org/wiki/São_Tomé_und_Príncipe"
    assert wikidata.wikipedia_url("en-US", "What?#&") == "https://en.wikipedia.org/wiki/What%3F%23%26"


def test_validate_checks_the_links_against_the_sitelinks(by_id):
    ch = by_id["217"]
    sitelinks = {ch["wikidata"]: {"en-US": "Switzerland", "de-CH": "Schweiz", "pl-PL": "Szwajcaria", "pt-BR": "Suíça"}}
    assert schema.validate_entry(ch, sitelinks=sitelinks) == []
    moved = {ch["wikidata"]: {"en-US": "Switzerland", "de-CH": "Schweiz (Land)", "pl-PL": "Szwajcaria", "pt-BR": "Suíça"}}
    assert any("wikipedia.de-CH must be https://de.wikipedia.org/wiki/Schweiz_(Land)" in p
               for p in schema.validate_entry(ch, sitelinks=moved))
    gone = {ch["wikidata"]: {"en-US": "Switzerland", "pl-PL": "Szwajcaria", "pt-BR": "Suíça"}}
    assert any("wikipedia.de-CH without a sitelink" in p for p in schema.validate_entry(ch, sitelinks=gone))
    missing = dict(ch, wikipedia={"en-US": ch["wikipedia"]["en-US"]})
    assert any("wikipedia.de-CH must be" in p for p in schema.validate_entry(missing, sitelinks=sitelinks))


def test_links_normalize_the_english_url():
    links = wikidata.wikipedia_links(
        "https://en.wikipedia.org/wiki/S%C3%A3o_Tom%C3%A9_and_Pr%C3%Adncipe", {"de-CH": "São Tomé und Príncipe"}
    )
    assert links == {
        "en-US": "https://en.wikipedia.org/wiki/São_Tomé_and_Príncipe",
        "de-CH": "https://de.wikipedia.org/wiki/São_Tomé_und_Príncipe",
    }
    assert wikidata.wikipedia_links("https://en.wikipedia.org/wiki/Sierra Leone", {}) == {
        "en-US": "https://en.wikipedia.org/wiki/Sierra_Leone"
    }


# --- source languages from data/locales.yaml ------------------------------------------------------


def test_sources_come_from_the_locale_list():
    assert wikidata.wikis() == {"en-US": "enwiki", "de-CH": "dewiki", "pl-PL": "plwiki", "pt-BR": "ptwiki"}
    assert wikidata.chain("de-CH") == ("de-ch", "de") and wikidata.chain("en-US") == ("en",)
    assert wikidata.chain("pl-PL") == ("pl",) and wikidata.chain("pt-BR") == ("pt-br", "pt")
    assert wikidata.label_languages() == ["en", "de-ch", "de", "pl", "pt-br", "pt"]
    assert wikidata.wikipedia_url("de-CH", "Schweiz") == "https://de.wikipedia.org/wiki/Schweiz"
    assert wikidata.wikipedia_url("zh-Hant-TW", "瑞士") == "https://zh.wikipedia.org/zh-hant/瑞士"


def test_a_label_is_the_first_value_along_the_chain():
    assert wikidata.resolve({"de-ch": "Weissrussland", "de": "Weißrussland"}, "de-CH") == "Weissrussland"
    assert wikidata.resolve({"de-ch": None, "de": "Schweiz"}, "de-CH") == "Schweiz"
    assert wikidata.resolve({"de": "Schweiz"}, "de-CH") == "Schweiz"
    assert wikidata.resolve({"en": "Switzerland"}, "de-CH") is None  # never another language


def test_sparql_variables_are_sanitized_and_follow_the_chain(monkeypatch):
    queries = []

    def sparql(query):
        queries.append(query)
        return [{"iso": {"value": "CH"}, "item": {"value": "http://www.wikidata.org/entity/Q39"}, "iso3": {"value": "CHE"},
                 "label_en_US": {"value": "Switzerland"}, "label_de_CH": {"value": "Schweiz"},
                 "label_pl_PL": {"value": "Szwajcaria"}}]

    monkeypatch.setattr(wikidata, "_sparql", sparql)
    assert wikidata.fetch_countries(["CH"]) == {
        "CH": [{"qid": "Q39", "iso3": "CHE", "label_en-US": "Switzerland", "label_de-CH": "Schweiz",
                "label_pl-PL": "Szwajcaria", "label_pt-BR": None}]
    }
    (query,) = queries
    assert "SELECT ?iso ?item ?iso3 ?label_en_US ?label_de_CH ?label_pl_PL ?label_pt_BR WHERE" in query
    assert 'OPTIONAL { ?item rdfs:label ?label_de_CH_0 FILTER(LANG(?label_de_CH_0) = "de-ch") }' in query
    assert 'OPTIONAL { ?item rdfs:label ?label_de_CH_1 FILTER(LANG(?label_de_CH_1) = "de") }' in query
    assert "BIND(COALESCE(?label_de_CH_0, ?label_de_CH_1) AS ?label_de_CH)" in query
    assert 'OPTIONAL { ?item rdfs:label ?label_pl_PL_0 FILTER(LANG(?label_pl_PL_0) = "pl") }' in query
    assert "BIND(COALESCE(?label_pt_BR_0, ?label_pt_BR_1) AS ?label_pt_BR)" in query
    assert "?de-CH" not in query and '"de-CH"' not in query


def test_entity_api_asks_for_the_chain_languages(monkeypatch):
    import sys
    import types

    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"entities": {"Q39": {"labels": {"en": {"value": "Switzerland"}, "de": {"value": "Schweiz"}}},
                                 "Q3": {"labels": {"de-ch": {"value": "Weissrussland"}, "de": {"value": "Weißrussland"}}}}}

    def get(url, params, **_):
        calls.append(params)
        return Response()

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get))
    assert wikidata.fetch_labels_api(["Q39", "Q3"]) == {
        "Q39": {"en-US": "Switzerland", "de-CH": "Schweiz", "pl-PL": None, "pt-BR": None},
        "Q3": {"en-US": None, "de-CH": "Weissrussland", "pl-PL": None, "pt-BR": None},
    }
    assert calls[0]["languages"] == "en|de-ch|de|pl|pt-br|pt"
