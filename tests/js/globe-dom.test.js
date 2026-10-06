// The packaged scripts in an Anki-like persistent window, with explicit frame/idle queues.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const media = path.join(__dirname, '..', '..', 'media');
const bootstrap = fs.readFileSync(path.join(media, '_cotw-globe.js'), 'utf8');
const PARTS = ['zones', 'detail'];
const partScripts = Object.fromEntries(PARTS.map(part =>
  [part, fs.readFileSync(path.join(media, `_cotw-globe-${part}.js`), 'utf8')]));
const detail = require(path.join(media, '_cotw-globe-detail.js'));
const hashed = Object.fromEntries(PARTS.map(part => [`data-${part}-src`, `_cotw-globe-${part}-1234abcd.js`]));

function reviewer({ tooltip = false } = {}) {
  let clock = 0, sequence = 0;
  const frames = new Map(), idle = new Map(), timers = new Map(), tasks = new Map(), strokes = [], writes = [], fills = [];
  const enqueue = q => fn => { const id = ++sequence; q.set(id, fn); return id; };
  const context = {
    setTransform() {}, clearRect() { writes.push(this.canvas); }, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {},
    arc() {}, closePath() {}, fill() { fills.push([this.canvas, this.fillStyle]); writes.push(this.canvas); },
    save() {}, restore() {}, clip() {},
    stroke() { strokes.push(this.strokeStyle); writes.push(this.canvas); },
    getImageData() {}, drawImage() { writes.push(this.canvas); }
  };
  function element(tag, attrs = {}) {
    return {
      tag, attrs, style: {}, children: [], clientWidth: 800,
      getAttribute(k) { return this.attrs[k] || null; },
      hasAttribute(k) { return k in this.attrs; },
      closest() { return this.night ? this : null; },
      appendChild(el) { this.children.push(el); el.parentNode = this; },
      removeChild(el) { this.children.splice(this.children.indexOf(el), 1); el.parentNode = null; },
      addEventListener() {}, removeEventListener() {}, setPointerCapture() {},
      getContext() { return this.context || (this.context = Object.assign(Object.create(context), { canvas: this })); },
      getBoundingClientRect() { return { left: 0, top: 0 }; }
    };
  }
  const tip = tooltip ? { 'data-tooltip': '' } : {};
  let card = element('div', { 'data-id': '209', 'data-lang': 'de', ...hashed, ...tip });
  const head = element('head');
  const document = {
    head, readyState: 'complete',
    currentScript: { src: 'https://example.com/media/_cotw-globe.js',
      getAttribute: k => hashed[k] || null },
    createElement: element,
    querySelectorAll: () => [card],
    querySelector: () => card,
    documentElement: { contains: el => el === card },
    addEventListener() {}, removeEventListener() {}
  };
  const window = {
    document, devicePixelRatio: 2, onShownHook: [],
    performance: { now: () => (clock += 0.1) },
    getComputedStyle: () => ({ position: 'static' }),
    requestAnimationFrame: enqueue(frames), cancelAnimationFrame: id => frames.delete(id),
    requestIdleCallback: enqueue(idle), cancelIdleCallback: id => idle.delete(id),
    setTimeout: enqueue(timers), clearTimeout: id => timers.delete(id),
    // Plain tasks (MessageChannel): continuation slices of started background work.
    MessageChannel: function () {
      const port1 = {};
      this.port1 = port1;
      this.port2 = { postMessage: () => enqueue(tasks)(() => port1.onmessage()) };
    },
    addEventListener() {}, removeEventListener() {}
  };
  const sandbox = vm.createContext({ window, document });
  const run = code => vm.runInContext(code, sandbox);
  // Tap timing (double tap = two taps within 350 ms) follows an explicit clock.
  let wall = 1e6;
  run('Date.now = function () { return window.__wall(); };');
  window.__wall = () => wall;
  const drain = queue => { const callbacks = [...queue.values()]; queue.clear(); callbacks.forEach(fn => fn()); };
  return {
    window, document, head, frames, idle, timers, tasks, strokes, context, writes, fills,
    wait: ms => { wall += ms; },
    run, boot: () => run(bootstrap),
    // A packet script arriving (the reviewer executes it); load() = every packet.
    loadPart: part => run(partScripts[part]), load: () => PARTS.forEach(part => run(partScripts[part])),
    requested: () => head.children.map(el => el.src.replace(/^.*\/_cotw-globe-|-1234abcd\.js$|\.js$/g, '')),
    advance: ms => { clock += ms; },
    frame: () => drain(frames), work: () => { drain(idle); drain(tasks); }, settle: () => drain(timers),
    globe: () => card.__cotwGlobe,
    world: () => window.__cotwGlobeWorld.world,
    finish() {
      for (let n = 0; frames.size || idle.size || tasks.size; n++) {
        assert.ok(n < 10000, 'deferred work did not finish');
        drain(idle); drain(tasks); drain(frames);
      }
    },
    replace(id, attrs = {}) { card = element('div', { 'data-id': id, 'data-lang': 'de', ...attrs }); }
  };
}

test('a cold card paints bootstrap borders before requesting or decoding detail', () => {
  const r = reviewer();
  r.boot();
  assert.equal(r.globe().stats.level, 0);
  assert.equal(r.globe().stats.stroke, true);
  assert.ok(r.strokes.includes(r.world().palette.day.coast));
  assert.equal(r.world().hasDetail(), false);
  assert.equal(r.head.children.length, 0);
  assert.equal(r.idle.size, 0);
  r.frame();
  assert.equal(r.head.children.length, 0, 'one rAF is still before first paint');
  r.frame();
  assert.deepEqual(r.requested(), ['zones'], 'no land packet for an overview: L2 is in the bootstrap');
  assert.equal(r.head.children[0].src, 'https://example.com/media/_cotw-globe-zones-1234abcd.js');
  assert.equal(r.world().levels[1], null);
});

test('reviewers without currentScript resolve the hashed detail reference from the card', () => {
  const r = reviewer();
  r.document.currentScript = null;
  r.boot(); r.frame(); r.frame();
  assert.equal(r.head.children[0].src, '_cotw-globe-zones-1234abcd.js');
  r.finish(); r.settle(); // deep idle
  assert.equal(r.head.children[1].src, '_cotw-globe-detail-1234abcd.js');
  r.load(); r.finish();
  assert.equal(r.world().hasDetail(), true);
});

test('deferred detail preserves rotation/zoom, pauses during drag, and publishes complete levels', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame();
  const g = r.globe();
  g.lon = 25; g.lat = 10; g.zoom = 6;
  g.interact();
  r.load(); r.frame();
  // One idle callback during a gesture must not decode detail.
  const work = [...r.idle.values()]; r.idle.clear(); work.forEach(fn => fn());
  assert.equal(r.world().levels[1], null);
  g.interacting = false;
  r.finish();
  assert.deepEqual([g.lon, g.lat, g.zoom], [25, 10, 6]);
  assert.equal(g.stats.level, 1);
  assert.ok(r.world().eez(g.id).length);
  assert.equal(g.stats.stroke, true);
});

test('drag, wheel and pinch draw shared borders and coalesce repeated input into one frame', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.load(); r.finish();
  const g = r.globe();
  const pointer = (pointerId, x, y) => ({ pointerId, clientX: x, clientY: y, pointerType: 'touch' });
  g.handlers.pointerdown(pointer(1, 200, 200));
  for (let i = 0; i < 20; i++) g.handlers.pointermove(pointer(1, 201 + i, 210));
  assert.equal(r.frames.size, 1);
  r.frame();
  assert.ok(g.stats.stroke && g.stats.borders > 0);
  assert.equal(g.stats.name, 'L2');
  g.handlers.wheel({ preventDefault() {}, deltaY: -200, deltaMode: 0 });
  r.frame();
  assert.equal(g.stats.stroke, true);
  g.handlers.pointerdown(pointer(2, 400, 200));
  const before = g.zoom;
  g.handlers.pointermove(pointer(2, 600, 200));
  r.frame();
  assert.ok(g.zoom > before && g.stats.stroke);
  g.handlers.pointerup(pointer(1, 220, 210));
  g.handlers.pointerup(pointer(2, 600, 200));
  r.settle(); r.finish();
  assert.equal(g.interacting, false);
});

test('subsequent cards keep decoded data but present bootstrap L2 borders first', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.load(); r.finish();
  const world = r.world(), first = r.globe();
  r.window.onShownHook = []; // Anki resets the hook list for every card
  r.replace('117'); r.boot();
  assert.equal(first.alive, false);
  assert.equal(r.world(), world);
  assert.equal(r.window.onShownHook.length, 1);
  assert.equal(r.globe().stats.id, '117');
  assert.equal(r.globe().stats.level, 0);
  assert.equal(r.globe().stats.stroke, true);
  r.finish();
  assert.deepEqual(r.requested(), ['zones'], 'packets are loaded only once per world');
});

test('an over-budget interaction draw stays at L2 with borders (no fallback below L2, #31)', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.load(); r.finish();
  const g = r.globe(), stroke = r.context.stroke;
  // Zoom 3 rests at L3; interaction is capped at L2, the coarsest level.
  g.zoom = 3; g.interact();
  r.context.stroke = function () { stroke.call(this); r.advance(20); };
  for (let i = 0; i < 5; i++) {
    g.draw();
    assert.equal(g.stats.name, 'L2');
    assert.ok(g.stats.ms > 16 && g.stats.stroke && g.stats.borders > 0);
  }
  r.context.stroke = stroke;
});

test('a reused card element also starts the next entry at bootstrap quality', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.load(); r.finish();
  const g = r.globe();
  g.el.attrs['data-id'] = '117';
  r.boot();
  assert.equal(r.globe(), g);
  assert.equal(g.stats.id, '117');
  assert.equal(g.stats.level, 0);
  assert.equal(g.stats.stroke, true);
});

test('missing detail keeps an interactive bordered world and retries on a subsequent card', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame();
  [...r.head.children].forEach(el => el.onerror()); r.finish();
  assert.equal(r.world().hasDetail(), false);
  assert.ok(r.globe().stats.stroke);
  assert.equal(r.globe().stats.level, 0, 'the bootstrap level (L2) stays');
  r.settle(); r.finish();
  assert.deepEqual(r.requested(), ['detail'], 'deep idle still tries the fine land once');
  r.head.children[0].onerror(); r.settle(); r.finish();
  assert.deepEqual(r.requested(), [], 'no retry loop on the same card');
  r.replace('117'); r.boot(); r.frame(); r.frame();
  assert.deepEqual(r.requested(), ['zones']);
  r.load(); r.finish();
  assert.equal(r.world().hasDetail(), true);
});

test('a deck switch cancels old work and rejects a late detail response from the previous deck', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame();
  const first = r.globe(), oldWorld = r.world();
  const code = bootstrap.replace(r.window.COTWGlobe.dataKey, '12345678').replace(detail.key, '0000000000000000');
  r.run(code);
  assert.equal(r.window.onShownHook.length, 1, 'retired renderers leave no stale hook');
  assert.deepEqual(r.requested(), [], 'pending packet scripts of the old deck are removed');
  assert.equal(first.alive, false);
  assert.notEqual(r.world(), oldWorld);
  r.load();
  assert.equal(r.world().hasDetail(), false);
  r.finish();
  assert.equal(r.world().hasDetail(), false);
  assert.ok(r.globe().stats.stroke);
});

function detailedReviewer() {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.load(); r.finish();
  return r;
}

test('a warm cache does not add detailed EEZ work to a new card first paint', () => {
  const r = detailedReviewer(), W = r.world(), eez = W.eez;
  assert.ok(W.eezCache['209'].length);
  W.eez = () => { throw new Error('EEZ must wait until after first paint'); };
  r.replace('209');
  assert.doesNotThrow(() => r.boot());
  assert.equal(r.globe().stats.level, 0);
  assert.equal(r.globe().stats.stroke, true);
  assert.equal(r.globe().stats.eez, false);
  W.eez = eez;
  r.finish();
  assert.equal(r.globe().stats.level, 0);
  assert.equal(r.globe().stats.eez, true);
});

test('resting detail keeps the complete bordered image visible until one atomic presentation', () => {
  const r = detailedReviewer(), g = r.globe();
  const before = g.stats, visibleWrites = () => r.writes.filter(c => c === g.canvas).length;
  const count = visibleWrites();
  g.lon = 20; g.lat = 35; g.zoom = 6;
  g.draw();
  assert.ok(g.pendingPaint, 'fine detail must not draw synchronously');
  assert.equal(g.stats, before);
  assert.equal(visibleWrites(), count);
  // Slow rasterization must yield too, not just path construction.
  const flush = r.context.getImageData;
  r.context.getImageData = () => { r.advance(4); };
  r.work();
  assert.ok(g.pendingPaint);
  assert.equal(visibleWrites(), count, 'a partial fill/mesh must never reach the visible canvas');
  r.context.getImageData = flush;
  r.finish();
  assert.equal(visibleWrites(), count + 1);
  assert.equal(g.stats.level, 1);
  assert.ok(g.stats.stroke && g.stats.borders && g.stats.maxSliceMs);
  assert.deepEqual([g.lon, g.lat, g.zoom], [20, 35, 6]);
});

test('new input cancels a completed resting image before it can overwrite the gesture', () => {
  const r = detailedReviewer(), g = r.globe();
  g.lon = 20; g.zoom = 6; g.draw();
  for (let i = 0; !g.presentFrame; i++) {
    assert.ok(i < 1000);
    r.work();
  }
  const oldFrame = g.presentFrame;
  g.handlers.wheel({ preventDefault() {}, deltaY: -100, deltaMode: 0 });
  assert.equal(g.pendingPaint, null);
  assert.equal(r.frames.has(oldFrame), false);
  r.frame();
  assert.ok(g.stats.interacting && g.stats.stroke && g.stats.level === 0);
  const view = [g.lon, g.lat, g.zoom];
  r.settle(); r.finish();
  assert.deepEqual([g.lon, g.lat, g.zoom], view);
  assert.equal(g.stats.level, 1);
});

test('theme and size changes discard staged images and preserve a bordered first resized frame', () => {
  const r = detailedReviewer(), g = r.globe();
  g.zoom = 6; g.draw(); r.work();
  const dayJob = g.pendingPaint;
  g.el.night = true; r.boot();
  assert.notEqual(g.pendingPaint, dayJob);
  r.finish();
  assert.equal(g.night, true);
  assert.ok(r.strokes.includes(r.world().palette.night.coast));
  g.lon += 10; g.draw();
  g.canvas.clientWidth = 400;
  g.resize(false);
  assert.equal(g.pendingPaint, null);
  assert.equal(g.stats.level, 0);
  assert.equal(g.canvas.width, 800);
  assert.equal(g.stats.stroke, true);
  r.finish();
  assert.equal(g.stats.level, 1);
  assert.equal(g.buffer.width, 800);
});

test('replacing a card or renderer cancels staged work and releases its pixel buffer', () => {
  const r = detailedReviewer(), old = r.globe();
  old.lon += 10; old.draw(); r.work();
  const buffer = old.buffer;
  r.replace('117'); r.boot();
  assert.equal(old.pendingPaint, null);
  assert.equal(old.presentFrame, 0);
  assert.equal(buffer.width, 0);
  r.finish();
  assert.equal(r.globe().stats.id, '117');
  const previous = r.globe(), world = r.world();
  previous.lon += 10; previous.draw();
  // A renderer-only update must invalidate the world even with identical geography.
  r.run(bootstrap.replace(/var VERSION = \d+;/, 'var VERSION = 999;'));
  assert.equal(previous.alive, false);
  assert.equal(previous.pendingPaint, null);
  assert.notEqual(r.world(), world);
  assert.equal(r.globe().stats.level, 0);
});

test('a zoomed-out globe rests and drags at L2, the bootstrap level', () => {
  const r = detailedReviewer(), g = r.globe();
  assert.equal(g.stats.name, 'L2');
  g.interact(); g.draw();
  assert.ok(g.stats.interacting && g.stats.stroke);
  assert.equal(g.stats.name, 'L2', 'rotating keeps the resting level');
});

test('sustained dropped frames never lower interaction detail below L2 (#31)', () => {
  const r = detailedReviewer(), g = r.globe();
  g.zoom = 3; g.interact(); g.draw();
  assert.equal(g.stats.name, 'L2');
  for (let i = 0; i < 10; i++) { g.schedule(); r.advance(40); r.frame(); }
  assert.ok(g.stats.frameWaitMs > 34, 'the dropped frames are still measured');
  assert.equal(g.stats.name, 'L2');
  assert.equal(g.stats.stroke, true);
  r.settle(); r.finish();
  assert.equal(g.stats.name, 'L3', 'the resting view gets fine land afterwards');
});

/** Every frame a globe presents (synchronous or a staged copy) publishes new ``stats``:
 *  record each of them, from the synchronous first paint in the constructor on. */
function recordFrames(el, frames) {
  let globe;
  Object.defineProperty(el, '__cotwGlobe', {
    configurable: true,
    get: () => globe,
    set: g => {
      globe = g;
      let stats = g.stats;
      Object.defineProperty(g, 'stats', {
        configurable: true, get: () => stats, set: v => { stats = v; if (v) frames.push({ ...v }); }
      });
    }
  });
}

test('no presented frame is coarser than L2: first paint, rest, drag, slow frames, missing packets (#31)', () => {
  const r = reviewer({ tooltip: true }), frames = [];
  recordFrames(r.document.querySelector(), frames);
  r.boot();
  const g = r.globe(), W = r.world(), stroke = r.context.stroke;
  assert.deepEqual(Array.from(W.names), ['L2', 'L3'], 'L2 is the coarsest level');
  assert.deepEqual(frames.map(f => f.name), ['L2'], 'cold first paint, before any packet');
  const touch = (x, y) => ({ pointerId: 3, clientX: x, clientY: y, pointerType: 'touch' });
  function drag(slow) {
    r.context.stroke = slow ? function () { stroke.call(this); r.advance(20); } : stroke;
    g.handlers.pointerdown(touch(300, 300));
    for (let i = 1; i <= 8; i++) {
      g.handlers.pointermove(touch(300 + 15 * i, 300 + 5 * i));
      if (slow) r.advance(40); // dropped frames, beyond any former fallback threshold
      r.frame();
    }
    g.handlers.pointerup(touch(420, 340));
    r.context.stroke = stroke;
    r.settle(); r.finish();
  }
  // Zoomed in, the view wants L3, but both packets fail: rest and drag while waiting.
  g.zoom = 6;
  r.frame(); r.frame();
  [...r.head.children].forEach(el => el.onerror());
  r.finish(); r.settle(); r.finish();
  [...r.head.children].forEach(el => el.onerror());
  assert.equal(W.levels[1], null, 'fine land never arrived');
  drag(false); drag(true);
  // Zoomed out, rotating while the zones load.
  g.zoom = 1; g.schedule(); r.frame(); r.finish();
  drag(false);
  // Every packet: rests at L3 when zoomed in, drags at L2, also under slow frames.
  r.load(); g.zoom = 6; g.schedule(); r.frame(); r.finish();
  assert.equal(g.stats.name, 'L3');
  drag(false); drag(true);
  assert.equal(g.stats.name, 'L3');
  // A resized canvas and a new card on the warm cache paint first, synchronously.
  g.canvas.clientWidth = 400; g.resize(false); r.finish();
  r.replace('117');
  recordFrames(r.document.querySelector(), frames);
  r.boot(); r.frame(); r.frame(); r.finish();
  drag(false);

  const moving = frames.filter(f => f.interacting);
  assert.ok(moving.length >= 40 && frames.some(f => f.name === 'L3'), 'every case was exercised');
  assert.ok(moving.some(f => f.ms > 16) && moving.some(f => f.frameWaitMs > 34), 'slow frames were simulated');
  for (const f of frames) {
    assert.ok(f.name === 'L2' || f.name === 'L3', `presented ${f.name}`);
    assert.ok(f.stroke && f.borders > 0, 'every frame has borders');
  }
  assert.deepEqual([...new Set(moving.map(f => f.name))], ['L2'], 'interaction is always L2');
});

test('timer-only WebViews also finish and cancel sliced resting work', () => {
  const r = reviewer();
  delete r.window.requestIdleCallback;
  delete r.window.cancelIdleCallback;
  delete r.window.MessageChannel;
  r.boot(); r.frame(); r.frame(); r.load();
  for (let i = 0; r.frames.size || r.timers.size; i++) {
    assert.ok(i < 10000);
    r.settle(); r.frame();
  }
  const g = r.globe();
  assert.equal(g.stats.level, 0);
  assert.equal(g.stats.eez, true);
  assert.equal(g.pendingPaint, null);
  g.zoom = 6; g.draw();
  assert.ok(g.pendingPaint);
  assert.equal(r.timers.size, 1, 'one slice queued as a plain timer');
  r.window.COTWGlobe.retire();
  assert.equal(g.pendingPaint, null);
  r.settle();
  assert.equal(r.timers.size, 0, 'the queued slice of a retired globe stops');
  assert.equal(r.frames.size, 0);
});

// --- progressive: L2 first paint, EEZ afterwards, fine land on demand (issues #17, #22, #31) ---

/** Run frames and idle work until ``done()``; returns whether it happened. */
function until(r, done) {
  for (let n = 0; n < 10000; n++) {
    if (done()) return true;
    if (!r.frames.size && !r.idle.size && !r.tasks.size) return done();
    r.work(); r.frame();
  }
  return false;
}

test('a cold card presents bordered L2 before any packet, then adds the EEZ when the zones arrive', () => {
  const r = reviewer();
  r.boot();
  const g = r.globe();
  assert.equal(g.stats.name, 'L2', 'the first paint is L2, the coarsest level (no L1 since #31)');
  assert.deepEqual(Object.keys(g.presented), ['L2']);
  r.frame(); r.frame();
  r.finish();
  assert.equal(g.stats.level, 0, 'L2 comes from the bootstrap');
  assert.equal(g.stats.want, 0, 'a zoomed-out view waits for no land');
  assert.ok(g.stats.stroke && g.stats.borders > 0);
  assert.deepEqual(r.requested(), ['zones'], 'nor for fine land');
  r.loadPart('zones'); r.finish();
  assert.equal(g.stats.level, 0, 'the zone never changes land detail');
  assert.equal(g.stats.eez, true);
  assert.ok(g.presented.L2 < g.presented.EEZ);
  assert.equal(g.presented.L3, undefined);
});

test('the EEZ is the only resting handoff of a zoomed-out card', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.load();
  const g = r.globe(), shown = [], draw = r.context.drawImage;
  // Every resting improvement is one atomic copy of a complete staged image; L2 is the
  // synchronous first paint.
  r.context.drawImage = function (...a) { draw.apply(this, a); shown.push(g.pendingPaint.key.split(':').slice(-2).join(':')); };
  r.finish();
  assert.deepEqual(shown, ['0:true']);
  assert.ok(g.presented.L2 < g.presented.EEZ);
});

test('a new country on a warm cache gets L2 land at first paint, its zone afterwards', () => {
  const r = detailedReviewer(), W = r.world();
  r.replace('117'); r.boot();
  const g = r.globe();
  assert.equal(g.stats.name, 'L2');
  assert.equal(g.stats.eez, false);
  assert.equal('117' in W.eezCache, false);
  r.frame(); r.frame();
  r.finish();
  assert.equal(g.stats.level, 0);
  assert.equal(g.stats.eez, true);
});

test('fine land is loaded only when a resting view needs it', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.loadPart('zones'); r.finish();
  const g = r.globe();
  assert.deepEqual(r.requested(), ['zones']);
  g.handlers.wheel({ preventDefault() {}, deltaY: -1500, deltaMode: 0 });
  r.frame();
  assert.deepEqual(r.requested(), ['zones'], 'interaction never needs fine land');
  const settle = [...r.timers.entries()].filter(([, fn]) => fn.toString().includes('interacting = false'));
  settle.forEach(([id, fn]) => { r.timers.delete(id); fn(); });
  r.frame();
  assert.equal(g.waitingFor, 1);
  r.finish();
  assert.equal(g.stats.name, 'L2', 'L2 stays visible meanwhile');
  assert.deepEqual(r.requested(), ['zones', 'detail']);
  assert.equal(r.head.children[1].async, true);
  r.loadPart('detail'); r.finish();
  assert.equal(g.stats.name, 'L3');
  assert.ok(g.stats.eez && g.stats.stroke);
});

test('deep idle loads fine land only once all visible work is done and nobody interacts', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.loadPart('zones');
  r.settle();
  assert.deepEqual(r.requested(), ['zones'], 'not while visible work remains');
  r.finish();
  const g = r.globe();
  g.interact();
  r.settle(); // the settle timer ends the gesture first, re-arming deep idle meanwhile
  r.finish();
  assert.deepEqual(r.requested(), ['zones']);
  r.settle(); r.finish();
  assert.deepEqual(r.requested(), ['zones', 'detail']);
  r.loadPart('detail'); r.finish();
  assert.ok(r.world().levels[1], 'fine land is prepared ahead of a later zoom');
  assert.equal(g.stats.name, 'L2', 'an overview view is not repainted with fine land');
});

test('a staged EEZ image is dropped by input and never overwrites the gesture', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.loadPart('zones');
  const g = r.globe();
  assert.ok(until(r, () => g.pendingPaint));
  assert.equal(g.stats.eez, false);
  g.handlers.pointerdown({ pointerId: 1, clientX: 100, clientY: 100, pointerType: 'mouse' });
  g.handlers.pointermove({ pointerId: 1, clientX: 140, clientY: 110, pointerType: 'mouse' });
  assert.equal(g.pendingPaint, null);
  r.frame();
  const view = [g.lon, g.lat, g.zoom];
  assert.ok(g.stats.interacting && g.stats.stroke);
  assert.equal(g.stats.name, 'L2');
  r.loadPart('detail');
  r.work(); r.frame();
  assert.equal(r.world().levels[1], null, 'no preparation while the pointer is held');
  g.handlers.pointerup({ pointerId: 1, clientX: 140, clientY: 110, pointerType: 'mouse' });
  r.settle(); r.finish();
  assert.deepEqual([g.lon, g.lat, g.zoom], view);
  assert.equal(g.stats.name, 'L2');
  assert.equal(g.stats.eez, true);
  assert.equal(g.stats.interacting, false);
});

test('preparation resumes as soon as a staged image is presented, without waiting for idle time', () => {
  const r = reviewer();
  r.boot();
  const g = r.globe();
  g.zoom = 6; // rests at L3: two staged images (the visible zone first, then fine land)
  r.frame(); r.frame(); r.loadPart('zones'); r.loadPart('detail');
  // Only plain tasks and animation frames: no idle period ever arrives.
  for (let n = 0; n < 10000 && !(g.stats.eez && g.stats.name === 'L3'); n++) {
    const tasks = [...r.tasks.values()]; r.tasks.clear(); tasks.forEach(fn => fn());
    r.frame();
  }
  assert.equal(g.stats.name, 'L3');
  assert.equal(g.stats.eez, true);
  assert.ok(g.presented.L2 < g.presented.EEZ && g.presented.EEZ < g.presented.L3);
});

test('fine land being prepared in deep idle yields to the next card\'s zone', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.loadPart('zones'); r.finish();
  r.loadPart('detail');
  for (let i = 0; i < 3; i++) r.work(); // L3 preparation started, far from done
  const W = r.world();
  assert.equal(W.levels[1], null);
  r.replace('117'); r.boot(); r.frame(); r.frame();
  assert.ok(until(r, () => '117' in W.eezCache));
  assert.equal(W.levels[1], null, 'the zone did not wait for fine land');
  r.finish();
  assert.ok(W.levels[1], 'fine land resumed afterwards');
  assert.equal(r.globe().stats.eez, true);
});

// --- tooltip selection: one entry for the tooltip and the selected fill (issue #18) ---------

const SOUTH_KOREA = '209', NORTH_KOREA = '163', JAPAN = '112';

/** A back-side card (tooltip on) with every packet loaded and all work done. */
function backReviewer() {
  const r = reviewer({ tooltip: true });
  r.boot(); r.frame(); r.frame(); r.load(); r.finish();
  return r;
}

/** Client point (the mock canvas sits at 0,0) of a lon/lat in the globe's presented view. */
function pointOf(r, g, lon, lat, extra = {}) {
  const api = r.window.COTWGlobe.api, q = api.project(api.toVector(lon, lat), g.basis), R = g.radius();
  return { clientX: g.side / 2 + R * q[0], clientY: g.side / 2 - R * q[1], ...extra };
}

const center = (r, id) => r.world().meta[id].c;
const mouse = (r, g, id, extra) => pointOf(r, g, ...center(r, id), { pointerId: 1, pointerType: 'mouse', ...extra });
const touch = (r, g, id, extra) => pointOf(r, g, ...center(r, id), { pointerId: 7, pointerType: 'touch', ...extra });
const SEA = [126, 30]; // East China Sea, far from any coast (well beyond the hit tolerance)

function tap(r, g, point) {
  r.wait(1000); // taps of a test are single taps unless it says otherwise
  g.handlers.pointerdown(point);
  g.handlers.pointerup(point);
}

const selectedFills = (r, canvas, night) =>
  r.fills.filter(([c, style]) => c === canvas && style === r.world().palette[night ? 'night' : 'day'].selected).length;

test('palette carries the selected colors for day and night', () => {
  const r = reviewer();
  r.boot();
  const { day, night } = r.world().palette;
  assert.equal(day.selected, '#D5D7A4');
  assert.equal(night.selected, '#75634F');
  // Day: a quiet warm shift of the ordinary land, far lighter than the green entry and
  // closer to the land than the neighbor fill is (the entry stays the strongest emphasis).
  const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  const dist = (a, b) => Math.hypot(...rgb(a).map((v, i) => v - rgb(b)[i]));
  const light = hex => rgb(hex).reduce((s, v) => s + v, 0);
  assert.ok(dist(day.selected, day.land) > 10, 'still distinguishable from ordinary land');
  assert.ok(dist(day.selected, day.land) < dist(day.neighbor, day.land));
  assert.ok(light(day.selected) > light(day.neighbor) && light(day.neighbor) > light(day.entry));
});

test('mouse hover is coalesced into one frame and selects tooltip + fill together', () => {
  const r = backReviewer(), g = r.globe();
  assert.equal(g.stats.name, 'L2');
  for (let i = 0; i < 25; i++) g.handlers.pointermove(mouse(r, g, NORTH_KOREA, { clientX: mouse(r, g, NORTH_KOREA).clientX + i / 10 }));
  assert.equal(r.frames.size, 1, 'raw pointermoves share one animation frame');
  assert.equal(g.selected, null, 'no hit test before the frame');
  const writes = r.writes.length, fills = r.fills.length;
  r.frame();
  assert.equal(g.selected, NORTH_KOREA);
  assert.equal(g.tip.style.display, 'block');
  assert.equal(g.tip.textContent, 'Nordkorea');
  assert.equal(g.shownSelection, NORTH_KOREA);
  // The overlay: one copy of the presented image, one selected fill, clipped strokes. The
  // world is not repainted (no other fill on the visible canvas, no staged paint).
  const visibleFills = r.fills.slice(fills).filter(([c]) => c === g.canvas);
  assert.deepEqual(visibleFills.map(([, style]) => style), [r.world().palette.day.selected]);
  assert.equal(r.writes.slice(writes).filter(c => c === g.buffer).length, 0, 'nothing staged');
  assert.equal(g.pendingPaint, null);
  assert.equal(r.frames.size, 0, 'nothing else queued');
  // Switch to another country, then the sea clears both.
  g.handlers.pointermove(mouse(r, g, JAPAN)); r.frame();
  assert.equal(g.selected, JAPAN);
  assert.equal(g.tip.textContent, 'Japan');
  assert.equal(g.shownSelection, JAPAN);
  g.handlers.pointermove(pointOf(r, g, ...SEA, { pointerId: 1, pointerType: 'mouse' })); r.frame();
  assert.equal(g.selected, null);
  assert.equal(g.shownSelection, null);
  assert.equal(g.tip.style.display, 'none');
  // Leaving the globe clears too, including a hover still waiting for its frame.
  g.handlers.pointermove(mouse(r, g, NORTH_KOREA)); r.frame();
  assert.equal(g.selected, NORTH_KOREA);
  g.handlers.pointermove(mouse(r, g, JAPAN));
  g.handlers.pointerleave({ pointerType: 'mouse' });
  r.frame();
  assert.equal(g.selected, null);
  assert.equal(g.shownSelection, null);
  assert.equal(g.tip.style.display, 'none');
});

test('the tooltip speaks data-lang as given, English for a language without names', () => {
  const r = backReviewer(), g = r.globe();
  const hover = lang => {
    g.el.attrs['data-lang'] = lang;
    g.configure();
    g.handlers.pointermove(mouse(r, g, NORTH_KOREA)); r.frame();
    const text = g.tip.textContent;
    g.handlers.pointerleave({ pointerType: 'mouse' }); r.frame();
    return text;
  };
  assert.equal(hover('de'), 'Nordkorea');
  assert.equal(hover('en'), 'North Korea');
  assert.equal(r.world().meta[NORTH_KOREA].name.xx, undefined);
  assert.equal(hover('xx'), 'North Korea', 'no names in that language: the English ones');
  r.world().meta[NORTH_KOREA].name.xx = 'Nordkorea (xx)';  // a newly registered language
  assert.equal(hover('xx'), 'Nordkorea (xx)');
});

test('the entry under the pointer shows its tooltip but keeps its own green', () => {
  const r = backReviewer(), g = r.globe();
  const fills = r.fills.length;
  g.handlers.pointermove(mouse(r, g, SOUTH_KOREA)); r.frame();
  assert.equal(g.selected, SOUTH_KOREA);
  assert.equal(g.tip.textContent, 'Südkorea');
  assert.equal(g.shownSelection, null, 'no selected fill over the entry');
  assert.equal(selectedFills({ fills: r.fills.slice(fills), world: r.world }, g.canvas), 0);
  // Also inline, during interaction.
  g.interact(); g.draw();
  assert.equal(g.shownSelection, null);
  assert.equal(selectedFills({ fills: r.fills.slice(fills), world: r.world }, g.canvas), 0);
});

test('touch: a tap selects, another tap switches, a tap on the sea clears', () => {
  const r = backReviewer(), g = r.globe();
  tap(r, g, touch(r, g, NORTH_KOREA));
  assert.equal(g.selected, NORTH_KOREA);
  assert.equal(g.tip.style.display, 'block');
  r.settle(); r.finish();
  assert.equal(g.stats.interacting, false);
  assert.equal(g.shownSelection, NORTH_KOREA, 'the resting image carries the selection');
  tap(r, g, touch(r, g, JAPAN));
  assert.equal(g.selected, JAPAN);
  assert.equal(g.tip.textContent, 'Japan');
  r.settle(); r.finish();
  assert.equal(g.shownSelection, JAPAN);
  tap(r, g, pointOf(r, g, ...SEA, { pointerId: 7, pointerType: 'touch' }));
  assert.equal(g.selected, null);
  assert.equal(g.tip.style.display, 'none');
  r.settle(); r.finish();
  assert.equal(g.shownSelection, null);
});

test('drag, pinch and wheel never select; the selection follows the moving globe', () => {
  const r = backReviewer(), g = r.globe();
  // A drag that starts on North Korea is not a tap.
  const start = touch(r, g, NORTH_KOREA);
  g.handlers.pointerdown(start);
  g.handlers.pointermove({ ...start, clientX: start.clientX + 40 });
  g.handlers.pointerup({ ...start, clientX: start.clientX + 40 });
  assert.equal(g.selected, null);
  r.settle(); r.finish();
  // Select Japan, then drag from the sea: the selection stays and tracks.
  tap(r, g, touch(r, g, JAPAN));
  r.settle(); r.finish();
  const before = g.tipAt.slice(), fills = r.fills.length;
  const sea = pointOf(r, g, ...SEA, { pointerId: 7, pointerType: 'touch' });
  g.handlers.pointerdown(sea);
  // Leaving the touch slop starts the drag without moving the globe; rotation follows from there.
  const from = { ...sea, clientX: sea.clientX + 13 };
  g.handlers.pointermove(from);
  r.frame();
  assert.equal(g.tipAt[0], before[0], 'no jump when the drag starts');
  g.handlers.pointermove({ ...from, clientX: from.clientX - 60, clientY: from.clientY + 20 });
  r.frame();
  assert.equal(g.selected, JAPAN);
  assert.equal(g.stats.interacting, true);
  assert.equal(g.shownSelection, JAPAN, 'interaction frames paint the selection inline');
  assert.ok(selectedFills({ fills: r.fills.slice(fills), world: r.world }, g.canvas) > 0);
  assert.equal(g.tip.style.display, 'block');
  assert.ok(Math.abs(g.tipAt[0] - (before[0] - 60)) <= 15 && Math.abs(g.tipAt[1] - (before[1] + 20)) <= 15,
    `the tooltip moved with its country: ${before} → ${g.tipAt}`);
  g.handlers.pointerup({ ...from, clientX: from.clientX - 60, clientY: from.clientY + 20 });
  assert.equal(g.selected, JAPAN, 'the end of a drag is not a tap on the sea');
  // Pinch with one finger on North Korea: its fingers never count as taps.
  const a = touch(r, g, NORTH_KOREA, { pointerId: 1 }), b = { ...a, pointerId: 2, clientX: a.clientX + 100 };
  g.handlers.pointerdown(a); g.handlers.pointerdown(b);
  g.handlers.pointermove({ ...b, clientX: b.clientX + 50 });
  g.handlers.pointerup(a); g.handlers.pointerup({ ...b, clientX: b.clientX + 50 });
  assert.equal(g.selected, JAPAN);
  g.handlers.wheel({ preventDefault() {}, deltaY: -100, deltaMode: 0 });
  r.frame();
  assert.equal(g.selected, JAPAN);
  r.settle(); r.finish();
  assert.equal(g.shownSelection, JAPAN, 'the settled resting image composes the selection');
  assert.equal(g.stats.interacting, false);
});

test('a tap with finger jitter inside the slop selects and never drops to an interaction frame', () => {
  const r = backReviewer(), g = r.globe();
  const view = [g.lon, g.lat, g.zoom], level = g.stats.level, draws = [], draw = g.draw;
  g.draw = function () { draws.push(this.interacting); return draw.apply(this, arguments); };
  const p = touch(r, g, NORTH_KOREA);
  g.handlers.pointerdown(p);
  // 8–10 px of jitter while the finger rests, in several directions.
  for (const [dx, dy] of [[4, 3], [8, 0], [-6, 6], [0, -10], [7, 7]]) {
    g.handlers.pointermove({ ...p, clientX: p.clientX + dx, clientY: p.clientY + dy });
  }
  assert.equal(r.frames.size, 0, 'no redraw requested inside the slop');
  assert.equal(g.interacting, false);
  g.handlers.pointerup({ ...p, clientX: p.clientX + 7, clientY: p.clientY + 7 });
  assert.equal(g.selected, NORTH_KOREA, 'a jittered tap is still a tap');
  r.settle(); r.finish();
  assert.deepEqual([g.lon, g.lat, g.zoom], view, 'the globe did not turn');
  assert.ok(!draws.includes(true), 'no interacting (coarse) frame was drawn');
  assert.equal(g.stats.interacting, false);
  assert.equal(g.stats.level, level, 'the resting level stays');
  assert.equal(g.shownSelection, NORTH_KOREA);
});

test('a drag beyond the slop rotates from where it left the slop, without a jump', () => {
  const r = backReviewer(), g = r.globe();
  const p = touch(r, g, JAPAN);
  g.handlers.pointerdown(p);
  g.handlers.pointermove({ ...p, clientX: p.clientX + 11 });
  assert.equal(g.interacting, false, 'still inside the 12 px touch slop');
  const lon0 = g.lon;
  g.handlers.pointermove({ ...p, clientX: p.clientX + 14 });
  assert.equal(g.interacting, true, 'the drag starts once the slop is exceeded');
  assert.equal(g.lon, lon0, 'the distance covered inside the slop is not applied');
  r.frame();
  assert.ok(g.stats.interacting && g.stats.stroke);
  g.handlers.pointermove({ ...p, clientX: p.clientX + 54 });
  r.frame();
  const k = 1 / (g.radius() * Math.PI / 180);
  assert.ok(Math.abs(g.lon - (lon0 - 40 * k)) < 1e-9, 'rotation follows the pointer from the slop edge');
  g.handlers.pointerup({ ...p, clientX: p.clientX + 54 });
  assert.equal(g.selected, null, 'a drag is not a tap');
  // A mouse has a smaller slop: 6 px already drags.
  const m = { ...mouse(r, g, JAPAN), pointerId: 3 };
  r.settle(); r.finish();
  g.handlers.pointerdown(m);
  g.handlers.pointermove({ ...m, clientX: m.clientX + 6 });
  assert.equal(g.interacting, true);
  g.handlers.pointerup({ ...m, clientX: m.clientX + 6 });
  r.settle(); r.finish();
  assert.equal(g.stats.interacting, false);
});

test('a double-tap reset leaves no selection, even at the initial view', () => {
  const r = backReviewer(), g = r.globe();
  tap(r, g, touch(r, g, JAPAN));
  r.settle(); r.finish();
  assert.equal(g.shownSelection, JAPAN);
  const p = touch(r, g, NORTH_KOREA);
  tap(r, g, p);
  assert.equal(g.selected, NORTH_KOREA);
  r.wait(200); g.handlers.pointerdown(p); g.handlers.pointerup(p); // second tap within 350 ms
  assert.equal(g.selected, null);
  assert.equal(g.tip.style.display, 'none');
  r.settle(); r.finish();
  assert.equal(g.shownSelection, null, 'the view did not change, the fill is gone anyway');
  // Mouse double click resets the same way.
  g.handlers.pointermove(mouse(r, g, JAPAN)); r.frame();
  assert.equal(g.selected, JAPAN);
  g.handlers.dblclick({ preventDefault() {} });
  assert.equal(g.selected, null);
  r.finish();
  assert.equal(g.shownSelection, null);
});

test('the front without a tooltip never selects or fills', () => {
  const r = reviewer();
  r.boot(); r.frame(); r.frame(); r.load(); r.finish();
  const g = r.globe();
  g.handlers.pointermove(mouse(r, g, NORTH_KOREA));
  assert.equal(r.frames.size, 0, 'no hover work at all');
  tap(r, g, touch(r, g, NORTH_KOREA));
  r.settle(); r.finish();
  assert.equal(g.selected, null);
  assert.notEqual(g.tip.style.display, 'block');
  assert.equal(selectedFills(r, g.canvas), 0);
  assert.equal(g.base, undefined, 'no base buffer is kept without a tooltip');
  // Switching an existing back to tooltip-less clears a selection.
  const back = backReviewer(), h = back.globe();
  tap(back, h, touch(back, h, NORTH_KOREA));
  back.settle(); back.finish();
  delete h.el.attrs['data-tooltip'];
  back.boot();
  assert.equal(h.selected, null);
  assert.equal(h.tip.style.display, 'none');
  back.finish();
  assert.equal(h.shownSelection, null);
});

test('card replacement, a reused element, a theme switch and retire clear the selection', () => {
  const r = backReviewer(), g = r.globe();
  tap(r, g, touch(r, g, NORTH_KOREA)); r.settle(); r.finish();
  assert.ok(g.base && g.base.width);
  // A new card (new element): the old globe is destroyed with its selection and buffers.
  const base = g.base;
  r.window.onShownHook = [];
  r.replace('117', { 'data-tooltip': '' }); r.boot();
  assert.equal(g.alive, false);
  assert.equal(g.selected, null);
  assert.equal(g.tip.style.display, 'none');
  assert.equal(base.width, 0, 'the base buffer is released');
  r.finish();
  const k = r.globe();
  assert.equal(k.selected, null);
  // A reused element with a new entry.
  r.replace(SOUTH_KOREA, { 'data-tooltip': '' }); r.boot(); r.finish();
  const s = r.globe();
  tap(r, s, touch(r, s, JAPAN)); r.settle(); r.finish();
  assert.equal(s.shownSelection, JAPAN);
  s.el.attrs['data-id'] = '117';
  r.boot();
  assert.equal(s.selected, null);
  assert.equal(s.tip.style.display, 'none');
  r.finish();
  assert.equal(s.shownSelection, null);
  // Theme switch.
  s.el.attrs['data-id'] = SOUTH_KOREA; r.boot(); r.finish();
  tap(r, s, touch(r, s, JAPAN)); r.settle(); r.finish();
  s.el.night = true; r.boot();
  assert.equal(s.selected, null);
  r.finish();
  assert.equal(s.night, true);
  assert.equal(s.shownSelection, null);
  // Night selection uses the night color.
  const fills = r.fills.length;
  tap(r, s, touch(r, s, JAPAN)); r.settle(); r.finish();
  assert.ok(selectedFills({ fills: r.fills.slice(fills), world: r.world }, s.canvas, true) > 0);
  assert.equal(selectedFills({ fills: r.fills.slice(fills), world: r.world }, s.canvas, false), 0);
  // Retire (deck update).
  r.window.COTWGlobe.retire();
  assert.equal(s.selected, null);
  assert.equal(s.tip.style.display, 'none');
  assert.equal(s.hoverFrame + s.selectFrame, 0);
});

test('a selection made at first paint survives the EEZ handoff and does not delay it', () => {
  const r = reviewer({ tooltip: true });
  r.boot(); r.frame(); r.frame();
  const g = r.globe();
  // Hover before anything was presented from a staged buffer: the shown L2 is repainted
  // directly.
  g.handlers.pointermove(mouse(r, g, NORTH_KOREA)); r.frame();
  assert.equal(g.selected, NORTH_KOREA);
  assert.equal(g.shownSelection, NORTH_KOREA);
  r.finish();
  assert.equal(g.stats.level, 0);
  assert.equal(g.shownSelection, NORTH_KOREA);
  r.loadPart('zones');
  // Hover while the EEZ is being staged: the staged paint is neither cancelled nor restarted.
  assert.ok(until(r, () => g.pendingPaint));
  const job = g.pendingPaint;
  g.handlers.pointermove(mouse(r, g, JAPAN)); r.frame();
  assert.equal(g.selected, JAPAN);
  assert.equal(g.pendingPaint, job);
  r.finish();
  assert.equal(g.stats.name, 'L2');
  assert.equal(g.stats.eez, true);
  assert.equal(g.shownSelection, JAPAN, 'the EEZ presentation carries the selection');
  assert.ok(g.presented.L2 < g.presented.EEZ);
});

test('the tooltip is clamped inside the globe for long German names near the rim', () => {
  const r = backReviewer(), g = r.globe();
  const W = r.world(), side = g.side, margin = r.window.COTWGlobe.api.TIP_MARGIN;
  // Measured size of a long name (the mock DOM has no layout).
  Object.defineProperty(g.tip, 'offsetWidth', { get: () => 420 });
  Object.defineProperty(g.tip, 'offsetHeight', { get: () => 36 });
  // Anchors 1 px inside the left, right, top and bottom edge (the zoomed sphere overfills
  // the canvas), and the four corners of the disc at zoom 1.
  const edges = [[1, side / 2], [side - 1, side / 2], [side / 2, 1], [side / 2, side - 1]];
  const check = (px, py) => {
    const R = g.radius(), ll = r.window.COTWGlobe.api.invert((px - side / 2) / R, (side / 2 - py) / R, g.basis);
    g.select({ id: '027', ll });
    assert.equal(g.tip.textContent, 'Bonaire, Sint Eustatius und Saba / Karibische Niederlande');
    assert.equal(g.tip.style.display, 'block', `visible at ${px},${py}`);
    assert.equal(g.tip.style.maxWidth, `${side - 2 * margin}px`);
    const [left, top] = g.tipAt;
    assert.ok(left >= margin && left + 420 <= side - margin, `left ${left} at ${px},${py}`);
    assert.ok(top >= margin && top + 36 <= side - margin, `top ${top} at ${px},${py}`);
    return [left, top];
  };
  assert.ok(g.radius() > side / 2);
  const placed = edges.map(([x, y]) => check(x, y));
  assert.equal(placed[0][0], margin, 'left edge: flush with the margin');
  assert.equal(placed[1][0], side - margin - 420, 'right edge');
  assert.ok(placed[2][1] > 1, 'top edge: below the anchor instead of above');
  assert.equal(placed[3][1], side - 1 - 36 - 6, 'bottom edge: above the anchor');
  g.zoom = 1; g.draw(); r.finish();
  const R = g.radius();
  for (const a of [45, 135, 225, 315].map(d => d * Math.PI / 180)) {
    check(side / 2 + 0.99 * R * Math.cos(a), side / 2 - 0.99 * R * Math.sin(a));
  }
  // An anchor behind the horizon hides the tooltip, the selection stays.
  g.lon += 180; g.draw(); r.finish();
  assert.equal(g.selected, '027');
  assert.equal(g.tip.style.display, 'none');
  assert.ok(W.meta['027']);
});

// --- hit tolerance: small islands can be hit (issue #27) ----------------------------------

const US = '237', KIRIBATI = '117', SAMOA = '193', AMERICAN_SAMOA = '005';

/** Rest the back-side globe at a view (all packets loaded, the resting level presented). */
function viewAt(r, g, lon, lat, zoom) {
  g.lon = lon; g.lat = lat; g.zoom = zoom;
  g.draw(); r.finish();
  assert.equal(g.stats.interacting, false);
}

/** Canvas point of a lon/lat in the presented view. */
function screenAt(r, g, lon, lat) {
  const p = pointOf(r, g, lon, lat);
  return [p.clientX, p.clientY];
}

/** Outer-ring vertices ([lon, lat]) of the entry's drawn parts that satisfy ``keep(box)``. */
function drawnVertices(r, g, id, keep) {
  const out = [];
  for (const poly of r.world().levels[g.stats.level].entries[id]) {
    if (!keep(poly.box)) continue;
    const ll = poly.rings[0].ll;
    for (let i = 0; i < ll.length; i += 2) out.push([ll[i], ll[i + 1]]);
  }
  return out;
}

const at = ([x, y], pointerType) => ({ pointerId: pointerType === 'mouse' ? 1 : 7, pointerType, clientX: x, clientY: y });
const exactHit = (r, g, [x, y]) => {
  const R = g.radius(), api = r.window.COTWGlobe.api;
  const ll = api.invert((x - g.side / 2) / R, (g.side / 2 - y) / R, g.basis);
  return ll && api.hit(r.world(), ll[0], ll[1]);
};

test('a tap 10 px off a small island selects it on touch, not with a mouse', () => {
  const r = backReviewer(), g = r.globe();
  viewAt(r, g, -157, 20.5, 1);
  assert.equal(g.stats.name, 'L2');
  // Hawaii's Big Island, about 8 px across: the tap goes 10 px east of its easternmost point.
  const coast = drawnVertices(r, g, US, b => b[0] > -157 && b[2] < -154 && b[1] > 18 && b[3] < 21)
    .reduce((a, v) => (screenAt(r, g, ...v)[0] > screenAt(r, g, ...a)[0] ? v : a));
  const [x, y] = screenAt(r, g, ...coast), off = [x + 10, y];
  assert.equal(exactHit(r, g, off), null, 'the tap is on the sea');
  tap(r, g, at(off, 'mouse'));
  assert.equal(g.selected, null, 'a mouse click 10 px off does not select');
  tap(r, g, at(off, 'touch'));
  assert.equal(g.selected, US);
  assert.equal(g.tip.textContent, 'Vereinigte Staaten');
  // The tooltip sits on the island's coast, not where the finger went down.
  const [ax, ay] = screenAt(r, g, ...g.anchor);
  assert.ok(Math.hypot(ax - x, ay - y) < 0.5, `anchor ${ax},${ay} vs coast ${x},${y}`);
  // A tap on the sea far from any coast still clears.
  tap(r, g, at(screenAt(r, g, -150, 12), 'touch'));
  assert.equal(g.selected, null);
  // Mouse hover: within 6 px selects, 10 px does not.
  g.handlers.pointermove(at([x + 4, y], 'mouse')); r.frame();
  assert.equal(g.selected, US);
  g.handlers.pointermove(at(off, 'mouse')); r.frame();
  assert.equal(g.selected, null);
});

test('overlapping tolerances: the nearer coast wins between two islands', () => {
  const r = backReviewer(), g = r.globe();
  viewAt(r, g, -171.4, -14, 4);
  // Upolu (Samoa) and Tutuila (American Samoa): the facing points of both coasts.
  const samoa = drawnVertices(r, g, SAMOA, () => true).map(v => screenAt(r, g, ...v));
  const tutuila = drawnVertices(r, g, AMERICAN_SAMOA, b => b[2] < -170.4 && b[0] > -171).map(v => screenAt(r, g, ...v));
  let pair = null;
  for (const a of samoa) for (const b of tutuila) {
    const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (!pair || d < pair.d) pair = { a, b, d };
  }
  assert.ok(pair.d > 10 && pair.d < 2 * r.window.COTWGlobe.api.TOUCH_HIT_PX, `gap ${pair.d}`);
  const toward = (p, q, px) => [p[0] + (q[0] - p[0]) * px / pair.d, p[1] + (q[1] - p[1]) * px / pair.d];
  const nearSamoa = toward(pair.a, pair.b, 3), nearTutuila = toward(pair.b, pair.a, 3);
  assert.equal(exactHit(r, g, nearSamoa), null);
  assert.equal(exactHit(r, g, nearTutuila), null);
  tap(r, g, at(nearSamoa, 'touch'));
  assert.equal(g.selected, SAMOA);
  tap(r, g, at(nearTutuila, 'touch'));
  assert.equal(g.selected, AMERICAN_SAMOA);
});

test('exact hits are unchanged: the tolerance only applies over sea or space', () => {
  const r = backReviewer(), g = r.globe();
  const W = r.world(), api = r.window.COTWGlobe.api;
  // Korea, China and Japan with their shared borders: every exact hit keeps its entry.
  let land = 0;
  for (let x = 250; x <= 550; x += 6) {
    for (let y = 250; y <= 550; y += 6) {
      const id = exactHit(r, g, [x, y]);
      if (!id) continue;
      land++;
      assert.equal(g.pick(x, y, api.TOUCH_HIT_PX).id, id, `${x},${y}`);
    }
  }
  assert.ok(land > 500, `${land} land points`);
  // Antarctica (other land) is never a tolerance target: 10 px off its coast clears, and a
  // tap on it does not reach a nearby entry either.
  viewAt(r, g, 0, -65, 1);
  const ice = W.levels[g.stats.level].other.find(p => p.box[1] <= -89);
  let north = null;
  const ll = ice.rings[0].ll;
  for (let i = 0; i < ll.length; i += 2) if (Math.abs(ll[i]) < 3 && (!north || ll[i + 1] > north[1])) north = [ll[i], ll[i + 1]];
  const [x, y] = screenAt(r, g, ...north);
  assert.equal(exactHit(r, g, [x, y - 10]), null);
  tap(r, g, at([x, y - 10], 'touch'));
  assert.equal(g.selected, null);
  assert.equal(g.pick(x, y + 10, api.TOUCH_HIT_PX), null, 'on Antarctica');
});

test('islands the globe does not draw (specks) can be tapped', () => {
  const r = backReviewer(), g = r.globe();
  const flint = [-152, -11.5]; // a Kiribati speck, no drawn land nearby
  assert.ok(r.world().meta[KIRIBATI].s.some(([lon, lat]) => lon === flint[0] && lat === flint[1]));
  viewAt(r, g, flint[0], flint[1], 1);
  const [x, y] = screenAt(r, g, ...flint);
  assert.equal(exactHit(r, g, [x, y]), null, 'not drawn: no exact hit');
  tap(r, g, at([x, y], 'touch'));
  assert.equal(g.selected, KIRIBATI);
  assert.deepEqual(Array.from(g.anchor, v => Math.round(v * 1e6) / 1e6), flint, 'the tooltip sits on the speck');
  tap(r, g, at([x - 6, y + 8], 'touch'));
  assert.equal(g.selected, KIRIBATI, '10 px off the speck');
  tap(r, g, at([x - 6, y + 8], 'mouse'));
  assert.equal(g.selected, null);
});
