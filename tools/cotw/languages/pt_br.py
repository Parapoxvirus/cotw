"""Portuguese (Brazil), following the Brazilian sources in ``docs/TRANSLATING.md``."""

from __future__ import annotations

from . import Language

# Object form of a sovereign after "território dependente …": the preposition "de" contracted
# with the article the name takes in Brazilian Portuguese (a test pins the set of parents).
GENITIVE = {
    "Austrália": "da Austrália",
    "China": "da China",
    "Dinamarca": "da Dinamarca",
    "Finlândia": "da Finlândia",
    "França": "da França",
    "Países Baixos": "dos Países Baixos",
    "Nova Zelândia": "da Nova Zelândia",
    "Noruega": "da Noruega",
    "Reino Unido": "do Reino Unido",
    "Estados Unidos": "dos Estados Unidos",
}


def object_form(name: str) -> str:
    return GENITIVE.get(name, "de " + name)


LANGUAGE = Language(
    code="pt-BR",
    identity="pt-BR",
    notetype_id=1906050354,
    deck_id=2081751341,
    extras_deck_id=1425183924,
    id_offset=150_000,
    notetype="COTW (PT-BR)",
    deck="Países do Mundo",
    extras="Países do Mundo::Extras",
    tag_root="COTW-PT-BR",
    status_tags={
        "sovereign": "Soberano",
        "dependency": "Território-Dependente",
        "disputed": "Disputado",
    },
    fields={
        "country": "País",
        "country_label": "País Observação",
        "formal_name": "Nome Oficial",
        "capital_1": "Capital 1",
        "capital_1_label": "Capital 1 Observação",
        "capital_2": "Capital 2",
        "capital_2_label": "Capital 2 Observação",
        "capital_3": "Capital 3",
        "capital_3_label": "Capital 3 Observação",
        "iso2": "ISO-2",
        "iso3": "ISO-3",
        "flag": "Bandeira",
        "map_1": "Mapa 1",
        "map_2": "Mapa 2",
        "locator": "Localizador",
        "borders": "Países Vizinhos",
        "wikipedia": "Wikipedia",
        "dependency_of": "Dependente De",
        "status": "Status",
    },
    templates={
        "country-capital": "01 País → Capital",
        "country-flag": "02 País → Bandeira",
        "capital-country": "03 Capital → País",
        "flag-country": "04 Bandeira → País",
        "map-country": "05 Mapa → País",
        "code-country": "06 Código ISO → País",
        "country-code": "07 País → Código ISO",
        "country-borders": "08 País → Países Vizinhos",
        "borders-country": "09 Países Vizinhos → País",
        "country-map": "10 País → Mapa",
    },
    dependency_of="território dependente {}",
    # Comentários de seção nos modelos de cartão (editor de modelos do Anki).
    comments={
        "question": "Pergunta",
        "answer": "Resposta",
        "info_button": "Botão: mostrar todas as informações",
        "info": "Todas as informações, exibidas pelo botão acima",
        "buttons": "Botões",
        "help": "Ajuda, exibida pelo botão Ajuda",
        "globe": "Globo",
    },
    status_disputed="status disputado",
    ui={
        "show_info": "Mostrar todas as informações",
        "info_title": "Todas as informações",
        "help": "Ajuda",
        "symbols": "Símbolos",
        "general": "Sobre este baralho",
        "sym_country": "País ou território",
        "sym_formal": "Nome oficial",
        "sym_capital": "Capital (se houver várias: numeradas, com a função de cada uma)",
        "sym_iso": "Códigos ISO 3166-1 (alfa-2 · alfa-3)",
        "sym_flag": "Bandeira",
        "sym_borders": "Países vizinhos (apenas fronteiras terrestres)",
        "sym_map": "Mapas e globo",
    },
    help="""
<p>Olá! Espero que você goste deste baralho.</p>
<p>Cada cartão mostra o país e pergunta alguma coisa sobre ele, ou mostra alguma coisa e pergunta
qual é o país, por exemplo PAÍS → BANDEIRA ou BANDEIRA → PAÍS.</p>
<p>
{infographic}
</p>
<p><b>Tipos de cartão:</b> Cinco tipos de cartão são recomendados e ficam no baralho principal:
capital, bandeira e mapa → país, além de país → capital e bandeira. Os outros cinco (país → mapa,
códigos ISO e países vizinhos nos dois sentidos) ficam no sub-baralho <i>Extras</i>. Se não quiser
estudá-los, abra o <i>Painel</i>, clique no baralho <i>Extras</i>, selecione todos os cartões e
escolha <i>Suspender</i>. Faça o mesmo para reativá-los depois.</p>
<p>
{infographic_filtered}
</p>
<p><b>Mapas e globo:</b> O mapa 1 mostra onde fica o país, o mapa 2, onde fica a capital. O globo
gira quando você o arrasta, o zoom é feito com dois dedos ou com a roda do mouse, e um toque duplo
o faz voltar à posição inicial. No verso, toque em um país para ver o nome dele.</p>
<p><b>Mar territorial e zonas econômicas:</b> A área azul-clara no mar é a zona econômica exclusiva
do país: até 200 milhas náuticas a partir da costa, onde a pesca e os recursos naturais pertencem a
ele. A linha clara dentro dela marca o mar territorial, em geral com 12 milhas náuticas de largura,
que juridicamente faz parte do país. O globo mostra apenas a zona econômica.</p>
<p><b>Ilhas pequenas:</b> Algumas ilhas muito pequenas não aparecem nos mapas nem no globo, mas as
zonas econômicas e os mares territoriais estão completos. Algumas ilhas disputadas também não
aparecem, ou aparecem como terra neutra, sem pertencer a nenhum país. O objetivo do baralho é
ensinar os países do mundo, não cada detalhe. Se quiser saber mais, o link da Wikipédia no verso
leva você adiante.</p>
<p><b>Fronteiras:</b> Os mapas e o globo usam as fronteiras fornecidas pelo
<a href="https://www.naturalearthdata.com">Natural Earth</a>, que representa fronteiras de fato:
quem realmente controla uma área. Por isso, as áreas disputadas seguem as linhas de controle
efetivo. O baralho não faz nenhuma declaração política; segue estritamente os dados fornecidos.
Não comente nem relate problemas relacionados a áreas disputadas.</p>
<p><b>Ajuda e contato:</b> Para saber mais sobre o COTW ou entrar em contato, acesse o
<a href="{repository}">repositório no GitHub</a>. Relate erros ou cartões desatualizados na
<a href="{issues}">página de problemas no GitHub</a>.</p>
""",
    description="""<p><b>Países do Mundo (COTW)</b>: {count} países e territórios, cada um com capital,
bandeira, dois mapas, um globo interativo, códigos ISO e países vizinhos.</p>
<p>Dez tipos de cartão: os cinco recomendados ficam neste baralho, os cinco extras no sub-baralho
<i>Extras</i>. Se não quiser estudar os extras, abra o <i>Painel</i>, clique no baralho
<i>Extras</i>, selecione todos os cartões e escolha <i>Suspender</i> (faça o mesmo para
reativá-los).</p>
<p><b>Fronteiras.</b> Os mapas e o globo desenham as fronteiras como a fonte,
<a href="https://www.naturalearthdata.com">Natural Earth</a>, as fornece, e o Natural Earth
representa fronteiras de fato: quem realmente controla uma área. A Crimeia, por exemplo, aparece
como russa, não como ucraniana, e as áreas disputadas no Himalaia seguem as linhas de controle
efetivo. O baralho não faz nenhuma declaração política; ele segue estritamente os dados
fornecidos.</p>
<p>Relate erros na <a href="{issues}">página de problemas no GitHub</a>. Para saber mais sobre o
COTW ou entrar em contato, acesse o <a href="{repository}">repositório no GitHub</a>.</p>
<p><b>Fontes e licenças.</b> Baralho, dados e código: domínio público
(<a href="https://creativecommons.org/publicdomain/zero/1.0/deed.pt-br">CC0 1.0</a>), Parapoxvirus.
Dados: <a href="https://www.wikidata.org">Wikidata</a> (CC0). Terra nos mapas e no globo:
<a href="https://www.naturalearthdata.com">Natural Earth</a> (domínio público). Zonas marítimas:
Marine Regions, Flanders Marine Institute (VLIZ),
<a href="https://creativecommons.org/licenses/by/4.0/deed.pt-br">CC BY 4.0</a>: {citation} Bandeiras:
<a href="https://commons.wikimedia.org">Wikimedia Commons</a>, apenas domínio público ou CC0; a
licença de cada arquivo está listada em {manifest}. Fonte tipográfica: IBM Plex Sans,
<a href="https://openfontlicense.org">SIL Open Font License 1.1</a> (incluída como {font_license}). Ícones:
<a href="https://phosphoricons.com">Phosphor Icons</a>, Copyright (c) 2023 Phosphor Icons, Licença MIT
(aviso completo incluído como {icons_license}).</p>""",
    extras_description="<p>Os cinco tipos de cartão extras: país → mapa, código ISO nos dois sentidos, países "
    "vizinhos nos dois sentidos. Se não quiser estudá-los, suspenda todos os cartões deste "
    "sub-baralho no <i>Painel</i>.</p>",
    # M49 region names (data/tags.txt) as they appear in the tags.
    regions={
        "Africa": "África",
        "Northern Africa": "África Setentrional",
        "Sub-Saharan Africa": "África Subsaariana",
        "Eastern Africa": "África Oriental",
        "Middle Africa": "África Central",
        "Southern Africa": "África Meridional",
        "Western Africa": "África Ocidental",
        "Americas": "Américas",
        "Latin America and the Caribbean": "América Latina e Caribe",
        "Caribbean": "Caribe",
        "Central America": "América Central",
        "South America": "América do Sul",
        "Northern America": "América do Norte",
        "Asia": "Ásia",
        "Central Asia": "Ásia Central",
        "Eastern Asia": "Ásia Oriental",
        "South-eastern Asia": "Sudeste da Ásia",
        "Southern Asia": "Ásia Meridional",
        "Western Asia": "Ásia Ocidental",
        "Europe": "Europa",
        "Eastern Europe": "Europa Oriental",
        "Northern Europe": "Europa Setentrional",
        "Channel Islands": "Ilhas do Canal",
        "Southern Europe": "Europa Meridional",
        "Western Europe": "Europa Ocidental",
        "Oceania": "Oceania",
        "Australia and New Zealand": "Austrália e Nova Zelândia",
        "Melanesia": "Melanésia",
        "Micronesia": "Micronésia",
        "Polynesia": "Polinésia",
    },
    object_form=object_form,
)
