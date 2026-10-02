"""Card templates (10 types, DECISIONS D) and a minimal Anki template renderer.

Every template is generated per language from the same rows, so the EN package contains
only EN texts and the DE package only DE texts. Asset file names are passed in (they carry a
content hash, docs/DECK.md), so the templates always point at exactly the files shipped with
the package that installed them.

The output is meant to be read and edited in Anki's card-template editor: block elements
(boxes, rows, icon and content cells) go on their own lines, indented by nesting, with a
comment per section. Inline content (a name with its label, a capital, a button) stays on one
line, because a line break between inline elements renders as a space. Every container that
gets line breaks is a flex container (style.css), where whitespace between children renders as
nothing, so the formatting does not change the layout.

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
INDENT = "  "


def _f(lang: dict, key: str) -> str:
    return lang["fields"][key]


# --- formatting ---------------------------------------------------------------------------------


def _indent(text: str) -> str:
    return "\n".join(INDENT + line if line.strip() else "" for line in text.split("\n"))


def _block(start: str, *children: str) -> str:
    """``start`` tag, the non-empty ``children`` one level deeper, the end tag on its own line.
    Without children the element stays on one line."""
    tag = start[1:].split(None, 1)[0].rstrip(">")
    body = "\n".join(c for c in children if c)
    return f"{start}\n{_indent(body)}\n</{tag}>" if body else f"{start}</{tag}>"


def _section(field: str, body: str, block: bool = False) -> str:
    """``{{#field}}…{{/field}}``: on one line around single-line inline ``body``, otherwise
    (or with ``block``, for block elements) with ``body`` indented on its own lines."""
    if not block and "\n" not in body:
        return f"{{{{#{field}}}}}{body}{{{{/{field}}}}}"
    return f"{{{{#{field}}}}}\n{_indent(body)}\n{{{{/{field}}}}}"


def _comment(lang: dict, key: str) -> str:
    return f"<!-- {lang['comments'][key]} -->"


# --- rows -----------------------------------------------------------------------------------------


def _icon(assets: dict, key: str) -> str:
    """A row icon in the text color of each mode: one file per mode, CSS shows one."""
    return "\n".join(f'<img class="cotw-{mode}" src="{assets[f"{key}-{mode}"]}">' for mode in ("day", "night"))


def _row(icon: str, content: str, cls: str = "", content_cls: str = "") -> str:
    """``icon`` is the icon cell's HTML (``_icon``, or ``""`` for an empty cell)."""
    extra = f" {cls}" if cls else ""
    content_extra = f" {content_cls}" if content_cls else ""
    start = f'<div class="cotw-content{content_extra}">'
    # Block content (a nested div, several lines) gets its own lines, inline content stays inside.
    block = "\n" in content or content.startswith("<div")
    cell = _block(start, content) if block else f"{start}{content}</div>"
    return _block(f'<div class="cotw-row{extra}">', _block('<div class="cotw-icon">', icon), cell)


def _title_row(text: str) -> str:
    return _row("", text, content_cls="cotw-title")


def _country(lang: dict) -> str:
    f = lambda k: _f(lang, k)  # noqa: E731
    label = f("country_label")
    dep = lang["dependency_of"].format("{{" + f("dependency_of") + "}}")
    name = (
        f'<div class="cotw-name">{{{{{f("country")}}}}}'
        f'{{{{#{label}}}}} <span class="cotw-label">{{{{{label}}}}}</span>{{{{/{label}}}}}</div>'
    )
    return "\n".join(
        (
            name,
            _section(f("dependency_of"), f'<div class="cotw-label">{dep}</div>', block=True),
            _section(f("status"), f'<div class="cotw-label">{{{{{f("status")}}}}}</div>', block=True),
        )
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
        out.append(line if n == 1 else _section(name, line, block=True))
    return "\n".join(out)


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
    maps = [f'<div class="cotw-map">{{{{{_f(lang, k)}}}}}</div>' for k in ("map_1", "map_2")]
    if globe:
        maps.append(_block('<div class="cotw-map">', _globe(lang, tooltip, assets)))
    return "\n".join(maps)


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
        return _section(_f(lang, cond), row)
    return row


def _infographic(assets: dict, key: str) -> str:
    return "".join(
        f'<img class="cotw-infographic cotw-{mode}" src="{assets[f"{key}-{mode}"]}">' for mode in ("day", "night")
    )


def _help(lang: dict, assets: dict, config: dict) -> str:
    ui = lang["ui"]
    rows = [_title_row(ui["symbols"])]
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
    rows.append(_title_row(ui["general"]))
    text = lang["help"].format(
        infographic=_infographic(assets, "infographic"),
        infographic_filtered=_infographic(assets, "infographic-filtered"),
        ankiweb=config["ankiweb"][lang["code"]],
        contact=config["contact"],
    )
    rows.append(_row(_icon(assets, "icon-help"), text.strip(), "cotw-help-text"))
    return _block('<div class="cotw-box cotw-help">', *rows)


def _help_button(lang: dict) -> str:
    return (
        f'<span class="cotw-button" role="button" onclick="{TOGGLE.format(cls="cotw-show-help")}">'
        f'{lang["ui"]["help"]}</span>'
    )


def _card(lang: dict, *parts: str) -> str:
    """The card root around ``parts``."""
    return _block(f'<div class="cotw cotw-{lang["code"]}">', *parts)


def front(card: dict, lang: dict, assets: dict, config: dict) -> str:
    """Front: the asked attribute as "?", then the prompt. Nothing that names the entry."""
    asked, shown = card["asked"], card["shown"]
    box = _block(
        '<div class="cotw-box">',
        _row(_icon(assets, ICONS[asked]), "?", "cotw-ask"),
        # The map prompt is the one front with a globe: no tooltip (DECISIONS B8).
        _row(_icon(assets, ICONS[shown]), _content(shown, lang, assets, tooltip=False)),
    )
    html = _card(
        lang,
        _comment(lang, "question"),
        box,
        _comment(lang, "buttons"),
        _block('<div class="cotw-buttons">', _help_button(lang)),
        _comment(lang, "help"),
        _help(lang, assets, config),
    )
    if shown == "maps":
        html += "\n" + _comment(lang, "globe") + "\n" + globe_script(assets)
    if "borders" in (asked, shown):  # no card for entries without land borders
        html = _section(_f(lang, "borders"), html, block=True)
    return html


def back(card: dict, lang: dict, assets: dict, config: dict) -> str:
    """Back: answer + prompt, the globe (every back, DECISIONS B8), full info on demand."""
    asked, shown = card["asked"], card["shown"]
    maps_in_answer = "maps" in (asked, shown)
    answer = [_attr_row(asked, lang, assets, "cotw-answer"), _attr_row(shown, lang, assets)]
    if not maps_in_answer:
        answer.append(_row(_icon(assets, ICONS["maps"]), _block('<div class="cotw-map">', _globe(lang, True, assets))))
    rest = [a for a in ATTRIBUTES if a not in (asked, shown)]
    ui = lang["ui"]
    info_button = _row(
        _icon(assets, "icon-info"),
        f'<span class="cotw-info-button" role="button" onclick="{TOGGLE.format(cls="cotw-show-info")}">'
        f'{ui["show_info"]}</span>',
        "cotw-info-toggle",
    )
    wiki = f'<a class="cotw-button" href="{{{{{_f(lang, "wikipedia")}}}}}" target="_blank" rel="noopener noreferrer">Wikipedia</a>'
    return "\n".join(
        (
            _card(
                lang,
                _comment(lang, "answer"),
                _block('<div class="cotw-box">', *answer),
                _comment(lang, "info_button"),
                _block('<div class="cotw-box cotw-info-button-box">', info_button),
                _comment(lang, "info"),
                _block(
                    '<div class="cotw-box cotw-info">',
                    _title_row(ui["info_title"]),
                    *(_attr_row(a, lang, assets, globe=False) for a in rest),
                ),
                _comment(lang, "buttons"),
                _block('<div class="cotw-buttons">', wiki, _help_button(lang)),
                _comment(lang, "help"),
                _help(lang, assets, config),
            ),
            _comment(lang, "globe"),
            globe_script(assets),
        )
    )


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
