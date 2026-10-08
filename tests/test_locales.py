"""The curated locale list ``data/locales.yaml`` and its loader (``cotw.locales``).

The first half checks the committed list: shape, required locales, BCP 47 validity (with
``langcodes``, dev extra only). The second half feeds broken lists to the loader.
"""

from __future__ import annotations

import copy

import pytest

from cotw import __main__ as cli
from cotw import locales

RAW = locales.read()

EU_LANGUAGES = {
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "ga", "hr",
    "hu", "it", "lt", "lv", "mt", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
}  # fmt: skip
UN_LANGUAGES = {"ar", "zh", "en", "fr", "ru", "es"}
VARIANTS = {
    "en-GB", "de-DE", "pt-PT", "zh-Hans-CN", "zh-Hant-TW", "sr-Cyrl-RS", "sr-Latn-RS",
    "es-ES", "es-419", "fr-FR", "fr-CA", "nb-NO", "nn-NO",
}  # fmt: skip
# The Wikipedia and Wikidata behaviour the published decks (en, de) have today, and the two
# locales planned next.
PINNED = {
    "en-US": ("enwiki", "https://en.wikipedia.org/wiki/", ("en",)),
    "de-CH": ("dewiki", "https://de.wikipedia.org/wiki/", ("de-ch", "de")),
    "pl-PL": ("plwiki", "https://pl.wikipedia.org/wiki/", ("pl",)),
    "pt-BR": ("ptwiki", "https://pt.wikipedia.org/wiki/", ("pt-br", "pt")),
}
# ISO 3166-1 user-assigned codes and the "unknown region": valid subtags, but no real region.
PRIVATE_REGIONS = {"AA", "ZZ"} | {f"Q{c}" for c in "MNOPQRSTUVWXYZ"} | {f"X{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


# --- the committed list -----------------------------------------------------------------------


def test_file_is_valid():
    assert locales.problems(RAW) == []
    assert locales.TAGS == tuple(e["tag"] for e in RAW)
    assert set(locales.LOCALES) == set(locales.TAGS)


def test_size_and_order():
    assert 40 <= len(locales.TAGS) <= 60
    assert list(locales.TAGS) == sorted(locales.TAGS), "data/locales.yaml is sorted by tag"


def test_required_locales():
    tags = set(locales.TAGS)
    languages = {t.split("-")[0] for t in tags}
    assert set(PINNED) <= tags
    assert VARIANTS <= tags
    assert EU_LANGUAGES <= languages
    assert UN_LANGUAGES <= languages


@pytest.mark.parametrize("tag", PINNED)
def test_pinned_sources(tag):
    loc = locales.get(tag)
    assert (loc.wiki, loc.wikipedia, loc.wikidata) == PINNED[tag]


def test_script_variants_pin_the_wikipedia_variant():
    assert locales.get("zh-Hant-TW").wikipedia == "https://zh.wikipedia.org/zh-hant/"
    assert locales.get("sr-Latn-RS").wikipedia == "https://sr.wikipedia.org/sr-el/"


def test_de_ch_naming_source_is_the_eda_list():
    source = locales.get("de-CH").naming_source
    assert source.title == "Liste der Staatenbezeichnungen"
    assert "EDA" in source.publisher
    assert source.url.startswith("https://www.eda.admin.ch/")


def test_names_are_unique():
    for key in ("endonym", "english"):
        names = [getattr(loc, key) for loc in locales.LOCALES.values()]
        assert len(names) == len(set(names)), key


def test_endonym_names_the_region_only_for_a_shared_language():
    """The region or script goes in parentheses exactly when another locale shares the language."""
    by_language: dict[str, int] = {}
    for tag in locales.TAGS:
        by_language[tag.split("-")[0]] = by_language.get(tag.split("-")[0], 0) + 1
    for loc in locales.LOCALES.values():
        shared = by_language[loc.tag.split("-")[0]] > 1
        assert loc.english.endswith(")") == shared, loc.tag
        assert loc.endonym.endswith((")", "）")) == shared, loc.tag


def test_tags_are_valid_bcp47():
    """Not just well-formed: registered subtags (IANA registry / CLDR), canonical form, a real region."""
    langcodes = pytest.importorskip("langcodes")
    for tag in locales.TAGS:
        assert langcodes.tag_is_valid(tag), tag
        assert langcodes.standardize_tag(tag) == tag, f"{tag}: not canonical"
        assert langcodes.Language.get(tag).territory not in PRIVATE_REGIONS, f"{tag}: private-use region"


def test_get_unknown_tag():
    with pytest.raises(KeyError):
        locales.get("xx-XX")


# --- broken lists -----------------------------------------------------------------------------


def _with(tag: str, /, **changes) -> list[dict]:
    """The committed list with one entry changed; a value of None removes the field."""
    raw = copy.deepcopy(RAW)
    entry = next(e for e in raw if e["tag"] == tag)
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return raw


@pytest.mark.parametrize(
    "tag",
    ["de", "de_CH", "de-ch", "DE-CH", "de-Ch", "de-che", "de-1", "zh-hans-CN", "zh-HANS-CN", "zh-Hans", "en-US-x-cotw", "en-US "],
)
def test_malformed_tag(tag):
    found = locales.problems(_with("pl-PL", tag=tag))
    assert any("must be language(-Script)?-REGION" in p for p in found), found


@pytest.mark.parametrize("tag", ["de-CH", "de-ch"])
def test_duplicate_tag(tag):
    raw = copy.deepcopy(RAW) + [dict(copy.deepcopy(RAW[0]), tag=tag)]
    found = locales.problems(raw)
    assert any("duplicate tag" in p for p in found), found


@pytest.mark.parametrize("field", locales.REQUIRED)
def test_missing_field(field):
    found = locales.problems(_with("pl-PL", **{field: None}))
    assert any(p.endswith(f"missing {field}") for p in found), found


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"endonym": ""}, "endonym must be a non-empty string"),
        ({"english": " Polish"}, "english must be a non-empty string"),
        ({"wiki": "pl.wikipedia"}, "must be a Wikidata site ID"),
        ({"wikipedia": "http://pl.wikipedia.org/wiki/"}, "must be https://"),
        ({"wikipedia": "https://pl.wikipedia.org/wiki"}, "must be https://"),
        ({"wikipedia": "https://pl.wikipedia.org/"}, "must be https://"),
        ({"wikipedia": "https://example.com/wiki/"}, "must be https://"),
        ({"wikipedia": "https://de.wikipedia.org/wiki/"}, "is not the site of wiki"),
        ({"wikidata": []}, "wikidata must be a non-empty list"),
        ({"wikidata": "pl"}, "wikidata must be a non-empty list"),
        ({"wikidata": ["pl-PL"]}, "are not Wikidata language codes"),
        ({"wikidata": ["pl", "pl"]}, "lists a language twice"),
        ({"naming_source": "KSNG"}, "naming_source must be a mapping"),
        ({"naming_source": {"title": "Wykaz", "publisher": "KSNG"}}, "naming_source.url must be a non-empty string"),
        ({"naming_source": {"title": "Wykaz", "publisher": "KSNG", "url": "http://example.com/"}}, "must start with https://"),
        ({"naming_source": {"title": "W", "publisher": "K", "url": "https://example.com/", "year": 2025}}, "unknown field 'year'"),
        ({"script": "Latn"}, "unknown field 'script'"),
    ],
)
def test_broken_entry(changes, message):
    found = locales.problems(_with("pl-PL", **changes))
    assert any(message in p for p in found), found
    assert all(p.startswith("data/locales.yaml: pl-PL: ") for p in found), found


@pytest.mark.parametrize("raw", [None, [], {"pl-PL": {}}, ["pl-PL"]])
def test_broken_file(raw):
    assert locales.problems(raw)


def test_parse_rejects_and_lists_every_problem():
    raw = _with("pl-PL", wiki=None, wikidata=[])
    with pytest.raises(ValueError) as e:
        locales.parse(raw)
    assert "missing wiki" in str(e.value) and "wikidata must be" in str(e.value)


def test_parse_keeps_configured_sources_and_optional_absence():
    parsed = locales.parse(RAW)
    assert parsed["pt-BR"].naming_source == locales.NamingSource(
        title="Manual de redação oficial e diplomática do Itamaraty",
        publisher="Ministério das Relações Exteriores do Brasil",
        url="https://www.gov.br/mre/pt-br/arquivos/manual-de-redacao",
    )
    assert parsed["es-419"].naming_source is None
    assert parsed["pl-PL"].naming_source.publisher.endswith("(KSNG)")


def test_validate_reports_locale_problems(monkeypatch, capsys):
    monkeypatch.setattr(locales, "read", lambda: _with("pl-PL", tag="pl_PL"))
    assert cli.cmd_validate(None) == 1
    out = capsys.readouterr().out
    assert "data/locales.yaml: pl_PL: tag 'pl_PL' must be" in out
