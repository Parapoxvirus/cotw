"""Card templates (10 types, DECISIONS D) and a minimal Anki template renderer.

Every template is generated per language from the same Jinja sources in ``cards/``, so each
package contains only the texts of its language. Asset file names are passed in
(they carry a content hash, docs/DECK.md), so the templates always point at exactly the files
shipped with the package that installed them.

The sources are the indented HTML that users see in Anki's card-template editor. Jinja uses
``[[ ]]`` / ``[% %]`` / ``[# #]`` so that Anki's ``{{Field}}`` syntax stays literal; fields are
written by key (``{{country}}``) and mapped to the language's field names after rendering.

Buttons use inline ``onclick`` handlers that toggle a class on the card root: no ids, no
``setTimeout``, nothing left over when Anki desktop reuses the webview for the next card.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import jinja2

from .. import languages
from ..languages import Language
from .lang import CARD_TYPES, FIELD_KEYS

CARDS = Path(__file__).parent / "cards"

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
# The help box's symbol legend: attribute → UI text key.
SYMBOLS = (
    ("country", "sym_country"),
    ("formal", "sym_formal"),
    ("capital", "sym_capital"),
    ("iso", "sym_iso"),
    ("flag", "sym_flag"),
    ("borders", "sym_borders"),
    ("maps", "sym_map"),
)

# Deferred globe packets (docs/GLOBE.md): attribute → asset. Anki ships only media named in a
# template, so every packet is referenced by name even though only the bootstrap runs eagerly.
GLOBE_PARTS = {"zones": "globe-zones", "detail": "globe-detail"}


def _fail(message: str):
    raise ValueError(message)


@cache
def _env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(CARDS),
        block_start_string="[%",
        block_end_string="%]",
        variable_start_string="[[",
        variable_end_string="]]",
        comment_start_string="[#",
        comment_end_string="#]",
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=False,
    )
    env.globals["fail"] = _fail
    return env


def _globe_parts(assets: dict) -> str:
    return "".join(f' data-{part}-src="{assets[key]}"' for part, key in GLOBE_PARTS.items())


def globe_script(assets: dict) -> str:
    """Deferred packets are referenced local media, loaded by the bootstrap only after first paint."""
    return f'<script src="{assets["globe"]}"{_globe_parts(assets)}></script>'


def _infographic(assets: dict, key: str) -> str:
    """The content of the help text's infographic paragraph: one image per mode, CSS shows one."""
    return "\n".join(
        f'  <img class="cotw-infographic cotw-{mode}" src="{assets[f"{key}-{mode}"]}">' for mode in ("day", "night")
    )


def _fields(html: str, lang: Language) -> str:
    """``{{key}}`` → ``{{Field Name}}`` of the language. An unknown key is a template typo."""

    def name(m: re.Match) -> str:
        if m.group(2) not in FIELD_KEYS:
            raise KeyError(f"unknown field key {m.group(2)!r}")
        return "{{" + m.group(1) + lang.fields[m.group(2)] + "}}"

    return _TAG.sub(name, html)


def _context(lang: Language, assets: dict, config: dict) -> dict:
    help_text = lang.help.format(
        infographic=_infographic(assets, "infographic"),
        infographic_filtered=_infographic(assets, "infographic-filtered"),
        # A language without its own AnkiWeb listing yet links the base language's.
        ankiweb=lang.ankiweb or languages.get(languages.BASE).ankiweb,
        contact=config["contact"],
    )
    return {
        "code": lang.code,
        "ui": lang.ui,
        "comments": lang.comments,
        "assets": assets,
        "icons": ICONS,
        "symbols": SYMBOLS,
        "help_text": help_text.strip(),
        "dependency_of": lang.dependency_of.format("{{dependency_of}}"),
        "globe_parts": _globe_parts(assets),
        "globe_script": globe_script(assets),
    }


def _finish(html: str, lang: Language) -> str:
    # Blank lines and trailing spaces are left over from the Jinja tags; neither renders.
    lines = (line.rstrip() for line in html.splitlines())
    return _fields("\n".join(line for line in lines if line), lang)


def _render(name: str, lang: Language, assets: dict, config: dict, **card) -> str:
    return _finish(_env().get_template(name).render(_context(lang, assets, config), **card), lang)


def _help(lang: Language, assets: dict, config: dict) -> str:
    """The help box on its own (unindented; on a card every line after the first is indented)."""
    module = _env().get_template("macros.html").make_module(_context(lang, assets, config))
    return _finish(str(module.help()), lang)


def front(card: dict, lang: Language, assets: dict, config: dict) -> str:
    """Front: the asked attribute as "?", then the prompt. Nothing that names the entry."""
    return _render("front.html", lang, assets, config, asked=card["asked"], shown=card["shown"])


def back(card: dict, lang: Language, assets: dict, config: dict) -> str:
    """Back: answer + prompt, the globe (every back, DECISIONS B8), full info on demand."""
    asked, shown = card["asked"], card["shown"]
    rest = [a for a in ATTRIBUTES if a not in (asked, shown)]
    return _render("back.html", lang, assets, config, asked=asked, shown=shown, rest=rest)


def templates(lang_code: str, assets: dict, config: dict) -> list[dict]:
    """genanki template dicts (``name``, ``qfmt``, ``afmt``) in card-type order."""
    lang = languages.get(lang_code)
    return [
        {
            "name": lang.templates[c["key"]],
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
