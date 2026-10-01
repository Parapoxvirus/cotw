"""Land adjacency from Natural Earth 10m admin-0 *map units*.

Map units split sovereign states into their separately governed parts (French Guiana,
Hong Kong, Greenland, …), which matches the COTW rule that a dependency is its own entity.
The shapefile is downloaded into the gitignored cache dir; only the derived adjacency
(``data/derived/ne-borders.yaml``) is committed, so the import and the tests work offline.
"""

from __future__ import annotations

import io
import zipfile
from collections import defaultdict
from pathlib import Path

import yaml

from .paths import CACHE, DERIVED

NE_VERSION = "5.1.1"
NE_NAME = "ne_10m_admin_0_map_units"
NE_URL = f"https://naciscdn.org/naturalearth/10m/cultural/{NE_NAME}.zip"
BORDERS_FILE = DERIVED / "ne-borders.yaml"

# Map units without an ISO code of their own (ISO_A2_EH = -99) are folded into the entry
# that controls them de facto (DECISIONS.md A2: disputed areas follow the de facto
# situation), keyed by the unit's GU_A3. Units not listed here are
# ignored (uninhabited rocks, Antarctica, leased bases, overlays without land of their own).
FOLD_UNITS = {
    "CYN": ("CY", "Northern Cyprus: de facto separate, but not an ISO entity; folded into Cyprus"),
    "CNM": ("CY", "UN buffer zone in Cyprus"),
    "WSB": ("GB", "Akrotiri sovereign base area: UK territory on the island of Cyprus"),
    "ESB": ("GB", "Dhekelia sovereign base area: UK territory on the island of Cyprus"),
    "KNZ": ("KP", "Korean DMZ, northern half"),
    "KNX": ("KR", "Korean DMZ, southern half"),
    "SYU": ("SY", "UNDOF zone on the Golan Heights, Syrian side"),
    "SOL": ("SO", "Somaliland: de facto separate, but not an ISO entity; folded into Somalia"),
    "USG": ("US", "Guantanamo Bay naval base: US-controlled under lease, de facto rule"),
    "KAS": ("IN", "Siachen Glacier: Indian-administered, de facto rule"),
}


def download(cache: Path = CACHE) -> Path:
    """Fetch and unpack the shapefile into the cache dir (no-op when present)."""
    import requests  # optional dependency, only for fetching

    target = cache / NE_NAME
    shp = target / f"{NE_NAME}.shp"
    if shp.exists():
        return shp
    target.mkdir(parents=True, exist_ok=True)
    resp = requests.get(NE_URL, timeout=300)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(target)
    return shp


def _load_units(shp: Path) -> list[dict]:
    import shapefile  # pyshp, optional dependency
    from shapely.geometry import shape

    reader = shapefile.Reader(str(shp), encoding="utf-8")
    fields = [f[0] for f in reader.fields[1:]]
    units = []
    for sr in reader.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        units.append(
            {
                "name": rec["NAME_LONG"],
                "gu_a3": rec["GU_A3"],
                "iso2": rec["ISO_A2_EH"],
                "geom": shape(sr.shape.__geo_interface__),
            }
        )
    return units


def assign_units(units: list[dict], iso2_codes: set[str]) -> tuple[dict[str, list], list[dict]]:
    """Map each map unit to a COTW entry (by ISO_A2_EH or the fold table). Returns
    ``(iso2 → [unit, …], ignored_units)``."""
    grouped: dict[str, list] = defaultdict(list)
    ignored = []
    for u in units:
        if u["iso2"] in iso2_codes:
            grouped[u["iso2"]].append(u)
        elif u["gu_a3"] in FOLD_UNITS:
            grouped[FOLD_UNITS[u["gu_a3"]][0]].append(u)
        else:
            ignored.append(u)
    return grouped, ignored


def compute_adjacency(grouped: dict[str, list]) -> dict[str, list[str]]:
    """Pairs of entries whose geometries share a boundary *line* (point contacts, e.g. the
    Four Corners kind, don't count as a land border)."""
    from shapely import STRtree
    from shapely.ops import unary_union

    geoms = {iso: unary_union([u["geom"] for u in us]).buffer(0) for iso, us in grouped.items()}
    isos = sorted(geoms)
    tree = STRtree([geoms[i] for i in isos])
    adjacency: dict[str, set[str]] = {i: set() for i in isos}
    for a_idx, a in enumerate(isos):
        for b_idx in tree.query(geoms[a], predicate="intersects"):
            b = isos[b_idx]
            if b <= a:
                continue
            shared = geoms[a].intersection(geoms[b])
            if shared.length > 0:
                adjacency[a].add(b)
                adjacency[b].add(a)
    return {i: sorted(n) for i, n in adjacency.items()}


def build(iso2_codes: set[str], cache: Path = CACHE) -> dict:
    shp = download(cache)
    units = _load_units(shp)
    grouped, ignored = assign_units(units, iso2_codes)
    adjacency = compute_adjacency(grouped)
    version_file = shp.with_name(f"{NE_NAME}.VERSION.txt")
    version = version_file.read_text().strip() if version_file.exists() else NE_VERSION
    return {
        "source": f"Natural Earth {NE_NAME} v{version} ({NE_URL}), public domain",
        "units": {
            iso: sorted(u["name"] for u in us) for iso, us in sorted(grouped.items())
        },
        "folded": {k: {"into": v[0], "reason": v[1]} for k, v in sorted(FOLD_UNITS.items())},
        "ignored": sorted(f"{u['name']} ({u['gu_a3']})" for u in ignored),
        "missing": sorted(iso2_codes - set(grouped)),
        "borders": {iso: n for iso, n in sorted(adjacency.items()) if n},
    }


def write(result: dict, path: Path = BORDERS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Land adjacency derived from Natural Earth. Generated by `python -m cotw fetch-naturalearth`,\n"
        "# do not edit by hand; manual corrections go to data/overrides/borders.yaml.\n"
    )
    path.write_text(header + yaml.safe_dump(result, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")


def load(path: Path = BORDERS_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
