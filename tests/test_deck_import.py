"""Coexistence proof: both packages imported into a real Anki collection (the ``anki`` package).

EN and DE must install side by side in any order, and each must be updatable on its own
(docs/DECK.md). The version-skew case is simulated: a later EN build with a changed field
medium (a map), a changed template asset (the globe) and a changed capital, imported while
the older DE package stays installed.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
from pathlib import Path

import pytest

pytest.importorskip("genanki")
anki_collection = pytest.importorskip("anki.collection")

from anki.import_export_pb2 import ImportAnkiPackageOptions  # noqa: E402

from cotw.deck import build, lang  # noqa: E402
from cotw.paths import MEDIA  # noqa: E402

EPOCH_V1 = 1_760_000_000
EPOCH_V2 = EPOCH_V1 + 86_400 * 365  # a year later
CHANGED_MAP = "cotw-217-map1-day.svg"


@pytest.fixture(scope="module")
def releases(tmp_path_factory) -> dict[str, dict[str, Path]]:
    root = tmp_path_factory.mktemp("releases")
    entries, by_id = build.load_entries()
    v1 = {b.lang: b.path for b in (build.build_package(c, entries, by_id, root / "v1", EPOCH_V1) for c in ("en", "de"))}

    media = root / "media-v2"
    shutil.copytree(MEDIA, media)
    (media / CHANGED_MAP).write_text(
        (media / CHANGED_MAP).read_text(encoding="utf-8").replace("</svg>", "<!-- v2 --></svg>"), encoding="utf-8"
    )
    for key in build.GLOBE_ASSETS:
        name = build.ASSET_SOURCES[key].name
        (media / name).write_text((media / name).read_text(encoding="utf-8") + "\n// v2\n", encoding="utf-8")
    by_id2 = copy.deepcopy(by_id)
    by_id2["217"]["capitals"][0]["name"] = {"en": "Bern (v2)", "de": "Bern (v2)"}
    v2 = {
        c: build.build_package(c, list(by_id2.values()), by_id2, root / "v2", EPOCH_V2, media_dir=media).path
        for c in ("en", "de")
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
    """Two note types, the expected decks, no duplicates, every referenced file present."""
    nts = _cotw_notetypes(col)
    assert set(nts) == {"COTW (EN)", "COTW (DE)"}
    assert {nts["COTW (EN)"]["id"], nts["COTW (DE)"]["id"]} == {
        lang.LANGS["en"]["notetype_id"],
        lang.LANGS["de"]["notetype_id"],
    }
    decks = {d.name for d in col.decks.all_names_and_ids()}
    for code in ("en", "de"):
        assert {lang.LANGS[code]["deck"], lang.LANGS[code]["extras"]} <= decks
        nids = col.find_notes(f'"note:{lang.LANGS[code]["notetype"]}"')
        assert len(nids) == 248
        assert len({col.get_note(n).guid for n in nids}) == 248
        country = lang.LANGS[code]["fields"]["country"]
        assert len({col.get_note(n)[country] for n in nids}) == 248
    assert col.note_count() == 2 * 248
    media_dir = Path(col.media.dir())
    for nt in nts.values():
        missing = {a for a in _template_assets(nt) if not (media_dir / a).exists()}
        assert not missing, (nt["name"], missing)
    check = col.media.check()
    assert list(check.missing) == []


@pytest.mark.parametrize("order", [("en", "de"), ("de", "en")])
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
        deck = col.decks.id_for_name(lang.LANGS[code]["deck"])
        extras = col.decks.id_for_name(lang.LANGS[code]["extras"])
        in_main = col.find_cards(f'"deck:{lang.LANGS[code]["deck"]}" -"deck:{lang.LANGS[code]["extras"]}"')
        in_extras = col.find_cards(f'"deck:{lang.LANGS[code]["extras"]}"')
        assert len(in_main) == 5 * 248 and deck and extras
        assert {col.get_card(c).ord for c in in_extras} == {i for i, c in enumerate(lang.CARD_TYPES) if c["extra"]}


def test_reimport_changes_nothing(col, releases):
    for code in ("en", "de", "en", "de"):
        _import(col, releases["v1"][code])
    _assert_consistent(col)
    assert len(os.listdir(col.media.dir())) == 248 * 5 + len(build.ASSET_SOURCES)


def test_updating_one_language_leaves_the_other_intact(col, releases):
    _import(col, releases["v1"]["en"])
    _import(col, releases["v1"]["de"])
    media_dir = Path(col.media.dir())
    old_map = (media_dir / CHANGED_MAP).read_bytes()
    old_de_assets = _template_assets(_cotw_notetypes(col)["COTW (DE)"])

    log = _import(col, releases["v2"]["en"])
    assert len(log.updated) == 248 and not log.new
    _assert_consistent(col)
    nts = _cotw_notetypes(col)

    # EN moved on: new capital, new globe, its map under a new name with the new content.
    ch_en = col.get_note(col.find_notes('"note:COTW (EN)" "Country:Switzerland"')[0])
    assert ch_en["Capital 1"] == "Bern (v2)"
    new_src = re.search(r'src="([^"]+)"', ch_en["Map 1"]).group(1)
    assert new_src != CHANGED_MAP and b"v2" in (media_dir / new_src).read_bytes()
    en_globe = {a for a in _template_assets(nts["COTW (EN)"]) if a.startswith("_cotw-globe-")}
    assert en_globe and not en_globe & old_de_assets
    assert len(en_globe) == 3  # bootstrap and its matching deferred packets coexist independently

    # DE is untouched: old capital, old map bytes, old globe still there and referenced.
    ch_de = col.get_note(col.find_notes('"note:COTW (DE)" "Land:Schweiz"')[0])
    assert ch_de["Hauptstadt 1"] == "Bern"
    assert ch_de["Karte 1"] == build.map_field("217", "map1")  # both files, the old day map
    assert f'src="{CHANGED_MAP}"' in ch_de["Karte 1"]
    assert (media_dir / CHANGED_MAP).read_bytes() == old_map
    assert _template_assets(nts["COTW (DE)"]) == old_de_assets
    assert list(col.media.check().unused) == []

    # DE catches up later: both now share the one new map file; the old one is left over and
    # reported as unused by Check Media (a field medium, so Anki may clean it up).
    _import(col, releases["v2"]["de"])
    _assert_consistent(col)
    ch_de = col.get_note(col.find_notes('"note:COTW (DE)" "Land:Schweiz"')[0])
    assert re.search(r'src="([^"]+)"', ch_de["Karte 1"]).group(1) == new_src
    assert "cotw-217-map1-night.svg" in ch_de["Karte 1"]  # the unchanged night map keeps its name
    assert list(col.media.check().unused) == [CHANGED_MAP]
    assert _template_assets(_cotw_notetypes(col)["COTW (DE)"]) == _template_assets(_cotw_notetypes(col)["COTW (EN)"])
