"""SVG maps per entry (DECISIONS.md C10–C13).

``python -m cotw build-maps`` renders ``media/cotw-<id>-map1-<mode>.svg`` (orientation:
region around the entry) and ``media/cotw-<id>-map2-<mode>.svg`` (capital: entry plus
margin, capitals marked and numbered) for every entry, from Natural Earth 10m map units and
Marine Regions in the cache. ``<mode>`` is ``day`` or ``night``: one file per palette,
without a media query, because an SVG inside ``<img>`` cannot see Anki's ``.nightMode``
class; the card CSS shows the right one (docs/MAPS.md). Output is text-free (no ``<text>``,
``<title>``, ``<desc>``, no names or ISO codes in ids/classes; the capital numbers are
paths) and deterministic (same input → identical bytes).

Layers, bottom to top: sea · EEZ fill · 12 nm outline · other land · neighbors · entry ·
highlight circle · capital markers · capital numbers.
"""

from __future__ import annotations

import html
import math
from pathlib import Path

import shapely
import yaml
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from . import geometry, languages, marineregions, naturalearth
from .paths import BUILD, MEDIA, OVERRIDES, STYLE

PALETTE_FILE = STYLE / "palette.yaml"
CENTERS_FILE = OVERRIDES / "centers.yaml"
MAP_OVERRIDES_FILE = OVERRIDES / "maps.yaml"
SIZE = 1000  # viewBox side, user units
STROKE_PX = 0.6  # land outline width in user units
SIMPLIFY_PX = 0.8  # topology-preserving simplification tolerance, user units
COORD_DECIMALS = 1  # precision of marker/circle attributes; path data is written on the integer grid
MIN_AREA_PX2 = 0.6  # other land / neighbor parts below this area (user units²) are dropped
MARKER_R = 11.0  # capital marker radius, user units
MARKER_STROKE = 2.5  # anthracite outline, centered on the circle edge
# Capital numbers (entries with several capitals): glyph height, white body stroke and
# anthracite outline in user units, plus the gap between marker and digit ink. The outline
# path sits underneath the body path, so the outline grows outward instead of eating the
# white digit.
DIGIT_H = 21.6
DIGIT_STROKE = 4.4
DIGIT_OUTLINE = 2.5
DIGIT_INK_STROKE = DIGIT_STROKE + 2 * DIGIT_OUTLINE
DIGIT_GAP = 6.0
HIGHLIGHT_R = 45.0  # minimum highlight circle radius, user units
# The entry gets highlight circles when its visible land covers less than this many user
# units² (≈ a 12 × 12 px square on a 1000 px map): micro-states on map 1, scattered islands
# on both maps.
HIGHLIGHT_AREA_PX2 = 150.0
HIGHLIGHT_STROKE = 4.0  # highlight circle stroke width, user units
# Clear space between a highlight circle's centerline and any 12 nm line: half the circle's
# stroke, half the 12 nm stroke and a visible gap. EEZ-based circles keep a slightly larger
# margin around their EEZ part (so a 12 nm line inside it is clear too).
HIGHLIGHT_CLEAR = HIGHLIGHT_STROKE / 2 + STROKE_PX * 0.75 + 3.0
HIGHLIGHT_MARGIN = HIGHLIGHT_CLEAR + 1.0
# An EEZ-based circle larger than this falls back to the island circle (a wide view would be
# mostly circle).
HIGHLIGHT_MAX_R = 0.45 * SIZE
COAST_GAP_PX = 0.5  # a hole of (zone ∪ entry land) this close to the entry's land is a coast gap
DOT_R = 2.0  # entry/neighbor that collapses below one pixel is drawn as a dot this size
SNAP_KM = 1e-4  # grid used to fuse antimeridian seams

# CSS class per layer; single letters so nothing readable ends up in the file.
CLASSES = {
    "sea": "a",
    "eez": "b",
    "territorial": "c",
    "land": "d",
    "neighbor": "e",
    "entry": "f",
    "highlight": "g",
    "marker": "h",
    "digit": "i",
    "digit_fill": "j",
}
MODES = ("day", "night")
# Digits 1–3 as stroked paths on a 10 × 16 box (x right, y down, 0 0 = top left), so no
# font and no ``<text>`` is needed. Stroked with round caps and joins at DIGIT_STROKE.
GLYPH_W, GLYPH_H = 10.0, 16.0
GLYPHS = {
    1: [("M", 1.8, 3.2), ("L", 5.6, 0), ("L", 5.6, 16)],
    2: [("M", 0.6, 4.2), ("C", 0.6, 1.6, 2.6, 0, 5.1, 0), ("C", 7.7, 0, 9.5, 1.6, 9.5, 4),
        ("C", 9.5, 6.2, 8.2, 7.6, 6.4, 9.3), ("L", 0.6, 16), ("L", 9.8, 16)],
    3: [("M", 0.8, 2.3), ("C", 1.7, 0.8, 3.2, 0, 5, 0), ("C", 7.6, 0, 9.2, 1.5, 9.2, 3.9),
        ("C", 9.2, 6.2, 7.4, 7.5, 4.6, 7.5), ("C", 7.8, 7.5, 9.7, 9.1, 9.7, 11.8),
        ("C", 9.7, 14.4, 7.7, 16, 4.9, 16), ("C", 2.9, 16, 1.3, 15.2, 0.4, 13.8)],
}


def load_palette(path: Path = PALETTE_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_centers(path: Path = CENTERS_FILE) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_map_overrides(path: Path = MAP_OVERRIDES_FILE) -> dict:
    overrides = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for cid, override in overrides.items():
        if not isinstance(cid, str) or not isinstance(override, dict):
            raise ValueError("Map overrides must map COTW IDs to settings")
        if set(override) != {"map2_capital_marker", "reason"} or type(override["map2_capital_marker"]) is not bool:
            raise ValueError(f"{cid}: map2_capital_marker must be a boolean with a reason")
        if not isinstance(override["reason"], str) or not override["reason"].strip():
            raise ValueError(f"{cid}: map override needs a reason")
    return overrides


# --- world data ---------------------------------------------------------------------------


class World:
    """Everything the renderer needs, loaded once: land geometry per entry (lon/lat), the
    ignored Natural Earth units (drawn as other land) and the maritime zones per ISO3."""

    def __init__(self, land: dict[str, object], other: list[object], eez: dict[str, list], nm12: dict[str, list], core: dict[str, object] | None = None):
        self.land = land  # iso2 → (Multi)Polygon
        # Land that decides center and window: the entry's own map units, without units folded
        # in by naturalearth.FOLD_UNITS (the UK's Cyprus bases would otherwise stretch the
        # UK's map 2 across Europe). Falls back to ``land``.
        self.core = core or {}
        self.other = other  # [(Multi)Polygon]
        self.eez = eez  # iso3 → [Polygon]
        self.nm12 = nm12
        self._parts: list[tuple[str | None, Polygon]] = []
        for iso, geom in sorted(land.items()):
            self._parts += [(iso, p) for p in geometry.polygons(geom)]
        for geom in other:
            self._parts += [(None, p) for p in geometry.polygons(geom)]
        self._tree = STRtree([p for _, p in self._parts])

    @classmethod
    def load(cls, entries: dict) -> "World":
        iso2 = {e["iso2"] for e in entries.values()}
        units = naturalearth._load_units(naturalearth.download())
        grouped, ignored = naturalearth.assign_units(units, iso2)
        land = {iso: unary_union([u["geom"] for u in parts]).buffer(0) for iso, parts in grouped.items()}
        core = {}
        for iso, parts in grouped.items():
            own = [u["geom"] for u in parts if u["gu_a3"] not in naturalearth.FOLD_UNITS]
            if own and len(own) < len(parts):
                core[iso] = unary_union(own).buffer(0)
        other = [u["geom"].buffer(0) for u in ignored]
        polys = [p for u in units for p in geometry.polygons(u["geom"])]
        maritime = marineregions.load_geometry({e["iso3"] for e in entries.values()}, land=polys)
        eez = {iso: [r["geom"] for r in a["eez"]] for iso, a in maritime["assigned"].items()}
        nm12 = {iso: [r["geom"] for r in a["nm12"]] for iso, a in maritime["assigned"].items()}
        return cls(land, other, eez, nm12, core)

    def candidates(self, bbox) -> list[tuple[str | None, Polygon]]:
        if bbox is None:
            return list(self._parts)
        idx = self._tree.query(shapely.box(*bbox))
        return [self._parts[i] for i in sorted(idx)]


# --- rendering -----------------------------------------------------------------------------


def _fmt(v: float) -> str:
    s = f"{v:.{COORD_DECIMALS}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def _to_units(geom, radius_km: float, offset=(0.0, 0.0)):
    """Projected km → SVG user units: ``x' = (x - cx + r) / (2r) × SIZE``, y flipped."""
    k = SIZE / (2.0 * radius_km)
    cx, cy = offset
    return shapely.affinity.affine_transform(geom, [k, 0, 0, -k, SIZE / 2.0 - k * cx, SIZE / 2.0 + k * cy])


def _num(v: int) -> str:
    return str(v)


def _ring_path(coords) -> str:
    """One closed subpath on the integer grid, relative moves (``M x y l dx dy … z``).
    Zero-length steps are skipped; rings with fewer than three distinct points are dropped."""
    pts: list[tuple[int, int]] = []
    for x, y in coords:
        q = (int(round(x)), int(round(y)))
        if not pts or q != pts[-1]:
            pts.append(q)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return ""
    out = [f"M{pts[0][0]} {pts[0][1]}l"]
    px, py = pts[0]
    for x, y in pts[1:]:
        dx, dy = x - px, y - py
        out.append(f"{dx}{'' if dy < 0 else ' '}{dy}")
        px, py = x, y
    # Numbers are separated by a space unless the next one starts with a minus sign.
    body = ""
    for i, tok in enumerate(out[1:]):
        body += tok if (i == 0 or tok.startswith("-")) else " " + tok
    return out[0] + body + "z"


def path_data(geom) -> str:
    parts = []
    for p in geometry.polygons(geom):
        parts.append(_ring_path(list(p.exterior.coords)))
        for ring in p.interiors:
            parts.append(_ring_path(list(ring.coords)))
    return "".join(x for x in parts if x)


def _drop_specks(geom, keep: bool):
    """Islands smaller than a pixel add bytes but no ink. The entry itself keeps everything."""
    if keep:
        return geom
    parts = [p for p in geometry.polygons(geom) if p.area >= MIN_AREA_PX2]
    return MultiPolygon(parts) if parts else Polygon()


def _marker(x: float, y: float, r: float = MARKER_R) -> str:
    """Every capital gets the same white circle with an anthracite outline."""
    return f'<circle class="{CLASSES["marker"]}" cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(r)}"/>'


def digit_size() -> tuple[float, float]:
    """Ink box of one digit (glyph plus stroke), user units."""
    k = DIGIT_H / GLYPH_H
    return GLYPH_W * k + DIGIT_INK_STROKE, DIGIT_H + DIGIT_INK_STROKE


def _digit(n: int, box: tuple[float, float, float, float]) -> str:
    """Digit ``n`` as an outline path under an identical white body path.

    The anthracite path is wider by twice ``DIGIT_OUTLINE``. This is the SVG equivalent
    of an outside-aligned stroke for an open glyph: the complete white body stays visible.
    """
    k = DIGIT_H / GLYPH_H
    ox, oy = box[0] + DIGIT_INK_STROKE / 2.0, box[1] + DIGIT_INK_STROKE / 2.0
    d = "".join(
        cmd + " ".join(f"{_fmt(ox + k * a)} {_fmt(oy + k * b)}" for a, b in zip(nums[::2], nums[1::2]))
        for cmd, *nums in GLYPHS[n]
    )
    return (
        f'<path class="{CLASSES["digit"]}" d="{d}"/>'
        f'<path class="{CLASSES["digit_fill"]}" d="{d}"/>'
    )


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _outside(box, size: float = SIZE) -> float:
    """Area of ``box`` outside the viewBox."""
    w, h = box[2] - box[0], box[3] - box[1]
    return w * h - _overlap(box, (0.0, 0.0, size, size))


def _clamp_box(box, size: float = SIZE):
    """Translate ``box`` into the viewBox without changing its dimensions."""
    x0, y0, x1, y1 = box
    if x0 < 0:
        x1 -= x0
        x0 = 0.0
    elif x1 > size:
        x0 -= x1 - size
        x1 = size
    if y0 < 0:
        y1 -= y0
        y0 = 0.0
    elif y1 > size:
        y0 -= y1 - size
        y1 = size
    return x0, y0, x1, y1


def layout_digits(markers: list[tuple[int, float, float]], r: float = MARKER_R, size: float = SIZE) -> list[tuple[int, tuple]]:
    """Place the number next to each marker: to the right by default; to the left, above or
    below when the right side would overlap another marker or an already placed number, or
    leave the viewBox. When every side collides, the side with the least overlap wins (in
    that order on ties). ``markers`` = ``[(number, x, y)]``; returns ``[(number, box)]``."""
    w, h = digit_size()
    g = r + DIGIT_GAP
    obstacles = [(x - r, y - r, x + r, y + r) for _, x, y in markers]
    placed: list[tuple[int, tuple]] = []
    for n, x, y in markers:
        options = tuple(map(_clamp_box, (
            (x + g, y - h / 2, x + g + w, y + h / 2),  # right
            (x - g - w, y - h / 2, x - g, y + h / 2),  # left
            (x - w / 2, y - g - h, x + w / 2, y - g),  # above
            (x - w / 2, y + g, x + w / 2, y + g + h),  # below
        )))
        def cost(box) -> float:
            hit = sum(_overlap(box, o) for o in obstacles) + sum(_overlap(box, b) for _, b in placed)
            return hit + _outside(box, size)

        best = min(options, key=cost)  # min() keeps the first of equal costs
        placed.append((n, best))
    return placed


def stylesheet(p: dict) -> str:
    """CSS for one palette (``palette[mode]``); each file carries exactly one."""
    c = CLASSES
    return (
        f".{c['sea']}{{fill:{p['sea']}}}"
        f".{c['eez']}{{fill:{p['eez']}}}"
        f".{c['territorial']}{{fill:none;stroke:{p['territorial']};stroke-width:{STROKE_PX * 1.5:g}}}"
        f".{c['land']}{{fill:{p['land']};stroke:{p['coast']};stroke-width:{STROKE_PX:g};stroke-linejoin:round}}"
        f".{c['neighbor']}{{fill:{p['neighbor']};stroke:{p['coast']};stroke-width:{STROKE_PX:g};stroke-linejoin:round}}"
        f".{c['entry']}{{fill:{p['entry']};stroke:{p['coast']};stroke-width:{STROKE_PX:g};stroke-linejoin:round}}"
        f".{c['highlight']}{{fill:none;stroke:{p['highlight']};stroke-width:{HIGHLIGHT_STROKE:g}}}"
        f".{c['marker']}{{fill:{p['marker_fill']};stroke:{p['marker_outline']};stroke-width:{MARKER_STROKE:g}}}"
        f".{c['digit']}{{fill:none;stroke:{p['marker_outline']};stroke-width:{DIGIT_INK_STROKE:g};stroke-linecap:round;stroke-linejoin:round}}"
        f".{c['digit_fill']}{{fill:none;stroke:{p['marker_fill']};stroke-width:{DIGIT_STROKE:g};stroke-linecap:round;stroke-linejoin:round}}"
    )


class MapSpec:
    """Everything decided about one map before drawing (also used by tests/preview)."""

    def __init__(self, entry: dict, kind: str, projection: geometry.Projection, radius_km: float, offset=(0.0, 0.0), capital_marker=True):
        self.entry, self.kind, self.projection, self.radius_km = entry, kind, projection, radius_km
        self.offset = offset  # window center in projected km
        self.capital_marker = capital_marker


def visible_capitals(entry: dict, projection: geometry.Projection) -> list[dict]:
    """Capitals with coordinates within ``MAP2_OUTLIER_DEG`` of the map center. Capitals of
    remote dependencies that lie far outside the entry (Oslo for Bouvet Island, London for
    the British Indian Ocean Territory, Canberra for Heard Island) are not drawn: they would
    turn map 2 into a world map."""
    return [
        cap
        for cap in entry.get("capitals", [])
        if cap.get("lat") is not None
        and geometry.angular_distance(projection.lat0, projection.lon0, cap["lat"], cap["lon"]) <= geometry.MAP2_OUTLIER_DEG
    ]


def capital_markers(entry: dict, projection: geometry.Projection, radius_km: float, offset=(0.0, 0.0)) -> list[tuple[int, float, float]]:
    """``[(number, x, y)]`` in user units for every visible capital. The number is the
    capital's position in the database, i.e. its *Capital 1–3* field, so it matches the
    card even when another capital is not drawn."""
    visible = visible_capitals(entry, projection)
    out = []
    for n, cap in enumerate(entry.get("capitals", []), start=1):
        if cap in visible:
            x, y = projection.point(cap["lat"], cap["lon"])
            px, py = _to_units(shapely.Point(x, y), radius_km, offset).coords[0]
            out.append((n, px, py))
    return out


def plan(entry: dict, kind: str, land, centers: dict, overrides: dict | None = None) -> MapSpec:
    """Center + window for one map. Map 2 also keeps every visible capital inside."""
    ov = centers.get(entry["id"])
    lat, lon = (ov["lat"], ov["lon"]) if ov else geometry.default_center(land)
    projection = geometry.Projection(lat, lon)
    minx, miny, maxx, maxy = geometry.entry_extent(land, projection)
    if kind == "map2":
        for cap in visible_capitals(entry, projection):
            x, y = projection.point(cap["lat"], cap["lon"])
            minx, miny, maxx, maxy = min(minx, x), min(miny, y), max(maxx, x), max(maxy, y)
    radius, offset = geometry.window((minx, miny, maxx, maxy), kind)
    overrides = load_map_overrides() if overrides is None else overrides
    marker = overrides.get(entry["id"], {}).get("map2_capital_marker", True)
    return MapSpec(entry, kind, projection, radius, offset, capital_marker=marker)


def _fuse(parts: list[Polygon]) -> list[Polygon]:
    """Union polygons of one owner after snapping to a 10 cm grid. Parts that were split
    at the antimeridian in the source data project onto (almost) the same seam; snapping
    makes the seam vertices identical so the union dissolves it instead of leaving a
    hairline that the coast stroke would draw."""
    snapped = [shapely.set_precision(p, SNAP_KM) for p in parts]
    return geometry.polygons(unary_union([g for g in snapped if not g.is_empty]))


def coast_gaps(zone, entry_land: list, touch: float = COAST_GAP_PX) -> list[Polygon]:
    """Holes of (zone ∪ entry land) that touch the entry's land. Marine Regions draws its
    zones up to its own coastline; the land on the map is Natural Earth's. In bays and
    fjords the two differ, and the sea between them would show as dark patches in the EEZ
    fill (and as stray loops in the 12 nm outline) where a bay opens between the zone's
    edge and the coast. Those gaps are enclosed by the zone and the entry's land, so
    filling them is safe: the land is painted on top. ``touch`` = how close a hole must come
    to the land, in the geometry's units (the globe works in degrees)."""
    land = unary_union(entry_land)
    gaps = []
    for p in geometry.polygons(unary_union([zone, land])):
        for ring in p.interiors:
            hole = Polygon(ring)
            if hole.distance(land) <= touch:
                gaps.append(hole)
    return gaps


def highlight_circles(entry_parts: list[Polygon], eez=None, nm12=None) -> list[tuple[float, float, float]]:
    """Circles (user units) around entry parts that would otherwise be hard to see: when
    the entry's visible area is below ``HIGHLIGHT_AREA_PX2``, parts closer than
    ``HIGHLIGHT_R`` are grouped and each group gets one circle (Kiribati: three island
    groups, three circles).

    A group's circle encloses its islands plus the EEZ part(s) they lie in (``eez`` as
    drawn), so no 12 nm line of the group can cross it. Fallback to the island circle when
    such an EEZ part is clipped by the window or the circle would exceed
    ``HIGHLIGHT_MAX_R``. Then, until nothing changes: overlapping circles merge into one,
    and a 12 nm part (``nm12`` as drawn) whose line comes within ``HIGHLIGHT_CLEAR`` of a
    circle's stroke joins that circle's group. Without an EEZ and 12 nm zone (landlocked
    micro-states) the island circles are all there is."""
    if not entry_parts or sum(p.area for p in entry_parts) >= HIGHLIGHT_AREA_PX2:
        return []
    zones = geometry.polygons(eez) if eez is not None else []
    seas = geometry.polygons(nm12) if nm12 is not None else []
    items = list(entry_parts) + seas
    island_groups = geometry.polygons(unary_union([p.buffer(HIGHLIGHT_R, quad_segs=2) for p in entry_parts]))
    groups = [{i for i, p in enumerate(entry_parts) if p.intersects(g)} for g in island_groups]
    lines = [(len(entry_parts) + k, p.boundary) for k, p in enumerate(seas)]
    while True:
        circles = [_group_circle([items[i] for i in sorted(g)], zones, max(g) >= len(entry_parts)) for g in groups]
        pair = next(
            ((i, j) for i in range(len(groups)) for j in range(i + 1, len(groups))
             if math.hypot(circles[i][0] - circles[j][0], circles[i][1] - circles[j][1]) < circles[i][2] + circles[j][2]),
            None,
        )
        if pair:
            i, j = pair
            groups[i] |= groups.pop(j)
            continue
        grown = False
        for g, (cx, cy, r) in zip(groups, circles):
            ring = shapely.Point(cx, cy).buffer(r, quad_segs=64).exterior
            for k, line in lines:
                if k not in g and ring.distance(line) <= HIGHLIGHT_CLEAR:
                    g.add(k)
                    grown = True
        if not grown:
            return sorted(circles)


def _group_circle(members: list[Polygon], zones: list[Polygon], grown: bool = False) -> tuple[float, float, float]:
    """One highlight circle: around the members and the EEZ parts they lie in. Fallback (no
    EEZ, a part clipped by the window, or too large): the island circle around the members'
    bounding box, or, once 12 nm parts have joined (``grown``), the tightest circle around
    the members, so a zoomed-in map 2 does not end up mostly circle."""
    core = unary_union(members)
    hit = [z for z in zones if z.distance(core) <= 1.0]
    edge = SIZE - 0.5
    clipped = any(minx <= 0.5 or miny <= 0.5 or maxx >= edge or maxy >= edge for minx, miny, maxx, maxy in (z.bounds for z in hit))
    if hit and not clipped:
        cx, cy, r = _enclosing_circle(unary_union([core] + hit))
        if r + HIGHLIGHT_MARGIN <= HIGHLIGHT_MAX_R:
            return (cx, cy, max(HIGHLIGHT_R, r + HIGHLIGHT_MARGIN))
    if grown:
        cx, cy, r = _enclosing_circle(core)
        return (cx, cy, max(HIGHLIGHT_R, r + HIGHLIGHT_MARGIN))
    minx, miny, maxx, maxy = core.bounds
    r = max(HIGHLIGHT_R, math.hypot(maxx - minx, maxy - miny) / 2.0 + HIGHLIGHT_R * 0.5)
    return ((minx + maxx) / 2.0, (miny + maxy) / 2.0, r)


def _enclosing_circle(geom) -> tuple[float, float, float]:
    """Center and radius of the smallest circle around ``geom`` (exact on its vertices)."""
    hull = geom.convex_hull
    center = shapely.minimum_bounding_circle(hull).centroid
    r = max(math.hypot(x - center.x, y - center.y) for x, y in shapely.get_coordinates(hull))
    return center.x, center.y, r


def render(spec: MapSpec, world: World, palette: dict, by_id: dict, mode: str = "day") -> str:
    """One map in one palette (``mode`` = ``day`` or ``night``)."""
    return render_modes(spec, world, palette, by_id)[mode]


def render_modes(spec: MapSpec, world: World, palette: dict, by_id: dict) -> dict[str, str]:
    """``{mode: svg}``: the geometry is computed once, each file gets its palette."""
    entry, proj, r, off = spec.entry, spec.projection, spec.radius_km, spec.offset
    window = geometry.window_box(r, center=off)
    km_per_unit = 2.0 * r / SIZE
    tolerance = SIMPLIFY_PX * km_per_unit
    neighbors = {by_id[b]["iso2"] for b in entry.get("borders", [])}

    # Land: project + clip every candidate polygon, fuse per owner (dissolves antimeridian
    # seams and unit borders inside one entry), then simplify everything together as one
    # coverage so shared borders stay gap-free.
    bbox = geometry.lonlat_bbox(proj, r + math.hypot(*off))
    per_owner: dict[str | None, list[Polygon]] = {}
    for iso, poly in world.candidates(bbox):
        clipped = geometry.project_clip(poly, proj, window)
        if clipped:
            per_owner.setdefault(iso, []).extend(clipped)
    order = sorted(per_owner, key=lambda k: (k is not None, k or ""))
    owners: list[str | None] = []
    fused: list[Polygon] = []
    for iso in order:
        for p in _fuse(per_owner[iso]):
            owners.append(iso)
            fused.append(p)
    simplified = shapely.coverage_simplify(fused, tolerance, simplify_boundary=True) if fused else []
    merged: dict[str | None, list] = {}
    for iso, geom in zip(owners, simplified):
        merged.setdefault(iso, []).append(geom)
    layers = {"land": [], "neighbor": [], "entry": []}
    for iso in order:
        if iso not in merged:
            continue
        keep = iso == entry["iso2"] or iso in neighbors
        geom = _drop_specks(_to_units(unary_union(merged[iso]), r, off), keep=keep)
        if geom.is_empty:
            continue
        key = "entry" if iso == entry["iso2"] else "neighbor" if iso in neighbors else "land"
        layers[key].append(geom)

    # Maritime zones of the entry only. Each part is thinned in lon/lat first with a plain
    # Douglas-Peucker pass (speed: the Russian EEZ alone has 600k vertices), then projected,
    # fused, closed morphologically by one tolerance (seals the hairline seams the thinning
    # can leave at the antimeridian) and simplified. Shells and holes go through this
    # separately: the loader left only the holes that are not land (another zone inside,
    # high-seas pockets; ``marineregions.drop_land_holes``), and those are cut out again at
    # the end. Any other hole the processing leaves is an artifact and is filled.
    tol_deg = tolerance / 111.0

    def zone(polys):
        parts = []
        for p in polys:
            for q in geometry.polygons(p):
                thin = shapely.simplify(q, tol_deg, preserve_topology=False)
                if not thin.is_empty:
                    parts += geometry.project_clip(thin, proj, window)
        if not parts:
            return None
        g = unary_union(_fuse(parts))
        g = g.buffer(tolerance, quad_segs=1, join_style="mitre").buffer(-tolerance, quad_segs=1, join_style="mitre")
        g = _to_units(g.simplify(tolerance, preserve_topology=True), r, off)
        return None if g.is_empty else g

    def shells_and_holes(rows):
        shells = [Polygon(q.exterior) for p in rows for q in geometry.polygons(p)]
        holes = [Polygon(h) for p in rows for q in geometry.polygons(p) for h in q.interiors]
        return zone(shells), zone(holes)

    def finish(shells, holes, with_land: bool):
        if shells is None:
            return None
        land = layers["entry"]
        g = unary_union([shells] + (land if with_land else []))
        if land:
            g = unary_union([g] + coast_gaps(g, land))
        g = unary_union([Polygon(p.exterior) for p in geometry.polygons(g)])
        if holes is not None:
            g = g.difference(holes)
        return None if g.is_empty else g

    eez = finish(*shells_and_holes(world.eez.get(entry["iso3"], [])), with_land=False)
    # 12 nm: the outline of (12 nm ∪ entry land), so only the seaward line shows, not the coast.
    nm12 = finish(*shells_and_holes(world.nm12.get(entry["iso3"], [])), with_land=True)
    if nm12 is not None:
        nm12 = nm12.simplify(SIMPLIFY_PX * 0.5, preserve_topology=True)

    c = CLASSES
    out = [f'<rect class="{c["sea"]}" width="{SIZE}" height="{SIZE}"/>']
    if eez is not None:
        out.append(f'<path class="{c["eez"]}" d="{path_data(eez)}"/>')
    if nm12 is not None:
        out.append(f'<path class="{c["territorial"]}" d="{path_data(nm12)}"/>')
    for key in ("land", "neighbor", "entry"):
        for geom in layers[key]:
            d = path_data(geom)
            if d:
                out.append(f'<path class="{c[key]}" d="{d}"/>')
            elif key != "land":
                # Smaller than a pixel (Vatican City on map 1, Macao on China's map 1): a
                # dot keeps the entity on the map instead of silently dropping it.
                pt = geom.representative_point()
                out.append(f'<circle class="{c[key]}" cx="{_fmt(pt.x)}" cy="{_fmt(pt.y)}" r="{_fmt(DOT_R)}"/>')
    entry_parts = [p for g in layers["entry"] for p in geometry.polygons(g)]
    for cx, cy, cr in highlight_circles(entry_parts, eez, nm12):
        out.append(f'<circle class="{c["highlight"]}" cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(cr)}"/>')
    if spec.kind == "map2" and spec.capital_marker:
        markers = capital_markers(entry, proj, r, off)
        out += [_marker(x, y) for _, x, y in markers]
        if len(entry.get("capitals", [])) > 1:
            out += [_digit(n, box) for n, box in layout_digits(markers)]
    body = "\n".join(out)
    return {
        mode: "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">',
                f"<style>{stylesheet(palette[mode])}</style>",
                body,
                "</svg>",
            ]
        )
        + "\n"
        for mode in MODES
    }


# --- driver ---------------------------------------------------------------------------------


def file_name(cid: str, kind: str, mode: str | None = None) -> str:
    """``cotw-<id>-flag.svg`` (one file), ``cotw-<id>-map1-day.svg`` / ``-night.svg``."""
    return f"cotw-{cid}-{kind}-{mode}.svg" if mode else f"cotw-{cid}-{kind}.svg"


def map_files(cid: str) -> list[str]:
    return [file_name(cid, kind, mode) for kind in ("map1", "map2") for mode in MODES]


def build(entries: dict, ids: list[str] | None = None, media: Path = MEDIA, world: World | None = None, log=print) -> dict:
    """Render map1 + map2 for the given ids (default: all). Returns ``{file: bytes}`` sizes."""
    by_id = entries
    world = world or World.load(entries)
    palette = load_palette()
    centers = load_centers()
    overrides = load_map_overrides()
    media.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for cid in ids or sorted(entries):
        entry = entries[cid]
        land = world.land.get(entry["iso2"])
        if land is None:
            raise RuntimeError(f"{cid} {entry['iso2']}: no Natural Earth geometry")
        for kind in ("map1", "map2"):
            spec = plan(entry, kind, world.core.get(entry["iso2"], land), centers, overrides)
            for mode, svg in render_modes(spec, world, palette, by_id).items():
                target = media / file_name(cid, kind, mode)
                target.write_text(svg, encoding="utf-8")
                sizes[target.name] = len(svg.encode("utf-8"))
            (media / file_name(cid, kind)).unlink(missing_ok=True)  # pre-rc2 single file
        log(f"{cid} {entry['name'][languages.BASE]}: map1 {sizes[file_name(cid, 'map1', 'day')] // 1024} KB, map2 {sizes[file_name(cid, 'map2', 'day')] // 1024} KB")
    return sizes


def write_preview(entries: dict, media: Path = MEDIA, build_dir: Path = BUILD) -> Path:
    """Contact sheet ``build/preview.html`` (not committed): flag, map1, map2 per entry, the
    day files by default, the night files with ``?night=1``."""
    build_dir.mkdir(parents=True, exist_ok=True)
    rel = Path("..") / media.name
    rows = []
    for cid, e in sorted(entries.items()):
        name = html.escape(f"{cid} {e['name'][languages.BASE]} ({e['iso2']})")
        cells = "".join(
            f'<figure><img data-src="{rel}/cotw-{cid}-{k}{"" if k == "flag" else "-@@"}.svg" loading="lazy" alt="">'
            f"<figcaption>{k}</figcaption></figure>"
            for k in ("flag", "map1", "map2")
        )
        rows.append(f'<section><h2>{name}</h2><div class="row">{cells}</div></section>')
    doc = (
        "<!doctype html><meta charset='utf-8'><title>COTW media preview</title>"
        "<style>body{font-family:sans-serif;background:#FBF8F3;color:#222;margin:1rem}"
        "body.night{background:#2C2C2C;color:#eee}"
        "h2{font-size:1rem;margin:.6rem 0 .2rem}.row{display:flex;gap:8px}"
        "figure{margin:0}img{width:300px;height:300px;object-fit:contain;background:#fff3}"
        "figcaption{font-size:.75rem;color:#888;text-align:center}</style>"
        "<h1>COTW media preview</h1><p><a href='?'>day</a> · <a href='?night=1'>night</a></p>"
        + "".join(rows)
        + "<script>var m=new URLSearchParams(location.search).get('night')==='1'?'night':'day';"
        "document.body.classList.toggle('night',m==='night');"
        "document.querySelectorAll('img[data-src]').forEach(function(i){i.src=i.dataset.src.replace('@@',m)});</script>"
    )
    target = build_dir / "preview.html"
    target.write_text(doc, encoding="utf-8")
    return target
