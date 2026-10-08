# Design decisions

Agreed 2026-09-24. Spelling throughout the project (code, fields, docs, deck texts): **US English**.

## A · Data & identity

1. **Stable key = own COTW ID.** Every entry gets a numeric ID, assigned once in
   alphabetical order (EN name) and then frozen; new entries are appended at the end.
   ISO codes can change and are therefore plain attributes (used to join geo data), never keys.
   Media file names derive from the COTW ID, not from ISO codes.
2. **Scope = every entry with an ISO 3166-1 code**, dependencies included. Dependencies
   get their own field (e.g. *Dependency of*), rendered on the card via an Anki
   conditional (`{{#…}}`). Disputed areas: de facto situation.
3. **Dependencies are separate entities.** Neighbors are computed per entity, so
   France does *not* border Suriname (French Guiana does).
4. **Capitals come from official evidence; Wikidata is a helper**, not the authority.
   Constitutional and legal decisions and the verified current location of state functions
   decide the shared locations, order and roles; corrections to the spreadsheet are allowed.
   Multiple capitals: the role (official capital, seat of government, …) stays in
   the card text (the capital's label); map 2 only shows position and number. Every capital
   gets the same marker: a white circle with an anthracite outline, identical in day and
   night mode. Entries with several capitals get the white digit 1 / 2 / 3 with an outside
   anthracite outline next to each marker, matching the *Capital 1–3* fields (revised
   2026-09-25, issue #12; before: one marker shape per role).
5. **Fields: same content as the existing deck**, but field names get renamed consistently
   (US spelling, fixed typos, one scheme per language note type). No population, area, languages, currency.
   Neighbor list errors in the spreadsheet (B1–B14) are fixed from official data.

Added 2026-10-05, numbered after the last decision so existing references stay valid
(sources and rules per language: [`TRANSLATING.md`](TRANSLATING.md)):

17. **German: Swiss spelling, ss never ß.** The German deck writes `ss`, never `ß`
    ("Weissrussland", "Grossherzogtum Luxemburg"), following the Swiss Federal Chancellery's
    *Schreibweisungen*. Forms taken from German, Austrian or EU sources are written without ß.
    The EDA *Liste der Staatenbezeichnungen* is the primary DE naming source; the lists of the
    Auswärtiges Amt and the StAGN are cross-checks only.
18. **Official changes are applied as soon as possible.** The primary source of a language
    decides only where official sources disagree; it is not a reason to wait. If it has not
    caught up with a change yet, COTW follows the current official publications (other
    national name lists, UN/UNTERM, government decrees). The language's spelling rules still
    apply.

Added 2026-10-07 (approved naming and factual-content policy):

19. **Names are local; facts are shared.** Each locale's official naming authorities decide
    country and city short names, formal names and spelling. Status, represented entities,
    locations, roles, order and granularity are shared facts based on relevant constitutional,
    legal and verified de facto evidence; a translating country's recognition policy does not
    override them. Labels translate the same shared role. Source roles and the fallback order
    are recorded in [`TRANSLATING.md`](TRANSLATING.md); Wikipedia and Wikidata are helpers,
    never naming authorities. A sourced `formal_name` is optional per locale: an omitted locale
    renders no formal-name row and never falls back to another language. Required names and
    shared labels remain complete. Deck and subdeck names, including *Extras*, are translated
    naturally. Official alternatives that do not reveal a capital are preferred consistently
    where available; none are invented. The deliberate Islamic Emirate, Majuro, Funafuti and
    Saipan choices remain explicit exceptions rather than consequences uniquely selected by
    this general rule.

## B · Globe in Anki

6. One shared renderer `_cotw-globe.js` with an embedded world map at L2, the coarsest level
   (issue #31; before, a coarser L1 plus an `overview` packet with L2); deferred packets supply
   EEZ and fine land data (rc3, issue #14): `_cotw-globe-zones.js` (EEZs),
   `_cotw-globe-detail.js` (fine land; issue #17)
   (TopoJSON, ~1–2 MB); the note field **`Locator`** (v3: `Globe`, renamed 2026-09-25) only
   carries the entry's COTW ID, not an `<img>`. The script keeps its name because it is the
   widget; the field says what it does. Template contract: [`GLOBE.md`](GLOBE.md).
   The exported maps use Natural Earth 10m at full resolution; the globe uses the same 10m
   units, heavily simplified (one topology-preserving pass), so both share one entry join.
7. Natural Earth is converted by the pipeline (no hand-made SVG input).
8. The globe (rendered from the `Locator` field) appears on the **back** of every card
   type. Exception: *Map → Country*, where maps and globe are the prompt on the front.
   There the globe shows no tooltip or
   other text, so it gives nothing away.
9. Flat fills only (country, neighbors, rest, sea), no textures, night mode supported.
   Night mode follows Anki's night mode only (`.nightMode` / `.night_mode`), never the system
   color scheme (2026-09-25, issue #12).

## C · Exported maps (SVG)

10. Projection centered on each country. Plan: Lambert azimuthal equal-area instead of
    Robinson (less distortion around the center, equal-area).
11. **No text at all.** Countries and capitals are marked by color/icon only, so maps
    stay language-neutral and give nothing away.
12. **Map 1** = orientation (“this is Europe / the Middle East”), region-scale window
    around the country. **Map 2** = where the capital lies within the country:
    country outline plus margin, micro-states get a highlight circle.
13. **Maritime zones** from Marine Regions (VLIZ, CC BY 4.0, attribution in the deck
    description and README): exclusive economic zone (EEZ) as a light-blue fill,
    territorial sea (12 nm) as an even lighter outline. The globe shows only the EEZ,
    since 12 nm is invisible at that scale. Only land borders count as neighbors.

## D · Card types

Every note has 10 card types, in two directions (*X → Country* and *Country → X*) over
five attributes: capital, flag, map, ISO code, bordering countries.

| Attribute | X → Country | Country → X |
|---|---|---|
| Capital | recommended | recommended |
| Flag | recommended | recommended |
| Map | recommended | extra |
| ISO code | extra | extra |
| Bordering countries | extra | extra |

Every package ships all 10 types: the 5 recommended ones in the main deck and the 5
extras in a subdeck `…::Extras`. That way a single package serves everyone. Users
switch the extras on or off by suspending or unsuspending the subdeck, which can be
undone later. Deleting card types instead would force a full sync and can't be undone.

## E · Deck build

- Help and deck descriptions use the public repository for information and contact, and its
  issue tracker for error reports. Both links come from `data/deck.yaml.repository`.
- **Distribution (2026-10-07):** AnkiWeb has one English listing. Every locale ships as an
  `.apkg` release asset; no additional locale-specific listings are created.
- **Flags come straight from Wikimedia Commons**: Wikidata `P41` (flag image) → Commons SVG.
  The license is read per file from the Commons API. Public domain / CC0 passes, anything
  else fails the build and needs a manual decision. The v3 flags (hampusborgos/country-flags,
  unmaintained, no license file) are not used and not in the repository.
  The weekly Wikidata check (step 5) also covers flag changes.
- **Media file names** use the COTW ID: `cotw-<id>-flag.svg`, `cotw-<id>-map1-day.svg` /
  `-night.svg`, `cotw-<id>-map2-day.svg` / `-night.svg` (one file per Anki mode since rc2),
  without a leading underscore. Field-referenced media is tracked by
  Anki's *Check Media*; the `_` prefix stays reserved for template assets (globe script,
  font, UI icons). Map rendering rules: [`MAPS.md`](MAPS.md).

14. One database (one file per entry), the build emits one `.apkg` per language.
    **There is no combined EN+DE package** (agreed 2026-09-25). Instead the EN and DE packages
    install side by side in the same collection without any conflict, in any order, and each
    can be updated on its own later: separate deck IDs and names, note type IDs and names,
    card-template names, note GUIDs, tag roots (`COTW-EN-US::` / `COTW-DE-CH::`) and `cotw-`-scoped
    CSS, all fixed constants or derivations. Media is shared (identical file names and bytes)
    and therefore stored only once; template assets carry a content hash in their name so an
    update of one package can never overwrite a file the other package's templates still use.
    Proven by an import test with the `anki` package. Details: [`DECK.md`](DECK.md).
    **No backward compatibility** with the old deck (clean break). Note GUIDs are derived
    deterministically from COTW ID + the language's frozen identity, so they stay stable across
    all future builds (decision 17).
15. **Change monitoring:** a weekly scheduled Gitea Actions job
    (`.gitea/workflows/wikidata-check.yml`) compares the database with Wikidata and opens an
    issue for each deviation. Nothing is applied without approval.
16. **Publishing:** development on Gitea for now, GitHub later. Deck, data and code: public domain (CC0),
    except the Marine Regions geometry (CC BY 4.0, attribution required).
17. **A language is a full BCP 47 locale** (`en-US`, `de-CH`, `pt-BR`): the language and the
    region whose spelling and official names it follows, so regional variants (`de-CH` next to
    a future `de-DE`, `pt-BR` next to `pt-PT`) can coexist. The locale code is the key of the
    names in the data, the package file (`COTW-DE-CH.apkg`), the tag root (`COTW-DE-CH::`) and
    the note type name (`COTW (DE-CH)`); deck names stay as they are. Its sources (Wikipedia,
    Wikidata label languages in fallback order) come from the curated list
    `data/locales.yaml`, which also bounds the possible locales. The GUIDs and IDs hang on a
    separate, frozen **identity**: the code for every new locale, `en` and `de` for the two
    locales published before (v1.0.x), so updating keeps every note and its review history.
    No two locales share an identity.

## Open
