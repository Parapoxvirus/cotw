"""Card templates (10 types, DECISIONS D) and a minimal Anki template renderer.

Every template is generated per language from the same rows, so the EN package contains
only EN texts and the DE package only DE texts. Asset file names are passed in (they carry a
content hash, docs/DECK.md), so the templates always point at exactly the files shipped with
the package that installed them.

Buttons use inline ``onclick`` handlers that toggle a class on the card root: no ids, no
``setTimeout``, nothing left over when Anki desktop reuses the webview for the next card.
"""

from __future__ import annotations

import re

from .lang import CARD_TYPES, LANGS

# Attribute rows, in the order of the "full info" section.
ATTRIBUTES = ("country", "formal", "capital", "iso", "flag", "borders", "maps")
ICONS = {
    "country": "icon-country",
    "formal": "icon-formal",
    "capital": "icon-capital",
    "iso": "icon-iso",
    "flag": "icon-flag",
    "borders": "icon-borders",
    "maps": "icon-map",
}
TOGGLE = "this.closest('.cotw').classList.toggle('{cls}')"


def _f(lang: dict, key: str) -> str:
    return lang["fields"][key]


def _icon(assets: dict, key: str) -> str:
    """A row icon in the text color of each mode: one file per mode, CSS shows one."""
    return "".join(f'<img class="cotw-{mode}" src="{assets[f"{key}-{mode}"]}">' for mode in ("day", "night"))


def _row(icon: str, content: str, cls: str = "") -> str:
    """``icon`` is the icon cell's HTML (``_icon``)."""
    extra = f" {cls}" if cls else ""
    return (
        f'<div class="cotw-row{extra}"><div class="cotw-icon">{icon}</div>'
        f'<div class="cotw-content">{content}</div></div>'
    )


def _country(lang: dict) -> str:
    f = lambda k: _f(lang, k)  # noqa: E731
    dep = lang["dependency_of"].format("{{" + f("dependency_of") + "}}")
    return (
        f'<div class="cotw-name">{{{{{f("country")}}}}}'
        f'{{{{#{f("country_label")}}}}} <span class="cotw-label">{{{{{f("country_label")}}}}}</span>{{{{/{f("country_label")}}}}}</div>'
        f'{{{{#{f("dependency_of")}}}}}<div class="cotw-label">{dep}</div>{{{{/{f("dependency_of")}}}}}'
        f'{{{{#{f("status")}}}}}<div class="cotw-label">{{{{{f("status")}}}}}</div>{{{{/{f("status")}}}}}'
    )


def _capitals(lang: dict) -> str:
    f = lambda k: _f(lang, k)  # noqa: E731
    out = []
    for n in (1, 2, 3):
        name, label = f(f"capital_{n}"), f(f"capital_{n}_label")
        if n == 1:
            number = f'{{{{#{f("capital_2")}}}}}<span class="cotw-label">1.</span> {{{{/{f("capital_2")}}}}}'
        else:
            number = f'<span class="cotw-label">{n}.</span> '
        line = (
            f'<div class="cotw-capital">{number}{{{{{name}}}}}'
            f'{{{{#{label}}}}} <span class="cotw-label">{{{{{label}}}}}</span>{{{{/{label}}}}}</div>'
        )
        out.append(line if n == 1 else f"{{{{#{name}}}}}{line}{{{{/{name}}}}}")
    return "".join(out)


# Deferred globe packets (docs/GLOBE.md): attribute → asset. Anki ships only media named in a
# template, so every packet is referenced by name even though only the bootstrap runs eagerly.
GLOBE_PARTS = {"zones": "globe-zones", "detail": "globe-detail"}


def _globe_parts(assets: dict) -> str:
    return "".join(f' data-{part}-src="{assets[key]}"' for part, key in GLOBE_PARTS.items())


def _globe(lang: dict, tooltip: bool, assets: dict) -> str:
    tip = " data-tooltip" if tooltip else ""
    return (
        f'<div class="cotw-globe" data-id="{{{{{_f(lang, "locator")}}}}}" data-lang="{lang["code"]}"{tip}'
        f"{_globe_parts(assets)}></div>"
    )


def globe_script(assets: dict) -> str:
    """Deferred packets are referenced local media, loaded by the bootstrap only after first paint."""
    return f'<script src="{assets["globe"]}"{_globe_parts(assets)}></script>'


def _maps(lang: dict, globe: bool, tooltip: bool, assets: dict) -> str:
    maps = "".join(f'<div class="cotw-map">{{{{{_f(lang, k)}}}}}</div>' for k in ("map_1", "map_2"))
    return maps + (f'<div class="cotw-map">{_globe(lang, tooltip, assets)}</div>' if globe else "")


def _content(attr: str, lang: dict, assets: dict, *, tooltip: bool = True, globe: bool = True) -> str:
    f = lambda k: _f(lang, k)  # noqa: E731
    if attr == "country":
        return _country(lang)
    if attr == "formal":
        return f'{{{{{f("formal_name")}}}}}'
    if attr == "capital":
        return _capitals(lang)
    if attr == "iso":
        return f'{{{{{f("iso2")}}}}} · {{{{{f("iso3")}}}}}'
    if attr == "flag":
        return f'<div class="cotw-flag">{{{{{f("flag")}}}}}</div>'
    if attr == "borders":
        return f'<div class="cotw-neighbors">{{{{{f("borders")}}}}}</div>'
    if attr == "maps":
        return _maps(lang, globe, tooltip, assets)
    raise ValueError(attr)


def _attr_row(attr: str, lang: dict, assets: dict, cls: str = "", **kw) -> str:
    """One attribute row; optional attributes vanish entirely when their field is empty."""
    row = _row(_icon(assets, ICONS[attr]), _content(attr, lang, assets, **kw), cls)
    cond = {"formal": "formal_name", "borders": "borders"}.get(attr)
    if cond:
        return f"{{{{#{_f(lang, cond)}}}}}{row}{{{{/{_f(lang, cond)}}}}}"
    return row


def _infographic(assets: dict, key: str) -> str:
    return "".join(
        f'<img class="cotw-infographic cotw-{mode}" src="{assets[f"{key}-{mode}"]}">' for mode in ("day", "night")
    )


def _help(lang: dict, assets: dict, config: dict) -> str:
    ui = lang["ui"]
    rows = [
        f'<div class="cotw-row"><div class="cotw-icon"></div><div class="cotw-content cotw-title">{ui["symbols"]}</div></div>',
    ]
    for attr, key in (
        ("country", "sym_country"),
        ("formal", "sym_formal"),
        ("capital", "sym_capital"),
        ("iso", "sym_iso"),
        ("flag", "sym_flag"),
        ("borders", "sym_borders"),
        ("maps", "sym_map"),
    ):
        rows.append(_row(_icon(assets, ICONS[attr]), ui[key]))
    rows.append(
        f'<div class="cotw-row"><div class="cotw-icon"></div><div class="cotw-content cotw-title">{ui["general"]}</div></div>'
    )
    text = lang["help"].format(
        infographic=_infographic(assets, "infographic"),
        infographic_filtered=_infographic(assets, "infographic-filtered"),
        ankiweb=config["ankiweb"][lang["code"]],
        contact=config["contact"],
    )
    rows.append(_row(_icon(assets, "icon-help"), text.strip(), "cotw-help-text"))
    return f'<div class="cotw-box cotw-help">{"".join(rows)}</div>'


def _help_button(lang: dict) -> str:
    return (
        f'<span class="cotw-button" role="button" onclick="{TOGGLE.format(cls="cotw-show-help")}">'
        f'{lang["ui"]["help"]}</span>'
    )


def front(card: dict, lang: dict, assets: dict, config: dict) -> str:
    """Front: the asked attribute as "?", then the prompt. Nothing that names the entry."""
    asked, shown = card["asked"], card["shown"]
    box = (
        _row(_icon(assets, ICONS[asked]), "?", "cotw-ask")
        # The map prompt is the one front with a globe: no tooltip (DECISIONS B8).
        + _row(_icon(assets, ICONS[shown]), _content(shown, lang, assets, tooltip=False))
    )
    html = (
        f'<div class="cotw cotw-{lang["code"]}">'
        f'<div class="cotw-box">{box}</div>'
        f'<div class="cotw-buttons">{_help_button(lang)}</div>'
        f"{_help(lang, assets, config)}"
        "</div>"
    )
    if shown == "maps":
        html += globe_script(assets)
    if "borders" in (asked, shown):  # no card for entries without land borders
        b = _f(lang, "borders")
        html = f"{{{{#{b}}}}}{html}{{{{/{b}}}}}"
    return html


def back(card: dict, lang: dict, assets: dict, config: dict) -> str:
    """Back: answer + prompt, the globe (every back, DECISIONS B8), full info on demand."""
    asked, shown = card["asked"], card["shown"]
    maps_in_answer = "maps" in (asked, shown)
    answer = _attr_row(asked, lang, assets, "cotw-answer") + _attr_row(shown, lang, assets)
    if not maps_in_answer:
        answer += _row(_icon(assets, ICONS["maps"]), f'<div class="cotw-map">{_globe(lang, True, assets)}</div>')
    rest = [a for a in ATTRIBUTES if a not in (asked, shown)]
    info_rows = "".join(_attr_row(a, lang, assets, globe=False) for a in rest)
    ui = lang["ui"]
    info_button = _row(
        _icon(assets, "icon-info"),
        f'<span class="cotw-info-button" role="button" onclick="{TOGGLE.format(cls="cotw-show-info")}">'
        f'{ui["show_info"]}</span>',
        "cotw-info-toggle",
    )
    title = f'<div class="cotw-row"><div class="cotw-icon"></div><div class="cotw-content cotw-title">{ui["info_title"]}</div></div>'
    wiki = f'<a class="cotw-button" href="{{{{{_f(lang, "wikipedia")}}}}}" target="_blank" rel="noopener noreferrer">Wikipedia</a>'
    html = (
        f'<div class="cotw cotw-{lang["code"]}">'
        f'<div class="cotw-box">{answer}</div>'
        f'<div class="cotw-box cotw-info-button-box">{info_button}</div>'
        f'<div class="cotw-box cotw-info">{title}{info_rows}</div>'
        f'<div class="cotw-buttons">{wiki}{_help_button(lang)}</div>'
        f"{_help(lang, assets, config)}"
        "</div>"
        + globe_script(assets)
    )
    return html


def templates(lang_code: str, assets: dict, config: dict) -> list[dict]:
    """genanki template dicts (``name``, ``qfmt``, ``afmt``) in card-type order."""
    lang = LANGS[lang_code]
    return [
        {
            "name": lang["templates"][c["key"]],
            "qfmt": front(c, lang, assets, config),
            "afmt": back(c, lang, assets, config),
        }
        for c in CARD_TYPES
    ]


# --- rendering (preview and tests) ------------------------------------------------------------

_TAG = re.compile(r"\{\{([#^/]?)([^}]+)\}\}")


def render(template: str, fields: dict[str, str]) -> str:
    """Anki's template subset used here: ``{{Field}}``, ``{{#Field}}…{{/Field}}``, ``{{^Field}}…``.

    Like Anki, a field that is empty or only whitespace counts as empty; field content is
    inserted as HTML. Unknown fields and unbalanced sections raise, so a typo in a template
    fails the tests.
    """

    def value(name: str) -> str:
        if name not in fields:
            raise KeyError(f"unknown field {name!r}")
        return fields[name]

    out: list[str] = []
    stack: list[tuple[str, bool]] = []  # (field, parent visible and this section visible)
    visible = True
    pos = 0
    for m in _TAG.finditer(template):
        if visible:
            out.append(template[pos : m.start()])
        pos = m.end()
        kind, name = m.group(1), m.group(2)
        if kind in "#^" and kind:
            stack.append((name, visible))
            present = bool(value(name).strip())
            visible = visible and present == (kind == "#")
        elif kind == "/":
            if not stack or stack[-1][0] != name:
                raise ValueError(f"unbalanced section {name!r}")
            visible = stack.pop()[1]
        elif visible:
            out.append(value(name))
        else:
            value(name)
    if stack:
        raise ValueError(f"unclosed section {stack[-1][0]!r}")
    if visible:
        out.append(template[pos:])
    return "".join(out)
