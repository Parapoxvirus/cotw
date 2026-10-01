// Hover/tap pick cost with the hit tolerance (issue #27): exact hit test, then on a miss over
// sea or space the nearest drawn coast within the touch radius. Seeded random resting views
// (800 CSS px, the level the globe rests at) and points, half of them within 20 px of a coast.
//
//   node tools/globe/pick-benchmark.js [--points 400]
//
// In a browser (CPU throttling via DevTools), load media/_cotw-globe*.js and this file, then
// call COTWPickBenchmark(COTWGlobe.api, world, { points: 400 }) with the decoded world.
'use strict';
(function (root) {
  function bench(api, W, opts) {
    var points = (opts && opts.points) || 400, repeat = (opts && opts.repeat) || 20;
    var side = 800, seed = 27, samples = { all: [], miss: [] }, byLevel = {};
    var clock = root.performance || { now: Date.now };
    function rand() { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }
    function pick(L, b, R, x, y) {
      var ll = api.invert((x - side / 2) / R, (side / 2 - y) / R, b), id = ll && api.hit(W, ll[0], ll[1]);
      if (!id && !(ll && api.hit(W, ll[0], ll[1], true))) {
        var near = api.nearestEntry(L, W.meta, b, R, side / 2, side / 2, x, y, api.TOUCH_HIT_PX);
        return { id: near && near.id, miss: true };
      }
      return { id: id, miss: false };
    }
    for (var k = 0; k < points; k++) {
      var lon = rand() * 360 - 180, lat = rand() * 130 - 60, zoom = [1, 1, 1.4, 3, 8][Math.floor(rand() * 5)];
      var R = side / 2 * api.SPHERE_FILL * zoom, level = api.chooseLevel(W.tolerances, R, api.LOD_REST_PX);
      var L = W.level(level), b = api.viewBasis(lon, lat), x, y;
      if (rand() < 0.5) {
        // Near a coast: a random visible vertex of a random visible entry part, up to 20 px off.
        var parts = [];
        Object.keys(L.entries).forEach(function (id) {
          L.entries[id].forEach(function (p) { if (api.capVisible(p.cap, p.capR, b.c, api.reachAngle(side, R))) parts.push(p); });
        });
        var v = parts.length && parts[Math.floor(rand() * parts.length)].rings[0].v, i = v ? 3 * Math.floor(rand() * v.length / 3) : 0;
        var q = v ? api.project([v[i], v[i + 1], v[i + 2]], b) : [0, 0, 1];
        x = side / 2 + R * q[0] + (rand() * 40 - 20);
        y = side / 2 - R * q[1] + (rand() * 40 - 20);
      } else {
        x = rand() * side; y = rand() * side;
      }
      var t0 = clock.now(), r;
      for (var n = 0; n < repeat; n++) r = pick(L, b, R, x, y);
      var ms = (clock.now() - t0) / repeat, name = W.names[level];
      samples.all.push(ms);
      if (r.miss) samples.miss.push(ms);
      (byLevel[name] = byLevel[name] || []).push(ms);
    }
    function dist(values) {
      var o = values.slice().sort(function (a, b) { return a - b; });
      var at = function (p) { return o.length ? Math.round(o[Math.min(o.length - 1, Math.ceil(o.length * p) - 1)] * 1000) / 1000 : null; };
      return { n: o.length, p50: at(0.5), p95: at(0.95), max: at(1) };
    }
    var out = { all: dist(samples.all), miss: dist(samples.miss), levels: {} };
    Object.keys(byLevel).sort().forEach(function (name) { out.levels[name] = dist(byLevel[name]); });
    return out;
  }
  root.COTWPickBenchmark = bench;

  if (typeof module === 'object' && module.exports && require.main === module) {
    var path = require('path'), media = path.join(__dirname, '..', '..', 'media');
    var api = require(path.join(media, '_cotw-globe.js')), W = api.prepWorld(api.data());
    ['zones', 'detail'].forEach(function (part) { W.installDetail(require(path.join(media, '_cotw-globe-' + part + '.js'))); });
    W.names.forEach(function (_, i) { W.level(i); });
    var at = process.argv.indexOf('--points');
    console.log(JSON.stringify(bench(api, W, { points: at > 0 ? Number(process.argv[at + 1]) : 400 }), null, 2));
  }
})(typeof window !== 'undefined' ? window : globalThis);
