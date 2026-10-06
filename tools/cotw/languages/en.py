"""English: the base language (the database's reference names, the fallback for the others)."""

from __future__ import annotations

from . import Language


def object_form(name: str) -> str:
    """``United States, The`` → ``the United States``: the database's sort form, read in a sentence."""
    return "the " + name[: -len(", The")] if name.endswith(", The") else name


LANGUAGE = Language(
    code="en",
    wiki="enwiki",
    notetype_id=1829704095,
    deck_id=1866953617,
    extras_deck_id=1918702087,
    id_offset=0,
    notetype="COTW (EN)",
    deck="Countries of the World",
    extras="Countries of the World::Extras",
    tag_root="COTW-EN",
    status_tags={
        "sovereign": "Sovereign",
        "dependency": "Dependency",
        "disputed": "Disputed",
    },
    fields={
        "country": "Country",
        "country_label": "Country Label",
        "formal_name": "Formal Name",
        "capital_1": "Capital 1",
        "capital_1_label": "Capital 1 Label",
        "capital_2": "Capital 2",
        "capital_2_label": "Capital 2 Label",
        "capital_3": "Capital 3",
        "capital_3_label": "Capital 3 Label",
        "iso2": "ISO-2",
        "iso3": "ISO-3",
        "flag": "Flag",
        "map_1": "Map 1",
        "map_2": "Map 2",
        "locator": "Locator",
        "borders": "Borders",
        "wikipedia": "Wikipedia",
        "dependency_of": "Dependency Of",
        "status": "Status",
    },
    templates={
        "country-capital": "01 Country → Capital",
        "country-flag": "02 Country → Flag",
        "capital-country": "03 Capital → Country",
        "flag-country": "04 Flag → Country",
        "map-country": "05 Map → Country",
        "code-country": "06 ISO Code → Country",
        "country-code": "07 Country → ISO Code",
        "country-borders": "08 Country → Bordering Countries",
        "borders-country": "09 Bordering Countries → Country",
        "country-map": "10 Country → Map",
    },
    dependency_of="dependency of {}",
    # Section comments in the card templates (Anki's template editor).
    comments={
        "question": "Question",
        "answer": "Answer",
        "info_button": "Button: show full info",
        "info": "Full info, shown by the button above",
        "buttons": "Buttons",
        "help": "Help, shown by the Help button",
        "globe": "Globe",
    },
    status_disputed="status disputed",
    ui={
        "show_info": "Show full info",
        "info_title": "Full info",
        "help": "Help",
        "symbols": "Symbols",
        "general": "About this deck",
        "sym_country": "Country or territory",
        "sym_formal": "Formal name",
        "sym_capital": "Capital (several: numbered, with their role)",
        "sym_iso": "ISO 3166-1 codes (alpha-2 · alpha-3)",
        "sym_flag": "Flag",
        "sym_borders": "Bordering countries (land borders only)",
        "sym_map": "Maps and globe",
    },
    help="""
<p>Hi there, I hope you enjoy this deck.</p>
<p>Each card either gives you the country and asks for something, or gives you something and asks
for the country, e.g. COUNTRY → FLAG or FLAG → COUNTRY.</p>
<p>
{infographic}
</p>
<p><b>Card types:</b> Five card types are recommended and live in the main deck: capital, flag and
map → country, and country → capital and flag. The other five (country → map, ISO codes and
bordering countries in both directions) are in the subdeck <i>Extras</i>. To switch them off, open
the Browser, click the <i>Extras</i> deck, select all cards and choose <i>Suspend</i>. Do the same
again to switch them back on.</p>
<p>
{infographic_filtered}
</p>
<p><b>Maps and globe:</b> Map 1 shows where the country lies, map 2 where its capital is. The globe
turns when you drag it, zooms with a pinch or the mouse wheel and resets on a double tap. On the
back, tap a country to see its name.</p>
<p><b>Territorial waters and economic zones:</b> The light-blue area in the sea is the country's
exclusive economic zone: up to 200 nautical miles off the coast, where fishing and natural resources
belong to it. The light line inside it marks the territorial waters, usually 12 nautical miles wide,
which are legally part of the country. The globe shows only the economic zone.</p>
<p><b>Small islands:</b> Some very small islands are missing from the maps and the globe, but the
economic zones and territorial waters are complete. Some disputed islands are missing too or are
shown as neutral land that belongs to no country. The deck is about learning the countries of the
world, not every last detail. If you want to know more, the Wikipedia link on the back takes you
further.</p>
<p><b>Help and contact:</b> More about the deck: <a href="{ankiweb}">AnkiWeb page</a>. Can't find
your answer there? Email me at <a href="mailto:{contact}">{contact}</a>. Please also write if you
spot an error or a card that needs updating. This deck does not intend to be political: disputed
areas follow the situation on the ground.</p>
""",
    description="""<p><b>Countries of the World (COTW)</b>: {count} countries and territories, each with
capital, flag, two maps, an interactive globe, ISO codes and bordering countries.</p>
<p>Ten card types: the five recommended ones are in this deck, the five extras in the subdeck
<i>Extras</i>. To switch the extras off, open the Browser, click the <i>Extras</i> deck, select all
cards and choose <i>Suspend</i> (again to switch them back on).</p>
<p><b>Borders.</b> The maps and the globe draw borders as their source,
<a href="https://www.naturalearthdata.com">Natural Earth</a>, supplies them, and Natural Earth maps
de facto borders: who actually controls an area. Crimea, for example, is shown as Russian, not
Ukrainian, and the disputed areas in the Himalayas follow the lines of actual control. The deck
makes no political statement; it follows the supplied data strictly.</p>
<p><b>Sources and licenses.</b> Deck, data and code: public domain
(<a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0</a>), Parapoxvirus. Data:
<a href="https://www.wikidata.org">Wikidata</a> (CC0). Land on the maps and the globe:
<a href="https://www.naturalearthdata.com">Natural Earth</a> (public domain). Maritime zones:
Marine Regions, Flanders Marine Institute (VLIZ),
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>: {citation} Flags:
<a href="https://commons.wikimedia.org">Wikimedia Commons</a>, public domain or CC0 only; the license
of every file is listed in {manifest}. Font: IBM Plex Sans,
<a href="https://openfontlicense.org">SIL Open Font License 1.1</a> (shipped as {font_license}). Icons:
<a href="https://phosphoricons.com">Phosphor Icons</a>, Copyright (c) 2023 Phosphor Icons, MIT License (full
notice shipped as {icons_license}).</p>""",
    extras_description="<p>The five extra card types: country → map, ISO code in both directions, bordering "
    "countries in both directions. Suspend all cards of this subdeck in the Browser to switch "
    "them off.</p>",
    # M49 region names (data/tags.txt) as they appear in the tags.
    regions={
        "Africa": "Africa",
        "Northern Africa": "Northern Africa",
        "Sub-Saharan Africa": "Sub-Saharan Africa",
        "Eastern Africa": "Eastern Africa",
        "Middle Africa": "Middle Africa",
        "Southern Africa": "Southern Africa",
        "Western Africa": "Western Africa",
        "Americas": "Americas",
        "Latin America and the Caribbean": "Latin America and the Caribbean",
        "Caribbean": "Caribbean",
        "Central America": "Central America",
        "South America": "South America",
        "Northern America": "Northern America",
        "Asia": "Asia",
        "Central Asia": "Central Asia",
        "Eastern Asia": "Eastern Asia",
        "South-eastern Asia": "South-eastern Asia",
        "Southern Asia": "Southern Asia",
        "Western Asia": "Western Asia",
        "Europe": "Europe",
        "Eastern Europe": "Eastern Europe",
        "Northern Europe": "Northern Europe",
        "Channel Islands": "Channel Islands",
        "Southern Europe": "Southern Europe",
        "Western Europe": "Western Europe",
        "Oceania": "Oceania",
        "Australia and New Zealand": "Australia and New Zealand",
        "Melanesia": "Melanesia",
        "Micronesia": "Micronesia",
        "Polynesia": "Polynesia",
    },
    object_form=object_form,
    ankiweb="https://ankiweb.net/shared/info/1365662043",
)
