"""Coexistence proof: all packages imported into a real Anki collection (the ``anki`` package).

The packages of every registered language must install side by side in any order, and each
must be updatable on its own (docs/DECK.md). The version-skew case is simulated: a later EN build with a changed field
medium (a map), a changed template asset (the globe) and a changed capital, imported while
the older DE package stays installed.

The upgrade from the packages published before the locale codes (``COTW-EN.apkg``,
``COTW-DE.apkg``: code ``en``/``de``, note types ``COTW (EN)``/``COTW (DE)``, tags ``COTW-EN::``/
``COTW-DE::``) to the locale packages keeps every note, its note type and its review history.
Those packages are rebuilt here from the frozen identities with the old public names
(``LEGACY``); ``COTW_LEGACY_PACKAGES=<dir>`` runs the same test against real ones (a build of
the last commit before the locale codes, or the published release assets).
"""

from __future__ import annotations

import copy
import dataclasses
import os
import re
import shutil
from pathlib import Path

import pytest

pytest.importorskip("genanki")
anki_collection = pytest.importorskip("anki.collection")

from anki.import_export_pb2 import ImportAnkiPackageOptions  # noqa: E402

from cotw import languages  # noqa: E402
from cotw.deck import build, lang  # noqa: E402
from cotw.paths import MEDIA  # noqa: E402

EPOCH_V1 = 1_760_000_000
EPOCH_V2 = EPOCH_V1 + 86_400 * 365  # a year later
CHANGED_MAP = "cotw-217-map1-day.svg"
EN, DE = languages.get("en-US"), languages.get("de-CH")

# What the packages before the locale codes (v1.0.x) shipped per locale: the code (CSS class,
# data-lang, file name), the note type name and the tag root. Identities and IDs are the same.
LEGACY = {
    "en-US": ("en", "COTW (EN)", "COTW-EN"),
    "de-CH": ("de", "COTW (DE)", "COTW-DE"),
}


@pytest.fixture(scope="module")
def releases(tmp_path_factory) -> dict[str, dict[str, Path]]:
    root = tmp_path_factory.mktemp("releases")
    entries, by_id = build.load_entries()
    v1 = {c: build.build_package(c, entries, by_id, root / "v1", EPOCH_V1).path for c in languages.LANGUAGES}

    media = root / "media-v2"
    shutil.copytree(MEDIA, media)
    (media / CHANGED_MAP).write_text(
        (media / CHANGED_MAP).read_text(encoding="utf-8").replace("</svg>", "<!-- v2 --></svg>"), encoding="utf-8"
    )
    for key in build.GLOBE_ASSETS:
        name = build.ASSET_SOURCES[key].name
        (media / name).write_text((media / name).read_text(encoding="utf-8") + "\n// v2\n", encoding="utf-8")
    by_id2 = copy.deepcopy(by_id)
    by_id2["217"]["capitals"][0]["name"] = dict.fromkeys(languages.LANGUAGES, "Bern (v2)")
    v2 = {
        c: build.build_package(c, list(by_id2.values()), by_id2, root / "v2", EPOCH_V2, media_dir=media).path
        for c in languages.LANGUAGES
    }
    return {"v1": v1, "v2": v2}


@pytest.fixture
def col(tmp_path):
    c = anki_collection.Collection(str(tmp_path / "collection.anki2"))
    yield c
    c.close()


def _import(col, path: Path):
    req = anki_collection.ImportAnkiPackageRequest(package_path=str(path), options=ImportAnkiPackageOptions())
    log = col.import_anki_package(req).log
    col.models._clear_cache()  # the Python side caches note types; the import ran in the backend
    return log


def _cotw_notetypes(col) -> dict[str, dict]:
    return {m["name"]: m for m in col.models.all() if m["name"].startswith("COTW")}


def _template_assets(nt: dict) -> set[str]:
    texts = [nt["css"]] + [t[k] for t in nt["tmpls"] for k in ("qfmt", "afmt")]
    return {m for t in texts for m in re.findall(r'(?:src="|url\(")(_cotw-[^"]+)"', t)}


def _assert_consistent(col) -> None:
    """One note type per language, the expected decks, no duplicates, every referenced file present."""
    nts = _cotw_notetypes(col)
    specs = [languages.get(code) for code in languages.LANGUAGES]
    assert set(nts) == {spec.notetype for spec in specs}
    assert {spec.notetype: spec.notetype_id for spec in specs} == {name: nt["id"] for name, nt in nts.items()}
    decks = {d.name for d in col.decks.all_names_and_ids()}
    for spec in specs:
        assert {spec.deck, spec.extras} <= decks
        nids = col.find_notes(f'"note:{spec.notetype}"')
        assert len(nids) == 248
        assert len({col.get_note(n).guid for n in nids}) == 248
        assert len({col.get_note(n)[spec.fields["country"]] for n in nids}) == 248
    assert col.note_count() == len(specs) * 248
    media_dir = Path(col.media.dir())
    for nt in nts.values():
        missing = {a for a in _template_assets(nt) if not (media_dir / a).exists()}
        assert not missing, (nt["name"], missing)
    check = col.media.check()
    assert list(check.missing) == []


@pytest.mark.parametrize("order", [languages.LANGUAGES, languages.LANGUAGES[::-1]])
def test_both_packages_side_by_side(col, releases, order):
    for code in order:
        log = _import(col, releases["v1"][code])
        assert len(log.new) == 248 and not log.updated and not log.conflicting
    _assert_consistent(col)
    # Shared media is stored once and never renamed.
    files = set(os.listdir(col.media.dir()))
    assert len(files) == 248 * 5 + len(build.ASSET_SOURCES)
    assert not [f for f in files if re.search(r"-[0-9a-f]{40}\.", f)]
    for code in order:
        spec = languages.get(code)
        deck = col.decks.id_for_name(spec.deck)
        extras = col.decks.id_for_name(spec.extras)
        in_main = col.find_cards(f'"deck:{spec.deck}" -"deck:{spec.extras}"')
        in_extras = col.find_cards(f'"deck:{spec.extras}"')
        assert len(in_main) == 5 * 248 and deck and extras
        assert {col.get_card(c).ord for c in in_extras} == {i for i, c in enumerate(lang.CARD_TYPES) if c["extra"]}


def test_reimport_changes_nothing(col, releases):
    for code in languages.LANGUAGES * 2:
        _import(col, releases["v1"][code])
    _assert_consistent(col)
    assert len(os.listdir(col.media.dir())) == 248 * 5 + len(build.ASSET_SOURCES)


def test_updating_one_language_leaves_the_other_intact(col, releases):
    for code in languages.LANGUAGES:
        _import(col, releases["v1"][code])
    media_dir = Path(col.media.dir())
    old_map = (media_dir / CHANGED_MAP).read_bytes()
    old_de_assets = _template_assets(_cotw_notetypes(col)[DE.notetype])

    log = _import(col, releases["v2"][EN.code])
    assert len(log.updated) == 248 and not log.new
    _assert_consistent(col)
    nts = _cotw_notetypes(col)

    # EN moved on: new capital, new globe, its map under a new name with the new content.
    ch_en = col.get_note(col.find_notes(f'"note:{EN.notetype}" "Country:Switzerland"')[0])
    assert ch_en["Capital 1"] == "Bern (v2)"
    new_src = re.search(r'src="([^"]+)"', ch_en["Map 1"]).group(1)
    assert new_src != CHANGED_MAP and b"v2" in (media_dir / new_src).read_bytes()
    en_globe = {a for a in _template_assets(nts[EN.notetype]) if a.startswith("_cotw-globe-")}
    assert en_globe and not en_globe & old_de_assets
    assert len(en_globe) == 3  # bootstrap and its matching deferred packets coexist independently

    # DE is untouched: old capital, old map bytes, old globe still there and referenced.
    ch_de = col.get_note(col.find_notes(f'"note:{DE.notetype}" "Land:Schweiz"')[0])
    assert ch_de["Hauptstadt 1"] == "Bern"
    assert ch_de["Karte 1"] == build.map_field("217", "map1")  # both files, the old day map
    assert f'src="{CHANGED_MAP}"' in ch_de["Karte 1"]
    assert (media_dir / CHANGED_MAP).read_bytes() == old_map
    assert _template_assets(nts[DE.notetype]) == old_de_assets
    assert list(col.media.check().unused) == []

    # The others catch up later: all now share the one new map file; the old one is left over
    # and reported as unused by Check Media (a field medium, so Anki may clean it up).
    for code in languages.LANGUAGES:
        if code != EN.code:
            _import(col, releases["v2"][code])
    _assert_consistent(col)
    ch_de = col.get_note(col.find_notes(f'"note:{DE.notetype}" "Land:Schweiz"')[0])
    assert re.search(r'src="([^"]+)"', ch_de["Karte 1"]).group(1) == new_src
    assert "cotw-217-map1-night.svg" in ch_de["Karte 1"]  # the unchanged night map keeps its name
    assert list(col.media.check().unused) == [CHANGED_MAP]
    assert _template_assets(_cotw_notetypes(col)[DE.notetype]) == _template_assets(_cotw_notetypes(col)[EN.notetype])


# --- upgrade from the packages before the locale codes ----------------------------------------------


def _legacy_entries(by_id: dict) -> dict:
    """The entries with every locale's texts also under its old code (``de`` next to ``de-CH``)."""
    out = copy.deepcopy(by_id)
    for e in out.values():
        maps = [e["name"], e.get("name_label"), e.get("formal_name"), e["wikipedia"]]
        for texts in maps + [t for c in e["capitals"] for t in (c["name"], c.get("label"))]:
            for code, (old, _, _) in LEGACY.items():
                if texts and code in texts:
                    texts[old] = texts[code]
    return out


@pytest.fixture(scope="module")
def legacy(tmp_path_factory) -> dict[str, Path]:
    """Per locale the package before the locale codes: real ones from ``COTW_LEGACY_PACKAGES``,
    else rebuilt from the registry with the old code, note type name and tag root."""
    real = os.environ.get("COTW_LEGACY_PACKAGES")
    if real:
        return {code: Path(real) / f"COTW-{old.upper()}.apkg" for code, (old, _, _) in LEGACY.items()}
    root = tmp_path_factory.mktemp("legacy")
    _, by_id = build.load_entries()
    old_by_id = _legacy_entries(by_id)
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        for code, (old, notetype, tag_root) in LEGACY.items():
            mp.setitem(languages.REGISTRY, old, dataclasses.replace(languages.get(code), code=old, notetype=notetype, tag_root=tag_root))
        for code, (old, _, _) in LEGACY.items():
            out[code] = build.build_package(old, list(old_by_id.values()), old_by_id, root, EPOCH_V1).path
    assert sorted(p.name for p in out.values()) == ["COTW-DE.apkg", "COTW-EN.apkg"]
    return out


def _review(col, spec, n: int) -> None:
    """Answer the first ``n`` new cards of the language's main deck: real review history."""
    col.decks.select(col.decks.id_for_name(spec.deck))
    for _ in range(n):
        card = col.sched.getCard()
        assert card is not None
        col.sched.answerCard(card, 3)


def _tag_roots(col) -> set[str]:
    return {t.split("::", 1)[0] for t in col.tags.all() if t.startswith("COTW-")}


def _filtered_deck(col, name: str, search: str) -> int:
    deck = col.sched.get_or_create_filtered_deck(deck_id=0)
    deck.name = name
    del deck.config.search_terms[1:]  # no second filter
    deck.config.search_terms[0].search = search
    deck.config.search_terms[0].limit = 1000
    return col.sched.add_or_update_filtered_deck(deck).id


def test_upgrade_from_the_packages_before_the_locale_codes(col, legacy, releases):
    for code in LEGACY:
        log = _import(col, legacy[code])
        assert len(log.new) == 248
    old_names = {old_nt: languages.get(code).notetype_id for code, (_, old_nt, _) in LEGACY.items()}
    assert {name: nt["id"] for name, nt in _cotw_notetypes(col).items()} == old_names
    assert _tag_roots(col) == {root for _, _, root in LEGACY.values()}
    for spec in (EN, DE):
        _review(col, spec, 5)
    # A filtered deck on the old tag root, built before the upgrade.
    europe = _filtered_deck(col, "Europe", f'"tag:{LEGACY[EN.code][2]}::Europe::*"')
    in_europe = set(col.find_cards(f"did:{europe}"))
    assert len(in_europe) > 100
    notes = {n: col.get_note(n).guid for n in col.find_notes("")}
    cards = {c: (card.ivl, card.due, card.type, card.queue) for c in col.find_cards("") for card in [col.get_card(c)]}
    revlog = col.db.all("SELECT id, cid, ease, ivl, type FROM revlog ORDER BY id")
    assert len(revlog) == 10

    # A later release of the locale packages (the release after the rename is always newer).
    for code in LEGACY:
        log = _import(col, releases["v2"][code])
        assert not log.new and not log.conflicting and len(log.updated) == 248, code

    # Same notes (GUIDs and note ids), same cards with their scheduling, the history kept.
    assert {n: col.get_note(n).guid for n in col.find_notes("")} == notes
    assert {c: (card.ivl, card.due, card.type, card.queue) for c in col.find_cards("") for card in [col.get_card(c)]} == cards
    assert col.db.all("SELECT id, cid, ease, ivl, type FROM revlog ORDER BY id") == revlog
    # Locales first published after the legacy packages install as their own notes.
    for code in languages.LANGUAGES:
        if code in LEGACY:
            continue
        log = _import(col, releases["v2"][code])
        assert len(log.new) == 248 and not log.conflicting, code
    # No second note type: the same IDs, now under the new names.
    _assert_consistent(col)
    assert {name: nt["id"] for name, nt in _cotw_notetypes(col).items()} == {
        languages.get(code).notetype: languages.get(code).notetype_id for code in languages.LANGUAGES
    }
    # Observed tag behaviour (docs/DECK.md, Tags): the import replaces a note's tags with the
    # package's. The old roots tag no note any more, their names stay in the tag list (unused)
    # until Check Database or "Clear Unused Tags".
    for code, (_, _, old_root) in LEGACY.items():
        spec = languages.get(code)
        assert col.find_notes(f'"tag:{old_root}::*"') == []
        assert len(col.find_notes(f'"tag:{spec.tag_root}::*"')) == 248
        assert all(t.startswith(spec.tag_root + "::") for n in col.find_notes(f'"note:{spec.notetype}"') for t in col.get_note(n).tags)
    current_roots = {languages.get(code).tag_root for code in languages.LANGUAGES}
    assert _tag_roots(col) == {root for _, _, root in LEGACY.values()} | current_roots
    col.tags.clear_unused_tags()
    assert _tag_roots(col) == current_roots
    # The filtered deck keeps its cards until it is rebuilt; then its old search finds nothing,
    # and the new root finds the same cards again.
    assert set(col.find_cards(f"did:{europe}")) == in_europe
    assert col.sched.rebuild_filtered_deck(europe).count == 0
    deck = col.sched.get_or_create_filtered_deck(deck_id=europe)
    deck.config.search_terms[0].search = f'"tag:{EN.tag_root}::Europe::*"'
    col.sched.add_or_update_filtered_deck(deck)
    assert set(col.find_cards(f"did:{europe}")) == in_europe
    assert col.db.all("SELECT id, cid, ease, ivl, type FROM revlog ORDER BY id") == revlog
