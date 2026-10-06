"""Interactive globe for the card templates (DECISIONS.md B6–B9, C13).

``python -m cotw build-globe`` writes ``media/_cotw-globe.js`` (renderer + L2 TopoJSON, the
coarsest level) and two deferred packets: ``_cotw-globe-zones.js`` (EEZs) and
``_cotw-globe-detail.js`` (fine high-zoom land). The land comes from the same
Natural Earth 10m map units and the same entry join as the SVG maps (``maps.World``), heavily
simplified in one topology-preserving pass (``shapely.coverage_simplify``) so shared
borders stay gap-free. Each entry also carries its own EEZ (Marine Regions, simplified on
its own), its center (same rule as the maps), its initial zoom, its neighbors (exactly
``borders``) and its EN/DE name for the optional tooltip.

The topology is keyed by COTW ID only. Land without an entry (Antarctica, Bir Tawil, …)
is one object ``other``. Output is deterministic: sorted iteration, fixed rounding, no
timestamps. Rendering rules and the template contract: ``docs/GLOBE.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from . import geometry, languages, maps
from .paths import BUILD, MEDIA, ROOT

SOURCE_JS = ROOT / "tools" / "globe" / "globe.js"
FILE_NAME = "_cotw-globe.js"
# Deferred packets: the EEZs right after first paint; the fine level only when a view needs it
# or after a deep-idle delay (docs/GLOBE.md). The former ``overview`` packet (L2) moved into
# the bootstrap with issue #31.
PART_FILE_NAMES = {
    "zones": "_cotw-globe-zones.js",
    "detail": "_cotw-globe-detail.js",
}
DETAIL_FILE_NAME = PART_FILE_NAMES["detail"]
DATA_MARKER = "var DATA = null; // @@COTW_DATA@@"
BOOTSTRAP_LEVELS = 1
# L2 is the first paint and the coarsest level (issue #31): ~369 KB, so the budget rose from
# 300,000 bytes (sized for the former 1° L1) with ~8 % headroom. The total shrank.
BOOTSTRAP_MAX_BYTES = 400_000
TOTAL_MAX_BYTES = 2_000_000

# Land: coverage simplification tolerance in degrees (~4.5 km at the equator). At the
# largest initial zoom on an 800 px card that is below one pixel.
LAND_TOLERANCE_DEG = 0.04
# EEZ: fills only, drawn under the land, so they can be coarser.
EEZ_TOLERANCE_DEG = 0.1
# Islands (parts that touch nothing else) smaller than this are dropped, except the
# largest part of every entry, so each entry stays locatable (micro-states, atolls).
SPECK_DEG2 = 0.004
# Levels of detail, coarsest first: (name, land tolerance °, speck threshold deg²). Each level
# is its own coverage simplification of all land (topology-preserving, gap-free borders), so
# the renderer swaps whole levels, never mixes them. L2 is the coarsest level: first paint,
# rest at overview zoom and every interaction frame (in the bootstrap); L3 fine high zoom,
# packaged separately (docs/GLOBE.md). The former 2° L0 (issue #22) and 1° L1 (issue #31)
# were dropped as too crude; the names stay, so measurements remain comparable.
LEVELS = (("L2", 0.25, 0.02), ("L3", LAND_TOLERANCE_DEG, SPECK_DEG2))
EEZ_SPECK_DEG2 = 0.02
# A hole of (zone ∪ entry land) this close to the entry's land (degrees) is a coast gap.
COAST_GAP_DEG = 1e-6
# Grid: 0.001° per step (~100 m), fine enough to keep Vatican City a polygon. Arcs are
# delta-encoded on it.
QUANTIZATION = 360001, 180001
# Segments longer than this are densified so the straight chord between two vertices stays
# close to the curved line on the sphere.
MAX_SEGMENT_DEG = 1.0

# Initial zoom: the sphere fills the canvas at zoom 1. An entry whose farthest part (within
# MAP2_OUTLIER_DEG of the center) lies θ away gets zoom = ZOOM_FILL / sin θ, clamped to
# [1, ZOOM_MAX_INITIAL]; so huge entries show the whole globe and small ones get closer
# while the globe still reads as a globe.
ZOOM_FILL = 0.2
# Highlight circles (globe.js): an entry gets them when ``a · R² < HIGHLIGHT_AREA · side²``,
# with the sphere radius R = SPHERE_FILL · side / 2 · zoom. Only entries that pass at zoom 1
# can ever get a circle; they carry the hulls of their EEZ parts (``meta.e``), so the circle
# can enclose the EEZ without waiting for the deferred zones packet.
HIGHLIGHT_AREA = maps.HIGHLIGHT_AREA_PX2 / maps.SIZE**2
SPHERE_FILL = 0.96
HULL_POINTS = 12  # vertices per EEZ hull at most
HULL_DECIMALS = 2  # lon/lat decimals (≈ 1 km)
SEAM_JOIN_KM = 1.0
ZOOM_MAX_INITIAL = 1.4


# --- geometry preparation ----------------------------------------------------------------


def _center(entry: dict, land, centers: dict) -> tuple[float, float]:
    """``(lat, lon)``: the override from ``centers.yaml`` or the maps' default rule."""
    ov = centers.get(entry["id"])
    return (float(ov["lat"]), float(ov["lon"])) if ov else geometry.default_center(land)


def angular_radius(land, lat: float, lon: float, outlier_deg: float = geometry.MAP2_OUTLIER_DEG) -> float:
    """Largest angular distance (degrees) from the center to a vertex of the entry's parts
    that lie within ``outlier_deg`` (same outlier rule as map 2)."""
    best = 0.0
    lat0, lon0 = math.radians(lat), math.radians(lon)
    s0, c0 = math.sin(lat0), math.cos(lat0)
    for p in geometry.polygons(land):
        c = p.centroid
        if geometry.angular_distance(lat, lon, c.y, c.x) > outlier_deg:
            continue
        for x, y in p.exterior.coords:
            la, lo = math.radians(y), math.radians(x)
            cosd = s0 * math.sin(la) + c0 * math.cos(la) * math.cos(lo - lon0)
            best = max(best, math.degrees(math.acos(max(-1.0, min(1.0, cosd)))))
    return best


def area_sr(land) -> float:
    """Land area in steradians (lon/lat area scaled by cos(latitude) per part; plenty for a
    visibility threshold). The script multiplies it by the sphere radius² in pixels."""
    total = 0.0
    for p in geometry.polygons(land):
        total += p.area * math.cos(math.radians(p.centroid.y))
    return float(f"{total * math.radians(1.0) ** 2:.3g}")


def initial_zoom(radius_deg: float) -> float:
    s = math.sin(math.radians(max(radius_deg, 0.01)))
    return round(min(max(ZOOM_FILL / s, 1.0), ZOOM_MAX_INITIAL), 2)


def can_highlight(area: float) -> bool:
    """Whether an entry of ``area`` sr gets highlight circles at the widest zoom (1)."""
    return area * (SPHERE_FILL / 2) ** 2 < HIGHLIGHT_AREA


def zone_hulls(polys: list, lat: float, lon: float, max_points: int = HULL_POINTS) -> list[list[list[float]]]:
    """One convex outline per EEZ part, ``[[lon, lat], …]`` with at most ``max_points``
    vertices, that contains the part. Worked out in the azimuthal projection around the
    entry's center, so parts cut at the antimeridian (Kiribati) are joined into one; the
    hull is thinned and then scaled about its centroid until it covers the full hull again."""
    proj = geometry.Projection(lat, lon)
    projected = []
    for p in polys:
        for q in geometry.polygons(p):
            if geometry.contains_antipode(q, proj):
                continue
            pq = proj.forward(Polygon(q.exterior))
            projected.append(pq if pq.is_valid else shapely.make_valid(pq))
    # Halves cut at the antimeridian meet along a seam that is only straight in lon/lat, so
    # they are grouped with a 1 km tolerance instead of relying on an exact union.
    groups = geometry.polygons(unary_union([p.buffer(SEAM_JOIN_KM, quad_segs=1) for p in projected]))
    parts = [unary_union([p for p in projected if p.intersects(g)]) for g in groups]
    out = []
    for part in sorted(parts, key=lambda g: (-g.area, g.bounds)):
        hull = part.convex_hull
        if hull.geom_type != "Polygon":
            continue
        thin, tol = hull, hull.length / 1000.0
        while len(thin.exterior.coords) - 1 > max_points:
            thin = hull.simplify(tol)
            tol *= 1.5
        c = thin.centroid
        scale = 1.0
        while not shapely.affinity.scale(thin, scale, scale, origin=c).buffer(1e-6).contains(hull):
            scale *= 1.01
        cover = shapely.affinity.scale(thin, scale, scale, origin=c)
        ring = proj.inverse_xy(shapely.get_coordinates(cover.exterior)[:-1])
        out.append([[round(float(x), HULL_DECIMALS), round(float(y), HULL_DECIMALS)] for x, y in ring])
    return out


def _isolated(parts: list[Polygon]) -> list[bool]:
    tree = shapely.STRtree(parts)
    out = []
    for i, p in enumerate(parts):
        out.append(all(j == i for j in tree.query(p, predicate="intersects")))
    return out


def simplify_land(
    owned: list[tuple[str | None, object]], tolerance: float = LAND_TOLERANCE_DEG, speck: float = SPECK_DEG2
) -> tuple[list[tuple[str | None, Polygon]], dict[str, list]]:
    """``[(owner, geom)]`` → ``([(owner, polygon)], {owner: [[lon, lat], …]})``. Parts of one
    owner are fused first (dissolves unit borders inside an entry, e.g. Somaliland in
    Somalia), then all land is simplified as one coverage at ``tolerance``. Isolated specks
    are dropped (see ``SPECK_DEG2``); an entry's dropped specks survive as points on a 0.5°
    grid, so the highlight circles still find every island group (Kiribati, the Maldives)."""
    fused: dict[str | None, list[Polygon]] = {}
    for owner, geom in owned:
        fused.setdefault(owner, []).append(geom)
    parts: list[Polygon] = []
    owners: list[str | None] = []
    for owner in sorted(fused, key=lambda k: (k is not None, k or "")):
        merged = unary_union(fused[owner]) if owner is not None else MultiPolygon(
            [p for g in fused[owner] for p in geometry.polygons(g)]
        )
        for p in sorted(geometry.polygons(merged), key=lambda q: q.bounds):
            parts.append(p)
            owners.append(owner)
    simplified = shapely.coverage_simplify(parts, tolerance, simplify_boundary=True)
    isolated = _isolated(parts)
    largest: dict[str, int] = {}
    for i, (owner, p) in enumerate(zip(owners, parts)):
        if owner is not None and (owner not in largest or p.area > parts[largest[owner]].area):
            largest[owner] = i
    keep_idx = set(largest.values())
    out = []
    specks: dict[str, set] = {}
    for i, (owner, g) in enumerate(zip(owners, simplified)):
        if isolated[i] and parts[i].area < speck and i not in keep_idx:
            if owner is not None:
                pt = parts[i].representative_point()
                specks.setdefault(owner, set()).add((round(pt.x * 2) / 2, round(pt.y * 2) / 2))
            continue
        for p in geometry.polygons(g):
            out.append((owner, p))
    return out, {k: [list(p) for p in sorted(v)] for k, v in specks.items()}


def simplify_zone(polys: list, entry_land: list | None = None) -> list[Polygon]:
    """One entry's EEZ, simplified on its own. Parts split at the antimeridian stay split
    (fills only, so the seam never shows). Land holes are gone already
    (``marineregions.drop_land_holes``); the holes that are left (another territory's zone,
    a high-seas pocket) are cut out again if they survive the simplification.

    With ``entry_land`` (Natural Earth, full resolution), the gaps between the zone and the
    entry's coast are filled first, as on the maps (``maps.coast_gaps``, docs/MAPS.md): Marine
    Regions draws its zones up to its own coastline, and where a bay or fjord opens between
    that line and Natural Earth's, the sea color would show as a dark patch in the zone."""
    shells = [Polygon(p.exterior) for g in polys for p in geometry.polygons(g)]
    holes = [Polygon(h) for g in polys for p in geometry.polygons(g) for h in p.interiors]
    if not shells:
        return []
    if entry_land:
        # Zone ∪ the land it reaches ∪ the gaps between them: the coast is inside the shape, so
        # neither a bay nor the simplification below opens sea between the zone and the coast.
        zone = unary_union(shells)
        coast = [p for g in entry_land for p in geometry.polygons(g) if p.intersects(zone)]
        gaps = maps.coast_gaps(zone, coast, touch=COAST_GAP_DEG) if coast else []
        shells = [Polygon(p.exterior) for p in geometry.polygons(unary_union([zone, *coast, *gaps]))]
    # Small zones (Monaco, Jordan, Bosnia and Herzegovina) get a tolerance to match their size.
    tol = min(EEZ_TOLERANCE_DEG, math.sqrt(max(p.area for p in shells)) / 10.0)
    largest = max(shells, key=lambda p: p.area)
    parts = []
    for p in shells:
        q = shapely.simplify(p, tol, preserve_topology=False)
        parts += [r for r in geometry.polygons(shapely.make_valid(q)) if r.area >= EEZ_SPECK_DEG2 or p is largest]
    if not parts:
        return []
    merged = unary_union(parts).simplify(tol, preserve_topology=True)
    merged = unary_union([Polygon(p.exterior) for p in geometry.polygons(merged)])
    cut = [shapely.simplify(h, tol, preserve_topology=True) for h in holes if h.area >= EEZ_SPECK_DEG2]
    if cut:
        merged = merged.difference(unary_union(cut))
    return sorted(geometry.polygons(merged), key=lambda q: q.bounds)


# --- TopoJSON -----------------------------------------------------------------------------


def quantize_point(x: float, y: float) -> tuple[int, int]:
    qx, qy = QUANTIZATION
    return (int(round((x + 180.0) / 360.0 * (qx - 1))), int(round((y + 90.0) / 180.0 * (qy - 1))))


def _quantize_ring(coords) -> list[tuple[int, int]]:
    pts: list[tuple[int, int]] = []
    for x, y in coords:
        q = quantize_point(x, y)
        if not pts or q != pts[-1]:
            pts.append(q)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


class Topology:
    """Arc builder: rings split at junctions, identical (or reversed) arcs stored once.

    A vertex is a junction when the rings passing through it do not all share the same two
    neighbors (where a border meets a coast, triple points, touching islands). Rings
    without junctions become one closed arc, rotated to their smallest vertex so an enclave
    and the hole it fills share one arc.
    """

    def __init__(self):
        self.arcs: list[list[tuple[int, int]]] = []
        self.max_segment: list[float] = []  # densification limit per arc, degrees
        self._index: dict[tuple, int] = {}  # (max segment, points) → arc
        self._segment = MAX_SEGMENT_DEG

    def _arc(self, pts: list[tuple[int, int]]) -> int:
        # Shared only between arcs with the same densification (never across levels whose
        # limits differ).
        key = (self._segment, tuple(pts))
        if key in self._index:
            return self._index[key]
        rev = (self._segment, tuple(reversed(pts)))
        if rev in self._index:
            return ~self._index[rev]
        self._index[key] = len(self.arcs)
        self.arcs.append(list(pts))
        self.max_segment.append(self._segment)
        return self._index[key]

    def add(
        self, geoms: list[list[list[tuple[int, int]]]], shared: bool = True, max_segment: float = MAX_SEGMENT_DEG
    ) -> list[list[list[int]]]:
        """``geoms`` = polygons as lists of quantized rings (open). Returns the TopoJSON
        ``arcs`` per polygon. All rings passed in one call share junction detection; with
        ``shared=False`` every ring becomes one closed arc (fills that are never stroked).
        New arcs are densified to ``max_segment`` degrees (``encoded_arcs``)."""
        self._segment = max_segment
        neighbors: dict[tuple[int, int], set] = {}
        for rings in geoms if shared else []:
            for ring in rings:
                n = len(ring)
                for i, p in enumerate(ring):
                    s = neighbors.setdefault(p, set())
                    s.add(ring[i - 1])
                    s.add(ring[(i + 1) % n])
        junction = {p for p, s in neighbors.items() if len(s) > 2}
        out = []
        for rings in geoms:
            poly = []
            for ring in rings:
                cuts = [i for i, p in enumerate(ring) if p in junction]
                if not cuts:
                    start = ring.index(min(ring))
                    rot = ring[start:] + ring[:start]
                    poly.append([self._arc(rot + [rot[0]])])
                    continue
                rot = ring[cuts[0]:] + ring[: cuts[0]]
                base = cuts[0]
                idx = sorted((c - base) % len(ring) for c in cuts) + [len(ring)]
                closed = rot + [rot[0]]
                poly.append([self._arc(closed[a : b + 1]) for a, b in zip(idx, idx[1:])])
            out.append(poly)
        return out

    def encoded_arcs(self) -> list[list[list[int]]]:
        """Densified, delta-encoded arcs (TopoJSON quantized form)."""
        qx, qy = QUANTIZATION
        out = []
        for arc, seg in zip(self.arcs, self.max_segment):
            max_dx = seg / 360.0 * (qx - 1)
            max_dy = seg / 180.0 * (qy - 1)
            dense = [arc[0]]
            for (x0, y0), (x1, y1) in zip(arc, arc[1:]):
                steps = max(1, math.ceil(max(abs(x1 - x0) / max_dx, abs(y1 - y0) / max_dy)))
                for k in range(1, steps + 1):
                    dense.append((x0 + round((x1 - x0) * k / steps), y0 + round((y1 - y0) * k / steps)))
            enc = [list(dense[0])]
            px, py = dense[0]
            for x, y in dense[1:]:
                enc.append([x - px, y - py])
                px, py = x, y
            out.append(enc)
        return out


def _rings(p: Polygon) -> list[list[tuple[int, int]]]:
    rings = [_quantize_ring(p.exterior.coords)] + [_quantize_ring(r.coords) for r in p.interiors]
    return [r for r in rings if len(r) >= 3]


def _geometry(arcs: list[list[list[int]]], gid: str | None = None) -> dict:
    g: dict = {"type": "MultiPolygon", "arcs": arcs}
    if gid is not None:
        g = {"type": "MultiPolygon", "id": gid, "arcs": arcs}
    return g


# --- payload ------------------------------------------------------------------------------


def payload(entries: dict, land: dict, core: dict, other: list, eez: dict, palette: dict, centers: dict) -> dict:
    """Everything the script embeds. ``land``/``core`` are keyed by ISO2 and ``eez`` by
    ISO3 (the join of ``maps.World``); the output is keyed by COTW ID only."""
    by_iso2 = {e["iso2"]: cid for cid, e in entries.items()}
    owned = [(by_iso2[iso], g) for iso, g in sorted(land.items()) if iso in by_iso2]
    owned += [(None, g) for g in other]

    topo = Topology()
    objects: dict = {}
    lod = []
    specks: dict = {}
    for level, (name, tolerance, speck) in enumerate(LEVELS):
        simplified, level_specks = simplify_land(owned, tolerance, speck)
        if level == len(LEVELS) - 1:
            specks = level_specks  # highlight points: the islands the finest level drops
        per_owner: dict[str | None, list] = {}
        for owner, p in simplified:
            rings = _rings(p)
            if rings:
                per_owner.setdefault(owner, []).append(rings)
        keys = sorted(per_owner, key=lambda k: (k is not None, k or ""))
        flat = [rings for k in keys for rings in per_owner[k]]
        arcs = iter(topo.add(flat))
        land_arcs = {k: [next(arcs) for _ in per_owner[k]] for k in keys}
        suffix = "" if level == len(LEVELS) - 1 else f"_{name[1:]}"
        objects[f"entries{suffix}"] = {
            "type": "GeometryCollection",
            "geometries": [_geometry(land_arcs[k], k) for k in keys if k is not None],
        }
        objects[f"other{suffix}"] = _geometry(land_arcs.get(None, []))
        lod.append({"name": name, "tolerance": tolerance, "entries": f"entries{suffix}", "other": f"other{suffix}"})

    zones: dict[str, list] = {}
    for cid in sorted(entries):
        entry_land = [land[entries[cid]["iso2"]]] if entries[cid]["iso2"] in land else None
        parts = [r for p in simplify_zone(eez.get(entries[cid]["iso3"], []), entry_land) if (r := _rings(p))]
        if parts:
            zones[cid] = parts
    eez_keys = sorted(zones)
    eez_arcs = topo.add([rings for k in eez_keys for rings in zones[k]], shared=False)
    it = iter(eez_arcs)
    eez_geoms = [_geometry([next(it) for _ in zones[k]], k) for k in eez_keys]

    qx, qy = QUANTIZATION
    topology = {
        "type": "Topology",
        "transform": {"scale": [360.0 / (qx - 1), 180.0 / (qy - 1)], "translate": [-180.0, -90.0]},
        "objects": {**objects, "eez": {"type": "GeometryCollection", "geometries": eez_geoms}},
        "arcs": topo.encoded_arcs(),
    }

    meta = {}
    for cid in sorted(entries):
        e = entries[cid]
        geom = core.get(e["iso2"], land.get(e["iso2"]))
        if geom is None:
            raise RuntimeError(f"{cid} {e['iso2']}: no Natural Earth geometry")
        lat, lon = _center(e, geom, centers)
        meta[cid] = {
            "c": [round(lon, 3), round(lat, 3)],
            "z": initial_zoom(angular_radius(geom, lat, lon)),
            "a": area_sr(land.get(e["iso2"], geom)),
            "n": list(e.get("borders", [])),
            "s": specks.get(cid, []),
            "name": {code: e["name"][code] for code in languages.LANGUAGES},
        }
        if can_highlight(meta[cid]["a"]) and (hulls := zone_hulls(eez.get(e["iso3"], []), lat, lon)):
            meta[cid]["e"] = hulls  # EEZ outlines for the highlight circles
    keys_needed = ("sea", "coast", "entry", "neighbor", "land", "eez", "highlight")
    colors = {
        mode: {**{k: palette[mode][k] for k in keys_needed}, **palette["globe"][mode]} for mode in ("day", "night")
    }
    return {"topology": topology, "lod": lod, "entries": meta, "palette": colors}


def render(data: dict, source: str | None = None) -> str:
    """Splice the data into the renderer source. Compact JSON, sorted keys → stable bytes.

    The data is embedded as a JSON *string* (``DATA_JSON``) and parsed on first use: Anki
    desktop runs the script again for every card, and a string literal costs only a scan,
    while an object literal of this size would be built anew each time. ``DATA_KEY`` (the
    first 8 hex digits of the data's SHA-256) keys the decoded world cached on ``window``."""
    source = source if source is not None else SOURCE_JS.read_text(encoding="utf-8")
    if source.count(DATA_MARKER) != 1:
        raise RuntimeError(f"{SOURCE_JS}: data marker missing or repeated")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    key = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]
    literal = json.dumps(blob, ensure_ascii=True)
    return source.replace(DATA_MARKER, f'var DATA = null, DATA_KEY = "{key}", DATA_JSON = {literal};')


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def subset_topology(topology: dict, objects: dict) -> dict:
    """Copy only referenced arcs and remap their indices, preserving reversed references."""
    used: set[int] = set()

    def visit(value):
        if isinstance(value, int):
            used.add(value if value >= 0 else ~value)
        else:
            for child in value:
                visit(child)

    for obj in objects.values():
        for geom in obj.get("geometries", [obj]):
            visit(geom["arcs"])
    indices = sorted(used)
    remap = {old: new for new, old in enumerate(indices)}

    def refs(value):
        if isinstance(value, int):
            return remap[value] if value >= 0 else ~remap[~value]
        return [refs(child) for child in value]

    def geometry_copy(obj):
        if "geometries" in obj:
            return {**obj, "geometries": [geometry_copy(g) for g in obj["geometries"]]}
        return {**obj, "arcs": refs(obj["arcs"])}

    return {
        "type": "Topology", "transform": topology["transform"],
        "objects": {key: geometry_copy(obj) for key, obj in objects.items()},
        "arcs": [topology["arcs"][i] for i in indices],
    }


def split_payload(data: dict) -> tuple[dict, dict[str, dict]]:
    """The coarse level up front; the deferred levels/EEZs as two packets (``PART_FILE_NAMES``):
    ``zones`` every EEZ, ``detail`` the finer levels. Each packet carries the same key (a hash
    over both),
    so the bootstrap rejects any packet from another build. ``lod[i].part`` names the packet of
    every deferred level.

    Loading a packet script only registers strings. Parsing and preparation happen in
    idle slices, and an EEZ is parsed only for an entry actually shown in the reviewer.
    """
    topo, lod = data["topology"], data["lod"]
    objects = topo["objects"]
    coarse = {key: objects[key] for level in lod[:BOOTSTRAP_LEVELS] for key in (level["entries"], level["other"])}

    def packet(objects):
        topology = subset_topology(topo, objects)
        # Avoid constructing every coordinate pair in a single JSON.parse on weak CPUs.
        # Individual arc strings are parsed lazily within the polygon/mesh idle slices.
        topology["arcs"] = [_json(arc) for arc in topology["arcs"]]
        return _json(topology)

    level_part = {i: "detail" for i in range(BOOTSTRAP_LEVELS, len(lod))}
    content: dict[str, dict] = {"zones": {"zones": {}}, "detail": {"levels": {}}}
    for i, part in level_part.items():
        level = lod[i]
        content[part]["levels"][str(i)] = packet({key: objects[key] for key in (level["entries"], level["other"])})
    for geom in objects["eez"]["geometries"]:
        content["zones"]["zones"][geom["id"]] = packet({"eez": geom})
    key = hashlib.sha256(_json(content).encode("utf-8")).hexdigest()[:16]
    bootstrap_lod = [{**level, "part": level_part[i]} if i in level_part else level for i, level in enumerate(lod)]
    bootstrap = {**data, "lod": bootstrap_lod, "topology": subset_topology(topo, coarse), "detailKey": key}
    return bootstrap, {part: {"key": key, "part": part, **body} for part, body in content.items()}


def render_detail(detail: dict) -> str:
    """One deferred packet as an ordinary local Anki script; a late response from another
    deck is rejected by key."""
    return (
        "/* COTW globe detail. CC0, Parapoxvirus. Natural Earth: public domain; "
        "Marine Regions / VLIZ: CC BY 4.0. */\n"
        "(function (root) {\n'use strict';\nvar DETAIL = " + _json(detail) + ";\n"
        "if (typeof module === 'object' && module.exports) module.exports = DETAIL;\n"
        "if (root.COTWGlobe && root.COTWGlobe.acceptDetail) root.COTWGlobe.acceptDetail(DETAIL);\n"
        "})(typeof window !== 'undefined' ? window : this);\n"
    )


def extract_detail(script: str) -> dict:
    start = script.index("var DETAIL = ") + len("var DETAIL = ")
    return json.loads(script[start:script.index(";\n", start)])


def extract_data(script: str) -> dict:
    """Inverse of ``render`` for the tests: the embedded JSON."""
    line = script.index("var DATA = null, DATA_KEY = ")  # the spliced line, not the defaults
    start = script.index("DATA_JSON = ", line) + len("DATA_JSON = ")
    end = script.index(";\n", start)
    return json.loads(json.loads(script[start:end]))


def size_report(data: dict, script: str) -> dict[str, int]:
    """Bytes per share: land arcs per level of detail, EEZ arcs, arc references,
    names/centers, code (rest, incl. the string escaping of the embedded JSON)."""
    topo = data["topology"]
    arcs = topo["arcs"]

    def ids(geoms) -> set[int]:
        out: set[int] = set()

        def walk(a):
            if isinstance(a, int):
                out.add(a if a >= 0 else ~a)
            else:
                for x in a:
                    walk(x)

        for g in geoms:
            walk(g["arcs"])
        return out

    def size(obj) -> int:
        return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    objs = topo["objects"]
    report: dict[str, int] = {"total": len(script.encode("utf-8"))}
    counted = 0
    for n, level in enumerate(data["lod"]):
        level_ids = ids(objs[level["entries"]]["geometries"] + [objs[level["other"]]])
        name = level.get("name", f"L{n}")
        report[f"land arcs {name}"] = sum(size(arcs[i]) + 1 for i in level_ids)
        counted += report[f"land arcs {name}"]
    report["eez arcs"] = sum(size(arcs[i]) + 1 for i in ids(objs["eez"]["geometries"]))
    report["arc references"] = size(objs)
    report["entries + palette"] = size(data["entries"]) + size(data["palette"]) + size(data["lod"])
    counted += report["eez arcs"] + report["arc references"] + report["entries + palette"]
    report["code"] = report["total"] - counted
    return report


# --- driver -------------------------------------------------------------------------------


def build(entries: dict, media: Path = MEDIA, world: "maps.World | None" = None) -> tuple[Path, dict]:
    world = world or maps.World.load(entries)
    eez = {iso: world.eez.get(iso, []) for iso in sorted({e["iso3"] for e in entries.values()})}
    data = payload(entries, world.land, world.core, world.other, eez, maps.load_palette(), maps.load_centers())
    bootstrap, parts = split_payload(data)
    script = render(bootstrap)
    part_scripts = {part: render_detail(packet) for part, packet in parts.items()}
    report = {"bootstrap": len(script.encode("utf-8"))}
    report.update({part: len(text.encode("utf-8")) for part, text in part_scripts.items()})
    report["total"] = sum(report.values())
    if report["bootstrap"] > BOOTSTRAP_MAX_BYTES or report["total"] > TOTAL_MAX_BYTES:
        raise RuntimeError(f"Globe asset budget exceeded: {report}")
    media.mkdir(parents=True, exist_ok=True)
    target = media / FILE_NAME
    target.write_text(script, encoding="utf-8")
    for part, text in part_scripts.items():
        (media / PART_FILE_NAMES[part]).write_text(text, encoding="utf-8")
    return target, report


def write_preview(entries: dict, media: Path = MEDIA, build_dir: Path = BUILD) -> Path:
    """``build/globe-preview.html`` (not committed): a grid of globes with day/night,
    tooltip, language and width toggles. ``?ids=217,190&w=400&night=1&tooltip=1`` narrows
    it down (used for the screenshots); ``night=1`` sets Anki's ``.nightMode`` class, the
    only thing the globe follows. ``&debug=1`` shows each globe's last frame time, its level
    of detail and whether the coast stroke was drawn."""
    build_dir.mkdir(parents=True, exist_ok=True)
    rel = Path("..") / media.name / FILE_NAME
    names = {cid: f"{cid} {e['name'][languages.BASE]} ({e['iso2']})" for cid, e in sorted(entries.items())}
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>COTW globe preview</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{font-family:sans-serif;background:#FBF8F3;color:#222;margin:1rem}}
body.nightMode{{background:#2C2C2C;color:#eee}}
#bar{{position:sticky;top:0;padding:.4rem 0;background:inherit;z-index:2;display:flex;gap:1rem;align-items:center}}
#grid{{display:flex;flex-wrap:wrap;gap:16px}}
figure{{margin:0;position:relative}}figcaption{{font-size:.8rem;margin:.2rem 0;color:#888}}
.dbg{{position:absolute;left:4px;bottom:4px;font:12px/1.3 monospace;background:#000a;color:#fff;padding:2px 5px;border-radius:3px;pointer-events:none}}
</style></head>
<body><div id="bar"><b>COTW globe</b>
<label><input type="checkbox" id="night"> night</label>
<label><input type="checkbox" id="tip"> tooltip</label>
<label>lang <select id="lang">{"".join(f"<option>{code}</option>" for code in languages.LANGUAGES)}</select></label>
<label>width <select id="w"><option>200</option><option>300</option><option>400</option><option>800</option></select></label>
</div><div id="grid"></div>
<script>
var NAMES = {json.dumps(names, ensure_ascii=False)};
var q = new URLSearchParams(location.search);
var ids = q.get('ids') ? q.get('ids').split(',') : Object.keys(NAMES);
var grid = document.getElementById('grid');
document.getElementById('w').value = q.get('w') || '300';
document.getElementById('night').checked = q.get('night') === '1';
document.getElementById('tip').checked = q.get('tooltip') === '1';
document.getElementById('lang').value = q.get('lang') || '{languages.BASE}';
function build() {{
  grid.innerHTML = '';
  var w = document.getElementById('w').value + 'px';
  document.body.classList.toggle('nightMode', document.getElementById('night').checked);
  ids.forEach(function (id) {{
    var f = document.createElement('figure');
    var c = document.createElement('figcaption');
    c.textContent = NAMES[id] || id;
    var d = document.createElement('div');
    d.className = 'cotw-globe';
    d.style.width = w;
    d.setAttribute('data-id', id);
    d.setAttribute('data-lang', document.getElementById('lang').value);
    if (document.getElementById('tip').checked) d.setAttribute('data-tooltip', '');
    f.appendChild(c); f.appendChild(d); grid.appendChild(f);
  }});
  if (window.COTWGlobe) window.COTWGlobe.renderAll();
  // Debug view: ?lon=…&lat=…&zoom=… overrides the initial view of every globe.
  if (q.get('lon') !== null) document.querySelectorAll('.cotw-globe').forEach(function (el) {{
    var g = el.__cotwGlobe;
    if (!g) return;
    g.lon = +q.get('lon'); g.lat = +(q.get('lat') || 0); g.zoom = +(q.get('zoom') || 1);
    g.draw();
  }});
}}
['night', 'tip', 'lang', 'w'].forEach(function (k) {{ document.getElementById(k).onchange = build; }});
// ?debug=1: frame time, level of detail (L2 coarsest) and stroke per globe, live.
if (q.get('debug') === '1') (function tick() {{
  document.querySelectorAll('.cotw-globe').forEach(function (el) {{
    var g = el.__cotwGlobe, s = g && g.stats, f = el.parentNode, d = f.querySelector('.dbg');
    if (!s) return;
    if (!d) {{ d = document.createElement('div'); d.className = 'dbg'; f.appendChild(d); }}
    var names = window.__cotwGlobeWorld.world.names;
    d.textContent = s.ms.toFixed(1) + ' ms · ' + names[s.level] + (s.want !== s.level ? '→' + names[s.want] : '') +
      (s.stroke ? '' : ' · no stroke') + ' · zoom ' + g.zoom.toFixed(2);
  }});
  requestAnimationFrame(tick);
}})();
</script>
<script src="{rel.as_posix()}"></script>
<script>build();</script>
</body></html>
"""
    target = build_dir / "globe-preview.html"
    target.write_text(doc, encoding="utf-8")
    return target
