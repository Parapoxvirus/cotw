"""Build the EN and DE ``.apkg`` packages from the database (roadmap step 4, docs/DECK.md).

genanki writes the collection; this module adds what it lacks: cards placed per card type
(main deck vs. ``::Extras``), fixed timestamps and IDs, and a byte-reproducible zip.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from .. import ui
from ..paths import BUILD, DATA, MEDIA, ROOT, UI_ASSETS
from .lang import CARD_TYPES, DATIVE_DE, FIELD_KEYS, LANGS, REGIONS_DE
from .templates import globe_script, render, templates

UI = UI_ASSETS
STYLE_CSS = Path(__file__).with_name("style.css")
CONFIG = DATA / "deck.yaml"
MODES = ("day", "night")

# Template assets: logical name → source file. Shipped as ``_cotw-<stem>-<hash8><ext>``.
# Icons and infographics exist once per mode (``icon-country-day``, …), generated into
# media/ui/ by ``python -m cotw build-ui`` (tools/cotw/ui.py).
ASSET_SOURCES = {
    "globe": MEDIA / "_cotw-globe.js",
    "globe-zones": MEDIA / "_cotw-globe-zones.js",
    "globe-detail": MEDIA / "_cotw-globe-detail.js",
    "font": UI / "_cotw-ui-IBMPlexSans-Variable.ttf",
    "font-license": UI / "OFL-IBMPlexSans.txt",
    "icons-license": UI / "LICENSE-PhosphorIcons.txt",
    **{
        f"icon-{name}-{mode}": ui.UI_MEDIA / ui.icon_file(name, mode)
        for name in ("country", "formal", "capital", "iso", "flag", "borders", "map", "info", "help")
        for mode in MODES
    },
    **{
        f"infographic{'-filtered' if filtered else ''}-{mode}": ui.UI_MEDIA / ui.infographic_file(filtered, mode)
        for filtered in (False, True)
        for mode in MODES
    },
}
GLOBE_ASSETS = ("globe", "globe-zones", "globe-detail")
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # the earliest date a zip entry can carry


def asset_name(logical: str, path: Path) -> str:
    """``_cotw-globe-1a2b3c4d.js``: same name ⇔ same content, so no update can overwrite a file
    that an older installed package's templates still use."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    stem = path.stem.removeprefix("_").removeprefix("cotw-")
    if logical.endswith("-license"):
        stem = "ui-" + stem
    return f"_cotw-{stem}-{digest}{path.suffix}"


def assets(media_dir: Path = MEDIA) -> dict[str, tuple[str, Path]]:
    sources = {**ASSET_SOURCES, **{key: media_dir / ASSET_SOURCES[key].name for key in GLOBE_ASSETS}}
    return {k: (asset_name(k, p), p) for k, p in sources.items()}


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def build_epoch() -> int:
    """Timestamp for every note, card and note type: ``SOURCE_DATE_EPOCH``, else the commit time.

    Same commit → same package. A later commit → a newer timestamp, which is what Anki needs to
    accept an update of an already installed package (it only replaces older notes/note types).
    """
    env = os.environ.get("SOURCE_DATE_EPOCH")
    if env:
        return int(env)
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        return int(out.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise SystemExit("build-deck needs git or SOURCE_DATE_EPOCH for a reproducible timestamp") from exc


# --- note content -------------------------------------------------------------------------------


def _sort_key(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def display_name(name: str, lang: str) -> str:
    """A name inside a sentence: first alternative, ``United States, The`` → ``the United States``."""
    first = name.split(" / ")[0]
    if lang == "en" and first.endswith(", The"):
        return "the " + first[: -len(", The")]
    if lang == "de":
        return DATIVE_DE.get(first, first)
    return first


def tag_segment(text: str) -> str:
    return text.replace(" ", "-")


def tags(entry: dict, lang: str) -> list[str]:
    spec = LANGS[lang]
    regions = entry["regions"] if lang == "en" else [REGIONS_DE[r] for r in entry["regions"]]
    root = spec["tag_root"]
    return [
        "::".join([root, *(tag_segment(r) for r in regions)]),
        f"{root}::Status::{spec['status_tags'][entry['status']]}",
    ]


def fields(entry: dict, by_id: dict[str, dict], lang: str) -> dict[str, str]:
    """Field values by key (``lang.FIELD_KEYS``). Text is HTML-escaped; media become ``<img>``."""
    spec = LANGS[lang]
    cid = entry["id"]
    out = dict.fromkeys(FIELD_KEYS, "")
    out["country"] = _esc(entry["name"][lang])
    out["country_label"] = _esc((entry.get("name_label") or {}).get(lang, ""))
    out["formal_name"] = _esc((entry.get("formal_name") or {}).get(lang, ""))
    for n, cap in enumerate(entry["capitals"][:3], start=1):
        out[f"capital_{n}"] = _esc(cap["name"][lang])
        out[f"capital_{n}_label"] = _esc((cap.get("label") or {}).get(lang, ""))
    out["iso2"] = entry["iso2"]
    out["iso3"] = entry["iso3"]
    out["flag"] = f'<img src="cotw-{cid}-flag.svg">'
    out["map_1"] = map_field(cid, "map1")
    out["map_2"] = map_field(cid, "map2")
    out["locator"] = cid
    neighbors = sorted(entry["borders"], key=lambda b: _sort_key(by_id[b]["name"][lang]))
    out["borders"] = "".join(
        f'<span class="cotw-neighbor"><img src="cotw-{b}-flag.svg">{_esc(by_id[b]["name"][lang])}</span>'
        for b in neighbors
    )
    wiki = entry["wikipedia"]
    out["wikipedia"] = wiki.get(lang) or wiki["en"]
    if entry.get("dependency_of"):
        out["dependency_of"] = _esc(display_name(by_id[entry["dependency_of"]]["name"][lang], lang))
    if entry["status"] == "disputed":
        out["status"] = _esc(spec["status_disputed"])
    return out


def map_field(cid: str, kind: str) -> str:
    """Both files of a map (docs/MAPS.md): an SVG in ``<img>`` cannot see Anki's night mode,
    so the card CSS shows the one that matches ``.nightMode``. Both sit in the field, since
    field-referenced media is what *Check Media* keeps."""
    return "".join(f'<img class="cotw-{mode}" src="cotw-{cid}-{kind}-{mode}.svg">' for mode in MODES)


def guid(cid: str, lang: str) -> str:
    """DECISIONS 14: derived from COTW ID + language only, stable across all builds."""
    import genanki

    return genanki.guid_for("cotw", lang, cid)


def card_fields(entry: dict, by_id: dict, lang: str) -> dict[str, str]:
    """Field values by the language's field *names* (what the templates reference)."""
    names = LANGS[lang]["fields"]
    return {names[k]: v for k, v in fields(entry, by_id, lang).items()}


# --- deck description ---------------------------------------------------------------------------

DESCRIPTION = {
    "en": """<p><b>Countries of the World (COTW)</b>: {count} countries and territories, each with
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
    "de": """<p><b>Länder der Welt (COTW)</b>: {count} Länder und Gebiete, jeweils mit Hauptstadt,
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
}
EXTRAS_DESCRIPTION = {
    "en": "<p>The five extra card types: country → map, ISO code in both directions, bordering "
    "countries in both directions. Suspend all cards of this subdeck in the Browser to switch "
    "them off.</p>",
    "de": "<p>Die fünf zusätzlichen Kartentypen: Land → Karte, ISO-Code in beide Richtungen, "
    "Nachbarländer in beide Richtungen. Wenn du sie nicht lernen möchtest, setze alle Karten "
    "dieses Unterdecks in <i>Durchsuchen</i> aus.</p>",
}
CITATION = (
    "Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Maritime Boundaries and "
    "Exclusive Economic Zones (200NM), version 12, and Territorial Seas (12NM), version 4. "
    'Available online at <a href="https://www.marineregions.org/">https://www.marineregions.org/</a>. '
    '<a href="https://doi.org/10.14284/632">https://doi.org/10.14284/632</a>, '
    '<a href="https://doi.org/10.14284/633">https://doi.org/10.14284/633</a>.'
)
MANIFEST_PATH = "data/derived/flags.yaml"


def description(lang: str, count: int, config: dict, asset_names: dict[str, str]) -> str:
    repo = (config.get("repository") or "").rstrip("/")
    manifest = f'<a href="{repo}/blob/main/{MANIFEST_PATH}">{MANIFEST_PATH}</a>' if repo else f"<code>{MANIFEST_PATH}</code>"
    return " ".join(
        DESCRIPTION[lang]
        .format(count=count, citation=CITATION, manifest=manifest, font_license=asset_names["font-license"],
                icons_license=asset_names["icons-license"])
        .split()
    )


# --- package ------------------------------------------------------------------------------------


@dataclass
class Built:
    lang: str
    path: Path
    notes: int
    cards: int
    media: list[str]


def css(asset_names: dict[str, str]) -> str:
    return STYLE_CSS.read_text(encoding="utf-8").replace("@@font@@", asset_names["font"])


def model(lang: str, asset_names: dict[str, str], config: dict):
    import genanki

    spec = LANGS[lang]
    return genanki.Model(
        spec["notetype_id"],
        spec["notetype"],
        fields=[{"name": spec["fields"][k], "font": "Arial"} for k in FIELD_KEYS],
        templates=templates(lang, asset_names, config),
        css=css(asset_names),
        sort_field_index=0,
    )


def field_media(entries: list[dict], media_dir: Path = MEDIA) -> list[Path]:
    """Every file the entries' fields reference: flag and both map files per entry, plus the
    flags of their neighbors (the borders field shows them, also for neighbors outside a
    ``--only`` subset)."""
    kinds = ["flag"] + [f"{k}-{m}" for k in ("map1", "map2") for m in MODES]
    ids = {e["id"] for e in entries}
    files = [media_dir / f"cotw-{e['id']}-{kind}.svg" for e in entries for kind in kinds]
    neighbors = sorted({b for e in entries for b in e.get("borders", [])} - ids)
    return files + [media_dir / f"cotw-{b}-flag.svg" for b in neighbors]


def _write_zip(target: Path, collection: Path, media: list[tuple[str, Path]]) -> None:
    """Deterministic zip: fixed entry dates and order, one compression setting."""
    tmp = target.with_suffix(".apkg.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:

        def put(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data, compresslevel=9)

        put("collection.anki2", collection.read_bytes())
        put("media", json.dumps({str(i): name for i, (name, _) in enumerate(media)}, ensure_ascii=False).encode())
        for i, (_, path) in enumerate(media):
            put(str(i), path.read_bytes())
    tmp.replace(target)


def build_package(
    lang: str,
    entries: list[dict],
    by_id: dict[str, dict],
    out_dir: Path,
    epoch: int,
    config: dict | None = None,
    media_dir: Path = MEDIA,
) -> Built:
    import genanki

    config = config or load_config()
    spec = LANGS[lang]
    table = assets(media_dir)
    asset_names = {k: name for k, (name, _) in table.items()}
    mdl = model(lang, asset_names, config)
    deck = genanki.Deck(spec["deck_id"], spec["deck"], description(lang, len(entries), config, asset_names))
    extras = genanki.Deck(spec["extras_deck_id"], spec["extras"], EXTRAS_DESCRIPTION[lang])
    for position, e in enumerate(sorted(entries, key=lambda x: x["id"])):
        values = fields(e, by_id, lang)
        note = genanki.Note(
            model=mdl,
            fields=[values[k] for k in FIELD_KEYS],
            tags=tags(e, lang),
            guid=guid(e["id"], lang),
            due=position,
        )
        deck.add_note(note)

    media = sorted(
        [(p.name, p) for p in field_media(entries, media_dir)] + [(name, path) for name, path in table.values()],
        key=lambda t: t[0],
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"COTW-{lang.upper()}.apkg"
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "collection.anki2"
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        ids = iter(range(epoch * 1000 + spec["id_offset"], epoch * 1000 + spec["id_offset"] + 10**6))
        genanki.Package([deck, extras]).write_to_db(cur, epoch, ids)
        extra_ords = [i for i, c in enumerate(CARD_TYPES) if c["extra"]]
        cur.execute(
            f"UPDATE cards SET did = ? WHERE ord IN ({','.join('?' * len(extra_ords))})",
            (spec["extras_deck_id"], *extra_ords),
        )
        _fix_collection(cur, epoch)
        conn.commit()
        (n_notes,) = cur.execute("SELECT count(*) FROM notes").fetchone()
        (n_cards,) = cur.execute("SELECT count(*) FROM cards").fetchone()
        conn.execute("VACUUM")
        conn.close()
        _write_zip(target, db, media)
    return Built(lang, target, n_notes, n_cards, [name for name, _ in media])


def _fix_collection(cur, epoch: int) -> None:
    """Pin the collection-level timestamps genanki leaves at its own constants or ``now``."""
    decks = json.loads(cur.execute("SELECT decks FROM col").fetchone()[0])
    for d in decks.values():
        d["mod"] = epoch
    cur.execute("UPDATE col SET decks = ?, mod = ?, crt = ?", (json.dumps(decks, sort_keys=True), epoch * 1000, epoch))


# --- entry points -------------------------------------------------------------------------------


def load_entries() -> tuple[list[dict], dict[str, dict]]:
    from .. import schema

    entries = list(schema.load_all().values())
    return entries, {e["id"]: e for e in entries}


def select(by_id: dict[str, dict], only: list[str]) -> list[dict]:
    """``--only``: COTW IDs (``184``) or ISO-2 codes (``RU``, any case), comma- or
    space-separated, in any mix. Unknown tokens raise ``ValueError``."""
    by_iso = {e["iso2"].upper(): cid for cid, e in by_id.items()}
    picked, unknown = [], []
    for token in (t for item in only for t in item.replace(",", " ").split()):
        cid = token if token in by_id else by_iso.get(token.upper())
        if cid is None:
            unknown.append(token)
        elif cid not in picked:
            picked.append(cid)
    if unknown:
        raise ValueError(f"unknown COTW IDs / ISO-2 codes: {', '.join(unknown)}")
    if not picked:
        raise ValueError("--only selected nothing")
    return [by_id[cid] for cid in sorted(picked)]


def build(langs: list[str], out_dir: Path = BUILD, epoch: int | None = None, only: list[str] | None = None) -> list[Built]:
    """One package per language. ``only`` limits the notes to a subset (``select``); IDs,
    GUIDs, note types and decks are those of the full build, the neighbors' names and flags
    stay in the borders field, and the globe is the whole world."""
    entries, by_id = load_entries()
    if only:
        entries = select(by_id, only)
    epoch = build_epoch() if epoch is None else epoch
    config = load_config()
    return [build_package(lang, entries, by_id, out_dir, epoch, config) for lang in langs]


# --- preview ------------------------------------------------------------------------------------

PREVIEW_IDS = ("217", "087", "207", "026", "098")  # CH, GL (dependency), ZA + BO (capitals), VA
PREVIEW_MEDIA = "deck-media"


def write_preview(out_dir: Path = BUILD, ids: tuple[str, ...] = PREVIEW_IDS) -> Path:
    """``build/deck-preview.html``: every card type, front and back, day and night, per language.

    Query parameters narrow it down: ``?lang=de&ids=217&side=back&mode=night&types=01,05``,
    ``&open=info,help`` expands the full info / help sections.
    """
    entries, by_id = load_entries()
    config = load_config()
    table = assets()
    names = {k: n for k, (n, _) in table.items()}
    media_dir = out_dir / PREVIEW_MEDIA
    media_dir.mkdir(parents=True, exist_ok=True)
    for name, path in table.values():
        shutil.copyfile(path, media_dir / name)
    for path in field_media([by_id[i] for i in by_id]):
        shutil.copyfile(path, media_dir / path.name)

    cards = []
    for lang in LANGS:
        tmpls = templates(lang, names, config)
        for cid in ids:
            values = card_fields(by_id[cid], by_id, lang)
            for n, (card, t) in enumerate(zip(CARD_TYPES, tmpls), start=1):
                for side, tmpl in (("front", t["qfmt"]), ("back", t["afmt"])):
                    body = render(tmpl, values)
                    if not body.strip():
                        continue  # no card (no land borders)
                    body = body.replace(globe_script(names), "")
                    for mode in ("day", "night"):
                        night = " nightMode night_mode" if mode == "night" else ""
                        cards.append(
                            f'<figure data-lang="{lang}" data-id="{cid}" data-side="{side}" data-mode="{mode}" '
                            f'data-type="{n:02d}"><figcaption>{lang.upper()} · {html.escape(by_id[cid]["name"]["en"])} · '
                            f'{html.escape(t["name"])} · {side} · {mode}</figcaption>'
                            f'<div class="card{night}">{body}</div></figure>'
                        )
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>COTW deck preview</title>
<base href="{PREVIEW_MEDIA}/">
<style>{css(names)}</style>
<style>
body {{ margin: 0; padding: 16px; background: #1b1b1b; font: 13px system-ui, sans-serif; color: #ccc; }}
main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 16px; align-items: start; }}
figure {{ margin: 0; }}
figcaption {{ padding: 4px 0; }}
figure .card {{ padding: 16px 10px; border-radius: 6px; }}
</style></head>
<body><main>
{''.join(cards)}
</main>
<script>
(function () {{
  var q = new URLSearchParams(location.search);
  var keep = {{ lang: q.get('lang'), id: q.get('ids'), side: q.get('side'), mode: q.get('mode'), type: q.get('types') }};
  document.querySelectorAll('figure').forEach(function (f) {{
    for (var k in keep) {{
      if (keep[k] && keep[k].split(',').indexOf(f.dataset[k]) < 0) {{ f.remove(); return; }}
    }}
  }});
  var open = (q.get('open') || '').split(',');
  document.querySelectorAll('.cotw').forEach(function (c) {{
    if (open.indexOf('info') >= 0) c.classList.add('cotw-show-info');
    if (open.indexOf('help') >= 0) c.classList.add('cotw-show-help');
  }});
  if (q.get('w')) document.querySelector('main').style.gridTemplateColumns = 'repeat(auto-fill, ' + q.get('w') + 'px)';
}})();
</script>
{globe_script(names)}
</body></html>
"""
    target = out_dir / "deck-preview.html"
    target.write_text(page, encoding="utf-8")
    return target
