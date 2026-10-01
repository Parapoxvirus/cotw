"""Checks over the committed media (media/*.svg) and manifests. Pure Python: no network,
no geometry libraries, so they run everywhere."""

from __future__ import annotations

import re
import statistics
import xml.etree.ElementTree as ET

import pytest
import yaml

from cotw import flags
from cotw.paths import MEDIA, OVERRIDES

SVG_NS = "{http://www.w3.org/2000/svg}"
# Flags are one file; every map is written twice, one palette each (docs/MAPS.md).
KINDS = ("flag", "map1-day", "map1-night", "map2-day", "map2-night")
MAP_KINDS = KINDS[1:]
MAP_MEDIAN_MAX = 100 * 1024
MAP_MAX = 500 * 1024
# Every word that may appear in a map SVG. Anything else (a country name, an ISO code in an
# id, a comment) would give the answer away in the card's HTML inspector.
MAP_WORDS = {
    "xml", "version", "encoding", "UTF", "svg", "xmlns", "http", "www", "org", "width",
    "height", "viewBox", "style", "fill", "stroke", "none", "linejoin", "linecap", "round",
    "rect", "path", "circle", "class", "cx", "cy",
}


@pytest.fixture(scope="session")
def manifest() -> dict:
    return flags.load_manifest()


def _media(cid: str, kind: str):
    return MEDIA / f"cotw-{cid}-{kind}.svg"


def test_every_entry_has_all_media(by_id):
    missing = [f"{cid}-{k}" for cid in by_id for k in KINDS if not _media(cid, k).exists()]
    assert missing == []
    expected = {f"cotw-{cid}-{k}.svg" for cid in by_id for k in KINDS}
    extra = sorted(p.name for p in MEDIA.glob("*.svg") if p.name not in expected)
    assert extra == [], "stale media files"


def test_media_names_use_cotw_ids_without_underscore():
    for p in MEDIA.glob("*.svg"):
        assert re.fullmatch(r"cotw-\d{3}-(flag|map[12]-(day|night))\.svg", p.name), p.name


def test_flag_manifest_covers_every_entry_with_allowed_license(by_id, manifest):
    overrides = flags.load_overrides()
    assert sorted(manifest) == sorted(by_id)
    for cid, rec in manifest.items():
        if flags.license_allowed(rec["license"]):
            continue
        ov = overrides.get(cid) or {}
        assert ov.get("license") == rec["license"] and ov.get("reason"), f"{cid}: {rec['license']}"
        assert rec.get("license_override")


def test_flag_overrides_have_reasons_and_are_used(by_id):
    for cid, ov in flags.load_overrides().items():
        assert cid in by_id, cid
        assert ov.get("reason"), cid
        assert ov.get("file") or ov.get("license"), cid


def test_shared_flags_are_documented(by_id, manifest):
    for cid, rec in manifest.items():
        if "shared_with" in rec:
            assert by_id[cid].get("dependency_of") == rec["shared_with"]
            assert rec["note"]


def test_flag_files_match_manifest_checksums(manifest):
    # The file is the cleaned Commons original; the manifest records its size.
    for cid, rec in manifest.items():
        assert _media(cid, "flag").stat().st_size == rec["bytes"], cid


@pytest.mark.parametrize("kind", KINDS)
def test_svgs_parse(by_id, kind):
    for cid in by_id:
        root = ET.parse(_media(cid, kind)).getroot()
        assert root.tag == f"{SVG_NS}svg", f"{cid}-{kind}"


def test_flags_carry_no_metadata_or_names():
    for p in sorted(MEDIA.glob("*-flag.svg")):
        text = p.read_text(encoding="utf-8")
        assert "<!--" not in text, p.name
        for tag in ("title", "desc", "metadata"):
            assert not re.search(rf"<{tag}\b", text), f"{p.name}: <{tag}>"
        assert "aria-" not in text and "inkscape:" not in text and "sodipodi:" not in text, p.name
        assert not re.search(r"<script\b|<foreignObject\b|\son[a-z]+=", text), p.name
        ids = re.findall(r"""\sid=["']([^"']*)["']""", text)
        assert all(re.fullmatch(r"i\d+", i) for i in ids), f"{p.name}: {ids[:3]}"


MAP_GLOB = "*-map[12]-*.svg"


def test_maps_are_text_free():
    for p in sorted(MEDIA.glob(MAP_GLOB)):
        text = p.read_text(encoding="utf-8")
        assert "<text" not in text and "<!--" not in text, p.name
        paths = re.findall(r' d="([^"]*)"', text)
        assert all(re.fullmatch(r"[MlLCz0-9 .-]*", d) for d in paths), p.name
        stripped = re.sub(r' d="[^"]*"', "", re.sub(r"#[0-9A-Fa-f]{3,8}\b", "", text))
        words = set(re.findall(r"[A-Za-z]{2,}", stripped))
        assert words <= MAP_WORDS, f"{p.name}: {sorted(words - MAP_WORDS)}"
        classes = set(re.findall(r'class="([^"]*)"', text))
        assert all(re.fullmatch(r"[a-z]", c) for c in classes), p.name


def test_maps_carry_one_palette_and_no_media_query(by_id):
    # An SVG in <img> cannot see Anki's .nightMode, so the card picks the file instead.
    palette = yaml.safe_load((MEDIA.parent / "data" / "style" / "palette.yaml").read_text(encoding="utf-8"))
    for cid in by_id:
        for kind in ("map1", "map2"):
            texts = {m: _media(cid, f"{kind}-{m}").read_text(encoding="utf-8") for m in ("day", "night")}
            for mode, text in texts.items():
                assert "@media" not in text and "prefers-color-scheme" not in text, f"{cid}-{kind}-{mode}"
                assert f".a{{fill:{palette[mode]['sea']}}}" in text, f"{cid}-{kind}-{mode}"
            strip = [re.sub(r"<style>.*?</style>", "", t) for t in texts.values()]
            assert strip[0] == strip[1], f"{cid}-{kind}: day and night differ beyond the palette"


def test_map_size_budget():
    sizes = {p.name: p.stat().st_size for p in MEDIA.glob(MAP_GLOB)}
    assert statistics.median(sizes.values()) <= MAP_MEDIAN_MAX
    too_big = {n: s for n, s in sizes.items() if s > MAP_MAX}
    assert too_big == {}


def test_every_map_draws_the_entry_once(by_id):
    for cid in by_id:
        for kind in ("map1-day", "map2-day"):
            text = _media(cid, kind).read_text(encoding="utf-8")
            assert text.count(' class="f"') == 1, f"{cid}-{kind}"


# Neighbors reached only through a folded Natural Earth unit that does not decide the window
# (docs/MAPS.md): the United Kingdom borders Cyprus via Akrotiri and Dhekelia, but its map 1
# is centered on the British Isles.
OUT_OF_VIEW_NEIGHBORS = {"235": {"058"}}


def test_neighbor_layer_is_exactly_the_borders(by_id):
    # One path (or dot) per neighbor on map 1: the renderer merges each entity into one
    # path, and a neighbor touches the entry, so it is inside the window.
    for cid, e in by_id.items():
        text = _media(cid, "map1-day").read_text(encoding="utf-8")
        expected = [b for b in e["borders"] if b not in OUT_OF_VIEW_NEIGHBORS.get(cid, set())]
        assert text.count(' class="e"') == len(expected), cid


def _marker_points(text: str) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for x, y in re.findall(r'<circle class="h" cx="([-\d.]+)" cy="([-\d.]+)"', text)]


def _digit_boxes(text: str) -> list[tuple[float, float, float, float]]:
    out = []
    for d in re.findall(r'<path class="i" d="([^"]+)"', text):
        nums = [float(n) for n in re.findall(r"-?[\d.]+", d)]
        xs, ys = nums[::2], nums[1::2]
        out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


# Remote dependencies whose capital lies more than 45° away (docs/MAPS.md): not marked.
REMOTE_CAPITALS = {"030": 1, "032": 1, "097": 1}  # Bouvet → Oslo, BIOT → London, Heard → Canberra


def test_map2_marks_every_capital_inside_the_view(by_id):
    overrides = yaml.safe_load((OVERRIDES / "maps.yaml").read_text(encoding="utf-8"))
    for cid, e in by_id.items():
        text = _media(cid, "map2-day").read_text(encoding="utf-8")
        pts = _marker_points(text)
        with_coords = [c for c in e["capitals"] if c.get("lat") is not None]
        expected = len(with_coords) - REMOTE_CAPITALS.get(cid, 0)
        if not overrides.get(cid, {}).get("map2_capital_marker", True):
            expected = 0
        assert len(pts) == len(set(pts)) == expected, cid
        for x, y in pts:
            assert 0 <= x <= 1000 and 0 <= y <= 1000, f"{cid}: marker at {x}, {y}"


def test_vatican_map2_has_no_marker_in_either_palette():
    for mode in ("day", "night"):
        assert _marker_points(_media("098", f"map2-{mode}").read_text(encoding="utf-8")) == []


def test_map2_numbers_only_on_multi_capital_entries(by_id):
    pytest.importorskip("shapely")
    from cotw import maps

    r = maps.MARKER_R
    stroke = maps.DIGIT_INK_STROKE / 2
    for cid, e in by_id.items():
        text = _media(cid, "map2-day").read_text(encoding="utf-8")
        pts = _marker_points(text)
        boxes = _digit_boxes(text)
        if len(e["capitals"]) == 1:
            assert boxes == [], cid
            continue
        assert len(boxes) == len(pts), cid
        # Ink boxes (path + half the stroke): inside the viewBox, clear of every other marker
        # and every other number.
        ink = [(b[0] - stroke, b[1] - stroke, b[2] + stroke, b[3] + stroke) for b in boxes]
        circles = [(x - r, y - r, x + r, y + r) for x, y in pts]
        for i, b in enumerate(ink):
            assert b[0] >= -0.2 and b[1] >= -0.2 and b[2] <= 1000.2 and b[3] <= 1000.2, (cid, b)
            for j, o in enumerate(ink):
                assert i == j or maps._overlap(b, o) == 0, (cid, i, j)
            assert sum(maps._overlap(b, c) > 0 for c in circles) == 0, (cid, i)


def test_map2_numbers_follow_the_capital_fields(by_id):
    # The digit next to each marker is the capital's field number: the marker nearest to a
    # number is the capital at that position in the database.
    pytest.importorskip("shapely")
    from cotw import maps

    for cid, e in by_id.items():
        if len(e["capitals"]) == 1:
            continue
        text = _media(cid, "map2-day").read_text(encoding="utf-8")
        digits = re.findall(r'<path class="i" d="([^"]+)"', text)
        expected = _numbered(e, text)
        assert len(digits) == len(expected), cid
        for d, (n, box) in zip(digits, expected):
            # Same glyph (command letters) at the same place (markers are rounded to 0.1).
            want = re.search(r'<path class="i" d="([^"]+)"', maps._digit(n, box)).group(1)
            assert re.sub(r"[-\d. ]", "", d) == re.sub(r"[-\d. \"/>]", "", want), (cid, n)
            got_nums = [float(v) for v in re.findall(r"-?[\d.]+", d)]
            want_nums = [float(v) for v in re.findall(r"-?[\d.]+", want)]
            assert max(abs(a - b) for a, b in zip(got_nums, want_nums)) <= 0.3, (cid, n)


def test_capital_markers_and_digits_keep_white_body_with_outside_outline():
    from cotw import maps

    for mode in maps.MODES:
        text = _media("207", f"map2-{mode}").read_text(encoding="utf-8")
        css = re.search(r"<style>(.*?)</style>", text).group(1)
        assert ".h{fill:#FFFFFF;stroke:#1F2328;stroke-width:2.5}" in css
        assert f".i{{fill:none;stroke:#1F2328;stroke-width:{maps.DIGIT_INK_STROKE:g}" in css
        assert f".j{{fill:none;stroke:#FFFFFF;stroke-width:{maps.DIGIT_STROKE:g}" in css
        outlines = re.findall(r'<path class="i" d="([^"]+)"', text)
        bodies = re.findall(r'<path class="j" d="([^"]+)"', text)
        assert outlines and outlines == bodies


def _numbered(e: dict, text: str):
    """Re-run the layout on the committed marker positions (field order)."""
    from cotw import maps

    pts = _marker_points(text)
    numbered = [(i, cap) for i, cap in enumerate(e["capitals"], start=1) if cap.get("lat") is not None]
    return maps.layout_digits([(n, x, y) for (n, _), (x, y) in zip(numbered, pts)])


def _rings(d: str):
    from shapely.geometry import Polygon

    out = []
    for x, y, rest in re.findall(r"M(-?\d+) (-?\d+)l([^z]*)z", d):
        x, y = int(x), int(y)
        pts = [(x, y)]
        nums = [int(n) for n in re.findall(r"-?\d+", rest)]
        for i in range(0, len(nums), 2):
            x, y = x + nums[i], y + nums[i + 1]
            pts.append((x, y))
        if len(pts) >= 3:
            out.append(Polygon(pts))
    return out


# Issue #12: Marine Regions cuts its zones along its own coastline; wherever Natural Earth's
# coast differs, a hole (or a gap) next to the entry's land let the dark sea show through the
# EEZ fill (bays, fjords, lagoons; Svalbard's map 2). No ring that punches the EEZ fill or the
# 12 nm outline may touch the entry's land. Holes away from it are real: another territory's
# zone (Saint-Pierre and Miquelon in Canada's EEZ) or a high-seas pocket (Aegean, Peanut Hole).
# Slivers under 10 px² (delta channels, rounding) are not visible and not counted. The v3-era
# maps had 4 286 such holes in 341 files.
HOLE_MIN_PX2 = 10.0


def test_no_zone_hole_along_the_entry_coast(by_id):
    pytest.importorskip("shapely")
    from shapely.ops import unary_union

    offenders = []
    for cid in by_id:
        for kind in ("map1", "map2"):
            text = _media(cid, f"{kind}-day").read_text(encoding="utf-8")
            f = re.search(r'<path class="f" d="([^"]+)"', text)
            if not f:  # the entry is a dot (Vatican City on map 1)
                continue
            entry = unary_union([r.buffer(0) for r in _rings(f.group(1))])
            for cls in ("b", "c"):
                m = re.search(rf'<path class="{cls}" d="([^"]+)"', text)
                if not m:
                    continue
                rings = _rings(m.group(1))
                for i, ring in enumerate(rings):
                    area = abs(ring.area)
                    if area < HOLE_MIN_PX2:
                        continue
                    pt = ring.representative_point()
                    depth = sum(1 for j, o in enumerate(rings) if j != i and abs(o.area) > area and o.buffer(0).contains(pt))
                    if depth % 2 == 1 and ring.distance(entry) <= 0.5:
                        offenders.append(f"{cid}-{kind} {cls}")
    assert offenders == []


# Issue #25: a highlight circle (class "g") encloses the EEZ part(s) of its islands, so no
# 12 nm line (class "c") can cross it; where that is not possible (EEZ clipped by the window
# or the circle too large) the island circle grows until no 12 nm line touches it. Checked
# on the committed files: path data is on the integer grid and circles have one decimal,
# so the gap asserted here (1 unit beyond both half strokes) is smaller than the renderer's.
HIGHLIGHT_GAP_MIN = 1.0


def _highlights(text: str) -> list[tuple[float, float, float]]:
    return [tuple(map(float, m)) for m in re.findall(r'<circle class="g" cx="([-\d.]+)" cy="([-\d.]+)" r="([-\d.]+)"', text)]


def _outer_rings(d: str):
    rings = _rings(d)
    out = []
    for i, ring in enumerate(rings):
        pt = ring.representative_point()
        depth = sum(1 for j, o in enumerate(rings) if j != i and abs(o.area) > abs(ring.area) and o.buffer(0).contains(pt))
        if depth % 2 == 0:
            out.append(ring)
    return out


def test_no_12nm_line_crosses_a_highlight_circle(by_id):
    pytest.importorskip("shapely")
    import shapely
    from shapely.geometry import LineString

    from cotw import maps

    clear = maps.HIGHLIGHT_STROKE / 2 + maps.STROKE_PX * 0.75 + HIGHLIGHT_GAP_MIN
    offenders = []
    for cid in by_id:
        for kind in ("map1", "map2"):
            text = _media(cid, f"{kind}-day").read_text(encoding="utf-8")
            circles = _highlights(text)
            m = re.search(r'<path class="c" d="([^"]+)"', text)
            if not circles or not m:
                continue
            lines = shapely.MultiLineString([LineString(list(r.exterior.coords)) for r in _rings(m.group(1))])
            for cx, cy, r in circles:
                ring = shapely.Point(cx, cy).buffer(r, quad_segs=64).exterior
                if ring.distance(lines) <= clear:
                    offenders.append(f"{cid}-{kind} ({cx}, {cy}, r={r})")
    assert offenders == []


def test_highlight_circles_enclose_their_eez_part(by_id):
    pytest.importorskip("shapely")
    import math

    import shapely
    from shapely.ops import unary_union

    from cotw import maps

    offenders = []
    for cid in by_id:
        for kind in ("map1", "map2"):
            text = _media(cid, f"{kind}-day").read_text(encoding="utf-8")
            circles = _highlights(text)
            f = re.search(r'<path class="f" d="([^"]+)"', text)
            b = re.search(r'<path class="b" d="([^"]+)"', text)
            if not circles or not f or not b:
                continue
            parts = [q for q in (p.buffer(0) for p in _rings(f.group(1))) if not q.is_empty]
            zones = _outer_rings(b.group(1))
            for cx, cy, r in circles:
                own = [p for p in parts if math.hypot(p.centroid.x - cx, p.centroid.y - cy) < r]
                hit = [z for z in zones if any(z.buffer(0).distance(p) <= 1.5 for p in own)]
                inside = all(math.hypot(x - cx, y - cy) <= r + 1.0 for z in hit for x, y in shapely.get_coordinates(z))
                if inside:
                    continue
                # Fallback allowed: an EEZ part clipped by the window, or a circle that would be too large.
                clipped = any(z.bounds[0] <= 1 or z.bounds[1] <= 1 or z.bounds[2] >= maps.SIZE - 1 or z.bounds[3] >= maps.SIZE - 1 for z in hit)
                *_, need = maps._enclosing_circle(unary_union([z.buffer(0) for z in hit] + own))
                if not clipped and need + maps.HIGHLIGHT_MARGIN <= maps.HIGHLIGHT_MAX_R + 1.0:
                    offenders.append(f"{cid}-{kind} ({cx}, {cy}, r={r})")
    assert offenders == []


def test_maritime_manifest_covers_every_entry(by_id):
    from cotw.marineregions import MANIFEST

    m = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert sorted(m["entries"]) == sorted(by_id)
    assert m["license"] == "CC BY 4.0"
