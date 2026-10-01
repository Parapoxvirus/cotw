"""Maritime zone assignment rule on synthetic attribute rows (offline, no geometry)."""

from __future__ import annotations

from cotw.marineregions import assign, latitude_first


def row(mrgid, kind, ter1="", sov1="", ter2="", sov2="", name="Zone"):
    return {
        "mrgid": mrgid, "pol_type": kind, "geoname": name,
        "iso_ter1": ter1, "iso_sov1": sov1, "iso_ter2": ter2, "iso_sov2": sov2,
        "iso_ter3": "", "iso_sov3": "",
    }


CODES = {"AAA", "BBB", "CCC", "DEP"}
OVERRIDES = {
    "aliases": {"XMI": {"to": "AAA", "reason": "minor islands of Mätzlingen"}},
    "assign": {7: {"to": "BBB", "reason": "administered by Groß-Übersee"}},
    "exclude": {8: "claim nobody administers"},
}


def zones(result, iso, layer="eez"):
    return [r["mrgid"] for r in result["assigned"][iso][layer]]


def test_territory_wins_over_sovereign():
    res = assign([row(1, "200NM", ter1="DEP", sov1="AAA")], [], CODES, {})
    assert zones(res, "DEP") == [1] and zones(res, "AAA") == []


def test_part_without_territory_code_goes_to_sovereign():
    res = assign([row(2, "200NM", sov1="AAA", name="Zone (Überseeinseln)")], [row(3, "12NM", sov1="AAA")], CODES, {})
    assert zones(res, "AAA") == [2]
    assert zones(res, "AAA", "nm12") == [3]


def test_overlapping_claim_only_first_territory():
    res = assign([row(4, "Overlapping claim", ter1="AAA", sov1="AAA", ter2="BBB", sov2="BBB")], [], CODES, {})
    assert zones(res, "AAA") == [4] and zones(res, "BBB") == []


def test_overlapping_claim_without_territory_is_skipped():
    res = assign([row(5, "Overlapping claim", sov1="AAA", sov2="BBB")], [], CODES, {})
    assert zones(res, "AAA") == [] and zones(res, "BBB") == []
    assert [s["mrgid"] for s in res["skipped"]] == [5]


def test_joint_regime_every_party():
    res = assign([row(6, "Joint regime", ter1="AAA", sov1="AAA", sov2="CCC")], [], CODES, {})
    assert zones(res, "AAA") == [6] and zones(res, "CCC") == [6]


def test_overrides_alias_assign_exclude():
    rows = [
        row(7, "Overlapping claim", sov1="AAA", sov2="BBB"),
        row(8, "Overlapping claim", ter1="AAA"),
        row(9, "200NM", ter1="XMI", sov1="ZZZ"),
    ]
    res = assign(rows, [], CODES, OVERRIDES)
    assert zones(res, "BBB") == [7]
    assert zones(res, "AAA") == [9]
    assert [(s["mrgid"], s["reason"]) for s in res["skipped"]] == [(8, "claim nobody administers")]


def test_unknown_territory_is_reported():
    res = assign([row(10, "200NM", ter1="QQQ", sov1="QQQ")], [], CODES, {})
    assert res["skipped"][0]["mrgid"] == 10 and "QQQ" in res["skipped"][0]["reason"]


def test_latitude_first_axis_order(tmp_path):
    prj = tmp_path / "a.prj"
    prj.write_text('GEOGCS["WGS 84", AXIS["Geodetic latitude", NORTH], AXIS["Geodetic longitude", EAST]]')
    assert latitude_first(prj)
    prj.write_text('GEOGCS["WGS 84", AXIS["Geodetic longitude", EAST], AXIS["Geodetic latitude", NORTH]]')
    assert not latitude_first(prj)
    assert not latitude_first(tmp_path / "missing.prj")


def test_land_holes_are_dropped_zone_holes_kept():
    shapely = __import__("pytest").importorskip("shapely")
    from shapely.geometry import MultiPolygon, Polygon, box

    from cotw.marineregions import drop_land_holes

    land = box(2.0, 2.0, 3.0, 3.0)  # a bay the zone's own coastline cut out
    enclave = box(6.0, 6.0, 7.0, 7.0)  # another territory's zone (Saint-Pierre in Canada's)
    outer = Polygon(box(0.0, 0.0, 10.0, 10.0).exterior, [land.exterior.coords, enclave.exterior.coords])
    island = Polygon(box(20.0, 0.0, 22.0, 2.0).exterior, [box(20.5, 0.5, 21.0, 1.0).exterior.coords])
    rows = [
        dict(row(1, "200NM", ter1="AAA", name="Groß-Zone"), geom=MultiPolygon([outer, island])),
        dict(row(2, "200NM", ter1="DEP", name="Übersee"), geom=enclave),
    ]
    out = drop_land_holes(rows)
    parts = list(out[0]["geom"].geoms)
    assert [len(p.interiors) for p in parts] == [1, 0]
    assert Polygon(parts[0].interiors[0]).equals(enclave)
    assert out[1]["geom"].equals(enclave) and out[0]["geoname"] == "Groß-Zone"
    assert shapely.get_num_interior_rings(rows[0]["geom"].geoms[0]) == 2  # input untouched


def test_large_land_free_holes_are_high_seas_pockets():
    __import__("pytest").importorskip("shapely")
    from shapely.geometry import Polygon, box

    from cotw.marineregions import POCKET_DEG2, drop_land_holes

    island = box(1.0, 1.0, 1.5, 1.5)  # Natural Earth land in the first hole
    lagoon = box(3.0, 3.0, 3.2, 3.2)  # small, no land: an atoll lagoon → filled
    pocket = box(5.0, 5.0, 7.0, 7.0)  # large, no land: the Peanut Hole → kept
    assert pocket.area >= POCKET_DEG2 > lagoon.area
    zone = Polygon(box(0.0, 0.0, 10.0, 10.0).exterior, [g.exterior.coords for g in (box(0.8, 0.8, 1.7, 1.7), lagoon, pocket)])
    rows = [dict(row(1, "200NM", ter1="AAA", name="Groß-Zone"), geom=zone)]
    (out,) = drop_land_holes(rows, land=[island])
    assert [Polygon(h).equals(pocket) for h in out["geom"].interiors] == [True]
    (bare,) = drop_land_holes(rows)  # without land only the other-zone rule applies
    assert list(bare["geom"].interiors) == []
