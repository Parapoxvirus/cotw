"""Build one ``.apkg`` package per registered language from the database (roadmap step 4, docs/DECK.md).

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

from .. import languages, ui
from ..paths import BUILD, DATA, MEDIA, ROOT, UI_ASSETS
from .lang import CARD_TYPES, FIELD_KEYS
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
    """A name inside a sentence: the first alternative in the language's object form
    (``United States, The`` → ``the United States``, ``Niederlande`` → ``den Niederlanden``)."""
    return languages.get(lang).object_form(name.split(" / ")[0])


def tag_segment(text: str) -> str:
    return text.replace(" ", "-")


def tags(entry: dict, lang: str) -> list[str]:
    spec = languages.get(lang)
    root = spec.tag_root
    return [
        "::".join([root, *(tag_segment(spec.regions[r]) for r in entry["regions"])]),
        f"{root}::Status::{spec.status_tags[entry['status']]}",
    ]


def fields(entry: dict, by_id: dict[str, dict], lang: str) -> dict[str, str]:
    """Field values by key (``lang.FIELD_KEYS``). Text is HTML-escaped; media become ``<img>``."""
    spec = languages.get(lang)
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
    out["wikipedia"] = wiki.get(lang) or wiki[languages.BASE]
    if entry.get("dependency_of"):
        out["dependency_of"] = _esc(display_name(by_id[entry["dependency_of"]]["name"][lang], lang))
    if entry["status"] == "disputed":
        out["status"] = _esc(spec.status_disputed)
    return out


def map_field(cid: str, kind: str) -> str:
    """Both files of a map (docs/MAPS.md): an SVG in ``<img>`` cannot see Anki's night mode,
    so the card CSS shows the one that matches ``.nightMode``. Both sit in the field, since
    field-referenced media is what *Check Media* keeps."""
    return "".join(f'<img class="cotw-{mode}" src="cotw-{cid}-{kind}-{mode}.svg">' for mode in MODES)


def guid(cid: str, lang: str) -> str:
    """DECISIONS 14: derived from COTW ID + frozen language identity, stable across locale renames."""
    import genanki

    return genanki.guid_for("cotw", languages.get(lang).identity, cid)


def card_fields(entry: dict, by_id: dict, lang: str) -> dict[str, str]:
    """Field values by the language's field *names* (what the templates reference)."""
    names = languages.get(lang).fields
    return {names[k]: v for k, v in fields(entry, by_id, lang).items()}


# --- deck description ---------------------------------------------------------------------------

CITATION = (
    "Flanders Marine Institute (2023). Maritime Boundaries Geodatabase: Maritime Boundaries and "
    "Exclusive Economic Zones (200NM), version 12, and Territorial Seas (12NM), version 4. "
    'Available online at <a href="https://www.marineregions.org/">https://www.marineregions.org/</a>. '
    '<a href="https://doi.org/10.14284/632">https://doi.org/10.14284/632</a>, '
    '<a href="https://doi.org/10.14284/633">https://doi.org/10.14284/633</a>.'
)
MANIFEST_PATH = "data/derived/flags.yaml"


def description(lang: str, count: int, config: dict, asset_names: dict[str, str]) -> str:
    repository = config["repository"].rstrip("/")
    manifest = f'<a href="{repository}/blob/main/{MANIFEST_PATH}">{MANIFEST_PATH}</a>'
    text = languages.get(lang).description.format(
        count=count, repository=repository, issues=f"{repository}/issues", citation=CITATION,
        manifest=manifest, font_license=asset_names["font-license"], icons_license=asset_names["icons-license"],
    )
    return " ".join(text.split())


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

    spec = languages.get(lang)
    return genanki.Model(
        spec.notetype_id,
        spec.notetype,
        fields=[{"name": spec.fields[k], "font": "Arial"} for k in FIELD_KEYS],
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
    spec = languages.get(lang)
    table = assets(media_dir)
    asset_names = {k: name for k, (name, _) in table.items()}
    mdl = model(lang, asset_names, config)
    deck = genanki.Deck(spec.deck_id, spec.deck, description(lang, len(entries), config, asset_names))
    extras = genanki.Deck(spec.extras_deck_id, spec.extras, spec.extras_description)
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
        ids = iter(range(epoch * 1000 + spec.id_offset, epoch * 1000 + spec.id_offset + 10**6))
        genanki.Package([deck, extras]).write_to_db(cur, epoch, ids)
        extra_ords = [i for i, c in enumerate(CARD_TYPES) if c["extra"]]
        cur.execute(
            f"UPDATE cards SET did = ? WHERE ord IN ({','.join('?' * len(extra_ords))})",
            (spec.extras_deck_id, *extra_ords),
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

    Query parameters narrow it down: ``?lang=de-CH&ids=217&side=back&mode=night&types=01,05``,
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
    for lang in languages.LANGUAGES:
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
                            f'data-type="{n:02d}"><figcaption>{lang.upper()} · {html.escape(by_id[cid]["name"][languages.BASE])} · '
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
