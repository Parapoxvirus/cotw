# Translating COTW

How a new deck language is added, which sources decide the names in each language, and the
rules every language follows. The technical side of a language (module, IDs, build) is in
[`DECK.md`](DECK.md#a-new-language), the data format in [`SCHEMA.md`](SCHEMA.md). How
contributions reach the published repository: [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Adding a language: checklist

1. **Module:** `tools/cotw/languages/<code>.py` (ISO 639-1 code), copied from `en.py` and
   translated ([`DECK.md`](DECK.md#a-new-language)):
   - texts: note type, deck and subdeck names, `fields`, `templates`, `comments`, `ui`,
     `help`, `description`, `extras_description`, `status_tags`, `status_disputed`;
   - `regions`: every M49 region of `data/tags.txt`;
   - `dependency_of` and `object_form`: the sovereign's form after *dependency of …* (article,
     case; a test pins it for every parent);
   - `tag_root`: `COTW-<CODE>`;
   - `notetype_id`, `deck_id`, `extras_deck_id`: computed once with
     `derive_id(code, "notetype" | "deck" | "deck-extras")` and written in as constants, frozen
     from the first release on;
   - `id_offset`: the next free multiple of 50 000 (EN 0, DE 50 000, the next language 100 000);
   - `wiki`: the Wikidata site ID of the language's Wikipedia (`plwiki`);
   - `ankiweb`: optional, `None` until the listing exists (the help then links the EN listing).
2. **Data:** in every `data/countries/*.yaml`, `name.<code>` and `name.<code>` of every capital
   (both required); `name_label`, `formal_name` and `capitals[].label` wherever EN or DE have
   them (`validate` rejects an optional map that lacks a registered language); `wikipedia.<code>`
   with `python -m cotw fetch-wikipedia` (from the Wikidata sitelinks, never typed by hand).
3. **Build and check:** `python -m cotw validate`, `python -m pytest`, `python -m cotw build-deck`.
   Show that the existing packages are unchanged: build before and after with the same
   `SOURCE_DATE_EPOCH` and run `python tools/compare_packages.py build/before build/after`.
4. **Names, complete check:** every entry, every capital, every label and long form is checked
   against the language's sources below, in their priority order. The check is complete,
   never sampled; a deviation from the primary source gets a row with its reason in
   [`data-changes.md`](data-changes.md).
5. **AnkiWeb:** once the listing exists, set `ankiweb` in the module and add the link to the
   README's install section.

## Naming sources

Sources per language, in priority order. Edition and date as found when the links were checked
on 2026-10-06; lists that are regenerated on demand are marked *online*.

### English (EN)

1. **[UNTERM](https://unterm.un.org/)** (United Nations Terminology Database, *online*): short
   and formal names of the UN member states and observer states. Primary; it decides where the
   official sources disagree.
2. **Territories**, which UNTERM largely lacks:
   - UK: [Geographical names index](https://www.gov.uk/government/publications/geographical-names-and-information)
     (FCDO with PCGN, updated 15 September 2026: states, Crown Dependencies, UK Overseas
     Territories) and [Country names](https://www.gov.uk/government/publications/country-names)
     (PCGN, updated 20 July 2026, states only);
   - US: [Independent States in the World](https://www.state.gov/independent-states-in-the-world/)
     (11 August 2026) and
     [Dependencies and Areas of Special Sovereignty](https://www.state.gov/dependencies-and-areas-of-special-sovereignty/)
     (31 March 2026), both by the Office of the Geographer, US Department of State.
3. **[ISO 3166-1](https://www.iso.org/iso-3166-country-codes.html)** English short names
   (ISO 3166-1:2020, maintained online): cross-check, and the source of the codes.

### German (DE)

1. **[Liste der Staatenbezeichnungen](https://www.eda.admin.ch/dam/de/sd-web/viWGvPDY5NYo/liste-etats_DE.pdf)**
   (EDA, Swiss Federal Department of Foreign Affairs, dated 21 August 2026). Primary; it decides
   where the official sources disagree. Sovereign states only (including Kosovo, Taiwan and the
   Holy See), in Swiss spelling like the deck.
2. Cross-checks only:
   - [Verzeichnis der Staatennamen für den amtlichen Gebrauch in der Bundesrepublik Deutschland](https://www.auswaertiges-amt.de/de/service/terminologie/215252-215252)
     (Auswärtiges Amt, Stand 28 July 2026);
   - [Liste der Staatennamen und ihrer Ableitungen im Deutschen](https://stagn.bkg.bund.de/was-wir-veroeffentlichen/uebersichten-listen-und-datenbanken/synoptische-staatennamenliste)
     (StAGN, 15th edition, October 2023), with an annex of selected dependent territories.

   For territories, which the EDA list does not cover, these and the EU list below are the
   official sources.
3. **Spelling:** the Swiss Federal Chancellery's
   [Schreibweisungen](https://www.bk.admin.ch/de/schreibweisungen) (2nd, updated edition 2013,
   corrected 2015), which make its
   [Rechtschreibleitfaden](https://www.bk.admin.ch/de/rechtschreibleitfaden) (4th, updated
   edition 2017) binding; the guide states that Swiss German does not write ß. COTW writes
   **ss, never ß**, also for forms taken from the German, Austrian or EU lists.

If the EDA list has not caught up with an official change yet, the change is applied from the
other official publications (see the source rule below) and written in Swiss spelling.

### Polish (PL)

1. **[Urzędowy wykaz nazw państw i terytoriów niesamodzielnych](https://www.gov.pl/web/ksng/Urzedowy-wykaz-nazw-panstw-i-terytoriow-niesamodzielnych)**
   (KSNG, 8th edition 2025, with update 1, the new capital of Equatorial Guinea of January 2026,
   and update 2, the renaming to Naoero of 12 May 2026). Primary; it decides where the official sources disagree.
   States and dependent territories with their capitals.
2. **[Urzędowy wykaz polskich nazw geograficznych świata](https://www.gov.pl/web/ksng/urzedowy-wykaz-polskich-nazw-geograficznych-swiata2)**
   (KSNG, 2nd edition 2019, list of changes as of 23 September 2026): other place names, for
   example capitals missing from the list above.

### Every EU language

**[Interinstitutional Style Guide, Annex A5](https://style-guide.europa.eu/en/content/-/isg/topic?identifier=annex-a5-list-countries-territories-currencies)**
(Publications Office of the European Union, *online*; German PDF built 2 October 2026, still
listing Nauru): short form, long form, capital and codes in all 24 EU languages. The common
cross-check for DE, PL and EN, and the starting point for future EU languages. Its German
version writes ß.

### Helpers, not naming sources

- **Wikidata:** the weekly change monitor, capitals as facts, coordinates, the flag link (P41).
  A Wikidata label is never the source of a name.
- **Wikipedia:** article links only. The editions follow different naming rules:
  de.wikipedia's [naming convention](https://de.wikipedia.org/wiki/Wikipedia:Namenskonventionen/Staaten)
  follows the AA, BMEIA and EDA lists, pl.wikipedia's
  [naming convention](https://pl.wikipedia.org/wiki/Wikipedia:Nazewnictwo_geograficzne) follows
  KSNG, en.wikipedia uses the [common name](https://en.wikipedia.org/wiki/Wikipedia:Article_titles#Common_names).

### Source rule: official changes are applied as soon as possible

The primary source of a language decides only where official sources **disagree**; it is not a
reason to wait. When a state changes its name or capital and the primary source has not been
updated yet (the EDA list can lag), COTW follows the current official publications instead:
other national name lists (for example AA, StAGN or a KSNG update), UN/UNTERM, government
decrees. The language's spelling rules still apply (DE: Swiss spelling, ss, no ß).

Example: Nauru's renaming to Naoero (UN notification of 26 June 2026) is an official change and
is applied as such: Naoero / Republik Naoero, from UNTERM and the Auswärtiges Amt list of
28 July 2026. The EDA list of 21 August 2026 lists Naoero as well. If it had still shown Nauru,
the change would not have waited for it, because the primary source only decides where official
sources disagree.

### All sources

Every source considered for COTW, used or not.

| Source | Publisher | Languages | Edition / date (checked 2026-10-06) | Role in COTW | Note |
|---|---|---|---|---|---|
| [Liste der Staatenbezeichnungen](https://www.eda.admin.ch/dam/de/sd-web/viWGvPDY5NYo/liste-etats_DE.pdf) | EDA (Swiss FDFA) | DE (also FR, IT) | 21 August 2026 | **DE primary** (decides on disagreement, not a reason to wait) | Swiss spelling, matches the deck; can lag, so newer official changes are applied without waiting for it |
| [Verzeichnis der Staatennamen für den amtlichen Gebrauch](https://www.auswaertiges-amt.de/de/service/terminologie/215252-215252) | Auswärtiges Amt (DE) | DE | Stand 28 July 2026 | DE cross-check | Uses ß; COTW writes ss |
| [Liste der Staatennamen und ihrer Ableitungen](https://stagn.bkg.bund.de/was-wir-veroeffentlichen/uebersichten-listen-und-datenbanken/synoptische-staatennamenliste) | StAGN | DE | 15th edition, October 2023 | DE cross-check | Uses ß; editions not always current |
| [Liste der Staatennamen](https://www.bmeia.gv.at/reports/staatennamen/) | BMEIA (AT) | DE (also EN, FR) | *online*, regenerated daily | not used | Austrian variants; one of de.wikipedia's bases |
| [Schreibweisungen](https://www.bk.admin.ch/de/schreibweisungen) | Swiss Federal Chancellery | DE | 2nd edition 2013, corrected 2015 | **DE spelling rule** | ss instead of ß (stated in its [Rechtschreibleitfaden](https://www.bk.admin.ch/de/rechtschreibleitfaden), 4th edition 2017) |
| [Urzędowy wykaz nazw państw i terytoriów niesamodzielnych](https://www.gov.pl/web/ksng/Urzedowy-wykaz-nazw-panstw-i-terytoriow-niesamodzielnych) | KSNG (PL) | PL | 8th edition 2025, updates 1 and 2 (2026) | **PL primary** (decides on disagreement, not a reason to wait) | Includes territories and capitals |
| [Urzędowy wykaz polskich nazw geograficznych świata](https://www.gov.pl/web/ksng/urzedowy-wykaz-polskich-nazw-geograficznych-swiata2) | KSNG (PL) | PL | 2nd edition 2019, changes as of 23 September 2026 | PL supplement | Other place names, e.g. capitals missing from the list above |
| [UNTERM](https://unterm.un.org/) | United Nations | AR, ZH, EN, FR, RU, ES | *online* | **EN primary** (UN member states; decides on disagreement, not a reason to wait) | Dependent territories largely missing |
| [Country names](https://www.gov.uk/government/publications/country-names), [Geographical names index](https://www.gov.uk/government/publications/geographical-names-and-information) | PCGN / FCDO (UK) | EN | 20 July 2026; 15 September 2026 | EN cross-check, territories | British usage; the index covers UK territories only |
| [Independent States in the World](https://www.state.gov/independent-states-in-the-world/); [Dependencies and Areas of Special Sovereignty](https://www.state.gov/dependencies-and-areas-of-special-sovereignty/) | US Department of State (Office of the Geographer) / BGN | EN | 11 August 2026; 31 March 2026 | EN cross-check, territories | US usage |
| [ISO 3166-1](https://www.iso.org/iso-3166-country-codes.html) | ISO | EN, FR | ISO 3166-1:2020, maintained online | Codes (`iso2`, `iso3`) | Short names follow UNTERM |
| [Interinstitutional Style Guide, Annex A5](https://style-guide.europa.eu/en/content/-/isg/topic?identifier=annex-a5-list-countries-territories-currencies) | European Union | all 24 EU languages | *online*; German PDF built 2 October 2026 | Cross-check DE/PL/EN; base for future EU languages | Short/long form, capital, codes; DE with ß |
| [List of Country Names](https://unstats.un.org/unsd/ungegn/sessions/2nd_session_2021/documents/GEGN.2_2021_CRP130_4c_WG_Country_Names_rev2.pdf) | UNGEGN | endonyms + UN languages | GEGN.2/2021/CRP.130/Rev.1, 25 April 2021 (current as of March 2019) | not used, reference | Endonyms and the six UN languages only; exonyms are left to the national names authorities (KSNG, StAGN, EDA) |
| [CLDR](https://cldr.unicode.org/) | Unicode Consortium | almost all | 48.2, 17 March 2026 | not used | Software localization, not official; last resort for languages without an official list |
| [Wikidata](https://www.wikidata.org/) | Wikimedia | all | *online*; cached in `data/wikidata/` | Change monitor; capitals, coordinates, flag link (P41) | **Not a naming source** |
| Wikipedia ([en](https://en.wikipedia.org/), [de](https://de.wikipedia.org/), [pl](https://pl.wikipedia.org/)) | Wikimedia | per edition | *online*; sitelinks cached in `data/wikidata/sitelinks.json` | Article links only | Naming rules differ: de → AA/BMEIA/EDA, pl → KSNG, en → "common name" |
| [Wikimedia Commons](https://commons.wikimedia.org/) | Wikimedia | – | per file, `data/derived/flags.yaml` | Flag SVGs, per-file license check | |
| [Natural Earth](https://www.naturalearthdata.com/) | Natural Earth | – | 5.1.1 | Land, de facto borders | Its names are not used |
| [Marine Regions](https://www.marineregions.org/) | VLIZ | – | EEZ v12, territorial seas v4 (2023) | EEZ and 12 nm zones | |
| v3 spreadsheet | COTW | EN, DE | – | Original starting point | Not in the repository |

Note: a primary source decides only where official sources disagree. An official change is
applied as soon as an official publication has it, even if the primary source has not caught
up yet; the language's spelling rules still apply.

## Standing rules

- **The official spelling of each language beats uniformity across languages.** A name is not
  adapted to look like the EN or DE form.
- **German: Swiss spelling, always `ss`, never `ß`** (e.g. "Weissrussland", "Grossherzogtum
  Luxemburg"). Forms taken from German, Austrian or EU sources are written without ß.
- **Official changes are applied as soon as possible** (source rule above).
- **Capitals have no disambiguating suffix:** "Meksyk", not "Meksyk (miasto)". The card says
  what it asks for.
- **The typographic apostrophe ’** is used everywhere ("Côte d’Ivoire"); `validate` rejects a
  straight `'` in names. The ʻokina is a letter, not an apostrophe, and stays ("Nukuʻalofa").
- **Checks of a new language are complete, never sampled:** every entry, every capital, every
  label.

## Deliberate exceptions

The same in every language:

- **Afghanistan:** the long form is the Islamic Emirate (EN "Islamic Emirate of Afghanistan",
  DE "Islamisches Emirat Afghanistan"), following the de facto situation, although the official
  lists above still name the Islamic Republic.
- **Capitals:** Majuro (Marshall Islands), Funafuti (Tuvalu) and Saipan (Northern Mariana
  Islands), not Delap, Vaiaku or Capitol Hill, the localities within them that some sources
  give.
