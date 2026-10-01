"""Reproduce the rc3 reviewer path in Chromium; no external requests or running server needed.
Records when first paint (L2, the coarsest level), the EEZ and fine land (L3) become ready per card.

python tools/globe/benchmark.py [--browser /path/to/chromium] [--samples 5]
Install .[browser] and run `playwright install chromium`, or pass an installed browser.
Writes JSON traces and screenshots to build/globe-benchmark/. Timings are observations,
not timing-sensitive CI assertions. Device approval still requires real Anki Desktop.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import math
from pathlib import Path
import shutil
import threading

from playwright.sync_api import sync_playwright

from cotw.deck import build
from cotw.deck.templates import globe_script, render, templates
from cotw.paths import BUILD


def distribution(values):
    ordered = sorted(values)
    return {key: round(ordered[min(len(ordered) - 1, math.ceil(len(ordered) * p) - 1)], 2)
            for key, p in (("p50", .5), ("p95", .95), ("max", 1))}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def fixtures(out):
    table = build.assets()
    names = {k: name for k, (name, _) in table.items()}
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    for name, source in table.values():
        shutil.copyfile(source, media / name)
    entries, by_id = build.load_entries()
    for source in build.field_media(entries):
        shutil.copyfile(source, media / source.name)
    tmpls = templates("en", names, build.load_config())
    cards = {}
    for cid, index in (("209", 3), ("117", 2), ("098", 9)):
        cards[cid] = render(tmpls[index]["afmt"], build.card_fields(by_id[cid], by_id, "en")).replace(globe_script(names), "")
    # The real card shell, CSS, images and font; only the container width is fixed.
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><base href="media/">'
        '<style>' + build.css(names) + '\n.cotw-globe{width:800px}.card{width:860px;margin:0 auto}</style>'
        '<div id="qa" class="card"></div>', encoding="utf-8")
    return names, cards


def show_card(page, names, card):
    return page.evaluate("""async ({names, card}) => {
      const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
      document.querySelector('#qa').innerHTML = card;
      window.onShownHook = [];
      await frame(); await frame(); // shell actually painted, as in the reported recording
      const start = performance.now();
      const script = document.createElement('script');
      script.src = names.globe;
      for (const part of ['zones', 'detail']) script.setAttribute(`data-${part}-src`, names[`globe-${part}`]);
      const first = await new Promise((resolve, reject) => {
        script.onload = () => resolve({...document.querySelector('.cotw-globe').__cotwGlobe.stats});
        script.onerror = reject;
        document.head.appendChild(script);
      });
      await frame(); await frame();
      script.remove();
      return {paintMs: performance.now() - start, firstPaintAt: performance.now(), start, first};
    }""", {"names": names, "card": card})


def wait_detail(page):
    page.wait_for_function("window.__cotwGlobeWorld.world.levels.every(Boolean)")
    page.wait_for_function("document.querySelector('.cotw-globe').__cotwGlobe.id in window.__cotwGlobeWorld.world.eezCache")
    # Decoded geometry is not a presented image. Include the staged paint and its final
    # canvas copy in the handoff window, then allow the Long Tasks observer to deliver.
    page.wait_for_function("""() => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe, W = window.__cotwGlobeWorld.world;
      return !g.pendingPaint && !g.frame && !g.dirty &&
        g.stats.level === COTWGlobe.api.chooseLevel(W.tolerances, g.radius(), COTWGlobe.api.LOD_REST_PX);
    }""")
    return page.evaluate("""() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe;
      resolve({readyAt: performance.now(), stats: {...g.stats}, view: [g.lon, g.lat, g.zoom]});
    })))""")


STAGES = ("firstPaint", "L2", "EEZ", "L3")


def stages(page, start):
    """When each improvement reached the visible canvas, in ms after the card shell (the
    bootstrap request): bordered first paint (L2, the coarsest level: issue #22 dropped L0, issue
    #31 L1), L2 (the same frame since #31), the entry's EEZ, and fine land L3 prepared (never presented at an overview zoom; a later
    zoom finds it ready). None =
    skipped because a finer level was already ready; L3 "cached" = prepared by an earlier card.
    ``prepared`` separates geometry preparation from the staged paint that presents it."""
    page.wait_for_function("""() => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe;
      return 'L2' in g.presented && 'EEZ' in g.presented && window.__cotwGlobeWorld.world.levels.every(Boolean);
    }""", timeout=60_000)
    return page.evaluate("""(start) => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe, W = window.__cotwGlobeWorld.world, seen = g.presented;
      const rel = t => t === undefined ? null : Math.round((t - start) * 10) / 10;
      const prepared = key => W.readyAt[key] >= start ? rel(W.readyAt[key]) : 'cached';
      return {firstPaint: rel(seen[W.names[0]]), L2: rel(seen.L2), EEZ: rel(seen.EEZ),
              L3: prepared('L3'), prepared: {L2: prepared('L2'), EEZ: prepared('EEZ:' + g.id)}};
    }""", start)


def stage_report(rows):
    out = {}
    for key in STAGES:
        values = [r[key] for r in rows if isinstance(r[key], (int, float))]
        out[key] = distribution(values) if values else None
        skipped = len(rows) - len(values)
        if skipped:
            out[key + "Skipped"] = sorted({str(r[key]) for r in rows if not isinstance(r[key], (int, float))})
    return out


def trace(page, region, mode, frames):
    lon, lat = (20, 15) if region == "africa-europe" else (-170.5, 0)
    page.evaluate("""([lon, lat]) => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe;
      g.lon = lon; g.lat = lat; g.zoom = 1.4; g.schedule();
    }""", [lon, lat])
    canvas = page.locator('.cotw-globe canvas')
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    x, y = box["x"] + 400, box["y"] + 400
    page.mouse.move(x, y)
    page.mouse.down()  # real pointer capture; moves below follow the same event handlers
    samples = page.evaluate("""async ({mode, frames, x, y}) => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe, samples = [];
      const canvas = g.canvas;
      let last = performance.now();
      for (let i = 0; i < frames; i++) {
        if (mode === 'drag') {
          canvas.dispatchEvent(new PointerEvent('pointermove', {pointerId: 1, pointerType: 'mouse',
            clientX: x + 140 * Math.sin((i + 1) / frames * Math.PI * 2), clientY: y + 80 * Math.sin((i + 1) / frames * Math.PI * 4)}));
        } else {
          canvas.dispatchEvent(new WheelEvent('wheel', {deltaY: i < frames / 2 ? -12 : 12, cancelable: true}));
        }
        await new Promise(resolve => requestAnimationFrame(resolve));
        const time = performance.now();
        samples.push({...g.stats, intervalMs: time - last, lon: g.lon, lat: g.lat, zoom: g.zoom});
        last = time;
      }
      return samples;
    }""", {"mode": mode, "frames": frames, "x": x, "y": y})
    # Pointer is still held: screenshot the actual interaction frame, with visible borders.
    return samples


def resting_view(page, out, throttle):
    """A high-zoom handoff, then input during a second staged image."""
    start = page.evaluate("""() => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe;
      g.lon = 20; g.lat = 35; g.zoom = 6; g.schedule(); return performance.now();
    }""")
    ready = wait_detail(page)
    assert ready['view'] == [20, 35, 6]
    assert ready['stats']['name'] == 'L3' and ready['stats']['stroke']
    page.locator('.cotw-globe').screenshot(path=out / f'africa-europe-{throttle}x-rest.png')
    tasks = page.evaluate('longTasks')
    result = {
        'maxSliceMs': round(ready['stats']['maxSliceMs'], 2),
        'longTasksMs': [t['ms'] for t in tasks if start <= t['start'] <= ready['readyAt']],
        'viewPreserved': True,
    }
    # Start a replacement and interrupt it before any idle callback can complete it.
    interrupted = page.evaluate("""async () => {
      const g = document.querySelector('.cotw-globe').__cotwGlobe;
      g.lon = 25; g.draw();
      const staged = !!g.pendingPaint;
      g.canvas.dispatchEvent(new WheelEvent('wheel', {deltaY: -30, cancelable: true}));
      const cancelled = !g.pendingPaint;
      await new Promise(resolve => requestAnimationFrame(resolve));
      return {staged, cancelled, view: [g.lon, g.lat, g.zoom], stats: {...g.stats}};
    }""")
    assert interrupted['staged'] and interrupted['cancelled']
    assert interrupted['stats']['interacting'] and interrupted['stats']['stroke']
    ready = wait_detail(page)
    assert ready['view'] == interrupted['view']
    result['interruptedHandoffPreservesInput'] = True
    return result


def run(args):
    out = args.out.resolve()
    names, cards = fixtures(out)
    report = {"widthCssPx": 800, "dpr": 2, "samplesPerLoad": args.samples, "framesPerTrace": args.frames, "runs": []}
    report['assets'] = {
        key: {'bytes': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        for key, (_, source) in build.assets().items() if key in build.GLOBE_ASSETS
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(out)))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.browser, headless=True)
            report["browser"] = browser.version
            for throttle in (1, 4):
                cold, subsequent, traces, errors, handoffs = [], [], {}, [], []
                cold_stages, subsequent_stages = [], []
                for sample in range(args.samples):
                    context = browser.new_context(viewport={"width": 1000, "height": 1050}, device_scale_factor=2, color_scheme="dark")
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    session = context.new_cdp_session(page)
                    session.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    # Report whole-load and post-paint handoff tasks separately from draw CPU time.
                    page.evaluate("""() => {
                      window.longTasks = [];
                      new PerformanceObserver(list => list.getEntries().forEach(e => longTasks.push({start: e.startTime, ms: e.duration})))
                        .observe({entryTypes: ['longtask']});
                    }""")
                    cold.append(show_card(page, names, cards["209"]))
                    initial_view = page.evaluate("""() => {
                      const g = document.querySelector('.cotw-globe').__cotwGlobe; return [g.lon, g.lat, g.zoom];
                    }""")
                    cold_stages.append(stages(page, cold[-1]['start']))
                    ready = wait_detail(page)
                    assert ready['view'] == initial_view, (initial_view, ready)
                    tasks = page.evaluate("longTasks")
                    handoffs.append({
                        'afterFirstPaintMs': round(ready['readyAt'] - cold[-1]['firstPaintAt'], 2),
                        'maxSliceMs': round(ready['stats'].get('maxSliceMs', 0), 2),
                        'longTasksMs': [t['ms'] for t in tasks if cold[-1]['firstPaintAt'] <= t['start'] <= ready['readyAt']],
                        # When they started, in ms after the card shell (compare with the stages).
                        'longTaskStartsMs': [round(t['start'] - cold[-1]['start'], 1) for t in tasks
                                             if cold[-1]['firstPaintAt'] <= t['start'] <= ready['readyAt']],
                        'viewPreserved': True,
                    })
                    subsequent.append(show_card(page, names, cards["117"]))
                    subsequent_stages.append(stages(page, subsequent[-1]['start']))
                    wait_detail(page)
                    if sample == args.samples - 1:
                        long_tasks = page.evaluate("longTasks")
                        for region in ("africa-europe", "pacific"):
                            for mode in ("drag", "wheel"):
                                rows = trace(page, region, mode, args.frames)
                                assert all(r["stroke"] and r["borders"] and r["interacting"] for r in rows), (region, mode, rows[:2])
                                traces[f"{region}-{mode}"] = rows
                                if mode == "drag":
                                    page.locator('.cotw-globe').screenshot(path=out / f"{region}-{throttle}x-moving.png")
                                page.mouse.up()
                                page.wait_for_timeout(200)
                        # Real multi-touch through Chromium's input boundary.
                        canvas = page.locator('.cotw-globe canvas').bounding_box()
                        cx, cy = canvas['x'] + 400, canvas['y'] + 400
                        pinch = []
                        for i in range(46):
                            distance = 80 + i * 3
                            points = [{"x": cx - distance, "y": cy, "id": 1}, {"x": cx + distance, "y": cy, "id": 2}]
                            session.send("Input.dispatchTouchEvent", {"type": "touchStart" if i == 0 else "touchMove", "touchPoints": points})
                            row = page.evaluate("""() => new Promise(resolve => requestAnimationFrame(() => resolve(
                              {...document.querySelector('.cotw-globe').__cotwGlobe.stats})))""")
                            if i: pinch.append(row)
                        session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                        assert all(r['stroke'] and r['interacting'] for r in pinch)
                        traces['pacific-pinch'] = pinch
                        # Theme remains controlled solely by Anki's class, despite dark OS above.
                        page.evaluate("document.querySelector('#qa').classList.add('nightMode'); COTWGlobe.renderAll()")
                        page.wait_for_function("document.querySelector('.cotw-globe').__cotwGlobe.night")
                        page.locator('.cotw-globe').screenshot(path=out / f"pacific-{throttle}x-night.png")
                        page.wait_for_timeout(200)
                        page.evaluate("document.querySelector('#qa').classList.remove('nightMode'); COTWGlobe.renderAll()")
                        wait_detail(page)
                        resting = resting_view(page, out, throttle)
                        show_card(page, names, cards['098'])
                        page.evaluate("document.querySelector('#qa').classList.remove('nightMode'); COTWGlobe.renderAll()")
                        page.locator('img.cotw-day[src*="098-map2"]').screenshot(path=out / f"vatican-map2-{throttle}x.png")
                        (out / f"traces-{throttle}x.json").write_text(json.dumps(traces, indent=2) + '\n')
                    context.close()
                assert not errors, errors
                report['runs'].append({
                    "cpuThrottle": throttle,
                    "coldPaintMs": distribution([r['paintMs'] for r in cold]),
                    "subsequentPaintMs": distribution([r['paintMs'] for r in subsequent]),
                    "coldStagesMs": stage_report(cold_stages),
                    "subsequentStagesMs": stage_report(subsequent_stages),
                    "stageSamples": {"cold": cold_stages, "subsequent": subsequent_stages},
                    "firstFrames": [r['first'] for r in cold + subsequent],
                    "loadLongTasksMs": [round(t['ms'], 2) for t in long_tasks],
                    "coldDetailHandoffLongTasksMs": [t for h in handoffs for t in h['longTasksMs']],
                    "coldDetailHandoffs": handoffs,
                    "highZoomRest": resting,
                    "traces": {name: {"drawMs": distribution([r['ms'] for r in rows]),
                                      "rafIntervalMs": distribution([r['intervalMs'] for r in rows]) if 'intervalMs' in rows[0] else None,
                                      "levels": sorted({r['name'] for r in rows}), "bordersEveryFrame": True}
                               for name, rows in traces.items()},
                })
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', help='Installed Chromium executable (default: Playwright Chromium)')
    parser.add_argument('--out', type=Path, default=BUILD / 'globe-benchmark')
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--frames', type=int, default=120)
    run(parser.parse_args())
