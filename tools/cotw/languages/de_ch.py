"""German (Switzerland): Swiss spelling (ss), names after the EDA list."""

from __future__ import annotations

from . import Language

# Object form of a sovereign after "abhängiges Gebiet von …" where the bare name needs an
# article. Every other parent reads correctly as is (a test pins the set of parents).
DATIVE = {
    "Vereinigte Staaten": "den Vereinigten Staaten",
    "Vereinigtes Königreich": "dem Vereinigten Königreich",
    "Niederlande": "den Niederlanden",
}


def object_form(name: str) -> str:
    return DATIVE.get(name, name)


LANGUAGE = Language(
    code="de-CH",
    # Legacy identity: v1.0.x was published with the code "de", before locales had a region. The
    # note GUIDs and the IDs below derive from it; changing it would duplicate every note.
    identity="de",
    notetype_id=1123558981,
    deck_id=2041372721,
    extras_deck_id=1539901401,
    id_offset=50_000,
    notetype="COTW (DE-CH)",
    deck="Länder der Welt",
    extras="Länder der Welt::Extras",
    tag_root="COTW-DE-CH",
    status_tags={
        "sovereign": "Souverän",
        "dependency": "Abhängiges-Gebiet",
        "disputed": "Umstritten",
    },
    fields={
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
    templates={
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
    dependency_of="abhängiges Gebiet von {}",
    # Abschnitts-Kommentare in den Kartenvorlagen (Vorlagen-Editor von Anki).
    comments={
        "question": "Frage",
        "answer": "Antwort",
        "info_button": "Knopf: alle Infos anzeigen",
        "info": "Alle Infos, eingeblendet über den Knopf oben",
        "buttons": "Knöpfe",
        "help": "Hilfe, eingeblendet über den Hilfe-Knopf",
        "globe": "Globus",
    },
    status_disputed="Status umstritten",
    ui={
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
    help="""
<p>Hallo! Schön, dass du mit diesem Deck lernst.</p>
<p>Jede Karte nennt dir entweder das Land und fragt nach etwas, oder sie zeigt dir etwas und fragt
nach dem Land, zum Beispiel LAND → FLAGGE oder FLAGGE → LAND.</p>
<p>
{infographic}
</p>
<p><b>Kartentypen:</b> Fünf Kartentypen sind empfohlen und liegen im Hauptdeck: Hauptstadt, Flagge
und Karte → Land sowie Land → Hauptstadt und Flagge. Die anderen fünf (Land → Karte, ISO-Codes und
Nachbarländer in beide Richtungen) liegen im Unterdeck <i>Extras</i>. Wenn du sie nicht lernen
möchtest, öffne das Fenster <i>Durchsuchen</i>, klicke auf das Deck <i>Extras</i>, markiere alle
Karten und wähle <i>Aussetzen</i>. Auf demselben Weg schaltest du sie später wieder ein.</p>
<p>
{infographic_filtered}
</p>
<p><b>Karten und Globus:</b> Karte 1 zeigt, wo das Land liegt, Karte 2, wo seine Hauptstadt ist. Den
Globus drehst du durch Ziehen, zoomen geht mit zwei Fingern oder dem Mausrad, ein Doppeltipp stellt
ihn zurück. Auf der Rückseite zeigt ein Tipp auf ein Land dessen Namen.</p>
<p><b>Hoheitsgewässer und Wirtschaftszonen:</b> Die hellblaue Fläche im Meer ist die Wirtschaftszone
des Landes: bis zu 200 Seemeilen vor der Küste, in denen Fischerei und Bodenschätze ihm gehören. Die
helle Linie darin zeigt die Hoheitsgewässer, meist 12 Seemeilen breit, die rechtlich zum Land
gehören. Der Globus zeigt nur die Wirtschaftszone.</p>
<p><b>Kleine Inseln:</b> Sehr kleine Inseln fehlen auf den Karten und dem Globus teilweise, die
Wirtschaftszonen und Hoheitsgewässer sind aber vollständig. Auch umstrittene Inseln fehlen zum Teil
oder sind neutral dargestellt, also ohne Zuordnung zu einem Land. Das Deck soll dir die Länder der
Welt beibringen, nicht jedes kleinste Detail. Wenn du es genauer wissen möchtest, hilft dir der
Wikipedia-Link auf der Rückseite weiter.</p>
<p><b>Grenzen:</b> Karten und Globus verwenden die von
<a href="https://www.naturalearthdata.com">Natural Earth</a> bereitgestellten Grenzen. Natural
Earth bildet De-facto-Grenzen ab: wer ein Gebiet tatsächlich kontrolliert. Umstrittene Gebiete
folgen deshalb den tatsächlichen Kontrolllinien. Das Deck macht keine politische Aussage, sondern
richtet sich strikt nach den gelieferten Daten. Bitte kommentiere umstrittene Gebiete nicht und
erstelle keine Issues dazu.</p>
<p><b>Hilfe und Kontakt:</b> Mehr Informationen zu COTW und Kontaktmöglichkeiten findest du im
<a href="{repository}">GitHub-Repository</a>. Fehler oder veraltete Karten kannst du in den
<a href="{issues}">GitHub-Issues</a> melden.</p>
""",
    description="""<p><b>Länder der Welt (COTW)</b>: {count} Länder und Gebiete, jeweils mit Hauptstadt,
Flagge, zwei Karten, einem drehbaren Globus, ISO-Codes und Nachbarländern.</p>
<p>Zehn Kartentypen: Die fünf empfohlenen liegen in diesem Deck, die fünf Extras im Unterdeck
<i>Extras</i>. Wenn du die Extras nicht lernen möchtest, öffne <i>Durchsuchen</i>, klicke auf das
Deck <i>Extras</i>, markiere alle Karten und wähle <i>Aussetzen</i> (genauso schaltest du sie wieder
ein).</p>
<p><b>Grenzen.</b> Karten und Globus zeigen die Grenzen so, wie die Kartenquelle
<a href="https://www.naturalearthdata.com">Natural Earth</a> sie liefert, und Natural Earth bildet
De-facto-Grenzen ab: wer ein Gebiet tatsächlich kontrolliert. Die Krim etwa erscheint als russisch,
nicht als ukrainisch, und die umstrittenen Gebiete im Himalaya folgen den tatsächlichen
Kontrolllinien. Das Deck macht keine politische Aussage, sondern richtet sich strikt nach dem
gelieferten Material.</p>
<p>Fehler kannst du in den <a href="{issues}">GitHub-Issues</a> melden. Mehr Informationen zu COTW
und Kontaktmöglichkeiten findest du im <a href="{repository}">GitHub-Repository</a>.</p>
<p><b>Quellen und Lizenzen.</b> Deck, Daten und Code: gemeinfrei
(<a href="https://creativecommons.org/publicdomain/zero/1.0/deed.de">CC0 1.0</a>), Parapoxvirus.
Daten: <a href="https://www.wikidata.org">Wikidata</a> (CC0). Land auf Karten und Globus:
<a href="https://www.naturalearthdata.com">Natural Earth</a> (gemeinfrei). Meereszonen: Marine
Regions, Flanders Marine Institute (VLIZ),
<a href="https://creativecommons.org/licenses/by/4.0/deed.de">CC BY 4.0</a>: {citation} Flaggen:
<a href="https://commons.wikimedia.org">Wikimedia Commons</a>, nur gemeinfrei oder CC0; die Lizenz
jeder Datei steht in {manifest}. Schrift: IBM Plex Sans,
<a href="https://openfontlicense.org">SIL Open Font License 1.1</a> (mitgeliefert als {font_license}). Symbole:
<a href="https://phosphoricons.com">Phosphor Icons</a>, Copyright (c) 2023 Phosphor Icons, MIT-Lizenz
(vollständiger Lizenzhinweis mitgeliefert als {icons_license}).</p>""",
    extras_description="<p>Die fünf zusätzlichen Kartentypen: Land → Karte, ISO-Code in beide Richtungen, "
    "Nachbarländer in beide Richtungen. Wenn du sie nicht lernen möchtest, setze alle Karten "
    "dieses Unterdecks in <i>Durchsuchen</i> aus.</p>",
    # M49 region names (data/tags.txt) as they appear in the tags.
    regions={
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
    },
    object_form=object_form,
)
