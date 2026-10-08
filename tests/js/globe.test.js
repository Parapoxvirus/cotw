// Unit tests for the pure parts of the globe renderer (tools/globe/globe.js) and a sanity
// pass over the committed media/_cotw-globe.js. Run: node --test tests/js/*.test.js
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const g = require(path.join(__dirname, '..', '..', 'tools', 'globe', 'globe.js'));
const built = require(path.join(__dirname, '..', '..', 'media', '_cotw-globe.js'));
const packets = Object.fromEntries(['zones', 'detail'].map(part =>
  [part, require(path.join(__dirname, '..', '..', 'media', `_cotw-globe-${part}.js`))]));
function fullWorld() {
  const w = built.prepWorld(built.data());
  for (const packet of Object.values(packets)) assert.equal(w.installDetail(packet), true);
  assert.equal(w.hasDetail(), true);
  return w;
}

const EPS = 1e-9;
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) <= eps, `${a} ≉ ${b}`);

// A sink that records the emitted path and can measure its area (arcs sampled finely).
function recorder() {
  const cmds = [];
  return {
    cmds,
    move: (x, y) => cmds.push(['M', x, y]),
    line: (x, y) => cmds.push(['L', x, y]),
    arc: (a0, a1) => cmds.push(['A', a0, a1]),
    points() {
      const pts = [];
      for (const c of cmds) {
        if (c[0] === 'A') {
          const n = Math.max(2, Math.ceil(Math.abs(c[2] - c[1]) / 0.01));
          for (let k = 1; k <= n; k++) {
            const a = c[1] + (c[2] - c[1]) * k / n;
            pts.push([Math.cos(a), Math.sin(a)]);
          }
        } else {
          pts.push([c[1], c[2]]);
        }
      }
      return pts;
    },
    area() {
      const p = this.points();
      let a = 0;
      for (let i = 0; i < p.length; i++) {
        const [x0, y0] = p[i], [x1, y1] = p[(i + 1) % p.length];
        a += x0 * y1 - x1 * y0;
      }
      return Math.abs(a / 2);
    }
  };
}

function viewRing(lonlat, basis) {
  const out = [];
  for (const [lon, lat] of lonlat) out.push(...g.project(g.toVector(lon, lat), basis));
  return Float64Array.from(out);
}

// A spherical cap as a lon/lat ring (radius in degrees, n vertices).
function cap(lon0, lat0, radius, n = 360) {
  const c = g.toVector(lon0, lat0), b = g.viewBasis(lon0, lat0), ring = [];
  const r = radius * Math.PI / 180;
  for (let i = 0; i < n; i++) {
    const t = 2 * Math.PI * i / n;
    const v = [0, 1, 2].map(k => Math.cos(r) * c[k] + Math.sin(r) * (Math.cos(t) * b.e[k] + Math.sin(t) * b.n[k]));
    ring.push(g.toLonLat(v));
  }
  return ring;
}

// Monte Carlo reference: visible (orthographic) area of a cap on the unit disc.
function visibleCapArea(lon0, lat0, radius, view) {
  const c = g.toVector(lon0, lat0), cosr = Math.cos(radius * Math.PI / 180);
  const N = 400;
  let hit = 0;
  for (let i = 0; i < N; i++) {
    for (let j = 0; j < N; j++) {
      const x = -1 + (2 * i + 1) / N, y = -1 + (2 * j + 1) / N;
      const ll = g.invert(x, y, view);
      if (!ll) continue;
      const v = g.toVector(ll[0], ll[1]);
      if (v[0] * c[0] + v[1] * c[1] + v[2] * c[2] >= cosr) hit++;
    }
  }
  return hit * 4 / (N * N);
}

// --- projection and rotation -----------------------------------------------------------------

test('view basis is orthonormal and right-handed', () => {
  for (const [lon, lat] of [[0, 0], [8.2, 46.8], [-170.5, 0], [180, 89.9], [45, -60]]) {
    const b = g.viewBasis(lon, lat);
    const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
    for (const u of [b.e, b.n, b.c]) close(dot(u, u), 1);
    close(dot(b.e, b.n), 0); close(dot(b.e, b.c), 0); close(dot(b.n, b.c), 0);
    // e × n = c (screen right × up = toward the viewer)
    const cross = [b.e[1] * b.n[2] - b.e[2] * b.n[1], b.e[2] * b.n[0] - b.e[0] * b.n[2], b.e[0] * b.n[1] - b.e[1] * b.n[0]];
    cross.forEach((v, k) => close(v, b.c[k]));
  }
});

test('the center projects to the middle; east is right, north is up', () => {
  const b = g.viewBasis(8.2, 46.8);
  const c = g.project(g.toVector(8.2, 46.8), b);
  close(c[0], 0); close(c[1], 0); close(c[2], 1);
  assert.ok(g.project(g.toVector(10, 46.8), b)[0] > 0);
  assert.ok(g.project(g.toVector(8.2, 50), b)[1] > 0);
  assert.ok(g.project(g.toVector(8.2 + 180, -46.8), b)[2] < 0); // antipode is hidden
});

test('invert is the inverse of project on the visible hemisphere', () => {
  const b = g.viewBasis(177.975, -17.8);
  for (const [lon, lat] of [[178, -17], [-179.5, -16], [170, 0], [-160, -40]]) {
    const p = g.project(g.toVector(lon, lat), b);
    assert.ok(p[2] > 0);
    const ll = g.invert(p[0], p[1], b);
    close(ll[0], lon, 1e-6); close(ll[1], lat, 1e-6);
  }
  assert.equal(g.invert(0.8, 0.8, b), null);
});

// --- horizon clipping ------------------------------------------------------------------------

test('a ring entirely in front is drawn as is', () => {
  const b = g.viewBasis(0, 0);
  const s = recorder();
  assert.equal(g.clipRing(viewRing([[-10, -10], [10, -10], [10, 10], [-10, 10]], b), s), true);
  assert.deepEqual(s.cmds.map(c => c[0]), ['M', 'L', 'L', 'L', 'L']);
});

test('a ring entirely behind draws nothing', () => {
  const b = g.viewBasis(0, 0);
  const s = recorder();
  assert.equal(g.clipRing(viewRing([[170, -10], [-170, -10], [-170, 10], [170, 10]], b), s), false);
  assert.equal(s.cmds.length, 0);
});

test('a ring crossing the horizon is closed along the limb', () => {
  const b = g.viewBasis(0, 0);
  const s = recorder();
  g.clipRing(viewRing(cap(90, 0, 30), b), s);
  assert.ok(s.cmds.some(c => c[0] === 'A'));
  for (const c of s.cmds) {
    if (c[0] !== 'A') assert.ok(Math.hypot(c[1], c[2]) <= 1 + EPS);
  }
  const expected = visibleCapArea(90, 0, 30, b);
  close(s.area(), expected, 0.01);
});

for (const [name, capLon, capLat, viewLon, viewLat] of [
  ['antimeridian, cap centered on 180°', 180, -17, 170, -10],
  ['antimeridian, cap on the limb', 180, 0, 90, 0],
  ['north pole, seen from above', 0, 90, 30, 80],
  ['north pole, cap on the limb', 0, 90, 0, 10],
  ['south pole, cap on the limb', 45, -85, -120, -20]
]) {
  test(`clipped fill area matches the visible area: ${name}`, () => {
    const b = g.viewBasis(viewLon, viewLat);
    const s = recorder();
    g.clipRing(viewRing(cap(capLon, capLat, 25), b), s);
    close(s.area(), visibleCapArea(capLon, capLat, 25, b), 0.01);
  });
}

test('lines stop exactly at the limb and skip seams', () => {
  const b = g.viewBasis(0, 0);
  const s = recorder();
  const line = viewRing([[60, 0], [80, 0], [100, 0], [120, 0]], b);
  g.clipLine(line, s);
  const last = s.cmds[s.cmds.length - 1];
  close(Math.hypot(last[1], last[2]), 1);
  assert.equal(s.cmds.length, 3); // M 60°, L 80°, L limb

  const t = recorder();
  g.clipLine(viewRing([[0, 0], [0, 10], [0, 20], [0, 30]], b), t, i => i === 1);
  assert.deepEqual(t.cmds.map(c => c[0]), ['M', 'L', 'M', 'L']);
});

test('seam bits flag antimeridian and pole vertices only; a pole corner carries both', () => {
  assert.equal(g.seam(180, 10), 4);
  assert.equal(g.seam(-180, 10), 4, '±180° is one meridian');
  assert.equal(g.seam(20, -90), 1);
  assert.equal(g.seam(20, 90), 2);
  assert.equal(g.seam(-180, -90), 5);
  assert.equal(g.seam(179.9, 89.9), 0);
  // Up the 180° meridian from the south pole corner: a seam (issue #33), not a coast.
  assert.ok(g.onSeam([g.seam(-180, -90), g.seam(-180, -89.059)], 0));
  assert.ok(g.onSeam([g.seam(180, -89.059), g.seam(180, -90)], 0));
  // A coast that reaches the cut is drawn up to it.
  assert.ok(!g.onSeam([g.seam(-180, -16.964), g.seam(-179.916, -16.695)], 0));
  assert.ok(!g.onSeam([g.seam(-180, -90), g.seam(10, -89)], 0));
});

test('no coast stroke runs along a cut of the source data, and every real coast is stroked (#33)', () => {
  // Independent of the lon/lat seam bits: on the sphere, the cuts are the 180° half-meridian
  // (y = 0, x ≤ 0, poles included) and the poles themselves.
  const tiny = 1e-12;
  const pole = (v, j) => 1 - Math.abs(v[3 * j + 2]) < tiny ? Math.sign(v[3 * j + 2]) : 0;
  const onMeridian = (v, j) => Math.abs(v[3 * j + 1]) < tiny && v[3 * j] <= tiny;
  const alongCut = (v, j) => (onMeridian(v, j) && onMeridian(v, j + 1)) || (pole(v, j) !== 0 && pole(v, j) === pole(v, j + 1));
  const w = fullWorld();
  built.data().lod.forEach((level, i) => {
    let cut = 0, coastAtCut = 0;
    for (const m of w.level(i).mesh) {
      for (let j = 0; j + 1 < m.v.length / 3; j++) {
        const along = alongCut(m.v, j), skipped = built.onSeam(m.seam, j);
        assert.equal(skipped, along, `${level.name}: segment ${j} ${along ? 'along a cut is stroked' : 'of a coast is skipped'}`);
        if (along) cut++;
        else if (m.seam[j] || m.seam[j + 1]) coastAtCut++;
      }
    }
    assert.ok(cut > 0, `${level.name}: no cut segments at all`);
    assert.ok(coastAtCut > 0, `${level.name}: coasts that reach the cut (Fiji, Chukotka) are drawn`);
  });
});

// --- TopoJSON --------------------------------------------------------------------------------

test('arcs decode from quantized deltas; negative refs run reversed', () => {
  const topo = { transform: { scale: [0.5, 0.25], translate: [-180, -90] }, arcs: [[[0, 0], [2, 0], [0, 4]], [[2, 4], [-2, 0], [0, -4]]] };
  const arcs = g.decodeArcs(topo);
  assert.deepEqual(Array.from(arcs[0]), [-180, -90, -179, -90, -179, -89]);
  const ring = g.ringCoords([0, 1], arcs);
  assert.deepEqual(ring, [-180, -90, -179, -90, -179, -89, -180, -89]);
  const rev = g.ringCoords([~1, ~0], arcs);
  assert.deepEqual(rev, [-180, -90, -180, -89, -179, -89, -179, -90]);
  const deferred = { ...topo, arcs: topo.arcs.map(JSON.stringify) };
  const lazy = g.lazyArcs(deferred);
  assert.equal(lazy.decoded(), 0);
  assert.deepEqual(lazy.get(0), arcs[0]);
  assert.equal(lazy.decoded(), 1);
  assert.deepEqual(g.decodeArcs(deferred), arcs);
});

test('point in ring', () => {
  const r = [0, 0, 10, 0, 10, 10, 0, 10];
  assert.equal(g.pointInRing(5, 5, r), true);
  assert.equal(g.pointInRing(15, 5, r), false);
});

// --- theme and highlight -------------------------------------------------------------------------

test('night palette follows Anki\'s class only, never the system color scheme', () => {
  const inNight = { closest: sel => (sel.includes('.nightMode') ? {} : null) };
  const inOldNight = { closest: sel => (sel.includes('.night_mode') ? {} : null) };
  const inDay = { closest: () => null };
  assert.equal(g.isNight(inNight), true);
  assert.equal(g.isNight(inOldNight), true);
  assert.equal(g.isNight(inDay), false);
  assert.equal(g.isNight(inDay, true), false); // a dark OS does not matter
  const palette = { day: { sea: '#68A3DE' }, night: { sea: '#1F3550' } };
  assert.equal(g.paletteFor(palette, true).sea, '#1F3550');
  assert.equal(g.paletteFor(palette, false).sea, '#68A3DE');
});

test('highlight circles group nearby parts and merge overlapping groups', () => {
  const side = 1000, r = g.HIGHLIGHT_R * side;
  const one = g.highlightCircles([[100, 100], [110, 105]], side);
  assert.equal(one.length, 1);
  assert.ok(one[0][2] >= r);
  const two = g.highlightCircles([[100, 100], [600, 600]], side);
  assert.equal(two.length, 2);
  const chain = g.highlightCircles([[100, 100], [100 + 1.4 * r, 100], [100 + 2.8 * r, 100]], side);
  assert.equal(chain.length, 1);
  assert.equal(g.highlightCircles([[100, 100], [100 + 2.2 * r, 100]], side).length, 2); // apart: no merge
});

// --- levels of detail, culling, cache ---------------------------------------------------------

test('level of detail: coarsest level whose screen error fits, finest otherwise', () => {
  const tol = [2, 1, 0.25, 0.04]; // degrees; error in px = tol × π/180 × R
  const err = (t, R) => t * Math.PI / 180 * R;
  // A zoomed-out 800 px globe (R ≈ 384 CSS px): the middle level, at rest and while dragging.
  assert.equal(g.chooseLevel(tol, 384, g.LOD_REST_PX), 2);
  // A small globe gets the coarse level even at rest; zoomed in, the finest.
  assert.equal(g.chooseLevel(tol, 120, g.LOD_REST_PX), 1);
  assert.equal(g.chooseLevel(tol, 384 * 6, g.LOD_REST_PX), 3);
  assert.equal(g.chooseLevel(tol, 1e6, g.LOD_REST_PX), 3); // nothing fits: finest
  // The switch happens exactly where the error crosses the threshold.
  const R = g.LOD_REST_PX / (0.25 * Math.PI / 180);
  assert.ok(err(0.25, R * 0.999) < g.LOD_REST_PX && g.chooseLevel(tol, R * 0.999, g.LOD_REST_PX) === 2);
  assert.equal(g.chooseLevel(tol, R * 1.001, g.LOD_REST_PX), 3);
  // Monotone: a bigger sphere never gets a coarser level.
  let last = 0;
  for (let r = 50; r < 20000; r *= 1.1) {
    const l = g.chooseLevel(tol, r, g.LOD_REST_PX);
    assert.ok(l >= last);
    last = l;
  }
});

test('culling: bounding caps behind the horizon or outside the zoomed canvas are skipped', () => {
  const b = g.viewBasis(0, 0);
  const cap = (lon, lat, r) => ({ cap: g.toVector(lon, lat), capR: r * Math.PI / 180 });
  const horizon = g.reachAngle(800, 384); // whole globe on the canvas
  close(horizon, Math.PI / 2);
  const front = cap(10, 0, 5), back = cap(180, 0, 5), limb = cap(95, 0, 10);
  assert.ok(g.capVisible(front.cap, front.capR, b.c, horizon));
  assert.ok(!g.capVisible(back.cap, back.capR, b.c, horizon));
  assert.ok(g.capVisible(limb.cap, limb.capR, b.c, horizon)); // reaches over the limb
  // Zoomed in 6×: only about ±14° around the center reach the canvas (its corners).
  const reach = g.reachAngle(800, 384 * 6);
  close(reach, Math.asin(Math.SQRT2 * 400 / (384 * 6)));
  assert.ok(reach < 15 * Math.PI / 180 && reach > 14 * Math.PI / 180);
  assert.ok(!g.capVisible(cap(30, 0, 5).cap, 5 * Math.PI / 180, b.c, reach));
  assert.ok(g.capVisible(cap(15, 0, 5).cap, 5 * Math.PI / 180, b.c, reach));
  // A bounding cap covers every vertex it was built from.
  const ring = cap(40, 20, 1); // reuse: vectors of a small circle
  const vs = [];
  for (let i = 0; i < 36; i++) vs.push(...g.toVector(40 + 3 * Math.cos(i / 36 * 2 * Math.PI), 20 + 3 * Math.sin(i / 36 * 2 * Math.PI)));
  const bc = g.boundingCap([Float64Array.from(vs)]);
  for (let i = 0; i < vs.length; i += 3) {
    const d = Math.acos(Math.min(1, bc.cap[0] * vs[i] + bc.cap[1] * vs[i + 1] + bc.cap[2] * vs[i + 2]));
    assert.ok(d <= bc.capR + 1e-12);
  }
  assert.ok(ring.capR > 0);
});

test('the decoded world is cached on window across cards, keyed by version and data', () => {
  const host = {};
  let builds = 0;
  const make = () => ({ n: ++builds });
  const first = g.worldCache(host, '2:aaaa1111', make);
  assert.equal(g.worldCache(host, '2:aaaa1111', make), first); // the 2nd card decodes nothing
  assert.equal(builds, 1);
  const updated = g.worldCache(host, '2:bbbb2222', make); // deck update: new data
  assert.notEqual(updated, first);
  assert.equal(builds, 2);
  assert.equal(g.worldCache(null, 'x', make).n, 3); // no window (tests): just build
});

test('levels are decoded lazily: a level only decodes its own arcs', () => {
  const w = built.prepWorld(built.data());
  assert.deepEqual(w.levels.map(Boolean), [false, false]);
  const coarse = w.level(0);
  assert.equal(w.level(0), coarse); // decoded once
  const afterCoarse = w.arcs.decoded();
  assert.equal(afterCoarse, built.data().topology.arcs.length, 'the bootstrap carries L2 only');
  assert.equal(w.level(1), null, 'fine land unavailable before registration');
  w.installDetail(packets.zones);
  assert.equal(w.level(1), null, 'the zones packet carries no land');
  w.installDetail(packets.detail);
  w.level(1);
  assert.equal(w.arcs.decoded(), afterCoarse, 'fine arcs are independent of bootstrap arcs');
  assert.deepEqual(w.levels.map(Boolean), [true, true]);
});

// --- the committed asset ---------------------------------------------------------------------

test('the built script carries the data lazily and every polygon is smaller than a hemisphere', () => {
  const data = built.data();
  assert.ok(data, 'media/_cotw-globe.js has no embedded data');
  assert.equal(built.data(), data); // parsed once
  assert.match(built.DATA_KEY, /^[0-9a-f]{8}$/);
  const w = fullWorld();
  const ids = Object.keys(data.entries);
  assert.ok(ids.length >= 248);
  assert.deepEqual(data.lod.map(l => l.name), ['L2', 'L3'], 'nothing coarser than L2 (#31)');
  assert.ok(data.lod[0].tolerance > data.lod[1].tolerance);
  data.lod.forEach((_, i) => {
    const L = w.level(i);
    for (const id of ids) {
      assert.ok(L.entries[id] && L.entries[id].length, `level ${i}: ${id} has no polygon`);
      for (const p of L.entries[id]) assert.ok(p.capR < Math.PI / 2, `${id}: polygon larger than a hemisphere`);
    }
    for (const p of L.other) assert.ok(p.capR < Math.PI / 2);
  });
  for (const id of ids) {
    const job = w.prepareEEZ(id);
    if (job) job.step(Infinity);
    for (const p of w.eez(id)) assert.ok(p.capR < Math.PI / 2, `EEZ ${id}: larger than a hemisphere`);
  }
});

test('the interaction mesh (L2) has at most 20 % of the fine mesh vertices', () => {
  const w = fullWorld();
  const count = i => w.level(i).mesh.reduce((n, arc) => n + arc.v.length / 3, 0);
  assert.ok(count(0) <= count(1) * 0.2);
});

test('there is no adaptive fallback below L2 (#31)', () => {
  assert.equal(g.adaptLevel, undefined);
  assert.equal(g.nearestReady, undefined);
  assert.equal(g.LATE_FRAMES, undefined);
});

test('deferred packets are keyed and prepared atomically in resumable slices', () => {
  const w = built.prepWorld(built.data());
  assert.equal(w.installDetail({ ...packets.zones, key: 'stale' }), false);
  assert.equal(w.installDetail({ ...packets.zones, part: 'other' }), false);
  assert.equal(w.installDetail({ ...packets.detail, part: 'overview' }), false, 'no overview packet since #31');
  assert.deepEqual(w.eez('040'), []);
  assert.equal(w.prepareEEZ('040'), null, 'zones are a packet of their own');
  assert.equal(w.installDetail(packets.zones), true);
  assert.equal(w.installDetail(packets.zones), false);
  assert.equal(w.hasDetail(), false, 'fine land still missing');
  w.level(0);
  assert.deepEqual(w.eez('040'), []); // draw never decodes zones
  w.prepareEEZ('040').step(Infinity);
  assert.ok(w.eez('040').length > 0);
  assert.equal(w.prepareLevel(1), null);
  assert.equal(w.installDetail(packets.detail), true);
  const job = w.prepareLevel(1);
  assert.equal(job.step(0), false); // one polygon, not a partially published level
  assert.equal(w.levels[1], null);
  job.step(Infinity);
  assert.equal(Object.keys(w.levels[1].entries).length, 248);
  assert.ok(w.readyAt.L3 >= w.readyAt.L2, 'measurements keep the level names');
});

test('every packet shares the bootstrap key and holds exactly its levels or zones', () => {
  const data = built.data();
  assert.deepEqual(data.lod.map(l => l.part), [undefined, 'detail']);
  for (const [part, packet] of Object.entries(packets)) {
    assert.equal(packet.key, data.detailKey);
    assert.equal(packet.part, part);
  }
  assert.deepEqual(Object.keys(packets), ['zones', 'detail']);
  assert.deepEqual(Object.keys(packets.detail.levels), ['1']);
  assert.ok(Object.keys(packets.zones.zones).length > 150 && !packets.zones.levels);
});

test('Switzerland: center and neighbors hit-test to the right entries on every level', () => {
  const w = fullWorld();
  for (let i = 0; i < 2; i++) {
    const L = w.level(i);
    const inside = (id, lon, lat) => L.entries[id].some(p => p.rings.reduce((acc, r) => acc !== g.pointInRing(lon, lat, r.ll), false));
    assert.ok(inside('217', 7.45, 46.95), `level ${i}: Bern`);
    assert.ok(!inside('217', 11.58, 48.14), `level ${i}: Munich`);
  }
  assert.equal(built.data().entries['217'].name['de-CH'], 'Schweiz');
});

test('tooltip placement: above the anchor, below when there is no room, clamped at all four edges', () => {
  const side = 300, m = g.TIP_MARGIN, w = 180, h = 20;
  const inside = ([left, top], label) => {
    assert.ok(left >= m && left + w <= side - m, `${label}: left ${left}`);
    assert.ok(top >= m && top + h <= side - m, `${label}: top ${top}`);
  };
  // Middle: centered, above the anchor.
  assert.deepEqual(g.tipPlacement(150, 150, w, h, side, m), [60, 124]);
  // Left and right edge: pushed inside, still above the anchor.
  const left = g.tipPlacement(1, 150, w, h, side, m), right = g.tipPlacement(299, 150, w, h, side, m);
  assert.deepEqual(left, [m, 124]); inside(left, 'left');
  assert.deepEqual(right, [side - m - w, 124]); inside(right, 'right');
  // Top edge: below the anchor (clear of a cursor). Bottom edge: above it.
  const top = g.tipPlacement(150, 1, w, h, side, m), bottom = g.tipPlacement(150, 299, w, h, side, m);
  assert.deepEqual(top, [60, 19]); inside(top, 'top');
  assert.deepEqual(bottom, [60, 273]); inside(bottom, 'bottom');
  // Corners.
  for (const [x, y] of [[0, 0], [side, 0], [0, side], [side, side]]) inside(g.tipPlacement(x, y, w, h, side, m), `${x},${y}`);
  // A name as wide as the globe (wrapped to max-width) stays flush with the margin.
  assert.equal(g.tipPlacement(10, 150, side - 2 * m, 40, side, m)[0], m);
  assert.equal(g.tipPlacement(290, 150, side - 2 * m, 40, side, m)[0], m);
});

test('selection overlay culling: one cap around all parts, overlap by caps', () => {
  const cap = (lon, lat, r) => ({ cap: g.toVector(lon, lat), capR: r });
  const parts = [cap(0, 0, 0.01), cap(10, 0, 0.01)];
  const u = g.unionCap(parts);
  for (const p of parts) assert.ok(g.capsOverlap(u, p));
  assert.ok(Math.abs(u.capR - (5 * Math.PI / 180 + 0.01)) < 1e-6);
  assert.equal(g.capsOverlap(u, cap(5, 20, 0.1)), false);
  assert.equal(g.capsOverlap(u, cap(5, 6, 0.1)), true, 'an arc reaching into the cap');
  assert.equal(g.unionCap([]).capR, Math.PI);
});

// --- hit tolerance (issue #27): nearest drawn coast within a screen-space radius ----------

/** A synthetic view: 800 CSS px, zoom 1, centered on (0, 0); one level with square islands. */
function toleranceView(entries, specks = {}, other = []) {
  const side = 800, R = side / 2 * g.SPHERE_FILL, b = g.viewBasis(0, 0);
  const square = (lon, lat, h) => g.prepPolygon([[lon - h, lat - h, lon + h, lat - h, lon + h, lat + h, lon - h, lat + h]]);
  const L = { entries: {}, other: other.map(([lon, lat, h]) => square(lon, lat, h)), mesh: [] };
  const meta = {};
  for (const [id, parts] of Object.entries(entries)) L.entries[id] = parts.map(([lon, lat, h]) => square(lon, lat, h));
  for (const id of new Set([...Object.keys(entries), ...Object.keys(specks)])) meta[id] = { s: specks[id] || [] };
  const screen = (lon, lat) => { const q = g.project(g.toVector(lon, lat), b); return [side / 2 + R * q[0], side / 2 - R * q[1]]; };
  const near = (x, y, tol) => g.nearestEntry(L, meta, b, R, side / 2, side / 2, x, y, tol);
  return { screen, near, R };
}

test('hit tolerance: within the radius of an island only, measured to its coast on screen', () => {
  const v = toleranceView({ A: [[0, 0, 0.1]] });
  const [ex] = v.screen(0.1, 0); // east coast of A
  const [, cy] = v.screen(0, 0);
  const hit = v.near(ex + 10, cy, g.TOUCH_HIT_PX);
  assert.equal(hit.id, 'A');
  close(hit.px, 10, 1e-4); // the coast is a chord between vertices: a hair inside the arc
  // The anchor snaps to the coast point nearest the tap, on the island, not in the sea.
  close(hit.ll[0], 0.1, 1e-4); close(hit.ll[1], 0, 1e-6);
  assert.equal(v.near(ex + 10, cy, g.MOUSE_HIT_PX), null, '10 px is beyond the mouse radius');
  assert.equal(v.near(ex + 5, cy, g.MOUSE_HIT_PX).id, 'A');
  assert.equal(v.near(ex + 17, cy, g.TOUCH_HIT_PX), null);
  assert.equal(g.TOUCH_HIT_PX, 16);
  assert.equal(g.MOUSE_HIT_PX, 6);
});

test('hit tolerance: overlapping radii go to the nearest coast, ties to the lower id', () => {
  // Two islands 2° apart (~13 px): both are within 16 px of a point between them.
  const v = toleranceView({ B: [[-1, 0, 0.05]], A: [[1, 0, 0.05]] });
  const [west] = v.screen(-0.95, 0), [east] = v.screen(0.95, 0), [, y] = v.screen(0, 0);
  assert.ok(east - west < 2 * g.TOUCH_HIT_PX);
  assert.equal(v.near(west + 3, y, g.TOUCH_HIT_PX).id, 'B');
  assert.equal(v.near(east - 3, y, g.TOUCH_HIT_PX).id, 'A');
  assert.equal(v.near((west + east) / 2, y, g.TOUCH_HIT_PX).id, 'A', 'equal distance: lower id');
  // Per part, not per entry: a far part of the same entry does not widen the margin.
  const w = toleranceView({ C: [[0, 0, 0.05], [20, 10, 5]] });
  const [cx, cy] = w.screen(0, 0);
  assert.equal(w.near(cx, cy + 20, g.TOUCH_HIT_PX), null);
});

test('hit tolerance: undrawn specks are point targets; other land never is', () => {
  const v = toleranceView({}, { K: [[0, 0]] }, [[3, 0, 1]]);
  const [x, y] = v.screen(0, 0);
  const hit = v.near(x + 8, y - 6, g.TOUCH_HIT_PX);
  assert.equal(hit.id, 'K');
  close(hit.px, 10, 1e-6);
  close(hit.ll[0], 0, 1e-6); close(hit.ll[1], 0, 1e-6);
  const [ox] = v.screen(4.2, 0); // just off the east coast of the other land
  assert.equal(v.near(ox, y, g.TOUCH_HIT_PX), null);
});

test('hit tolerance: land behind the horizon never counts, even where its projection is near', () => {
  // An island just behind the limb (lon 92°) projects right next to the rim at x ≈ R.
  const v = toleranceView({ H: [[92, 0, 0.5]] }, { S: [[95, 5]] });
  const [x, y] = v.screen(88, 0);
  assert.equal(v.near(x, y, g.TOUCH_HIT_PX), null);
  // Rotated into view, the same island is found.
  const w = toleranceView({ H: [[88, 0, 0.5]] });
  const [x2, y2] = w.screen(86, 0);
  assert.equal(w.near(x2, y2, g.TOUCH_HIT_PX).id, 'H');
  // A part crossing the horizon is measured to its visible stretch: from just outside the
  // rim, the nearest coast is its visible west edge (lon 88°, the chord between its corners).
  const c = toleranceView({ X: [[91, 0, 3]] });
  const hit = c.near(400 + c.R + 5, 400, g.TOUCH_HIT_PX);
  assert.equal(hit.id, 'X');
  close(hit.px, c.R + 5 - c.R * Math.cos(3 * Math.PI / 180) * Math.sin(88 * Math.PI / 180), 1e-6);
});
