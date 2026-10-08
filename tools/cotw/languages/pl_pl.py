"""Polish (Poland): names after the KSNG official lists."""

from __future__ import annotations

from . import Language

# Genitive after "terytorium zależne od …". A test pins the set of parents.
GENITIVE = {
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


def object_form(name: str) -> str:
    return GENITIVE.get(name, name)


LANGUAGE = Language(
    code="pl-PL",
    identity="pl-PL",
    notetype_id=2128848329,
    deck_id=2050014339,
    extras_deck_id=1596502066,
    id_offset=100_000,
    notetype="COTW (PL-PL)",
    deck="Kraje świata",
    extras="Kraje świata::Dodatkowe",
    tag_root="COTW-PL-PL",
    status_tags={
        "sovereign": "Suwerenne",
        "dependency": "Terytorium-zależne",
        "disputed": "Sporne",
    },
    fields={
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
    templates={
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
    dependency_of="terytorium zależne od {}",
    comments={
        "question": "Pytanie",
        "answer": "Odpowiedź",
        "info_button": "Przycisk: pokaż wszystkie informacje",
        "info": "Wszystkie informacje, po przycisku powyżej",
        "buttons": "Przyciski",
        "help": "Pomoc, po przycisku Pomoc",
        "globe": "Globus",
    },
    status_disputed="status sporny",
    ui={
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
    help="""
<p>Cześć! Mam nadzieję, że ta talia Ci się przyda.</p>
<p>Każda karta albo podaje kraj i pyta o coś, albo pokazuje coś i pyta o kraj, na przykład
KRAJ → FLAGA albo FLAGA → KRAJ.</p>
<p>
{infographic}
</p>
<p><b>Typy kart:</b> COTW poleca pięć typów w talii głównej: stolica, flaga i mapa → kraj oraz
kraj → stolica i flaga. Pozostałe pięć (kraj → mapa, kody ISO i sąsiedzi w obie strony) jest
w podtalii <i>Dodatkowe</i>. Jeśli nie chcesz się ich uczyć, otwórz <i>Przeglądaj</i>, kliknij
talię <i>Dodatkowe</i>, zaznacz wszystkie karty i wybierz <i>Zawieś</i>. Tak samo włączysz je
później z powrotem.</p>
<p>
{infographic_filtered}
</p>
<p><b>Mapy i globus:</b> Mapa 1 pokazuje, gdzie leży kraj, mapa 2 — gdzie jest jego stolica.
Globus obracasz przeciągając, zoomujesz szczypnięciem albo kółkiem myszy, a podwójne stuknięcie
resetuje widok. Na rewersie stuknięcie w kraj pokazuje jego nazwę.</p>
<p><b>Wody terytorialne i strefy ekonomiczne:</b> Jasnoniebieski obszar na morzu to wyłączna
strefa ekonomiczna kraju: do 200 mil morskich od brzegu, gdzie rybołówstwo i złoża mu
przysługują. Jasna linia w środku to wody terytorialne, zwykle 12 mil morskich, które prawnie
należą do kraju. Globus pokazuje tylko strefę ekonomiczną.</p>
<p><b>Małe wyspy:</b> Części bardzo małych wysp brakuje na mapach i globusie, ale strefy
ekonomiczne i wody terytorialne są kompletne. Części spornych wysp też brakuje, a niektóre są
narysowane jako ziemia niczyja. Talia uczy krajów świata, nie każdego szczegółu. Jeśli chcesz
wiedzieć więcej, link do Wikipedii na rewersie prowadzi dalej.</p>
<p><b>Granice:</b> Mapy i globus korzystają z granic dostarczanych przez
<a href="https://www.naturalearthdata.com">Natural Earth</a>, który pokazuje granice de facto:
kto faktycznie kontroluje dany obszar. Sporne obszary przebiegają więc wzdłuż linii faktycznej
kontroli. Talia nie zajmuje stanowiska politycznego; ściśle stosuje dostarczone dane. Nie komentuj
ani nie zgłaszaj problemów dotyczących spornych obszarów.</p>
<p><b>Pomoc i kontakt:</b> Więcej informacji o COTW i dane kontaktowe znajdziesz w
<a href="{repository}">repozytorium na GitHubie</a>. Błędy i nieaktualne karty zgłaszaj w
<a href="{issues}">zgłoszeniach na GitHubie</a>.</p>
""",
    description="""<p><b>Kraje świata (COTW)</b>: {count} krajów i terytoriów, każde ze stolicą,
flagą, dwiema mapami, obrotowym globusem, kodami ISO i sąsiadami.</p>
<p>Dziesięć typów kart: pięć polecanych jest w tej talii, pięć dodatkowych w podtalii
<i>Dodatkowe</i>. Jeśli nie chcesz uczyć się kart dodatkowych, otwórz <i>Przeglądaj</i>, kliknij
talię <i>Dodatkowe</i>, zaznacz wszystkie karty i wybierz <i>Zawieś</i> (tak samo włączysz je z
powrotem).</p>
<p><b>Granice.</b> Mapy i globus rysują granice tak, jak podaje źródło
<a href="https://www.naturalearthdata.com">Natural Earth</a>, a Natural Earth pokazuje granice
de facto: kto faktycznie kontroluje obszar. Krym na przykład jest rosyjski, nie ukraiński, a
sporne tereny w Himalajach idą za liniami kontroli. Talia nie zajmuje stanowiska politycznego;
trzyma się dostarczonych danych.</p>
<p>Błędy zgłaszaj w <a href="{issues}">zgłoszeniach na GitHubie</a>. Więcej informacji o COTW i
dane kontaktowe znajdziesz w <a href="{repository}">repozytorium na GitHubie</a>.</p>
<p><b>Źródła i licencje.</b> Talia, dane i kod: domena publiczna
(<a href="https://creativecommons.org/publicdomain/zero/1.0/deed.pl">CC0 1.0</a>), Parapoxvirus.
Dane: <a href="https://www.wikidata.org">Wikidata</a> (CC0). Ląd na mapach i globusie:
<a href="https://www.naturalearthdata.com">Natural Earth</a> (domena publiczna). Strefy morskie:
Marine Regions, Flanders Marine Institute (VLIZ),
<a href="https://creativecommons.org/licenses/by/4.0/deed.pl">CC BY 4.0</a>: {citation} Flagi:
<a href="https://commons.wikimedia.org">Wikimedia Commons</a>, tylko domena publiczna albo CC0;
licencja każdego pliku jest w {manifest}. Czcionka: IBM Plex Sans,
<a href="https://openfontlicense.org">SIL Open Font License 1.1</a> (dołączona jako
{font_license}). Ikony: <a href="https://phosphoricons.com">Phosphor Icons</a>, Copyright (c)
2023 Phosphor Icons, licencja MIT (pełna nota dołączona jako {icons_license}).</p>""",
    extras_description="<p>Pięć dodatkowych typów kart: kraj → mapa, kod ISO w obie strony, "
    "sąsiedzi w obie strony. Jeśli nie chcesz się ich uczyć, zawieś wszystkie karty tej "
    "podtalii w <i>Przeglądaj</i>.</p>",
    regions={
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
    },
    object_form=object_form,
)
