"""The globe script media/_cotw-globe.js: checks over the committed asset (pure Python) and
the TopoJSON builder on synthetic geometry (shapely needed). The renderer's math is tested
in tests/js/ (node --test tests/js/*.test.js)."""

from __future__ import annotations

import hashlib
import json
import re

import pytest
import yaml

from cotw import languages
from cotw.paths import DERIVED, MEDIA, OVERRIDES, ROOT, STYLE

SCRIPT = MEDIA / "_cotw-globe.js"
PARTS = {part: MEDIA / f"_cotw-globe-{part}.js" for part in ("zones", "detail")}
SOURCE = ROOT / "tools" / "globe" / "globe.js"
MARKER = "var DATA = null; // @@COTW_DATA@@"
SIZE_MAX = 2_000_000
BOOTSTRAP_MAX = 400_000


def _data(text: str) -> dict:
    # The data is embedded as a JSON string literal (parsed by the script on first use).
    line = text.index("var DATA = null, DATA_KEY = ")  # the spliced line, not the defaults above it
    start = text.index("DATA_JSON = ", line) + len("DATA_JSON = ")
    return json.loads(json.loads(text[start : text.index(";\n", start)]))


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bootstrap(script) -> dict:
    return _data(script)


def _packet(path) -> dict:
    script = path.read_text(encoding="utf-8")
    start = script.index("var DETAIL = ") + len("var DETAIL = ")
    return json.loads(script[start:script.index(";\n", start)])


@pytest.fixture(scope="module")
def packets() -> dict[str, dict]:
    return {part: _packet(path) for part, path in PARTS.items()}


@pytest.fixture(scope="module")
def data(bootstrap, packets) -> dict:
    """Join independent packets for the existing whole-world geometry checks."""
    import copy
    data = copy.deepcopy(bootstrap)
    topo = data["topology"]
    topo["objects"]["eez"] = {"type": "GeometryCollection", "geometries": []}

    def add(part):
        offset = len(topo["arcs"])
        def refs(value):
            if isinstance(value, int):
                return value + offset if value >= 0 else ~(~value + offset)
            return [refs(child) for child in value]
        for key, obj in part["objects"].items():
            for geom in obj.get("geometries", [obj]):
                geom["arcs"] = refs(geom["arcs"])
            if key == "eez":
                topo["objects"]["eez"]["geometries"].append(obj)
            else:
                topo["objects"][key] = obj
        topo["arcs"] += [json.loads(arc) for arc in part["arcs"]]

    for packet in packets.values():
        for part in [*packet.get("levels", {}).values(), *packet.get("zones", {}).values()]:
            add(json.loads(part))
    return data


def _arc_ids(arcs) -> set[int]:
    out: set[int] = set()
    for poly in arcs:
        for ring in poly:
            out |= {a if a >= 0 else ~a for a in ring}
    return out


# --- committed asset --------------------------------------------------------------------------


def test_size_budget(script):
    assert len(script.encode("utf-8")) <= BOOTSTRAP_MAX
    assert len(script.encode("utf-8")) + sum(path.stat().st_size for path in PARTS.values()) <= SIZE_MAX
    assert not (MEDIA / "_cotw-globe-overview.js").exists(), "the overview packet is gone (issue #31)"


def test_asset_is_built_from_current_source(script, bootstrap):
    """The committed script is exactly the renderer source plus the data line."""
    blob = json.dumps(bootstrap, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    key = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]
    line = f'var DATA = null, DATA_KEY = "{key}", DATA_JSON = {json.dumps(blob, ensure_ascii=True)};'
    assert script == SOURCE.read_text(encoding="utf-8").replace(MARKER, line)


def test_deferred_packets_are_outside_first_paint_and_share_a_key(bootstrap, packets):
    # L2, the coarsest level, is the bootstrap (L0 was dropped with issue #22, L1 with #31).
    assert set(bootstrap["topology"]["objects"]) == {"entries_2", "other_2"}
    # EEZs and fine land are independent packets (issue #17).
    assert set(packets["detail"]["levels"]) == {"1"} and "zones" not in packets["detail"]
    assert packets["zones"]["zones"] and "levels" not in packets["zones"]
    assert [level.get("part") for level in bootstrap["lod"]] == [None, "detail"]
    for packet in packets.values():
        for part in [*packet.get("levels", {}).values(), *packet.get("zones", {}).values()]:
            assert all(isinstance(arc, str) for arc in json.loads(part)["arcs"])
    content = {part: {k: v for k, v in p.items() if k not in ("key", "part")} for part, p in packets.items()}
    blob = json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    key = hashlib.sha256(blob.encode()).hexdigest()[:16]
    assert bootstrap["detailKey"] == key
    assert {part: (p["key"], p["part"]) for part, p in packets.items()} == {part: (key, part) for part in PARTS}


def _levels(data) -> list[tuple[dict, dict]]:
    objs = data["topology"]["objects"]
    return [(objs[level["entries"]], objs[level["other"]]) for level in data["lod"]]


def test_levels_of_detail(by_id, data):
    """Two levels, coarsest first, each a complete land topology of every entry. Nothing is
    coarser than L2 (issue #31)."""
    assert [(level["name"], level["tolerance"]) for level in data["lod"]] == [("L2", 0.25), ("L3", 0.04)]
    assert data["lod"][-1] == {"name": "L3", "tolerance": 0.04, "entries": "entries", "other": "other", "part": "detail"}
    for entries, other in _levels(data):
        assert [g["id"] for g in entries["geometries"]] == sorted(by_id)
        assert all(g["arcs"] for g in entries["geometries"])
        assert other["arcs"]
    # Each level is its own simplification; an arc is shared only where two levels agree on
    # it exactly.
    sets = [set().union(*(_arc_ids(g["arcs"]) for g in e["geometries"])) | _arc_ids(o["arcs"]) for e, o in _levels(data)]
    assert not sets[0] & sets[1]
    assert len(sets[0]) < len(sets[1])


def test_kept_eez_holes_reach_the_globe(data):
    """Canada's EEZ keeps the hole of the French zone of Saint-Pierre and Miquelon."""
    eez = {g["id"]: g for g in data["topology"]["objects"]["eez"]["geometries"]}
    assert any(len(poly) > 1 for poly in eez["040"]["arcs"])


def _polygons(topo: dict, geom: dict) -> list:
    """Shapely polygons (lon/lat) of one TopoJSON MultiPolygon of the committed topology."""
    from shapely.geometry import Polygon

    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]

    def arc(i):
        x = y = 0
        pts = []
        for dx, dy in topo["arcs"][i if i >= 0 else ~i]:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        return pts if i >= 0 else pts[::-1]

    out = []
    for poly in geom["arcs"]:
        rings = []
        for ring in poly:
            pts: list = []
            for i in ring:
                a = arc(i)
                pts += a if not pts else a[1:]
            rings.append(pts)
        if len(rings[0]) >= 3:
            out.append(Polygon(rings[0], [r for r in rings[1:] if len(r) >= 3]).buffer(0))
    return out


# Coast gaps: holes of (EEZ ∪ entry land) along the entry's coast show the plain sea color in
# the zone. Before issue #22 the globe had 7 239 of them (45 deg², Svalbard's and Norway's
# fjords, the Gulf of Bothnia …); quantization leaves specks far below this size.
EEZ_GAP_MAX_DEG2 = 0.01


def test_no_eez_gap_along_the_entry_coast(data):
    pytest.importorskip("shapely")
    from shapely.ops import unary_union

    topo = data["topology"]
    land = {g["id"]: g for g in topo["objects"][data["lod"][-1]["entries"]]["geometries"]}
    offenders = []
    for g in topo["objects"]["eez"]["geometries"]:
        coast = unary_union(_polygons(topo, land[g["id"]]))
        both = unary_union([*_polygons(topo, g), coast])
        for p in getattr(both, "geoms", [both]):
            for ring in p.interiors:
                hole = type(p)(ring)
                if hole.area > EEZ_GAP_MAX_DEG2 and hole.distance(coast) <= 1e-6:
                    offenders.append((g["id"], round(hole.area, 3), hole.representative_point().coords[0]))
    assert offenders == []


def test_every_entry_is_in_the_topology_under_its_cotw_id(by_id, data):
    geoms = data["topology"]["objects"]["entries"]["geometries"]
    ids = [g["id"] for g in geoms]
    assert ids == sorted(by_id)
    assert sorted(data["entries"]) == sorted(by_id)
    for g in geoms:
        assert g["arcs"], f"{g['id']}: no land"


def test_keys_are_cotw_ids_never_iso(by_id, data):
    iso = {e["iso2"] for e in by_id.values()} | {e["iso3"] for e in by_id.values()}
    objects = data["topology"]["objects"]
    keys = set(data["entries"]) | {g["id"] for g in objects["entries"]["geometries"]}
    keys |= {g["id"] for g in objects["eez"]["geometries"]}
    assert all(re.fullmatch(r"\d{3}", k) for k in keys)
    assert not keys & iso
    assert "id" not in objects["other"]


def test_neighbors_are_exactly_the_borders(by_id, data):
    for cid, e in by_id.items():
        assert data["entries"][cid]["n"] == e.get("borders", []), cid


def test_eez_present_where_step_2_has_one(data):
    manifest = yaml.safe_load((DERIVED / "maritime.yaml").read_text(encoding="utf-8"))["entries"]
    expected = sorted(cid for cid, m in manifest.items() if m["eez"])
    assert [g["id"] for g in data["topology"]["objects"]["eez"]["geometries"]] == expected


def test_names_and_centers(by_id, data):
    centers = yaml.safe_load((OVERRIDES / "centers.yaml").read_text(encoding="utf-8"))
    for cid, e in by_id.items():
        m = data["entries"][cid]
        assert m["name"] == {code: e["name"][code] for code in languages.LANGUAGES}
        lon, lat = m["c"]
        assert -180 <= lon <= 180 and -90 <= lat <= 90
        assert 1.0 <= m["z"] <= 2.5
        assert m["a"] > 0
        if cid in centers:
            assert (lon, lat) == pytest.approx((centers[cid]["lon"], centers[cid]["lat"]), abs=1e-3)


def test_umlauts_survive(data):
    assert data["entries"]["217"]["name"]["de"] == "Schweiz"
    assert any("ä" in m["name"]["de"] or "ö" in m["name"]["de"] or "ü" in m["name"]["de"] for m in data["entries"].values())


def test_eez_hulls_for_entries_that_can_get_circles(by_id, bootstrap):
    # Issue #25: the highlight circle encloses the EEZ, so its outline must be in the
    # bootstrap (not the deferred zones packet) for every entry that can get circles.
    manifest = yaml.safe_load((DERIVED / "maritime.yaml").read_text(encoding="utf-8"))["entries"]
    fill, area = _js_number("SPHERE_FILL"), _js_number("HIGHLIGHT_AREA")
    for cid in by_id:
        m = bootstrap["entries"][cid]
        small = m["a"] * (fill / 2) ** 2 < area
        assert ("e" in m) == (small and bool(manifest[cid]["eez"])), cid
        for ring in m.get("e", []):
            assert 3 <= len(ring) <= 12
            assert all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in ring)
    assert len(bootstrap["entries"]["117"]["e"]) == 3  # Kiribati: Gilbert, Phoenix, Line Islands


def _js_number(name: str) -> float:
    m = re.search(rf"var {name} = ([\d./ e]+);", SOURCE.read_text(encoding="utf-8"))
    return float(eval(m.group(1)))  # a literal or a quotient of literals from the COTW globe source


def test_palette_matches_palette_yaml(data):
    palette = yaml.safe_load((STYLE / "palette.yaml").read_text(encoding="utf-8"))
    for mode in ("day", "night"):
        got = data["palette"][mode]
        for k in ("sea", "coast", "entry", "neighbor", "land", "eez", "highlight"):
            assert got[k] == palette[mode][k]
        for k, v in palette["globe"][mode].items():
            assert got[k] == v


def test_arcs_are_valid_and_all_used(data):
    topo = data["topology"]
    n = len(topo["arcs"])
    used: set[int] = set()
    objects = topo["objects"]
    for entries, other in _levels(data):
        for g in entries["geometries"] + [other]:
            used |= _arc_ids(g["arcs"])
    for g in objects["eez"]["geometries"]:
        used |= _arc_ids(g["arcs"])
    assert used == set(range(n))
    for arc in topo["arcs"]:
        assert len(arc) >= 2
        assert all(len(p) == 2 and all(isinstance(v, int) for v in p) for p in arc)


def test_land_borders_are_shared_arcs(by_id, data):
    """Topology: Switzerland and each of its neighbors reference a common arc."""
    for entries, _ in _levels(data):
        geoms = {g["id"]: g for g in entries["geometries"]}
        ch = _arc_ids(geoms["217"]["arcs"])
        for n in by_id["217"]["borders"]:
            assert ch & _arc_ids(geoms[n]["arcs"]), n


# --- builder on synthetic geometry ---------------------------------------------------------------


@pytest.fixture(scope="module")
def globe():
    pytest.importorskip("shapely")
    from cotw import globe

    return globe


def _entry(cid, iso2, iso3, borders):
    return {"id": cid, "iso2": iso2, "iso3": iso3, "borders": list(borders), "name": {"en": f"Mätzland {cid}", "de": f"Groß-Mätzland {cid}"}}


@pytest.fixture(scope="module")
def synthetic(globe):
    from shapely.geometry import MultiPolygon, box

    # AA borders BB; DD is an enclave in BB; EE straddles the antimeridian; one other-land box.
    land = {
        "AA": box(8.0, 0.0, 12.0, 4.0),
        "BB": box(12.0, 0.0, 20.0, 4.0).difference(box(15.0, 1.0, 15.5, 1.5)),
        "DD": box(15.0, 1.0, 15.5, 1.5),
        "EE": MultiPolygon([box(178.0, 50.0, 180.0, 52.0), box(-180.0, 50.0, -178.0, 52.0)]),
    }
    entries = {
        "001": _entry("001", "AA", "AAA", ["002"]),
        "002": _entry("002", "BB", "BBB", ["001", "004"]),
        "004": _entry("004", "DD", "DDD", ["002"]),
        "005": _entry("005", "EE", "EEE", []),
    }
    eez = {"AAA": [box(6.0, -2.0, 8.0, 6.0).difference(box(6.5, 0.0, 7.0, 0.5))]}
    other = [box(-60.0, -80.0, 60.0, -70.0)]
    return entries, land, other, eez


def _payload(globe, synthetic):
    from cotw import maps

    entries, land, other, eez = synthetic
    return globe.payload(entries, land, {}, other, eez, maps.load_palette(), {"005": {"lat": 51.0, "lon": 180.0}})


def test_deterministic(globe, synthetic):
    a, da = globe.split_payload(_payload(globe, synthetic))
    b, db = globe.split_payload(_payload(globe, synthetic))
    assert globe.render(a) == globe.render(b)
    assert set(da) == set(db) == set(globe.PART_FILE_NAMES)
    for part in da:
        assert globe.render_detail(da[part]) == globe.render_detail(db[part])


def test_packet_assets_are_built_from_current_source(globe, packets):
    assert {part: path.name for part, path in PARTS.items()} == globe.PART_FILE_NAMES
    for part, path in PARTS.items():
        assert path.read_text(encoding="utf-8") == globe.render_detail(packets[part])


def test_detail_change_invalidates_bootstrap(globe, synthetic):
    data = _payload(globe, synthetic)
    before, _ = globe.split_payload(data)
    data["topology"]["objects"]["eez"]["geometries"].clear()
    after, _ = globe.split_payload(data)
    assert before["detailKey"] != after["detailKey"]
    assert globe.render(before) != globe.render(after)


def test_synthetic_topology(globe, synthetic):
    data = _payload(globe, synthetic)
    topo = data["topology"]
    geoms = {g["id"]: g for g in topo["objects"]["entries"]["geometries"]}
    assert sorted(geoms) == ["001", "002", "004", "005"]
    # Shared border AA|BB and the enclave ring DD = hole of BB: one arc each, used twice.
    assert _arc_ids(geoms["001"]["arcs"]) & _arc_ids(geoms["002"]["arcs"])
    assert _arc_ids(geoms["004"]["arcs"]) <= _arc_ids(geoms["002"]["arcs"])
    # Antimeridian: two parts, not fused (lon/lat topology), the renderer skips the seam.
    assert len(geoms["005"]["arcs"]) == 2
    assert data["entries"]["005"]["c"] == [180.0, 51.0]
    assert data["entries"]["002"]["n"] == ["001", "004"]
    # EEZ: the hole the loader left (another zone, a pocket) is kept: exterior + hole.
    eez = topo["objects"]["eez"]["geometries"]
    assert [g["id"] for g in eez] == ["001"] and len(eez[0]["arcs"][0]) == 2
    # Every level carries every entry.
    for level in data["lod"]:
        assert sorted(g["id"] for g in topo["objects"][level["entries"]]["geometries"]) == ["001", "002", "004", "005"]
    assert "id" not in topo["objects"]["other"] and topo["objects"]["other"]["arcs"]


def test_eez_fills_the_bays_between_zone_and_coast(globe):
    """The zone reaches into a bay only as a tongue (Marine Regions' coastline lies seaward of
    Natural Earth's): the globe fills the bay like the maps do, and keeps a high-seas pocket."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    land = box(0, 0, 10, 10).difference(box(3, 5, 7, 10))
    zone = unary_union([box(-1, 10, 11, 14), box(3.5, 8, 6.5, 10)])
    without = unary_union(globe.simplify_zone([zone]))
    assert without.intersection(box(3, 5, 7, 8)).area == 0, "the bay is open without the land"
    filled = unary_union(globe.simplify_zone([zone], [land]))
    assert filled.contains(box(3.1, 5.1, 6.9, 9.9)), "the bay is filled"
    # A hole the loader kept (a pocket away from the coast, another territory's zone) stays.
    pocket = Polygon(box(-1, 10, 11, 20).exterior, [box(4, 15, 6, 17).exterior.coords])
    kept = unary_union(globe.simplify_zone([pocket], [land]))
    assert kept.intersection(box(4.2, 15.2, 5.8, 16.8)).area == 0
    assert kept.contains(box(3.1, 5.1, 6.9, 9.9))


def test_decoded_coordinates_roundtrip(globe, synthetic):
    topo = _payload(globe, synthetic)["topology"]
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    pts = set()
    for arc in topo["arcs"]:
        x = y = 0
        for dx, dy in arc:
            x += dx
            y += dy
            pts.add((round(x * sx + tx, 6), round(y * sy + ty, 6)))
    for corner in [(8.0, 0.0), (12.0, 4.0), (15.5, 1.5), (180.0, 50.0), (-180.0, 52.0)]:
        assert corner in pts


def test_junctions_split_rings_and_reuse_reversed_arcs(globe):
    t = globe.Topology()
    a = [(0, 0), (2, 0), (2, 2), (0, 2)]
    b = [(2, 0), (4, 0), (4, 2), (2, 2)]
    polys = t.add([[a], [b]])
    shared = [i for i in polys[0][0] if (i if i >= 0 else ~i) in {j if j >= 0 else ~j for j in polys[1][0]}]
    assert len(shared) == 1
    # The shared edge runs in opposite directions in the two rings: one ref is reversed.
    other = [j for j in polys[1][0] if (j if j >= 0 else ~j) == (shared[0] if shared[0] >= 0 else ~shared[0])][0]
    assert (shared[0] < 0) != (other < 0)


def test_long_segments_are_densified(globe):
    t = globe.Topology()
    q = globe.quantize_point
    ring = [q(0, 0), q(10, 0), q(10, 1), q(0, 1)]
    t.add([[ring]])
    t.add([[ring]], max_segment=3.0)  # a different densification: own arc
    fine, coarse = t.encoded_arcs()
    for arc, seg in ((fine, globe.MAX_SEGMENT_DEG), (coarse, 3.0)):
        step = seg / 360.0 * (globe.QUANTIZATION[0] - 1)
        assert all(abs(dx) <= step + 1 and abs(dy) <= step + 1 for dx, dy in arc[1:])
    assert len(fine) > 20 and len(coarse) < len(fine)


def test_zone_hulls_fuse_the_antimeridian_and_contain_the_zone(globe):
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    from cotw import geometry

    # A Kiribati-like EEZ cut at ±180° plus a separate part further east.
    ragged = Polygon([(175, -5), (177, -6), (180, -5), (180, 5), (176, 6), (175, 3)])
    polys = [ragged, box(-180, -5, -172, 3), box(-160, -3, -150, 2)]
    hulls = globe.zone_hulls(polys, 0.0, 179.0, max_points=6)
    assert len(hulls) == 2  # the two halves are one part
    proj = geometry.Projection(0.0, 179.0)
    first = proj.forward(Polygon(hulls[0])).buffer(1e-3)
    assert all(len(h) <= 6 for h in hulls)
    assert first.contains(unary_union([proj.forward(p) for p in polys[:2]]))
    assert proj.forward(Polygon(hulls[1])).buffer(1e-3).contains(proj.forward(polys[2]))
    assert globe.zone_hulls([], 0.0, 0.0) == []


def test_can_highlight_matches_the_renderer(globe):
    assert globe.SPHERE_FILL == _js_number("SPHERE_FILL")
    assert globe.HIGHLIGHT_AREA == pytest.approx(_js_number("HIGHLIGHT_AREA"))
    limit = globe.HIGHLIGHT_AREA / (globe.SPHERE_FILL / 2) ** 2
    assert globe.can_highlight(limit * 0.99) and not globe.can_highlight(limit * 1.01)


def test_initial_zoom_rule(globe):
    assert globe.initial_zoom(80.0) == 1.0  # Russia-sized: whole globe
    assert globe.initial_zoom(0.1) == globe.ZOOM_MAX_INITIAL  # micro-state: capped
    assert 1.0 < globe.initial_zoom(9.0) < globe.ZOOM_MAX_INITIAL


def test_size_report_adds_up(globe, synthetic):
    data = _payload(globe, synthetic)
    script = globe.render(data)
    report = globe.size_report(data, script)
    assert report["total"] == len(script.encode("utf-8"))
    assert report["code"] > 0 and report["eez arcs"] > 0
    assert all(report[f"land arcs {name}"] > 0 for name, *_ in globe.LEVELS)
    assert sum(v for k, v in report.items() if k != "total") == report["total"]
