# Roadmap

Each step is one Gitea issue and one PR. The next step starts after the previous PR is merged.

1. **Country database**: one YAML file per entry with frozen COTW IDs, imported from
   the v3 spreadsheet (not in the repository), checked against Wikidata and Natural Earth, plus validation tests.
2. **Geodata, flags + SVG maps**: flags from Wikimedia Commons via Wikidata P41 with a per-file license check; Natural Earth 10m and Marine Regions (EEZ, 12 nm), with
   Map 1 (region) and Map 2 (capital) per entry, text-free, LAEA centered on the entry.
3. **Globe**: `_cotw-globe.js` with an embedded simplified TopoJSON, canvas rendering,
   night mode, and no tooltip on the front side ([`GLOBE.md`](GLOBE.md)); the note field
   `Globe` becomes `Locator`.
4. **Deck build**: one `.apkg` per locale (en-US, de-CH, pl-PL, pt-BR), 10 card types, the 5 extras in the
   `::Extras` subdeck, shared media, deterministic GUIDs.
5. **Change monitoring** (done): a weekly scheduled Gitea Action compares the data with
   Wikidata and Commons and opens an issue for every deviation ([`MONITORING.md`](MONITORING.md)).
