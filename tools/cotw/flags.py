"""Flags from Wikimedia Commons, selected via Wikidata ``P41`` (flag image).

Pipeline (``python -m cotw fetch-flags``):

1. ``P41`` statements per entry are cached in ``data/wikidata/flags.json``.
2. One file is chosen per entry: the *preferred*-rank statement, otherwise the only
   normal-rank statement without an end date. Anything ambiguous needs an override.
3. The license of every file is read from the Commons API (``extmetadata``). Public
   domain / CC0 passes; everything else fails unless ``data/overrides/flags.yaml`` lists the
   entry with the file, license and a reason.
4. The SVG is downloaded, stripped of ``<title>``, ``<desc>``, ``<metadata>``, editor
   metadata and comments (they would leak the country name into the card HTML) and written
   to ``media/cotw-<id>-flag.svg``.
5. ``data/derived/flags.yaml`` records file, license, checksum and any fallback per entry.

Tests and the deck build only read the manifest and ``media/``; the network is needed to
refresh only.
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from pathlib import Path

import yaml

from . import languages
from .paths import CACHE, DERIVED, MEDIA, OVERRIDES, WIKIDATA
from .wikidata import USER_AGENT, _chunks, _qid, _sparql, _val, dump, _load

FLAGS_CACHE = WIKIDATA / "flags.json"
MANIFEST = DERIVED / "flags.yaml"
OVERRIDES_FILE = OVERRIDES / "flags.yaml"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_PREFIX = "http://commons.wikimedia.org/wiki/Special:FilePath/"
# Commons ``LicenseShortName`` values that pass without a manual decision.
ALLOWED_LICENSE_RE = re.compile(r"^(public domain|pd\b|cc0)", re.IGNORECASE)

_STRIP_ELEMENTS = ("title", "desc", "metadata", "sodipodi:namedview", "script", "foreignObject")
_STRIP_ATTRIBUTES = ("sodipodi:docname", "inkscape:export-filename", "xml:base")


# --- Wikidata --------------------------------------------------------------------------


def fetch_p41(qids: list[str]) -> dict[str, list[dict]]:
    """All ``P41`` statements per item with rank and start/end qualifiers."""
    out: dict[str, list[dict]] = {}
    for chunk in _chunks(sorted(qids), 50):
        values = " ".join(f"wd:{q}" for q in chunk)
        query = f"""
        SELECT ?item ?flag ?rank ?start ?end WHERE {{
          VALUES ?item {{ {values} }}
          ?item p:P41 ?st . ?st ps:P41 ?flag . ?st wikibase:rank ?rank .
          OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }}
        }}"""
        for b in _sparql(query):
            rec = {
                "file": commons_title(_val(b, "flag")),
                "rank": _val(b, "rank").rsplit("#", 1)[-1].lower().replace("rank", ""),
                "start": _val(b, "start"),
                "end": _val(b, "end"),
            }
            bucket = out.setdefault(_qid(_val(b, "item")), [])
            if rec not in bucket:
                bucket.append(rec)
    return {k: sorted(v, key=lambda r: (r["rank"] != "preferred", r["end"] or "", r["file"])) for k, v in sorted(out.items())}


def commons_title(uri: str) -> str:
    """``…/Special:FilePath/Flag%20of%20X.svg`` → ``Flag of X.svg``."""
    name = uri.rsplit("/", 1)[-1]
    return urllib.parse.unquote(name).replace("_", " ")


def select_file(statements: list[dict]) -> tuple[str | None, str]:
    """Pick the current flag: preferred rank wins, else the single normal-rank statement
    without an end date. Returns ``(file, reason)`` with ``file=None`` when ambiguous."""
    preferred = [s for s in statements if s["rank"] == "preferred"]
    if len(preferred) == 1:
        return preferred[0]["file"], "preferred rank"
    if len(preferred) > 1:
        return None, "several preferred-rank P41 statements: " + ", ".join(s["file"] for s in preferred)
    current = [s for s in statements if s["rank"] == "normal" and not s["end"]]
    files = sorted({s["file"] for s in current})
    if len(files) == 1:
        return files[0], "only current normal-rank statement"
    if not files:
        return None, "no current P41 statement"
    return None, "several current normal-rank P41 statements: " + ", ".join(files)


# --- Commons ----------------------------------------------------------------------------


def _get(url: str, params: dict | None = None, retries: int = 4):
    import requests  # optional dependency, only for fetching

    for attempt in range(retries):
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=120)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"{url} failed after {retries} attempts")


def fetch_imageinfo(files: list[str]) -> dict[str, dict]:
    """License, original URL and checksum per Commons file (``File:`` title without prefix)."""
    out: dict[str, dict] = {}
    for chunk in _chunks(sorted(set(files)), 50):
        resp = _get(
            COMMONS_API,
            params={
                "action": "query",
                "titles": "|".join(f"File:{f}" for f in chunk),
                "prop": "imageinfo",
                "iiprop": "extmetadata|url|size|sha1",
                "iiextmetadatafilter": "LicenseShortName|License|Artist|Credit",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
            },
        )
        data = resp.json()["query"]
        # File redirects (renamed files): map the requested title back.
        redirects = {r["to"]: r["from"] for r in data.get("redirects", [])}
        for page in data["pages"]:
            title = page["title"]
            requested = redirects.get(title, title)
            info = (page.get("imageinfo") or [None])[0]
            if page.get("missing") or not info:
                out[requested.removeprefix("File:")] = {"missing": True}
                continue
            meta = info.get("extmetadata", {})
            out[requested.removeprefix("File:")] = {
                "title": title.removeprefix("File:"),
                "license": meta.get("LicenseShortName", {}).get("value"),
                "license_template": meta.get("License", {}).get("value"),
                "url": info["url"].split("?", 1)[0],
                "page": info["descriptionurl"],
                "sha1": info["sha1"],
                "size": info["size"],
            }
    return out


def license_allowed(short_name: str | None) -> bool:
    return bool(short_name) and bool(ALLOWED_LICENSE_RE.match(short_name.strip()))


# Originals are only fetched from the Commons upload host the API points to.
UPLOAD_PREFIX = "https://upload.wikimedia.org/wikipedia/commons/"


def download(url: str, sha1: str, cache: Path = CACHE) -> Path:
    if not url.startswith(UPLOAD_PREFIX):
        raise ValueError(f"refusing to download a flag from outside Wikimedia Commons: {url}")
    if not re.fullmatch(r"[0-9a-f]{40}", sha1):
        raise ValueError(f"not a SHA-1 checksum: {sha1!r}")
    target = cache / "flags" / f"{sha1}.svg"
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    resp = _get(url)
    target.write_bytes(resp.content)
    return target


# --- SVG cleanup ------------------------------------------------------------------------


_ID_RE = re.compile(r"""\sid=(["'])(.*?)\1""")
# Namespaced editor attributes and accessibility labels: none of them draws anything, and
# several carry names ("Flag_of_…", aria-label="MAYOTTE").
_DROP_ATTR_RE = re.compile(r"""\s(?:inkscape|sodipodi|rdf|cc|dc|v|sketch|serif):[\w.-]+=(["']).*?\1|\saria-[\w-]+=(["']).*?\2""", re.DOTALL)
# Event handlers never belong in a flag (scripts are stripped as elements above).
_EVENT_ATTR_RE = re.compile(r"""\son[a-zA-Z]+=(["']).*?\1""", re.DOTALL)
_DROP_NS_RE = re.compile(r"""\sxmlns:(?:inkscape|sodipodi|rdf|cc|dc|v|sketch|serif|svg)=(["']).*?\1""")


def strip_text_metadata(svg: str) -> str:
    """Remove everything that could carry the country name without being part of the
    drawing: comments, ``<title>``, ``<desc>``, ``<metadata>``, editor blocks, editor and
    ``aria-*`` attributes. Element ids are renamed to neutral ``i0``, ``i1``, … (in order of
    appearance) and every ``href``/``url()`` reference is rewritten, so ids such as
    ``Flag_of_the_United_Kingdom`` disappear. Visible writing that is part of a flag
    (a motto drawn as paths) stays."""
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.DOTALL)
    svg = re.sub(r"<\?xml-stylesheet.*?\?>", "", svg, flags=re.DOTALL)
    for tag in _STRIP_ELEMENTS:
        svg = re.sub(rf"<{tag}\b[^>]*/>", "", svg, flags=re.DOTALL)
        svg = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}\s*>", "", svg, flags=re.DOTALL)
    for attr in _STRIP_ATTRIBUTES:
        svg = re.sub(rf'\s+{attr}="[^"]*"', "", svg)
        svg = re.sub(rf"\s+{attr}='[^']*'", "", svg)
    svg = _DROP_ATTR_RE.sub("", svg)
    svg = _EVENT_ATTR_RE.sub("", svg)
    svg = _DROP_NS_RE.sub("", svg)
    svg = rename_ids(svg)
    # Collapse the blank lines the removals leave behind so output stays tidy.
    svg = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n", svg)
    return svg.strip() + "\n"


def rename_ids(svg: str) -> str:
    mapping: dict[str, str] = {}
    for m in _ID_RE.finditer(svg):
        if m.group(2) not in mapping:
            mapping[m.group(2)] = f"i{len(mapping)}"
    if not mapping:
        return svg

    def sub_id(m: re.Match) -> str:
        return f' id="{mapping[m.group(2)]}"'

    svg = _ID_RE.sub(sub_id, svg)

    def sub_ref(m: re.Match) -> str:
        old = m.group("ref")
        return m.group(0).replace("#" + old, "#" + mapping[old]) if old in mapping else m.group(0)

    # href="#x" / xlink:href='#x' / url(#x) / url('#x') / url("#x")
    svg = re.sub(r"""(?:href=(["'])#(?P<ref>[^"']+)\1)""", sub_ref, svg)
    svg = re.sub(r"""url\(\s*["']?#(?P<ref>[^)"'\s]+)["']?\s*\)""", sub_ref, svg)
    return svg


# --- Build --------------------------------------------------------------------------------


def load_overrides(path: Path = OVERRIDES_FILE) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_manifest(path: Path = MANIFEST) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_p41() -> dict:
    return _load(FLAGS_CACHE)


def build(entries: dict, p41: dict, overrides: dict, imageinfo_fn=fetch_imageinfo, download_fn=download, media: Path = MEDIA) -> tuple[dict, list[str]]:
    """Resolve every entry to a Commons file, check licenses, write the SVGs. Returns
    ``(manifest, problems)``; problems must be empty for a clean build."""
    problems: list[str] = []
    chosen: dict[str, dict] = {}
    for cid, entry in sorted(entries.items()):
        ov = overrides.get(cid) or {}
        if ov.get("file"):
            chosen[cid] = {"file": ov["file"], "selection": f"override: {ov.get('reason', '')}".strip()}
            continue
        file, reason = select_file(p41.get(entry["wikidata"], []))
        if file is None:
            problems.append(f"{cid} {entry['name'][languages.BASE]}: {reason} (add data/overrides/flags.yaml entry)")
            continue
        chosen[cid] = {"file": file, "selection": reason}

    info = imageinfo_fn(sorted({c["file"] for c in chosen.values()}))
    manifest: dict[str, dict] = {}
    for cid, entry in sorted(entries.items()):
        if cid not in chosen:
            continue
        file = chosen[cid]["file"]
        meta = info.get(file)
        if not meta or meta.get("missing"):
            problems.append(f"{cid} {entry['name'][languages.BASE]}: Commons file not found: {file}")
            continue
        ov = overrides.get(cid) or {}
        lic = meta["license"]
        record = {
            "file": meta["title"],
            "license": lic,
            "license_template": meta["license_template"],
            "page": meta["page"],
            "sha1": meta["sha1"],
            "selection": chosen[cid]["selection"],
        }
        if not license_allowed(lic):
            if ov.get("license") == lic and ov.get("reason"):
                record["license_override"] = ov["reason"]
            else:
                problems.append(
                    f"{cid} {entry['name'][languages.BASE]}: license {lic!r} for {meta['title']} is not public domain/CC0 "
                    f"(add an override with file, license and reason)"
                )
                continue
        manifest[cid] = record

    # Dependencies whose P41 is the sovereign's flag: a documented fallback, not an error.
    for cid, record in manifest.items():
        parent = entries[cid].get("dependency_of")
        if parent and parent in manifest and manifest[parent]["sha1"] == record["sha1"]:
            record["shared_with"] = parent
            record["note"] = f"uses the flag of {entries[parent]['name'][languages.BASE]} (Wikidata P41 points to the same file)"

    if problems:
        return manifest, problems

    media.mkdir(parents=True, exist_ok=True)
    for cid, record in manifest.items():
        src = download_fn(info[chosen[cid]["file"]]["url"], record["sha1"])
        raw = src.read_bytes()
        if hashlib.sha1(raw).hexdigest() != record["sha1"]:
            problems.append(f"{cid}: checksum mismatch for {record['file']}")
            continue
        cleaned = strip_text_metadata(raw.decode("utf-8"))
        target = media / f"cotw-{cid}-flag.svg"
        target.write_text(cleaned, encoding="utf-8")
        record["bytes"] = target.stat().st_size
    return manifest, problems


def write_manifest(manifest: dict, path: Path = MANIFEST) -> None:
    header = (
        "# Flag per entry, generated by `python -m cotw fetch-flags`; do not edit by hand.\n"
        "# file/license/sha1 come from the Wikimedia Commons API (extmetadata). Allowed without an\n"
        "# override: public domain / CC0. Manual decisions live in data/overrides/flags.yaml.\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(manifest, allow_unicode=True, sort_keys=True, width=120), encoding="utf-8")


def refresh_cache(entries: dict) -> dict:
    p41 = fetch_p41(sorted({e["wikidata"] for e in entries.values()}))
    dump(FLAGS_CACHE, p41)
    return p41
