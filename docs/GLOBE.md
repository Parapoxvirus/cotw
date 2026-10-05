# Globe

`media/_cotw-globe.js` is the small bootstrap for an interactive orthographic globe on a
`<canvas>`, centered on the card's entry. It embeds world TopoJSON at L2 (0.25°, the coarsest
level) and, after the first frame has painted, loads two deferred packets from packaged Anki
media: `media/_cotw-globe-zones.js` (EEZs) and `media/_cotw-globe-detail.js` (L3 fine land, only
when needed). Design decisions: [`DECISIONS.md`](DECISIONS.md) B6–B9, C13. Map rules it shares:
[`MAPS.md`](MAPS.md). Code: `tools/globe/globe.js` (renderer, hand-written, no
dependencies), `tools/cotw/globe.py` (data build).

```bash
.venv/bin/python -m cotw build-globe   # needs the Natural Earth + Marine Regions cache (see README)
```

It writes `media/_cotw-globe.js` and the two packets (committed) and `build/globe-preview.html` (not committed):
a grid of all globes with day/night, tooltip, language and width toggles. Query parameters
narrow it down: `?ids=217,184&w=400&night=1&tooltip=1&lang=de` (or `lang=pl`), and
`&lon=…&lat=…&zoom=…` overrides the view. `night=1` sets Anki's `.nightMode` class (the only
thing the globe follows). `&debug=1` shows per globe the last frame time, the level of
detail it drew (`L2` coarsest; `L2→L3` = waiting for a level still being decoded), whether
the coast stroke was drawn, and the zoom.

## Template contract (roadmap step 4)

```html
<div class="cotw-globe" data-id="{{Locator}}"></div>
<script src="_cotw-globe.js" data-zones-src="_cotw-globe-zones.js"
  data-detail-src="_cotw-globe-detail.js"></script>
```

| Attribute | Meaning |
|---|---|
| `class="cotw-globe"` | Required. Every such element on the card gets a globe. |
| `data-id` | Required. The COTW ID, i.e. the note field `Locator` (DECISIONS B6). An unknown ID shows a plain globe. |
| `data-lang` | `en` (default), `de` or `pl`: language of the tooltip. |
| `data-tooltip` | Present = the back side's tooltip is on (hover with a mouse, tap on touch devices shows the country name and gives that country the quiet `selected` fill). **Absent by default**, and it must stay absent on the front of *Map → Country* (DECISIONS B8): no text at all. `data-tooltip="false"` also switches it off. |

The deck builder supplies content-hashed filenames for **all three** scripts. Each optional
`data-<part>-src` (`zones`, `detail`) accepts only a local
`_cotw-globe-<part>[-<hash8>].js` media basename; it defaults to `_cotw-globe-<part>.js` beside
the bootstrap. The packaged card also carries the references on its `.cotw-globe` element, for
reviewers without `document.currentScript`; referencing every packet in the template is also
what makes Anki ship it. No remote fetch is used. The globe is square and as wide as its container, so size it with the
container (`width`, `max-width`). The script adds a `<canvas>` and a hidden tooltip `<div>`
inside the element, and sets `position: relative` on it if it was `static`.

Example back side (German deck):

```html
<div class="cotw-globe" data-id="{{Locator}}" data-lang="de" data-tooltip></div>
<script src="_cotw-globe.js" data-zones-src="_cotw-globe-zones.js"
  data-detail-src="_cotw-globe-detail.js"></script>
```

### Anki constraints

- **Offline:** no network, no CDN, no fonts to load. The tooltip inherits the card's font.
- **Plain ES2017-ish script:** no modules, no bundler runtime, no optional chaining. Uses
  Pointer Events, `canvas` 2D, `ResizeObserver` when available (falls back to `resize`).
- **Re-init safe.** Anki desktop reuses the webview between cards and runs the script again
  for every card. The first run defines `window.COTWGlobe`; every later run with the same
  `VERSION` and data (`DATA_KEY`, a hash of the embedded data) only calls
  `COTWGlobe.renderAll()`, which destroys globes whose element left the page (listeners,
  `ResizeObserver`, pending animation frame, settle timer, staged paint and its pixel buffer) and (re)renders every
  `.cotw-globe`, drawing each exactly once. The script also registers `renderAll` in Anki
  desktop's `onShownHook` when that list exists. `COTWGlobe.destroyAll()` removes every
  globe (canvas, tooltip, listeners). A different script version or different data retires
  the globes of the one that already ran in the same webview.
- **Cross-card cache.** The data is embedded as a JSON string and parsed on first use, so a
  later card only scans the small bootstrap string. The
  decoded world is kept on `window.__cotwGlobeWorld`, keyed by `VERSION` and `DATA_KEY`:
  later cards reuse land, and each entry’s EEZ is decoded at most once after first paint. The
  world is plain data (no DOM references), so keeping it is re-init safe. The bootstrap key
  also covers the key shared by both packets: changing just the deferred geometry
  invalidates the world. A late packet from an older deck is rejected by key; retiring a
  renderer cancels its pending frame, idle work and packet requests. EN/DE packages carry the
  same three assets; updates leave older hashed files available to the other installed deck.
- **Touch:** the canvas sets `touch-action: none` so dragging the globe does not scroll the
  card; the rest of the card scrolls normally.

## Interaction

- Drag (mouse or one finger) rotates; latitude is clamped to ±89.9°. A pressed pointer only
  starts a drag once it has moved more than **12 CSS px** (touch, pen) or **4 px** (mouse)
  from where it went down. Until then nothing rotates, redraws or drops to the interaction
  level, and releasing it is a tap (issue #22: finger jitter turned taps into drags). Once
  past the slop the globe rotates from that point on, without jumping by the distance
  already covered.
- Mouse wheel and pinch zoom between 1× (whole globe) and 12×.
- **Hit tolerance** (issue #27): a tap or hover that hits no land still picks an entry when
  its drawn coast is within **16 CSS px** on screen (touch, pen) or **6 px** (mouse; the
  coalesced hover uses the mouse value), so small islands (Hawaii, atolls) can be hit. The
  exact hit comes first (highlight circles, then the entry's land), so shared borders behave
  as before. Only a miss over sea or space searches: a tap on land without an entry
  (Antarctica, Bir Tawil) clears as before. The distance is measured per land part to its
  projected coast on the currently drawn level (the margin belongs to the island, not to a
  box around its country; the US mainland is unaffected), and islands the globe does not
  draw (the specks `s`, all entries) are point targets with the same radius. Only entries
  are targets, never `other` land. Where tolerances overlap, the nearest coast wins, and
  equal distances go to the lower id. The tooltip anchor is the nearest coast point (or the
  speck), so the tooltip sits on the island, not in the sea. The search prefilters each part
  by its bounding cap in screen space and skips land behind the horizon. Pick time
  (`node tools/globe/pick-benchmark.js`: 400 seeded resting views and points, half within
  20 px of a coast, exact hit plus search, L2/L3 at 800 px): Node 22 p95 0.25 ms (misses
  0.32 ms, max 1.2 ms); Chromium 153 p95 0.36 ms, and 1.46 ms under 4× CPU throttling
  (misses 1.6 ms, max 2.5 ms).
- Double-click / double-tap returns to the initial view.
- No inertia.
- **Every interaction frame includes borders.** Whole land coverages and their shared
  boundary mesh switch together; each shared arc is stroked once. Every interaction frame is
  **L2** (0.25°): interaction picks its level like the resting view (2.5 px), capped below
  the finest level, and L2 is the coarsest level there is. The fine 0.04° resting mesh is
  never used during interaction. Input is coalesced with requestAnimationFrame. The resting
  image is prepared 150 ms after release. Detail work pauses while a pointer is held or
  interaction is settling.
- **No adaptive fallback below L2** (issue #31). Until then a draw over 16 ms, or three
  animation-frame waits over 34 ms, stepped down to the 1° L1, and a drag could stay there
  (issue #29 capped normal interaction at L2 but kept L1 as first paint and fallback floor;
  it still showed up while rotating). Now slow frames stutter at L2 instead of going
  coarser; frame waits are still measured (`stats.frameWaitMs`) for the benchmark. Measured
  drag frame times: see Performance.

## Night mode

The night palette applies exactly when the element sits inside `.nightMode` (Anki sets it on
the card/body; `.night_mode` in AnkiDroid and older clients). The system color scheme is
ignored on purpose: with Anki set to light and the OS dark, the card must be light (issue
#12). The class is checked on every draw and on every `renderAll`, which redraws when it
changed. Both palettes come from `data/style/palette.yaml`: the map colors are
shared, the `globe` section adds `space` (outside the sphere, `transparent` so the card
background shows), `rim` (sphere outline) and `graticule`.

## Data

| Part | Source and rule |
|---|---|
| Land | Natural Earth **10m** admin-0 map units with the same entry join as the maps (`naturalearth.FOLD_UNITS`), fused per entry (no internal unit borders), then simplified **all at once** with `shapely.coverage_simplify`, so shared borders stay gap-free, once per **level of detail** (below): 1°, 0.25° and 0.04° (~4.5 km at the finest level). 10m heavily simplified was chosen over 50m: the entry join (incl. `FOLD_UNITS`) is exactly the maps' join with no second source to reconcile, every entry is guaranteed to exist, and after simplification the extra detail costs little. |
| Levels of detail | `globe.LEVELS`, coarsest first: **L2** 0.25° (first paint, overview/rest and every interaction frame; islands under 0.02 deg² dropped), **L3** 0.04° (high zoom, under 0.004 deg²). Every level is an independent coverage simplification and keeps the largest part of every entry. L2 is in the bootstrap, L3 is the `detail` packet (`lod[i].part`). Each `lod` entry carries its `name`, used by measurements and the debug view; the renderer's level *index* is 0 = L2, 1 = L3. A 2° **L0** was dropped with issue #22, a 1° **L1** (first paint and adaptive fallback floor, islands under 0.2 deg² dropped, 4,867 mesh points vs 17,568 for L2) with issue #31: it kept showing up while dragging. L2 was the `overview` packet until then. |
| Specks | Isolated islands under 0.004 deg² (~50 km²) are dropped, except the largest part of every entry. The dropped islands of an entry survive as points on a 0.5° grid (`s`), used only to place highlight circles (Kiribati, the Maldives). |
| Topology | Arcs split at junctions, shared borders and enclave/hole rings stored once, quantized on a 0.001° grid (Vatican City stays a polygon), delta-encoded, segments over 1° densified (every level, so the chord error stays sub-pixel wherever a level is drawn). Standard TopoJSON (`type: Topology`, `transform`, `objects`, `arcs`). |
| Objects | `entries…`: one `MultiPolygon` per entry per level, `id` = COTW ID (never ISO, DECISIONS A1). `other…`: all land without an entry (Antarctica, Bir Tawil, …). `eez`: the entry's own EEZ (Marine Regions, same assignment as the maps), one level, simplified per entry at 0.1° (finer for small zones). Land holes are gone ([`MAPS.md`](MAPS.md)); holes that hold another territory's zone (Saint-Pierre and Miquelon in Canada's) or a high-seas pocket are kept. Before simplifying, the zone is joined with the entry's Natural Earth land parts it touches and the gaps between them (`maps.coast_gaps`, issue #22): Marine Regions draws zones up to its own coastline, so bays and fjords (Svalbard, Norway, the Gulf of Bothnia) showed as dark sea patches in the zone, and simplifying the coastal edge on its own opened thin slivers along every coast (7,239 gaps, 45 deg², before; `tests/test_globe.py` now allows none over 0.01 deg²). The EEZ is drawn under the land, so the joined land never shows. No 12 nm zone (DECISIONS C13). |
| Per entry | `c` center (lon, lat) by the maps' rule: `data/overrides/centers.yaml`, else the centroid of the largest polygon (without folded units); `z` initial zoom; `a` land area in steradians; `n` neighbors = exactly `borders`; `name.en` / `name.de` / `name.pl` for the tooltip; `e` (only entries that can get highlight circles at zoom 1, `globe.can_highlight`) one convex outline per EEZ part, at most 12 lon/lat points with 2 decimals, fused across the antimeridian and scaled so it contains the whole part (`globe.zone_hulls`); 87 entries, 100 outlines, about 16 KB of the bootstrap (issue #25: bootstrap 203,137 → 222,728 bytes). |

Output is deterministic (sorted iteration, fixed rounding, `sort_keys`, no timestamps):
the same input gives byte-identical assets. Enforced budgets are **400,000 bytes** for the
bootstrap and **2,000,000 bytes** for all three files together. The bootstrap includes the
renderer, palettes, entry metadata and the L2 topology. The bootstrap budget was 300,000
bytes while it carried the 1° L1 (228,451 bytes); with L2 it is 369,424 bytes, so issue #31
raised it with ~8 % headroom rather than keep a coarser level. The total went down
(1,593,479 → 1,501,918 bytes), since L1 and the `overview` packet (232,534 bytes) are gone. The packets register
JSON strings (`zones`: each EEZ separately, `detail`: L3), both carrying one
key over their combined content; loading a packet does not decode anything.
Each deferred arc is itself serialized, so parsing a packet does not allocate all of its
coordinate pairs at once; each arc is parsed in the idle slice that first uses it.
Independent packets remap only their own referenced arcs, keeping shared boundaries intact.

## Rendering

- **Orthographic projection** on the unit sphere, rotated so the view center faces the
  viewer. Vertices are converted to 3D unit vectors once; each frame is three dot products
  per vertex. HiDPI: the canvas is `devicePixelRatio` × its CSS size.
- **Horizon clipping.** Fills: a ring's visible stretches are drawn as they are; where the
  ring goes behind the globe, the path follows the limb (the shorter way between
  consecutive hidden vertices, as an exact circular arc) until it comes back. So the fill is
  exactly the visible part; rings entirely behind draw nothing. This needs every polygon to
  be smaller than a hemisphere, which holds for all land and EEZ parts (a JS test checks
  it). Strokes are clipped as lines and end exactly on the limb.
- **Antimeridian and poles.** The data stays in lon/lat, so parts split at ±180° stay split
  (their fills meet seamlessly on the sphere). The coast stroke is drawn once over the arc
  mesh and skips segments that run along ±180° or ±90° (the cuts of the source data), so no
  seam line shows (Chukotka, Fiji, Antarctica). Each vertex carries a bit per cut it lies on
  (`seam`); a segment is skipped when both ends share a cut (`onSeam`). The corner where the
  180° cut meets the south pole lies on both, so the meridian stretch up from the pole is
  skipped too (issue #33: it used to show as a short stroke in the middle of Antarctica).
- **Levels of detail.** Screen error = tolerance × π/180 × sphere radius in CSS px.
  Choose the coarsest coverage within **2.5 px**, during interaction capped at L2. Nothing
  is ever drawn coarser than L2: not at rest, while rotating, at first paint, on a slow
  device, or while a packet is missing or still loading (issue #31). A zoomed-out 800 px
  globe rests and interacts at L2; high zoom rests at L3 and interacts at L2. Every newly
  inserted or resized canvas first draws L2 without EEZ detail, including with a warm
  decoded-world cache, so detail cannot delay the shell.
- **Progressive handoff (L2 first paint, then the EEZ, then L3 when needed; issues #17, #22,
  #31).** The first paint is L2, decoded synchronously from the bootstrap. There is no land
  handoff below L2 any more: until issue #31 the first paint was L1, and L2 followed from
  the `overview` packet. Two animation-frame callbacks guarantee that painted frame before
  anything else. Then the best ready level is staged at once (a warm cache with L3 goes
  straight to it at high zoom), and the `zones` packet is requested. Every improvement is
  presented as soon as it is prepared: the EEZ is added on the same land level, and L3 never
  delays it. A view waiting for L3 keeps L2. Preparation pauses
  while a staged image is pending, so each improvement is presented before the next one is
  prepared; presentation resumes it at once. Fine land (`detail`) is requested only when a
  resting view needs L3, or after **2 s** of deep idle (all visible levels and zones done, no
  input), so a later zoom finds it ready; it never delays L2.
- **Slicing.** JSON packets are parsed on demand, then polygons and mesh arcs are prepared in
  slices with a 4 ms budget (a single polygon/arc is indivisible). Only visible entries' EEZs
  are prepared, outside `draw()`. Work starts after first paint and continues as plain tasks
  (`MessageChannel`), so input and frames still run between slices; idle callbacks were
  dropped for continuations because a callback requested inside an idle period waits for the
  next one (up to 50 ms), which made every 4 ms slice cost a whole period. Held or settling
  input parks preparation in idle-time polling. A resting image is painted on a detached
  software canvas in 4 ms slices with explicit raster flushes; a single polygon remains
  indivisible. The visible bordered globe stays intact until one animation-frame copy presents
  the complete replacement. Center, zoom, pointers and palette are unchanged. Input cancels
  pending paint immediately; publication also checks the card, view, size and Anki theme, so
  stale work cannot overwrite a newer frame. Destroying a globe cancels callbacks and releases
  its pixel buffers. Without `requestIdleCallback`/`MessageChannel` timers take over. A missing
  packet leaves the best prepared bordered level, is not retried on the same card, and is
  retried on the next card. Every packet is keyed to the bootstrap, preventing stale cross-deck data.
- **Culling.** Every polygon and arc gets a bounding cap (center + angular radius) when its
  level is decoded; a cap entirely behind the horizon or outside the zoomed canvas is
  skipped before any of its vertices is projected.
- **Layers**, bottom to top, flat fills only: space · sphere (sea) · the entry's EEZ ·
  graticule (30°, faint) · other land · neighbors · the tooltip's country (`selected`, backs
  only) · entry · coast/border stroke · rim · highlight circles. No textures, no shading, no capitals.
- **Initial view:** centered on the entry. Zoom = 0.2 / sin θ, clamped to **1–1.4**, where θ
  is the angular distance from the center to the entry's farthest vertex (parts beyond 45°,
  like Clipperton for France, don't count; same outlier rule as map 2). At zoom 1 the whole
  globe fits (Russia, Canada, Brazil, the United States); small entries get at most 1.4 so
  the limb still shows in the corners and the globe still reads as a globe.
- **Highlight circles** (same idea as the maps' micro-state circle): when the entry's land,
  seen face-on at the current zoom, would cover less than 150/1000² of the canvas, every
  visible group of its parts (polygons, dropped islands, or else the center) gets a circle
  of at least 4.5 % of the canvas side; groups whose circles would overlap merge. Decided
  on the whole entry, not the visible part, so a large country turning away over the
  horizon never gets circles. Same rule as the maps (issue #25): a group's circle encloses
  the **EEZ part(s)** its islands lie in, with a margin of 0.8 % of the side. The EEZ
  outlines come from the bootstrap (`e`, below), not the deferred `zones` packet, so the
  circle never jumps when the zones arrive. **Fallback** to the island circle when an EEZ
  part is not entirely on the visible hemisphere or the circle would exceed 0.45 × side
  (zoomed in). The globe has no 12 nm line, so there is no crossing check.
- **Tooltip and selection** (opt-in, see above): the name of the entry under the pointer
  (inside a highlight circle: the card's entry), in `data-lang`, from the embedded names.
  Hit-testing inverts the projection and tests the entries' lon/lat rings of the finest decoded
  level. One selection drives both the tooltip and a quiet fill (`selected` in
  `data/style/palette.yaml`: day `#D5D7A4`, the land fill `#DAE6AF` blended 30 % toward
  sand `#C8B58B`; night `#75634F` warm brown), so they always name the same entry. The card's
  own entry keeps its green when it is the one selected and stays the strongest emphasis;
  neighbors, EEZ, graticule, coasts/borders, rim and circles are unchanged.
  - *Mouse:* hovering selects (within the hit tolerance); moving to another country switches;
    the sea, space or leaving the globe clears. Pointer moves are coalesced: at most one hit test, tooltip move and
    selection repaint per animation frame.
  - *Touch:* a tap (a finger that never left its slop, see Interaction) selects or switches the
    country where it went down, or within the hit tolerance of it; a tap on the sea clears. Drags, pinch fingers and wheel never
    select; a double-tap (or double-click) reset clears the selection.
  - *Moving view:* the selection stays on its country; interaction frames paint it inline and
    the tooltip follows its anchor (hidden while the anchor is behind the horizon or off the
    canvas).
  - *Cost:* on backs the presented resting image is kept as a base. A selection change copies
    it and draws only the selected country's fill plus, clipped to it, the borders, rim and
    circles it covered. The world is never repainted for hover. A staged detail image is left
    alone and gets the selection when it is presented. Before the first staged image (the
    synchronous coarse first paint) or right after a gesture, the shown coarse level is
    repainted directly.
  - *Lifecycle:* cleared on a new card or entry, a view reset, an Anki theme switch,
    `destroy`/`retire`, and on views without `data-tooltip` (the *Map → Country* front never
    selects).
  - *Placement:* centered above the anchor, below it when there is no room above, and clamped
    2 px inside the globe at all four edges. Long names wrap within the globe's width.

## Performance

The reproducible harness uses real rendered deck backs, a persistent reviewer window,
packaged hashed assets, 800 CSS px and DPR 2. The path starts with South Korea → Kiribati,
then exercises Africa/Europe and Pacific drag/rotation, wheel zoom, and a real two-pointer
pinch. Every sampled interaction frame must include borders. It records both draw CPU
time and animation-frame intervals; these are different measurements (60 Hz frame
intervals are about 16.7 ms even for a cheap draw).

```bash
.venv/bin/pip install -e '.[browser]'
.venv/bin/playwright install chromium
.venv/bin/python tools/globe/benchmark.py
# Or use an installed Chromium: --browser /path/to/chromium
```

`build/globe-benchmark/report.json`, `traces-{1,4}x.json` and screenshots contain the
measurements and visual evidence. Cold samples use fresh browser contexts; subsequent
samples replace the card shell and reload the bootstrap in the same window. Timing starts
after the shell is painted; the harness records when the first bordered canvas, L2 (the same
frame since issue #31) and the entry's EEZ were presented and when L3 was prepared (`coldStagesMs`, `subsequentStagesMs`). The
harness reports normal CPU and 4× throttling, long tasks during the whole load and after first paint, and moving
screenshots in both regions. The handoff window includes the final presented canvas, not
only geometry decoding. It checks preserved view state, high-zoom resting detail, and input
that interrupts a staged image. Every cold sample reports handoff long tasks and the largest
paint slice. The OS is set dark while the default card stays light; a
separate Anki-class night screenshot verifies the approved theme behavior.

Measured 2026-09-30 (issue #31) with Chromium 153.0.8010.12, five cold and five subsequent
cards, 120 frames per drag/wheel trace and 45 pinch frames, before (rc9, `main` at 36bfb35: L1
first paint + `overview` packet) and after (L2 bootstrap, no fallback below L2), same machine,
back to back (the measured bootstrap was 11 bytes smaller: a later comment-only change). Full results, asset hashes, per-card stage samples and frame intervals:
[`benchmarks/globe-l2-first-paint.json`](benchmarks/globe-l2-first-paint.json) (after) and
[`benchmarks/globe-rc9.json`](benchmarks/globe-rc9.json) (before); earlier runs:
[`globe-progressive.json`](benchmarks/globe-progressive.json) (issue #17),
[`globe-handoff.json`](benchmarks/globe-handoff.json), [`globe-rc3.json`](benchmarks/globe-rc3.json).

| Bytes | Bootstrap (budget) | Overview | Zones | Detail | Total (budget 2,000,000) |
|---|---:|---:|---:|---:|---:|
| Before (L1 bootstrap) | 228,451 (300,000) | 232,534 | 197,585 | 934,909 | 1,593,479 |
| After (L2 bootstrap) | 369,424 (400,000) | — | 197,585 | 934,909 | 1,501,918 |

Stages, ms after the card shell (p50 / p95), before → after. Since #31 the first paint *is*
L2. *Subsequent* cards reuse the decoded world; their L3 was prepared by the earlier card. L3
is *prepared*, not shown, at the overview zoom (it is loaded after 2 s of deep idle).

| Stage | Normal CPU cold | Normal subsequent | 4× CPU cold | 4× subsequent |
|---|---:|---:|---:|---:|
| Bordered first paint | 52.7 / 91.0 → **67.7 / 79.0** | 13.2 / 41.4 → **13.5 / 13.9** | 131.4 / 178.0 → **318.2 / 471.1** | 46.5 / 55.3 → **103.4 / 112.6** |
| L2 presented | 181.3 / 305.8 → **67.7 / 79.0** | 83.5 / 176.6 → **13.5 / 13.9** | 611.3 / 728.4 → **318.2 / 471.1** | 260.4 / 266.4 → **103.4 / 112.6** |
| Entry EEZ added | 230.9 / 405.3 → **159.2 / 175.0** | 139.7 / 309.7 → **68.2 / 83.3** | 826.2 / 975.8 → **973.1 / 1,358.4** | 436.9 / 441.3 → **582.2 / 592.1** |
| L3 prepared | 2,216 / 2,238 → **2,184 / 2,195** | cached | 2,540 / 2,547 → **3,192 / 3,405** | cached |

L2 now shows up to ~2.7× sooner (normal CPU) and ~1.9× sooner (4×), because it no longer
waits for a packet. The price is a later, heavier first paint under 4× throttling:
decoding the whole L2 synchronously is one long task (282 ms max during load at 4×; 52 ms at
normal CPU), and the first bordered frame arrives ~190 ms later than the old L1 frame did.
Cold handoff long tasks after first paint at 4×: 54–107 ms (before 52–60 ms); none at normal
CPU, and none in the high-zoom resting handoff (largest paint slice 5.4 ms normal / 6.1 ms
at 4×). View state survived completion and interruption by new input; every sampled
interaction frame had borders.

| Interaction at 800 px (ms) | Normal draw p50 / p95 | Normal rAF p95 | 4× draw p50 / p95 | 4× rAF p95 | 4× levels |
|---|---:|---:|---:|---:|---|
| Africa/Europe drag, before | 2.8 / 3.8 | 34.6 | 5.6 / 7.6 | 104.6 | L1, L2 |
| Africa/Europe drag, after | 3.1 / 5.0 | 48.7 | 10.8 / 19.3 | 208.1 | L2 |
| Africa/Europe wheel, before | 1.2 / 2.5 | 22.4 | 3.3 / 4.9 | 83.5 | L1, L2 |
| Africa/Europe wheel, after | 1.4 / 2.8 | 27.0 | 4.1 / 9.8 | 85.2 | L2 |
| Pacific drag, before | 2.2 / 3.2 | 18.0 | 5.1 / 7.1 | 60.6 | L1, L2 |
| Pacific drag, after | 2.7 / 3.6 | 21.1 | 8.8 / 10.1 | 57.3 | L2 |
| Pacific wheel, before | 1.1 / 2.5 | 17.8 | 2.7 / 4.5 | 36.0 | L1, L2 |
| Pacific wheel, after | 1.1 / 2.2 | 20.2 | 2.8 / 7.7 | 39.1 | L2 |
| Pacific pinch, before | 0.8 / 1.8 | — | 3.5 / 8.2 | — | L2 |
| Pacific pinch, after | 1.4 / 3.1 | — | 2.2 / 6.0 | — | L2 |

At normal CPU every trace was L2 before and after. Under 4× throttling the old fallback
dropped part of every drag and wheel trace to L1 (the reported symptom); now they stay at L2
and stutter instead: the Africa/Europe drag, the densest view, draws in ~11 ms p50 and its frame
interval p95 doubled. No result here establishes a flat 60 fps under CPU throttling. A
single polygon can exceed the 4 ms slice target.

Browser results are a reproducible regression check, **not Anki Desktop or phone approval**.
The original recording showed roughly 2 seconds of blank globe area after the card shell.
Recheck that symptom in the same 10-entry EN/DE device packages after merge, then test phones:

```bash
.venv/bin/python -m cotw build-deck --only RU,KR,ZA,CW,CH,VA,SJ,KI,BO,ID --out build/device-test
```

## Why no vendored library

d3-geo + topojson-client would add ~60 KB and a license header for what amounts to one
projection, one clipping rule and a delta decoder. The hand-written renderer is plain JavaScript,
has no runtime dependency, and its pure parts (rotation, projection, horizon clipping incl.
antimeridian and pole cases, TopoJSON decoding, palette switch, highlight grouping) are
unit-tested with `node --test tests/js/*.test.js`.
