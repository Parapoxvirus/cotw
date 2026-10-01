"""Maritime zones from Marine Regions (Flanders Marine Institute, CC BY 4.0).

``python -m cotw fetch-marineregions`` downloads the ``eez`` (v12, 200 nm) and ``eez_12nm``
(territorial sea) layers from the public WFS as shapefiles into the gitignored cache and
writes the per-entry assignment to ``data/derived/maritime.yaml``. The geometry itself is
never committed; the map build reads it from the cache.

Assignment rule (DECISIONS.md A2, de facto situation), joined via the *territory* ISO code
``iso_ter1`` (not the sovereign, so Greenland's EEZ belongs to Greenland, not Denmark):

* ``200NM`` / ``12NM`` polygons belong to ``iso_ter1``; parts without a territory code
  (Alaska, Hawaii, Azores, Galápagos, …) belong to the sovereign ``iso_sov1``.
* ``Overlapping claim`` polygons are drawn for the first-listed territory ``iso_ter1``
  only. Claims without a territory code (islets such as Senkaku or Tromelin) are skipped
  unless ``data/overrides/maritime.yaml`` assigns them to the de facto administrator.
* ``Joint regime`` polygons are drawn for every listed party.
* ``data/overrides/maritime.yaml`` also holds territory-code aliases (``UMI`` → ``USA``,
  same fold as the land) and excludes (e.g. the South China Sea nine-dash claim).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import yaml

from .paths import CACHE, DERIVED, OVERRIDES

WFS_URL = "https://geo.vliz.be/geoserver/MarineRegions/wfs"
LAYERS = {"eez": "MarineRegions:eez", "eez_12nm": "MarineRegions:eez_12nm"}
MANIFEST = DERIVED / "maritime.yaml"
OVERRIDES_FILE = OVERRIDES / "maritime.yaml"
CITATION = (
    "Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Maritime Boundaries "
    "and Exclusive Economic Zones (200NM), version 12. Available online at "
    "https://www.marineregions.org/. https://doi.org/10.14284/632"
)
CITATION_12NM = (
    "Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Territorial Seas "
    "(12NM), version 4. Available online at https://www.marineregions.org/. "
    "https://doi.org/10.14284/633"
)


def download(cache: Path = CACHE) -> dict[str, Path]:
    """Fetch both layers as SHAPE-ZIP (no-op when present). Returns ``layer → .shp``."""
    import requests  # optional dependency, only for fetching

    from .wikidata import USER_AGENT

    out = {}
    for name, typename in LAYERS.items():
        target = cache / "marineregions" / name
        shp = target / f"{name}.shp"
        if not shp.exists():
            target.mkdir(parents=True, exist_ok=True)
            resp = requests.get(
                WFS_URL,
                params={
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": typename,
                    "outputFormat": "SHAPE-ZIP",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=1800,
                stream=True,
            )
            resp.raise_for_status()
            zip_path = target.with_suffix(".zip")
            with zip_path.open("wb") as fh:
                for chunk in resp.iter_content(1 << 20):
                    fh.write(chunk)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(target)
            if not shp.exists():  # GeoServer names the file after the layer; be tolerant
                found = sorted(target.glob("*.shp"))
                if not found:
                    raise RuntimeError(f"no shapefile in {zip_path}")
                for f in found[0].parent.glob(f"{found[0].stem}.*"):
                    f.rename(target / f"{name}{f.suffix}")
        out[name] = shp
    return out


def latitude_first(prj: Path) -> bool:
    """GeoServer's WFS 2.0 honours the EPSG:4326 axis order (latitude, longitude) and writes
    the shapefile that way; the .prj says so via its AXIS entries. Everything downstream
    expects (longitude, latitude)."""
    if not prj.exists():
        return False
    text = prj.read_text(errors="replace").lower()
    lat, lon = text.find("latitude"), text.find("longitude")
    return lat != -1 and lon != -1 and lat < lon


def _load(shp: Path, with_geometry: bool = True) -> list[dict]:
    import shapefile  # pyshp, optional dependency

    # GeoServer writes the DBF code page into a .cst side file (ISO-8859-1 for these layers).
    cst = shp.with_suffix(".cst")
    encoding = cst.read_text().strip() if cst.exists() else "utf-8"
    reader = shapefile.Reader(str(shp), encoding=encoding, encodingErrors="replace")
    fields = [f[0] for f in reader.fields[1:]]
    rows = []
    if with_geometry:
        import shapely
        from shapely.geometry import shape

        swap = latitude_first(shp.with_suffix(".prj"))
        for sr in reader.iterShapeRecords():
            rec = dict(zip(fields, sr.record))
            geom = shape(sr.shape.__geo_interface__)
            rec["geom"] = shapely.transform(geom, lambda c: c[:, ::-1]) if swap else geom
            rows.append(rec)
    else:
        for record in reader.iterRecords():
            rows.append(dict(zip(fields, record)))
    return rows


def load_overrides(path: Path = OVERRIDES_FILE) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def assign(eez_rows: list[dict], nm12_rows: list[dict], iso3_codes: set[str], overrides: dict) -> dict:
    """Apply the assignment rule. Returns ``{"assigned": {iso3: {"eez": [rows], "nm12":
    [rows]}}, "skipped": [...]}`` where ``skipped`` explains every unassigned polygon."""
    aliases = {k: v["to"] for k, v in (overrides.get("aliases") or {}).items()}
    forced = {int(k): v["to"] for k, v in (overrides.get("assign") or {}).items()}
    excluded = {int(k): v for k, v in (overrides.get("exclude") or {}).items()}
    result: dict[str, dict] = {iso: {"eez": [], "nm12": []} for iso in sorted(iso3_codes)}
    skipped = []

    def code(row: dict, i: int, sovereign_fallback: bool) -> str:
        c = row.get(f"iso_ter{i}") or (row.get(f"iso_sov{i}") if sovereign_fallback else "") or ""
        return aliases.get(c, c)

    def place(row: dict, layer: str, parties: list[str]) -> None:
        hit = [p for p in dict.fromkeys(parties) if p in result]
        for p in hit:
            result[p][layer].append(row)
        if not hit:
            what = ", ".join(p for p in parties if p) or "no territory code"
            skipped.append({"mrgid": int(row["mrgid"]), "name": row["geoname"], "reason": f"{row['pol_type']}: no COTW entry ({what})"})

    for layer, rows in (("eez", eez_rows), ("nm12", nm12_rows)):
        for row in rows:
            mrgid = int(row["mrgid"])
            kind = row["pol_type"]
            if mrgid in excluded:
                skipped.append({"mrgid": mrgid, "name": row["geoname"], "reason": excluded[mrgid]})
            elif mrgid in forced:
                place(row, layer, [forced[mrgid]])
            elif kind == "Joint regime":
                place(row, layer, [code(row, i, True) for i in (1, 2, 3)])
            elif kind == "Overlapping claim":
                place(row, layer, [code(row, 1, False)])
            else:  # 200NM / 12NM; parts without a territory code belong to the sovereign itself
                place(row, layer, [code(row, 1, True)])
    return {"assigned": result, "skipped": skipped}


def build_manifest(entries: dict, assigned: dict, skipped: list[dict]) -> dict:
    per_entry = {}
    for cid, e in sorted(entries.items()):
        a = assigned["assigned"].get(e["iso3"], {"eez": [], "nm12": []})
        per_entry[cid] = {
            "iso3": e["iso3"],
            "eez": [{"mrgid": int(r["mrgid"]), "name": r["geoname"], "type": r["pol_type"]} for r in sorted(a["eez"], key=lambda r: int(r["mrgid"]))],
            "nm12": [{"mrgid": int(r["mrgid"]), "name": r["geoname"]} for r in sorted(a["nm12"], key=lambda r: int(r["mrgid"]))],
        }
    return {
        "source": [CITATION, CITATION_12NM],
        "license": "CC BY 4.0",
        "rule": "200NM/12NM → iso_ter1, else iso_sov1; Overlapping claim → iso_ter1 only; Joint regime → every listed party; aliases, assignments and excludes in data/overrides/maritime.yaml",
        "entries": per_entry,
        "skipped": sorted(skipped, key=lambda s: s["mrgid"]),
    }


def write_manifest(manifest: dict, path: Path = MANIFEST) -> None:
    header = (
        "# Maritime zones per entry (Marine Regions, CC BY 4.0). Generated by\n"
        "# `python -m cotw fetch-marineregions`; do not edit by hand. Geometry lives in .cache/.\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def load_manifest(path: Path = MANIFEST) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# A hole without land and without another zone is a high-seas pocket (the Peanut Hole in
# Russia's EEZ, the Aegean between Greece's 6 nm zones) when it is at least this large;
# smaller ones are lagoons, ice-filled fjords and reefs that Natural Earth has no land for.
POCKET_DEG2 = 1.0


def drop_land_holes(rows: list[dict], land: list | None = None) -> list[dict]:
    """Zone polygons without their land holes. Marine Regions cuts a hole wherever land is,
    following its own coastline; the maps paint Natural Earth land on top, so where the two
    coastlines differ the plain sea color would show through the hole (bays, fjords,
    lagoons). A hole is kept only when it is not the zone's land:

    * another zone of the same layer lies in it (the French zone of Saint-Pierre and
      Miquelon inside Canada's, Guernsey inside France's, the Liancourt Rocks claim inside
      South Korea's): that area is not the entry's sea;
    * or it is a high-seas pocket: no ``land`` polygon touches it and it covers at least
      ``POCKET_DEG2`` (without ``land``, only the first rule applies).

    Test per hole for the first rule: does a representative point of another row's part
    fall into it? Only parts whose box lies inside the polygon's box are candidates, so the
    200 000 land holes cost nothing."""
    import shapely
    from shapely.geometry import MultiPolygon, Polygon

    from .geometry import polygons

    probes = []  # (row index, point) per part of every row
    for i, row in enumerate(rows):
        for p in polygons(row["geom"]):
            probes.append((i, p.representative_point()))
    tree = shapely.STRtree([pt for _, pt in probes])
    land_tree = shapely.STRtree(land) if land else None
    out = []
    for i, row in enumerate(rows):
        parts = []
        for p in polygons(row["geom"]):
            if not p.interiors:
                parts.append(p)
                continue
            holes = [Polygon(h) for h in p.interiors]
            hit = set()
            inside = [probes[j][1] for j in tree.query(shapely.box(*p.bounds)) if probes[j][0] != i]
            if inside:
                htree = shapely.STRtree(holes)
                for pt in inside:
                    hit.update(int(k) for k in htree.query(pt, predicate="within"))
            if land_tree is not None:
                for k, h in enumerate(holes):
                    if h.area >= POCKET_DEG2 and not len(land_tree.query(h, predicate="intersects")):
                        hit.add(k)
            parts.append(Polygon(p.exterior, [p.interiors[k] for k in sorted(hit)]))
        geom = parts[0] if len(parts) == 1 else MultiPolygon(parts)
        out.append({**row, "geom": geom})
    return out


def load_geometry(iso3_codes: set[str], cache: Path = CACHE, land: list | None = None) -> dict:
    """Assigned rows *with* geometry, for the map build (needs the cache). Land holes are
    dropped (``drop_land_holes``; ``land`` = Natural Earth polygons for the pocket rule)."""
    shps = {name: cache / "marineregions" / name / f"{name}.shp" for name in LAYERS}
    for shp in shps.values():
        if not shp.exists():
            raise FileNotFoundError(f"{shp} missing: run `python -m cotw fetch-marineregions` first")
    eez, nm12 = (drop_land_holes(_load(shps[name]), land) for name in ("eez", "eez_12nm"))
    return assign(eez, nm12, iso3_codes, load_overrides())
