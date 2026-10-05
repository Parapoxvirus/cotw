"""Everything that differs between language packages: identities, names, UI texts.

The numeric IDs are frozen constants. They were derived once from
``(int.from_bytes(sha256(f"cotw:{lang}:{kind}").digest()[:4], "big") >> 1) | 1 << 30`` and must
never change: Anki matches note types by ID, and a new ID would install a second note type
next to the old one on the next import (docs/DECK.md, "Identities").
"""

from __future__ import annotations

# Field keys in note-type order. The first field is the sort field (the country name).
FIELD_KEYS = (
    "country",
    "country_label",
    "formal_name",
    "capital_1",
    "capital_1_label",
    "capital_2",
    "capital_2_label",
    "capital_3",
    "capital_3_label",
    "iso2",
    "iso3",
    "flag",
    "map_1",
    "map_2",
    "locator",
    "borders",
    "wikipedia",
    "dependency_of",
    "status",
)

# Card types in template order (DECISIONS D). ``asked`` is the "?" on the front and the
# highlighted answer on the back; ``shown`` is the prompt.
CARD_TYPES = (
    {"key": "country-capital", "asked": "capital", "shown": "country", "extra": False},
    {"key": "country-flag", "asked": "flag", "shown": "country", "extra": False},
    {"key": "capital-country", "asked": "country", "shown": "capital", "extra": False},
    {"key": "flag-country", "asked": "country", "shown": "flag", "extra": False},
    {"key": "map-country", "asked": "country", "shown": "maps", "extra": False},
    {"key": "code-country", "asked": "country", "shown": "iso", "extra": True},
    {"key": "country-code", "asked": "iso", "shown": "country", "extra": True},
    {"key": "country-borders", "asked": "borders", "shown": "country", "extra": True},
    {"key": "borders-country", "asked": "country", "shown": "borders", "extra": True},
    {"key": "country-map", "asked": "maps", "shown": "country", "extra": True},
)

REGIONS_DE = {
    "Africa": "Afrika",
    "Northern Africa": "Nordafrika",
    "Sub-Saharan Africa": "Subsahara-Afrika",
    "Eastern Africa": "Ostafrika",
    "Middle Africa": "Zentralafrika",
    "Southern Africa": "Südliches Afrika",
    "Western Africa": "Westafrika",
    "Americas": "Amerika",
    "Latin America and the Caribbean": "Lateinamerika und Karibik",
    "Caribbean": "Karibik",
    "Central America": "Zentralamerika",
    "South America": "Südamerika",
    "Northern America": "Nordamerika",
    "Asia": "Asien",
    "Central Asia": "Zentralasien",
    "Eastern Asia": "Ostasien",
    "South-eastern Asia": "Südostasien",
    "Southern Asia": "Südasien",
    "Western Asia": "Westasien",
    "Europe": "Europa",
    "Eastern Europe": "Osteuropa",
    "Northern Europe": "Nordeuropa",
    "Channel Islands": "Kanalinseln",
    "Southern Europe": "Südeuropa",
    "Western Europe": "Westeuropa",
    "Oceania": "Ozeanien",
    "Australia and New Zealand": "Australien und Neuseeland",
    "Melanesia": "Melanesien",
    "Micronesia": "Mikronesien",
    "Polynesia": "Polynesien",
}

REGIONS_PL = {
    "Africa": "Afryka",
    "Northern Africa": "Afryka Północna",
    "Sub-Saharan Africa": "Afryka Subsaharyjska",
    "Eastern Africa": "Afryka Wschodnia",
    "Middle Africa": "Afryka Środkowa",
    "Southern Africa": "Afryka Południowa",
    "Western Africa": "Afryka Zachodnia",
    "Americas": "Ameryka",
    "Latin America and the Caribbean": "Ameryka Łacińska i Karaiby",
    "Caribbean": "Karaiby",
    "Central America": "Ameryka Środkowa",
    "South America": "Ameryka Południowa",
    "Northern America": "Ameryka Północna",
    "Asia": "Azja",
    "Central Asia": "Azja Środkowa",
    "Eastern Asia": "Azja Wschodnia",
    "South-eastern Asia": "Azja Południowo-Wschodnia",
    "Southern Asia": "Azja Południowa",
    "Western Asia": "Azja Zachodnia",
    "Europe": "Europa",
    "Eastern Europe": "Europa Wschodnia",
    "Northern Europe": "Europa Północna",
    "Channel Islands": "Wyspy Normandzkie",
    "Southern Europe": "Europa Południowa",
    "Western Europe": "Europa Zachodnia",
    "Oceania": "Oceania",
    "Australia and New Zealand": "Australia i Nowa Zelandia",
    "Melanesia": "Melanezja",
    "Micronesia": "Mikronezja",
    "Polynesia": "Polinezja",
}

# Object form of a sovereign after "abhängiges Gebiet von …" where the bare name needs an
# article. Every other parent reads correctly as is (a test pins the set of parents).
DATIVE_DE = {
    "Vereinigte Staaten": "den Vereinigten Staaten",
    "Vereinigtes Königreich": "dem Vereinigten Königreich",
    "Niederlande": "den Niederlanden",
}

# Genitive after "terytorium zależne od …". A test pins the set of parents.
DATIVE_PL = {
    "Australia": "Australii",
    "Chiny": "Chin",
    "Dania": "Danii",
    "Finlandia": "Finlandii",
    "Francja": "Francji",
    "Holandia": "Holandii",
    "Nowa Zelandia": "Nowej Zelandii",
    "Norwegia": "Norwegii",
    "Stany Zjednoczone": "Stanów Zjednoczonych",
    "Wielka Brytania": "Wielkiej Brytanii",
}

LANGS = {
    "en": {
        "code": "en",
        "notetype_id": 1829704095,
        "deck_id": 1866953617,
        "extras_deck_id": 1918702087,
        "id_offset": 0,
        "notetype": "COTW (EN)",
        "deck": "Countries of the World",
        "extras": "Countries of the World::Extras",
        "tag_root": "COTW-EN",
        "status_tags": {"sovereign": "Sovereign", "dependency": "Dependency", "disputed": "Disputed"},
        "fields": {
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
        "templates": {
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
        "dependency_of": "dependency of {}",
        # Section comments in the card templates (Anki's template editor).
        "comments": {
            "question": "Question",
            "answer": "Answer",
            "info_button": "Button: show full info",
            "info": "Full info, shown by the button above",
            "buttons": "Buttons",
            "help": "Help, shown by the Help button",
            "globe": "Globe",
        },
        "status_disputed": "status disputed",
        "ui": {
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
        "help": """
<p>Hi there, I hope you enjoy this deck.</p>
<p>Each card either gives you the country and asks for something, or gives you something
and asks for the country, e.g. COUNTRY → FLAG or FLAG → COUNTRY.</p>
<p>{infographic}</p>
<p><b>Card types:</b> Five card types are recommended and live in the main deck: capital, flag and map → country,
and country → capital and flag. The other five (country → map, ISO codes and bordering
countries in both directions) are in the subdeck <i>Extras</i>. To switch them off, open the
Browser, click the <i>Extras</i> deck, select all cards and choose <i>Suspend</i>. Do the same
again to switch them back on.</p>
<p>{infographic_filtered}</p>
<p><b>Maps and globe:</b> Map 1 shows where the country lies, map 2 where its capital is. The globe turns when you
drag it, zooms with a pinch or the mouse wheel and resets on a double tap. On the back, tap a
country to see its name.</p>
<p><b>Territorial waters and economic zones:</b> The light-blue area in the sea is the country's exclusive economic zone: up to 200 nautical
miles off the coast, where fishing and natural resources belong to it. The light line inside it
marks the territorial waters, usually 12 nautical miles wide, which are legally part of the
country. The globe shows only the economic zone.</p>
<p><b>Small islands:</b> Some very small islands are missing from the maps and the globe, but
the economic zones and territorial waters are complete. Some disputed islands are missing too
or are shown as neutral land that belongs to no country. The deck is about learning the
countries of the world, not every last detail. If you want to know more, the Wikipedia link on
the back takes you further.</p>
<p><b>Help and contact:</b> More about the deck: <a href="{ankiweb}">AnkiWeb page</a>. Can't find your answer there?
Email me at <a href="mailto:{contact}">{contact}</a>. Please also write if you spot an error or
a card that needs updating. This deck does not intend to be political: disputed areas follow
the situation on the ground.</p>
""",
    },
    "de": {
        "code": "de",
        "notetype_id": 1123558981,
        "deck_id": 2041372721,
        "extras_deck_id": 1539901401,
        "id_offset": 50_000,
        "notetype": "COTW (DE)",
        "deck": "Länder der Welt",
        "extras": "Länder der Welt::Extras",
        "tag_root": "COTW-DE",
        "status_tags": {"sovereign": "Souverän", "dependency": "Abhängiges-Gebiet", "disputed": "Umstritten"},
        "fields": {
            "country": "Land",
            "country_label": "Land Zusatz",
            "formal_name": "Amtlicher Name",
            "capital_1": "Hauptstadt 1",
            "capital_1_label": "Hauptstadt 1 Zusatz",
            "capital_2": "Hauptstadt 2",
            "capital_2_label": "Hauptstadt 2 Zusatz",
            "capital_3": "Hauptstadt 3",
            "capital_3_label": "Hauptstadt 3 Zusatz",
            "iso2": "ISO-2",
            "iso3": "ISO-3",
            "flag": "Flagge",
            "map_1": "Karte 1",
            "map_2": "Karte 2",
            "locator": "Locator",
            "borders": "Nachbarländer",
            "wikipedia": "Wikipedia",
            "dependency_of": "Abhängig von",
            "status": "Status",
        },
        "templates": {
            "country-capital": "01 Land → Hauptstadt",
            "country-flag": "02 Land → Flagge",
            "capital-country": "03 Hauptstadt → Land",
            "flag-country": "04 Flagge → Land",
            "map-country": "05 Karte → Land",
            "code-country": "06 ISO-Code → Land",
            "country-code": "07 Land → ISO-Code",
            "country-borders": "08 Land → Nachbarländer",
            "borders-country": "09 Nachbarländer → Land",
            "country-map": "10 Land → Karte",
        },
        "dependency_of": "abhängiges Gebiet von {}",
        # Abschnitts-Kommentare in den Kartenvorlagen (Vorlagen-Editor von Anki).
        "comments": {
            "question": "Frage",
            "answer": "Antwort",
            "info_button": "Knopf: alle Infos anzeigen",
            "info": "Alle Infos, eingeblendet über den Knopf oben",
            "buttons": "Knöpfe",
            "help": "Hilfe, eingeblendet über den Hilfe-Knopf",
            "globe": "Globus",
        },
        "status_disputed": "Status umstritten",
        "ui": {
            "show_info": "Alle Infos anzeigen",
            "info_title": "Alle Infos",
            "help": "Hilfe",
            "symbols": "Symbole",
            "general": "Über dieses Deck",
            "sym_country": "Land oder Gebiet",
            "sym_formal": "Amtlicher Name",
            "sym_capital": "Hauptstadt (bei mehreren: nummeriert, mit ihrer Rolle)",
            "sym_iso": "ISO-3166-1-Codes (Alpha-2 · Alpha-3)",
            "sym_flag": "Flagge",
            "sym_borders": "Nachbarländer (nur Landgrenzen)",
            "sym_map": "Karten und Globus",
        },
        "help": """
<p>Hallo! Schön, dass du mit diesem Deck lernst.</p>
<p>Jede Karte nennt dir entweder das Land und fragt nach etwas, oder sie zeigt dir etwas und
fragt nach dem Land, zum Beispiel LAND → FLAGGE oder FLAGGE → LAND.</p>
<p>{infographic}</p>
<p><b>Kartentypen:</b> Fünf Kartentypen empfehlen wir, sie liegen im Hauptdeck: Hauptstadt, Flagge und Karte →
Land sowie Land → Hauptstadt und Flagge. Die anderen fünf (Land → Karte, ISO-Codes und
Nachbarländer in beide Richtungen) liegen im Unterdeck <i>Extras</i>. Wenn du sie nicht lernen
möchtest, öffne das Fenster <i>Durchsuchen</i>, klicke auf das Deck <i>Extras</i>, markiere alle Karten
und wähle <i>Aussetzen</i>. Auf demselben Weg schaltest du sie später wieder ein.</p>
<p>{infographic_filtered}</p>
<p><b>Karten und Globus:</b> Karte 1 zeigt, wo das Land liegt, Karte 2, wo seine Hauptstadt ist. Den Globus drehst du
durch Ziehen, zoomen geht mit zwei Fingern oder dem Mausrad, ein Doppeltipp stellt ihn
zurück. Auf der Rückseite zeigt ein Tipp auf ein Land dessen Namen.</p>
<p><b>Hoheitsgewässer und Wirtschaftszonen:</b> Die hellblaue Fläche im Meer ist die Wirtschaftszone des Landes: bis zu 200 Seemeilen vor
der Küste, in denen Fischerei und Bodenschätze ihm gehören. Die helle Linie darin zeigt die
Hoheitsgewässer, meist 12 Seemeilen breit, die rechtlich zum Land gehören. Der Globus zeigt nur
die Wirtschaftszone.</p>
<p><b>Kleine Inseln:</b> Sehr kleine Inseln fehlen auf den Karten und dem Globus teilweise, die
Wirtschaftszonen und Hoheitsgewässer sind aber vollständig. Auch umstrittene Inseln fehlen zum
Teil oder sind neutral dargestellt, also ohne Zuordnung zu einem Land. Das Deck soll dir die
Länder der Welt beibringen, nicht jedes kleinste Detail. Wenn du es genauer wissen möchtest,
hilft dir der Wikipedia-Link auf der Rückseite weiter.</p>
<p><b>Hilfe und Kontakt:</b> Mehr zum Deck steht auf der <a href="{ankiweb}">AnkiWeb-Seite</a>. Keine Antwort gefunden?
Schreib mir an <a href="mailto:{contact}">{contact}</a>, gerne auch, wenn dir ein Fehler
auffällt oder eine Karte veraltet ist. Das Deck bezieht keine politische Position: Umstrittene
Gebiete sind so erfasst, wie die Lage vor Ort tatsächlich ist.</p>
""",
    },
    "pl": {
        "code": "pl",
        "notetype_id": 1086132728,
        "deck_id": 1918334422,
        "extras_deck_id": 1757053035,
        "id_offset": 100_000,
        "notetype": "COTW (PL)",
        "deck": "Kraje świata",
        "extras": "Kraje świata::Extras",
        "tag_root": "COTW-PL",
        "status_tags": {"sovereign": "Suwerenne", "dependency": "Terytorium-zależne", "disputed": "Sporne"},
        "fields": {
            "country": "Kraj",
            "country_label": "Kraj dopisek",
            "formal_name": "Nazwa oficjalna",
            "capital_1": "Stolica 1",
            "capital_1_label": "Stolica 1 dopisek",
            "capital_2": "Stolica 2",
            "capital_2_label": "Stolica 2 dopisek",
            "capital_3": "Stolica 3",
            "capital_3_label": "Stolica 3 dopisek",
            "iso2": "ISO-2",
            "iso3": "ISO-3",
            "flag": "Flaga",
            "map_1": "Mapa 1",
            "map_2": "Mapa 2",
            "locator": "Locator",
            "borders": "Sąsiedzi",
            "wikipedia": "Wikipedia",
            "dependency_of": "Zależne od",
            "status": "Status",
        },
        "templates": {
            "country-capital": "01 Kraj → Stolica",
            "country-flag": "02 Kraj → Flaga",
            "capital-country": "03 Stolica → Kraj",
            "flag-country": "04 Flaga → Kraj",
            "map-country": "05 Mapa → Kraj",
            "code-country": "06 Kod ISO → Kraj",
            "country-code": "07 Kraj → Kod ISO",
            "country-borders": "08 Kraj → Sąsiedzi",
            "borders-country": "09 Sąsiedzi → Kraj",
            "country-map": "10 Kraj → Mapa",
        },
        "dependency_of": "terytorium zależne od {}",
        "comments": {
            "question": "Pytanie",
            "answer": "Odpowiedź",
            "info_button": "Przycisk: pokaż wszystkie informacje",
            "info": "Wszystkie informacje, po przycisku powyżej",
            "buttons": "Przyciski",
            "help": "Pomoc, po przycisku Pomoc",
            "globe": "Globus",
        },
        "status_disputed": "status sporny",
        "ui": {
            "show_info": "Pokaż wszystkie informacje",
            "info_title": "Wszystkie informacje",
            "help": "Pomoc",
            "symbols": "Oznaczenia",
            "general": "O tej talii",
            "sym_country": "Kraj lub terytorium",
            "sym_formal": "Nazwa oficjalna",
            "sym_capital": "Stolica (kilka: numerowane, z rolą)",
            "sym_iso": "Kody ISO 3166-1 (alpha-2 · alpha-3)",
            "sym_flag": "Flaga",
            "sym_borders": "Sąsiedzi (tylko granice lądowe)",
            "sym_map": "Mapy i globus",
        },
        "help": """
<p>Cześć! Mam nadzieję, że ta talia Ci się przyda.</p>
<p>Każda karta albo podaje kraj i pyta o coś, albo pokazuje coś i pyta o kraj, na przykład
KRAJ → FLAGA albo FLAGA → KRAJ.</p>
<p>{infographic}</p>
<p><b>Typy kart:</b> Pięć typów polecamy — są w talii głównej: stolica, flaga i mapa → kraj oraz kraj → stolica
i flaga. Pozostałe pięć (kraj → mapa, kody ISO i sąsiedzi w obie strony) leży w podtalii
<i>Extras</i>. Jeśli nie chcesz ich uczyć, otwórz <i>Przeglądaj</i>, kliknij talię <i>Extras</i>, zaznacz
wszystkie karty i wybierz <i>Zawieś</i>. Tak samo włączysz je później z powrotem.</p>
<p>{infographic_filtered}</p>
<p><b>Mapy i globus:</b> Mapa 1 pokazuje, gdzie leży kraj, mapa 2 — gdzie jest jego stolica. Globus obracasz
przeciągając, zoomujesz szczypnięciem albo kółkiem myszy, podwójne stuknięcie resetuje widok.
Na rewersie stuknięcie w kraj pokazuje jego nazwę.</p>
<p><b>Wody terytorialne i strefy ekonomiczne:</b> Jasnoniebieski obszar na morzu to wyłączna strefa ekonomiczna kraju: do 200 mil
morskich od brzegu, gdzie rybołówstwo i złoża mu przysługują. Jasna linia w środku to wody
terytorialne, zwykle 12 mil morskich, które prawnie należą do kraju. Globus pokazuje tylko
strefę ekonomiczną.</p>
<p><b>Małe wyspy:</b> Bardzo małe wyspy częściowo brakują na mapach i globusie, ale strefy ekonomiczne
i wody terytorialne są kompletne. Część spornych wysp też brakuje albo jest narysowana jako
ziemia niczyja. Talia uczy krajów świata, nie każdego szczegółu. Jeśli chcesz wiedzieć więcej,
link do Wikipedii na rewersie prowadzi dalej.</p>
<p><b>Pomoc i kontakt:</b> Więcej o talii: <a href="{ankiweb}">strona AnkiWeb</a>. Nie znalazłeś odpowiedzi?
Napisz na <a href="mailto:{contact}">{contact}</a>, też gdy znajdziesz błąd albo nieaktualną kartę.
Talia nie zajmuje stanowiska politycznego: sporne obszary są zapisane tak, jak wygląda sytuacja
na miejscu.</p>
""",
    },
}
