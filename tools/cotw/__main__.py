"""Command line: ``python -m cotw <command>``."""

from __future__ import annotations

import argparse
import sys

from .paths import COUNTRIES, OVERRIDES, REGION_TAGS, ROOT


def cmd_validate(_args) -> int:
    import yaml

    from . import schema, wikidata

    entries = schema.load_all(COUNTRIES)
    exc_file = OVERRIDES / "exceptions.yaml"
    exceptions = yaml.safe_load(exc_file.read_text(encoding="utf-8")) if exc_file.exists() else {}
    sitelinks = wikidata.load_sitelinks() if wikidata.SITELINKS_CACHE.exists() else None
    problems = []
    for path, entry in entries.items():
        problems += schema.validate_entry(entry, path, exceptions, sitelinks)
    problems += schema.validate_all(entries, schema.load_regions_taxonomy(REGION_TAGS))
    for p in problems:
        print(p)
    print(f"{len(entries)} entries, {len(problems)} problems")
    return 1 if problems else 0


def cmd_fetch_wikidata(args) -> int:
    from . import importer, schema, wikidata

    entries = sorted(schema.load_all(COUNTRIES).values(), key=lambda e: e["id"])
    if args.step in ("all", "countries"):
        wikidata.dump(wikidata.COUNTRIES_CACHE, wikidata.fetch_countries([e["iso2"] for e in entries]))
    qids = sorted({e["wikidata"] for e in entries})
    if args.step in ("all", "capitals"):
        wikidata.dump(wikidata.CAPITALS_CACHE, wikidata.fetch_capitals(qids))
    capitals = wikidata.load_capitals()
    if args.step in ("all", "places"):
        # Label lookup only for capitals P36 does not cover (Oslo for Bouvet Island, …).
        labels = [
            c["name"]["en"]
            for e in entries
            for c in e["capitals"]
            if not importer.match_capital(c["name"]["en"], capitals.get(e["wikidata"], []))
        ]
        wikidata.dump(wikidata.PLACES_CACHE, wikidata.fetch_places(labels))
    if args.step in ("all", "status"):
        wikidata.dump(wikidata.STATUS_CACHE, wikidata.fetch_status(qids))
    if args.step in ("all", "iso-codes"):
        wikidata.dump(wikidata.ISO_CODES_CACHE, wikidata.fetch_iso_codes())
    print("Wikidata caches refreshed")
    return 0


def cmd_fetch_wikipedia(args) -> int:
    from . import languages, schema, wikidata
    from .importer import dump_entry

    base = languages.BASE
    entries = schema.load_all(COUNTRIES)
    if not args.offline:
        wikidata.dump(wikidata.SITELINKS_CACHE, wikidata.fetch_sitelinks([e["wikidata"] for e in entries.values()]))
    sitelinks = wikidata.load_sitelinks()
    changed, fallback = 0, []
    for path, entry in entries.items():
        links = wikidata.wikipedia_links(entry["wikipedia"][base], sitelinks.get(entry["wikidata"]))
        for code in languages.LANGUAGES:
            if code not in links:
                fallback.append((code, f"{entry['id']} {entry['name'][base]}"))
        if links != entry["wikipedia"]:
            entry["wikipedia"] = links
            path.write_text(dump_entry(entry), encoding="utf-8")
            changed += 1
    for code, f in fallback:
        print(f"no {languages.get(code).wiki} article, deck falls back to {base.upper()}: {f}")
    print(f"{changed} entries updated, {len(fallback)} missing articles")
    return 0


def cmd_fetch_naturalearth(_args) -> int:
    from . import naturalearth
    from .source import parse_source

    result = naturalearth.build({e.iso2 for e in parse_source()})
    naturalearth.write(result)
    print(f"{len(result['borders'])} entries with land borders, {len(result['ignored'])} units ignored")
    return 0


def _entries_by_id() -> dict:
    from . import schema

    return {e["id"]: e for e in schema.load_all(COUNTRIES).values()}


def cmd_fetch_flags(args) -> int:
    from . import flags

    entries = _entries_by_id()
    p41 = flags.load_p41() if args.offline_wikidata else flags.refresh_cache(entries)
    manifest, problems = flags.build(entries, p41, flags.load_overrides())
    for p in problems:
        print(p)
    if problems:
        print(f"{len(problems)} problems, nothing written")
        return 1
    flags.write_manifest(manifest)
    shared = sum(1 for r in manifest.values() if "shared_with" in r)
    print(f"{len(manifest)} flags written, {shared} shared with the sovereign")
    return 0


def cmd_fetch_marineregions(_args) -> int:
    from . import marineregions

    entries = _entries_by_id()
    marineregions.download()
    assigned = marineregions.load_geometry({e["iso3"] for e in entries.values()})
    manifest = marineregions.build_manifest(entries, assigned, assigned["skipped"])
    marineregions.write_manifest(manifest)
    without = [cid for cid, m in manifest["entries"].items() if not m["eez"]]
    print(f"{len(entries) - len(without)} entries with an EEZ, {len(without)} without, {len(manifest['skipped'])} polygons skipped")
    return 0


def cmd_build_maps(args) -> int:
    from . import maps

    entries = _entries_by_id()
    ids = args.ids or None
    unknown = [i for i in ids or [] if i not in entries]
    if unknown:
        print(f"unknown COTW ids: {unknown}")
        return 1
    sizes = maps.build(entries, ids)
    total = sum(sizes.values())
    print(f"{len(sizes)} maps, {total / 1024 / 1024:.1f} MB")
    if not ids:
        print(f"preview: {maps.write_preview(entries)}")
    return 0


def cmd_build_globe(_args) -> int:
    from . import globe

    entries = _entries_by_id()
    target, report = globe.build(entries)
    for k, v in report.items():
        print(f"{k:>18}: {v / 1024:8.1f} KB")
    print(f"{target.relative_to(target.parents[1])} written, preview: {globe.write_preview(entries)}")
    return 0


def cmd_build_ui(args) -> int:
    from pathlib import Path

    from . import ui

    for path in ui.build():
        print(f"{path.relative_to(ROOT)}")
    if args.check:
        for filtered in (False, True):
            name = "infographic-filtered" if filtered else "infographic"
            m = ui.fidelity(filtered)
            print(f"{name}: " + ", ".join(f"{k} {v:.4f}" if isinstance(v, float) else f"{k} {v}" for k, v in m.items()))
            print(f"  overlay: {ui.overlay(filtered, Path(ROOT / 'build' / f'{name}-overlay.png'))}")
    return 0


def cmd_build_deck(args) -> int:
    from pathlib import Path

    from . import languages
    from .deck import build

    langs = [args.lang] if args.lang else list(languages.LANGUAGES)
    out = Path(args.out) if args.out else build.BUILD
    try:
        built = build.build(langs, out, only=args.only)
    except ValueError as exc:
        print(exc)
        return 1
    for b in built:
        size = b.path.stat().st_size / 1024 / 1024
        print(f"{b.path.name}: {b.notes} notes, {b.cards} cards, {len(b.media)} media files, {size:.1f} MB")
    if not args.only:
        print(f"preview: {build.write_preview(out)}")
    return 0


def cmd_preview(_args) -> int:
    from . import maps

    print(maps.write_preview(_entries_by_id()))
    return 0


def cmd_check_wikidata(args) -> int:
    from . import monitor

    return monitor.check(args.dry_run, args.max_issues, args.gitea_url, args.repo)


def cmd_import_monitor_issues(args) -> int:
    from . import monitor

    return monitor.import_issues(args.apply, args.gitea_url, args.repo)


def cmd_accept_wikidata(args) -> int:
    from . import monitor

    return monitor.accept(args.fingerprint)


def cmd_import(args) -> int:
    from pathlib import Path

    from . import importer

    importer.run(Path(args.csv))
    return 0


def main(argv: list[str] | None = None) -> int:
    from . import languages

    parser = argparse.ArgumentParser(prog="cotw", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="check data/countries against the schema").set_defaults(func=cmd_validate)
    fw = sub.add_parser("fetch-wikidata", help="refresh data/wikidata/*.json (network)")
    fw.add_argument("--step", choices=["all", "countries", "capitals", "places", "status", "iso-codes"], default="all")
    fw.set_defaults(func=cmd_fetch_wikidata)
    fwp = sub.add_parser("fetch-wikipedia", help="Wikidata sitelinks → wikipedia.<lang> in data/countries (network)")
    fwp.add_argument("--offline", action="store_true", help="reuse data/wikidata/sitelinks.json")
    fwp.set_defaults(func=cmd_fetch_wikipedia)
    sub.add_parser("fetch-naturalearth", help="download Natural Earth, recompute data/derived/ne-borders.yaml (network)").set_defaults(func=cmd_fetch_naturalearth)
    ff = sub.add_parser("fetch-flags", help="Wikidata P41 → Commons flags with license check → media/*-flag.svg (network)")
    ff.add_argument("--offline-wikidata", action="store_true", help="reuse data/wikidata/flags.json instead of querying Wikidata")
    ff.set_defaults(func=cmd_fetch_flags)
    sub.add_parser("fetch-marineregions", help="download EEZ + 12 nm (Marine Regions WFS), write data/derived/maritime.yaml (network)").set_defaults(func=cmd_fetch_marineregions)
    bm = sub.add_parser("build-maps", help="render media/*-map{1,2}-{day,night}.svg from the cached geodata")
    bm.add_argument("ids", nargs="*", help="COTW ids (default: all)")
    bm.set_defaults(func=cmd_build_maps)
    sub.add_parser("build-globe", help="build globe bootstrap + deferred detail media from the cached geodata").set_defaults(func=cmd_build_globe)
    bu = sub.add_parser("build-ui", help="write media/ui/ (row icons and infographics per mode, from assets/ui)")
    bu.add_argument("--check", action="store_true", help="compare the infographics with the v3 PNGs, write overlays to build/ (needs shapely + Pillow)")
    bu.set_defaults(func=cmd_build_ui)
    bd = sub.add_parser("build-deck", help="build build/COTW-<LANG>.apkg per registered language and build/deck-preview.html")
    bd.add_argument("--lang", choices=languages.LANGUAGES, help="one language only (default: every registered language)")
    bd.add_argument("--out", help="output directory (default: build/)")
    bd.add_argument("--only", nargs="+", metavar="ID|ISO2", help="only these entries: COTW IDs or ISO-2 codes, comma- or space-separated (e.g. --only RU,KR,ZA 217)")
    bd.set_defaults(func=cmd_build_deck)
    cw = sub.add_parser("check-wikidata", help="compare the caches with live Wikidata/Commons, one issue (or Paperclip task) per change (network)")
    cw.add_argument("--dry-run", action="store_true", help="print the would-be issues, write nothing (default without COTW_MONITOR_TOKEN)")
    cw.add_argument("--max-issues", type=int, default=20, help="new issues per run; the rest go into one summary issue (default 20)")
    cw.add_argument("--gitea-url", help="Gitea base URL (default: $GITHUB_SERVER_URL)")
    cw.add_argument("--repo", help="owner/name (default: $GITHUB_REPOSITORY)")
    cw.set_defaults(func=cmd_check_wikidata)
    im = sub.add_parser("import-monitor-issues", help="seed the Paperclip sink's state branch with the fingerprints of the existing Gitea issues (network)")
    im.add_argument("--apply", action="store_true", help="write the state (default: dry run)")
    im.add_argument("--gitea-url", help="Gitea base URL (default: $GITHUB_SERVER_URL)")
    im.add_argument("--repo", help="owner/name (default: $GITHUB_REPOSITORY)")
    im.set_defaults(func=cmd_import_monitor_issues)
    aw = sub.add_parser("accept-wikidata", help="accept one deviation found by check-wikidata: update its cache keys (network)")
    aw.add_argument("fingerprint")
    aw.set_defaults(func=cmd_accept_wikidata)
    sub.add_parser("preview", help="write build/preview.html (contact sheet of all media)").set_defaults(func=cmd_preview)
    iv = sub.add_parser("import-v3", help="regenerate data/countries and docs/data-changes.md from the v3 spreadsheet export")
    iv.add_argument("csv", help="the v3 spreadsheet as CSV (not in the repository)")
    iv.set_defaults(func=cmd_import)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
