# Countries of the World (COTW)

Build pipeline for the **Countries of the World (COTW)** Anki deck: a single country
database generates language-specific decks (EN, DE, …) that share one set of
language-neutral media (flags, maps, globe).

Status: all five steps of [`docs/ROADMAP.md`](docs/ROADMAP.md) are done; the last one, a
weekly Wikidata change check, keeps the data current ([`docs/MONITORING.md`](docs/MONITORING.md)).
Design in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## The decks

```bash
.venv/bin/python -m cotw build-deck      # build/COTW-EN.apkg, build/COTW-DE.apkg, build/deck-preview.html
.venv/bin/python -m cotw build-deck --only RU,KR,ZA --out build/test   # test packages with a few entries
```

- **`COTW-EN.apkg`**: deck *Countries of the World*, note type *COTW (EN)*, English only.
- **`COTW-DE.apkg`**: deck *Länder der Welt*, note type *COTW (DE)*, German only.

Each has 248 entries × 10 card types (capital, flag, map, ISO code and bordering countries, both
directions) with two maps and an interactive globe. The five recommended card types sit in
the main deck, the five extras in the subdeck `…::Extras`; suspend that subdeck's cards in the
Browser to switch them off. **Installing both** is fine: import one, then the other (any
order) with *File → Import*. They share the media files and never touch each other's notes,
so each can be updated later on its own. Details: [`docs/DECK.md`](docs/DECK.md).

## Borders

The maps and the globe draw borders as their source, [Natural Earth](https://www.naturalearthdata.com),
supplies them, and Natural Earth maps **de facto** borders: who actually controls an area.
Crimea, for example, is shown as Russian, not Ukrainian, and the disputed areas in the Himalayas
(Kashmir, Aksai Chin, Arunachal Pradesh) follow the lines of actual control. Overlapping
maritime claims follow the administering party too ([`docs/MAPS.md`](docs/MAPS.md)).
The deck makes no political statement; it follows the supplied data strictly.

## Layout

| Path | Content |
|---|---|
| `data/countries/` | The country database: one YAML file per entry, frozen COTW IDs ([`docs/SCHEMA.md`](docs/SCHEMA.md)) |
| `data/ids.yaml` | The ID ledger |
| `data/wikidata/`, `data/derived/` | Cached Wikidata answers (also the baseline of the weekly change check), Natural Earth land adjacency, flag and maritime-zone manifests (committed, so builds work offline) |
| `data/style/palette.yaml` | Map colors, day and night |
| `media/` | Generated, language-neutral media: `cotw-<id>-flag.svg`, `cotw-<id>-map1-day.svg` / `-night.svg` (orientation), `cotw-<id>-map2-day.svg` / `-night.svg` (capital), the template assets `_cotw-globe.js` and its deferred packets `_cotw-globe-zones.js`, `_cotw-globe-detail.js` (interactive globe) and `ui/` (row icons and help infographics per mode, from `python -m cotw build-ui`) |
| `data/overrides/` | Manual decisions, each with a reason |
| `docs/data-changes.md` | Every deviation from the v3 spreadsheet |
| `tools/cotw/` | Python tooling (`python -m cotw --help`) |
| `tools/globe/` | The globe renderer (plain JS), built into `media/_cotw-globe.js` |
| `tools/cotw/deck/` | The deck build: note types, card templates, CSS, package writer ([`docs/DECK.md`](docs/DECK.md)) |
| `data/deck.yaml` | Deck settings: AnkiWeb links, contact, public repository URL |
| `assets/ui/` | Font (IBM Plex Sans, OFL), Phosphor icons (MIT) and the help infographics the deck ships, with their license files |
| `data/tags.txt` | The UN M49 region hierarchy for the `regions` field |

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,fetch]"
.venv/bin/python -m cotw validate
.venv/bin/python -m pytest
node --test tests/js/*.test.js                 # globe renderer (Node ≥ 20)
```

Media:

```bash
.venv/bin/python -m cotw fetch-flags          # Wikidata P41 → Commons SVG, license check (network)
.venv/bin/python -m cotw fetch-naturalearth   # Natural Earth 10m map units into .cache/ (network)
.venv/bin/python -m cotw fetch-marineregions  # EEZ + 12 nm from the Marine Regions WFS into .cache/ (network, ~170 MB)
.venv/bin/python -m cotw build-maps [ID …]    # render the maps from the cache, write build/preview.html
.venv/bin/python -m cotw build-globe          # split globe assets from the same cache, write build/globe-preview.html
.venv/bin/python -m cotw build-ui [--check]   # media/ui/: icons + infographics per mode (--check: fidelity vs. the v3 PNGs)
```

Change monitoring ([`docs/MONITORING.md`](docs/MONITORING.md)):

```bash
.venv/bin/python -m cotw check-wikidata --dry-run    # caches vs. live Wikidata/Commons (network), writes nothing
.venv/bin/python -m cotw accept-wikidata <fingerprint>   # accept one reported change into the caches
```

The scheduled workflow `.gitea/workflows/wikidata-check.yml` runs the check every Monday and
opens one `wikidata` issue per change.

Map rendering rules (projection, windows, highlight circles, maritime-zone assignment)
are documented in [`docs/MAPS.md`](docs/MAPS.md); the globe and its template contract in
[`docs/GLOBE.md`](docs/GLOBE.md).

## Sources and attribution

[Wikidata](https://www.wikidata.org) (CC0), [Natural Earth](https://www.naturalearthdata.com)
(public domain), icons from [Phosphor Icons](https://phosphoricons.com) (MIT, full notice in
`assets/ui/LICENSE-PhosphorIcons.txt` and in every package), the font IBM
Plex Sans (SIL OFL 1.1), flags from [Wikimedia Commons](https://commons.wikimedia.org) (public
domain / CC0 only, per file in `data/derived/flags.yaml`), and maritime zones from
[Marine Regions](https://www.marineregions.org) by the Flanders Marine Institute (VLIZ),
**CC BY 4.0**:

> Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Maritime Boundaries
> and Exclusive Economic Zones (200NM), version 12, and Territorial Seas (12NM), version 4.
> Available online at https://www.marineregions.org/. https://doi.org/10.14284/632,
> https://doi.org/10.14284/633

Details in [`docs/ATTRIBUTION.md`](docs/ATTRIBUTION.md).

## License

Code, data and deck are dedicated to the public domain under
[CC0 1.0](LICENSE) by Parapoxvirus, except the maritime-zone geometry in the maps and
the globe (Marine Regions, CC BY 4.0, see above), the font (OFL) and the icons (MIT). Knowledge is free.
