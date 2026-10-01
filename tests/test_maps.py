"""Projection, windows and SVG rendering on synthetic geometry (offline; shapely needed)."""

from __future__ import annotations

import math
import re

import pytest

np = pytest.importorskip("numpy")
shapely = pytest.importorskip("shapely")
from shapely.geometry import MultiPolygon, box  # noqa: E402

from cotw import geometry, maps  # noqa: E402

PALETTE = maps.load_palette()


def test_projection_center_and_roundtrip():
    proj = geometry.Projection(46.9, 7.4)
    assert proj.point(46.9, 7.4) == pytest.approx((0.0, 0.0), abs=1e-9)
    pts = np.array([[7.4, 50.0], [-170.0, -20.0], [179.9, 10.0], [0.0, -89.0]])
    back = proj.inverse_xy(proj.forward_xy(pts))
    assert back == pytest.approx(pts, abs=1e-6)


def test_projection_is_equal_area():
    # A 1°×1° cell near the center and one 40° away have the area the sphere gives them.
    proj = geometry.Projection(0.0, 0.0)
    for lat in (0.0, 40.0):
        cell = proj.forward(box(10.0, lat, 11.0, lat + 1.0))
        exact = (math.radians(1.0) * geometry.R**2) * (math.sin(math.radians(lat + 1)) - math.sin(math.radians(lat)))
        assert cell.area == pytest.approx(exact, rel=1e-3)


def test_antipode_polygon_is_dropped():
    proj = geometry.Projection(10.0, 10.0)
    assert proj.antipode == (-10.0, -170.0)
    far = box(-175.0, -15.0, -165.0, -5.0)  # contains the antipode
    assert geometry.project_clip(far, proj, geometry.window_box(20000.0)) == []


def test_window_rules():
    assert geometry.window((-10, -10, 10, 10), "map1") == (geometry.MAP1_MIN_KM, (0.0, 0.0))
    assert geometry.window((-3000, -10, 3000, 10), "map1")[0] == geometry.MAP1_MAX_KM
    r, c = geometry.window((-100, -50, 80, 100), "map2")
    assert r == pytest.approx(90 * geometry.MAP2_FACTOR) and c == pytest.approx((-10, 25))
    assert geometry.window((-0.1, -0.1, 0.1, 0.1), "map2")[0] == geometry.MAP2_MIN_KM


# --- synthetic world -----------------------------------------------------------------------
#   AA (entry, 4°×4°) borders BB to the east; CC is an island to the south (no border);
#   DD is a micro-state inside BB; EE straddles the antimeridian, split in two parts.


def _entry(cid, iso2, iso3, borders, capitals=()):
    return {
        "id": cid, "iso2": iso2, "iso3": iso3, "name": {"en": f"Mätzlingen {cid}"},
        "borders": list(borders),
        "capitals": [
            {"name": {"en": "Groß-Stadt"}, "role": role, "lat": lat, "lon": lon} for role, lat, lon in capitals
        ],
    }


@pytest.fixture(scope="module")
def world_and_entries():
    bb = box(12.0, 0.0, 20.0, 4.0).difference(box(15.0, 1.0, 15.01, 1.01))
    land = {
        "AA": box(8.0, 0.0, 12.0, 4.0),
        "BB": bb,
        "CC": box(9.0, -4.0, 11.0, -3.0),
        "DD": box(15.0, 1.0, 15.01, 1.01),
        "EE": MultiPolygon([box(178.0, 50.0, 180.0, 52.0), box(-180.0, 50.0, -178.0, 52.0)]),
    }
    eez = {"AAA": [box(7.0, -1.0, 8.0, 5.0)]}
    nm12 = {"AAA": [box(7.8, -0.2, 8.0, 4.2)]}
    world = maps.World(land, [], eez, nm12)
    entries = {
        "001": _entry("001", "AA", "AAA", ["002"], [("capital", 2.0, 10.0), ("seat_of_government", 1.0, 9.0)]),
        "002": _entry("002", "BB", "BBB", ["001", "004"]),
        "003": _entry("003", "CC", "CCC", []),
        "004": _entry("004", "DD", "DDD", ["002"], [("capital", 1.005, 15.005)]),
        "005": _entry("005", "EE", "EEE", [], [("capital", 51.0, 179.0)]),
    }
    return world, entries


def _render(world, entries, cid, kind):
    spec = maps.plan(entries[cid], kind, world.land[entries[cid]["iso2"]], {})
    return maps.render(spec, world, PALETTE, entries)


def test_layers_and_neighbors(world_and_entries):
    world, entries = world_and_entries
    svg = _render(world, entries, "001", "map1")
    assert svg.count('class="f"') == 1  # entry
    assert svg.count('class="e"') == 1  # exactly its one neighbor
    assert svg.count('class="d"') >= 1  # other land (island CC, micro-state DD is not a neighbor of AA)
    assert svg.count('class="b"') == 1 and svg.count('class="c"') == 1  # EEZ + 12 nm


def _boxes(svg: str) -> list[tuple[float, float, float, float]]:
    """Bounding box of every digit path (absolute coordinates, class "i")."""
    out = []
    for d in re.findall(r'<path class="i" d="([^"]+)"', svg):
        nums = [float(n) for n in re.findall(r"-?[\d.]+", d)]
        xs, ys = nums[::2], nums[1::2]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


def test_capital_markers_are_uniform_and_numbered(world_and_entries):
    world, entries = world_and_entries
    svg = _render(world, entries, "001", "map2")
    # Two capitals of different roles: the same outlined white circle, one number each.
    assert svg.count('<circle class="h"') == 2
    assert "<rect" not in svg.replace('<rect class="a"', "")
    assert svg.count('<path class="i"') == 2
    assert ".h{fill:#FFFFFF;stroke:#1F2328;stroke-width:2.5}" in svg
    assert svg.count('<path class="j"') == 2
    assert 'class="h"' not in _render(world, entries, "001", "map1")
    assert 'class="i"' not in _render(world, entries, "001", "map1")
    # One capital: marker, no number.
    one = _render(world, entries, "004", "map2")
    assert one.count('<circle class="h"') == 1 and 'class="i"' not in one


def test_documented_marker_override_does_not_change_capital_data(world_and_entries, by_id):
    world, entries = world_and_entries
    overrides = maps.load_map_overrides()
    assert overrides["098"]["map2_capital_marker"] is False
    assert overrides["098"]["reason"]
    assert by_id["098"]["capitals"][0]["name"]["en"] == "Vatican City"
    # Apply the same setting to a synthetic entry: it hides only markers and numbers.
    entry = entries["001"]
    normal = maps.plan(entry, "map2", world.land["AA"], {}, {})
    hidden = maps.plan(entry, "map2", world.land["AA"], {}, {"001": overrides["098"]})
    for mode, svg in maps.render_modes(hidden, world, PALETTE, entries).items():
        reference = maps.render_modes(normal, world, PALETTE, entries)[mode]
        assert 'class="h"' not in svg and 'class="i"' not in svg and 'class="j"' not in svg
        assert svg.replace("\n", "") == re.sub(r'<(?:circle|path) class="[hij]"[^>]+/>', '', reference).replace("\n", "")
    assert len(entry["capitals"]) == 2


@pytest.mark.parametrize("setting", ['"false"', 'null', '0'])
def test_map_override_requires_a_boolean(tmp_path, setting):
    path = tmp_path / "maps.yaml"
    path.write_text(f"'098':\n  map2_capital_marker: {setting}\n  reason: Größeres Kartenbild\n")
    with pytest.raises(ValueError, match="boolean"):
        maps.load_map_overrides(path)


def test_capital_numbers_follow_field_order(world_and_entries):
    world, entries = world_and_entries
    e = entries["001"]
    spec = maps.plan(e, "map2", world.land["AA"], {})
    markers = maps.capital_markers(e, spec.projection, spec.radius_km, spec.offset)
    assert [n for n, _, _ in markers] == [1, 2]
    # A capital that is not drawn keeps the numbers of the others (field order).
    far = dict(e, capitals=[{"name": {"en": "Groß-Fern"}, "role": "capital", "lat": -60.0, "lon": -120.0}] + e["capitals"])
    assert [n for n, _, _ in maps.capital_markers(far, spec.projection, spec.radius_km, spec.offset)] == [2, 3]


def test_digits_are_the_glyphs_drawn_right_of_the_marker():
    placed = maps.layout_digits([(1, 500.0, 500.0)])
    (n, box), = placed
    w, h = maps.digit_size()
    assert n == 1 and box[0] == pytest.approx(500 + maps.MARKER_R + maps.DIGIT_GAP)
    assert box[1] + h / 2 == pytest.approx(500) and box[2] - box[0] == pytest.approx(w)
    for digit in (1, 2, 3):
        d = maps._digit(digit, box)
        nums = [float(v) for v in re.findall(r"-?[\d.]+", d.split('d="')[1])]
        xs, ys = nums[::2], nums[1::2]
        # The glyph (without stroke) stays inside the ink box minus half the stroke.
        assert min(xs) >= box[0] + maps.DIGIT_STROKE / 2 - 0.1 and max(xs) <= box[2] - maps.DIGIT_STROKE / 2 + 0.1
        assert min(ys) >= box[1] + maps.DIGIT_STROKE / 2 - 0.1 and max(ys) <= box[3] - maps.DIGIT_STROKE / 2 + 0.1


def _clear(box, others) -> bool:
    return all(maps._overlap(box, o) == 0 for o in others)


@pytest.mark.parametrize(
    "markers",
    [
        [(1, 500.0, 500.0), (2, 540.0, 500.0)],  # 2 sits right of 1: 1 flips
        [(1, 990.0, 500.0), (2, 300.0, 300.0)],  # right edge: flips left
        [(1, 500.0, 500.0), (2, 540.0, 500.0), (3, 460.0, 500.0)],  # both sides taken: above
        [(1, 10.0, 10.0), (2, 60.0, 10.0), (3, 10.0, 70.0)],  # corner: below, below, right
    ],
)
def test_digit_layout_avoids_markers_digits_and_edges(markers):
    placed = maps.layout_digits(markers)
    assert [n for n, _ in placed] == [n for n, _, _ in markers]
    r = maps.MARKER_R
    circles = [(x - r, y - r, x + r, y + r) for _, x, y in markers]
    boxes = [b for _, b in placed]
    for i, b in enumerate(boxes):
        assert 0 <= b[0] and b[2] <= 1000 and 0 <= b[1] and b[3] <= 1000, b
        assert _clear(b, circles), (i, b)
        assert _clear(b, boxes[:i] + boxes[i + 1 :]), (i, b)


def test_digit_layout_prefers_the_right_side():
    placed = maps.layout_digits([(1, 500.0, 500.0), (2, 500.0, 700.0)])
    assert all(b[0] > x for (_, b), (_, x, _) in zip(placed, [(1, 500.0, 500.0), (2, 500.0, 700.0)]))


def test_maps_carry_one_palette_per_file(world_and_entries):
    world, entries = world_and_entries
    spec = maps.plan(entries["001"], "map2", world.land["AA"], {})
    out = maps.render_modes(spec, world, PALETTE, entries)
    assert set(out) == {"day", "night"}
    for mode, svg in out.items():
        assert "@media" not in svg and "prefers-color-scheme" not in svg
        assert f".a{{fill:{PALETTE[mode]['sea']}}}" in svg
        assert (
            f".h{{fill:{PALETTE[mode]['marker_fill']};stroke:{PALETTE[mode]['marker_outline']}"
            in svg
        )
    assert all(
        PALETTE[mode]["marker_fill"] == "#FFFFFF"
        and PALETTE[mode]["marker_outline"] == "#1F2328"
        for mode in maps.MODES
    )
    # Same geometry, different style only.
    strip = lambda s: re.sub(r"<style>.*</style>", "", s)  # noqa: E731
    assert strip(out["day"]) == strip(out["night"])


def test_micro_state_gets_highlight_on_map1_only(world_and_entries):
    world, entries = world_and_entries
    assert 'class="g"' in _render(world, entries, "004", "map1")
    assert 'class="g"' not in _render(world, entries, "004", "map2")
    assert 'class="g"' not in _render(world, entries, "001", "map1")


def test_antimeridian_parts_fuse_into_one_ring(world_and_entries):
    world, entries = world_and_entries
    svg = _render(world, entries, "005", "map2")
    d = re.search(r'<path class="f" d="([^"]+)"', svg).group(1)
    assert d.count("M") == 1, "the two halves must be one polygon without a seam"


def test_map2_window_contains_entry_and_capitals(world_and_entries):
    world, entries = world_and_entries
    for cid in entries:
        spec = maps.plan(entries[cid], "map2", world.land[entries[cid]["iso2"]], {})
        cx, cy = spec.offset
        minx, miny, maxx, maxy = geometry.entry_extent(world.land[entries[cid]["iso2"]], spec.projection)
        assert max(abs(minx - cx), abs(maxx - cx), abs(miny - cy), abs(maxy - cy)) <= spec.radius_km
        for cap in entries[cid]["capitals"]:
            x, y = spec.projection.point(cap["lat"], cap["lon"])
            assert abs(x - cx) <= spec.radius_km and abs(y - cy) <= spec.radius_km


def test_map2_margins_are_even(world_and_entries):
    world, entries = world_and_entries
    svg = _render(world, entries, "001", "map2")
    d = re.search(r'<path class="f" d="M(\d+) (\d+)l([^z"]+)z', svg)
    x, y = int(d.group(1)), int(d.group(2))
    xs, ys = [x], [y]
    nums = [int(n) for n in re.findall(r"-?\d+", d.group(3))]
    for i in range(0, len(nums), 2):
        x += nums[i]; y += nums[i + 1]; xs.append(x); ys.append(y)
    assert abs((min(xs) - 0) - (1000 - max(xs))) <= 2
    assert abs((min(ys) - 0) - (1000 - max(ys))) <= 2


def test_core_land_decides_the_window(world_and_entries):
    world, entries = world_and_entries
    e = entries["001"]
    far = MultiPolygon([world.land["AA"], box(40.0, 0.0, 40.1, 0.1)])  # a folded remote base
    wide = maps.plan(e, "map2", far, {})
    core = maps.plan(e, "map2", world.land["AA"], {})
    assert core.radius_km < wide.radius_km / 3


def test_output_is_text_free(world_and_entries):
    world, entries = world_and_entries
    for cid in entries:
        for kind in ("map1", "map2"):
            svg = _render(world, entries, cid, kind)
            assert "Mätzlingen" not in svg and "Groß" not in svg
            for tag in ("<text", "<title", "<desc", "<!--", " id="):
                assert tag not in svg
            words = set(re.findall(r"[A-Za-z]{2,}", re.sub(r"#[0-9A-Fa-f]{3,8}\b", "", svg)))
            assert entries[cid]["iso2"] not in words and entries[cid]["iso3"] not in words


def test_deterministic(world_and_entries):
    world, entries = world_and_entries
    for cid in ("001", "004", "005"):
        assert _render(world, entries, cid, "map1") == _render(world, entries, cid, "map1")
    # A freshly built world gives the same bytes (no dependence on object identity/order).
    world2 = maps.World(dict(reversed(list(world.land.items()))), [], world.eez, world.nm12)
    assert _render(world, entries, "001", "map1") == _render(world2, entries, "001", "map1")


def test_path_writer_integer_grid_and_relative_moves():
    d = maps.path_data(box(0.2, 0.4, 10.6, 5.2))
    assert d == "M11 5l0-5-10 0 0 5z" or re.fullmatch(r"M\d+ \d+l[-\d ]+z", d)
    assert "." not in d


def test_coast_gaps_fill_a_bay_but_not_open_sea():
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    # A U-shaped coast around a bay (x 30..70, y 50..100); the zone reaches into the bay
    # only as a tongue (Marine Regions' coastline lies seaward of Natural Earth's).
    land = box(0, 0, 100, 100).difference(box(30, 50, 70, 100))
    zone = unary_union([box(-10, 100, 110, 140), box(35, 80, 65, 100)])
    gaps = maps.coast_gaps(zone, [land])
    assert unary_union(gaps).area == pytest.approx(40 * 50 - 30 * 20)
    # A hole of the zone away from the land (a high-seas pocket) is not a gap.
    pocket = Polygon(box(-10, 100, 110, 200).exterior, [box(40, 150, 60, 170).exterior.coords])
    gaps = maps.coast_gaps(pocket, [land])
    assert [g.bounds for g in gaps] == [(30, 50, 70, 100)]  # the bay, not the pocket


def test_zone_keeps_the_holes_the_loader_kept(world_and_entries):
    from shapely.geometry import Polygon

    world, entries = world_and_entries
    # The loader only leaves holes that are not land (another zone inside, a pocket).
    enclave = Polygon(box(4.0, -2.0, 7.5, 6.0).exterior, [box(5.0, 1.0, 6.0, 2.0).exterior.coords])
    w = maps.World(world.land, [], {"AAA": [enclave]}, {})
    d = re.search(r'<path class="b" d="([^"]+)"', _render(w, entries, "001", "map1")).group(1)
    assert d.count("M") == 2, "exterior + the kept hole"
    # Without the hole: one ring, nothing punched out by the processing.
    w = maps.World(world.land, [], {"AAA": [Polygon(enclave.exterior)]}, {})
    d = re.search(r'<path class="b" d="([^"]+)"', _render(w, entries, "001", "map1")).group(1)
    assert d.count("M") == 1


# --- highlight circles (issue #25) --------------------------------------------------------
# Synthetic geometry in user units: an atoll is a 2 × 2 box, its EEZ part a larger box.


def _atoll(x, y):
    return box(x, y, x + 2, y + 2)


def _contains(circle, geom, margin=0.0):
    cx, cy, r = circle
    return all(math.hypot(x - cx, y - cy) <= r - margin for x, y in shapely.get_coordinates(geom))


def _clear_of(circle, geom):
    cx, cy, r = circle
    return shapely.Point(cx, cy).buffer(r, quad_segs=64).exterior.distance(geom.boundary) > maps.HIGHLIGHT_CLEAR


def test_highlight_circle_encloses_the_eez_part():
    eez = box(400, 420, 640, 560)
    [c] = maps.highlight_circles([_atoll(500, 480)], eez=eez)
    assert _contains(c, eez, margin=maps.HIGHLIGHT_STROKE / 2)
    assert c[2] == pytest.approx(math.hypot(120, 70) + maps.HIGHLIGHT_MARGIN, abs=0.5)


def test_highlight_groups_in_one_eez_part_share_a_circle():
    eez = box(300, 300, 700, 700)
    islands = [_atoll(350, 350), _atoll(640, 640)]  # far apart: two island groups
    assert len(maps.highlight_circles(islands)) == 2
    [c] = maps.highlight_circles(islands, eez=eez)
    assert _contains(c, eez)


def test_highlight_separate_eez_parts_get_separate_circles_unless_they_overlap():
    a, b = box(100, 100, 200, 200), box(700, 700, 800, 800)
    circles = maps.highlight_circles([_atoll(150, 150), _atoll(750, 750)], eez=shapely.union(a, b))
    assert len(circles) == 2 and _contains(circles[0], a) and _contains(circles[1], b)
    near = box(230, 100, 330, 200)  # circles around a and near would overlap → one circle
    [c] = maps.highlight_circles([_atoll(150, 150), _atoll(280, 150)], eez=shapely.union(a, near))
    assert _contains(c, a) and _contains(c, near)


def test_highlight_falls_back_to_islands_when_the_eez_is_clipped_or_too_large():
    island = [_atoll(500, 500)]
    plain = maps.highlight_circles(island)
    assert plain == [(501.0, 501.0, maps.HIGHLIGHT_R)]
    clipped = box(0, 300, 700, 700)  # runs into the window edge
    assert maps.highlight_circles(island, eez=clipped) == plain
    huge = box(80, 80, 920, 920)  # inside the window, but r ≈ 594 > 0.45 × SIZE
    assert maps.highlight_circles(island, eez=huge) == plain


def test_highlight_fallback_grows_until_no_12nm_line_touches_it():
    # The EEZ is clipped, so the island circle (r = 45) is the start; it would cut the 12 nm
    # outline of its own atoll (half side 35) and touch the one of a neighbour atoll.
    eez = box(0, 0, 1000, 1000)
    islands = [_atoll(499, 499), _atoll(579, 499)]
    nm12 = shapely.union(box(465, 465, 535, 535), box(545, 465, 615, 535))
    circles = maps.highlight_circles(islands, eez=eez, nm12=nm12)
    assert len(circles) == 1
    assert _clear_of(circles[0], nm12) and _contains(circles[0], nm12)


def test_highlight_eez_circle_joins_a_12nm_part_that_leaves_the_eez():
    eez = box(400, 400, 600, 600)
    nm12 = box(590, 490, 640, 510)  # sticks out of the EEZ part
    [c] = maps.highlight_circles([_atoll(500, 500)], eez=eez, nm12=shapely.union(nm12, _atoll(500, 500)))
    assert _contains(c, eez) and _contains(c, nm12)
    assert _clear_of(c, nm12)


def test_highlight_landlocked_micro_state_is_unchanged():
    assert maps.highlight_circles([box(500, 500, 501, 501)]) == [(500.5, 500.5, maps.HIGHLIGHT_R)]
    assert maps.highlight_circles([box(0, 0, 100, 100)]) == []  # large enough, no circle
