"""The language registry (``cotw.languages``): one module per locale, nothing else to change.

The first half checks every registered locale; the second half registers a synthetic fifth
locale (``xx-XX``) through the same discovery and shows that a module, the names in the data
and one entry in data/locales.yaml are all it takes: validation and the build pick it up.
"""

from __future__ import annotations

import copy
from dataclasses import replace
import importlib
import json
import re
import sqlite3
import sys
import zipfile

import pytest
import yaml

from cotw import languages, locales, schema, wikidata
from cotw.deck import build
from cotw.deck.lang import CARD_TYPES, FIELD_KEYS

LANGS = [languages.get(code) for code in languages.LANGUAGES]
EPOCH = 1_760_000_000

# The published locales and their frozen identities: the identity is the code they were
# published with before locales had a region. Notes, note types and decks hang on these values;
# every other locale has ``identity == code``.
PUBLISHED = {
    # code: (identity, notetype_id, deck_id, extras_deck_id, id_offset)
    "en-US": ("en", 1829704095, 1866953617, 1918702087, 0),
    "de-CH": ("de", 1123558981, 2041372721, 1539901401, 50_000),
    "pl-PL": ("pl-PL", 2128848329, 2050014339, 1596502066, 100_000),
    "pt-BR": ("pt-BR", 1906050354, 2081751341, 1425183924, 150_000),
}

# The object form of every parent after "dependency of …", per language. A new parent needs a
# decision in every language module (``object_form``), a new language one for every parent.
PARENT_FORMS = {
    "013": {"en-US": "Australia", "de-CH": "Australien", "pl-PL": "Australii", "pt-BR": "da Austrália"},
    "045": {"en-US": "China", "de-CH": "China", "pl-PL": "Chin", "pt-BR": "da China"},
    "060": {"en-US": "Denmark", "de-CH": "Dänemark", "pl-PL": "Danii", "pt-BR": "da Dinamarca"},
    "075": {"en-US": "Finland", "de-CH": "Finnland", "pl-PL": "Finlandii", "pt-BR": "da Finlândia"},
    "076": {"en-US": "France", "de-CH": "Frankreich", "pl-PL": "Francji", "pt-BR": "da França"},
    "155": {"en-US": "the Netherlands", "de-CH": "den Niederlanden", "pl-PL": "Holandii", "pt-BR": "dos Países Baixos"},
    "157": {"en-US": "New Zealand", "de-CH": "Neuseeland", "pl-PL": "Nowej Zelandii", "pt-BR": "da Nova Zelândia"},
    "166": {"en-US": "Norway", "de-CH": "Norwegen", "pl-PL": "Norwegii", "pt-BR": "da Noruega"},
    "235": {"en-US": "the United Kingdom", "de-CH": "dem Vereinigten Königreich", "pl-PL": "Wielkiej Brytanii", "pt-BR": "do Reino Unido"},
    "237": {"en-US": "the United States", "de-CH": "den Vereinigten Staaten", "pl-PL": "Stanów Zjednoczonych", "pt-BR": "dos Estados Unidos"},
}
HELP_PLACEHOLDERS = {"infographic", "infographic_filtered", "repository", "issues"}
DESCRIPTION_PLACEHOLDERS = {
    "count", "repository", "issues", "citation", "manifest", "font_license", "icons_license",
}


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"(?<!\{)\{(\w*)\}(?!\})", text))


# --- every registered language ----------------------------------------------------------------


def test_discovery_order():
    assert languages.BASE == "en-US"
    assert languages.LANGUAGES == ("en-US", "de-CH", "pl-PL", "pt-BR")  # today; a new module joins in code order
    assert languages.LANGUAGES[0] == languages.BASE
    assert list(languages.LANGUAGES[1:]) == sorted(languages.LANGUAGES[1:])
    assert languages.discover() == languages.REGISTRY


def test_ids_are_pinned():
    """Frozen: a changed identity changes every GUID (every note twice in the collection), a
    changed ID installs a second note type (or deck) next to the old one."""
    for code, pinned in PUBLISHED.items():
        spec = languages.get(code)
        assert (spec.identity, spec.notetype_id, spec.deck_id, spec.extras_deck_id, spec.id_offset) == pinned, code
    for spec in LANGS:
        if spec.code not in PUBLISHED:
            assert spec.identity == spec.code  # a new locale never reuses a legacy identity


@pytest.mark.parametrize("code", PUBLISHED)
def test_guid_follows_the_identity_not_the_code(code, monkeypatch, by_id):
    import genanki

    spec = languages.get(code)
    monkeypatch.setitem(languages.REGISTRY, "xx-XX", replace(spec, code="xx-XX"))
    for cid in by_id:
        assert build.guid(cid, code) == build.guid(cid, "xx-XX") == genanki.guid_for("cotw", spec.identity, cid)


@pytest.mark.parametrize("lang", LANGS, ids=languages.LANGUAGES)
def test_ids_follow_the_documented_rule(lang):
    assert lang.notetype_id == languages.derive_id(lang.identity, "notetype")
    assert lang.deck_id == languages.derive_id(lang.identity, "deck")
    assert lang.extras_deck_id == languages.derive_id(lang.identity, "deck-extras")
    assert lang.id_offset % languages.OFFSET_STEP == 0


def test_ids_offsets_and_names_are_unique():
    ids = [i for lang in LANGS for i in (lang.notetype_id, lang.deck_id, lang.extras_deck_id)]
    assert len(set(ids)) == len(ids)
    # Not the Wikipedia: sister locales share one (de-CH, de-DE: dewiki). A sister needs its own
    # deck name, though, and its own identity (so it never reuses a GUID namespace).
    for key in ("code", "identity", "id_offset", "notetype", "deck", "extras", "tag_root"):
        values = [getattr(lang, key) for lang in LANGS]
        assert len(set(values)) == len(values), key


@pytest.mark.parametrize("lang", LANGS, ids=languages.LANGUAGES)
def test_language_is_complete(lang, taxonomy):
    base = languages.get(languages.BASE)
    assert lang.code in locales.TAGS and locales.TAG_SHAPE.fullmatch(lang.code)
    assert importlib.import_module(f"cotw.languages.{languages.module_name(lang.code)}").LANGUAGE is lang
    assert lang.tag_root == f"COTW-{lang.code.upper()}" and lang.notetype == f"COTW ({lang.code.upper()})"
    assert lang.extras.startswith(lang.deck + "::")
    assert list(lang.fields) == list(FIELD_KEYS)
    assert len(set(lang.fields.values())) == len(FIELD_KEYS)  # Anki needs distinct field names
    assert list(lang.templates) == [c["key"] for c in CARD_TYPES]
    assert len(set(lang.templates.values())) == len(CARD_TYPES)
    assert set(lang.status_tags) == set(schema.STATUSES)
    assert lang.ui.keys() == base.ui.keys() and lang.comments.keys() == base.comments.keys()
    assert all(v.strip() for m in (lang.fields, lang.templates, lang.status_tags, lang.ui, lang.comments) for v in m.values())
    assert lang.dependency_of.count("{}") == 1 and lang.status_disputed.strip()
    regions = {name for path in taxonomy for name in path}
    assert regions <= lang.regions.keys() and all(lang.regions[r].strip() for r in regions)


def test_base_language_names_regions_as_in_the_data(taxonomy):
    base = languages.get(languages.BASE)
    assert all(base.regions[r] == r for path in taxonomy for r in path)


@pytest.mark.parametrize("lang", LANGS, ids=languages.LANGUAGES)
def test_help_and_descriptions_have_their_placeholders(lang):
    assert _placeholders(lang.help) == HELP_PLACEHOLDERS
    assert _placeholders(lang.description) == DESCRIPTION_PLACEHOLDERS
    assert _placeholders(lang.extras_description) == set()
    lang.help.format(**dict.fromkeys(HELP_PLACEHOLDERS, ""))  # no stray braces
    lang.description.format(**dict.fromkeys(DESCRIPTION_PLACEHOLDERS, ""))


def test_object_form_is_decided_for_every_parent(by_id):
    parents = {e["dependency_of"] for e in by_id.values() if e.get("dependency_of")}
    assert parents == PARENT_FORMS.keys(), "a new parent needs its object form in every language"
    for pid, forms in PARENT_FORMS.items():
        assert forms.keys() == set(languages.LANGUAGES), pid
        for code, form in forms.items():
            assert build.display_name(by_id[pid]["name"][code], code) == form, (pid, code)


# --- a fifth locale, registered through the discovery -------------------------------------------

# A variant built from a sister module (docs/DECK.md, "A new language"): everything of en-US
# except what must be its own. A real locale has its own texts.
XX_MODULE = '''"""Test locale: a copy of English (United States) with its own identities."""

from __future__ import annotations

import dataclasses

from .en_us import LANGUAGE as EN_US

LANGUAGE = dataclasses.replace(
    EN_US,
    code="xx-XX",
    identity="xx-XX",
    notetype_id={notetype},
    deck_id={deck},
    extras_deck_id={extras},
    id_offset=200_000,
    notetype="COTW (XX-XX)",
    deck="Countries of the World XX",
    extras="Countries of the World XX::Extras",
    tag_root="COTW-XX-XX",
)
'''

# Its entry in data/locales.yaml.
XX_LOCALE = {
    "tag": "xx-XX",
    "endonym": "Xx (Xx)",
    "english": "Test language",
    "wiki": "xxwiki",
    "wikipedia": "https://xx.wikipedia.org/wiki/",
    "wikidata": ["xx"],
}


PACKAGE_PATH = list(languages.__path__)


@pytest.fixture
def add_locale(tmp_path, monkeypatch):
    """data/locales.yaml, copied; ``add_locale(entry)`` appends an entry to the copy in use."""
    path, raw = tmp_path / "locales.yaml", locales.read()

    def add(entry=None):
        raw.extend([entry] if entry else [])
        path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        locales._load.cache_clear()

    monkeypatch.setattr(locales, "LOCALES_FILE", path)
    add()
    yield add
    locales._load.cache_clear()


def _discover_with(directory, monkeypatch, stem: str, source: str) -> dict:
    """A fresh discovery with one more module, ``<stem>.py``, in a second package directory."""
    directory.mkdir()
    (directory / f"{stem}.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(languages, "__path__", [*PACKAGE_PATH, str(directory)])
    return languages.discover()


def _ids(identity: str) -> dict[str, int]:
    return {k: languages.derive_id(identity, kind) for k, kind in (("notetype", "notetype"), ("deck", "deck"), ("extras", "deck-extras"))}


def test_registry_rejects_a_code_missing_from_the_locale_list(add_locale, tmp_path, monkeypatch):
    try:
        with pytest.raises(ValueError, match=r"languages/xx_xx.py: 'xx-XX' is not in data/locales.yaml"):
            _discover_with(tmp_path / "pkg", monkeypatch, "xx_xx", XX_MODULE.format(**_ids("xx-XX")))
    finally:
        sys.modules.pop("cotw.languages.xx_xx", None)


@pytest.mark.parametrize("stem", ["xx", "xx_XX", "xxxx", "de_ch_xx"])
def test_registry_rejects_a_file_name_that_is_not_the_code(stem, add_locale, tmp_path, monkeypatch):
    add_locale(XX_LOCALE)
    try:
        with pytest.raises(ValueError, match=rf"languages/{stem}.py defines code 'xx-XX', expected xx_xx.py"):
            _discover_with(tmp_path / "pkg", monkeypatch, stem, XX_MODULE.format(**_ids("xx-XX")))
    finally:
        sys.modules.pop(f"cotw.languages.{stem}", None)


@pytest.fixture
def xx(add_locale, tmp_path, monkeypatch):
    """``languages/xx_xx.py`` in a second directory of the package and the locale's entry in
    data/locales.yaml, then a fresh discovery."""
    add_locale(XX_LOCALE)
    registry = _discover_with(tmp_path / "languages", monkeypatch, "xx_xx", XX_MODULE.format(**_ids("xx-XX")))
    monkeypatch.setattr(languages, "REGISTRY", registry)
    monkeypatch.setattr(languages, "LANGUAGES", tuple(registry))
    yield languages.get("xx-XX")
    sys.modules.pop("cotw.languages.xx_xx", None)


def _with_xx(entry: dict) -> dict:
    """The entry with ``xx-XX`` names (copies of the en-US ones) in every text map."""
    e = copy.deepcopy(entry)
    for texts in [e["name"], e.get("name_label"), e.get("formal_name")] + [t for c in e["capitals"] for t in (c["name"], c.get("label"))]:
        if texts:  # complete the positive fixture; only shared optional maps require this
            texts["xx-XX"] = texts.get("en-US", next(iter(texts.values())))
    return e


def test_fifth_locale_is_discovered(xx):
    assert languages.LANGUAGES == ("en-US", "de-CH", "pl-PL", "pt-BR", "xx-XX")
    assert xx.identity == xx.code  # a new locale: the identity is its code
    assert xx.id_offset == 200_000 and xx.notetype_id == languages.derive_id("xx-XX", "notetype")
    assert wikidata.chain("xx-XX") == ("xx",) and wikidata.wikis()["xx-XX"] == "xxwiki"
    assert wikidata.wikipedia_url("xx-XX", "Mätzland") == "https://xx.wikipedia.org/wiki/Mätzland"


def test_fifth_locale_is_required_by_validate(xx, by_id, capsys):
    ch = by_id["217"]
    problems = schema.validate_entry(ch)
    assert "217: name.xx-XX: missing" in problems
    assert "217: capitals[0].name.xx-XX: missing" in problems
    assert not any("formal_name" in p for p in problems)  # optional per locale
    assert "217: capitals[0].label.xx-XX: missing (present in other languages)" in problems
    assert schema.validate_entry(_with_xx(ch)) == []
    # The command line validates the committed data, which has no xx-XX names yet.
    from cotw.__main__ import main

    assert main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "217-switzerland.yaml: name.xx-XX: missing" in out and "capitals[0].name.xx-XX: missing" in out


def test_fifth_locale_is_built_by_default(xx, by_id, tmp_path, monkeypatch):
    fixture = {cid: _with_xx(e) for cid, e in by_id.items()}
    monkeypatch.setattr(build, "load_entries", lambda: (list(fixture.values()), fixture))
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    from cotw.__main__ import main

    out = tmp_path / "out"
    assert main(["build-deck", "--out", str(out), "--only", "CH,GL"]) == 0
    assert sorted(p.name for p in out.glob("*.apkg")) == [
        "COTW-DE-CH.apkg", "COTW-EN-US.apkg", "COTW-PL-PL.apkg", "COTW-PT-BR.apkg", "COTW-XX-XX.apkg"
    ]
    with zipfile.ZipFile(out / "COTW-XX-XX.apkg") as z:
        (tmp_path / "xx.anki2").write_bytes(z.read("collection.anki2"))
    col = sqlite3.connect(tmp_path / "xx.anki2")
    (models,) = col.execute("SELECT models FROM col").fetchone()
    (nt,) = json.loads(models).values()
    assert (int(nt["id"]), nt["name"]) == (xx.notetype_id, "COTW (XX-XX)")
    assert 'class="cotw cotw-xx-XX"' in nt["tmpls"][0]["qfmt"]
    decks = {d["name"]: d["id"] for d in json.loads(col.execute("SELECT decks FROM col").fetchone()[0]).values()}
    assert decks[xx.deck] == xx.deck_id and decks[xx.extras] == xx.extras_deck_id
    notes = dict(col.execute("SELECT guid, tags FROM notes"))
    assert notes.keys() == {build.guid("217", "xx-XX"), build.guid("087", "xx-XX")}
    assert all(tag.startswith("COTW-XX-XX::") for tags in notes.values() for tag in tags.split())
    (first,) = col.execute("SELECT min(id) FROM notes").fetchone()
    assert first == EPOCH * 1000 + 200_000
    help_text = " ".join(t["qfmt"] for t in nt["tmpls"])
    repository = build.load_config()["repository"].rstrip("/")
    assert repository in help_text and f"{repository}/issues" in help_text
    col.close()
