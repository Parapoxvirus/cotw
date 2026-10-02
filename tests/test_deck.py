"""The deck build (roadmap step 4): package content, identities, templates. No Anki needed."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("genanki")

from cotw.deck import build, lang, templates  # noqa: E402

EPOCH = 1_760_000_000
RECOMMENDED = {"country-capital", "country-flag", "capital-country", "flag-country", "map-country"}


@pytest.fixture(scope="session")
def packages(tmp_path_factory) -> dict[str, build.Built]:
    out = tmp_path_factory.mktemp("deck")
    return {b.lang: b for b in build.build(["en", "de"], out, epoch=EPOCH)}


def _collection(pkg: build.Built, tmp_path: Path) -> sqlite3.Connection:
    with zipfile.ZipFile(pkg.path) as z:
        target = tmp_path / f"{pkg.lang}.anki2"
        target.write_bytes(z.read("collection.anki2"))
    return sqlite3.connect(target)


@pytest.fixture(scope="session")
def collections(packages, tmp_path_factory) -> dict[str, sqlite3.Connection]:
    tmp = tmp_path_factory.mktemp("col")
    return {k: _collection(p, tmp) for k, p in packages.items()}


def _media(pkg: build.Built) -> dict[str, bytes]:
    with zipfile.ZipFile(pkg.path) as z:
        index = json.loads(z.read("media"))
        return {name: z.read(i) for i, name in index.items()}


def _notetype(col: sqlite3.Connection) -> dict:
    (models,) = col.execute("SELECT models FROM col").fetchone()
    (nt,) = json.loads(models).values()
    return nt


# --- identities -----------------------------------------------------------------------------------


def test_ids_are_frozen_and_distinct():
    ids = []
    for code, spec in lang.LANGS.items():
        for kind, key in (("notetype", "notetype_id"), ("deck", "deck_id"), ("deck-extras", "extras_deck_id")):
            digest = hashlib.sha256(f"cotw:{code}:{kind}".encode()).digest()[:4]
            assert spec[key] == (int.from_bytes(digest, "big") >> 1) | 1 << 30, (code, kind)
            ids.append(spec[key])
    assert len(set(ids)) == len(ids)


def test_names_differ_per_language():
    en, de = lang.LANGS["en"], lang.LANGS["de"]
    for key in ("notetype", "deck", "extras", "tag_root"):
        assert en[key] != de[key], key
    assert not set(en["templates"].values()) & set(de["templates"].values())
    assert en["extras"].startswith(en["deck"] + "::") and de["extras"].startswith(de["deck"] + "::")


def test_guids_are_stable_and_differ_per_language():
    # Pinned: a changed derivation would duplicate every note in every collection.
    assert build.guid("217", "en") == "C,F0URhk8F"
    assert build.guid("217", "de") == "B+v1yB?A&S"


def test_guids_in_packages(collections, by_id):
    guids = {}
    for code, col in collections.items():
        guids[code] = {g for (g,) in col.execute("SELECT guid FROM notes")}
        assert guids[code] == {build.guid(cid, code) for cid in by_id}
    assert not guids["en"] & guids["de"]


def test_build_is_reproducible(packages, tmp_path):
    again = build.build(["en"], tmp_path, epoch=EPOCH)[0]
    assert again.path.read_bytes() == packages["en"].path.read_bytes()


# --- content ----------------------------------------------------------------------------------------


def test_counts(packages, by_id):
    without_borders = sum(1 for e in by_id.values() if not e["borders"])
    for pkg in packages.values():
        assert pkg.notes == 248
        assert pkg.cards == 248 * 10 - 2 * without_borders


def test_required_fields_filled(collections):
    required = ("country", "capital_1", "iso2", "iso3", "flag", "map_1", "map_2", "locator", "wikipedia")
    for code, col in collections.items():
        names = [f["name"] for f in _notetype(col)["flds"]]
        assert names == [lang.LANGS[code]["fields"][k] for k in lang.FIELD_KEYS]
        for (flds,) in col.execute("SELECT flds FROM notes"):
            values = dict(zip(lang.FIELD_KEYS, flds.split("\x1f")))
            for key in required:
                assert values[key].strip(), (code, values["country"], key)


def test_every_media_reference_is_shipped(collections, packages):
    ref = re.compile(r'(?:src|href)="([^":]+?)"|url\("([^"]+)"\)')
    for code, col in collections.items():
        shipped = set(_media(packages[code]))
        nt = _notetype(col)
        texts = [nt["css"]] + [t[k] for t in nt["tmpls"] for k in ("qfmt", "afmt")]
        texts += [flds for (flds,) in col.execute("SELECT flds FROM notes")]
        referenced = {a or b for t in texts for a, b in ref.findall(t)} - {""}
        referenced = {r for r in referenced if not r.startswith("{{")}
        assert referenced - shipped == set(), code
        # Everything shipped is used, except the license texts that travel with the font and icons.
        assert shipped - referenced == {build.assets()["font-license"][0], build.assets()["icons-license"][0]}, code


def test_both_packages_ship_identical_media(packages):
    en, de = _media(packages["en"]), _media(packages["de"])
    assert en.keys() == de.keys()
    assert all(en[k] == de[k] for k in en)
    assert len(en) == 248 * 5 + len(build.ASSET_SOURCES)  # flag + 2 maps × day/night


def test_template_assets_carry_a_content_hash(tmp_path):
    names = build.assets()
    for key, (name, path) in names.items():
        assert re.fullmatch(r"_cotw-[\w-]+-[0-9a-f]{8}\.\w+", name), name
        assert hashlib.sha256(path.read_bytes()).hexdigest()[:8] in name
    changed = tmp_path / "_cotw-globe.js"
    changed.write_bytes(build.ASSET_SOURCES["globe"].read_bytes() + b"\n")
    assert build.asset_name("globe", changed) != names["globe"][0]


def test_field_media_keeps_its_name(collections):
    for (flds,) in collections["en"].execute("SELECT flds FROM notes"):
        for src in re.findall(r'src="([^"]+)"', flds):
            assert re.fullmatch(r"cotw-\d{3}-(flag|map[12]-(day|night))\.svg", src)


def test_recommended_and_extras_split(collections):
    keys = [c["key"] for c in lang.CARD_TYPES]
    assert {c["key"] for c in lang.CARD_TYPES if not c["extra"]} == RECOMMENDED
    for code, col in collections.items():
        spec = lang.LANGS[code]
        for ord_, did in col.execute("SELECT DISTINCT ord, did FROM cards"):
            expected = spec["deck_id"] if keys[ord_] in RECOMMENDED else spec["extras_deck_id"]
            assert did == expected, (code, keys[ord_])
        decks = json.loads(col.execute("SELECT decks FROM col").fetchone()[0])
        names = {d["name"] for d in decks.values()}
        assert {spec["deck"], spec["extras"]} <= names


def test_sort_field_is_the_country(collections):
    for col in collections.values():
        assert _notetype(col)["sortf"] == 0
        sfld = {s for (s,) in col.execute("SELECT sfld FROM notes")}
        assert "Switzerland" in sfld or "Schweiz" in sfld


def test_tags_per_language(collections):
    for code, col in collections.items():
        root = lang.LANGS[code]["tag_root"] + "::"
        for (t,) in col.execute("SELECT tags FROM notes"):
            assert t.split() and all(tag.startswith(root) for tag in t.split()), t
    de = {tag for (t,) in collections["de"].execute("SELECT tags FROM notes") for tag in t.split()}
    assert "COTW-DE::Europa::Westeuropa" in de
    assert "COTW-DE::Afrika::Subsahara-Afrika::Südliches-Afrika" in de
    assert "COTW-DE::Status::Abhängiges-Gebiet" in de


def test_regions_have_german_names(taxonomy):
    assert {name for path in taxonomy for name in path} <= lang.REGIONS_DE.keys()


def test_german_texts_use_real_umlauts(collections, by_id):
    col = collections["de"]
    blob = " ".join(flds for (flds,) in col.execute("SELECT flds FROM notes"))
    blob += json.dumps(json.loads(col.execute("SELECT decks FROM col").fetchone()[0]), ensure_ascii=False)
    blob += json.dumps(_notetype(col), ensure_ascii=False)
    for word in ("Länder der Welt", "Österreich", "Südafrika", "Nachbarländer", "Grönland", "abhängiges Gebiet"):
        assert word in blob, word
    for bad in ("Laender", "Oesterreich", "Suedafrika", "Nachbarlaender", "Groenland", "abhaengig"):
        assert bad not in blob, bad


def test_dependency_and_status_texts(by_id):
    parents = {by_id[e["dependency_of"]]["name"]["de"] for e in by_id.values() if e.get("dependency_of")}
    # A new parent needs a decision on its German object form (lang.DATIVE_DE).
    assert parents == {
        "Australien", "China", "Dänemark", "Finnland", "Frankreich", "Neuseeland", "Niederlande",
        "Norwegen", "Vereinigte Staaten", "Vereinigtes Königreich",
    }
    gl = build.fields(by_id["087"], by_id, "en")
    assert (gl["dependency_of"], gl["status"]) == ("Denmark", "")
    assert build.fields(by_id["001"], by_id, "de")["dependency_of"] == ""
    uk_dep = next(e for e in by_id.values() if e.get("dependency_of") == "235")
    assert build.fields(uk_dep, by_id, "en")["dependency_of"] == "the United Kingdom"
    assert build.fields(uk_dep, by_id, "de")["dependency_of"] == "dem Vereinigten Königreich"
    xk = build.fields(by_id["118"], by_id, "de")
    assert (xk["status"], xk["dependency_of"]) == ("Status umstritten", "")


def test_german_wikipedia_with_english_fallback(by_id):
    assert build.fields(by_id["217"], by_id, "de")["wikipedia"] == "https://de.wikipedia.org/wiki/Schweiz"
    assert build.fields(by_id["217"], by_id, "en")["wikipedia"] == "https://en.wikipedia.org/wiki/Switzerland"
    assert build.fields(by_id["215"], by_id, "de")["wikipedia"].startswith("https://en.wikipedia.org/")


def test_borders_list_neighbor_names_with_flags(by_id):
    de = build.fields(by_id["217"], by_id, "de")["borders"]
    names = re.findall(r"<img[^>]*>([^<]+)</span>", de)
    assert names == ["Deutschland", "Frankreich", "Italien", "Liechtenstein", "Österreich"]
    assert 'src="cotw-014-flag.svg"' in de


# --- templates --------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rendered(by_id):
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    out = {}
    for code in lang.LANGS:
        tmpls = templates.templates(code, names, config)
        for cid, e in by_id.items():
            values = build.card_fields(e, by_id, code)
            for card, t in zip(lang.CARD_TYPES, tmpls):
                out[code, cid, card["key"]] = (
                    templates.render(t["qfmt"], values),
                    templates.render(t["afmt"], values),
                )
    return out


def test_all_templates_render(rendered, by_id):
    for (code, cid, key), (front, back) in rendered.items():
        if "borders" in key and not by_id[cid]["borders"]:
            assert front.strip() == "", (code, cid, key)  # no card
        else:
            assert front.strip() and back.strip(), (code, cid, key)


def _visible_text(html: str) -> str:
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_map_front_has_no_text(rendered, by_id):
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    for (code, cid, key), (front, _back) in rendered.items():
        if key != "map-country":
            continue
        spec = lang.LANGS[code]
        # The help box sits indented inside the card root: compare with whitespace collapsed.
        help_box, flat = " ".join(templates._help(spec, names, config).split()), " ".join(front.split())
        assert help_box in flat
        prompt = flat.replace(help_box, "")
        assert _visible_text(prompt) == f"? {spec['ui']['help']}", (code, cid)
        assert "data-tooltip" not in front
        assert "wikipedia.org" not in front
        e = by_id[cid]
        values = build.fields(e, by_id, code)
        for leak in (e["iso2"], e["iso3"], values["country"], values["formal_name"], values["capital_1"]):
            if leak:
                assert leak not in _visible_text(prompt), (code, cid, leak)
        assert f'data-id="{cid}"' in front  # the globe is there, just silent


def test_globe_on_every_back_with_tooltip(rendered):
    for (code, cid, key), (front, back) in rendered.items():
        if not front.strip():
            continue
        assert back.count('class="cotw-globe"') == 1, (code, cid, key)
        assert f'data-id="{cid}" data-lang="{code}" data-tooltip' in back
        assert ('class="cotw-globe"' in front) == (key == "map-country")


def test_deferred_packets_are_referenced_without_eager_execution(rendered):
    names = {key: name for key, (name, _) in build.assets().items()}
    parts = " ".join(f'data-{part}-src="{names["globe-" + part]}"' for part in ("zones", "detail"))
    for front, back in rendered.values():
        for html in (front, back):
            if 'class="cotw-globe"' not in html:
                continue
            assert f'<script src="{names["globe"]}" {parts}>' in html
            for part in ("zones", "detail"):
                assert f'<script src="{names["globe-" + part]}"' not in html
                # The card element also carries the filename for reviewers without currentScript.
                assert html.count(f'data-{part}-src="{names["globe-" + part]}"') == 2
            assert "overview" not in html, "L2 is in the bootstrap since #31: no overview packet"


def test_each_package_speaks_its_language(rendered):
    en_only = ("Show full info", "Help", "Symbols", "Bordering countries")
    de_only = ("Alle Infos anzeigen", "Hilfe", "Symbole", "Nachbarländer (nur Landgrenzen)")
    for (code, cid, key), (front, back) in rendered.items():
        if cid != "217":
            continue
        text = front + back
        for word in en_only:
            assert (word in text) == (code == "en") or key == "map-country" and word == "Show full info", (code, key, word)
        for word in de_only:
            assert (word in text) == (code == "de"), (code, key, word)


def test_templates_are_readable():
    """Anki's template editor shows the source: one block element per line, indented by nesting."""
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    blocks = ('<div class="cotw-box', '<div class="cotw-row', '<div class="cotw-icon', '<div class="cotw-content')
    for code in lang.LANGS:
        for t in templates.templates(code, names, config):
            for side in ("qfmt", "afmt"):
                lines = t[side].split("\n")
                assert len(lines) > 100, (code, t["name"], side)
                assert any(line.strip().startswith("<!-- ") for line in lines), (code, t["name"], side)
                for line in lines:
                    indent = len(line) - len(line.lstrip(" "))
                    assert "\t" not in line and indent % 2 == 0, (code, t["name"], side, line)
                    assert sum(line.count(b) for b in blocks) <= 1, (code, t["name"], side, line)
                    assert len(line) <= 240, (code, t["name"], side, line)
                opened = []  # every multi-line div closes at the indentation it opened at
                for line in lines:
                    s, indent = line.strip(), len(line) - len(line.lstrip(" "))
                    if s.startswith("<div") and not s.endswith("</div>"):
                        opened.append(indent)
                    elif s == "</div>":
                        assert opened and opened.pop() == indent, (code, t["name"], side, line)
                assert not opened, (code, t["name"], side)


def test_buttons_without_timers_or_ids(packages, collections):
    for col in collections.values():
        for t in _notetype(col)["tmpls"]:
            for side in ("qfmt", "afmt"):
                assert "setTimeout" not in t[side]
                assert " id=" not in t[side]
                assert "onclick=\"this.closest('.cotw')" in t[side]


def test_ankiweb_links_come_from_the_config(rendered):
    config = build.load_config()
    front, _ = rendered["de", "217", "country-capital"]
    assert config["ankiweb"]["de"] in front and config["ankiweb"]["en"] not in front
    assert "mailto:info@feldbuch.com" in front


def test_ui_icons_have_the_text_color_of_their_mode():
    text = {"day": "#1F2328", "night": "#E6EDF3"}
    icons = [k for k in build.ASSET_SOURCES if k.startswith("icon-")]
    assert len(icons) == 9 * 2
    for key in icons:
        mode = key.rsplit("-", 1)[1]
        fills = re.findall(r'fill="(#[0-9a-fA-F]{6})"', build.ASSET_SOURCES[key].read_text(encoding="utf-8"))
        assert fills == [text[mode]], key


# --- night mode: Anki's class only (issue #12) -------------------------------------------------------


def test_no_system_color_scheme_anywhere():
    """Anki's .nightMode decides, not the OS: with Anki light and the OS dark the cards stayed
    dark. Neither the card CSS, the globe, nor any map may follow prefers-color-scheme."""
    names = {k: n for k, (n, _) in build.assets().items()}
    assert "prefers-color-scheme" not in build.css(names)
    assert "prefers-color-scheme" not in build.ASSET_SOURCES["globe"].read_text(encoding="utf-8")
    from cotw.paths import ROOT

    assert "prefers-color-scheme" not in (ROOT / "tools" / "globe" / "globe.js").read_text(encoding="utf-8")


def test_css_switches_day_and_night_images_by_anki_class():
    css = re.sub(r"/\*.*?\*/", "", build.css({k: n for k, (n, _) in build.assets().items()}), flags=re.S)
    rules = {sel.strip(): body for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)}
    assert "display: none" in rules[".cotw img.cotw-night"]
    assert "display: none" in rules[".nightMode .cotw img.cotw-day, .night_mode .cotw img.cotw-day"]
    assert "display: block" in rules[".nightMode .cotw img.cotw-night, .night_mode .cotw img.cotw-night"]
    # Last in the file: an img rule of the same weight declared earlier cannot override them.
    last = list(rules)[-3:]
    assert last[0] == ".cotw img.cotw-night"
    # Text colors per mode.
    assert "color: #1F2328" in rules[".card"] and "color: #E6EDF3" in rules[
        ".card.nightMode, .nightMode .card, .card.night_mode, .night_mode .card"
    ]
    assert "#2C2C2C" in rules[".card.nightMode, .nightMode .card, .card.night_mode, .night_mode .card"]
    assert "--cotw-label: #59636E" in rules[".cotw"]


def test_both_map_files_are_in_the_field(by_id):
    for cid, e in by_id.items():
        values = build.fields(e, by_id, "en")
        for key, kind in (("map_1", "map1"), ("map_2", "map2")):
            assert values[key] == (
                f'<img class="cotw-day" src="cotw-{cid}-{kind}-day.svg">'
                f'<img class="cotw-night" src="cotw-{cid}-{kind}-night.svg">'
            ), (cid, key)
        assert values["flag"] == f'<img src="cotw-{cid}-flag.svg">'  # flags stay one file


def test_icons_and_infographics_exist_once_per_mode(rendered):
    names = {k: n for k, (n, _) in build.assets().items()}
    front, back = rendered["en", "217", "country-capital"]
    for key in ("infographic", "infographic-filtered"):
        for mode in ("day", "night"):
            assert f'<img class="cotw-infographic cotw-{mode}" src="{names[f"{key}-{mode}"]}">' in front
    icon = f'<img class="cotw-day" src="{names["icon-capital-day"]}">\n'
    assert re.search(re.escape(icon) + rf' *<img class="cotw-night" src="{re.escape(names["icon-capital-night"])}">', back)
    assert not any(n.endswith(".png") for n in names.values()), "the v3 PNGs left the package"


def test_deck_description_attributions(collections):
    for code, col in collections.items():
        decks = json.loads(col.execute("SELECT decks FROM col").fetchone()[0])
        desc = next(d["desc"] for d in decks.values() if d["name"] == lang.LANGS[code]["deck"])
        for needle in ("Marine Regions", "10.14284/632", "10.14284/633", "CC BY 4.0", "Natural Earth",
                       "Wikimedia Commons", "IBM Plex Sans", "Open Font License", "CC0", "Wikidata",
                       "Phosphor Icons"):
            assert needle in desc, (code, needle)


def test_phosphor_mit_notice_ships_in_full(collections, packages):
    """MIT requires the copyright and permission notice to travel with the icons: the full text
    ships in every package as a ``_``-prefixed file (kept by Anki's Check Media, like the OFL
    text) and the deck description names it."""
    name, source = build.assets()["icons-license"]
    assert name.startswith("_cotw-ui-") and name.endswith(".txt")
    assert source.parent == build.UI  # next to the Phosphor sources in the repo
    for code, pkg in packages.items():
        text = _media(pkg)[name].decode("utf-8")
        assert "Copyright (c) 2023 Phosphor Icons" in text
        assert "Permission is hereby granted, free of charge" in text
        assert "The above copyright notice and this permission notice shall be included" in text
        assert 'THE SOFTWARE IS PROVIDED "AS IS"' in text
        decks = json.loads(collections[code].execute("SELECT decks FROM col").fetchone()[0])
        desc = next(d["desc"] for d in decks.values() if d["name"] == lang.LANGS[code]["deck"])
        assert name in desc and "Copyright (c) 2023 Phosphor Icons" in desc, code


def test_renderer():
    r = templates.render
    assert r("{{#A}}x{{B}}{{/A}}", {"A": "1", "B": "y"}) == "xy"
    assert r("{{#A}}x{{/A}}{{^A}}z{{/A}}", {"A": " "}) == "z"
    assert r("{{#A}}{{#A}}in{{/A}}{{/A}}", {"A": "1"}) == "in"
    with pytest.raises(KeyError):
        r("{{Nope}}", {})
    with pytest.raises(ValueError):
        r("{{#A}}x", {"A": "1"})


# --- subset build (--only) ------------------------------------------------------------------------


def test_select_by_id_or_iso2(by_id):
    picked = build.select(by_id, ["RU,kr", "207 CH", "217"])
    assert [e["id"] for e in picked] == sorted({"184", "207", "209", "217"})
    with pytest.raises(ValueError, match="XX"):
        build.select(by_id, ["RU", "XX"])
    with pytest.raises(ValueError):
        build.select(by_id, [" , "])


@pytest.fixture(scope="session")
def subset(tmp_path_factory) -> dict[str, build.Built]:
    out = tmp_path_factory.mktemp("subset")
    only = ["RU,KR,ZA,CW,CH,VA,SJ,KI,BO,ID"]
    return {b.lang: b for b in build.build(["en", "de"], out, epoch=EPOCH, only=only)}


def test_subset_keeps_ids_guids_and_neighbors(subset, packages, by_id, tmp_path):
    for code, pkg in subset.items():
        assert pkg.notes == 10
        for d in ("s", "f"):
            (tmp_path / d).mkdir(exist_ok=True)
        sub = _collection(pkg, tmp_path / "s")
        full = _collection(packages[code], tmp_path / "f")
        # Same note type, decks, GUIDs and field content as the full build.
        assert _notetype(sub)["id"] == _notetype(full)["id"]
        rows = dict(sub.execute("SELECT guid, flds FROM notes"))
        full_rows = dict(full.execute("SELECT guid, flds FROM notes"))
        assert rows and all(full_rows[g] == f for g, f in rows.items())
        decks = {d["name"]: d["id"] for d in json.loads(sub.execute("SELECT decks FROM col").fetchone()[0]).values()}
        assert decks[lang.LANGS[code]["deck"]] == lang.LANGS[code]["deck_id"]
        # Switzerland's borders still name and flag its neighbors, none of them in the subset.
        ch = next(f for f in rows.values() if f.startswith(("Switzerland", "Schweiz")))
        assert "cotw-014-flag.svg" in ch  # Austria: not in the subset, still listed
        # Every referenced file is shipped; the globe is the whole world.
        shipped = set(_media(pkg))
        refs = {r for f in rows.values() for r in re.findall(r'src="([^"]+)"', f)}
        assert refs <= shipped
        for key in build.GLOBE_ASSETS:
            assert build.assets()[key][0] in shipped
            assert _media(pkg)[build.assets()[key][0]] == build.ASSET_SOURCES[key].read_bytes()


def test_help_explains_the_maritime_zones():
    """Issue #22: the help says what the light-blue area and the light line in the sea mean."""
    from cotw.deck import lang

    en, de = (" ".join(lang.LANGS[code]["help"].split()) for code in ("en", "de"))
    assert "exclusive economic zone" in en and "200 nautical" in en and "12 nautical miles" in en
    assert "The globe shows only the economic zone." in en
    assert "Wirtschaftszone" in de and "200 Seemeilen" in de and "Hoheitsgewässer" in de
    assert "Der Globus zeigt nur die Wirtschaftszone." in de
    # The EEZ paragraph follows the maps/globe paragraph.
    assert en.index("Map 1 shows") < en.index("light-blue area") < en.index("More about the deck")
    assert de.index("Karte 1 zeigt") < de.index("hellblaue Fläche") < de.index("Mehr zum Deck")
    assert "ß" not in de


def test_help_is_split_into_chapters():
    """The help has bold inline chapter headings, in this order; small islands are explained."""
    from cotw.deck import lang

    chapters = {
        "en": ("Card types:", "Maps and globe:", "Territorial waters and economic zones:", "Small islands:",
               "Help and contact:"),
        "de": ("Kartentypen:", "Karten und Globus:", "Hoheitsgewässer und Wirtschaftszonen:", "Kleine Inseln:",
               "Hilfe und Kontakt:"),
    }
    for code, heads in chapters.items():
        text = " ".join(lang.LANGS[code]["help"].split())
        pos = [text.index(f"<p><b>{h}</b> ") for h in heads]
        assert pos == sorted(pos), code
    en, de = (" ".join(lang.LANGS[code]["help"].split()) for code in ("en", "de"))
    assert "economic zones and territorial waters are complete" in en and "disputed islands" in en
    assert "Wirtschaftszonen und Hoheitsgewässer sind aber vollständig" in de and "umstrittene Inseln" in de


def test_german_texts_address_the_learner_as_du():
    """Deck descriptions and help speak to the learner directly, never impersonally."""
    from cotw.deck import build, lang

    for text in (build.DESCRIPTION["de"], build.EXTRAS_DESCRIPTION["de"], lang.LANGS["de"]["help"]):
        flat = " ".join(text.split())
        assert not re.search(r"\b(Wer|man)\b", flat), flat
        assert "ß" not in flat
