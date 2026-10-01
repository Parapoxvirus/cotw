"""Projection and window math for the exported maps.

Lambert azimuthal equal-area (LAEA) on the sphere, centered on each entry (DECISIONS.md
C10). The whole sphere maps into a disc of radius ``2R``; only the antipode of the center is
singular, so polygons crossing the antimeridian need no special handling. A polygon that
*contains* the antipode projects inside-out and is dropped (it can never reach a window
smaller than a hemisphere anyway).

Units: kilometers in projected space, WGS84 degrees on input.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon, box

R = 6371.0088  # mean earth radius, km

# Map windows. Radii in km, half the side of the square window.
MAP1_FACTOR = 3.0  # window radius = MAP1_FACTOR × entry radius, clamped to the range below
MAP1_MIN_KM = 1500.0
MAP1_MAX_KM = 6000.0
MAP2_FACTOR = 1.2
MAP2_MIN_KM = 1.5  # Vatican City: ~1 km wide, still clearly visible
# Parts of an entry farther than this from the center (angular distance) do not widen the
# map 2 window (Clipperton for France, Kerguelen-style outliers); they are still drawn if
# they happen to fall inside.
MAP2_OUTLIER_DEG = 45.0


class Projection:
    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self._phi0 = math.radians(lat0)
        self._lam0 = math.radians(lon0)
        self._sin0, self._cos0 = math.sin(self._phi0), math.cos(self._phi0)

    @property
    def antipode(self) -> tuple[float, float]:
        lon = self.lon0 + 180.0
        if lon > 180.0:
            lon -= 360.0
        return -self.lat0, lon

    def forward_xy(self, coords: np.ndarray) -> np.ndarray:
        """``[[lon, lat], …]`` degrees → ``[[x, y], …]`` km."""
        lam = np.radians(coords[:, 0]) - self._lam0
        phi = np.radians(coords[:, 1])
        sin_phi, cos_phi = np.sin(phi), np.cos(phi)
        cos_lam, sin_lam = np.cos(lam), np.sin(lam)
        denom = 1.0 + self._sin0 * sin_phi + self._cos0 * cos_phi * cos_lam
        denom = np.maximum(denom, 1e-12)  # antipode
        k = np.sqrt(2.0 / denom) * R
        x = k * cos_phi * sin_lam
        y = k * (self._cos0 * sin_phi - self._sin0 * cos_phi * cos_lam)
        return np.column_stack([x, y])

    def forward(self, geom):
        return shapely.transform(geom, self.forward_xy)

    def point(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = self.forward_xy(np.array([[lon, lat]], dtype=float))[0]
        return float(x), float(y)

    def inverse_xy(self, coords: np.ndarray) -> np.ndarray:
        """``[[x, y], …]`` km → ``[[lon, lat], …]`` degrees."""
        x, y = coords[:, 0], coords[:, 1]
        rho = np.hypot(x, y)
        c = 2.0 * np.arcsin(np.clip(rho / (2.0 * R), -1.0, 1.0))
        sin_c, cos_c = np.sin(c), np.cos(c)
        with np.errstate(invalid="ignore", divide="ignore"):
            phi = np.arcsin(np.where(rho == 0, self._sin0, cos_c * self._sin0 + y * sin_c * self._cos0 / rho))
            lam = np.where(
                rho == 0,
                0.0,
                np.arctan2(x * sin_c, rho * self._cos0 * cos_c - y * self._sin0 * sin_c),
            )
        lon = (np.degrees(lam + self._lam0) + 180.0) % 360.0 - 180.0
        return np.column_stack([lon, np.degrees(phi)])


def angular_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in degrees."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def polygons(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        return [p for g in geom.geoms for p in polygons(g)]
    return []


def largest_polygon(geom) -> Polygon:
    """Largest part by (roughly) true area: lon/lat area scaled by cos(latitude)."""
    def area(p: Polygon) -> float:
        return p.area * math.cos(math.radians(p.centroid.y))

    return max(polygons(geom), key=area)


def default_center(geom) -> tuple[float, float]:
    """Centroid of the largest polygon, ``(lat, lon)``."""
    c = largest_polygon(geom).centroid
    return round(c.y, 4), round(c.x, 4)


def contains_antipode(poly: Polygon, projection: Projection) -> bool:
    lat, lon = projection.antipode
    return poly.contains(Point(lon, lat))


def entry_extent(geom, projection: Projection, outlier_deg: float = MAP2_OUTLIER_DEG) -> tuple[float, float, float, float]:
    """Projected bounding box (km) of the entry's parts within ``outlier_deg`` of the center."""
    parts = []
    for p in polygons(geom):
        c = p.centroid
        if angular_distance(projection.lat0, projection.lon0, c.y, c.x) <= outlier_deg:
            parts.append(projection.forward(p))
    if not parts:  # degenerate override; fall back to everything
        parts = [projection.forward(p) for p in polygons(geom)]
    return MultiPolygon(parts).bounds if len(parts) > 1 else parts[0].bounds


def window(extent: tuple[float, float, float, float], kind: str) -> tuple[float, tuple[float, float]]:
    """``(radius, (cx, cy))`` of the square window in projected km. Map 1 stays centered on
    the projection center (orientation, the entry in the middle); map 2 is centered on the
    entry's bounding box so the margins are even on all sides."""
    minx, miny, maxx, maxy = extent
    if kind == "map1":
        half = max(abs(minx), abs(maxx), abs(miny), abs(maxy))
        return min(max(half * MAP1_FACTOR, MAP1_MIN_KM), MAP1_MAX_KM), (0.0, 0.0)
    half = max(maxx - minx, maxy - miny) / 2.0
    return max(half * MAP2_FACTOR, MAP2_MIN_KM), ((minx + maxx) / 2.0, (miny + maxy) / 2.0)


def window_box(radius_km: float, margin: float = 0.02, center: tuple[float, float] = (0.0, 0.0)):
    r = radius_km * (1.0 + margin)
    cx, cy = center
    return box(cx - r, cy - r, cx + r, cy + r)


def lonlat_bbox(projection: Projection, radius_km: float, samples: int = 32) -> tuple[float, float, float, float] | None:
    """Lon/lat bounding box of the square window (for candidate selection), or ``None``
    when the window contains a pole or wraps around the antimeridian."""
    r = radius_km * 1.05
    t = np.linspace(-r, r, samples)
    edge = np.concatenate(
        [np.column_stack([t, np.full_like(t, -r)]), np.column_stack([t, np.full_like(t, r)]),
         np.column_stack([np.full_like(t, -r), t]), np.column_stack([np.full_like(t, r), t])]
    )
    ll = projection.inverse_xy(edge)
    if np.any(np.isnan(ll)):
        return None
    lons, lats = ll[:, 0], ll[:, 1]
    # Pole inside the window: the window reaches beyond the pole → no lon bound possible.
    if np.max(np.abs(lats)) > 89.0 or (np.max(lons) - np.min(lons)) > 180.0:
        return None
    if r >= R * 1.4:
        return None
    return float(np.min(lons)), float(np.min(lats)), float(np.max(lons)), float(np.max(lats))


def project_clip(geom, projection: Projection, window) -> list[Polygon]:
    """Project every polygon of ``geom`` (dropping antipode-containing parts) and clip it to
    the window. Returns single polygons."""
    out = []
    for p in polygons(geom):
        if contains_antipode(p, projection):
            continue
        pp = projection.forward(p)
        if not pp.is_valid:  # projected rings can self-touch (polar seams); heal first
            pp = shapely.make_valid(pp)
        if not pp.intersects(window):
            continue
        try:
            clipped = pp.intersection(window)
        except shapely.errors.GEOSException:
            clipped = pp.buffer(0).intersection(window)
        out += polygons(clipped)
    return out
