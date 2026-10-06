"""Cross-checks over the committed country database (data/countries)."""

from __future__ import annotations

from collections import Counter

from cotw import ids as ids_mod
from cotw import schema, wikidata


def test_entry_count(entries):
    assert len(entries) == 248


def test_every_entry_matches_schema(entries, exceptions):
    sitelinks = wikidata.load_sitelinks()
    problems = []
    for path, entry in entries.items():
        problems += schema.validate_entry(entry, path, exceptions, sitelinks)
    assert problems == []


def test_cross_entry_rules(entries, taxonomy):
    assert schema.validate_all(entries, taxonomy) == []


def test_ids_unique_and_contiguous(by_id):
    numbers = sorted(int(i) for i in by_id)
    assert numbers == list(range(1, len(by_id) + 1))


def test_iso_codes_unique(entries):
    for field in ("iso2", "iso3", "wikidata"):
        counts = Counter(e[field] for e in entries.values())
        assert [v for v, n in counts.items() if n > 1] == [], field


def test_borders_symmetric(by_id):
    for cid, e in by_id.items():
        for b in e["borders"]:
            assert cid in by_id[b]["borders"], f"{cid} → {b} not symmetric"


def test_dependency_of_points_to_sovereign(by_id):
    for e in by_id.values():
        if e["status"] == "dependency":
            assert by_id[e["dependency_of"]]["status"] == "sovereign", e["id"]
        else:
            assert "dependency_of" not in e, e["id"]


def test_every_entry_has_a_capital_with_coordinates(by_id, exceptions):
    allowed = exceptions.get("no_capital_coordinates", {})
    for cid, e in by_id.items():
        with_coords = [c for c in e["capitals"] if "lat" in c and "lon" in c]
        assert with_coords or cid in allowed, cid


def test_status_counts(by_id):
    counts = Counter(e["status"] for e in by_id.values())
    assert counts == {"sovereign": 195, "dependency": 49, "disputed": 4}


def test_ledger_matches_files(entries, by_id):
    ledger = ids_mod.load()
    assert set(ledger) == set(by_id)
    for path, e in entries.items():
        assert path.name == f"{e['id']}-{ledger[e['id']]['slug']}.yaml"
        assert ledger[e["id"]]["iso2"] == e["iso2"]
        assert ledger[e["id"]]["wikidata"] == e["wikidata"]


def test_known_spreadsheet_errors_fixed(entries):
    by_iso = {e["iso2"]: e for e in entries.values()}
    ids = {iso: e["id"] for iso, e in by_iso.items()}

    def borders(iso):
        return {i for i in by_iso[iso]["borders"]}

    assert ids["MY"] in borders("ID") and ids["ML"] not in borders("ID")
    assert ids["MW"] in borders("MZ") and ids["ML"] not in borders("MZ")
    assert ids["MW"] in borders("ZM") and ids["ML"] not in borders("ZM")
    assert ids["SK"] in borders("UA") and ids["SI"] not in borders("UA")
    assert ids["AF"] not in borders("IN") and ids["IN"] not in borders("AF")
    assert ids["HK"] in borders("CN") and ids["MO"] in borders("CN")
    assert ids["SR"] not in borders("FR") and ids["SR"] in borders("GF")


def test_umlauts_survive_round_trip(entries):
    """Real non-ASCII strings must be stored verbatim (no transliteration, no escapes)."""
    by_iso = {e["iso2"]: e for e in entries.values()}
    assert by_iso["AT"]["name"]["de"] == "Österreich"
    assert by_iso["CI"]["name"]["en"].startswith("Côte d’Ivoire")
    assert by_iso["CW"]["name"]["en"] == "Curaçao"
    assert by_iso["ST"]["name"]["de"] == "São Tomé und Príncipe"
    # and the files contain them literally, not as \u escapes
    for path, e in entries.items():
        if e["iso2"] in ("AT", "CI", "CW"):
            text = path.read_text(encoding="utf-8")
            assert e["name"]["de"] in text and e["name"]["en"] in text
            assert "\\u" not in text


def test_naoero_renamed_codes_kept(by_id):
    """Nauru became the Republic of Naoero (2026-06-26); ISO NR/NRU, id and slug stay."""
    nr = by_id["153"]
    assert nr["name"] == {"en": "Naoero", "de": "Naoero", "pt": "Naoero"}
    assert nr["formal_name"] == {"en": "The Republic of Naoero", "de": "Republik Naoero", "pt": "República de Naoero"}
    assert (nr["iso2"], nr["iso3"], nr["wikidata"]) == ("NR", "NRU", "Q697")
    assert ids_mod.load()["153"]["slug"] == "nauru"
    assert [c["name"]["en"] for c in nr["capitals"]] == ["Yaren"]


def test_equatorial_guinea_capital_ciudad_de_la_paz(by_id):
    """Decreto Ley 1/2026 made Ciudad de la Paz the capital; Malabo stays seat of
    government while the ministries move. Capital 1 is what "Country → Capital" asks."""
    caps = by_id["067"]["capitals"]
    assert [(c["wikidata"], c["role"]) for c in caps] == [
        ("Q1140136", "capital"),
        ("Q3818", "seat_of_government"),
    ]
    assert caps[0]["label"] == {"en": "capital", "de": "Hauptstadt", "pt": "capital"}
    assert caps[1]["label"] == {
        "en": "seat of government until the move is completed",
        "de": "Regierungssitz bis zum Abschluss des Umzugs",
        "pt": "sede do governo até a conclusão da mudança",
    }
