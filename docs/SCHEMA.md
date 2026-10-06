# Country database schema

One YAML file per entry in `data/countries/<id>-<slug>.yaml`, UTF-8, real umlauts and
accents (never transliterated). The schema is enforced by `tools/cotw/schema.py`
(`python -m cotw validate`) and by the tests. Field order in the file is fixed to the
order below.

## Example

```yaml
id: '039'
iso2: CH
iso3: CHE
wikidata: Q39
status: sovereign
name:
  en: Switzerland
  de: Schweiz
formal_name:
  en: Swiss Confederation
  de: Schweizerische Eidgenossenschaft
capitals:
- name:
    en: Bern
    de: Bern
  label:
    en: seat of government
    de: Regierungssitz
  role: seat_of_government
  wikidata: Q70
  lat: 46.94798
  lon: 7.44743
borders:
- '015'
- '079'
regions:
- Europe
- Western Europe
wikipedia:
  en: https://en.wikipedia.org/wiki/Switzerland
  de: https://de.wikipedia.org/wiki/Schweiz
```

## Languages

A *text map* holds one text per language: `{en: …, de: …}`. The languages are the registered
ones, one module each in `tools/cotw/languages/` (today `en`, `de` and `pt`, see
[`DECK.md`](DECK.md#a-new-language)). `python -m cotw validate` requires every registered
language where a map is required (`name`, `capitals[].name`), and rejects keys of languages
that are not registered (in every text map and in `wikipedia`), so a half-added language
fails early. An optional map (`name_label`, `formal_name`, `capitals[].label`) is either absent
or present in every registered language, never in only some of them. Texts use the typographic
apostrophe ’, never a straight `'` (the ʻokina, as in *Nukuʻalofa*, is a letter and allowed).

## Fields

| Field | Type | Rule |
|---|---|---|
| `id` | string `NNN` | **COTW ID**, the stable key. Assigned once in `data/ids.yaml` (alphabetical by EN name, accent-insensitive), then frozen. Never reused. New entries get the next free number. |
| `iso2`, `iso3` | string | ISO 3166-1 alpha-2 / alpha-3. Attributes, not keys: they may change. Unique across entries. |
| `wikidata` | `Q…` | Wikidata item of the entry. Unique. |
| `status` | enum | `sovereign` · `dependency` · `disputed`. Disputed areas follow the de facto situation. |
| `dependency_of` | id | Required for `dependency`, forbidden otherwise. Must point to an existing `sovereign` entry. |
| `name` | text map | Display name, every registered language required (`{en, de}`). Alternatives are separated by ` / ` as in the deck. |
| `name_label` | text map, optional | Free-text note shown next to the name (e.g. *formerly Swaziland*). The parent code of a dependency and the *disputed* marker are **not** stored; they derive from `dependency_of` / `status`. |
| `formal_name` | text map, optional | Formal/long name (was *long form*). Absent or in every registered language; entered even when the official long form equals the short name (*Australia*). |
| `capitals` | list, ≥ 1 | See below. Order as on the card (first = primary). |
| `borders` | list of ids | **Land borders only**, between entities (a dependency is its own entity: France does not border Suriname, French Guiana does). Sorted, unique, symmetric (enforced). Bridges, causeways and maritime boundaries do not count. |
| `regions` | list of names | UN M49 hierarchy path, outermost first, names as in `data/tags.txt` (e.g. `[Africa, Sub-Saharan Africa, Eastern Africa]`). |
| `wikipedia` | map | `{en: <https://en.wikipedia.org/wiki/…>, de: <https://de.wikipedia.org/wiki/…>}`. `en` is required (the database's choice); every other registered language is the item's sitelink to its Wikipedia (`de`: `dewiki`; `python -m cotw fetch-wikipedia`, cached in `data/wikidata/sitelinks.json`) and missing exactly where that Wikipedia has no article; that language's deck then links the English one. `validate` checks both against the cache. Spaces are written as `_`, letters unescaped. |

### Capital

| Field | Type | Rule |
|---|---|---|
| `name` | text map | Every registered language required (`{en, de}`). |
| `label` | text map, optional | Display note as on the card (*seat of government*, *uninhabited*, *Bonaire*, …). |
| `role` | enum | `capital` · `seat_of_government` · `executive` · `legislative` · `judicial` · `de_jure` · `de_facto` · `proclaimed`. Machine-readable role shown in card text; map markers are uniform (DECISIONS.md A4). |
| `wikidata` | `Q…` | Wikidata item of the place. |
| `lat`, `lon` | float | WGS84 decimal degrees, from Wikidata P625, 5 decimals. Given together. Every entry has at least one capital with coordinates unless listed in `data/overrides/exceptions.yaml`. |

## Sources and overrides

| Path | Content |
|---|---|
| `data/ids.yaml` | The frozen ID ledger (`id → slug, iso2, wikidata`). |
| `data/wikidata/*.json` | Cached Wikidata answers (`python -m cotw fetch-wikidata`), committed so the build works offline. |
| `data/derived/ne-borders.yaml` | Land adjacency computed from Natural Earth 10m admin-0 map units (`python -m cotw fetch-naturalearth`). The shapefile itself is downloaded into `.cache/` and not committed. |
| `data/wikidata/sitelinks.json` | Cached Wikipedia article titles per entry item, one per registered language (`python -m cotw fetch-wikipedia`), the source of `wikipedia.<lang>` except `en`. |
| `data/wikidata/flags.json` | Cached Wikidata P41 (flag image) statements (`python -m cotw fetch-flags`). |
| `data/derived/flags.yaml` | Flag manifest: Commons file, license, checksum, selection reason and shared-flag fallback per entry. |
| `data/derived/maritime.yaml` | Marine Regions polygons (EEZ, 12 nm) assigned to each entry, plus every skipped polygon with its reason (`python -m cotw fetch-marineregions`). |
| `data/overrides/*.yaml` | Manual decisions (Wikidata item choice, capital lookup, border corrections, validation exceptions, flag files/licenses, map centers, maritime-zone assignment). Every entry carries a reason. |
| `docs/data-changes.md` | Every deviation from the v3 spreadsheet, generated by `python -m cotw import-v3`; later edits listed by hand under *Changes after the import*. |

## Workflow

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,fetch]"
.venv/bin/python -m cotw validate            # schema + cross-entry rules
.venv/bin/python -m pytest                   # the same plus unit tests
.venv/bin/python -m cotw fetch-wikidata      # refresh the Wikidata cache (network)
.venv/bin/python -m cotw fetch-naturalearth  # refresh the adjacency (network, downloads ~5 MB)
.venv/bin/python -m cotw fetch-wikipedia     # refresh the sitelinks, write wikipedia.de (network; --offline reuses the cache)
.venv/bin/python -m cotw import-v3 <csv>     # regenerate the entries from the v3 spreadsheet export (not in the repository)
```

The YAML files are the database. Edit them directly for content changes and add a row
to *Changes after the import* in `docs/data-changes.md`.
