# Deck build

`python -m cotw build-deck` builds one Anki package per language from the database:

```bash
.venv/bin/python -m cotw build-deck            # build/COTW-EN.apkg + build/COTW-DE.apkg + build/deck-preview.html
.venv/bin/python -m cotw build-deck --lang de  # one language only
.venv/bin/python -m cotw build-deck --only RU,KR,ZA,CW,CH,VA,SJ,KI,BO,ID --out build/rc2   # test package
```

Both packages are designed to be installed **side by side in the same collection**, in any
order, and each can be updated on its own later (DECISIONS 14). There is no combined EN+DE
package any more. Code: `tools/cotw/deck/` (`lang.py` identities and texts, `templates.py`
card templates, `style.css`, `build.py` package writer and preview). Settings that change
without a code change (AnkiWeb links, contact, public repository URL): `data/deck.yaml`.

## What is in a package

| | EN | DE |
|---|---|---|
| File | `COTW-EN.apkg` | `COTW-DE.apkg` |
| Main deck | `Countries of the World` | `Länder der Welt` |
| Subdeck | `Countries of the World::Extras` | `Länder der Welt::Extras` |
| Note type | `COTW (EN)` | `COTW (DE)` |
| Notes / cards | 248 / 2318 | 248 / 2318 |
| Media | 1240 field media (flag + 2 maps × day/night per entry) + 27 template assets | the same files, byte-identical |
| Size | ≈ 8.5 MB (rc1: 5.6 MB; the night maps add ~2.9 MB) | ≈ 8.5 MB |

2318 cards = 248 × 10 minus the two border card types of the 81 entries without land borders
(their front renders empty, so Anki creates no card).

## Identities

Every identity is a fixed constant or a pure derivation, never random, and differs per
language, so nothing the EN package installs can collide with the DE package.

| What | EN | DE | Rule |
|---|---|---|---|
| Note type ID | `1829704095` | `1123558981` | frozen constants in `lang.py` |
| Main deck ID | `1866953617` | `2041372721` | 〃 |
| Extras deck ID | `1918702087` | `1539901401` | 〃 |
| Note GUID | `guid_for("cotw", "en", id)` | `guid_for("cotw", "de", id)` | genanki's `guid_for` (SHA-256, base91) of COTW ID + language (DECISIONS 14); Switzerland: `C,F0URhk8F` / `B+v1yB?A&S` (pinned in a test) |
| Card template names | `01 Country → Capital` … | `01 Land → Hauptstadt` … | see below |
| Tags | `COTW-EN::…` | `COTW-DE::…` | one root per language |
| CSS | one stylesheet per note type | the same stylesheet | Anki applies CSS per note type; every class carries the `cotw-` prefix, the root also `cotw-en` / `cotw-de` |
| Note / card row IDs | build time × 1000 + 0 … | build time × 1000 + 50 000 … | Anki re-keys colliding row IDs anyway; matching uses the GUID |

The constants were derived once as
`(int.from_bytes(sha256(f"cotw:{lang}:{kind}").digest()[:4], "big") >> 1) | 1 << 30` for
`kind` = `notetype`, `deck`, `deck-extras`; a test recomputes them. **Never change them**:
Anki matches note types by ID and notes by GUID, so a new value would install a second note
type or a second copy of every note in every user's collection.

### Tags

`<root>::<M49 region path>` plus `<root>::Status::<status>`, spaces as `-`:

| EN | DE |
|---|---|
| `COTW-EN::Europe::Western-Europe` | `COTW-DE::Europa::Westeuropa` |
| `COTW-EN::Africa::Sub-Saharan-Africa::Southern-Africa` | `COTW-DE::Afrika::Subsahara-Afrika::Südliches-Afrika` |
| `COTW-EN::Status::Sovereign` / `Dependency` / `Disputed` | `COTW-DE::Status::Souverän` / `Abhängiges-Gebiet` / `Umstritten` |

A search for `tag:COTW-EN::Europe` or a filtered deck on it never pulls DE cards. German
region names live in `lang.REGIONS_DE`; a test checks that every region of the taxonomy has one.

## Fields

Same content as v3 (DECISIONS A5), renamed consistently; the DE note type uses German field
names, since German users see them in the browser and the editor. `Locator` keeps its name in
both: it is the globe's template contract ([`GLOBE.md`](GLOBE.md)). The first field is the
sort field.

| # | EN | DE | v3 (EN / DE) | Content |
|---|---|---|---|---|
| 1 | Country | Land | EN Country / DE Land | `name` |
| 2 | Country Label | Land Zusatz | EN Country Label / DE Land Label | `name_label` (e.g. *formerly Swaziland*). v3 put the parent's ISO code here; that is now field 18. |
| 3 | Formal Name | Amtlicher Name | EN Long Form / DE Langform | `formal_name` |
| 4–9 | Capital 1–3, Capital 1–3 Label | Hauptstadt 1–3, Hauptstadt 1–3 Zusatz | EN Capital n (Label) / DE Hauptstadt n (Label) | `capitals` in database order, with their text label |
| 10, 11 | ISO-2, ISO-3 | ISO-2, ISO-3 | ISO-2 Code, ISO-3 Code | |
| 12 | Flag | Flagge | Flag | `<img src="cotw-<id>-flag.svg">` |
| 13, 14 | Map 1, Map 2 | Karte 1, Karte 2 | Map 1, Map 2 | both files of the map: `<img class="cotw-day" src="cotw-<id>-map1-day.svg"><img class="cotw-night" src="cotw-<id>-map1-night.svg">`, the same for map 2 (see *Night mode*) |
| 15 | Locator | Locator | Globe | the COTW ID ([`GLOBE.md`](GLOBE.md)) |
| 16 | Borders | Nachbarländer | Borders | neighbors in that language, sorted by name, each with its flag (v3: flag + ISO code) |
| 17 | Wikipedia | Wikipedia | EN Wiki URL | `wikipedia.<lang>`; DE falls back to EN where no German article exists (only Svalbard and Jan Mayen) |
| 18 | Dependency Of | Abhängig von | (EN/DE Country Label) | the sovereign as it reads in *dependency of …* / *abhängiges Gebiet von …*: `the United Kingdom`, `dem Vereinigten Königreich` (`lang.DATIVE_DE`); empty unless `status: dependency` |
| 19 | Status | Status | (tag only) | `status disputed` / `Status umstritten` for disputed entries, else empty |

Fields 18 and 19 are rendered under the name via conditionals (DECISIONS A2), e.g.
*Greenland · dependency of Denmark*, *Kosovo · status disputed*. Text is HTML-escaped; the
image fields hold plain `<img>` tags so Anki's *Check Media* tracks them.

## Card types and decks

| # | Card type | Deck | |
|---|---|---|---|
| 01 | Country → Capital | main | recommended |
| 02 | Country → Flag | main | recommended |
| 03 | Capital → Country | main | recommended |
| 04 | Flag → Country | main | recommended |
| 05 | Map → Country | main | recommended |
| 06 | ISO Code → Country | `::Extras` | extra |
| 07 | Country → ISO Code | `::Extras` | extra |
| 08 | Country → Bordering Countries | `::Extras` | extra, only with land borders |
| 09 | Bordering Countries → Country | `::Extras` | extra, only with land borders |
| 10 | Country → Map | `::Extras` | extra |

This is the DECISIONS D split; the build places every card in its deck. **Switching the
extras off:** Browse → click the `…::Extras` deck in the sidebar → select all → *Suspend*
(Ctrl+J). The same again switches them back on. Deleting card types instead would force a
full sync and can't be undone. The same instructions are in the deck description and the
help section.

### Templates

- **Front:** the asked attribute as `?`, then the prompt, a *Help* button. The front of
  *Map → Country* shows the two maps and the globe and no text at all: no name, code or label,
  no Wikipedia link, and the globe without `data-tooltip` (DECISIONS B8; tested).
- **Back:** the answer (highlighted) and the prompt, then the globe with tooltip on every
  back (DECISIONS B8; *Map → Country* and *Country → Map* show it in the maps row), a
  *Show full info* button revealing everything else, *Wikipedia* and *Help*.
- **Buttons** are inline `onclick` handlers that toggle a class on the card's root element:
  no element ids, no `setTimeout`, nothing to re-initialize when Anki desktop reuses the
  webview. They are `<span role="button">`, not `<button>`, so a focused button never
  swallows the space bar that shows the answer.
- **Help** per language (EN adapted from v3, DE written in German; it also explains the
  light-blue economic zone and the 12 nm line on the maps), with the AnkiWeb page from
  `data/deck.yaml` (default: the v3 pages; update after the upload and rebuild) and the
  contact `info@feldbuch.com`.
- **Night mode follows Anki only:** its `.nightMode` class (desktop, AnkiMobile) or
  `.night_mode` (AnkiDroid, older clients) on the card, body or html. The system color scheme
  is ignored: with Anki set to light and the OS dark, the cards stayed dark in rc1. No
  `prefers-color-scheme` anywhere in the card CSS, the globe or the maps (tested).
  - An SVG inside `<img>` cannot see Anki's class, so everything that differs per mode
    exists twice: the maps (`…-day.svg` / `…-night.svg`, both in the field, because
    field-referenced media is what *Check Media* keeps), the row icons and the infographics
    (template assets). Each `<img>` carries `cotw-day` or `cotw-night`; the last rules of the
    CSS show the one that matches (`.cotw img.cotw-night` hidden by default,
    `.nightMode .cotw img.cotw-day` hidden in night mode). Flags stay one file.
  - Colors: light mode text `#1F2328`, secondary text (labels such as *Regierungssitz*)
    `#59636E`, page `#FFFFFF`; dark mode text `#E6EDF3`, page `#2C2C2C` as in v3. Row icons
    have the text color of their mode (`media/ui/`, generated from the white Phosphor
    originals). The *Wikipedia* / *Help* buttons follow the mode as well.
  - The answer row (the highlighted attribute on the back): light mode `#375A7F`, the blue
    of the *Show full info* button, with a darker line `#2A4663`, white text, near-white
    labels (`rgba(255,255,255,.8)`) and white links; dark mode `#2E4A5F` with the normal
    dark-mode text. The row's icon column keeps its mode's colors.
- **Help section infographics:** SVG rebuilds of the two v3 PNGs, transparent, in four
  variants (normal / filtered × day / night), see *Infographics* below.

## Media

| Kind | Name | Referenced from |
|---|---|---|
| Field media | `cotw-<id>-flag.svg`, `cotw-<id>-map1-day.svg`, `…-map1-night.svg`, `…-map2-day.svg`, `…-map2-night.svg` | note fields |
| Template assets | `_cotw-<stem>-<hash8>.<ext>`: `_cotw-globe-…js`, `_cotw-globe-zones-…js`, `_cotw-globe-detail-…js`, `_cotw-ui-IBMPlexSans-Variable-…ttf`, `_cotw-ui-<icon>-day-…svg` / `-night-…svg` (9 icons), `_cotw-ui-infographic(-filtered)-day-…svg` / `-night-…svg`, `_cotw-ui-OFL-IBMPlexSans-…txt` (the font license, shipped with the font), `_cotw-ui-LICENSE-PhosphorIcons-…txt` (the full MIT notice of the icons) | templates and CSS |

The mode-specific icons and the infographics are generated, never edited by hand:
`python -m cotw build-ui` writes `media/ui/` (committed) from the Phosphor originals in
`assets/ui/`; `tests/test_ui.py` fails when the committed files are stale.

### Infographics

The v3 infographics (`assets/ui/_cotw-ui-infographic.png`, `…-filtered.png`, 1848 × 1713)
had an opaque beige background and black lines that vanished in night mode, and their design
file no longer exists. They are rebuilt as SVG (`tools/cotw/ui.py`), *generated*, from:

- the five Phosphor icons we ship (`assets/ui/`: bank = capital, flag, map, hash = ISO,
  squares-four = borders) and the center square (Phosphor's square = our country icon), their
  path data verbatim, all at one scale (1.285) on the PNG's 330 px row grid;
- two curly braces as stroked cubic Béziers (20 px, round caps).

Scale, offsets and the braces' control points were fitted to the PNGs by maximizing the
line-mask IoU. `python -m cotw build-ui --check` rasterizes the SVG at 1848 × 1713 and
compares it with the PNG, and writes an overlay (PNG lines magenta, SVG lines green, both
black) to `build/`. Current result: **IoU 0.972** (normal) / **0.977** (filtered; grayed
lines alone 0.972), **max deviation 6 px** (of 1848). `tests/test_ui.py` holds it to
**IoU ≥ 0.96, max ≤ 8 px** (Pillow reads the PNG, shapely + Pillow rasterize the SVG).

Four variants with a transparent background: normal / filtered × day / night. Day lines
`#1F2328`, grayed `#C9CDD1`; night lines `#E6EDF3`, grayed `#5A5F66`. The filtered variant
grays the extras exactly as the PNG does: ISO code and bordering countries in both columns
and the map in the right column (*Country → Map*); the left map (*Map → Country*) is a
recommended card type and stays dark. The PNGs are no longer shipped.

`<hash8>` is the first 8 hex digits of the file's SHA-256. Both packages of one build carry the
same files under the same names, so Anki stores them once (tested).

### Version skew: updating one package only

The dangerous case is a user who updates EN a year later but keeps the old DE. On import,
Anki compares every incoming file with the file of the same name in the collection:

- **Same name, same content:** nothing happens.
- **Same name, different content:** Anki stores the incoming file under a new name
  (`name-<sha1>.ext`) and rewrites the references **in the incoming note fields**, but not in
  templates or CSS.

So:

- **Template assets** can never hit the second case: a changed file has a new hash and thus a
  new name. The updated EN note type points at the new files, the old DE note type keeps
  pointing at the old ones, and both sets stay in the media folder. Files starting with `_` are
  never reported as unused by *Check Media*, so the old set is not deleted while DE uses it.
- **Field media** keep their stable names. A changed map arrives under Anki's renamed name and
  only the EN notes point at it; the DE notes keep the old file. When DE is updated too, its
  incoming map has the same content as the renamed file and is stored under the same name, so
  both decks share it again; the original file is then unused and *Check Media* offers to
  delete it. Nothing breaks at any step.

`tests/test_deck_import.py` proves all of this with the real `anki` package: both import
orders, a repeated import, and a simulated later EN release (changed map, changed globe,
changed capital) imported next to the old DE package and then followed by the DE update.

Two rules follow for later releases:

1. **Keep the note types' fields and card templates stable** (names, count, order). Anki
   updates templates and CSS of an installed note type in place, but a changed field or
   template list is a schema change: users then need *Merge note types* in the import dialog.
2. **The globe's `VERSION`** ([`GLOBE.md`](GLOBE.md)) still decides which globe script owns
   the webview when an old and a new deck are studied in one session; bump it on any change of
   the template contract. Data-only changes are harmless either way.

## Test packages (`--only`)

`--only` takes COTW IDs or ISO-2 codes (any case, comma- or space-separated) and builds the
packages with just those notes. Everything else is the full build's: note type, deck and
note IDs, GUIDs, templates, CSS, field content. The borders field still names and flags
neighbors outside the subset (their flags ship with it), and the globe is the whole world.
Installing a test package and later the full package updates the same notes. The deck
description counts only the notes in the package.

## Updates and timestamps

Every note, card and note type carries one build timestamp: `SOURCE_DATE_EPOCH` if set,
otherwise the time of the current git commit. Anki only replaces installed notes and note
types with *newer* ones, so a build from a later commit updates a collection, while the same
commit always produces the same package: zip entries have fixed dates and a fixed order, the
collection is written in a fixed order, and the IDs derive from the timestamp. Building twice
gives a byte-identical `.apkg` (tested); across machines a different zlib or SQLite version
(the SQLite file header records it) can change the bytes, never the content.

## Why genanki

[genanki](https://github.com/kerrickstaley/genanki) (MIT) writes the package without an Anki
installation and lets us set every ID, GUID and timestamp. The `anki` package (AGPL-3.0) is
the reference implementation but creates IDs and timestamps from the clock and brings a
large binary; it is used only as a test dependency to prove the import (`dev` extra), never
shipped and never imported by the build. genanki lacks three things the build adds:
per-card-type deck placement (a SQL update after writing), pinned collection timestamps and a
deterministic zip.

## Preview

`build/deck-preview.html` renders every card type, front and back, day and night, for
Switzerland, Greenland (dependency), South Africa and Bolivia (several capitals) and Vatican
City, in both languages, with the real CSS, media and globe. It uses the same template
renderer as the tests. Query parameters narrow it down:
`?lang=de&ids=217&side=back&mode=night&types=01,05&open=info,help&w=380`. Serve the `build/`
directory over HTTP (`python3 -m http.server -d build`) so the globe script loads.
