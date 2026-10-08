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

from cotw import languages  # noqa: E402
from cotw.deck import build, lang, templates  # noqa: E402

EPOCH = 1_760_000_000
RECOMMENDED = {"country-capital", "country-flag", "capital-country", "flag-country", "map-country"}


@pytest.fixture(scope="session")
def packages(tmp_path_factory) -> dict[str, build.Built]:
    out = tmp_path_factory.mktemp("deck")
    return {b.lang: b for b in build.build(list(languages.LANGUAGES), out, epoch=EPOCH)}


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


# Derivation and uniqueness of the IDs and names of every language: tests/test_languages.py.


def test_published_identities_match_golden_fixture(collections):
    """The identity fixture is append-only: append new entries, never change existing rows.

    Read every GUID and ID from the built .apkg collections, independently of the
    current GUID derivation. Locale refactors change only the identity lookup below.
    """
    fixture = json.loads((Path(__file__).parent / "fixtures" / "identities.json").read_text())
    hint = "Append new identities/entries to the fixture; never change or remove existing rows."
    observed = {}
    for code, col in collections.items():
        spec = languages.get(code)
        identity = spec.identity
        nt = _notetype(col)
        locator = [field["name"] for field in nt["flds"]].index(spec.fields["locator"])
        rows = col.execute("SELECT guid, flds FROM notes").fetchall()
        guids = {fields.split("\x1f")[locator]: guid for guid, fields in rows}
        assert len(guids) == len(rows), f"{identity}: duplicate COTW IDs in package"
        decks = {d["name"]: d["id"] for d in json.loads(col.execute("SELECT decks FROM col").fetchone()[0]).values()}
        observed[identity] = {
            "notetype_id": int(nt["id"]),
            "deck_id": decks[spec.deck],
            "extras_deck_id": decks[spec.extras],
            "id_offset": col.execute("SELECT min(id) FROM notes").fetchone()[0] - EPOCH * 1000,
            "note_guids": guids,
        }
        assert {mid for (mid,) in col.execute("SELECT DISTINCT mid FROM notes")} == {int(nt["id"])}, hint
        assert {did for (did,) in col.execute("SELECT DISTINCT did FROM cards")} == {
            decks[spec.deck], decks[spec.extras]
        }, hint
    assert len(observed) == len(collections), "Published identities must be unique"
    assert observed == fixture, hint


def test_package_ids_in_the_collection(collections):
    for code, col in collections.items():
        spec = languages.get(code)
        assert int(_notetype(col)["id"]) == spec.notetype_id, code
        assert {mid for (mid,) in col.execute("SELECT DISTINCT mid FROM notes")} == {spec.notetype_id}, code
        decks = {d["name"]: d["id"] for d in json.loads(col.execute("SELECT decks FROM col").fetchone()[0]).values()}
        assert decks[spec.deck] == spec.deck_id and decks[spec.extras] == spec.extras_deck_id, code
        (first,) = col.execute("SELECT min(id) FROM notes").fetchone()
        assert first == EPOCH * 1000 + spec.id_offset, code


def test_guids_are_stable_and_differ_per_language():
    # Pinned: a changed derivation would duplicate every note in every collection.
    assert build.guid("217", "en-US") == "C,F0URhk8F"
    assert build.guid("217", "de-CH") == "B+v1yB?A&S"
    assert build.guid("217", "pl-PL") == "r`Zh{w}T?!"


def test_renamed_entry_keeps_its_guid():
    """Renaming 153 (Nauru → Naoero) keeps the GUID: it hangs on the id alone, progress stays."""
    assert build.guid("153", "en-US") == "L1#_L{AY0a"
    assert build.guid("153", "de-CH") == "D5js<BPzmK"


def test_ham74_fields(by_id):
    for code in ("en-US", "de-CH"):
        gq = build.fields(by_id["067"], by_id, code)
        assert (gq["capital_1"], gq["capital_2"]) == ("Ciudad de la Paz", "Malabo")
        nr = build.fields(by_id["153"], by_id, code)
        assert nr["country"] == "Naoero"
    assert build.fields(by_id["067"], by_id, "de-CH")["capital_2_label"] == "Regierungssitz bis zum Abschluss des Umzugs"
    assert build.fields(by_id["153"], by_id, "de-CH")["formal_name"] == "Republik Naoero"
    assert build.fields(by_id["153"], by_id, "en-US")["wikipedia"] == "https://en.wikipedia.org/wiki/Nauru"


def test_shared_corrections_fields(by_id):
    """DE formal names from the official German lists, Eswatini's Lobamba as the
    legislature; Hong Kong and Macao keep their own administrative locations."""
    de = {cid: build.fields(by_id[cid], by_id, "de-CH") for cid in ("002", "070", "100", "130")}
    assert de["002"]["formal_name"] == "Ålandinseln"
    assert de["100"]["formal_name"] == "Sonderverwaltungsregion Hongkong der Volksrepublik China"
    assert de["130"]["formal_name"] == "Sonderverwaltungsregion Macau der Volksrepublik China"
    assert (de["100"]["capital_1"], de["130"]["capital_1"]) == ("Hongkong", "Macau")
    assert (de["070"]["capital_2"], de["070"]["capital_2_label"]) == ("Lobamba", "Legislative")
    en = build.fields(by_id["070"], by_id, "en-US")
    assert (en["capital_1_label"], en["capital_2_label"]) == ("capital", "legislative")


def test_portuguese_approved_names_and_shared_facts(by_id):
    """The adopted contributor data follows the settled pt-BR naming choices and translates
    the shared post-correction capital facts instead of restoring older classifications."""
    names = {cid: by_id[cid]["name"]["pt-BR"] for cid in ("050", "051", "093", "100", "130", "181")}
    assert names == {
        "050": "República Democrática do Congo / RDC",
        "051": "República do Congo",
        "093": "República da Guiné",
        "100": "Hong Kong",
        "130": "Macau",
        "181": "República da China (Taiwan)",
    }
    assert by_id["151"]["name"]["pt-BR"] == "Myanmar"
    assert by_id["098"]["name"]["pt-BR"] == "Vaticano"
    assert by_id["072"]["name"]["pt-BR"] == "Ilhas Malvinas"
    assert by_id["070"]["capitals"][1]["role"] == "legislative"
    assert by_id["070"]["capitals"][1]["label"]["pt-BR"] == "legislativa"


def test_formal_name_absent_in_one_locale_renders_no_row_and_no_fallback(by_id):
    """A locale without a sourced formal name shows no formal-name row; the other locale's
    formal name is never shown instead (docs/SCHEMA.md)."""
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    entry = dict(by_id["217"], formal_name={"en-US": by_id["217"]["formal_name"]["en-US"]})
    icon = "_cotw-ui-longform-day-"  # the formal-name row's icon
    for code in languages.LANGUAGES:
        values = build.card_fields(entry, by_id, code)
        back = templates.render(templates.templates(code, names, config)[0]["afmt"], values)
        info, sep, _help = back.partition('<div class="cotw-box cotw-help">')  # the help lists every icon
        assert sep
        if code == "en-US":
            assert "Swiss Confederation" in info and icon in info
        else:
            assert values[languages.get(code).fields["formal_name"]] == ""
            assert "Swiss Confederation" not in back and icon not in info, code


def test_guids_in_packages(collections, by_id):
    guids = {}
    for code, col in collections.items():
        guids[code] = {g for (g,) in col.execute("SELECT guid FROM notes")}
        assert guids[code] == {build.guid(cid, code) for cid in by_id}
    assert len(set().union(*guids.values())) == len(guids) * len(by_id)  # no GUID shared between languages


def test_build_is_reproducible(packages, tmp_path):
    again = build.build([languages.BASE], tmp_path, epoch=EPOCH)[0]
    assert again.path.read_bytes() == packages[languages.BASE].path.read_bytes()


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
        assert names == [languages.get(code).fields[k] for k in lang.FIELD_KEYS]
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


def test_all_packages_ship_identical_media(packages):
    base = _media(packages[languages.BASE])
    for code, pkg in packages.items():
        media = _media(pkg)
        assert media.keys() == base.keys(), code
        assert all(media[k] == base[k] for k in base), code
    assert len(base) == 248 * 5 + len(build.ASSET_SOURCES)  # flag + 2 maps × day/night


def test_template_assets_carry_a_content_hash(tmp_path):
    names = build.assets()
    for key, (name, path) in names.items():
        assert re.fullmatch(r"_cotw-[\w-]+-[0-9a-f]{8}\.\w+", name), name
        assert hashlib.sha256(path.read_bytes()).hexdigest()[:8] in name
    changed = tmp_path / "_cotw-globe.js"
    changed.write_bytes(build.ASSET_SOURCES["globe"].read_bytes() + b"\n")
    assert build.asset_name("globe", changed) != names["globe"][0]


def test_field_media_keeps_its_name(collections):
    for (flds,) in collections["en-US"].execute("SELECT flds FROM notes"):
        for src in re.findall(r'src="([^"]+)"', flds):
            assert re.fullmatch(r"cotw-\d{3}-(flag|map[12]-(day|night))\.svg", src)


def test_recommended_and_extras_split(collections):
    keys = [c["key"] for c in lang.CARD_TYPES]
    assert {c["key"] for c in lang.CARD_TYPES if not c["extra"]} == RECOMMENDED
    for code, col in collections.items():
        spec = languages.get(code)
        for ord_, did in col.execute("SELECT DISTINCT ord, did FROM cards"):
            expected = spec.deck_id if keys[ord_] in RECOMMENDED else spec.extras_deck_id
            assert did == expected, (code, keys[ord_])
        decks = json.loads(col.execute("SELECT decks FROM col").fetchone()[0])
        names = {d["name"] for d in decks.values()}
        assert {spec.deck, spec.extras} <= names


def test_sort_field_is_the_country(collections, by_id):
    for code, col in collections.items():
        assert _notetype(col)["sortf"] == 0
        sfld = {s for (s,) in col.execute("SELECT sfld FROM notes")}
        assert by_id["217"]["name"][code] in sfld, code
    assert "Switzerland" in {s for (s,) in collections["en-US"].execute("SELECT sfld FROM notes")}
    assert "Schweiz" in {s for (s,) in collections["de-CH"].execute("SELECT sfld FROM notes")}


def test_tags_per_language(collections):
    for code, col in collections.items():
        root = languages.get(code).tag_root + "::"
        for (t,) in col.execute("SELECT tags FROM notes"):
            assert t.split() and all(tag.startswith(root) for tag in t.split()), t
    de = {tag for (t,) in collections["de-CH"].execute("SELECT tags FROM notes") for tag in t.split()}
    assert "COTW-DE-CH::Europa::Westeuropa" in de
    assert "COTW-DE-CH::Afrika::Subsahara-Afrika::Südliches-Afrika" in de
    assert "COTW-DE-CH::Status::Abhängiges-Gebiet" in de


def test_german_texts_use_real_umlauts(collections, by_id):
    col = collections["de-CH"]
    blob = " ".join(flds for (flds,) in col.execute("SELECT flds FROM notes"))
    blob += json.dumps(json.loads(col.execute("SELECT decks FROM col").fetchone()[0]), ensure_ascii=False)
    blob += json.dumps(_notetype(col), ensure_ascii=False)
    for word in ("Länder der Welt", "Österreich", "Südafrika", "Nachbarländer", "Grönland", "abhängiges Gebiet"):
        assert word in blob, word
    for bad in ("Laender", "Oesterreich", "Suedafrika", "Nachbarlaender", "Groenland", "abhaengig"):
        assert bad not in blob, bad


def test_dependency_and_status_texts(by_id):
    gl = build.fields(by_id["087"], by_id, "en-US")
    assert (gl["dependency_of"], gl["status"]) == ("Denmark", "")
    assert build.fields(by_id["001"], by_id, "de-CH")["dependency_of"] == ""
    uk_dep = next(e for e in by_id.values() if e.get("dependency_of") == "235")
    assert build.fields(uk_dep, by_id, "en-US")["dependency_of"] == "the United Kingdom"
    assert build.fields(uk_dep, by_id, "de-CH")["dependency_of"] == "dem Vereinigten Königreich"
    xk = build.fields(by_id["118"], by_id, "de-CH")
    assert (xk["status"], xk["dependency_of"]) == ("Status umstritten", "")


def test_german_wikipedia_with_english_fallback(by_id):
    assert build.fields(by_id["217"], by_id, "de-CH")["wikipedia"] == "https://de.wikipedia.org/wiki/Schweiz"
    assert build.fields(by_id["217"], by_id, "en-US")["wikipedia"] == "https://en.wikipedia.org/wiki/Switzerland"
    assert build.fields(by_id["215"], by_id, "de-CH")["wikipedia"].startswith("https://en.wikipedia.org/")


def test_borders_list_neighbor_names_with_flags(by_id):
    de = build.fields(by_id["217"], by_id, "de-CH")["borders"]
    names = re.findall(r"<img[^>]*>([^<]+)</span>", de)
    assert names == ["Deutschland", "Frankreich", "Italien", "Liechtenstein", "Österreich"]
    assert 'src="cotw-014-flag.svg"' in de


# --- templates --------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rendered(by_id):
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    out = {}
    for code in languages.LANGUAGES:
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
        spec = languages.get(code)
        help_box = templates._help(spec, names, config)
        prompt, sep, rest = front.partition('<div class="cotw-box cotw-help">')
        assert sep and _visible_text(help_box) in _visible_text(sep + rest)
        assert _visible_text(prompt) == f"? {spec.ui['help']}", (code, cid)
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
            assert (word in text) == (code == "en-US") or key == "map-country" and word == "Show full info", (code, key, word)
        for word in de_only:
            assert (word in text) == (code == "de-CH"), (code, key, word)


def test_templates_are_readable():
    """Anki's template editor shows the source: one block element per line, indented by nesting."""
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    blocks = ('<div class="cotw-box', '<div class="cotw-row', '<div class="cotw-icon', '<div class="cotw-content')
    for code in languages.LANGUAGES:
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


def test_github_links_replace_email_and_ankiweb(rendered, collections):
    repository = build.load_config()["repository"].rstrip("/")
    issues = f"{repository}/issues"
    forbidden = ("mailto:", "info@feldbuch.com", "ankiweb.net")
    neutrality = {
        "en-US": "The deck makes no political statement",
        "de-CH": "Das Deck macht keine politische Aussage",
        "pl-PL": "Talia nie zajmuje stanowiska politycznego",
        "pt-BR": "O baralho não faz nenhuma declaração política",
    }
    border_warning = {
        "en-US": "Do not comment on or file issues regarding disputed areas.",
        "de-CH": "Bitte kommentiere umstrittene Gebiete nicht und erstelle keine Issues dazu.",
        "pl-PL": "Nie komentuj ani nie zgłaszaj problemów dotyczących spornych obszarów.",
        "pt-BR": "Não comente nem relate problemas relacionados a áreas disputadas.",
    }
    for code, col in collections.items():
        front, _ = rendered[code, "217", "country-capital"]
        decks = json.loads(col.execute("SELECT decks FROM col").fetchone()[0])
        description = next(d["desc"] for d in decks.values() if d["name"] == languages.get(code).deck)
        for text in (front, description):
            assert repository in text and issues in text, code
            assert not any(value in text.lower() for value in forbidden), code
        flat_front = " ".join(front.split())
        assert 'href="https://www.naturalearthdata.com">Natural Earth</a>' in flat_front
        assert neutrality[code] in flat_front and border_warning[code] in flat_front


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
        values = build.fields(e, by_id, "en-US")
        for key, kind in (("map_1", "map1"), ("map_2", "map2")):
            assert values[key] == (
                f'<img class="cotw-day" src="cotw-{cid}-{kind}-day.svg">'
                f'<img class="cotw-night" src="cotw-{cid}-{kind}-night.svg">'
            ), (cid, key)
        assert values["flag"] == f'<img src="cotw-{cid}-flag.svg">'  # flags stay one file


def test_icons_and_infographics_exist_once_per_mode(rendered):
    names = {k: n for k, (n, _) in build.assets().items()}
    front, back = rendered["en-US", "217", "country-capital"]
    for key in ("infographic", "infographic-filtered"):
        for mode in ("day", "night"):
            assert f'<img class="cotw-infographic cotw-{mode}" src="{names[f"{key}-{mode}"]}">' in front
    assert f'<img class="cotw-day" src="{names["icon-capital-day"]}"><img class="cotw-night" src="{names["icon-capital-night"]}">' in back
    assert not any(n.endswith(".png") for n in names.values()), "the v3 PNGs left the package"


def test_deck_description_attributions(collections):
    for code, col in collections.items():
        decks = json.loads(col.execute("SELECT decks FROM col").fetchone()[0])
        desc = next(d["desc"] for d in decks.values() if d["name"] == languages.get(code).deck)
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
        desc = next(d["desc"] for d in decks.values() if d["name"] == languages.get(code).deck)
        assert name in desc and "Copyright (c) 2023 Phosphor Icons" in desc, code


def _single_element(line: str) -> bool:
    """One tag (with its end tag) on the line: the globe element and its script carry hashed names."""
    return re.fullmatch(r'\s*<(\w+)[^<>]*>(</\1>)?', line) is not None


def test_templates_are_readable_html():
    """Anki's template editor shows the source: indented, commented, no endless lines (#44)."""
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    for code in languages.LANGUAGES:
        for t in templates.templates(code, names, config):
            for side, keys in (("qfmt", ("question", "buttons", "help")), ("afmt", ("answer", "info", "buttons", "help", "globe"))):
                text = t[side]
                comments = [languages.get(code).comments[k] for k in keys]
                lines = text.split("\n")
                where = (code, t["name"], side)
                assert len(lines) > 50, where
                for comment in comments:
                    assert f"<!-- {comment} -->" in text, (*where, comment)
                depth = 0
                for line in lines:
                    indent = len(line) - len(line.lstrip(" "))
                    assert indent % 2 == 0 and "\t" not in line, (*where, line)
                    assert indent <= depth + 2, (*where, line)  # never more than one level deeper
                    depth = indent
                    assert line == line.rstrip() and line.strip(), (*where, line)
                    assert len(line) <= 160 or _single_element(line), (*where, line)
                # Row structure: one element per line.
                assert '"><div class="cotw-' not in text, where
                assert "</div><div" not in text and "</div>    <div" not in text, where


def test_field_keys_are_mapped_to_field_names():
    names = {k: n for k, (n, _) in build.assets().items()}
    config = build.load_config()
    for code in languages.LANGUAGES:
        fields = set(languages.get(code).fields.values())
        for t in templates.templates(code, names, config):
            for side in ("qfmt", "afmt"):
                used = {m[1] for m in re.findall(r"\{\{([#^/]?)([^}]+)\}\}", t[side])}
                assert used <= fields, (code, t["name"], used - fields)
    with pytest.raises(KeyError, match="nope"):
        templates._fields("{{#nope}}", languages.get("en-US"))


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
    return {b.lang: b for b in build.build(list(languages.LANGUAGES), out, epoch=EPOCH, only=only)}


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
        assert decks[languages.get(code).deck] == languages.get(code).deck_id
        # Switzerland's borders still name and flag its neighbors, none of them in the subset.
        ch = next(f for f in rows.values() if f.startswith(by_id["217"]["name"][code]))
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
    en, de = (" ".join(languages.get(code).help.split()) for code in ("en-US", "de-CH"))
    assert "exclusive economic zone" in en and "200 nautical" in en and "12 nautical miles" in en
    assert "The globe shows only the economic zone." in en
    assert "Wirtschaftszone" in de and "200 Seemeilen" in de and "Hoheitsgewässer" in de
    assert "Der Globus zeigt nur die Wirtschaftszone." in de
    # The EEZ paragraph follows the maps/globe paragraph.
    assert en.index("Map 1 shows") < en.index("light-blue area") < en.index("For more information")
    assert de.index("Karte 1 zeigt") < de.index("hellblaue Fläche") < de.index("Mehr Informationen")
    assert "ß" not in de


def test_help_is_split_into_chapters():
    """The help has bold inline chapter headings, in this order; small islands are explained."""
    chapters = {
        "en-US": ("Card types:", "Maps and globe:", "Territorial waters and economic zones:", "Small islands:",
               "Borders:", "Help and contact:"),
        "de-CH": ("Kartentypen:", "Karten und Globus:", "Hoheitsgewässer und Wirtschaftszonen:", "Kleine Inseln:",
               "Grenzen:", "Hilfe und Kontakt:"),
        "pl-PL": ("Typy kart:", "Mapy i globus:", "Wody terytorialne i strefy ekonomiczne:", "Małe wyspy:",
               "Granice:", "Pomoc i kontakt:"),
        "pt-BR": ("Tipos de cartão:", "Mapas e globo:", "Mar territorial e zonas econômicas:", "Ilhas pequenas:",
               "Fronteiras:", "Ajuda e contato:"),
    }
    for code, heads in chapters.items():
        text = " ".join(languages.get(code).help.split())
        pos = [text.index(f"<p><b>{h}</b> ") for h in heads]
        assert pos == sorted(pos), code
    en, de = (" ".join(languages.get(code).help.split()) for code in ("en-US", "de-CH"))
    assert "economic zones and territorial waters are complete" in en and "disputed islands" in en
    assert "Wirtschaftszonen und Hoheitsgewässer sind aber vollständig" in de and "umstrittene Inseln" in de


def test_german_texts_address_the_learner_as_du():
    """Deck descriptions and help speak to the learner directly, never impersonally."""
    de = languages.get("de-CH")
    for text in (de.description, de.extras_description, de.help):
        flat = " ".join(text.split())
        assert not re.search(r"\b(Wer|man)\b", flat), flat
        assert "ß" not in flat
