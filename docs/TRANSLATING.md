# Translating COTW

How a new deck language is added, which sources decide the names in each language, and the
rules every language follows. A deck language is a full BCP 47 locale (`en-US`, `de-CH`,
`fr-FR`): the language and the region whose spelling and official names it follows. The
technical side of a language (module, IDs, build) is in
[`DECK.md`](DECK.md#a-new-language), the data format in [`SCHEMA.md`](SCHEMA.md). How
contributions reach the published repository: [`CONTRIBUTING.md`](../CONTRIBUTING.md).

The wanted languages and their primary sources are listed in
[`data/locales.yaml`](../data/locales.yaml): every wanted locale with its Wikipedia, its
Wikidata label languages and, where known, its official naming source. The source register
below gives the role, coverage and limitations of every source actually used. A language is
added to the registry before its module; the registry rejects a module whose code is not listed.

## Adding a language: checklist

1. **List entry:** the locale in [`data/locales.yaml`](../data/locales.yaml), if it is not
   listed yet: `tag` in canonical case (`fr-FR`), `wiki`, `wikipedia`, `wikidata` (label
   languages in fallback order, `[fr]`), and the `naming_source` where known. Its
   Wikipedia links and Wikidata labels come from there.
2. **Module:** `tools/cotw/languages/<module>.py`, copied from `en_us.py` and translated
   ([`DECK.md`](DECK.md#a-new-language)):
   - **file name:** the code in lower case with `_` for `-` (`fr-FR` → `fr_fr.py`);
   - **`code`:** the tag exactly as in the list (`"fr-FR"`), also the key of its names in the
     data;
   - **`identity`:** the same value as `code` (`identity = code`); only en-US and de-CH keep
     the legacy identities `en` and `de`;
   - texts: note type, deck and subdeck names, `fields`, `templates`, `comments`, `ui`,
     `help`, `description`, `extras_description`, `status_tags`, `status_disputed`;
   - `regions`: every M49 region of `data/tags.txt`;
   - `dependency_of` and `object_form`: the sovereign's form after *dependency of …* (article,
     case; a test pins it for every parent);
   - `tag_root`: `COTW-<CODE>` (`COTW-FR-FR`), note type `COTW (<CODE>)`;
   - `notetype_id`, `deck_id`, `extras_deck_id`: computed once with
     `derive_id(identity, "notetype" | "deck" | "deck-extras")` and written in as constants,
     frozen from the first release on;
   - `id_offset`: the next free multiple of 50 000 (currently 200 000);
   - keep the `{repository}` and `{issues}` placeholders in `help` and `description`; translate
     their link text naturally. The build derives both links from `data/deck.yaml.repository`.

   A regional variant of a published language (`de-DE` next to `de-CH`) may build its module
   from the sister's with `dataclasses.replace`, but needs its own identity, IDs, deck names
   and names in the data.
3. **Data:** in every `data/countries/*.yaml`, `name.<code>` and `name.<code>` of every capital
   (both required); `name_label` and `capitals[].label` wherever the other locales have them
   (these shared-content maps remain complete); `formal_name.<code>` only where a sourced
   formal form is established. Omit an unsourced formal name—never copy the short name without
   a source, use null/empty text or fall back to another locale. `validate` strictly checks
   every supplied value;
   `wikipedia.<code>` with `python -m cotw fetch-wikipedia` (from the Wikidata sitelinks, never
   typed by hand); the labels in the Wikidata caches with `python -m cotw fetch-wikidata`.
4. **Build and check:** `python -m cotw validate`, `python -m pytest`, `python -m cotw build-deck`.
   Show that the existing packages are unchanged: build before and after with the same
   `SOURCE_DATE_EPOCH` and run `python tools/compare_packages.py build/before build/after`.
5. **Names, complete check:** every entry, every capital, every label and possible long form is
   checked against the language's sources below, in their priority order. The check is
   complete, never sampled. Verify the primary source in both `data/locales.yaml` and the source
   register below. A deviation, translated fallback or deliberately absent formal name gets a
   provenance row in [`data-changes.md`](data-changes.md); a sparse map is not permission to
   skip the check.
6. **Distribution:** new locales ship as `.apkg` release assets. Do not create another
   AnkiWeb listing; the English listing remains the only one.

Deck, subdeck and note-type texts are translated naturally for the locale, including the
`Extras` subdeck. Do not preserve an English label merely to make package names look uniform.

## Naming sources

Sources per language, in priority order. Edition and date as found when the links were checked
on 2026-10-07; lists that are regenerated on demand are marked *online*.

### English (EN-US)

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

### German (DE-CH)

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

### Polish (PL-PL)

1. **[Urzędowy wykaz nazw państw i terytoriów niesamodzielnych](https://www.gov.pl/web/ksng/Urzedowy-wykaz-nazw-panstw-i-terytoriow-niesamodzielnych)**
   (KSNG, 8th edition 2025, with update 1, the new capital of Equatorial Guinea of January 2026,
   and update 2, the renaming to Naoero of 12 May 2026). Primary; it decides where the official sources disagree.
   States and dependent territories with their capitals.
2. **[Urzędowy wykaz polskich nazw geograficznych świata](https://www.gov.pl/web/ksng/urzedowy-wykaz-polskich-nazw-geograficznych-swiata2)**
   (KSNG, 2nd edition 2019, list of changes as of 23 September 2026): other place names, for
   example capitals missing from the list above.

### Brazilian Portuguese (PT-BR)

1. **[Manual de redação oficial e diplomática do Itamaraty](https://www.gov.br/mre/pt-br/arquivos/manual-de-redacao)**
   (Ministério das Relações Exteriores do Brasil, approved by Portaria nº 292 of 11 May 2016,
   updated 23 July 2026). Primary for Brazilian Portuguese country/capital short and formal
   names. The official page may challenge automated clients, so the accessible official FUNAG
   reproduction below records the checked table without pretending to be a newer edition.
2. **[Topônimos e gentílicos](https://funag.gov.br/manual/index.php?title=Top%C3%B4nimos_e_gent%C3%ADlicos)**
   (Fundação Alexandre de Gusmão, checked 7 October 2026). Official accessible reproduction
   and supplement for the Manual's country, formal-name and capital table.
3. EU Annex A5 in Portuguese is **pt-PT**. It is only a cross-check for pt-BR, never its
   primary naming authority.

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

### Source rule and fallback

The primary source of a language decides only where official sources **disagree**; it is not a
reason to wait. When a state changes its name or capital and the primary source has not been
updated yet (the EDA list can lag), COTW follows the current official publications instead:
other national name lists (for example AA, StAGN or a KSNG update), UN/UNTERM, government
decrees. The language's spelling rules still apply (DE: Swiss spelling, ss, no ß).

If the primary national list has no entry, use this documented order: another official
publication for that locale; an official list in the same language variant where available;
then established local usage with recorded evidence. Do not cross a language variant silently
and do not invent a formal name to satisfy validation.

Example: Nauru's renaming to Naoero (UN notification of 26 June 2026) is an official change and
is applied as such: Naoero / Republik Naoero, from UNTERM and the Auswärtiges Amt list of
28 July 2026. The EDA list of 21 August 2026 lists Naoero as well. If it had still shown Nauru,
the change would not have waited for it, because the primary source only decides where official
sources disagree.

### All sources

Every source considered for COTW, used or not.

| Source | Publisher | Locale / language | Edition / date (checked 2026-10-07) | Role in COTW | Coverage / limitations |
|---|---|---|---|---|---|
| [Liste der Staatenbezeichnungen](https://www.eda.admin.ch/dam/de/sd-web/viWGvPDY5NYo/liste-etats_DE.pdf) | EDA (Swiss FDFA) | DE (also FR, IT) | 21 August 2026 | **DE primary** (decides on disagreement, not a reason to wait) | Swiss spelling, matches the deck; can lag, so newer official changes are applied without waiting for it |
| [Verzeichnis der Staatennamen für den amtlichen Gebrauch](https://www.auswaertiges-amt.de/de/service/terminologie/215252-215252) | Auswärtiges Amt (DE) | DE | Stand 28 July 2026 | DE cross-check | Uses ß; COTW writes ss |
| [Länderverzeichnis für den amtlichen Gebrauch](https://www.auswaertiges-amt.de/de/service/terminologie) | Auswärtiges Amt (DE), Sprachendienst | DE, EN, FR, ES, RU | Online PDF, checked 7 October 2026 | DE supplement for territories and geographical forms | Covers states, territories and historical terms; supplies Åland, Hong Kong and Macao forms |
| [Hongkong: Steckbrief](https://www.auswaertiges-amt.de/de/service/laender/hongkong-node/hongkong-200852) | Auswärtiges Amt (DE) | DE, EN | 12 March 2026; checked 7 October 2026 | DE supplement / cross-check | Gives the full Hong Kong designation; the Länderverzeichnis supplies the corresponding Macao form |
| [Macau: Steckbrief](https://www.auswaertiges-amt.de/de/service/laender/macau-node/macau-200870) | Auswärtiges Amt (DE) | DE, EN | 20 April 2026; checked 7 October 2026 | DE supplement / cross-check | Gives the full Macau designation |
| [Liste der Staatennamen und ihrer Ableitungen](https://stagn.bkg.bund.de/was-wir-veroeffentlichen/uebersichten-listen-und-datenbanken/synoptische-staatennamenliste) | StAGN | DE | 15th edition, October 2023 | DE cross-check | Uses ß; editions not always current |
| [Liste der Staatennamen](https://www.bmeia.gv.at/reports/staatennamen/) | BMEIA (AT) | DE (also EN, FR) | *online*, regenerated daily | not used | Austrian variants; one of de.wikipedia's bases |
| [Schreibweisungen](https://www.bk.admin.ch/de/schreibweisungen) | Swiss Federal Chancellery | DE | 2nd edition 2013, corrected 2015 | **DE spelling rule** | ss instead of ß (stated in its [Rechtschreibleitfaden](https://www.bk.admin.ch/de/rechtschreibleitfaden), 4th edition 2017) |
| [Urzędowy wykaz nazw państw i terytoriów niesamodzielnych](https://www.gov.pl/web/ksng/Urzedowy-wykaz-nazw-panstw-i-terytoriow-niesamodzielnych) | KSNG (PL) | PL | 8th edition 2025, updates 1 and 2 (2026) | **PL primary** (decides on disagreement, not a reason to wait) | Includes territories and capitals |
| [Urzędowy wykaz polskich nazw geograficznych świata](https://www.gov.pl/web/ksng/urzedowy-wykaz-polskich-nazw-geograficznych-swiata2) | KSNG (PL) | PL | 2nd edition 2019, changes as of 23 September 2026 | PL supplement | Other place names, e.g. capitals missing from the list above |
| [Manual de redação oficial e diplomática do Itamaraty](https://www.gov.br/mre/pt-br/arquivos/manual-de-redacao) | Ministério das Relações Exteriores do Brasil | pt-BR | Approved 11 May 2016; updated 23 July 2026 | **pt-BR primary** | Countries and capitals; the official page may challenge automated clients |
| [Topônimos e gentílicos](https://funag.gov.br/manual/index.php?title=Top%C3%B4nimos_e_gent%C3%ADlicos) | Fundação Alexandre de Gusmão (FUNAG) | pt-BR | Official online reproduction, checked 7 October 2026 | pt-BR supplement / accessible reproduction | Short and formal country names and capitals; not claimed as a newer independent edition |
| [Tabela Países da e-Financeira](https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/e-financeira/manuais-e-documento-tecnicos/tabelas-de-codigos/paises) | Receita Federal do Brasil | pt-BR | Modified 29 May 2026; checked 8 October 2026 | pt-BR fallback for ISO territories outside the Manual table | Maintained short-name/code list; it does not supply capitals or formal names and retains some tax-system qualifiers/legacy forms, so every disagreement is explicit in the field audit |
| [Agenda do Diretor do Departamento de Sanidade Vegetal, 10 August 2017](https://www.gov.br/agricultura/pt-br/acesso-a-informacao/2017-2018/agenda-do-diretor-do-departamento-de-sanidade-vegetal/2017-08-10) | Ministério da Agricultura e Pecuária do Brasil | pt-BR | Published and updated 10 August 2017; checked 8 October 2026 | Established Brazilian federal-government usage for `República da China (Taiwan)` | Narrow wording evidence only; not a general country-name list |
| [UNTERM](https://unterm.un.org/) | United Nations | AR, ZH, EN, FR, RU, ES | *online* | **EN primary** (UN member states; decides on disagreement, not a reason to wait) | Dependent territories largely missing |
| [Country names](https://www.gov.uk/government/publications/country-names), [Geographical names index](https://www.gov.uk/government/publications/geographical-names-and-information) | PCGN / FCDO (UK) | EN | 20 July 2026; 15 September 2026 | EN cross-check, territories | British usage; the index covers UK territories only |
| [Independent States in the World](https://www.state.gov/independent-states-in-the-world/); [Dependencies and Areas of Special Sovereignty](https://www.state.gov/dependencies-and-areas-of-special-sovereignty/) | US Department of State (Office of the Geographer) / BGN | EN | 11 August 2026; 31 March 2026 | EN cross-check, territories | US usage |
| [ISO 3166-1 Online Browsing Platform](https://www.iso.org/obp/ui/#iso:pub:PUB500001:en) | ISO | EN, FR | ISO 3166-1:2020, maintained online; checked 8 October 2026 | Codes and territory-name/formal-name cross-check | No pt-BR forms or capitals; an English/French formal form does not establish a pt-BR translation, which is omitted without separate evidence |
| [Geographic Names Server](https://geonames.nga.mil/geonames/GNSHome/) | US Board on Geographic Names / National Geospatial-Intelligence Agency | local approved names, romanized forms and variants | Online, updated daily; checked 8 October 2026 | Capital/place-name fallback outside the Brazilian Manual | Supplies authoritative foreign place spellings, not pt-BR exonyms or political-status decisions; US domestic/territory names use [GNIS](https://edits.nationalmap.gov/apps/gaz-domestic/public/search/names), Antarctic names use the [SCAR gazetteer](https://data.aad.gov.au/aadc/gaz/scar/) |
| [Interinstitutional Style Guide, Annex A5](https://style-guide.europa.eu/en/content/-/isg/topic?identifier=annex-a5-list-countries-territories-currencies) | European Union | all 24 EU languages | *online*; German PDF built 2 October 2026 | Cross-check DE/PL/PT/EN; base for future EU languages | Short/long form, capital, codes; DE with ß |
| [List of Country Names](https://unstats.un.org/unsd/ungegn/sessions/2nd_session_2021/documents/GEGN.2_2021_CRP130_4c_WG_Country_Names_rev2.pdf) | UNGEGN | endonyms + UN languages | GEGN.2/2021/CRP.130/Rev.1, 25 April 2021 (current as of March 2019) | not used, reference | Endonyms and the six UN languages only; exonyms are left to the national names authorities (KSNG, StAGN, EDA) |
| [CLDR](https://cldr.unicode.org/) | Unicode Consortium | almost all | 48.2, 17 March 2026 | not used | Software localization, not official; last resort for languages without an official list |
| [Wikidata](https://www.wikidata.org/) | Wikimedia | all | *online*; cached in `data/wikidata/` | Change monitor; capitals, coordinates, flag link (P41) | **Not a naming source** |
| Wikipedia ([en](https://en.wikipedia.org/), [de](https://de.wikipedia.org/), [pl](https://pl.wikipedia.org/), [pt](https://pt.wikipedia.org/)) | Wikimedia | per edition | *online*; sitelinks cached in `data/wikidata/sitelinks.json` | Article links only | Naming rules differ: de → AA/BMEIA/EDA, pl → KSNG, pt-BR → Brazilian authorities, en → "common name" |
| [Wikimedia Commons](https://commons.wikimedia.org/) | Wikimedia | – | per file, `data/derived/flags.yaml` | Flag SVGs, per-file license check | |
| [Natural Earth](https://www.naturalearthdata.com/) | Natural Earth | – | 5.1.1 | Land, de facto borders | Its names are not used |
| [Marine Regions](https://www.marineregions.org/) | VLIZ | – | EEZ v12, territorial seas v4 (2023) | EEZ and 12 nm zones | |
| v3 spreadsheet | COTW | EN, DE | – | Original starting point | Not in the repository |

Note: a primary source decides only where official sources disagree. An official change is
applied as soon as an official publication has it, even if the primary source has not caught
up yet; the language's spelling rules still apply.

## Standing rules

- **Names are locale-specific; facts are shared.** Official naming catalogues decide spelling,
  short/formal names and city names for their locale. Constitutional/legal and verified de
  facto evidence decides represented entities, status, locations, roles, order and granularity
  once for every locale. Labels translate the same role; a naming list's recognition qualifier
  or obsolete factual choice does not override shared facts.
- **The official spelling of each language beats uniformity across languages.** A name is not
  adapted to look like the EN or DE form.
- **German: Swiss spelling, always `ss`, never `ß`** (e.g. "Weissrussland", "Grossherzogtum
  Luxemburg"). Forms taken from German, Austrian or EU sources are written without ß.
- **Official changes are applied as soon as possible** (source rule above).
- **Formal names are optional per locale.** Record a sourced value even when it equals the
  short name; otherwise omit that locale and record why in `data-changes.md`. Missing means no
  rendered row, never another locale's text.
- **Prefer an official alternative that does not reveal the capital** where the locale's
  sources offer one, applying the same selection principle across locales. Do not invent one.
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
- **Hong Kong and Macao:** keep their own administrative locations, not Beijing. Their names
  remain locale-specific.
- **Jerusalem:** keep the disputed-capital qualification.
- **Equatorial Guinea:** keep Ciudad de la Paz as capital and Malabo as the government seat
  during the documented transition.

## Shared-fact evidence reviewed for the 2026-10-07 corrections

These sources decide roles and locations, not locale spelling. Exact old/new data and the
bounded verdicts are recorded in [`data-changes.md`](data-changes.md).

| Entity | Publisher and source | Date / checked | Role | Coverage / limitation |
|---|---|---|---|---|
| Eswatini: Mbabane | Government of Eswatini, [*Mbabane: From Town to Capital City*](https://40years.gov.sz/mbabane-from-town-to-capital-city/) | 6 April 2026 / checked 7 October 2026 | Primary national evidence | Calls Mbabane the administrative seat and centre of governance; does not define Lobamba's role |
| Eswatini: Lobamba | Parliament of the Kingdom of Eswatini, [FAQ](https://www.parliament.gov.sz/about/faqs/) | checked 7 October 2026 | Primary institutional evidence | Confirms Parliament is in Lobamba; supports `legislative`, not a general government-seat claim |
| Sri Lanka: capital functions | Ministry of Foreign Affairs, [National Profile](https://www.mfa.gov.lk/en/national-profile-and-geography); Parliament, [location](https://www.parliament.lk/en/visit-parliament/visiting-parliament/how-to-get-here) | checked 7 October 2026 | Primary national/institutional evidence | Kotte is the administrative capital and Parliament location; the profile does not classify Colombo as a government seat |
| Sri Lanka: Colombo functions | Presidential Secretariat, [contact](https://www.presidentsoffice.gov.lk/contact/); Prime Minister's Office, [contact](https://www.pmoffice.gov.lk/contact_details.php); Right to Information Commission, [Supreme Court listing](https://rti.gov.lk/do-list/) | checked 7 October 2026 | Primary institutional cross-check | Confirms the President, Prime Minister and Supreme Court remain in Colombo; supports retaining the bounded `seat_of_government` role, not relabelling a merely commercial function |
