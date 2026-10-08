"""Compare two builds of the COTW packages: is the output of a refactoring unchanged?

    python tools/compare_packages.py OLD_DIR NEW_DIR [--normalize-assets] [--pair OLD=NEW ...]

Both directories hold ``COTW-<LOCALE>.apkg`` files built with the same ``SOURCE_DATE_EPOCH``.
For every package present in both (or paired with ``--pair COTW-DE.apkg=COTW-DE-CH.apkg``
when a file was renamed), the script compares:

- the ``.apkg`` SHA-256 and the zip member list;
- the media: file names and the SHA-256 of every file;
- the collection: notes (guid, mid, flds, tags, sort field), note types (id, name, css,
  template names, qfmt/afmt), decks (id, name, description) and cards (nid, ord, did).

``--normalize-assets`` replaces the content hash in template asset names
(``_cotw-globe-1a2b3c4d.js`` → ``_cotw-globe-<hash>.js``) before comparing the collection and
lists the assets whose content changed. Use it when a template asset (e.g. the globe renderer)
changed on purpose: what remains then is everything else that changed.

A differing table is detailed by its key (notes by GUID, note types and decks by ID, cards by
note and ordinal): rows only on one side, the columns that differ, and the distinct
replacements in the differing texts (``cotw-en`` → ``cotw-en-US``).

Exit code 0 when everything compared is identical, 1 otherwise. Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ASSET = re.compile(r"(_cotw-[\w-]+?)-[0-9a-f]{8}(\.\w+)")
TOKEN = re.compile(r"[^\s\"'<>=]+|.", re.S)
COLUMNS = {
    "notes": ("guid", "mid", "flds", "tags", "sfld"),
    "notetypes": ("id", "name", "css", "templates"),
    "decks": ("id", "name", "desc"),
    "cards": ("nid", "ord", "did"),
}
KEY = {"notes": 1, "notetypes": 1, "decks": 1, "cards": 2}  # leading columns that identify a row
SHOWN = 4  # replacements listed per column


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize(value, on: bool):
    if not on:
        return value
    if isinstance(value, str):
        return ASSET.sub(r"\1-<hash>\2", value)
    if isinstance(value, (list, tuple)):
        return type(value)(_normalize(v, on) for v in value)
    if isinstance(value, dict):
        return {_normalize(k, on): _normalize(v, on) for k, v in value.items()}
    return value


def read(path: Path) -> dict:
    """Everything the comparison looks at, as plain data."""
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as z:
        members = z.namelist()
        index = json.loads(z.read("media"))
        media = {name: _sha(z.read(i)) for i, name in index.items()}
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "collection.anki2"
            db.write_bytes(z.read("collection.anki2"))
            con = sqlite3.connect(db)
            try:
                notes = sorted(con.execute("SELECT guid, mid, flds, tags, sfld FROM notes"))
                cards = sorted(con.execute("SELECT nid, ord, did FROM cards"))
                models, decks = con.execute("SELECT models, decks FROM col").fetchone()
            finally:
                con.close()
    notetypes = sorted(
        (
            m["id"],
            m["name"],
            m["css"],
            tuple((t["name"], t["qfmt"], t["afmt"]) for t in m["tmpls"]),
        )
        for m in json.loads(models).values()
    )
    decks = sorted((d["id"], d["name"], d.get("desc", "")) for d in json.loads(decks).values())
    return {
        "sha256": _sha(raw),
        "members": members,
        "media": media,
        "notes": notes,
        "notetypes": notetypes,
        "decks": decks,
        "cards": cards,
    }


def _text(value) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(map(_text, value))
    return str(value)


def _diff(a: list[str], b: list[str]) -> list[tuple[list[str], list[str]]]:
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    return [(a[i1:i2], b[j1:j2]) for op, i1, i2, j1, j2 in ops if op != "equal"]


def _replacements(old, new) -> list[tuple[str, str]]:
    """The pieces of ``old`` replaced in ``new``: the differing lines, then within them the
    tokens (split at whitespace, quotes and ``<>=``)."""
    out = []
    for a, b in _diff(_text(old).splitlines(keepends=True), _text(new).splitlines(keepends=True)):
        for x, y in _diff(TOKEN.findall("".join(a)), TOKEN.findall("".join(b))):
            out.append(("".join(x), "".join(y)))
    return out


def details(table: str, x: list, y: list) -> list[str]:
    """What differs between two versions of a table, row by row on its key."""
    n = KEY[table]
    old, new = {r[:n]: r for r in x}, {r[:n]: r for r in y}
    out = []
    if old.keys() != new.keys():
        out.append(f"{table}: {len(old.keys() - new.keys())} keys only in old, {len(new.keys() - old.keys())} only in new")
    for i, column in enumerate(COLUMNS[table][n:], start=n):
        rows = [k for k in old.keys() & new.keys() if old[k][i] != new[k][i]]
        if not rows:
            continue
        found: dict[tuple[str, str], int] = {}
        for k in rows:
            for pair in _replacements(old[k][i], new[k][i]):
                found[pair] = found.get(pair, 0) + 1
        top = sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = "; ".join(f"{a!r} → {b!r} ×{c}" for (a, b), c in top[:SHOWN])
        more = f"; … {len(top) - SHOWN} more distinct" if len(top) > SHOWN else ""
        out.append(f"{table}.{column}: {len(rows)} of {len(old)} rows differ: {shown}{more}")
    return out


def compare(old: Path, new: Path, normalize: bool = False) -> list[str]:
    """Differences between two packages, one line each (empty: identical)."""
    a, b = read(old), read(new)
    out: list[str] = []
    if a["sha256"] != b["sha256"]:
        out.append(f"apkg sha256: {a['sha256']} → {b['sha256']}")
    if a["members"] != b["members"]:
        out.append(f"zip members differ: {len(a['members'])} → {len(b['members'])}")
    renamed = {}
    if normalize:  # an asset whose content changed: same name apart from the hash
        old_by, new_by = ({_normalize(n, True): n for n in m} for m in (a["media"], b["media"]))
        for key in old_by.keys() & new_by.keys():
            if old_by[key] != new_by[key]:
                renamed[old_by[key]] = new_by[key]
                out.append(f"asset changed: {old_by[key]} → {new_by[key]}")
    for name in sorted(a["media"].keys() - b["media"].keys() - renamed.keys()):
        out.append(f"media only in old: {name}")
    for name in sorted(b["media"].keys() - a["media"].keys() - set(renamed.values())):
        out.append(f"media only in new: {name}")
    for name in sorted(a["media"].keys() & b["media"].keys()):
        if a["media"][name] != b["media"][name]:
            out.append(f"media content differs: {name}")
    for table in ("notes", "notetypes", "decks", "cards"):
        x, y = _normalize(a[table], normalize), _normalize(b[table], normalize)
        if x != y:
            changed = len(set(map(repr, x)) ^ set(map(repr, y)))
            out.append(f"{table}: {len(x)} → {len(y)} rows, {changed} rows only on one side")
            out += [f"  {d}" for d in details(table, x, y)]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--normalize-assets", action="store_true", help="ignore the content hash in template asset names")
    parser.add_argument("--pair", action="append", default=[], metavar="OLD=NEW",
                        help="compare OLD (in OLD_DIR) with NEW (in NEW_DIR), for a renamed package; repeatable")
    args = parser.parse_args(argv)
    old = {p.name: p for p in args.old.glob("COTW-*.apkg")}
    new = {p.name: p for p in args.new.glob("COTW-*.apkg")}
    if not old or not new:
        print("no COTW-*.apkg in one of the directories")
        return 1
    pairs = {name: name for name in old.keys() & new.keys()}
    for pair in args.pair:
        a, _, b = pair.partition("=")
        if a not in old or b not in new:
            print(f"--pair {pair}: {a} not in {args.old} or {b} not in {args.new}")
            return 1
        pairs[a] = b
    status = 0
    for name in sorted(old.keys() - pairs.keys()) + sorted(new.keys() - set(pairs.values())):
        print(f"{name}: only in {'old' if name in old else 'new'}")
        status = 1
    for name, other in sorted(pairs.items()):
        diffs = compare(old[name], new[other], args.normalize_assets)
        info = read(new[other])
        summary = (
            f"{len(info['members'])} zip members, {len(info['media'])} media, {len(info['notes'])} notes, "
            f"{len(info['notetypes'])} note types, {len(info['decks'])} decks, {len(info['cards'])} cards"
        )
        assets_only = args.normalize_assets and all(d.startswith(("apkg sha256", "asset changed")) for d in diffs)
        verdict = "identical" if not diffs else "identical apart from changed assets" if assets_only else "DIFFERENT"
        print(f"{name}{'' if other == name else f' → {other}'}: {verdict} ({summary})")
        print(f"  old sha256 {read(old[name])['sha256']}")
        print(f"  new sha256 {info['sha256']}")
        for d in diffs:
            print(f"  {d}")
        # With normalized names, only the changed assets (and so the apkg hash) may differ.
        status |= bool(diffs) and not assets_only
    return status


if __name__ == "__main__":
    sys.exit(main())
