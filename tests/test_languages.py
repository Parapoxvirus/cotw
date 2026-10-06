"""The language registry (``cotw.languages``): one module per language, nothing else to change.

The first half checks every registered language; the second half registers a synthetic third
language through the same discovery and shows that validation and the build pick it up.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import sys
import zipfile

import pytest

from cotw import languages, schema
from cotw.deck import build
from cotw.deck.lang import CARD_TYPES, FIELD_KEYS

LANGS = [languages.get(code) for code in languages.LANGUAGES]
EPOCH = 1_760_000_000

# The object form of every parent after "dependency of …", per language. A new parent needs a
# decision in every language module (``object_form``), a new language one for every parent.
PARENT_FORMS = {
    "013": {"en": "Australia", "de": "Australien"},
    "045": {"en": "China", "de": "China"},
    "060": {"en": "Denmark", "de": "Dänemark"},
    "075": {"en": "Finland", "de": "Finnland"},
    "076": {"en": "France", "de": "Frankreich"},
    "155": {"en": "the Netherlands", "de": "den Niederlanden"},
    "157": {"en": "New Zealand", "de": "Neuseeland"},
    "166": {"en": "Norway", "de": "Norwegen"},
    "235": {"en": "the United Kingdom", "de": "dem Vereinigten Königreich"},
    "237": {"en": "the United States", "de": "den Vereinigten Staaten"},
}
HELP_PLACEHOLDERS = {"infographic", "infographic_filtered", "ankiweb", "contact"}
DESCRIPTION_PLACEHOLDERS = {"count", "citation", "manifest", "font_license", "icons_license"}


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"(?<!\{)\{(\w*)\}(?!\})", text))


# --- every registered language ----------------------------------------------------------------


def test_discovery_order():
    assert languages.LANGUAGES == ("en", "de")  # today; a new module joins in code order
    assert languages.LANGUAGES[0] == languages.BASE
    assert list(languages.LANGUAGES[1:]) == sorted(languages.LANGUAGES[1:])
    assert languages.discover() == languages.REGISTRY


def test_ids_are_pinned():
    """Frozen: a changed ID installs a second note type (or deck) next to the old one."""
    en, de = languages.get("en"), languages.get("de")
    assert (en.notetype_id, en.deck_id, en.extras_deck_id, en.id_offset) == (1829704095, 1866953617, 1918702087, 0)
    assert (de.notetype_id, de.deck_id, de.extras_deck_id, de.id_offset) == (1123558981, 2041372721, 1539901401, 50_000)


@pytest.mark.parametrize("lang", LANGS, ids=languages.LANGUAGES)
def test_ids_follow_the_documented_rule(lang):
    assert lang.notetype_id == languages.derive_id(lang.code, "notetype")
    assert lang.deck_id == languages.derive_id(lang.code, "deck")
    assert lang.extras_deck_id == languages.derive_id(lang.code, "deck-extras")
    assert lang.id_offset % languages.OFFSET_STEP == 0


def test_ids_offsets_and_names_are_unique():
    ids = [i for lang in LANGS for i in (lang.notetype_id, lang.deck_id, lang.extras_deck_id)]
    assert len(set(ids)) == len(ids)
    for key in ("id_offset", "notetype", "deck", "extras", "tag_root", "wiki"):
        values = [getattr(lang, key) for lang in LANGS]
        assert len(set(values)) == len(values), key


@pytest.mark.parametrize("lang", LANGS, ids=languages.LANGUAGES)
def test_language_is_complete(lang, taxonomy):
    base = languages.get(languages.BASE)
    assert re.fullmatch(r"[a-z]{2}", lang.code) and lang.wiki == f"{lang.code}wiki"
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
    assert lang.ankiweb is None or lang.ankiweb.startswith("https://ankiweb.net/shared/info/")


def test_base_language_names_regions_as_in_the_data(taxonomy):
    base = languages.get(languages.BASE)
    assert all(base.regions[r] == r for path in taxonomy for r in path)
    assert base.ankiweb  # the fallback for a language without its own listing


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


# --- a third language, registered through the discovery ------------------------------------------

XX_MODULE = '''"""Test language: a copy of English with its own identities."""

from __future__ import annotations

import dataclasses

from .en import LANGUAGE as EN

LANGUAGE = dataclasses.replace(
    EN,
    code="xx",
    wiki="xxwiki",
    notetype_id={notetype},
    deck_id={deck},
    extras_deck_id={extras},
    id_offset=100_000,
    notetype="COTW (XX)",
    deck="Countries of the World XX",
    extras="Countries of the World XX::Extras",
    tag_root="COTW-XX",
    ankiweb=None,
)
'''


@pytest.fixture
def xx(tmp_path, monkeypatch):
    """``languages/xx.py`` in a second directory of the package, then a fresh discovery."""
    pkg = tmp_path / "languages"
    pkg.mkdir()
    ids = {k: languages.derive_id("xx", kind) for k, kind in (("notetype", "notetype"), ("deck", "deck"), ("extras", "deck-extras"))}
    (pkg / "xx.py").write_text(XX_MODULE.format(**ids), encoding="utf-8")
    monkeypatch.setattr(languages, "__path__", [*languages.__path__, str(pkg)])
    registry = languages.discover()
    monkeypatch.setattr(languages, "REGISTRY", registry)
    monkeypatch.setattr(languages, "LANGUAGES", tuple(registry))
    yield languages.get("xx")
    sys.modules.pop("cotw.languages.xx", None)


def _with_xx(entry: dict) -> dict:
    """The entry with ``xx`` names (copies of the EN ones) in every text map."""
    e = copy.deepcopy(entry)
    for texts in [e["name"], e.get("name_label"), e.get("formal_name")] + [t for c in e["capitals"] for t in (c["name"], c.get("label"))]:
        if texts:  # optional maps are absent or complete (validate)
            texts["xx"] = texts["en"]
    return e


def test_third_language_is_discovered(xx):
    assert languages.LANGUAGES == ("en", "de", "xx")
    assert xx.id_offset == 100_000 and xx.notetype_id == languages.derive_id("xx", "notetype")


def test_third_language_is_required_by_validate(xx, by_id, capsys):
    ch = by_id["217"]
    problems = schema.validate_entry(ch)
    assert "217: name.xx: missing" in problems
    assert "217: capitals[0].name.xx: missing" in problems
    assert "217: formal_name.xx: missing (present in other languages)" in problems
    assert "217: capitals[0].label.xx: missing (present in other languages)" in problems
    assert schema.validate_entry(_with_xx(ch)) == []
    # The command line validates the committed data, which has no xx names yet.
    from cotw.__main__ import main

    assert main(["validate"]) == 1
    out = capsys.readouterr().out
    assert "217-switzerland.yaml: name.xx: missing" in out and "capitals[0].name.xx: missing" in out


def test_third_language_is_built_by_default(xx, by_id, tmp_path, monkeypatch):
    fixture = {cid: _with_xx(e) for cid, e in by_id.items()}
    monkeypatch.setattr(build, "load_entries", lambda: (list(fixture.values()), fixture))
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    from cotw.__main__ import main

    assert main(["build-deck", "--out", str(tmp_path), "--only", "CH,GL"]) == 0
    assert sorted(p.name for p in tmp_path.glob("*.apkg")) == ["COTW-DE.apkg", "COTW-EN.apkg", "COTW-XX.apkg"]
    with zipfile.ZipFile(tmp_path / "COTW-XX.apkg") as z:
        (tmp_path / "xx.anki2").write_bytes(z.read("collection.anki2"))
    col = sqlite3.connect(tmp_path / "xx.anki2")
    (models,) = col.execute("SELECT models FROM col").fetchone()
    (nt,) = json.loads(models).values()
    assert (int(nt["id"]), nt["name"]) == (xx.notetype_id, "COTW (XX)")
    decks = {d["name"]: d["id"] for d in json.loads(col.execute("SELECT decks FROM col").fetchone()[0]).values()}
    assert decks[xx.deck] == xx.deck_id and decks[xx.extras] == xx.extras_deck_id
    notes = dict(col.execute("SELECT guid, tags FROM notes"))
    assert notes.keys() == {build.guid("217", "xx"), build.guid("087", "xx")}
    assert all(tag.startswith("COTW-XX::") for tags in notes.values() for tag in tags.split())
    (first,) = col.execute("SELECT min(id) FROM notes").fetchone()
    assert first == EPOCH * 1000 + 100_000
    help_text = " ".join(t["qfmt"] for t in nt["tmpls"])
    assert languages.get(languages.BASE).ankiweb in help_text  # no listing of its own yet
    col.close()
