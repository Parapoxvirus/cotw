# Maps

Every entry gets two text-free SVG maps, each written in a day and a night version, rendered by `python -m cotw build-maps` from
Natural Earth 10m admin-0 map units and Marine Regions (both cached in `.cache/`, never
committed). Design decisions: [`DECISIONS.md`](DECISIONS.md) C10–C13. Code:
`tools/cotw/geometry.py` (projection, windows), `tools/cotw/maps.py` (layers, SVG),
`tools/cotw/marineregions.py` (maritime zones).

| File | Purpose | Window |
|---|---|---|
| `media/cotw-<id>-map1-day.svg`, `…-map1-night.svg` | Orientation (“this is Europe / the Middle East”) | 3 × the entry's extent, clamped to 1 500–6 000 km (half side) |
| `media/cotw-<id>-map2-day.svg`, `…-map2-night.svg` | Where the capital lies | Centered on the bounding box of the entry and its capitals, 1.2 × its size, at least 1.5 km (half side) |

## Projection and center

- **Lambert azimuthal equal-area** on the sphere (R = 6371 km), centered on each entry.
  The whole globe fits into a disc, so polygons crossing the antimeridian need no cutting;
  only a polygon that contains the antipode of the center is dropped (it can never reach
  a window of at most 6 000 km).
- **Center** = centroid of the largest polygon (area weighted by latitude). Overrides in
  `data/overrides/centers.yaml`: Kiribati (spread across the antimeridian) and the United
  States (shifted north-west so Alaska and Hawaii fit into map 2).
- **Outlying parts** farther than 45° from the center do not widen the window (Clipperton
  for France, the Minor Outlying Islands for the United States). They are still drawn when
  they fall inside. Natural Earth units folded into an entry (`FOLD_UNITS`: the UK's
  Cyprus bases, Guantánamo Bay, buffer zones) are drawn as part of it but never move the
  center or widen the window. The same holds for capitals: Oslo (Bouvet Island), London (British
  Indian Ocean Territory) and Canberra (Heard Island) lie outside the entry and are not
  marked on map 2. France is metropolitan France plus Corsica: the overseas departments are
  separate COTW entries (DECISIONS.md A3).

## Layers (bottom to top, flat fills only)

1. Sea (whole square)
2. The entry's own **EEZ** as a light-blue fill
3. The entry's **12 nm territorial sea** as an even lighter outline. It is the outline of
   (12 nm ∪ entry land), so only the seaward line shows, not the coast.
4. Other land, including Natural Earth units without an ISO code (Antarctica, Bir Tawil, …)
5. **Neighbors**: exactly the entry's `borders` (land borders), one path per neighbor.
   Single exception: Cyprus, which borders the United Kingdom only through the sovereign
   base areas, lies outside the UK's map 1.
6. The **entry**, one path
7. **Highlight circles** (see below)
8. **Capital markers** (map 2 only): every capital gets the same white circle with an
   anthracite outline (DECISIONS A4), identical in day and night mode. The role (seat of
   government, judicial capital, …) is in the card text, not on the map. **Vatican City
   (098) is the explicit exception:** `data/overrides/maps.yaml` sets
   `map2_capital_marker: false`, because the city is itself the capital and the marker
   covers its tiny land area. The capital remains in the database and card text; the
   map window, geometry and day/night palettes are unchanged.
9. **Capital numbers** (map 2, entries with several capitals only): the digit 1, 2 or 3 next
   to each marker, white with the same anthracite outline, matching the order of the
   *Capital 1–3* fields.
   A capital that is not drawn (outside the 45° rule below) keeps its number, so the others
   still match the card. The digits are stroked paths from a built-in glyph set
   (`maps.GLYPHS`), no `<text>` and no font. Placement: to the right of the marker; when
   that would overlap another marker or number or leave the viewBox, to the left, above or
   below (first free side in that order, else the side with the least overlap).

Marker and number body: `#FFFFFF`; outline: `#1F2328`, in both modes
(`marker_fill` / `marker_outline` in `data/style/palette.yaml`). Number glyphs use two
identical paths: the wider outline underneath and the white body above, so the outline lies
outside the body instead of narrowing it.

All land shares one coast stroke, so land borders and coasts look the same. An entry or
neighbor that shrinks below one pixel (Vatican City on Italy's map 1, Macao on China's)
is drawn as a small dot in its layer color instead of disappearing.

## Micro-states and scattered islands

When the entry's visible land covers less than **150 px²** of the 1000 × 1000 map (about a
12 × 12 px square), its parts are grouped (parts closer than 45 px form one group) and
each group gets a **highlight circle** (radius ≥ 45 px). This covers micro-states on map 1
(Vatican City, Monaco, …) and island states on both maps. Tiny specks of *other* land
(< 0.6 px²) are dropped; the entry and its neighbors are always kept.

The circle encloses the group's islands **and the EEZ part(s) they lie in** (the EEZ as
drawn, after coast gaps and kept holes): the smallest enclosing circle plus a margin
(`HIGHLIGHT_MARGIN`), so the stroke stays clear of the EEZ edge and no 12 nm line of the
group can cross it (issue #25). Groups in the same EEZ part, and groups whose circles would
overlap, merge into one circle (Kiribati's map 1: one circle around all three island
groups' zones).

**Fallback** when an EEZ circle makes no sense in the view: an EEZ part is clipped by the
window edge (typical for map 2, which is zoomed in on the islands) or the circle would be
larger than 0.45 × the map side. Then the circle is the island circle (bounding box, as
before), grown until no 12 nm line comes within `HIGHLIGHT_CLEAR` of its stroke: a 12 nm
part the stroke would touch joins the group and the circle becomes the smallest one around
the group plus the margin; repeat until stable (overlapping circles keep merging). Where
archipelagic baselines make one large 12 nm part (Marshall Islands, Tuvalu on map 2) that
circle gets large. Entries without an EEZ or 12 nm zone (Vatican City, San Marino,
Liechtenstein, Andorra, …) keep the island circle. `tests/test_media.py` checks every
committed map: no 12 nm line within half strokes + 1 px of a circle, and every circle
either contains its EEZ part or meets the fallback condition.

## Maritime zones

Drawn from each zone's outer ring only, plus the holes that are not land:

- Marine Regions cuts a hole into a zone wherever land is, along its own coastline. The land
  on the maps is Natural Earth's; where the two coastlines differ, the plain sea color showed
  through those holes as dark patches in bays, fjords and lagoons (Svalbard's map 2). The
  loader drops every such hole (`marineregions.drop_land_holes`) and keeps only two kinds:
  another zone of the same layer lies in it (Saint-Pierre and Miquelon inside Canada's EEZ,
  Guernsey inside France's, the Liancourt Rocks claim inside South Korea's), or it is a
  high-seas pocket: no Natural Earth land and at least 1 deg² (the Peanut Hole in Russia's
  EEZ, the Aegean between Greece's 6 nm zones, the Bohai Sea in China's 12 nm layer).
- The renderer draws the zone's shells, fills every gap between the zone and the entry's
  land (a bay whose Marine Regions coastline lies seaward of Natural Earth's), fills any hole
  the processing leaves, and cuts the kept holes out again. The 12 nm outline is the outline
  of (12 nm ∪ entry land) under the same rules, so it shows the seaward line and real pockets
  only, never loops along the coast.
- `tests/test_media.py` checks every map: no ring larger than 10 px² that punches the EEZ
  fill or the 12 nm outline touches the entry's land (the v3-era maps had 4 286 of them).

Joined on the **territory** code (`iso_ter1`), not the sovereign, so Greenland's EEZ is
Greenland's, not Denmark's. Rules, with every manual decision in
`data/overrides/maritime.yaml` and the result per entry in `data/derived/maritime.yaml`:

- `200NM` / `12NM`: the territory; parts without a territory code (Alaska, Hawaii, the
  Azores, Galápagos, …) belong to the sovereign.
- **Joint regime**: drawn for every party.
- **Overlapping claim**: drawn for the first-listed territory only (Marine Regions lists
  the administering party first, e.g. Falklands, Gibraltar, Mayotte, Taiwan). Claims
  without a territory code (islets) go to the **de facto administrator** by explicit
  assignment (Kurils → Russia, Senkaku → Japan, Liancourt Rocks → South Korea, Ceuta and
  Melilla → Spain, Glorioso and Tromelin → French Southern and Antarctic Lands, …) or are
  excluded with a reason (South China Sea nine-dash claim, Matthew and Hunter, Doumeira,
  Perejil).
- **Chagos**: Marine Regions v12 lists the zone as Mauritian; it is assigned to the entry
  British Indian Ocean Territory, which owns the land in Natural Earth and Wikidata. To be
  revisited when the UK–Mauritius treaty takes effect.
- Aliases fold territory codes that are not COTW entries into the entry that holds the
  land: US Minor Outlying Islands → United States, Ascension and Tristan da Cunha → Saint
  Helena, Ascension and Tristan da Cunha.
- Hong Kong, Macao and Åland have no zone of their own in Marine Regions; Bouvet Island
  has only a 12 nm zone.

The Marine Regions WFS writes EPSG:4326 in latitude/longitude axis order (as its `.prj`
says); the loader swaps it to longitude/latitude.

## Size and determinism

- One simplification per map scale: **0.8 px** tolerance, topology-preserving across all
  land at once (`shapely.coverage_simplify`), so shared borders stay gap-free. Parts split
  at the antimeridian in the source data are fused before simplification (10 cm grid), so no
  seam line is drawn. Maritime zones are thinned in lon/lat first and closed by one
  tolerance afterwards.
- Path data on the integer grid of the 1000-unit viewBox, relative moves.
- No timestamps, no set iteration without sorting: same input → identical bytes.
- Budget, enforced by `tests/test_media.py`: median ≤ 100 KB, max ≤ 500 KB per map file.
  All 992 map files (248 entries × 2 maps × day/night) take about 20 MB.

## Text-free

No `<text>`, `<title>`, `<desc>`, comments or ids; CSS classes are single letters; the
capital numbers are paths. A test
checks that every map contains only SVG keywords, so neither a name nor an ISO code can
leak through the HTML inspector. Flags are cleaned the same way (metadata, `aria-*`,
editor attributes removed, ids renamed to `i0`, `i1`, …); writing that is part of a flag's
design stays.

## Night mode

Only Anki's night mode decides, never the system color scheme. An SVG inside `<img>` cannot
see Anki's `.nightMode` class, so every map is written twice from the same geometry:
`…-day.svg` with the day palette and `…-night.svg` with the night palette, each with exactly
one stylesheet and no media query (byte-identical except for the `<style>`). The note field
holds both `<img>` (field-referenced media is what *Check Media* keeps) and the card CSS
shows the one that matches (docs/DECK.md). Both palettes live in `data/style/palette.yaml`.
Flags stay one file.
