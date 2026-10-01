# Attribution

Code, data and deck are dedicated to the public domain under [CC0 1.0](../LICENSE).
The media in `media/` is built from the following sources.

## Maritime zones (maps and globe): Marine Regions, CC BY 4.0

The exclusive economic zone (EEZ) fill and the 12 nm territorial-sea outline on every
map, and the EEZ fill on the globe (`media/_cotw-globe-zones.js`), are derived from the Marine Regions Maritime Boundaries Geodatabase by the Flanders
Marine Institute (VLIZ), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The geometry was projected,
clipped and simplified for the maps. Required citation:

> Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Maritime Boundaries
> and Exclusive Economic Zones (200NM), version 12. Available online at
> https://www.marineregions.org/. https://doi.org/10.14284/632

> Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Territorial Seas
> (12NM), version 4. Available online at https://www.marineregions.org/.
> https://doi.org/10.14284/633

Apart from the font and the icons below, this is the only part of the deck that is not public domain. The
same text is in the deck description of both packages.

## Land (maps and globe): Natural Earth, public domain

Country and territory outlines on the maps and the globe come from
[Natural Earth](https://www.naturalearthdata.com) 10m admin-0 map units, which are in the
public domain. No attribution is required; it is given anyway.

## Flags: Wikimedia Commons

Every flag is the SVG that Wikidata's *flag image* (P41) points to on
[Wikimedia Commons](https://commons.wikimedia.org), unless `data/overrides/flags.yaml`
records a different choice with a reason. The license of every file is read from the
Commons API and recorded in [`data/derived/flags.yaml`](../data/derived/flags.yaml)
(file name, Commons page, license). Only public domain and CC0 files are used. The files
were cleaned (metadata, titles, editor attributes removed, element ids renamed) without
changing the drawing.

## Globe renderer

`media/_cotw-globe.js` is hand-written (`tools/globe/globe.js`, CC0) and vendors no
third-party code: no d3, no topojson-client ([`GLOBE.md`](GLOBE.md) explains why). Its
header repeats the Natural Earth and Marine Regions credits, since the file carries their
geometry.

## Font: IBM Plex Sans, SIL Open Font License 1.1

The cards use IBM Plex Sans (variable font, `assets/ui/_cotw-ui-IBMPlexSans-Variable.ttf`),
Copyright © 2017 IBM Corp. with Reserved Font Name "Plex", licensed under the
[SIL Open Font License 1.1](https://openfontlicense.org). The license text
(`assets/ui/OFL-IBMPlexSans.txt`) ships in every package next to the font
(`_cotw-ui-OFL-IBMPlexSans-<hash>.txt`), and the deck description names it. The font is
bundled unmodified; the OFL allows that, including in a public-domain deck, as long as the
font is not sold on its own.

## UI icons and infographics: Phosphor Icons, MIT

The row icons (`assets/ui/_cotw-ui-*.svg`) are [Phosphor Icons](https://phosphoricons.com)
(regular weight, recolored white), Copyright (c) 2023 Phosphor Icons, licensed under the
[MIT License](https://github.com/phosphor-icons/core/blob/main/LICENSE). The v3 deck did not
record their source; they were identified by their path data. The two help infographics are
drawn from the same icons. MIT requires the copyright and permission notice to travel with
the copies: the full text sits next to the icons (`assets/ui/LICENSE-PhosphorIcons.txt`,
verbatim from phosphor-icons/core) and ships in every package as
`_cotw-ui-LICENSE-PhosphorIcons-<hash>.txt`; the `_` prefix keeps it through Anki's *Check
Media*, like the font license. The deck description credits the icons and names that file.

## Deck build

The packages are written with [genanki](https://github.com/kerrickstaley/genanki) (MIT), a
build-time dependency that is not part of the packages. The import test uses the `anki`
package (AGPL-3.0) as a test tool only ([`DECK.md`](DECK.md)).
