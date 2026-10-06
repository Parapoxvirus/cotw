/*
 * COTW globe: an interactive orthographic globe for the Countries of the World Anki deck.
 * Public domain (CC0 1.0), Parapoxvirus. Land: Natural Earth (public domain). Maritime
 * zones: Marine Regions, Flanders Marine Institute (VLIZ), CC BY 4.0.
 *
 * Built into media/_cotw-globe.js by `python -m cotw build-globe`, which embeds the L2
 * TopoJSON (the coarsest level) and writes the deferred packets _cotw-globe-zones.js (EEZs)
 * and _cotw-globe-detail.js (fine land). Template contract and
 * rendering rules: docs/GLOBE.md. Plain ES2017, no dependencies, no network.
 *
 *   <div class="cotw-globe" data-id="{{Locator}}" data-lang="de" data-tooltip></div>
 *   <script src="_cotw-globe.js"></script>
 */
(function (root) {
  'use strict';

  var VERSION = 11;
  var DATA_KEY = '', DATA_JSON = '';
  var DATA = null; // @@COTW_DATA@@

  // Anki desktop reuses the webview between cards and runs this script again for every
  // card: define once, (re)render every time. The data string is only scanned then, never
  // parsed again, and the decoded world stays on window (worldCache).
  if (root && root.COTWGlobe && root.COTWGlobe.version === VERSION && root.COTWGlobe.dataKey === DATA_KEY &&
      root.COTWGlobe.ready) {
    root.COTWGlobe.renderAll();
    if (Array.isArray(root.onShownHook) && root.onShownHook.indexOf(root.COTWGlobe.renderAll) < 0) {
      root.onShownHook.push(root.COTWGlobe.renderAll);
    }
    return;
  }
  // A different version already ran in this webview (deck update): retire its globes.
  if (root && root.COTWGlobe) (root.COTWGlobe.retire || root.COTWGlobe.destroyAll)();

  var RAD = Math.PI / 180;
  var ZOOM_MIN = 1;
  var ZOOM_MAX = 12;
  var SPHERE_FILL = 0.96; // sphere radius at zoom 1, relative to half the canvas side
  // Same rule as the SVG maps (docs/MAPS.md): the entry gets highlight circles when its
  // visible land covers less than 150/1000² of the canvas; circle radius ≥ 45/1000 of the
  // side; parts closer than that radius share one circle.
  var HIGHLIGHT_AREA = 150 / 1e6;
  var HIGHLIGHT_R = 0.045;
  // A circle around the entry's EEZ part keeps this margin (× side) and falls back to the
  // island circle when it would be larger than HIGHLIGHT_MAX_R × side (docs/GLOBE.md).
  var HIGHLIGHT_MARGIN = 0.008;
  var HIGHLIGHT_MAX_R = 0.45;
  var GRATICULE_STEP = 30;
  // Levels of detail (docs/GLOBE.md): the coarsest level whose simplification error, seen at
  // the current sphere radius, stays within this many CSS pixels. Interaction is capped below
  // the finest level, i.e. always L2. L2 is the coarsest level (issue #31): nothing, not even
  // slow frames, ever draws coarser.
  var LOD_REST_PX = 2.5;
  var PAINT_SLICE_MS = 4;
  var SETTLE_MS = 150; // redraw at full quality this long after the last drag/wheel event
  // A pressed pointer only starts a drag once it has moved this far (CSS px) from where it
  // went down; until then nothing rotates or redraws, and releasing it is a tap. Fingers
  // jitter more than a mouse.
  var TOUCH_SLOP_PX = 12;
  var MOUSE_SLOP_PX = 4;
  // Hit tolerance (issue #27): a tap or hover that misses all land picks the entry whose
  // drawn coast (or speck) is nearest within this many CSS px on screen, so small islands
  // can be hit. Fingers get more room than a mouse.
  var TOUCH_HIT_PX = 16;
  var MOUSE_HIT_PX = 6;
  // Fine land is loaded when a resting view needs it, or this long after all visible work is
  // done (deep idle), so a later zoom finds it ready.
  var DEEP_IDLE_MS = 2000;
  var PARTS = ['zones', 'detail'];
  // Tooltip box: gap above the anchor, offset below it (clear of a mouse cursor) when there
  // is no room above, and the minimum distance to every edge of the globe (CSS px).
  var TIP_GAP = 6;
  var TIP_BELOW = 18;
  var TIP_MARGIN = 2;

  // --- sphere math (pure) ------------------------------------------------------------

  function toVector(lon, lat) {
    var l = lon * RAD, p = lat * RAD, c = Math.cos(p);
    return [c * Math.cos(l), c * Math.sin(l), Math.sin(p)];
  }

  function toLonLat(v) {
    return [Math.atan2(v[1], v[0]) / RAD, Math.asin(Math.max(-1, Math.min(1, v[2]))) / RAD];
  }

  /** Orthonormal view basis for a globe centered on (lon0, lat0): e = screen right (east),
   *  n = screen up (north), c = toward the viewer (the center). */
  function viewBasis(lon0, lat0) {
    var l = lon0 * RAD, p = lat0 * RAD;
    var sl = Math.sin(l), cl = Math.cos(l), sp = Math.sin(p), cp = Math.cos(p);
    return {
      e: [-sl, cl, 0],
      n: [-sp * cl, -sp * sl, cp],
      c: [cp * cl, cp * sl, sp]
    };
  }

  /** Unit vector → view coordinates [x, y, z]; z > 0 is the visible hemisphere. */
  function project(v, b) {
    return [
      v[0] * b.e[0] + v[1] * b.e[1] + v[2] * b.e[2],
      v[0] * b.n[0] + v[1] * b.n[1] + v[2] * b.n[2],
      v[0] * b.c[0] + v[1] * b.c[1] + v[2] * b.c[2]
    ];
  }

  /** View coordinates on the unit disc → [lon, lat], or null outside the disc. */
  function invert(x, y, b) {
    var r2 = x * x + y * y;
    if (r2 > 1) return null;
    var z = Math.sqrt(1 - r2);
    return toLonLat([
      x * b.e[0] + y * b.n[0] + z * b.c[0],
      x * b.e[1] + y * b.n[1] + z * b.c[1],
      x * b.e[2] + y * b.n[2] + z * b.c[2]
    ]);
  }

  /** Point where the segment a→b crosses the horizon (z = 0), as a limb angle. */
  function limbAngle(a, b) {
    var t = a[2] / (a[2] - b[2]);
    return Math.atan2(a[1] + t * (b[1] - a[1]), a[0] + t * (b[0] - a[0]));
  }

  function shortest(a0, a1) {
    var d = a1 - a0;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d <= -Math.PI) d += 2 * Math.PI;
    return d;
  }

  /**
   * Horizon clipping for a closed ring of view coordinates (flat array x,y,z,x,y,z,…).
   * Visible stretches are drawn as they are; stretches behind the globe are replaced by the
   * limb arc between where the ring leaves and where it comes back, following the ring's
   * hidden part along the limb (always the shorter way between consecutive vertices), so
   * the fill stays exactly the visible part of the polygon. Rings entirely behind the
   * horizon draw nothing. Works for polygons smaller than a hemisphere (all land and EEZ).
   * Emits sink.move(x, y), sink.line(x, y), sink.arc(a0, a1) in unit-disc coordinates.
   * Returns false when nothing was emitted.
   */
  function clipRing(p, sink) {
    var n = p.length / 3, i0 = -1, i, k;
    for (i = 0; i < n; i++) if (p[3 * i + 2] > 0) { i0 = i; break; }
    if (i0 < 0) return false;
    sink.move(p[3 * i0], p[3 * i0 + 1]);
    var angle = 0;
    for (k = 1; k <= n; k++) {
      var a = 3 * ((i0 + k - 1) % n), b = 3 * ((i0 + k) % n);
      var av = p[a + 2] > 0, bv = p[b + 2] > 0;
      if (av && bv) {
        sink.line(p[b], p[b + 1]);
      } else if (av) {
        angle = limbAngle([p[a], p[a + 1], p[a + 2]], [p[b], p[b + 1], p[b + 2]]);
        sink.line(Math.cos(angle), Math.sin(angle));
      } else if (bv) {
        var enter = limbAngle([p[a], p[a + 1], p[a + 2]], [p[b], p[b + 1], p[b + 2]]);
        sink.arc(angle, angle + shortest(angle, enter));
        angle = enter;
        sink.line(p[b], p[b + 1]);
      } else if (p[b] * p[b] + p[b + 1] * p[b + 1] > 1e-12) {
        var next = Math.atan2(p[b + 1], p[b]);
        var d = shortest(angle, next);
        if (d !== 0) sink.arc(angle, angle + d);
        angle += d;
      }
    }
    return true;
  }

  /**
   * Horizon clipping for an open polyline (strokes). Emits visible runs only, ending
   * exactly on the limb where the line crosses it. `skip(i)` may veto segment i → i+1
   * (antimeridian and pole seams of the source data are not coastlines).
   */
  function clipLine(p, sink, skip) {
    var n = p.length / 3, pen = false;
    for (var i = 0; i + 1 < n; i++) {
      var a = 3 * i, b = a + 3;
      var av = p[a + 2] > 0, bv = p[b + 2] > 0;
      if ((!av && !bv) || (skip && skip(i))) { pen = false; continue; }
      if (av && bv) {
        if (!pen) sink.move(p[a], p[a + 1]);
        sink.line(p[b], p[b + 1]);
        pen = true;
      } else {
        var ang = limbAngle([p[a], p[a + 1], p[a + 2]], [p[b], p[b + 1], p[b + 2]]);
        if (av) {
          if (!pen) sink.move(p[a], p[a + 1]);
          sink.line(Math.cos(ang), Math.sin(ang));
          pen = false;
        } else {
          sink.move(Math.cos(ang), Math.sin(ang));
          sink.line(p[b], p[b + 1]);
          pen = true;
        }
      }
    }
  }

  // --- TopoJSON (pure) ----------------------------------------------------------------

  /** Decode delta-encoded, quantized arcs into lon/lat arrays [lon, lat, lon, lat, …]. */
  function decodeArc(arc, s, t) {
    if (typeof arc === 'string') arc = JSON.parse(arc); // deferred packets parse one arc at a time
    var out = new Float64Array(arc.length * 2), x = 0, y = 0;
    for (var i = 0; i < arc.length; i++) {
      x += arc[i][0]; y += arc[i][1];
      out[2 * i] = x * s[0] + t[0];
      out[2 * i + 1] = y * s[1] + t[1];
    }
    return out;
  }

  function decodeArcs(topology) {
    var s = topology.transform.scale, t = topology.transform.translate;
    return topology.arcs.map(function (arc) { return decodeArc(arc, s, t); });
  }

  /** Arcs decoded on first use: a level only pays for its own arcs. */
  function lazyArcs(topology) {
    var s = topology.transform.scale, t = topology.transform.translate, cache = [];
    return {
      get: function (i) { return cache[i] || (cache[i] = decodeArc(topology.arcs[i], s, t)); },
      decoded: function () { return cache.filter(Boolean).length; }
    };
  }

  function arcList(arcs) {
    return typeof arcs.get === 'function' ? arcs : { get: function (i) { return arcs[i]; } };
  }

  /** One ring from arc references (negative = ~index, reversed) → [lon, lat, …], open. */
  function ringCoords(refs, arcs) {
    var out = [], A = arcList(arcs);
    refs.forEach(function (ref) {
      var a = A.get(ref < 0 ? ~ref : ref), m = a.length / 2;
      for (var j = 0; j < m; j++) {
        var i = ref < 0 ? m - 1 - j : j;
        if (j === 0 && out.length) continue; // shared endpoint
        out.push(a[2 * i], a[2 * i + 1]);
      }
    });
    if (out.length >= 4 && out[0] === out[out.length - 2] && out[1] === out[out.length - 1]) out.length -= 2;
    return out;
  }

  function pointInRing(lon, lat, ring) {
    var inside = false, n = ring.length / 2;
    for (var i = 0, j = n - 1; i < n; j = i++) {
      var xi = ring[2 * i], yi = ring[2 * i + 1], xj = ring[2 * j], yj = ring[2 * j + 1];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  /** Seam bits of a vertex: the cuts of the source data it lies on (1 south pole, 2 north
   *  pole, 4 antimeridian; ±180° is one meridian). A corner where the 180° cut meets a pole
   *  carries both, so the segment up the meridian from it is a seam too (issue #33). */
  function seam(lon, lat) {
    return (lat <= -89.999 ? 1 : 0) | (lat >= 89.999 ? 2 : 0) | (lon <= -179.999 || lon >= 179.999 ? 4 : 0);
  }

  /** Whether segment i → i+1 of an arc with seam bits ``s`` runs along a cut (both ends on it). */
  function onSeam(s, i) {
    return (s[i] & s[i + 1]) !== 0;
  }

  /** Bounding cap (unit center vector + angular radius) of flat xyz vertex arrays. Every
   *  part gets one when it is prepared, so culling costs one dot product per part. */
  function boundingCap(vectors) {
    var sx = 0, sy = 0, sz = 0, i, k;
    for (k = 0; k < vectors.length; k++) {
      var v = vectors[k];
      for (i = 0; i < v.length; i += 3) { sx += v[i]; sy += v[i + 1]; sz += v[i + 2]; }
    }
    var len = Math.sqrt(sx * sx + sy * sy + sz * sz) || 1;
    var c = [sx / len, sy / len, sz / len], minDot = 1;
    for (k = 0; k < vectors.length; k++) {
      var w = vectors[k];
      for (i = 0; i < w.length; i += 3) minDot = Math.min(minDot, c[0] * w[i] + c[1] * w[i + 1] + c[2] * w[i + 2]);
    }
    return { cap: c, capR: Math.acos(Math.max(-1, Math.min(1, minDot))) };
  }

  /** Culling: can a part with this bounding cap reach the canvas? ``maxAngle`` is the angle
   *  from the view center beyond which nothing is on the canvas (the horizon, or the canvas
   *  corners when zoomed in). */
  function capVisible(cap, capR, center, maxAngle) {
    var d = cap[0] * center[0] + cap[1] * center[1] + cap[2] * center[2];
    return Math.acos(Math.max(-1, Math.min(1, d))) - capR < maxAngle;
  }

  /** Angle from the view center beyond which nothing reaches a canvas of ``side`` CSS px at
   *  sphere radius ``R``: the horizon (π/2) unless the zoomed sphere overfills the canvas. */
  function reachAngle(side, R) {
    var reach = Math.SQRT2 * side / 2 / R;
    return reach >= 1 ? Math.PI / 2 : Math.asin(reach);
  }

  /** Level of detail: the coarsest level whose tolerance (degrees), seen at the sphere radius
   *  ``R`` (CSS px), stays within ``maxPx``; the finest when none does. */
  function chooseLevel(tolerances, R, maxPx) {
    for (var i = 0; i < tolerances.length; i++) if (tolerances[i] * RAD * R <= maxPx) return i;
    return tolerances.length - 1;
  }

  function now() { return root.performance ? root.performance.now() : Date.now(); }

  /** Top-left corner (CSS px) of a ``w`` × ``h`` tooltip for the anchor (x, y) on a globe of
   *  ``side`` px: centered above the anchor, below it when there is no room above, and always
   *  clamped inside the globe, so names near the rim or a corner are never clipped. */
  function tipPlacement(x, y, w, h, side, margin) {
    var left = x - w / 2, top = y - h - TIP_GAP;
    if (top < margin) top = y + TIP_BELOW;
    left = Math.max(margin, Math.min(side - margin - w, left));
    top = Math.max(margin, Math.min(side - margin - h, top));
    return [Math.round(left), Math.round(top)];
  }

  /** One cap around several bounding caps (the parts of one entry). */
  function unionCap(items) {
    var sx = 0, sy = 0, sz = 0, r = 0;
    items.forEach(function (p) { sx += p.cap[0]; sy += p.cap[1]; sz += p.cap[2]; });
    var len = Math.sqrt(sx * sx + sy * sy + sz * sz);
    if (!len) return { cap: [0, 0, 1], capR: Math.PI };
    var c = [sx / len, sy / len, sz / len];
    items.forEach(function (p) {
      var d = c[0] * p.cap[0] + c[1] * p.cap[1] + c[2] * p.cap[2];
      r = Math.max(r, Math.acos(Math.max(-1, Math.min(1, d))) + p.capR);
    });
    return { cap: c, capR: Math.min(Math.PI, r) };
  }

  function capsOverlap(a, b) {
    var d = a.cap[0] * b.cap[0] + a.cap[1] * b.cap[1] + a.cap[2] * b.cap[2];
    return Math.acos(Math.max(-1, Math.min(1, d))) <= a.capR + b.capR;
  }

  function prepPolygon(rings) {
    var box = [180, 90, -180, -90];
    var out = rings.map(function (r) {
      var n = r.length / 2, v = new Float64Array(n * 3);
      for (var i = 0; i < n; i++) {
        var q = toVector(r[2 * i], r[2 * i + 1]);
        v[3 * i] = q[0]; v[3 * i + 1] = q[1]; v[3 * i + 2] = q[2];
        box[0] = Math.min(box[0], r[2 * i]); box[1] = Math.min(box[1], r[2 * i + 1]);
        box[2] = Math.max(box[2], r[2 * i]); box[3] = Math.max(box[3], r[2 * i + 1]);
      }
      return { ll: r, v: v };
    });
    var c = boundingCap(out.map(function (r) { return r.v; }));
    return { rings: out, cap: c.cap, capR: c.capR, box: box };
  }

  function prepGeometry(geom, arcs) {
    return (geom ? geom.arcs : []).map(function (poly) {
      return prepPolygon(poly.map(function (refs) { return ringCoords(refs, arcs); }).filter(function (r) { return r.length >= 6; }));
    }).filter(function (p) { return p.rings.length; });
  }

  /** One level of detail: polygons per entry, the other land, and the stroke mesh (every
   *  land arc of the level once, with per-vertex seam codes). */
  function levelJob(topology, arcs, entriesKey, otherKey) {
    var objs = topology.objects, A = arcList(arcs), entries = {}, other = [], mesh = [], used = {};
    var tasks = [], cursor = 0;
    function polygons(geom, target) {
      geom.arcs.forEach(function (poly) {
        poly.forEach(function (r) { r.forEach(function (a) { used[a < 0 ? ~a : a] = true; }); });
        tasks.push(function () {
          Array.prototype.push.apply(target, prepGeometry({ arcs: [poly] }, A));
        });
      });
    }
    if (entriesKey) {
      objs[entriesKey].geometries.forEach(function (g) { polygons(g, entries[g.id] = []); });
      polygons(objs[otherKey], other);
    } else {
      polygons(objs.eez, other);
      used = {}; // EEZ fills do not need a stroke mesh
    }
    Object.keys(used).map(Number).sort(function (a, b) { return a - b; }).forEach(function (i) {
      tasks.push(function () {
        var a = A.get(i), n = a.length / 2, v = new Float64Array(n * 3), s = new Uint8Array(n);
        for (var j = 0; j < n; j++) {
          var q = toVector(a[2 * j], a[2 * j + 1]);
          v[3 * j] = q[0]; v[3 * j + 1] = q[1]; v[3 * j + 2] = q[2];
          s[j] = seam(a[2 * j], a[2 * j + 1]);
        }
        var c = boundingCap([v]);
        mesh.push({ v: v, seam: s, cap: c.cap, capR: c.capR });
      });
    });
    return {
      result: { entries: entries, other: other, mesh: mesh },
      step: function (budget) {
        var start = now();
        while (cursor < tasks.length) {
          tasks[cursor++]();
          if (now() - start >= budget) break;
        }
        return cursor === tasks.length;
      }
    };
  }

  /** The decoded world, lazily: levels and EEZs are prepared on first use. Deferred data
   *  arrives as independent packets (``PARTS``), each keyed to this bootstrap. */
  function prepWorld(data) {
    var topo = data.topology, arcs = lazyArcs(topo), parts = {}, levelData = {}, zoneData = null, jobs = {};
    var lod = data.lod || [{ tolerance: 0, entries: 'entries', other: 'other' }];
    var W = {
      tolerances: lod.map(function (l) { return l.tolerance; }),
      // Level names for measurements and the debug view (L2 = coarsest, docs/GLOBE.md).
      names: lod.map(function (l, i) { return l.name || 'L' + i; }),
      levels: lod.map(function () { return null; }),
      eezCache: {},
      graticule: graticule(),
      meta: data.entries,
      palette: data.palette,
      arcs: arcs,
      readyAt: {}, // first time each level (L2, L3) / zone (EEZ:<id>) was prepared, for measurements
      installDetail: function (packet) {
        if (!packet || packet.key !== data.detailKey || PARTS.indexOf(packet.part) < 0 || parts[packet.part]) return false;
        parts[packet.part] = true;
        Object.keys(packet.levels || {}).forEach(function (i) { levelData[i] = packet.levels[i]; });
        if (packet.zones) zoneData = packet.zones;
        return true;
      },
      hasPart: function (name) { return !!parts[name]; },
      hasDetail: function () { return PARTS.every(W.hasPart); },
      /** Packet that carries level ``i``; null for bootstrap levels. */
      partOf: function (i) { return lod[i] && !topo.objects[lod[i].entries] ? lod[i].part || 'detail' : null; },
      prepareLevel: function (i) {
        if (W.levels[i]) return null;
        if (jobs[i]) return jobs[i];
        var source = topo, A = arcs;
        if (W.partOf(i)) {
          if (!levelData[i]) return null;
          source = JSON.parse(levelData[i]);
          A = lazyArcs(source);
        }
        var job = levelJob(source, A, lod[i].entries, lod[i].other);
        jobs[i] = { level: i, step: function (budget) {
          if (!job.step(budget)) return false;
          W.levels[i] = job.result;
          W.readyAt[W.names[i]] = now();
          delete jobs[i];
          return true;
        } };
        return jobs[i];
      },
      level: function (i) {
        // Synchronous preparation is only used for the bootstrap or by geometry tests.
        var job = W.prepareLevel(i);
        if (job) job.step(Infinity);
        return W.levels[i];
      },
      prepareEEZ: function (id) {
        if (id in W.eezCache || !zoneData) return null;
        if (!zoneData[id]) return { zone: id, step: function () { W.eezCache[id] = []; return true; } };
        var source = JSON.parse(zoneData[id]);
        var job = levelJob(source, lazyArcs(source));
        return { zone: id, step: function (budget) {
          if (!job.step(budget)) return false;
          W.eezCache[id] = job.result.other;
          W.readyAt['EEZ:' + id] = now();
          return true;
        } };
      },
      eez: function (id) {
        return W.eezCache[id] || []; // never parse or decode on the draw path
      }
    };
    return W;
  }

  /** The decoded world is kept on window: Anki desktop runs the script for every card in the
   *  same webview, and only the first card pays for decoding. Keyed by the script version and
   *  the data's hash, so a deck update never draws stale data. */
  function worldCache(host, key, make) {
    var c = host && host.__cotwGlobeWorld;
    if (c && c.key === key) return c.world;
    var world = make();
    if (host) host.__cotwGlobeWorld = { key: key, world: world };
    return world;
  }

  function graticule() {
    var lines = [], lon, lat, pts;
    for (lon = -180; lon < 180; lon += GRATICULE_STEP) {
      pts = [];
      for (lat = -90; lat <= 90; lat += 2) pts.push(toVector(lon, lat));
      lines.push(pts);
    }
    for (lat = -90 + GRATICULE_STEP; lat < 90; lat += GRATICULE_STEP) {
      pts = [];
      for (lon = -180; lon <= 180; lon += 2) pts.push(toVector(lon, lat));
      lines.push(pts);
    }
    return lines.map(function (l) {
      var v = new Float64Array(l.length * 3);
      l.forEach(function (q, i) { v[3 * i] = q[0]; v[3 * i + 1] = q[1]; v[3 * i + 2] = q[2]; });
      return { v: v, cap: [0, 0, 1], capR: Math.PI };
    });
  }

  // --- theme (pure) --------------------------------------------------------------------

  /** Night palette exactly when the card is in Anki's night mode: .nightMode on the card,
   *  body or html (.night_mode in AnkiDroid and older clients). The system color scheme is
   *  ignored on purpose: Anki's own setting decides (docs/GLOBE.md). */
  function isNight(el) {
    return !!(el && el.closest && el.closest('.nightMode, .night_mode'));
  }

  function paletteFor(palette, night) {
    return palette[night ? 'night' : 'day'];
  }

  /** Group screen points (parts of a tiny entry) into highlight circles. A point may carry
   *  the index of the EEZ part it lies in (``[x, y, k]``); ``zones[k]`` is that part's
   *  outline in screen points, or null when it is not fully on the visible hemisphere. A
   *  group's circle encloses its EEZ parts (docs/GLOBE.md); fallback to the island circle
   *  when a part is not fully visible or the circle would exceed HIGHLIGHT_MAX_R × side. */
  function highlightCircles(parts, side, zones) {
    var minR = HIGHLIGHT_R * side, groups = [];
    parts.forEach(function (p) {
      var hit = null;
      groups.forEach(function (g) {
        if (!hit && p[0] >= g.box[0] - minR && p[0] <= g.box[2] + minR && p[1] >= g.box[1] - minR && p[1] <= g.box[3] + minR) hit = g;
      });
      if (hit) {
        hit.box = [Math.min(hit.box[0], p[0]), Math.min(hit.box[1], p[1]), Math.max(hit.box[2], p[0]), Math.max(hit.box[3], p[1])];
      } else {
        groups.push(hit = { box: [p[0], p[1], p[0], p[1]], pts: [], zones: [] });
      }
      hit.pts.push(p);
      if (p[2] >= 0 && hit.zones.indexOf(p[2]) < 0) hit.zones.push(p[2]);
    });
    function circle(g) {
      var b = g.box, usable = g.zones.length > 0 && zones;
      g.zones.forEach(function (k) { if (!zones || !zones[k]) usable = false; });
      if (usable) {
        var pts = g.pts.slice();
        g.zones.forEach(function (k) { pts = pts.concat(zones[k]); });
        var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        pts.forEach(function (q) { x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]); });
        var cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, r = 0;
        pts.forEach(function (q) { r = Math.max(r, Math.hypot(q[0] - cx, q[1] - cy)); });
        r += HIGHLIGHT_MARGIN * side;
        if (r <= HIGHLIGHT_MAX_R * side) return [cx, cy, Math.max(minR, r)];
      }
      var w = b[2] - b[0], h = b[3] - b[1];
      return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, Math.max(minR, Math.sqrt(w * w + h * h) / 2 + minR * 0.5)];
    }
    // Groups whose circles would overlap become one group (one clean circle, not a chain).
    for (var merged = true; merged;) {
      merged = false;
      var circles = groups.map(circle);
      for (var i = 0; i < groups.length && !merged; i++) {
        for (var j = i + 1; j < groups.length && !merged; j++) {
          var a = circles[i], c = circles[j];
          if (Math.hypot(a[0] - c[0], a[1] - c[1]) < a[2] + c[2]) {
            var g = groups[i], o = groups[j];
            g.box = [Math.min(g.box[0], o.box[0]), Math.min(g.box[1], o.box[1]), Math.max(g.box[2], o.box[2]), Math.max(g.box[3], o.box[3])];
            g.pts = g.pts.concat(o.pts);
            o.zones.forEach(function (k) { if (g.zones.indexOf(k) < 0) g.zones.push(k); });
            groups.splice(j, 1);
            merged = true;
          }
        }
      }
    }
    return groups.map(circle);
  }

  /** EEZ hulls of an entry (``meta.e``, lon/lat) as unit vectors plus, per edge, the plane
   *  normal signed so the inside is positive: ``inZone`` then is a dot product per edge. */
  function prepZones(hulls) {
    return (hulls || []).map(function (ring) {
      var v = ring.map(function (ll) { return toVector(ll[0], ll[1]); }), c = [0, 0, 0];
      v.forEach(function (p) { c[0] += p[0]; c[1] += p[1]; c[2] += p[2]; });
      var planes = v.map(function (a, i) {
        var b = v[(i + 1) % v.length];
        var n = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
        var s = n[0] * c[0] + n[1] * c[1] + n[2] * c[2] < 0 ? -1 : 1;
        return [s * n[0], s * n[1], s * n[2]];
      });
      return { v: v, planes: planes };
    });
  }

  function inZone(zone, p) {
    for (var i = 0; i < zone.planes.length; i++) {
      var n = zone.planes[i];
      if (n[0] * p[0] + n[1] * p[1] + n[2] * p[2] < 0) return false;
    }
    return true;
  }

  /**
   * Hit tolerance (issue #27): the entry whose land comes nearest to the canvas point
   * (``px``, ``py``, CSS px) within ``tol`` CSS px on screen, or null. Each polygon of level
   * ``L`` is its own target, so an island gets the margin and not a box around its whole
   * country; islands the globe does not draw (``meta[id].s``) are point targets. Only
   * entries: ``other`` land (Antarctica, Bir Tawil, …) never is. The nearest coast wins;
   * equal distances go to the lower id. ``b``, ``R``, ``cx``, ``cy``: the drawn view.
   * Returns { id, ll, px } with ``ll`` the nearest coast point on the sphere (the tooltip
   * anchor sits on the island, not in the sea) and ``px`` its distance.
   */
  function nearestEntry(L, meta, b, R, cx, cy, px, py, tol) {
    var ux = (px - cx) / R, uy = (cy - py) / R, t = tol / R; // unit-disc coordinates
    var best = null, bestD = t * t, bx = 0, by = 0;
    var e = b.e, n = b.n, c = b.c;
    function consider(id, x, y, d) {
      // Strictly nearer only: ids are visited in sorted order, so ties keep the lower id.
      if (d < bestD || (!best && d <= bestD)) { best = id; bestD = d; bx = x; by = y; }
    }
    var ids = Object.keys(meta).sort();
    for (var k = 0; k < ids.length; k++) {
      var id = ids[k], polys = L.entries[id] || [], specks = meta[id].s || [];
      for (var p = 0; p < polys.length; p++) {
        var poly = polys[p], cap = poly.cap;
        // The projection is 1-Lipschitz: the polygon lies within the cap's chord of the
        // cap center's projection. Skip it when that disc is out of reach or behind.
        if (!capVisible(cap, poly.capR, c, Math.PI / 2)) continue;
        var qx = cap[0] * e[0] + cap[1] * e[1] + cap[2] * e[2];
        var qy = cap[0] * n[0] + cap[1] * n[1] + cap[2] * n[2];
        var reach = Math.sqrt(bestD) + 2 * Math.sin(poly.capR / 2);
        if ((qx - ux) * (qx - ux) + (qy - uy) * (qy - uy) > reach * reach) continue;
        for (var r = 0; r < poly.rings.length; r++) {
          var v = poly.rings[r].v, m = v.length / 3;
          var j = m - 1, x0 = v[3 * j] * e[0] + v[3 * j + 1] * e[1] + v[3 * j + 2] * e[2];
          var y0 = v[3 * j] * n[0] + v[3 * j + 1] * n[1] + v[3 * j + 2] * n[2];
          var z0 = v[3 * j] * c[0] + v[3 * j + 1] * c[1] + v[3 * j + 2] * c[2];
          for (var i = 0; i < m; i++) {
            var x1 = v[3 * i] * e[0] + v[3 * i + 1] * e[1] + v[3 * i + 2] * e[2];
            var y1 = v[3 * i] * n[0] + v[3 * i + 1] * n[1] + v[3 * i + 2] * n[2];
            var z1 = v[3 * i] * c[0] + v[3 * i + 1] * c[1] + v[3 * i + 2] * c[2];
            if (z0 > 0 || z1 > 0) {
              // Visible part of the segment: a segment crossing the horizon ends on the limb.
              var ax = x0, ay = y0, sx = x1, sy = y1;
              if (z0 <= 0 || z1 <= 0) {
                var h = z0 / (z0 - z1), hx = x0 + h * (x1 - x0), hy = y0 + h * (y1 - y0);
                if (z0 <= 0) { ax = hx; ay = hy; } else { sx = hx; sy = hy; }
              }
              var dx = sx - ax, dy = sy - ay, len = dx * dx + dy * dy;
              var f = len ? Math.max(0, Math.min(1, ((ux - ax) * dx + (uy - ay) * dy) / len)) : 0;
              var nx = ax + f * dx, ny = ay + f * dy;
              consider(id, nx, ny, (nx - ux) * (nx - ux) + (ny - uy) * (ny - uy));
            }
            x0 = x1; y0 = y1; z0 = z1;
          }
        }
      }
      for (var s = 0; s < specks.length; s++) {
        var w = toVector(specks[s][0], specks[s][1]);
        if (w[0] * c[0] + w[1] * c[1] + w[2] * c[2] <= 0) continue;
        var wx = w[0] * e[0] + w[1] * e[1] + w[2] * e[2], wy = w[0] * n[0] + w[1] * n[1] + w[2] * n[2];
        consider(id, wx, wy, (wx - ux) * (wx - ux) + (wy - uy) * (wy - uy));
      }
    }
    if (!best) return null;
    var r2 = bx * bx + by * by;
    if (r2 >= 1) { r2 = (1 - 1e-12) / Math.sqrt(r2); bx *= r2; by *= r2; } // a limb point, rounded
    return { id: best, ll: invert(bx, by, b), px: Math.sqrt(bestD) * R };
  }

  /** The embedded data, parsed on first use (null in the unbuilt source). */
  function data() {
    if (!DATA && DATA_JSON) DATA = JSON.parse(DATA_JSON);
    return DATA;
  }

  var api = {
    toVector: toVector, toLonLat: toLonLat, viewBasis: viewBasis, project: project, invert: invert,
    clipRing: clipRing, clipLine: clipLine, decodeArcs: decodeArcs, lazyArcs: lazyArcs, ringCoords: ringCoords,
    pointInRing: pointInRing, seam: seam, onSeam: onSeam, isNight: isNight, paletteFor: paletteFor,
    highlightCircles: highlightCircles, prepZones: prepZones, inZone: inZone, prepWorld: prepWorld, worldCache: worldCache, data: data,
    boundingCap: boundingCap, capVisible: capVisible, reachAngle: reachAngle, chooseLevel: chooseLevel,
    tipPlacement: tipPlacement, unionCap: unionCap,
    capsOverlap: capsOverlap, prepPolygon: prepPolygon, nearestEntry: nearestEntry, hit: hit, VERSION: VERSION, DATA_KEY: DATA_KEY, TIP_MARGIN: TIP_MARGIN,
    ZOOM_MIN: ZOOM_MIN, ZOOM_MAX: ZOOM_MAX, HIGHLIGHT_AREA: HIGHLIGHT_AREA, HIGHLIGHT_R: HIGHLIGHT_R,
    HIGHLIGHT_MARGIN: HIGHLIGHT_MARGIN, HIGHLIGHT_MAX_R: HIGHLIGHT_MAX_R,
    LOD_REST_PX: LOD_REST_PX,
    TOUCH_HIT_PX: TOUCH_HIT_PX, MOUSE_HIT_PX: MOUSE_HIT_PX, SPHERE_FILL: SPHERE_FILL
  };

  if (typeof module === 'object' && module.exports) {
    module.exports = api; // unit tests (node --test); no DOM needed
  }
  if (typeof document === 'undefined' || !DATA_JSON) return;

  // --- rendering (DOM) -------------------------------------------------------------------

  var instances = [], retired = false, decoding = false, activeJob = null;
  var idleHandle = 0, paintHandle = 0, deepHandle = 0;
  // Deferred packets: script element while loading/loaded, and whether loading failed on
  // this card (retried on the next card, never in a loop).
  var partScripts = {}, partFailed = {};
  // All paths are local packaged media. Capture currentScript before any async callback.
  var script = document.currentScript;
  var detailBase = script && script.src ? script.src.replace(/[^/]*$/, '') : '';
  // Some reviewers evaluate a template script without currentScript. The same hashed
  // media references are on the globe element, so they never fall back to an unshipped name.
  var partNames = {};
  PARTS.forEach(function (part) {
    var attr = 'data-' + part + '-src', fallback = '_cotw-globe-' + part + '.js';
    var config = script && script.getAttribute && script.getAttribute(attr) ? script : document.querySelector('.cotw-globe[' + attr + ']');
    var name = config && config.getAttribute(attr) || fallback;
    partNames[part] = new RegExp('^_cotw-globe-' + part + '(?:-[0-9a-f]{8})?\\.js$').test(name) ? name : fallback;
  });
  function idle(fn) {
    idleHandle = root.requestIdleCallback ? root.requestIdleCallback(fn, { timeout: 500 }) : root.setTimeout(fn, 30);
  }

  // The next slice of work already started in idle time: a plain task right after this one,
  // so input and frames still run between 4 ms slices. A callback requested inside an idle
  // period waits for the next idle period (up to 50 ms in Chromium when nothing renders),
  // which made every slice cost a whole period. Callers re-check their state (retired,
  // cancelled paint), so a queued slice needs no cancel handle.
  var soonQueue = [], soonPort = null;
  function soon(fn) {
    if (!root.MessageChannel) { root.setTimeout(fn, 0); return; }
    if (!soonPort) {
      var channel = new root.MessageChannel();
      channel.port1.onmessage = function () {
        var next = soonQueue.shift();
        if (next) next();
      };
      soonPort = channel.port2;
    }
    soonQueue.push(fn);
    soonPort.postMessage(0);
  }

  function getWorld() {
    return worldCache(root, VERSION + ':' + DATA_KEY, function () { return prepWorld(data()); });
  }

  function readyLevels(W) {
    return W.levels.map(Boolean);
  }

  function liveGlobes() {
    return instances.filter(function (g) { return g.alive && document.documentElement.contains(g.el); });
  }

  /** Load one deferred packet as local media (at most once; a failure keeps the best bordered
   *  level and is retried on the next card). ``ordered`` scripts execute in request order. */
  function loadPart(part, ordered) {
    if (retired || partScripts[part] || partFailed[part] || getWorld().hasPart(part)) return;
    var el = partScripts[part] = document.createElement('script');
    el.src = detailBase + partNames[part];
    el.async = !ordered;
    el.onerror = function () {
      if (partScripts[part] === el) delete partScripts[part];
      partFailed[part] = true;
      if (el.parentNode) el.parentNode.removeChild(el);
    };
    (document.head || document.documentElement).appendChild(el);
  }

  /** Fine land after deep idle: all visible levels and zones are done and nobody interacts. */
  function scheduleDeepIdle() {
    if (deepHandle || retired || getWorld().hasPart('detail')) return;
    deepHandle = root.setTimeout(function () {
      deepHandle = 0;
      if (retired) return;
      var live = liveGlobes();
      if (!live.length) return;
      if (decoding || live.some(function (g) { return g.busy(); })) return scheduleDeepIdle();
      loadPart('detail');
    }, DEEP_IDLE_MS);
  }

  // Background preparation parked while a globe is busy: polled in idle time, and resumed
  // right away when a staged image has been presented.
  var parked = null;
  function park(step) {
    var token = parked = { step: step }; // one token per park: a stale poll never takes over
    idle(function () {
      if (parked !== token) return; // already resumed or parked again
      parked = null;
      step();
    });
  }
  function resumeDecode() {
    var token = parked;
    if (!token) return;
    parked = null;
    soon(token.step);
  }

  /** Prepare polygons/arcs in <=4 ms slices, yielding between them, during interaction, and
   *  while a resting image is being painted (so each improvement is presented in order).
   *  A level is published atomically, so fills and their shared borders always agree. */
  function decodeInBackground() {
    if (decoding || retired) return;
    decoding = true;
    // Always requested after the first paint: start with a plain task, not the next idle period.
    soon(function step() {
      if (retired) return;
      var live = liveGlobes();
      if (!live.length) { decoding = false; return; }
      if (live.some(function (g) { return g.busy(); })) {
        park(step);
        return;
      }
      var W = getWorld(), i, last = W.levels.length - 1, next = null;
      if (!activeJob || activeJob.level === last) {
        // Intermediate levels first (none: the first paint decodes L2, the coarsest), then
        // visible EEZs, then fine land, which only a resting high-zoom view or deep idle
        // requests. Fine land is resumable, so it yields to a new card's zone instead of
        // delaying it.
        for (i = 0; i < last && !next; i++) next = W.prepareLevel(i);
        for (i = 0; i < live.length && !next; i++) next = W.prepareEEZ(live[i].id);
        activeJob = next || activeJob || W.prepareLevel(last);
      }
      if (!activeJob) {
        decoding = false;
        scheduleDeepIdle();
        return;
      }
      if (activeJob.step(4)) {
        var completed = activeJob;
        activeJob = null;
        live.forEach(function (g) {
          // Any improvement toward the wanted level is staged right away (L2 before L3); the
          // staged paint holds further preparation back until it is presented.
          if ('level' in completed ? g.waitingFor >= 0 : g.id === completed.zone) g.refresh();
        });
      }
      soon(step);
    });
  }

  function acceptDetail(packet) {
    if (retired || !getWorld().installDetail(packet)) return false;
    decodeInBackground();
    return true;
  }

  function afterPaint() {
    if (paintHandle || retired) return;
    // A single rAF runs before paint. Two callbacks ensure the first canvas is presented
    // before even requesting deferred packets (including on cached, subsequent cards).
    paintHandle = root.requestAnimationFrame(function () {
      paintHandle = root.requestAnimationFrame(function () {
        paintHandle = 0;
        if (retired) return;
        partFailed = {}; // a new card retries packets that were missing before
        // Stage the best ready level now (a warm cache: L3 or the EEZ right away), before any
        // background preparation can claim the next idle period.
        instances.forEach(function (g) { if (g.alive) g.refresh(); });
        decodeInBackground();
        loadPart('zones', true);
      });
    });
  }

  function Globe(el) {
    this.el = el;
    this.alive = true;
    this.frame = 0;
    this.pointers = {};
    this.lastTap = 0;
    this.interacting = false;
    this.waitingFor = -1;
    this.presented = {};
    // One selection drives both the tooltip and the selected fill (back sides only).
    this.selected = null;
    this.anchor = null;
    this.shownSelection = null;
    this.hoverAt = null;
    this.hoverFrame = this.selectFrame = 0;
    el.__cotwGlobe = this;
    if (root.getComputedStyle && root.getComputedStyle(el).position === 'static') el.style.position = 'relative';
    this.canvas = document.createElement('canvas');
    this.canvas.style.cssText = 'display:block;width:100%;touch-action:none;cursor:grab';
    this.tip = document.createElement('div');
    // Positioned by placeTip (clamped inside the globe); long names wrap within its width.
    this.tip.style.cssText = 'position:absolute;pointer-events:none;display:none;padding:2px 6px;border-radius:4px;' +
      'font:inherit;font-size:13px;line-height:1.3;width:max-content;box-sizing:border-box;text-align:center;' +
      'overflow-wrap:break-word;left:0;top:0;z-index:1';
    el.appendChild(this.canvas);
    el.appendChild(this.tip);
    this.ctx = this.canvas.getContext('2d');
    this.configure();
    this.listen();
    this.resize(true);
  }

  /** Read the element's attributes. A new entry resets the view; nothing is drawn here (the
   *  caller draws once). */
  Globe.prototype.configure = function () {
    var id = this.el.getAttribute('data-id');
    id = id ? String(id).trim() : '';
    // The tooltip shows m.name[lang], falling back to English for a language without names.
    this.lang = this.el.getAttribute('data-lang') || 'en';
    this.tooltip = this.el.hasAttribute('data-tooltip') && this.el.getAttribute('data-tooltip') !== 'false';
    if (!this.tooltip) this.select(null);
    if (id !== this.id) {
      this.id = id;
      this.stats = null; // a reviewer may reuse the element for a new card
      this.presented = {};
      this.setView();
      this.dirty = true;
    }
    if (isNight(this.el) !== this.night) {
      // Anki switched night mode: the repaint below drops the selection with the tooltip.
      if (this.night !== undefined) this.clearSelection();
      this.dirty = true;
    }
  };

  /** Held or settling input, or a staged resting image: deferred work waits, so interaction
   *  frames stay cheap and every improvement is presented before the next one is prepared. */
  Globe.prototype.busy = function () {
    return this.interacting || Object.keys(this.pointers).length > 0 || !!this.pendingPaint;
  };

  Globe.prototype.setView = function () {
    var m = getWorld().meta[this.id];
    this.meta = m || null;
    this.lon = m ? m.c[0] : 0;
    this.lat = m ? m.c[1] : 20;
    this.zoom = m ? m.z : 1;
    // A new card or a reset view starts without a selection (a double-tap reset never
    // selects: it clears what its first tap selected).
    this.select(null);
    this.neighbors = {};
    if (m) m.n.forEach(function (n) { this.neighbors[n] = true; }, this);
  };

  Globe.prototype.reset = function () {
    this.setView();
    this.schedule();
  };

  /** Dragging, pinching or wheeling: L2 land and shared borders until SETTLE_MS after the
   *  last event; then one redraw at resting quality. */
  Globe.prototype.interact = function () {
    var self = this;
    this.interacting = true;
    this.cancelPaint();
    if (this.settle) root.clearTimeout(this.settle);
    this.settle = root.setTimeout(function () {
      self.settle = 0;
      if (Object.keys(self.pointers).length) return self.interact(); // still held down
      self.interacting = false;
      self.schedule();
      decodeInBackground();
    }, SETTLE_MS);
  };

  Globe.prototype.listen = function () {
    var self = this, c = this.canvas;
    this.handlers = {
      pointerdown: function (e) {
        // Nothing changes yet: a tap must not switch to the interaction level. The drag
        // (and interact()) starts once the pointer leaves its slop.
        self.pointers[e.pointerId] = {
          x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, moved: false,
          slop: e.pointerType === 'mouse' ? MOUSE_SLOP_PX : TOUCH_SLOP_PX
        };
        if (c.setPointerCapture) c.setPointerCapture(e.pointerId);
        var ids = Object.keys(self.pointers);
        if (ids.length === 2) {
          self.interact();
          var a = self.pointers[ids[0]], b = self.pointers[ids[1]];
          self.pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, zoom: self.zoom };
          // Fingers of a pinch never count as taps; the one left after it rotates at once.
          a.multi = b.multi = a.moved = b.moved = true;
        }
      },
      pointermove: function (e) {
        var p = self.pointers[e.pointerId];
        if (!p) {
          if (e.pointerType === 'mouse') self.hoverLater(e);
          return;
        }
        if (!p.moved) {
          if (Math.hypot(e.clientX - p.x0, e.clientY - p.y0) <= p.slop) return;
          // Left the slop: the drag starts here (L2 interaction frame, same view) and
          // rotates from this point on, without jumping by the distance covered so far.
          p.moved = true;
          p.x = e.clientX; p.y = e.clientY;
          self.interact();
          self.schedule();
          return;
        }
        var dx = e.clientX - p.x, dy = e.clientY - p.y;
        p.x = e.clientX; p.y = e.clientY;
        var ids = Object.keys(self.pointers);
        if (ids.length >= 2 && self.pinch) {
          var a = self.pointers[ids[0]], b = self.pointers[ids[1]];
          self.interact();
          self.setZoom(self.pinch.zoom * Math.hypot(a.x - b.x, a.y - b.y) / self.pinch.d);
        } else if (ids.length === 1 && (dx || dy)) {
          var k = 1 / (self.radius() * RAD);
          self.lon -= dx * k;
          self.lat = Math.max(-89.9, Math.min(89.9, self.lat + dy * k));
          while (self.lon > 180) self.lon -= 360;
          while (self.lon < -180) self.lon += 360;
          self.interact();
          self.schedule();
        }
      },
      pointerup: function (e) {
        var p = self.pointers[e.pointerId];
        delete self.pointers[e.pointerId];
        if (Object.keys(self.pointers).length < 2) self.pinch = null;
        // Drags and pinch fingers never select; the selection just follows the globe.
        if (!p || p.multi || p.moved || Math.hypot(e.clientX - p.x0, e.clientY - p.y0) > p.slop) return;
        // A tap: double tap resets (touch) and clears the selection; a single tap selects the
        // country under it (tooltip + fill), switches to another one, or clears on the sea.
        var now = Date.now();
        if (e.pointerType !== 'mouse' && now - self.lastTap < 350) {
          self.lastTap = 0;
          self.reset();
          return;
        }
        self.lastTap = now;
        // Where the finger went down, not where the jitter ended.
        self.pointAt(p.x0, p.y0, e.pointerType === 'mouse' ? MOUSE_HIT_PX : TOUCH_HIT_PX);
      },
      pointercancel: function (e) {
        delete self.pointers[e.pointerId];
        self.pinch = null;
      },
      pointerleave: function (e) {
        if (e.pointerType !== 'mouse') return;
        if (self.hoverFrame) root.cancelAnimationFrame(self.hoverFrame);
        self.hoverFrame = 0;
        self.hoverAt = null;
        self.select(null);
      },
      dblclick: function (e) {
        e.preventDefault();
        self.reset();
      },
      wheel: function (e) {
        e.preventDefault();
        self.interact();
        self.setZoom(self.zoom * Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)));
      }
    };
    Object.keys(this.handlers).forEach(function (k) {
      c.addEventListener(k, self.handlers[k], k === 'wheel' ? { passive: false } : false);
    });
    if (root.ResizeObserver) {
      // Resize in the next frame: resizing inside the callback changes the observed
      // element's height and would trigger a "ResizeObserver loop" error. The first callback
      // (right after observe) finds the size unchanged and draws nothing.
      this.observer = new root.ResizeObserver(function () { self.needsResize = true; self.schedule(false); });
      this.observer.observe(this.el);
    } else {
      this.onResize = function () { self.resize(false); };
      root.addEventListener('resize', this.onResize);
    }
  };

  Globe.prototype.destroy = function () {
    if (!this.alive) return;
    this.alive = false;
    this.cancelPaint();
    this.clearSelection();
    if (this.buffer) this.buffer.width = this.buffer.height = 0;
    if (this.base) this.base.width = this.base.height = 0;
    this.buffer = this.base = this.baseInfo = null;
    var self = this, c = this.canvas;
    Object.keys(this.handlers).forEach(function (k) { c.removeEventListener(k, self.handlers[k], k === 'wheel' ? { passive: false } : false); });
    if (this.observer) this.observer.disconnect();
    if (this.onResize) root.removeEventListener('resize', this.onResize);
    if (this.frame) root.cancelAnimationFrame(this.frame);
    if (this.settle) root.clearTimeout(this.settle);
    this.frame = this.settle = 0;
    if (this.canvas.parentNode) this.canvas.parentNode.removeChild(this.canvas);
    if (this.tip.parentNode) this.tip.parentNode.removeChild(this.tip);
    this.canvas.width = this.canvas.height = 0; // release the pixel buffer
    this.ctx = null;
    if (this.el.__cotwGlobe === this) delete this.el.__cotwGlobe;
  };

  Globe.prototype.setZoom = function (z) {
    this.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    this.schedule();
  };

  /** Draw in the next animation frame (at most once per frame). ``dirty`` = false only asks
   *  for the pending resize check. */
  Globe.prototype.schedule = function (dirty) {
    var self = this;
    if (dirty !== false) this.dirty = true;
    if (this.frame || !this.alive) return;
    var requested = now();
    this.frame = root.requestAnimationFrame(function () {
      self.frame = 0;
      // Includes browser raster/paint work after the previous draw, which stats.ms misses
      // (measurements only: slow frames never step below L2, issue #31).
      self.frameWaitMs = now() - requested;
      if (self.needsResize) self.resize(false);
      if (self.dirty) self.draw();
    });
  };

  /** Draw now instead of in the next frame. At rest this only stages a paint (published by
   *  its own animation frame); during interaction the frame loop keeps drawing. */
  Globe.prototype.refresh = function () {
    if (this.interacting) return this.schedule();
    if (this.frame) { root.cancelAnimationFrame(this.frame); this.frame = 0; }
    this.dirty = true;
    if (this.needsResize) this.resize(false);
    if (this.dirty) this.draw();
  };

  /** Match the canvas to the element; draws when the size changed or ``force``. */
  Globe.prototype.resize = function (force) {
    // The canvas's own width (100 % of the content box), so padding on the element
    // cannot make the globe non-square.
    this.needsResize = false;
    var w = this.canvas.clientWidth;
    if (!w) return false;
    var dpr = root.devicePixelRatio || 1, px = Math.round(w * dpr);
    var changed = this.canvas.width !== px || this.canvas.height !== px || this.side !== w || this.dpr !== dpr;
    if (changed) {
      this.canvas.width = px;
      this.canvas.height = px;
      this.canvas.style.height = w + 'px';
      this.side = w;
      this.dpr = dpr;
      this.stats = null; // a resized canvas is blank: present bordered L2 synchronously
      this.paintKey = null;
    }
    if (changed || force || this.dirty) this.draw();
    if (changed) afterPaint();
    return changed;
  };

  /** Sphere radius in CSS pixels. */
  Globe.prototype.radius = function () {
    return (this.side || 1) / 2 * SPHERE_FILL * this.zoom;
  };

  /** The first draw always uses the bootstrap level (L2, the coarsest). Later draws never
   *  prepare a missing level: until the wanted one is ready they keep L2, which the first
   *  draw decoded, so no frame is ever coarser than L2 (issue #31). Interaction is capped
   *  below the finest level: always L2. */
  Globe.prototype.pickLevel = function (W, R) {
    var want = chooseLevel(W.tolerances, R, LOD_REST_PX);
    if (this.interacting) want = Math.max(0, Math.min(want, W.levels.length - 2));
    if (!this.stats) W.level(0);
    var have = this.stats && W.levels[want] ? want : 0;
    this.waitingFor = have === want ? -1 : want;
    return have;
  };

  /** State a resting image belongs to. Compare again before publication: input, resize,
   *  card replacement and Anki theme changes must never publish a stale image. */
  Globe.prototype.viewKey = function () {
    return [this.id, this.lon, this.lat, this.zoom, this.side, this.dpr, isNight(this.el)].join(':');
  };

  /** Queued slices of a dropped paint find it is no longer pending and stop. */
  Globe.prototype.cancelPaint = function () {
    if (this.presentFrame) root.cancelAnimationFrame(this.presentFrame);
    this.presentFrame = 0;
    this.pendingPaint = null;
  };

  /** Projection state of one frame: palette, basis, radius, culling and a path sink. */
  function frameOf(g, ctx, W, level) {
    var side = g.side, night = isNight(g.el), R = g.radius(), cx = side / 2, cy = side / 2;
    var b = viewBasis(g.lon, g.lat), maxAngle = reachAngle(side, R), buf = new Float64Array(0);
    var sink = {
      move: function (x, y) { ctx.moveTo(cx + R * x, cy - R * y); },
      line: function (x, y) { ctx.lineTo(cx + R * x, cy - R * y); },
      arc: function (a0, a1) { ctx.arc(cx, cy, R, -a0, -a1, a1 > a0); }
    };
    function view(v) {
      if (buf.length < v.length) buf = new Float64Array(v.length * 2);
      var out = buf.subarray(0, v.length);
      for (var i = 0; i < v.length; i += 3) {
        var x = v[i], y = v[i + 1], z = v[i + 2];
        out[i] = x * b.e[0] + y * b.e[1] + z * b.e[2];
        out[i + 1] = x * b.n[0] + y * b.n[1] + z * b.n[2];
        out[i + 2] = x * b.c[0] + y * b.c[1] + z * b.c[2];
      }
      return out;
    }
    return {
      side: side, night: night, pal: paletteFor(W.palette, night), R: R, cx: cx, cy: cy, b: b,
      L: W.levels[level], sink: sink, view: view,
      // Parts whose bounding cap cannot reach the canvas are skipped before projecting.
      visible: function (item) { return capVisible(item.cap, item.capR, b.c, maxAngle); },
      /** Adds one polygon's rings to the current path; returns its vertex count. */
      polygon: function (poly) {
        var vertices = 0;
        poly.rings.forEach(function (r) {
          if (clipRing(view(r.v), sink)) ctx.closePath();
          vertices += r.v.length / 3;
        });
        return vertices;
      }
    };
  }

  /** Coasts and borders: one stroke per shared arc (``only`` may narrow the arcs down),
   *  bounded paths with a yield after each. */
  function* strokeMesh(f, ctx, only) {
    ctx.strokeStyle = f.pal.coast;
    ctx.lineWidth = Math.max(0.35, Math.min(0.8, f.R / 600));
    ctx.lineJoin = 'round';
    ctx.beginPath();
    var vertices = 0, mesh = f.L.mesh;
    for (var k = 0; k < mesh.length; k++) {
      var m = mesh[k];
      if (!f.visible(m) || (only && !only(m))) continue;
      clipLine(f.view(m.v), f.sink, function (i) { return onSeam(m.seam, i); });
      vertices += m.v.length / 3;
      if (vertices >= 512) {
        ctx.stroke();
        yield;
        ctx.beginPath();
        vertices = 0;
      }
    }
    if (vertices) { ctx.stroke(); yield; }
  }

  function strokeRim(f, ctx) {
    ctx.beginPath();
    ctx.arc(f.cx, f.cy, f.R, 0, 2 * Math.PI);
    ctx.strokeStyle = f.pal.rim;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  function strokeCircles(f, ctx, circles) {
    if (!circles.length) return;
    ctx.beginPath();
    circles.forEach(function (c) {
      ctx.moveTo(c[0] + c[2], c[1]);
      ctx.arc(c[0], c[1], c[2], 0, 2 * Math.PI);
    });
    ctx.strokeStyle = f.pal.highlight;
    ctx.lineWidth = Math.max(1.5, f.side * 0.004);
    ctx.stroke();
  }

  function drain(gen) {
    while (!gen.next().done) { /* run to completion */ }
  }

  /** The tooltip's country gets the quiet ``selected`` fill, drawn like the other land (under
   *  coasts, borders, rim and circles). Never for the card's own entry: it keeps its green. */
  function selectedPolys(g, L, selected) {
    return selected && selected !== g.id && L.entries[selected] || [];
  }

  /** One painter for synchronous coarse/interaction frames and sliced resting frames.
   *  Every yield follows a bounded canvas path, so software rasterization can finish in
   *  the same slice instead of accumulating a monolithic path for publication.
   *  ``selected`` is only passed for frames drawn straight onto the visible canvas; resting
   *  images are staged without it and get it as an overlay (paintSelection). */
  function* paintGlobe(g, ctx, W, level, zones, selected) {
    var f = frameOf(g, ctx, W, level), side = f.side, pal = f.pal, L = f.L;

    ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
    ctx.clearRect(0, 0, side, side);
    if (pal.space && pal.space !== 'transparent') {
      ctx.fillStyle = pal.space;
      ctx.fillRect(0, 0, side, side);
    }
    ctx.beginPath();
    ctx.arc(f.cx, f.cy, f.R, 0, 2 * Math.PI);
    ctx.fillStyle = pal.sea;
    ctx.fill();

    // Bounded paths per color. Polygons of one layer never overlap, so the even-odd rule only
    // acts on holes (enclaves); the limb stretches of clipped rings enclose no area.
    function* fill(polys, color) {
      if (!polys.length) return;
      ctx.beginPath();
      ctx.fillStyle = color;
      var vertices = 0;
      for (var k = 0; k < polys.length; k++) {
        if (!f.visible(polys[k])) continue;
        vertices += f.polygon(polys[k]);
        // Bound path complexity as well as JS work: one giant path defers expensive
        // tessellation/raster work until the browser presents the frame.
        if (vertices >= 512) {
          ctx.fill('evenodd');
          yield;
          ctx.beginPath();
          vertices = 0;
        }
      }
      if (vertices) { ctx.fill('evenodd'); yield; }
    }

    yield;
    yield* fill(zones, pal.eez);

    ctx.beginPath();
    W.graticule.forEach(function (gr) { clipLine(f.view(gr.v), f.sink); });
    ctx.strokeStyle = pal.graticule;
    ctx.lineWidth = 0.6;
    ctx.stroke();
    yield;

    var pick = selectedPolys(g, L, selected), chosen = pick.length ? selected : null;
    var rest = L.other.slice(), near = [];
    Object.keys(L.entries).forEach(function (id) {
      if (id === g.id || id === chosen) return;
      Array.prototype.push.apply(g.neighbors[id] ? near : rest, L.entries[id]);
    });
    var own = L.entries[g.id] || [];
    yield* fill(rest, pal.land);
    yield* fill(near, pal.neighbor);
    yield* fill(pick, pal.selected);
    yield* fill(own, pal.entry);

    // Coasts and borders on EVERY frame: one stroke per shared arc. During interaction
    // the one interaction level (L2) supplies both fills and mesh, so edges cannot separate.
    yield* strokeMesh(f, ctx);
    strokeRim(f, ctx);
    var circles = g.highlight(own, f.b, f.R, f.cx, f.cy, side);
    strokeCircles(f, ctx, circles);
    return { basis: f.b, circles: circles, night: f.night, borders: L.mesh.length, selected: chosen };
  }

  /** The selected country over a presented resting image: its fill, then, clipped to that
   *  fill, the coast/border strokes, rim and highlight circles it covered. Costs one entry's
   *  polygons and the arcs near it, never a repaint of the world. Returns what is shown. */
  function paintSelection(g, ctx, W, level, selected, circles) {
    var L = W.levels[level], polys = L ? selectedPolys(g, L, selected) : [];
    if (!polys.length) return null;
    var f = frameOf(g, ctx, W, level), any = false;
    ctx.setTransform(g.dpr, 0, 0, g.dpr, 0, 0);
    ctx.beginPath();
    polys.forEach(function (p) {
      if (f.visible(p)) { f.polygon(p); any = true; }
    });
    if (!any) return selected;
    ctx.fillStyle = f.pal.selected;
    ctx.fill('evenodd');
    ctx.save();
    ctx.clip('evenodd');
    var cap = unionCap(polys);
    drain(strokeMesh(f, ctx, function (m) { return capsOverlap(m, cap); }));
    strokeRim(f, ctx);
    strokeCircles(f, ctx, circles);
    ctx.restore();
    return selected;
  }

  Globe.prototype.draw = function () {
    this.dirty = false;
    if (!this.alive || !this.side || !this.ctx) return;
    var t0 = now(), W = getWorld(), level = this.pickLevel(W, this.radius());
    var self = this, first = !this.stats;
    // Even a warm cache must not add detailed EEZ raster work to the first frame.
    var zones = first ? [] : W.eez(this.id);
    var eez = !first && this.id in W.eezCache;
    // Interaction frames share their level (L2) with a zoomed-out resting image; the suffix
    // still makes the view repaint at rest once the gesture ends.
    var key = this.viewKey(), paintKey = key + ':' + level + ':' + eez + (this.interacting ? ':moving' : '');
    // Each level is presented as soon as it is prepared; the entry's zone follows on its
    // own and never holds back land detail. A missing level's packet is requested here, so
    // fine land is only loaded early when a resting view actually needs it.
    if (!first && this.waitingFor >= 0) {
      var part = W.partOf(this.waitingFor);
      if (part) loadPart(part, part !== 'detail');
      decodeInBackground();
    }
    if (!first && !this.interacting) {
      if (paintKey === this.paintKey || (this.pendingPaint && this.pendingPaint.key === paintKey)) return;
    }
    this.cancelPaint();
    function publish(result, ms, selected) {
      var t = now(), seen = self.presented;
      self.basis = result.basis;
      self.circles = result.circles;
      self.night = result.night;
      self.tipColors = result.night ? ['#1A1A1A', '#EEEEEE'] : ['#FFFFFF', '#222222'];
      self.paintKey = paintKey;
      self.shownSelection = selected;
      if (!self.interacting) {
        if (!(W.names[level] in seen)) seen[W.names[level]] = t;
        if (eez && !('EEZ' in seen)) seen.EEZ = t;
      }
      self.stats = {
        id: self.id, level: level, name: W.names[level], want: self.waitingFor < 0 ? level : self.waitingFor, stroke: true,
        ms: ms, interacting: self.interacting, borders: result.borders, frameWaitMs: self.frameWaitMs || 0,
        eez: eez, presented: seen
      };
      self.placeTip(); // the tooltip follows its country when the view moves
    }
    if (first || this.interacting) {
      var painter = paintGlobe(this, this.ctx, W, level, zones, this.selected), step;
      do { step = painter.next(); } while (!step.done);
      publish(step.value, now() - t0, step.value.selected);
      return;
    }
    // Software-backed detached canvas: finish raster work incrementally, keeping the
    // previous fully bordered image visible until the replacement is complete.
    if (!this.buffer) this.buffer = document.createElement('canvas');
    if (this.buffer.width !== this.canvas.width || this.buffer.height !== this.canvas.height) {
      this.buffer.width = this.canvas.width;
      this.buffer.height = this.canvas.height;
    }
    var ctx = this.buffer.getContext('2d', { willReadFrequently: true });
    var job = { key: paintKey, painter: paintGlobe(this, ctx, W, level, zones, null), maxSliceMs: 0 };
    this.pendingPaint = job;
    function current() {
      return self.alive && document.documentElement.contains(self.el) && self.pendingPaint === job &&
        !self.interacting && self.viewKey() === key;
    }
    function slice() {
      if (!current()) { if (self.pendingPaint === job) self.cancelPaint(); return; }
      var start = now(), step;
      do {
        step = job.painter.next();
        // Flush this batch, including on WebViews that ignore willReadFrequently.
        ctx.getImageData(0, 0, 1, 1);
      } while (!step.done && now() - start < PAINT_SLICE_MS);
      job.maxSliceMs = Math.max(job.maxSliceMs, now() - start);
      if (!step.done) { soon(slice); return; }
      self.presentFrame = root.requestAnimationFrame(function () {
        self.presentFrame = 0;
        if (!current()) { if (self.pendingPaint === job) self.cancelPaint(); return; }
        var start = now();
        self.ctx.setTransform(1, 0, 0, 1, 0, 0);
        self.ctx.globalCompositeOperation = 'copy';
        self.ctx.drawImage(self.buffer, 0, 0);
        self.ctx.globalCompositeOperation = 'source-over';
        var selected = null;
        if (self.tooltip) {
          // Keep the presented image as the base for selection changes (tooltip views only):
          // the next resting image is staged in the other buffer.
          var shown = self.buffer;
          self.buffer = self.base;
          self.base = shown;
          self.baseInfo = { key: key, level: level, circles: step.value.circles };
          if (self.selectFrame) { root.cancelAnimationFrame(self.selectFrame); self.selectFrame = 0; }
          selected = paintSelection(self, self.ctx, W, level, self.selected, step.value.circles);
        }
        publish(step.value, now() - start, selected);
        self.stats.maxSliceMs = job.maxSliceMs;
        self.pendingPaint = null;
        resumeDecode();
      });
    }
    // Staged work starts right after this task; every slice re-checks that it is current.
    soon(slice);
  };

  /** Highlight circles (CSS px) for tiny entries (micro-states, atolls): when the entry's
   *  land, seen face-on at the current zoom, would cover less than HIGHLIGHT_AREA of the
   *  canvas. Decided on the whole entry (not the visible part), so a big country turning
   *  away over the horizon never gets circles. One circle per group of visible parts, around
   *  the EEZ part(s) the group lies in (``meta.e``, embedded in the bootstrap so the circle
   *  never jumps when the zones packet arrives). */
  Globe.prototype.highlight = function (own, b, R, cx, cy, side) {
    var m = this.meta;
    if (!m || m.a * R * R >= HIGHLIGHT_AREA * side * side) return [];
    if (this.hullsOf !== m) { this.hulls = prepZones(m.e); this.hullsOf = m; }
    var zones = this.hulls, pts = [];
    function screen(v) {
      var q = project(v, b);
      return q[2] > 0 ? [cx + R * q[0], cy - R * q[1]] : null;
    }
    function add(v) {
      var p = screen(v), k = -1;
      if (!p) return;
      for (var i = 0; i < zones.length && k < 0; i++) if (inZone(zones[i], v)) k = i;
      pts.push([p[0], p[1], k]);
    }
    own.forEach(function (poly) {
      var r = poly.rings[0].v, sx = 0, sy = 0, sz = 0;
      for (var i = 0; i < r.length; i += 3) { sx += r[i]; sy += r[i + 1]; sz += r[i + 2]; }
      var len = Math.sqrt(sx * sx + sy * sy + sz * sz) || 1;
      add([sx / len, sy / len, sz / len]);
    });
    // Islands too small for the embedded land (globe.py SPECK_DEG2), then the center.
    m.s.forEach(function (ll) { add(toVector(ll[0], ll[1])); });
    if (!pts.length) add(toVector(m.c[0], m.c[1]));
    // Each EEZ outline in screen points; null when part of it is behind the horizon.
    var outlines = zones.map(function (z) {
      var out = [];
      for (var i = 0; i < z.v.length; i++) {
        var p = screen(z.v[i]);
        if (!p) return null;
        out.push(p);
      }
      return out;
    });
    return pts.length ? highlightCircles(pts, side, outlines) : [];
  };

  /** Entry under a canvas point (CSS px) and the point's lon/lat, or null over sea/space.
   *  Inside a highlight circle: the card's entry. Exact hits come first; only a miss over
   *  sea or space looks for the nearest drawn coast within ``tol`` CSS px (issue #27), and
   *  then the lon/lat is that coast point. */
  Globe.prototype.pick = function (px, py, tol) {
    if (!this.basis) return null;
    var R = this.radius(), side = this.side, W = getWorld(), self = this, id = null;
    (this.circles || []).forEach(function (c) {
      if (!id && Math.hypot(px - c[0], py - c[1]) <= c[2]) id = self.id;
    });
    var ll = invert((px - side / 2) / R, (side / 2 - py) / R, this.basis);
    if (!id && ll) id = hit(W, ll[0], ll[1]);
    var L = this.stats && W.levels[this.stats.level];
    if (!id && tol > 0 && L && !(ll && hit(W, ll[0], ll[1], true))) {
      var near = nearestEntry(L, W.meta, this.basis, R, side / 2, side / 2, px, py, tol);
      if (near && near.ll) return { id: near.id, ll: near.ll };
    }
    var m = id && W.meta[id];
    return m ? { id: id, ll: ll || m.c } : null;
  };

  /** Select what is under a client point (tap, click, coalesced hover) within ``tol`` px. */
  Globe.prototype.pointAt = function (clientX, clientY, tol) {
    var rect = this.canvas.getBoundingClientRect();
    this.select(this.pick(clientX - rect.left, clientY - rect.top, tol));
  };

  /** Tooltip and selected fill always show the same entry: ``hit`` (from pick) selects it,
   *  null clears both. Only views with the tooltip (card backs) ever select. */
  Globe.prototype.select = function (hit) {
    var id = hit && this.tooltip ? hit.id : null;
    this.anchor = id ? hit.ll : null;
    if (id) {
      var m = getWorld().meta[id], colors = this.tipColors || ['#FFFFFF', '#222222'];
      this.tip.textContent = m.name[this.lang] || m.name.en;
      this.tip.style.background = colors[0];
      this.tip.style.color = colors[1];
    }
    var changed = id !== this.selected;
    this.selected = id;
    this.placeTip();
    if (changed) this.repaintSelection();
  };

  /** Drop the selection without repainting (a full repaint follows anyway). */
  Globe.prototype.clearSelection = function () {
    this.selected = this.anchor = this.hoverAt = null;
    if (this.hoverFrame) root.cancelAnimationFrame(this.hoverFrame);
    if (this.selectFrame) root.cancelAnimationFrame(this.selectFrame);
    this.hoverFrame = this.selectFrame = 0;
    this.tip.style.display = 'none';
  };

  /** Put the tooltip at its anchor in the current view, clamped inside the globe; hidden
   *  while the anchor is behind the horizon or off the zoomed canvas. */
  Globe.prototype.placeTip = function () {
    var tip = this.tip, side = this.side, b = this.basis;
    if (!this.selected || !this.anchor || !b || !side) { tip.style.display = 'none'; return; }
    var q = project(toVector(this.anchor[0], this.anchor[1]), b), R = this.radius();
    var x = side / 2 + R * q[0], y = side / 2 - R * q[1];
    if (q[2] <= 0 || x < 0 || y < 0 || x > side || y > side) { tip.style.display = 'none'; return; }
    var text = tip.textContent, size = this.tipSize;
    tip.style.display = 'block';
    if (!size || size.text !== text || size.side !== side) {
      // Measured once per name and width, at the origin so the full width is available.
      tip.style.maxWidth = Math.max(0, side - 2 * TIP_MARGIN) + 'px';
      tip.style.left = tip.style.top = '0px';
      size = this.tipSize = { text: text, side: side, w: tip.offsetWidth || 0, h: tip.offsetHeight || 0 };
    }
    var at = tipPlacement(x, y, size.w, size.h, side, TIP_MARGIN);
    // Relative to the element's padding box: add the canvas offset (element padding).
    tip.style.left = at[0] + (this.canvas.offsetLeft || 0) + 'px';
    tip.style.top = at[1] + (this.canvas.offsetTop || 0) + 'px';
    this.tipAt = at;
  };

  /** Mouse hover: at most one hit test, tooltip move and selection repaint per frame, for
   *  the latest pointer position. */
  Globe.prototype.hoverLater = function (e) {
    if (!this.tooltip) return;
    this.hoverAt = [e.clientX, e.clientY];
    if (this.hoverFrame) return;
    var self = this;
    this.hoverFrame = root.requestAnimationFrame(function () {
      self.hoverFrame = 0;
      var at = self.hoverAt;
      self.hoverAt = null;
      if (!at || !self.alive) return;
      self.pointAt(at[0], at[1], MOUSE_HIT_PX);
      if (self.selectFrame) {
        // Already inside a frame: show the new selection now, not one frame later.
        root.cancelAnimationFrame(self.selectFrame);
        self.selectFrame = 0;
        self.composeSelection();
      }
    });
  };

  /** Show a changed selection in the next frame (at most one composition per frame). Frames
   *  drawn during interaction paint it inline as well, so it follows the moving globe. */
  Globe.prototype.repaintSelection = function () {
    if (!this.alive || !this.stats || this.selectFrame) return;
    var self = this;
    this.selectFrame = root.requestAnimationFrame(function () {
      self.selectFrame = 0;
      self.composeSelection();
    });
  };

  /** The presented resting image (base) with the current selection on top. Without a base
   *  for this view (the synchronous first paint, the last frame of a gesture) the shown level
   *  is repainted directly, which is then always L2, the cheap level. A staged detail image
   *  is never touched: it gets the selection when it is presented. */
  Globe.prototype.composeSelection = function () {
    if (!this.alive || !this.ctx || !this.stats) return;
    var W = getWorld(), info = this.baseInfo, ctx = this.ctx;
    if (this.base && info && info.key === this.viewKey() && W.levels[info.level]) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = 'copy';
      ctx.drawImage(this.base, 0, 0);
      ctx.globalCompositeOperation = 'source-over';
      this.shownSelection = paintSelection(this, ctx, W, info.level, this.selected, info.circles);
      return;
    }
    var s = this.stats;
    if (!W.levels[s.level]) return;
    var painter = paintGlobe(this, ctx, W, s.level, s.eez ? W.eez(this.id) : [], this.selected), step;
    do { step = painter.next(); } while (!step.done);
    this.shownSelection = step.value.selected;
  };

  /** Entry under a lon/lat point, tested against the finest decoded level; with ``other``,
   *  whether the point is on land without an entry (Antarctica, Bir Tawil, …) instead. */
  function hit(W, lon, lat, other) {
    var ready = readyLevels(W), L = W.level(ready.lastIndexOf(true) >= 0 ? ready.lastIndexOf(true) : 0);
    if (other) return inPolygons(L.other, lon, lat);
    var ids = Object.keys(L.entries).sort();
    for (var k = 0; k < ids.length; k++) if (inPolygons(L.entries[ids[k]], lon, lat)) return ids[k];
    return null;
  }

  function inPolygons(polys, lon, lat) {
    for (var p = 0; p < polys.length; p++) {
      var poly = polys[p], bx = poly.box;
      if (lon < bx[0] || lon > bx[2] || lat < bx[1] || lat > bx[3]) continue;
      var inside = false;
      poly.rings.forEach(function (r) { if (pointInRing(lon, lat, r.ll)) inside = !inside; });
      if (inside) return true;
    }
    return false;
  }

  /** Render every `.cotw-globe` on the page (one draw each); drop instances whose element
   *  is gone. */
  function renderAll() {
    if (retired) return;
    instances = instances.filter(function (g) {
      if (g.alive && document.documentElement.contains(g.el)) return true;
      g.destroy();
      return false;
    });
    var els = document.querySelectorAll('.cotw-globe');
    for (var i = 0; i < els.length; i++) {
      var g = els[i].__cotwGlobe;
      if (g && g.alive) {
        g.configure();
        g.resize(false); // draws only if the entry, the mode or the size changed
      } else {
        instances.push(new Globe(els[i]));
      }
    }
    if (els.length) afterPaint();
  }

  function destroyAll() {
    instances.forEach(function (g) { g.destroy(); });
    instances = [];
  }

  function retire() {
    retired = true;
    destroyAll();
    if (paintHandle) root.cancelAnimationFrame(paintHandle);
    if (idleHandle) {
      if (root.cancelIdleCallback) root.cancelIdleCallback(idleHandle);
      else root.clearTimeout(idleHandle);
    }
    if (deepHandle) root.clearTimeout(deepHandle);
    deepHandle = 0;
    Object.keys(partScripts).forEach(function (part) {
      var el = partScripts[part];
      if (el.parentNode) el.parentNode.removeChild(el);
    });
    partScripts = {};
    document.removeEventListener('DOMContentLoaded', renderAll);
    activeJob = null;
    parked = null;
    soonQueue = [];
    if (Array.isArray(root.onShownHook)) {
      var hook = root.onShownHook.indexOf(renderAll);
      if (hook >= 0) root.onShownHook.splice(hook, 1);
    }
  }

  root.COTWGlobe = {
    version: VERSION, dataKey: DATA_KEY, ready: true, renderAll: renderAll, destroyAll: destroyAll, retire: retire,
    acceptDetail: acceptDetail, api: api,
    // Debug view (build/globe-preview.html?debug=1): frame time and level per globe.
    stats: function () { return instances.map(function (g) { return g.stats || null; }); }
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderAll, { once: true });
  } else {
    renderAll();
  }
  // Anki desktop: hooks run after the card is shown (lists are reset for every card).
  if (Array.isArray(root.onShownHook)) root.onShownHook.push(renderAll);
})(typeof window !== 'undefined' ? window : this);
